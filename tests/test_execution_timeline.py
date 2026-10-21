"""Execution/sample/telemetry joins with actual transport and saved snapshots."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from rilldex import ExecutionRecorder, Outbox, TrainerTelemetry, Workspace, chat_document
from tracker import execution_records as execution, execution_timeline as timeline, training_lineage, capture_bundle
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict


class ExecutionTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'workspace.sqlite')
        self.logger=TrainerTelemetry(self.store,producer='learner',experiment='run',framework='verl',
            framework_version='test',objective='authored',session='start')

    def put(self,*records,producer='worker',schema=execution.TIMELINE_VERSION):
        return execution.receive(self.store,dict(schema=schema,experiment='run',producer=producer,records=list(records)))

    def span(self,identifier='request',kind='inference',revision=1,state='completed',start=0,end=10,clock='job/utc',**extra):
        return dict(id=identifier,kind=kind,revision=revision,state=state,
            rollout=None if kind in execution.KINDS[4:] else dict(producer='actor',id='episode'),
            context=dict(worker='sampler 1'),evidence='Authored test boundaries',
            timing=dict(clock=clock,start=start,end=end)) | extra

    def sample(self,delivered=True):
        run=None
        if delivered:
            run=self.store.ingest(dict(producer='actor',rollout_id='episode',revision=0,state='complete',
                document=chat_document([dict(role='assistant',content='Inspect, change, then verify.')],success=True),
                metadata={'experiment':'run'}))['id']
        clock=dict(schema='policy-clock/1',clock='weights',unit='policy_publication',index=3)
        records=[dict(id='sample',revision=0,kind='sample',sample=dict(producer='actor',rollout_id='episode'),
            evidence=dict(source_revision=0,basis='native sample'),data=dict(split='train',
            policy_history=dict(schema='generation-policy-history/1',token_count=4,segments=[dict(start=0,end=4,policy=clock)]))),
            dict(id='use',revision=0,kind='use',sample=dict(producer='actor',rollout_id='episode'),evidence=dict(basis='native use'),
                 data=dict(stage='optimizer_step_completed',batch_id='batch-90',learner_step=90,model_tokens=4,learner_policy={**clock,'index':6}))]
        training_lineage.receive(self.store,dict(schema='training-records/1',producer='learner',experiment='run',records=records))
        return run

    def log(self):
        self.logger.log({'actor/pg_loss':.2,'actor/grad_norm':3},step=90,record_id='log',training_uses=dict(
            coverage='complete',basis='actual batch members',records=[dict(producer='learner',id='use',revision=0)]))

    def test_reverse_delivery_exact_links_and_policy_age(self):
        final=self.span(source_revision=0)
        self.put(final);self.put(self.span(revision=0,state='running',end=None))
        self.put(self.span('update',kind='learner_update',start=11,end=12,telemetry=[dict(producer='learner',id='log')]))
        missing=timeline.snapshot(self.store,experiment='run')
        self.assertEqual(len(missing['missing_logs']),1)
        self.sample();self.log()
        result=timeline.snapshot(self.store,experiment='run',clock='job/utc')
        self.assertEqual(len(result['executions']),2)
        self.assertEqual(result['logs'][0]['record']['step'],90)
        self.assertEqual(result['logs'][0]['policy_age']['clocks'][0]['mean_age'],3)
        self.assertTrue(result['samples'][0]['run_id'])
        self.assertEqual(result['logs'][0]['sample_ids'],[result['samples'][0]['id']])
        self.assertEqual(Workspace(self.store.path,experiment='run').execution_view(clock='job/utc')['snapshot_id'],result['snapshot_id'])

    def test_late_sources_do_not_change_saved_view(self):
        self.sample(False);self.log()
        self.put(self.span(kind='learner_update',telemetry=[dict(producer='learner',id='log')]))
        frozen=timeline.save(self.store,experiment='run',clock='job/utc')
        self.assertIsNone(frozen['samples'][0]['run_id'])
        self.sample(True)
        self.assertTrue(timeline.snapshot(self.store,experiment='run')['samples'][0]['run_id'])
        self.assertEqual(timeline.load(self.store,frozen['saved']),frozen)
        self.assertEqual(Workspace(self.store.path,experiment='run').execution_view(saved=frozen['saved']),frozen)

    def test_clocks_ranges_and_missing_times_are_not_inferred(self):
        self.put(self.span(),self.span('foreign',clock='other',start=500,end=510))
        old=self.span('legacy');old.pop('timing');self.put(old,schema=execution.VERSION)
        selected=timeline.snapshot(self.store,experiment='run',clock='job/utc',start=2,end=5)
        self.assertEqual(len(selected['executions']),1)
        self.assertEqual({c['clock'] for c in selected['clocks']},{None,'job/utc','other'})
        self.assertEqual(timeline.snapshot(self.store,experiment='run',clock='job/utc',start=11)['executions'],[])
        for kwargs in [dict(start=1),dict(clock='job/utc',start=5,end=1),dict(clock='job/utc',end=float('nan'))]:
            with self.assertRaises(InputError):timeline.snapshot(self.store,experiment='run',**kwargs)

    def test_terminal_timing_config_and_reference_conflicts(self):
        record=self.span(configuration={'precision':'bf16'},telemetry=[dict(producer='learner',id='log')]);self.put(record)
        for patch in [dict(timing=dict(clock='other',start=0,end=10)),dict(timing=dict(clock='job/utc',start=0,end=11)),
                      dict(configuration={'precision':'fp4'}),dict(telemetry=[])]:
            with self.subTest(patch=patch),self.assertRaises(ReviewConflict):self.put({**record,**patch,'revision':2})
        with self.assertRaises(InputError):self.put(self.span(configuration={'invalid':float('nan')}))
        with self.assertRaises(InputError):self.put(self.span(end=-1))
        with self.assertRaises(InputError):self.put(self.span(),schema=[])

    def test_no_join_by_equal_step_or_newest_source(self):
        self.sample();self.log()
        self.put(self.span(source_revision=99),self.span('update',kind='learner_update'))
        value=timeline.snapshot(self.store,experiment='run')
        self.assertEqual(value['logs'],[])
        self.assertTrue(all(not e['run_id'] for e in value['executions']))

    def test_update_has_no_fake_rollout_and_sdk_span_handles_failure(self):
        times=iter([10.,12.,15.,16.]);recorder=ExecutionRecorder(self.store,producer='trainer',experiment='run',clock='utc',now=lambda:next(times))
        with recorder.span('update',kind='learner_update',configuration={'precision':'nvfp4'}) as span:
            span['telemetry']=[dict(producer='learner',id='late')]
        with self.assertRaisesRegex(RuntimeError,'operation failed'):
            with recorder.span('sync',kind='weight_sync'):raise RuntimeError('operation failed')
        value=timeline.snapshot(self.store,experiment='run')
        self.assertEqual(value['counts']['states'],{'completed':1,'failed':1})
        self.assertTrue(all(e['record']['rollout'] is None for e in value['executions']))
        self.assertTrue(all(r['rollout_id'] is None for r in Workspace(self.store.path).table('executions')['rows']))

    def test_version_two_offline_bundle_replay_and_restart(self):
        box=Outbox(self.root/'outbox.sqlite',producer='worker')
        final=self.span(kind='learner_update',configuration={'backward':'dequantized'})
        box.log_execution('run',[final],schema=execution.TIMELINE_VERSION)
        bundle=self.root/'offline.zip';capture_bundle.export(box.path,bundle)
        self.assertEqual(capture_bundle.receive(self.store,bundle)['accepted'],1)
        fresh=Store(self.store.path)
        self.assertEqual(capture_bundle.receive(fresh,bundle)['already_present'],1)
        self.assertEqual(timeline.snapshot(fresh,experiment='run')['executions'][0]['record'],final)

    def test_truncated_view_and_missing_uses_remain_explicit(self):
        self.log();self.put(self.span('u1',kind='learner_update',telemetry=[dict(producer='learner',id='log')]),
                            self.span('u2',kind='learner_update',start=20,end=21))
        value=timeline.snapshot(self.store,experiment='run',limit=1)
        self.assertTrue(value['truncated'])
        value=timeline.snapshot(self.store,experiment='run')
        self.assertEqual(len(value['logs'][0]['unresolved_uses']),1)
        self.assertEqual(value['logs'][0]['sample_ids'],[])

    def test_independent_samples_keep_shared_source_and_exact_span_validation(self):
        from test_training_samples import record
        run_id=self.sample()
        run=self.store.get(run_id)['run']
        event=next(e for e in run['events'] if e['kind']=='message')
        source=dict(producer='actor',rollout_id='episode',revision=0)
        span=dict(event_id=event['id'],source_pointer=event['source_pointer'],start=0,end=2,text=event['text'][:2])
        records=[record('sample','one',source={**source,'spans':[span]}),
                 record('sample','two',source={**source,'spans':[{**span,'text':'zz'}]}),
                 record('sample','three',source=source),record('selection','three',decision='rejected'),
                 record('use','one'),record('use','two')]
        training_lineage.receive(self.store,dict(schema='training-records/2',producer='learner-export',experiment='run',records=records))
        self.logger.log({'actor/pg_loss':.2},step=90,record_id='independent',training_uses=dict(
            coverage='complete',basis='native independent samples',records=[dict(producer='learner-export',id='use/'+s,revision=0) for s in ('one','two')]))
        self.put(self.span(source_revision=0),self.span('update',kind='learner_update',telemetry=[dict(producer='learner',id='independent')]))
        value=timeline.snapshot(self.store,experiment='run')
        samples={s['sample_id']:s for s in value['samples'] if s['schema']=='training-records/2'}
        self.assertEqual(samples['one']['run_id'],run_id)
        self.assertIsNone(samples['two']['run_id'])
        self.assertEqual(samples['two']['source_status'],'invalid_source_spans')
        self.assertEqual(samples['three']['selections'][0]['data']['decision'],'rejected')
        self.assertEqual(len(value['logs'][0]['sample_ids']),2)
        self.assertEqual(value['logs'][0]['unresolved_uses'],[])

    def test_environment_scope_keeps_whole_native_batch_and_blocks_foreign_source(self):
        self.store.ingest(dict(producer='actor',rollout_id='episode',revision=0,state='complete',
            document=chat_document([dict(role='assistant',content='A different experiment.')],metadata={'experiment':'foreign'})))
        self.sample(False);self.log()
        self.put(self.span('terminal',source_revision=0,context=dict(environment='terminal')),
                 self.span('browser',context=dict(environment='browser')),
                 self.span('update',kind='learner_update',telemetry=[dict(producer='learner',id='log')]))
        value=timeline.snapshot(self.store,experiment='run',environment='terminal')
        self.assertEqual({e['record']['id'] for e in value['executions']},{'terminal','update'})
        self.assertEqual(value['logs'][0]['declared_uses'],1)
        self.assertIsNone(value['samples'][0]['run_id'])
        self.assertEqual(value['samples'][0]['source_status'],'experiment_conflict')

    def test_sampled_logprob_comparison_keeps_mask_and_stable_ess(self):
        from tracker.trainer_telemetry import snapshot
        self.logger.log_policy_comparison([-2.,-1001.,float('nan')],[-2.,-1.,float('nan')],mask=[1,1,0],
            step=1,basis='Same target positions; raw natural-log probabilities; authored test')
        rows={s['native_key']:s for s in snapshot(self.store)['series']}
        self.assertEqual(rows['comparison/mean_absolute_gap']['points'][0]['value'],500)
        self.assertAlmostEqual(rows['comparison/token_weight_ess_fraction']['points'][0]['value'],.5)
        self.assertTrue(all(s['group']=='mismatch' for s in rows.values()))
        with self.assertRaises(InputError):self.logger.log_policy_comparison([0],[0,1],mask=[1],step=2,basis='invalid')
        self.logger.log_policy_comparison([0],[0],mask=[0],step=3,basis='empty mask')
        self.assertTrue(any(p['status']=='missing' for s in snapshot(self.store)['series'] for p in s['points']))

    def test_mask_replay_logs_keep_rule_and_population_in_series_identity(self):
        import math
        from tracker.trainer_telemetry import snapshot
        for step,band in [(1,[.2,5]),(2,[.5,2])]:
            self.logger.log_policy_comparison([math.log(.01),math.log(.9)], [math.log(.06),math.log(.2)],
                mask=[1,1],step=step,basis='Aligned raw sampled probabilities before optimizer masking',
                probability_thresholds=[.2,.3],ratio_bounds=band)
        rows=snapshot(self.store)['series']
        disagreements=[s for s in rows if s['native_key'].endswith('/disagreement_fraction')]
        self.assertEqual(len(disagreements),4)
        self.assertTrue(all(sum(p['status']=='recorded' for p in s['points'])==1 for s in disagreements))
        self.assertTrue(all('not the actual trainer mask' in s['definition'] for s in disagreements))
        self.assertTrue(any(p['value']==1 for s in disagreements for p in s['points']))


if __name__=='__main__':unittest.main()
