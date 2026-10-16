import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.compare import compare
from tracker.comparison_evidence import evidence, ComparisonChanged
from tracker.observe import analyze
from tracker.schema import InputError
from tracker.schema import dumps
from tracker.sequence import observe
from tracker.store import Store


def trace(modes):
    tools={'explore':'read_file','apply':'write_file','verify':'run_tests','report':'submit','unresolved':'unknown_operation'}
    return {'schema_version':'ATIF-v1.7','agent':{'name':'sequence-fixture'},'steps':[
        {'step_id':0,'source':'user','message':'Synthetic comparison test; inspect, modify and check a parser.'},
        *[{'step_id':i+1,'source':'agent','message':'Fixture operation.',
           'tool_calls':[{'tool_call_id':str(i),'function_name':tools[mode],'arguments':{'path':'parser.py'}}],
           'observation':{'results':[{'source_call_id':str(i),'content':'synthetic result'}]}}
          for i,mode in enumerate(modes)]]}


class SequenceTests(unittest.TestCase):
    def test_unknown_work_is_a_state_and_not_bridged(self):
        run=normalize(trace(['explore','unresolved','verify']))[0]
        sequence=analyze(run)['sequence']
        self.assertEqual(sequence['summary']['counts'],{'explore.unresolved':1,'unresolved.verify':1})
        self.assertEqual(sequence['summary']['unresolved_pairs'],2)

    def test_batch_order_and_batch_boundaries_are_excluded(self):
        doc=trace(['explore','apply','verify','report'])
        doc['steps'][2]['tool_calls'].append({'tool_call_id':'parallel','function_name':'read_file','arguments':{'path':'other.py'}})
        result=analyze(normalize(doc)[0])
        self.assertEqual(result['metrics']['sequence']['possible_pairs'],4)
        self.assertEqual(result['metrics']['sequence']['excluded_batch_pairs'],3)
        self.assertEqual(result['metrics']['sequence']['counts'],{'verify.report':1})
        self.assertEqual(result['flow']['edges'],[{'source':'verify','target':'report','count':1}])

    def test_interleaved_agents_never_create_cross_actor_edges(self):
        actions=[{'event_id':str(i),'trajectory_id':actor,'parent_id':None,'mode':mode}
                 for i,(actor,mode) in enumerate([('a','explore'),('b','apply'),('a','verify'),('b','report')])]
        sequence=observe(actions)
        self.assertEqual(sequence['summary']['counts'],{'explore.verify':1,'apply.report':1})
        self.assertEqual([p['trajectory_id'] for p in sequence['pairs']],['a','b'])


class SequenceComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'sequence.sqlite')

    def add(self, task, checkpoint, modes, **extra):
        run=normalize(trace(modes),meta={'task_id':task,'checkpoint':checkpoint,'training_step':int(checkpoint[1:]),
                      'experiment':'sequence-fixture','environment_version':'v1','split':'eval',**extra})[0]
        self.store.add([run]);return run

    def populate(self, count=1):
        for i in range(count):
            self.add(f't{i}','c0',['explore','apply','verify'])
            self.add(f't{i}','c1',['explore','verify','apply'])

    def request(self, metric='transition.apply.verify', **kwargs):
        rows=self.store.list(); result=compare(rows)
        return evidence(rows,self.store.get,comparison_id=result['comparison_id'],metric=metric,
                        reference='c0',checkpoint='c1',**kwargs)

    def test_same_action_proportions_can_have_different_temporal_structure(self):
        self.populate(5)
        result=compare(self.store.list())
        self.assertEqual(result['checkpoints'][0]['modes'],result['checkpoints'][1]['modes'])
        delta=result['paired_deltas'][0]
        self.assertEqual(delta['metrics']['transition.apply.verify']['delta'],-.5)
        self.assertEqual(delta['metrics']['transition.apply.verify']['interval_95'],[-.5,-.5])
        self.assertEqual(delta['sequence']['before']['apply.verify'],.5)
        self.assertEqual(delta['sequence']['after']['apply.verify'],0)
        self.assertAlmostEqual(sum(delta['sequence']['before'].values()),1)

    def test_no_sequence_opportunity_is_not_zero_and_cohort_is_paired(self):
        self.populate()
        self.add('no-pair','c0',['explore'])
        self.add('no-pair','c1',['explore','apply'])
        result=compare(self.store.list())['paired_deltas'][0]
        self.assertEqual(result['sequence']['task_ids'],['t0'])
        self.assertEqual(result['sequence']['excluded_task_ids'],['no-pair'])
        self.assertEqual(result['metrics']['transition.apply.verify']['task_count'],1)
        self.assertEqual(result['sequence']['coverage']['before']['eligible_rollouts'],1)

    def test_equal_rollout_and_task_weights_do_not_pool_transition_counts(self):
        self.populate()
        self.add('t0','c0',['explore','apply','verify']*4,seed='long')
        self.add('other','c0',['explore','explore'])
        self.add('other','c1',['explore','explore'])
        result=compare(self.store.list())['paired_deltas'][0]
        # t0 has 1/2 and 4/11 apply->verify; other has zero. Average
        # rollouts inside t0 first, then give its task half the weight.
        expected=((.5+4/11)/2)/2
        self.assertAlmostEqual(result['sequence']['before']['apply.verify'],expected)

    def test_evidence_reconciles_tasks_rollouts_and_exact_source_actions(self):
        self.populate(5)
        result=self.request()
        self.assertAlmostEqual(sum(t['contribution_to_mean'] for t in result['tasks']),result['aggregate']['delta'])
        self.assertEqual(result['before']['selected_run']['numerator'],1)
        self.assertEqual(result['before']['selected_run']['denominator'],2)
        self.assertEqual(result['before']['match_count'],1)
        pair=result['before']['matches'][0]
        self.assertEqual([p['purpose'] for p in pair],['apply','verify'])
        self.assertTrue(all(p['source_pointer'].startswith('/steps/') for p in pair))
        self.assertEqual(result['after']['matches'],[])
        self.assertEqual(result['after']['selected_run']['value'],0)

    def test_missing_opportunity_rollout_remains_visible_with_unknown_rate(self):
        self.populate()
        empty=self.add('t0','c0',['explore'],seed='single-action')
        result=self.request(before_run=empty['id'])
        self.assertEqual(result['before']['selected_run']['denominator'],0)
        self.assertIsNone(result['before']['selected_run']['value'])
        self.assertEqual(len(result['before']['rollouts']),2)

    def test_all_current_metric_families_have_consistent_drilldown(self):
        self.populate()
        metrics=['purpose.explore','task_relation.unresolved','feedback.unresolved','repeat_rate','goal_assignment_rate','action_count']
        for metric in metrics:
            with self.subTest(metric=metric):
                result=self.request(metric)
                self.assertEqual(result['before']['match_count'],result['before']['selected_run']['numerator'])

    def test_changed_observations_or_cohort_reject_stale_evidence(self):
        self.populate();rows=self.store.list();snapshot=compare(rows)
        self.add('t0','c1',['explore','verify','verify'],seed='new')
        with self.assertRaises(ComparisonChanged):
            evidence(self.store.list(),self.store.get,comparison_id=snapshot['comparison_id'],metric='purpose.verify',reference='c0',checkpoint='c1')
        current=compare(self.store.list())
        def changed(run_id):
            bundle=self.store.get(run_id);bundle['analysis']['metrics']['actions']+=1;return bundle
        with self.assertRaises(ComparisonChanged):
            evidence(self.store.list(),changed,comparison_id=current['comparison_id'],metric='purpose.verify',reference='c0',checkpoint='c1')

    def test_checkpoint_subset_reference_and_context_filters(self):
        self.populate()
        self.add('unmatched','c2',['report'])
        self.add('t0','c0',['explore'],environment_version='v2',seed='different-environment')
        self.assertEqual(compare(self.store.list())['status'],'no_matched_tasks')
        result=compare(self.store.list(),checkpoints=['c0','c1'],reference='c1',environment_version='v1',split='eval',inspector_signature='heuristic')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['reference_checkpoint'],'c1')
        self.assertEqual(result['paired_deltas'][0]['metrics']['transition.apply.verify']['delta'],.5)
        with self.assertRaises(InputError): compare(self.store.list(),checkpoints=['c0','c1'],reference='c2')

    def test_foreign_task_or_rollout_cannot_enter_evidence(self):
        self.populate(2)
        foreign=self.add('other','c0',['report'])
        with self.assertRaises(InputError):self.request(task_id='other')
        with self.assertRaises(InputError):self.request(before_run=foreign['id'])

    def test_pending_review_refresh_cannot_pass_as_an_unreviewed_cohort(self):
        self.populate()
        run=self.store.list()[0]
        event=self.store.get(run['id'])['analysis']['actions'][0]['event_id']
        review={'event_id':event,'field':'mode','value':'explore','reviewer':'test','note':'simulated refresh interruption',
                'evidence_ids':[event],'expected_revision':0}
        from tracker.reviews import validate
        validated=validate(self.store.get(run['id'],raw=True)['run'],review)
        with self.store.connect() as c:
            c.execute('INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)',(run['id'],dumps(validated),'2026-10-06T12:00:00Z'))
        self.assertEqual(compare(self.store.list())['status'],'selective_reviews')


if __name__=='__main__':unittest.main()
