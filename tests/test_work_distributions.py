import copy
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tracker import behavior_distributions as distributions, graph_store
from tracker.schema import digest
from tracker.store import Store
from tests.test_work_episodes import example, edge
from tests.test_adaptation_patterns import comparison, saved_graph


class WorkDistributionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'tracker.sqlite')

    def save(self,run,graph,step=None):
        run['metadata'].update(experiment='authored-control',task_id='same-task',training_step=step)
        graph['metadata']=run['metadata'];graph['source_hash']=digest(run)
        graph=saved_graph(graph);self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,graph)
        return graph

    def test_action_denominator_and_exact_path_drilldown(self):
        run,g,a=example(('A','A','B','A'))
        edge(g,a[1],a[0],'same_action_target');edge(g,a[3],a[1],'same_action_target')
        g=self.save(run,g)
        result=distributions.snapshot(self.store,lens='recurrence')
        self.assertEqual(result['distribution']['counts'],{'continued':1,'returned':1,'interrupted':0,'unknown':2})
        self.assertEqual({c['id'] for c in result['cases']},{e['id'] for e in run['events'] if e['kind']=='action'})
        case=next(c for c in result['cases'] if c['category']=='returned')
        params=parse_qs(urlparse(case['map_url']).query)
        self.assertEqual(params['graph'],[g['id']]);self.assertEqual(params['level'],['work'])
        self.assertEqual(params['work_episode'],[case['episode']['id']])
        self.assertEqual(params['focus_unit'],[a[3]['id']]);self.assertTrue(case['edge_ids'])
        self.assertEqual(result['bins'],[])
        with self.store.connect() as c:count=c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0]
        self.assertEqual(result,distributions.snapshot(self.store,lens='recurrence'))
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0],count)
        self.assertEqual(result['inference_calls'],0)

    def test_missing_middle_action_stays_in_denominator_and_blocks_return_claim(self):
        run,g,a=example();edge(g,a[2],a[0],'same_action_target')
        g['nodes']=[n for n in g['nodes'] if n['id']!=a[1]['id']]
        g['edges']=[e for e in g['edges'] if a[1]['id'] not in (e['source'],e['target'])]
        self.save(run,g);result=distributions.snapshot(self.store,lens='recurrence')
        self.assertEqual(result['distribution']['counts'],{'continued':0,'returned':0,'interrupted':1,'unknown':2})
        missing=next(c for c in result['cases'] if c['unit_id'] is None)
        self.assertEqual(missing['category'],'unknown')
        self.assertEqual(parse_qs(urlparse(missing['map_url']).query)['focus_unit'],['event:'+a[1]['source']['event_id']])
        self.assertEqual(result['points'][0]['work_coverage']['represented_actions'],2)

    def test_procedure_uses_exact_pair_observation_not_payload_and_keeps_unknowns(self):
        run,g,a=example(('A','A','A','A'))
        for previous,current in zip(a,a[1:]):edge(g,current,previous,'same_action_target')
        comparison(g,a[1],a[0],'same_procedure');comparison(g,a[2],a[1],'alternative_procedure')
        self.save(run,g,0);result=distributions.snapshot(self.store,lens='procedure')
        self.assertEqual(result['distribution']['counts'],{'same_procedure':1,'reconfigured_procedure':0,'alternative_procedure':1,'unknown':1})
        self.assertAlmostEqual(result['distribution']['shares']['alternative_procedure'],1/3)
        self.assertEqual(result['points'][0]['work_coverage']['procedure_compared'],2)
        self.assertEqual(result['points'][0]['step'],0)
        self.assertTrue(all(c['episode'] and c['edge_ids'] for c in result['cases']))

    def test_identity_review_without_recurrence_is_not_zero_procedure_change(self):
        run,g,a=example(('A',));g['semantic_context']['work_observations']={'identity_reviews':[{'action_unit_id':a[0]['id'],'status':'no_prior_selected_action'}]}
        self.save(run,g);result=distributions.snapshot(self.store,lens='procedure')
        self.assertEqual((result['observed_rollouts'],result['distribution']['eligible_rollouts']),(1,0))
        self.assertTrue(all(v is None for v in result['distribution']['shares'].values()))
        self.assertEqual(result['points'][0]['total'],0)
        self.assertEqual(result['observation_readiness']['current'],1)
        self.assertEqual(result['observation_readiness']['no_opportunities'],1)
        self.assertEqual(result['observation_members'][0]['status'],'no_opportunities')

    def test_uninspected_identity_does_not_supply_a_zero_recurrence_population(self):
        run,g,_=example(('A',));self.save(run,g)
        self.assertEqual(distributions.snapshot(self.store,lens='procedure')['observed_rollouts'],0)
        recurrence=distributions.snapshot(self.store,lens='recurrence')
        self.assertEqual(recurrence['distribution']['counts']['unknown'],1)

    def test_latest_graph_replaces_old_results_without_recounting(self):
        run,g,a=example(('A','A'));self.save(run,g)
        self.assertEqual(distributions.snapshot(self.store,lens='recurrence')['distribution']['counts']['unknown'],2)
        edge(g,a[1],a[0],'same_action_target');self.save(run,g)
        result=distributions.snapshot(self.store,lens='recurrence')
        self.assertEqual((result['observed_rollouts'],result['distribution']['total']),(1,2))
        self.assertEqual(result['distribution']['counts']['continued'],1)

    def test_stale_and_nonsemantic_graphs_are_not_projected(self):
        run,g,a=example();self.save(run,g)
        stale=copy.deepcopy(g);stale['observer']='stale';stale['source_hash']='different-source'
        nonsemantic=copy.deepcopy(g);nonsemantic['observer']='state-only';nonsemantic['coverage']['semantic_relations']='unavailable'
        with self.store.connect() as c:
            for value in (stale,nonsemantic):graph_store.save(c,saved_graph(value))
        result=distributions.snapshot(self.store,lens='recurrence')
        self.assertEqual([r['id'] for r in result['observers']],['test'])
        stale_view=distributions.snapshot(self.store,lens='recurrence',observer='stale')
        self.assertEqual(stale_view['observation_members'][0]['status'],'source_mismatch')
        self.assertEqual(stale_view['population'],1)
        layer_view=distributions.snapshot(self.store,lens='recurrence',observer='state-only')
        self.assertEqual(layer_view['observation_members'][0]['status'],'layer_unavailable')

    def test_training_windows_use_actual_coordinates_with_missing_observation_gap(self):
        run,g,a=example(('A','A'));edge(g,a[1],a[0],'same_action_target');self.save(run,g,1)
        run,g,a=example(('B','B'));run['metadata'].update(experiment='authored-control',task_id='same-task',training_step=2)
        self.store.add([run])
        run,g,a=example(('C','D','C'));edge(g,a[2],a[0],'same_action_target');self.save(run,g,3)
        result=distributions.snapshot(self.store,lens='recurrence')
        self.assertEqual([b['step'] for b in result['bins']],[1,2,3])
        self.assertIsNone(result['bins'][1]['shares']['returned'])
        self.assertTrue(result['comparable'])
        self.assertAlmostEqual(next(d['pp'] for d in result['deltas'] if d['id']=='returned'),100/3)


if __name__=='__main__':unittest.main()
