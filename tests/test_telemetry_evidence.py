import io
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from rilldex import Outbox, TrainerTelemetry, chat_document, Workspace
from tracker import trainer_telemetry as t, telemetry_evidence as evidence
from tracker import training_lineage, investigation_workspace, failure_investigations, capture_bundle
from tracker.schema import InputError
from tracker.store import Store
from tracker.telemetry_cli import run as import_logs


class TelemetryEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.store=Store(self.root/'workspace.sqlite')
        self.config=dict(experiment='run',producer='learner',framework='verl',framework_version='test',objective='gspo/control',session='start-1')
        self.logger=TrainerTelemetry(self.store,**self.config)

    def source(self,name,step,revision=0):
        return self.store.ingest(dict(producer='actor',rollout_id=name,revision=revision,state='complete',
            document=chat_document([dict(role='assistant',content='Attempt '+name)],success=True),
            metadata=dict(experiment='run',training_step=step,training_clock='policy',training_step_basis='generation')))['id']

    def use(self,name,source_revision=0,producer='learner'):
        records=[dict(id='sample-'+name,revision=0,kind='sample',sample=dict(producer='actor',rollout_id=name),
                      evidence=dict(source_revision=source_revision,basis='source capture'),data=dict(split='train')),
                 dict(id='use-'+name,revision=0,kind='use',sample=dict(producer='actor',rollout_id=name),
                      evidence=dict(basis='native learner'),data=dict(stage='optimizer_step_completed',learner_step=700,batch_id='batch'))]
        training_lineage.receive(self.store,dict(schema='training-records/1',producer=producer,experiment='run',records=records))
        return dict(producer=producer,id='use-'+name,revision=0)

    def refs(self,*refs,coverage='complete'):
        return dict(records=list(refs),coverage=coverage,basis='Producer-recorded log context')

    def save(self,**kwargs):
        return investigation_workspace.save(self.store,dict(experiment='run',baseline=[0,0],current=[1,1],monitor_ids=[],**kwargs))

    def test_exact_uses_join_different_clocks_not_equal_numbers(self):
        a=self.source('a',1);ref=self.use('a')
        self.logger.log({'actor/pg_loss':.3},step=700,record_id='linked',training_uses=self.refs(ref))
        self.logger.log({'actor/pg_loss':9},step=1,record_id='unlinked')
        data=self.save()['snapshot']['native_telemetry']
        self.assertEqual(len(data['records']),1);r=data['records'][0]
        self.assertEqual((r['record']['step'],r['windows'],r['run_ids']),(700,['current'],[a]))
        self.assertEqual(data['unlinked_logs'],1)
        self.assertEqual(data['referenced_selected_uses'],1)
        point=evidence.evidence(self.store,producer='learner',experiment='run',record_id='linked')
        self.assertEqual(point['run_ids'],[a]);self.assertEqual(point['references'][0]['matches'][0]['use_record']['id'],ref['id'])
        self.assertEqual(Workspace(self.store.path,experiment='run').telemetry_evidence(producer='learner',record_id='linked'),point)

    def test_mixed_partial_batch_is_retained_once_without_conditional_mean(self):
        a=self.source('a',0);b=self.source('b',1);refs=[self.use('a'),self.use('b'),dict(producer='missing',id='use',revision=0)]
        self.logger.log({'actor/pg_loss':.8,'perf/total_num_tokens':2000},step=700,training_uses=self.refs(*refs,coverage='partial'))
        data=self.save()['snapshot']['native_telemetry'];self.assertEqual(len(data['records']),1)
        r=data['records'][0];self.assertEqual(r['windows'],['baseline','current'])
        self.assertEqual((r['matched_uses'],r['declared_uses'],r['unmatched_uses']),(2,3,1))
        self.assertNotIn('delta',r);self.assertEqual(r['record']['metrics']['actor/pg_loss']['value'],.8)
        self.assertEqual(set(r['run_ids']),{a,b})

    def test_late_source_and_receipt_require_new_frozen_capture(self):
        self.source('a',1)
        ref=dict(producer='learner',id='use-a',revision=0)
        self.logger.log({'actor/pg_loss':.4},step=700,record_id='before-use',training_uses=self.refs(ref))
        old=self.save();self.assertEqual(old['snapshot']['native_telemetry']['records'],[])
        self.use('a');new=self.save(parent_id=old['id'])
        self.assertEqual(len(new['snapshot']['native_telemetry']['records']),1)
        self.assertEqual(failure_investigations.read(self.store,old['id']),old)

    def test_producer_revision_and_experiment_mismatches_do_not_join(self):
        self.source('a',1);ref=self.use('a',source_revision=1)
        self.logger.log({'actor/pg_loss':.2},step=1,record_id='wrong-source',training_uses=self.refs(ref))
        self.assertEqual(self.save()['snapshot']['native_telemetry']['records'],[])
        self.source('b',1);refb=self.use('b')
        self.logger.log({'actor/pg_loss':.3},step=1,record_id='wrong-writer',training_uses=self.refs({**refb,'producer':'other'}))
        TrainerTelemetry(self.store,**{**self.config,'experiment':'other'}).log({'loss':4},step=1,training_uses=self.refs(refb))
        self.assertEqual(self.save()['snapshot']['native_telemetry']['records'],[])

    def test_reference_contract_and_legacy_transport(self):
        old=t.packet({'loss':1},step=0,**self.config);self.assertEqual(old['schema'],t.VERSION)
        ref=dict(producer='learner',id='use',revision=0)
        for links in (self.refs(ref,ref),self.refs({**ref,'revision':1}),self.refs(),dict(coverage=[],basis='x',records=[ref])):
            with self.assertRaises(InputError):t.packet({'loss':1},step=0,training_uses=links,**self.config)
        linked=t.packet({'loss':1},step=0,training_uses=self.refs(ref),**self.config)
        self.assertEqual(linked['schema'],t.LINKED_VERSION)
        with self.assertRaises(InputError):t.validate({**linked,'schema':t.VERSION})
        box=Outbox(self.root/'out.sqlite',producer='learner')
        TrainerTelemetry(box,**self.config).log({'loss':1},step=0,training_uses=self.refs(ref))
        capture_bundle.export(box.path,self.root/'bundle.zip');capture_bundle.receive(self.store,self.root/'bundle.zip')
        with patch('tracker.capture.urlopen',side_effect=lambda req,**kw:io.BytesIO(json.dumps(t.receive(self.store,json.loads(req.data))).encode())):
            self.assertEqual(box.drain()['sent_now'],1)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM trainer_telemetry_uses').fetchone()[0],1)

    def test_independent_samples_bind_only_their_recorded_source(self):
        rid=self.source('episode',1)
        sample=dict(producer='generator',id='independent-sample')
        records=[dict(id='independent-declaration',revision=0,kind='sample',sample=sample,evidence=dict(basis='export'),
                      data=dict(split='train',source=dict(producer='actor',rollout_id='episode',revision=0))),
                 dict(id='independent-use',revision=0,kind='use',sample=sample,evidence=dict(basis='learner'),
                      data=dict(stage='backward_completed',learner_step=91,batch_id='packed-batch'))]
        training_lineage.receive(self.store,dict(schema='training-records/2',producer='learner',experiment='run',records=records))
        self.logger.log({'actor/pg_loss':.6},step=91,training_uses=self.refs(dict(producer='learner',id='independent-use',revision=0)))
        logs=self.save()['snapshot']['native_telemetry']['records']
        self.assertEqual(logs[0]['run_ids'],[rid])
        self.assertEqual(logs[0]['references'][0]['matches'][0]['stage'],'backward_completed')

    def test_bounded_capture_and_python_access_preserve_links(self):
        self.source('a',1);ref=self.use('a')
        for step in range(3):self.logger.log({'actor/pg_loss':.2},step=step+700,training_uses=self.refs(ref))
        saved=self.save();lineage=saved['snapshot']['training_lineage']
        bounded=evidence.capture(self.store,experiment='run',lineage=lineage,limit=1)
        self.assertTrue(bounded['truncated']);self.assertEqual(len(bounded['records']),1)
        row=Workspace(self.store.path,experiment='run').telemetry().rows[0]
        self.assertEqual(row['record']['training_uses']['records'],[ref])

    def test_jsonl_references_need_explicit_split_and_survive_import(self):
        ref=dict(producer='learner',id='use',revision=0);file=self.root/'logs.jsonl'
        args=SimpleNamespace(db=str(self.store.path),telemetry_command='import',path=str(file),definitions=None,
            clock='learner_update',population='native batch',environment='unspecified',split='train',**self.config)
        row=dict(step=7,metrics={'actor/pg_loss':.3},training_uses=self.refs(ref))
        file.write_text(json.dumps(row));
        with self.assertRaises(InputError):import_logs(args)
        file.write_text(json.dumps({**row,'split':'train'}));self.assertEqual(import_logs(args)['imported'],1)
        self.assertEqual(import_logs(args)['imported'],0)
        self.assertEqual(Workspace(self.store.path).telemetry().rows[0]['record']['training_uses']['records'],[ref])

    def test_explicit_evaluation_import_retains_split_for_unprefixed_trl_logs(self):
        file=self.root/'eval.jsonl'
        file.write_text(json.dumps(dict(step=8,loss=.4,entropy=.8)),encoding='utf-8')
        args=SimpleNamespace(db=str(self.store.path),telemetry_command='import',path=str(file),definitions=None,
            clock='evaluation_step',population='evaluation batch',environment='unspecified',split='evaluation',
            **{**self.config,'framework':'trl-grpo'})
        self.assertEqual(import_logs(args)['imported'],1)
        rows=Workspace(self.store.path).telemetry().rows
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['record']['split'],'evaluation')
        self.assertEqual(rows[0]['record']['metrics']['loss']['value'],.4)

    def test_readonly_legacy_database_reports_missing_telemetry(self):
        with self.store.connect() as c:
            c.execute('DROP TABLE trainer_telemetry_uses')
            c.execute('DROP TABLE trainer_telemetry')
        with self.assertRaisesRegex(InputError,'no native trainer logs'):
            Workspace(self.store.path,experiment='run').telemetry_evidence(producer='learner',record_id='old')


if __name__=='__main__':unittest.main()
