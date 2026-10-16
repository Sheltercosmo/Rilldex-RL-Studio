import unittest

from tracker import task_mix
from tracker.behavior_distributions import aggregate, snapshot, sync
from tracker.schema import InputError
import test_behavior_distributions as fixtures


class TaskMixMathTests(unittest.TestCase):
    def point(self, task, step, numerator, total=1, revision=None):
        return {'task':task_mix.identity({'task_id':task,'task_revision':revision}),
                'step':step,'counts':{'return':numerator,'unknown':total-numerator},'total':total}

    def compare(self, points, population=None, **kwargs):
        return task_mix.compare(points, points if population is None else population,
                                ['return','unknown'], kwargs.get('weighting','rollout'),
                                kwargs.get('earlier',(1,1)),kwargs.get('later',(3,3)),[1,2,3],aggregate)

    def test_composition_shift_is_not_within_task_change(self):
        points=([self.point('A',1,1)]*9+[self.point('B',1,0)] +
                [self.point('A',3,1)]+[self.point('B',3,0)]*9)
        result=self.compare(points)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['deltas'][0]['raw_pp'],-80)
        self.assertEqual(result['deltas'][0]['fixed_pp'],0)
        self.assertEqual(result['earlier']['shares']['return'],.5)
        self.assertEqual(result['later']['shares']['return'],.5)
        self.assertAlmostEqual(sum(result['weights'].values()),1)

    def test_weighting_inside_tasks_preserves_unknowns(self):
        points=[self.point('A',s,1,1) for s in (1,3)]+[self.point('A',s,0,9) for s in (1,3)]+[self.point('B',s,1) for s in (1,3)]
        self.assertEqual(self.compare(points)['earlier']['shares']['return'],.75)
        self.assertEqual(self.compare(points,weighting='opportunity')['earlier']['shares']['return'],.55)

    def test_missing_task_breaks_curve_and_never_renormalizes(self):
        points=[self.point(t,s,1) for t in ('A','B') for s in (1,3)]+[self.point('A',2,0)]
        result=self.compare(points)
        self.assertIsNone(result['bins'][1]['shares']['return'])
        self.assertEqual(result['bins'][1]['tasks_observed'],1)
        self.assertEqual(result['bins'][1]['tasks_required'],2)

    def test_unshared_unobserved_and_unknown_identity_are_explicit(self):
        points=[self.point('A',1,1),self.point('A',3,0),self.point('B',1,1),self.point('C',3,1),self.point(None,1,1)]
        population=points+[self.point('D',1,1),self.point('D',3,1)]
        result=self.compare(points,population)
        self.assertEqual(len(result['shared_task_ids']),1)
        self.assertEqual({r['task']['task_id']:r['status'] for r in result['tasks']},
                         {'A':'shared','B':'earlier_only','C':'later_only','D':'unobserved'})
        self.assertEqual(result['unidentified_rollouts'],[1,0])
        self.assertEqual(result['unobserved_rollouts'],[1,1])
        self.assertEqual(result['deltas'][0]['fixed_pp'],-100)

    def test_changed_revision_is_not_a_shared_task(self):
        result=self.compare([self.point('A',1,1,revision='v1'),self.point('A',3,0,revision='v2')])
        self.assertFalse(result['available']);self.assertEqual(result['weights'],{})
        self.assertIsNone(result['deltas'][0]['fixed_pp'])

    def test_overlapping_or_empty_windows_do_not_produce_delta(self):
        points=[self.point('A',1,1),self.point('A',3,0)]
        for args in ({'earlier':(1,3)},{'later':(4,4)},{'earlier':(None,None)}):
            result=self.compare(points,**args)
            self.assertFalse(result['available']);self.assertIsNone(result['deltas'][0]['fixed_pp'])

    def test_zero_opportunities_are_not_zero_share(self):
        points=[self.point('A',1,0,0),self.point('A',3,0,0)]
        result=self.compare(points)
        self.assertFalse(result['available']);self.assertIsNone(result['earlier']['shares']['return'])


class TaskMixIntegrationTests(unittest.TestCase):
    setUp=fixtures.DistributionTests.setUp
    run_fixture=fixtures.DistributionTests.run_fixture
    graph=fixtures.DistributionTests.graph

    def seed(self):
        for i,(task,step,activity) in enumerate([('A',1,'orient'),('A',3,'verify'),('B',1,'verify'),('B',3,'orient')]):
            self.graph(self.run_fixture(i,task_id=task,training_step=step,policy_version='v'+str(step)),(activity,))
        sync(self.store)

    def test_opt_in_pooling_keeps_task_drilldown_and_snapshot_provenance(self):
        self.seed()
        original=snapshot(self.store);self.assertEqual(len(original['cohorts']),2)
        mixed=snapshot(self.store,population_mode='task_mix')
        self.assertEqual(len(mixed['cohorts']),1);self.assertEqual(mixed['observed_rollouts'],4)
        self.assertTrue(mixed['task_mix']['available']);self.assertEqual(len(mixed['task_mix']['tasks']),2)
        for row in mixed['task_mix']['tasks']:
            task=snapshot(self.store,cohort_id=row['cohort_id'])
            self.assertEqual(task['metadata']['task_id'],row['task']['task_id'])
            self.assertEqual(task['observed_rollouts'],2)
        self.assertTrue(all(p['graph_id'] and p['task'] for p in mixed['points']))
        self.assertEqual(mixed,snapshot(self.store,population_mode='task_mix'))

    def test_recorded_context_stays_separate_and_missing_annotations_visible(self):
        self.seed();self.run_fixture(10,task_id='A',training_step=1)
        self.graph(self.run_fixture(11,task_id='A',sampling={'temperature':2}),('orient',))
        self.graph(self.run_fixture(12,task_id='B',split='eval'),('verify',))
        self.graph(self.run_fixture(13,task_id='B',reward_definition='other'),('verify',))
        sync(self.store);result=snapshot(self.store,population_mode='task_mix')
        self.assertEqual(len(result['cohorts']),4)
        self.assertEqual(result['population'],5)
        self.assertEqual(result['task_mix']['unobserved_rollouts'],[1,0])
        with self.assertRaises(InputError):snapshot(self.store,population_mode='all')

    def test_unplaced_data_has_no_training_task_mix_estimate(self):
        self.graph(self.run_fixture(1,task_id='A',training_step=None),('orient',));sync(self.store)
        result=snapshot(self.store,population_mode='task_mix')
        self.assertEqual(result['unplaced_rollouts'],1)
        self.assertFalse(result['task_mix']['available']);self.assertEqual(result['task_mix']['bins'],[])

    def test_macro_recurrence_reuses_exact_relations_and_receipts(self):
        from tests.test_work_episodes import example, edge
        from tests.test_adaptation_patterns import saved_graph
        from tracker import graph_store
        from tracker.schema import digest
        for task, step, names in [('A',1,('A','B','A')),('A',3,('A','B','A')),('B',1,('C','C')),('B',3,('C','C'))]:
            run,g,actions=example(names)
            run['id']=digest([run['id'],task,step])[:24]
            run['metadata'].update(experiment='macro-control',task_id=task,training_step=step)
            g.update(run_id=run['id'],metadata=run['metadata'],source_hash=digest(run))
            edge(g,actions[-1],actions[0],'same_action_target')
            self.store.add([run])
            with self.store.connect() as c:graph_store.save(c,saved_graph(g))
        result=snapshot(self.store,lens='recurrence',population_mode='task_mix')
        self.assertEqual(len(result['task_mix']['shared_task_ids']),2)
        self.assertAlmostEqual(result['task_mix']['earlier']['shares']['returned'],1/6)
        self.assertEqual(next(r['fixed_pp'] for r in result['task_mix']['deltas'] if r['id']=='returned'),0)
        self.assertEqual(len(result['analysis_receipts']),4)
        self.assertTrue(all('graph=' in r['map_url'] for r in result['cases']))


if __name__=='__main__':unittest.main()
