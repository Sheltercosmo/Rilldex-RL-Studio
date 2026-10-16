import copy
import tempfile
import unittest
from pathlib import Path

from rilldex import chat_document
from tracker import monitoring as m, monitor_comparisons as comparisons, execution_records as executions
from tracker import population_readiness as readiness
from tracker.schema import digest, dumps
from tracker.store import Store


class PopulationReadinessTests(unittest.TestCase):
    def test_unresolved_receipts_are_not_missing_measurements_or_zero(self):
        points=[dict(value=None,status='unavailable',capture_state='complete',value_id='receipt',
                     opportunities=1,unknown_opportunities=1)]
        summary=readiness.summarize(points)
        self.assertEqual(summary['value_states'],{'unresolved_evidence':1})
        self.assertEqual(summary['measured'],0)
        cohort=dict(baseline={'readiness':readiness.summarize([])},current={'readiness':summary},
                    task_mix={'recorded_task_mix_distance':0},cohort={})
        codes={r['code'] for r in readiness.review([cohort])}
        self.assertIn('current_unresolved_evidence',codes)
        self.assertNotIn('current_unmeasured',codes)
        self.assertIsNone(comparisons.summarize(points,'opportunity_ratio')['value'])
        cases=[(dict(value_id=None),'no_receipt'),
               (dict(unknown_opportunities=0,opportunities=0),'no_opportunities'),
               (dict(status='error'),'measurement_error'),
               (dict(unknown_opportunities=0,opportunities=None),'no_value')]
        for extra,expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(readiness.value_state({**points[0],**extra}),expected)

    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'workspace.sqlite')
        self.monitor=m.create(self.store,dict(name='Success',kind='metric',metric='recorded_success',observer='source'))

    def source(self, step, name, outcome, state='complete', revision=0, **extra):
        metadata=dict(experiment='arrival-study',environment='terminal',training_step=step,
            training_step_basis='generation',task_id=name,policy_version='policy-1',split='train',**extra)
        document=chat_document([dict(role='user',content='Task '+name),dict(role='assistant',content='Recorded response')],
            metadata=metadata,success=outcome)
        return self.store.ingest(dict(producer='simulation',rollout_id=str(step)+'-'+name,
            revision=revision,state=state,document=document,metadata=metadata))

    def capture(self):
        m.sync(self.store)
        return comparisons.save(self.store,self.monitor['id'],baseline=[0,0],current=[1,1],experiment='arrival-study')

    def test_completion_order_can_bias_in_either_direction_without_final_regression(self):
        for fast_success in (False,True):
            with self.subTest(fast_success=fast_success):
                # Separate independent workspaces, same final outcomes and task mix.
                self.setUp()
                for step in (0,1):
                    self.source(step,'fast',fast_success)
                    self.source(step,'slow',not fast_success,'complete' if step==0 else 'in_progress')
                before=self.capture();row=before['cohorts'][0]
                self.assertEqual(row['delta'],.5 if fast_success else -.5)
                self.assertEqual(row['current']['readiness']['unfinished'],1)
                self.assertEqual(row['current']['readiness']['measurement_coverage'],.5)
                mix=row['current']['readiness']['selection'][0]
                self.assertEqual(mix['measured_mix_distance'],.5)
                self.assertIn('current_unfinished',{r['code'] for r in before['review']})
                self.source(1,'slow',not fast_success,revision=1)
                after=self.capture();self.assertEqual(after['cohorts'][0]['delta'],0)
                self.assertEqual(after['cohorts'][0]['current']['readiness']['unfinished'],0)
                self.assertIsNone(after['cohorts'][0]['current']['readiness']['population_closed'])
                self.assertEqual(comparisons.read(self.store,before['id']),before)

    def test_real_regression_remains_after_all_observed_work_is_measured(self):
        for name in ('a','b'):
            self.source(0,name,True);self.source(1,name,False)
        d=self.capture();r=d['cohorts'][0]
        self.assertEqual(r['delta'],-1)
        self.assertEqual(r['current']['readiness']['measurement_coverage'],1)
        self.assertNotIn('current_unfinished',{q['code'] for q in d['review']})
        self.assertEqual(r['task_mix']['recorded_task_mix_distance'],0)
        self.assertIsNone(r['current']['readiness']['population_closed'])

    def test_missing_outcome_and_failed_capture_are_not_unfinished_or_task_failures(self):
        self.source(0,'a',True);self.source(1,'no-score',None)
        self.source(1,'capture-failed',False,'failed')
        d=self.capture();r=d['cohorts'][0]['current']['readiness']
        self.assertEqual((r['unfinished'],r['completed_unmeasured'],r['failed_capture']),(0,1,1))
        self.assertEqual(r['measured'],0)
        self.assertIsNone(d['cohorts'][0]['current']['value'])

    def test_completed_only_import_does_not_prove_no_inflight_jobs(self):
        from tracker.adapters import normalize
        doc=chat_document([dict(role='user',content='A'),dict(role='assistant',content='B')],success=True,
            metadata=dict(experiment='arrival-study',training_step=1))
        self.store.add(normalize(doc));d=self.capture()
        r=d['cohorts'][0]['current']['readiness']
        self.assertEqual(r['capture_states'],dict(imported_snapshot=1))
        self.assertIsNone(r['population_closed'])
        self.assertEqual(d['execution_context']['observed_attempts'],0)

    def execution(self,revision,state):
        return executions.receive(self.store,dict(schema=executions.VERSION,producer='scheduler',experiment='arrival-study',records=[
            dict(id='attempt',revision=revision,kind='rollout',rollout=dict(producer='simulation',id='1-slow'),
                state=state,context=dict(environment='terminal',policy_version='policy-1'),
                metrics=dict(output_tokens=0,**({'duration_ms':0} if state=='completed' else {'elapsed_ms':1000})),
                evidence='Synthetic scheduler lifecycle event')]))

    def test_lifecycle_before_sources_is_selectable_and_frozen_separately_from_step_windows(self):
        self.execution(0,'running')
        snapshot=m.snapshot(self.store,experiment='arrival-study')
        self.assertIn(dict(id='arrival-study',count=0),snapshot['experiments'])
        self.assertEqual(snapshot['population'],0)
        self.assertEqual(snapshot['execution_context']['groups'][0]['unfinished'],1)
        frozen=self.capture();self.execution(1,'completed')
        current=m.snapshot(self.store,experiment='arrival-study')['execution_context']
        self.assertEqual(current['groups'][0]['unfinished'],0)
        self.assertEqual(current['groups'][0]['completed_output_tokens']['p50'],0)
        self.assertIn('not the selected comparison steps',current['scope'])
        self.assertEqual(comparisons.read(self.store,frozen['id'])['execution_context']['groups'][0]['unfinished'],1)

    def test_legacy_receipts_remain_readable_without_inventing_capture_history(self):
        self.source(0,'a',True);current=self.capture();legacy=copy.deepcopy(current)
        legacy['schema']='monitor-comparison/1';legacy.pop('review');legacy.pop('execution_context')
        for row in legacy['cohorts']:
            for side in ('baseline','current'):row[side].pop('readiness')
        legacy['id']='comparison-'+digest({k:v for k,v in legacy.items() if k!='id'})
        with self.store.connect() as c:c.execute('INSERT INTO monitor_comparisons VALUES (?,?,?)',(legacy['id'],dumps(legacy),legacy['captured_at']))
        self.assertEqual(comparisons.read(self.store,legacy['id']),legacy)

    def test_execution_only_updates_have_an_independent_live_revision(self):
        from tracker.connections import Service
        from test_connections import MonitorStub
        service=Service(self.store,MonitorStub());self.addCleanup(service.close)
        before=service.snapshot();self.execution(0,'running');after=service.snapshot()
        self.assertEqual(before['source_revision'],after['source_revision'])
        self.assertEqual(before['training_revision'],after['training_revision'])
        self.assertNotEqual(before['execution_revision'],after['execution_revision'])
        self.execution(1,'completed')
        self.assertNotEqual(after['execution_revision'],service.snapshot()['execution_revision'])

    def test_unknown_and_structured_policy_metadata_do_not_crash_or_become_zero(self):
        r=readiness.summarize([dict(status='pending',value=None,capture_state='in_progress',policy_version={'actor':['1','2']})])
        self.assertIsNone(r['selection'][1]['measured_mix_distance'])
        self.assertEqual(r['selection'][1]['groups'][0]['value'],{'actor':['1','2']})
        self.assertIsNone(readiness.summarize([])['measurement_coverage'])


if __name__=='__main__':unittest.main()
