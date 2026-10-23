import copy
import json
from pathlib import Path
import tempfile
import unittest

from rilldex import Workspace, chat_document
from tracker import case_behavior, case_studies, monitoring as m, graph_store, findings_report, failure_investigations
from tracker.schema import InputError, digest
from tracker.store import Store


class CaseBehaviorTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name)/'study.sqlite');self.serial=0
        self.success=m.create(self.store,dict(name='Reported success',kind='metric',metric='recorded_success',observer='source',group='Training'))

    def add(self,side,task='easy',success=True,**extra):
        self.serial+=1;revision=extra.pop('revision',0);name=extra.pop('rollout_id',str(self.serial))
        metadata=dict(experiment=side,task_id=task,task_revision='1',environment='terminal',environment_version='1',
                      split='train',reward_definition='tests/v1');metadata.update(extra)
        result=self.store.ingest(dict(producer='actor',rollout_id=name,revision=revision,state='complete',metadata=metadata,
            document=chat_document([dict(role='assistant',content='Attempt '+str(self.serial))],success=success)))
        return result['id']

    def save(self,**kwargs):
        return case_studies.save(self.store,dict(reference=dict(experiment='before'),selected=dict(experiment='after'),**kwargs))

    def panel(self,doc,mid=None):
        return next(p for p in doc['snapshot']['behavior']['panels'] if p['monitor']['id']==(mid or self.success['id']))

    def test_task_mix_change_does_not_appear_as_within_task_decline(self):
        for side,easy,hard in [('before',3,1),('after',1,3)]:
            for task,n,outcome in [('easy',easy,True),('hard',hard,False)]:
                for _ in range(n):self.add(side,task,outcome)
        m.sync(self.store);doc=self.save();p=self.panel(doc)
        self.assertEqual((p['baseline']['value'],p['current']['value'],p['delta']),(.75,.25,-.5))
        self.assertEqual((p['same_tasks']['baseline'],p['same_tasks']['current'],p['same_tasks']['delta']),(.5,.5,0))
        self.assertEqual(p['same_tasks']['measured_contexts'],2)
        self.assertTrue(all(r['value_id'] and r['graph_id'] for r in p['points']['baseline']))
        self.assertIn('Same tasks',findings_report.summary(doc)['measures'])

    def test_no_rollout_coordinates_required(self):
        self.add('before');self.add('after',success=False);m.sync(self.store)
        p=self.panel(self.save());self.assertEqual(p['delta'],-1)
        self.assertEqual(p['baseline']['total'],1)

    def test_missing_measurements_do_not_become_failures_and_capture_does_not_materialize(self):
        self.add('before');m.sync(self.store);self.add('after')
        before=self.save();p=self.panel(before)
        self.assertIsNone(p['current']['value']);self.assertEqual(p['current']['missing'],1)
        self.assertEqual(p['same_tasks']['contexts'],1);self.assertEqual(p['same_tasks']['measured_contexts'],0)
        m.sync(self.store);after=self.save()
        self.assertEqual(self.panel(after)['current']['value'],1)
        self.assertEqual(failure_investigations.read(self.store,before['id']),before)

    def test_ratios_pool_opportunities_but_same_tasks_have_equal_weight(self):
        for side in ['before','after']:
            self.add(side,'easy',n=1,d=1);self.add(side,'hard',n=0,d=9)
        monitor=Workspace(self.store.path,observer='source').monitor('Recovery',version='test/1',description='Authored opportunity counts',unit='fraction',aggregation='opportunity_ratio')
        monitor.run(lambda c:dict(numerator=c.run['metadata']['n'],denominator=c.run['metadata']['d'],unknown=2))
        m.sync(self.store);p=self.panel(self.save(),monitor.id)
        self.assertEqual((p['baseline']['value'],p['baseline']['numerator'],p['baseline']['denominator']),(.1,1,10))
        self.assertEqual(p['baseline']['unknown_opportunities'],4)
        self.assertEqual(p['same_tasks']['baseline'],.5)

    def test_unknown_opportunities_and_zero_opportunities_are_not_zero_rates(self):
        self.add('before');self.add('after')
        monitor=Workspace(self.store.path,observer='source').monitor('Unresolved recovery',version='test/1',description='Authored missing checks',unit='fraction',aggregation='opportunity_ratio')
        result=monitor.run(lambda c:dict(numerator=0,denominator=0,unknown=3 if c.run['metadata']['experiment']=='before' else 0,
                                       reason='No resolved recovery opportunities'))
        self.assertEqual(result['errors'],0)
        m.sync(self.store);p=self.panel(self.save(),monitor.id)
        self.assertIsNone(p['baseline']['value']);self.assertIsNone(p['current']['value']);self.assertIsNone(p['delta'])
        self.assertEqual(p['baseline']['unknown_opportunities'],3)

    def test_missing_context_changed_reward_definition_and_unmatched_tasks_stay_separate(self):
        self.add('before','same');self.add('after','same',reward_definition='tests/v2')
        self.add('before','missing',environment_version=None);self.add('after','missing',environment_version=None)
        self.add('before','only-before');m.sync(self.store);p=self.panel(self.save())
        self.assertEqual(p['baseline']['measured'],3);self.assertEqual(p['current']['measured'],2)
        self.assertEqual(p['same_tasks']['contexts'],0)
        self.assertEqual(p['same_tasks']['incomplete_context_rollouts'],dict(baseline=1,current=1))
        self.assertEqual(p['same_tasks']['without_counterpart'],dict(baseline=2,current=1))

    def test_population_scope_and_explicit_monitor_selection(self):
        self.add('before');self.add('after')
        scoped=m.create(self.store,dict(name='Reference only',kind='metric',metric='recorded_success',observer='source',population={'experiment':'before'}))
        m.sync(self.store);p=self.panel(self.save(monitor_ids=[scoped['id']]),scoped['id'])
        self.assertEqual(p['excluded']['current'],1);self.assertIsNone(p['current']['value'])
        self.assertEqual(self.save(monitor_ids=[])['snapshot']['behavior']['panels'],[])
        for ids in ([self.success['id']]*2,['unknown'],True):
            with self.assertRaises(InputError):self.save(monitor_ids=ids)

    def test_older_consumed_source_keeps_its_measurement(self):
        a=self.add('before',success=False,rollout_id='first');b=self.add('after')
        m.sync(self.store);self.add('before',success=True,rollout_id='first',revision=1);m.sync(self.store)
        with self.store.connect() as c:
            rows=c.execute('SELECT id,document,imported_at FROM runs WHERE id IN (?,?)',(a,b)).fetchall()
        sources=[dict(id=r['id'],metadata=json.loads(r['document'])['metadata'],state='complete',adapter='chat',imported_at=r['imported_at']) for r in rows]
        with self.store.read_snapshot() as saved:
            p=case_behavior.capture(saved,sources,dict(baseline=[a],current=[b]))['panels'][0]
        self.assertEqual(p['baseline']['value'],0);self.assertEqual(p['delta'],1)

    def test_shared_rollouts_are_not_counted_in_either_measure_population(self):
        a=self.add('before');b=self.add('after');shared=self.add('before');m.sync(self.store)
        doc=self.save();sources=doc['snapshot']['source_rows']
        with self.store.read_snapshot() as saved:p=case_behavior.capture(saved,sources,dict(baseline=[a],current=[b]))['panels'][0]
        self.assertEqual(p['baseline']['total'],1);self.assertNotIn(shared,[r['run_id'] for r in p['points']['baseline']])

    def test_new_graph_waits_for_a_matching_receipt_without_changing_saved_measurements(self):
        a=self.add('before');self.add('after')
        with self.store.connect() as c:runs=[json.loads(r[0]) for r in c.execute('SELECT document FROM runs')]
        for run in runs:
            graph=graph_store.build(run,dict(document=dict(source_hash=digest(run),units=[],relations=[]),observer=dict(id='review',label='Review')))
            with self.store.connect() as c:graph_store.save(c,graph)
        monitor=Workspace(self.store.path,observer='review').monitor('Reviewed activity',version='code/1',description='Authored saved analysis')
        monitor.run(lambda _:dict(value=2));m.sync(self.store);old=self.save();p=self.panel(old,monitor.id)
        self.assertEqual(p['baseline']['value'],2)
        run=next(r for r in runs if r['id']==a)
        graph=graph_store.build(run,dict(document=dict(source_hash=digest(run),units=[],relations=[],annotation='changed'),observer=dict(id='review',label='Review')))
        with self.store.connect() as c:graph_store.save(c,graph)
        new=self.panel(self.save(),monitor.id)
        self.assertIsNone(new['baseline']['value']);self.assertEqual(new['points']['baseline'][0]['status'],'pending')
        self.assertEqual(self.panel(failure_investigations.read(self.store,old['id']),monitor.id),p)

    def test_version_comparison_ignores_input_lineage_but_retains_detector_changes(self):
        self.add('before');self.add('after')
        with self.store.connect() as c:runs=[json.loads(r[0]) for r in c.execute('SELECT document FROM runs')]
        def annotate(changed=False):
            for run in runs:
                provenance=dict(harness='detector/2' if changed and run['metadata']['experiment']=='after' else 'detector/1',
                                revision=dict(parent=run['id']))
                graph=graph_store.build(run,dict(document=dict(source_hash=digest(run),units=[],relations=[],provenance=provenance),observer=dict(id='review',label='Review')))
                with self.store.connect() as c:graph_store.save(c,graph)
        annotate()
        monitor=Workspace(self.store.path,observer='review').monitor('Reviewed activity',version='code/1',description='Authored saved analysis')
        monitor.run(lambda _:dict(value=2));p=self.panel(self.save(),monitor.id)
        self.assertTrue(p['versions']['same_recorded_versions'])
        annotate(changed=True);monitor.run(lambda _:dict(value=2));p=self.panel(self.save(),monitor.id)
        self.assertFalse(p['versions']['same_recorded_versions'])

    def test_python_selection_and_out_of_scope_choices_are_retained(self):
        self.add('before');self.add('after')
        scoped=m.create(self.store,dict(name='Another experiment',kind='metric',metric='recorded_success',observer='source',population={'experiment':'another'}))
        doc=Workspace(self.store.path).compare_rollouts(reference=dict(experiment='before'),selected=dict(experiment='after'),monitor_ids=[scoped['id']])
        self.assertEqual(doc['controls']['monitor_ids'],[scoped['id']])
        self.assertIn(scoped['id'],[r['id'] for r in doc['snapshot']['behavior']['choices']])
        p=self.panel(doc,scoped['id'])
        self.assertEqual(p['excluded'],dict(baseline=1,current=1));self.assertIsNone(p['delta'])

    def test_later_code_monitors_are_discoverable_without_rewriting_the_comparison(self):
        self.add('before');self.add('after');m.sync(self.store);doc=self.save()
        monitor=Workspace(self.store.path).monitor('Later analysis',version='code/1',description='Created after comparison')
        options=case_behavior.options(self.store,doc)
        self.assertIn(monitor.id,[r['id'] for r in options['choices']])
        self.assertNotIn(monitor.id,[r['id'] for r in doc['snapshot']['behavior']['choices']])
        self.assertEqual(failure_investigations.read(self.store,doc['id']),doc)


if __name__=='__main__':unittest.main()
