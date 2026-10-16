import json
import tempfile
import unittest
from pathlib import Path

from tracker.store import Store
from tracker.training_lineage import receive
from tracker.training_health import snapshot
from tracker.reward_relationships import _correlation
from tracker.trl_reward_components import validate_components
from tracker.schema import InputError
from test_training_health import record


class RewardRelationshipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name)/'tracker.sqlite')

    def add(self, *rows, producer='worker'):
        return receive(self.store, {'schema':'training-records/1', 'experiment':'exp',
                                   'producer':producer, 'records':list(rows)})

    def group(self, group, xs, ys, step=0):
        for i, (x, y) in enumerate(zip(xs, ys)):
            sid = group + str(i)
            self.add(record('sample', sid, group_id=group, group_size=len(xs), step=step, task_id=group),
                     record('score', sid, identifier='x/'+sid, component='x', definition='x/1', value=x),
                     record('score', sid, identifier='y/'+sid, component='y', definition='y/1', value=y))

    def view(self, **kwargs):
        return snapshot(self.store, **kwargs)['cohorts'][0]['reward_relationships']

    def test_task_mix_can_reverse_interpretation(self):
        self.group('easy', [0, 1], [1, 0]); self.group('hard', [10, 11], [11, 10])
        r = self.view()
        self.assertAlmostEqual(r['correlation']['value'], 99/101)
        self.assertAlmostEqual(r['within_group_correlation']['value'], -1)
        self.assertEqual((r['matched_samples'], r['within_group_samples'], r['complete_groups']), (4,4,2))
        self.assertEqual(snapshot(self.store)['cohorts'][0]['dashboard']['default']['mode'], 'reward_relationships')

    def test_missing_component_excludes_whole_group_only_from_group_statistic(self):
        self.group('g', [0,1,2], [0,1,2])
        self.add(record('score', 'g1', identifier='y/g1', revision=1, component='y', definition='y/1', status='unavailable', value=None))
        r = self.view()
        self.assertEqual((r['matched_samples'],r['within_group_samples']), (2,0))
        self.assertIsNone(r['within_group_correlation']['value'])
        self.assertEqual(r['group_states'], {'scores_incomplete':1})
        self.assertIn('unavailable', r['x_states'] | r['y_states'])

    def test_conflicting_scores_excluded_even_when_numerically_equal(self):
        self.group('g',[0,1],[1,0])
        self.add(record('score','g0',identifier='second-x',component='x',definition='x/1',value=0))
        r=self.view()
        self.assertEqual(r['matched_samples'],1)
        self.assertEqual(r['correlation']['status'],'insufficient_samples')

    def test_late_score_revision_and_retry(self):
        self.group('g',[0,1],[0,1])
        change=record('score','g0',identifier='y/g0',revision=2,component='y',definition='y/1',value=2)
        self.add(change)
        before=self.view()
        self.add(change)
        self.add(record('score','g0',identifier='y/g0',revision=1,component='y',definition='y/1',value=-4))
        self.assertEqual(before,self.view())
        self.assertAlmostEqual(before['correlation']['value'],-1)
        evidence=[row for row in before['records'] if row['id']=='g0'][0]
        self.assertTrue(any(evidence[k]['record']['revision']==2 for k in ('x','y')))

    def test_group_context_conflict_is_not_repaired_by_step_slicing(self):
        for i in range(2):
            self.add(record('sample','g'+str(i),group_id='g',group_size=2,step=i,task_id='g'),
                     record('score','g'+str(i),identifier='x/'+str(i),component='x',definition='x/1',value=i),
                     record('score','g'+str(i),identifier='y/'+str(i),component='y',definition='y/1',value=i))
        r=self.view()
        self.assertEqual(r['group_states'],{'conflicting_context':1})
        self.assertTrue(all(p['within_group_samples']==0 for p in r['points']))

    def test_unequal_groups_pool_residuals_not_correlations(self):
        self.group('a',[0,2],[0,2]); self.group('b',[0,2,4],[4,2,0])
        r=self.view()
        # Cross-products: +2 -8; squared residuals: 2+8 on both axes.
        self.assertAlmostEqual(r['within_group_correlation']['value'],-.6)

    def test_ungrouped_and_unclocked_samples_still_have_raw_pair(self):
        for i in range(2):
            s=record('sample',str(i));s['data']={'split':'train'}
            self.add(s,record('score',str(i),component='x',definition='x/1',identifier='x/'+str(i),value=i),
                     record('score',str(i),component='y',definition='y/1',identifier='y/'+str(i),value=i))
        r=self.view()
        self.assertAlmostEqual(r['correlation']['value'],1)
        self.assertEqual(r['points'],[])
        self.assertEqual(r['missing_step_samples'],2)
        self.assertEqual(r['missing_group_samples'],2)
        self.assertIsNone(r['within_group_correlation']['value'])

    def test_pair_is_symmetric_explicit_and_definition_bound(self):
        self.group('g',[0,1],[1,0])
        r=self.view();a=r['selected']['x']['id'];b=r['selected']['y']['id']
        swapped=self.view(reward_x=b,reward_y=a)
        self.assertEqual(swapped['correlation'],r['correlation'])
        self.assertEqual(swapped['selected']['x']['id'],b)
        self.assertEqual(self.view(reward_x=a,reward_y=a)['status'],'selection_unavailable')
        self.assertEqual(self.view(reward_x=a,reward_y='missing')['status'],'selection_unavailable')

    def test_no_overlap_and_constants_remain_undefined(self):
        self.group('g',[1,1],[0,1])
        r=self.view()
        self.assertEqual(r['correlation']['status'],'constant_component')
        self.assertEqual(r['within_group_correlation']['status'],'constant_component')
        for i in range(2):
            self.add(record('score','g'+str(i),identifier='y/g'+str(i),revision=1,component='y',definition='y/1',status='error',value=None))
        self.assertEqual(self.view()['matched_samples'],0)

    def test_native_step_points_and_missing_correlations_are_preserved(self):
        self.group('a',[0,1],[0,1],step=0)
        self.group('b',[0,0],[0,1],step=1)
        self.group('c',[0,1],[1,0],step=2)
        r=self.view()
        self.assertAlmostEqual(r['points'][0]['correlation']['value'],1)
        self.assertIsNone(r['points'][1]['correlation']['value'])
        self.assertAlmostEqual(r['points'][2]['correlation']['value'],-1)
        self.assertEqual([p['step'] for p in r['points']],[0,1,2])

    def test_extreme_values_are_json_finite(self):
        for xs in ([(-1e308,1e308),(1e308,-1e308)],[(1e-308,2e-308),(2e-308,1e-308)]):
            r=_correlation([xs],centered=False)
            self.assertAlmostEqual(r['value'],-1)
            json.dumps(r,allow_nan=False)

    def test_different_group_constants_do_not_create_within_group_signal(self):
        groups=[[(.1,y) for y in range(7)],[(.39,y) for y in range(9)]]
        self.assertEqual(_correlation(groups,centered=True)['status'],'constant_component')

    def test_reward_component_contract(self):
        components=[{'component':'accuracy','definition':'accuracy/1'},{'component':'format','definition':'format/1'}]
        self.assertEqual(validate_components(components,2,'accuracy/1'),components)
        for value,count,definition in [(None,2,'accuracy/1'),(components,1,'accuracy/1'),
                (components,2,'wrong'),([components[0],components[0]],2,'accuracy/1')]:
            with self.assertRaises(InputError):validate_components(value,count,definition)

    def test_verified_multi_reward_settings_prioritize_relationships(self):
        from tracker.training_dashboard import project
        cohort={'reward_relationships':{'components':[{},{}],'matched_samples':4},
            'monitoring_plan':{'status':'ready','groups':[{'monitors':[{'id':'reward_components'}]}]},
            'uses':[{'id':'s','stage':'backward_completed','producer':'p',
                     'policy_age':{'clocks':[{'known_tokens':10}]}}]}
        self.assertEqual(project(cohort)['default']['mode'],'reward_relationships')
        cohort['monitoring_plan']['status']='review'
        self.assertEqual(project(cohort)['default']['mode'],'use')

    def test_native_trl_aggregation_and_weight_list_enable_comparison_guidance(self):
        from tracker import training_setup
        from test_training_setup import request
        for aggregation,weights in [('normalize_then_sum',None),('sum_then_normalize',[.7,1.3])]:
            config=request('trl')
            config['config'].update(multi_objective_aggregation=aggregation,reward_weights=weights)
            inspected=training_setup.inspect(config)
            self.assertEqual(inspected['status'],'ready')
            self.assertIn('reward_components',{m['id'] for m in inspected['monitors']})
        config['config']['reward_weights']=[1.]
        self.assertNotIn('reward_components',{m['id'] for m in training_setup.inspect(config)['monitors']})

    def test_native_matrix_capture_preserves_return_and_failed_capture_is_empty(self):
        from tracker.trl_lineage import GRPOTrainingLineageMixin
        class Matrix:
            def __init__(self,rows):self.rows=rows
            def detach(self):return self
            def cpu(self):return self
            def tolist(self):return self.rows
        class Native:
            def _calculate_rewards(self):return self.matrix
        class Capture(GRPOTrainingLineageMixin,Native):pass
        capture=Capture.__new__(Capture)
        capture._jev_reward_components=[{},{}]
        errors=[];capture._jev_error=errors.append
        matrix=Matrix([[1.,float('nan')],[2.,3.]])
        capture.matrix=matrix
        self.assertIs(capture._calculate_rewards(),matrix)
        self.assertEqual(capture._jev_reward_matrix,[[1.,None],[2.,3.]])
        capture.matrix=Matrix([[float('inf'),0.]])
        self.assertIs(capture._calculate_rewards(),capture.matrix)
        self.assertIsNone(capture._jev_reward_matrix)
        self.assertEqual(len(errors),1)
