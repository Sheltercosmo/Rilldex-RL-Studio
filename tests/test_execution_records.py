import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tracker import execution_records as execution, capture_bundle
from tracker.analytics import Analysis
from tracker.analysis_mirror import FeedMirror
from tracker.capture import Outbox
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict


def record(identifier='episode',revision=0,state='queued',kind='rollout',**extra):
    return dict(id=identifier,revision=revision,kind=kind,
        rollout=dict(producer='orchestrator',id='episode'),state=state,
        context=dict(environment='terminal',environment_version='v1'),
        evidence='Authored test native lifecycle report',**extra)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'workspace.sqlite');self.data=Analysis(self.store.path)

    def packet(self,records,producer='worker',experiment='mixed'):
        return dict(schema=execution.VERSION,producer=producer,experiment=experiment,records=records)

    def receive(self,*rows,**options):return execution.receive(self.store,self.packet(list(rows),**options))

    def test_reverse_revisions_and_retries_preserve_latest(self):
        final=record(revision=2,state='completed',metrics={'duration_ms':0})
        self.receive(final);self.receive(record());self.receive(record(revision=1,state='running'))
        self.assertEqual(self.receive(final)['inserted'],0)
        rows=self.data.table('executions')['rows'];self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['revision'],rows[0]['state'],rows[0]['duration_ms']),(2,'completed',0))
        self.assertEqual(len(self.data.table('executions',history=True)['rows']),3)
        self.assertEqual(self.data.options(history=True)['experiments'][0]['execution_attempts'],1)
        self.assertEqual(self.data.table('rollouts')['rows'],[])

    def test_conflicting_revisions_roll_back_whole_packet(self):
        self.receive(record(revision=1,state='running'))
        with self.assertRaises(ReviewConflict):self.receive(record('other'),record(revision=1,state='failed'))
        self.assertEqual(len(self.data.table('executions')['rows']),1)
        with self.assertRaises(ReviewConflict):self.receive(record(revision=2))
        self.receive(record(revision=3,state='completed'))
        with self.assertRaises(ReviewConflict):self.receive(record(revision=4,state='running'))

    def test_mixed_servers_need_distinct_attempts_and_can_report_before_parent(self):
        first=record('call-a',1,'failed','inference',parent={'producer':'controller','id':'root'})
        first['context'].update(backend='vllm',server='a',model='policy',policy_version='12')
        self.receive(first)
        changed=copy.deepcopy(first);changed['revision']=2;changed['context']['backend']='sglang'
        with self.assertRaises(ReviewConflict):self.receive(changed)
        second=record('call-b',0,'running','inference',parent=first['parent'],retry_of={'producer':'worker','id':'call-a'})
        second['context'].update(backend='sglang',server='b',model='policy',policy_version='13')
        self.receive(second)
        self.receive(record('root'),producer='controller')
        result=self.data.execution_summary(experiment='mixed',kind='inference',group_by=['backend','model','policy_version'])
        self.assertEqual(len(result['groups']),2)
        self.assertEqual(sum(g['explicit_retry_attempts'] for g in result['groups']),1)

    def test_context_can_be_added_but_not_lost_or_reassigned(self):
        queued=record('call',0,kind='inference');self.receive(queued)
        running=copy.deepcopy(queued);running.update(revision=1,state='running');running['context']['server']='instance-a'
        self.receive(running)
        missing=copy.deepcopy(queued);missing.update(revision=2,state='completed')
        with self.assertRaises(ReviewConflict):self.receive(missing)
        self.assertEqual(self.receive(queued)['inserted'],0)

    def test_completion_mix_retains_stragglers_and_latency_missingness(self):
        self.receive(record('fast',1,'completed',metrics={'duration_ms':10,'queue_ms':0}))
        slow=record('slow',1,'running',metrics={'elapsed_ms':1000});slow['context']['environment']='browser'
        unknown=record('unmeasured',1,'completed');unknown['context']['environment']='browser'
        self.receive(slow,unknown)
        summary=self.data.execution_summary(experiment='mixed');groups={g['context']['environment']:g for g in summary['groups']}
        self.assertEqual(groups['browser']['unfinished'],1)
        self.assertEqual(groups['browser']['completed_duration_ms'],dict(measured=0,eligible=1,p50=None,p95=None,max=None))
        self.assertAlmostEqual(groups['terminal']['completion_mix_shift'],.5-1/3)
        self.assertEqual(groups['terminal']['queue_ms']['p50'],0)
        with self.assertRaises(InputError):self.data.execution_summary(experiment='mixed',limit=1)
        self.assertEqual(self.data.execution_summary(experiment='absent')['observed_attempts'],0)

    def test_scope_and_identity_do_not_depend_on_worker_local_ids(self):
        self.receive(record());self.receive(record(),producer='second-worker');self.receive(record(),experiment='other')
        self.assertEqual(len(self.data.table('executions',experiment='mixed')['rows']),2)
        self.assertEqual(self.data.options()['experiments'],[
            dict(experiment='mixed',snapshots=0,execution_attempts=2),dict(experiment='other',snapshots=0,execution_attempts=1)])
        summary=self.data.execution_summary(experiment='mixed',group_by=['backend'])
        self.assertIsNone(summary['groups'][0]['context']['backend'])

    def test_bad_values_and_ambiguous_latency_rejected(self):
        for extra in [dict(metrics={'duration_ms':1}),dict(metrics={'elapsed_ms':float('nan')}),
                      dict(metrics={'queue_ms':-1}),dict(metrics={'output_tokens':1.5}),
                      dict(observed_at='2026-10-15T00:00:00'),dict(source_revision=True),
                      dict(parent={'producer':'worker','id':'episode'})]:
            with self.assertRaises(InputError):self.receive(record(**extra))
        with self.assertRaises(InputError):self.receive(record(),record())
        with self.assertRaises(InputError):self.data.execution_summary(experiment='mixed',group_by=['not_a_column'])

    def test_default_groups_do_not_pool_training_evaluation_or_model_roles(self):
        for i,(split,role) in enumerate([('train','actor'),('evaluation','actor'),('train','verifier')]):
            r=record(str(i),1,'completed');r['context'].update(split=split,model_role=role)
            self.receive(r)
        summary=self.data.execution_summary(experiment='mixed')
        self.assertEqual(len(summary['groups']),3)
        self.assertEqual({(g['context']['split'],g['context']['model_role']) for g in summary['groups']},
            {('train','actor'),('evaluation','actor'),('train','verifier')})

    def test_feed_mirror_and_exports_keep_out_of_order_facts(self):
        self.receive(record(revision=3,state='completed'));first=self.data.changes('executions',limit=1)
        self.receive(record());later=self.data.changes('executions',cursor=first['next_cursor'])
        self.assertEqual(later['rows'][0]['document']['revision'],0)
        mirror=FeedMirror(self.data,self.root/'mirror.sqlite')
        self.assertEqual(mirror.sync(feeds=['executions'])['feeds'][0]['inserted'],2)
        self.assertEqual(mirror.sync(feeds=['executions'])['feeds'][0]['inserted'],0)
        manifest=self.data.export(self.root/'export.zip',tables=['executions'],experiment='mixed')
        self.assertTrue(manifest['tables']['executions']['available'])
        self.assertEqual(manifest['tables']['executions']['rows'],1)
        frozen=self.root/'frozen.sqlite';self.data.database(frozen)
        self.assertEqual(Analysis(frozen).execution_summary(experiment='mixed')['observed_attempts'],1)

    def test_older_workspace_and_snapshot_are_available_without_fake_zero_metrics(self):
        with self.store.connect() as c:c.execute('DROP TABLE execution_records')
        self.assertFalse(self.data.table('executions')['available'])
        self.assertNotIn('executions',self.data.catalog()['feeds'])
        with self.assertRaises(InputError):self.data.changes('executions')
        with self.assertRaises(InputError):self.data.execution_summary(experiment='mixed')
        mirror=FeedMirror(self.data,self.root/'mirror.sqlite');mirror.sync()
        frozen=self.root/'frozen.sqlite';manifest=self.data.database(frozen)
        self.assertFalse(manifest['tables']['executions']['included'])
        with self.assertRaises(InputError):Analysis(frozen).execution_summary(experiment='mixed')
        self.assertFalse(Analysis(frozen).table('executions')['available'])

    def test_offline_bundle_delivery_and_acknowledgment(self):
        box=Outbox(self.root/'worker.sqlite',producer='worker')
        box.log_execution('mixed',[record(revision=2,state='completed')])
        box.log_execution('mixed',[record()])
        path=self.root/'packets.zip';capture_bundle.export(box.path,path)
        self.assertEqual(capture_bundle.inspect(path)['kinds'],{'execution_records':2})
        receipts=capture_bundle.receive(self.store,path,with_receipts=True)
        self.assertTrue(receipts['complete']);self.assertEqual(receipts['accepted'],2)
        self.assertEqual(capture_bundle.receive(self.store,path)['already_present'],2)
        acknowledgment=self.root/'receipts.json';acknowledgment.write_text(json.dumps(
            dict(schema='jev-capture-receipts/1',acknowledgments=receipts['acknowledgments'])))
        capture_bundle.acknowledge(box.path,acknowledgment)
        self.assertEqual(box.status()['sent'],2)

    def test_distributed_contract_is_bundled_for_installed_users(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual((root/'docs/DISTRIBUTED_RL.md').read_bytes(),(root/'tracker/web/execution-guide.md').read_bytes())


if __name__=='__main__':unittest.main()
