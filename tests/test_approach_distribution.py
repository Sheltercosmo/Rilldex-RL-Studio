"""Conditional approach/report distributions; no provider calls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import behavior_distributions as bd, graph_store, execution_reports as er
from tracker.schema import digest
from tracker.store import Store
from tests.test_work_episodes import example, edge
from tests.test_adaptation_patterns import comparison, saved_graph


def save_run(store, name, step, reports, procedures, task='same-task', metadata=None):
    run, graph, actions=example(tuple(name for _ in reports))
    run['metadata'].update(experiment='approach-followup-controls',task_id=task,training_step=step)
    run['metadata'].update(metadata or {})
    graph['metadata']=run['metadata'];graph['source_hash']=digest(run)
    events={e['id']:e for e in run['events']}
    for node in graph['nodes']:
        if node['kind']=='unit':
            unit=node['properties'];event=events[unit['source']['event_id']]
            unit['source']['source_pointer']=event.get('source_pointer')
            unit['trajectory_id']=event['trajectory_id']
    for earlier,later,procedure in zip(actions,actions[1:],procedures):
        edge(graph,later,earlier,'same_action_target')
        if procedure:comparison(graph,later,earlier,procedure)
    pairs=er.bound_responses(run)
    by_event={response['id']:reports[i] for i,(_,response) in enumerate(pairs)}
    graph['semantic_context']['execution_reports']=er.build(run,lambda request: (
        {'error':{'value':by_event[request['state']['cutoff_event_id']]},'warning':{'value':'not_reported'}},'authored-report'))
    graph=saved_graph(graph);store.add([run])
    with store.connect() as connection:graph_store.save(connection,graph)
    return run,graph


class ApproachDistributionTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=Store(Path(directory.name)/'review.sqlite')

    def snapshot(self,**kw):
        return bd.snapshot(self.store,lens='procedure',a_start=0,a_end=2,b_start=3,b_end=5,**kw)

    def test_full_pipeline_conditions_on_prior_error_and_keeps_unknown_procedure(self):
        run,g=save_run(self.store,'one',0,['reported','not_reported','reported','unresolved','reported'],
                       ['same_procedure','alternative_procedure',None,'same_procedure'])
        d=self.snapshot();f=d['approach_followup'];rows={r['id']:r for r in f['earlier']['rows']}
        self.assertEqual(f['earlier']['total'],2)
        self.assertEqual(rows['same_procedure']['counts']['no_reported_error'],1)
        self.assertEqual(rows['alternative_procedure']['no_prior_error'],1)
        self.assertEqual(rows['unknown']['counts']['followup_unknown'],1)
        self.assertEqual(rows['unknown']['shares']['followup_unknown'],1)
        self.assertEqual(rows['same_procedure']['prior_report_unknown'],1)
        self.assertEqual(f['later']['total'],0)
        self.assertTrue(all(v is None for r in f['later']['rows'] for v in r['shares'].values()))
        self.assertTrue(all(c['graph_id']==g['id'] and c['input_id'] for c in d['cases']))
        self.assertEqual(f['inference_calls'],0)
        self.assertEqual(d,self.snapshot())

    def test_weighting_is_within_approach_and_keeps_unresolved_in_denominator(self):
        save_run(self.store,'short',0,['reported','not_reported'],['same_procedure'])
        save_run(self.store,'long',1,['reported','reported','reported','unresolved'],['same_procedure']*3)
        save_run(self.store,'no-error',2,['not_reported','not_reported'],['same_procedure'])
        equal=self.snapshot()['approach_followup']['earlier']['rows'][0]
        pooled=self.snapshot(weighting='opportunity')['approach_followup']['earlier']['rows'][0]
        self.assertEqual(equal['counts'],{'reported_again':2,'no_reported_error':1,'followup_unknown':1})
        self.assertEqual((equal['total'],equal['eligible_rollouts'],equal['no_prior_error']),(4,2,1))
        self.assertAlmostEqual(equal['shares']['no_reported_error'],.5)
        self.assertAlmostEqual(equal['shares']['reported_again'],1/3)
        self.assertAlmostEqual(pooled['shares']['no_reported_error'],.25)
        self.assertAlmostEqual(sum(equal['shares'].values()),1)

    def test_source_windows_unplaced_and_empty_population(self):
        for name,step in [('zero',0),('end',2),('outside',6),('unplaced',None)]:
            save_run(self.store,name,step,['reported','reported'],['reconfigured_procedure'])
        d=self.snapshot();f=d['approach_followup']
        self.assertEqual((f['overall']['total'],f['earlier']['total'],f['later']['total']),(3,2,0))
        # Missing progress metadata has its own configuration cohort; it is not
        # silently merged with the logged-step cohort.
        other=next(c for c in d['cohorts'] if c['id']!=d['cohort_id'])
        unplaced=self.snapshot(cohort_id=other['id'])
        self.assertEqual(unplaced['unplaced_rollouts'],1)
        self.assertEqual(unplaced['approach_followup']['overall']['total'],1)
        self.assertEqual(unplaced['approach_followup']['earlier']['total'],0)
        self.assertFalse(d['comparable'])
        empty=self.snapshot(experiment='does-not-exist')['approach_followup']
        self.assertEqual(empty['overall']['total'],0)

    def test_task_scope_not_silently_adjusted_and_overlapping_windows_no_delta(self):
        save_run(self.store,'task-a',0,['reported','reported'],['same_procedure'],task='a')
        save_run(self.store,'task-b',1,['reported','not_reported'],['same_procedure'],task='b')
        self.assertEqual(self.snapshot()['approach_followup']['overall']['total'],1)
        d=bd.snapshot(self.store,lens='procedure',population_mode='task_mix',a_start=0,a_end=1,b_start=1,b_end=1)
        f=d['approach_followup']
        self.assertEqual((f['overall']['total'],f['earlier']['total'],f['later']['total']),(2,2,1))
        self.assertEqual(f['population'],'Observed task mix');self.assertFalse(f['task_adjusted'])
        self.assertFalse(d['comparable'])

    def test_unjoined_case_never_supplies_error_absence_or_a_different_pair(self):
        save_run(self.store,'one',0,['reported','not_reported'],['same_procedure'])
        d=self.snapshot();original=deepcopy(d)
        d['cases'][0]['graph_id']='wrong-graph'
        f=bd.approach_followup(d)
        self.assertEqual(f['earlier']['total'],0)
        self.assertEqual(f['earlier']['unavailable_pairs'],1)
        self.assertEqual(self.snapshot(),original)

    def test_refresh_new_report_snapshot_does_not_modify_retained_comparison(self):
        _,g=save_run(self.store,'one',0,['reported','unresolved'],['same_procedure'])
        before=self.snapshot();saved=deepcopy(before)
        g['semantic_context']['execution_reports']['observations'][1].update(error='not_reported',complete_readable_response=True)
        with self.store.connect() as connection:graph_store.save(connection,saved_graph(g))
        after=self.snapshot()
        self.assertNotEqual(before['snapshot_id'],after['snapshot_id']);self.assertEqual(before,saved)
        self.assertEqual(before['approach_followup']['earlier']['rows'][0]['counts']['followup_unknown'],1)
        self.assertEqual(after['approach_followup']['earlier']['rows'][0]['counts']['no_reported_error'],1)


if __name__=='__main__':unittest.main()
