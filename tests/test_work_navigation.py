import copy
import tempfile
import unittest
from pathlib import Path
from tracker import work_navigation as nav, graph_store, investigation_plans as plans
from tracker.schema import digest, InputError
from tracker.store import Store
from tests.test_work_episodes import example, edge, unit_at, method


class WorkNavigationTests(unittest.TestCase):
    def test_only_supported_consecutive_visits_collapse(self):
        _, g, a = example(('A', 'A', 'B', 'A'))
        edge(g, a[1], a[0], 'same_action_target'); edge(g, a[3], a[1], 'same_action_target')
        out = nav.project(g)
        self.assertEqual([v['positions'] for v in out['visits']], [[1, 2], [3], [4]])
        self.assertEqual([i for v in out['visits'] for i in v['unit_ids']], [u['id'] for u in a])
        returns = [e for e in out['links'] if e['type'] == 'same_work_return']
        self.assertEqual(len(returns), 2); self.assertEqual(returns[0]['source'], returns[0]['target'])
        self.assertNotEqual(returns[1]['source'], returns[1]['target'])

    def test_identical_text_without_identity_stays_separate(self):
        _, g, a = example(('A', 'A'))
        out = nav.project(g)
        self.assertEqual(len(out['visits']), 2)
        self.assertFalse(any(e['type'] == 'same_work_return' for e in out['links']))
        self.assertNotIn('new_work', str(out)); self.assertNotIn('exploration_count', out['counts'])

    def test_missing_action_keeps_axis_and_interrupts_return(self):
        _, g, a = example(); edge(g, a[2], a[0], 'same_action_target')
        g['nodes'] = [n for n in g['nodes'] if n['id'] != a[1]['id']]
        out = nav.project(g)
        self.assertEqual([v['positions'] for v in out['visits']], [[1], [2], [3]])
        self.assertEqual(out['visits'][1]['unit_ids'], [])
        self.assertEqual(next(e for e in out['links'] if e['type'] == 'same_work_return')['category'], 'interrupted')

    def test_correction_connection_retains_actual_operation_and_declaration(self):
        run, g, a = example(); edge(g, a[2], a[0], 'same_action_target')
        declaration = unit_at(g, run['events'][3]['id'])
        source = edge(g, declaration, a[0], 'adjustment_before_retry', via_action=a[1]['id'],
                      retry_unit_id=a[2]['id'], cutoff=a[2]['source'], work_text='Repair a prerequisite')
        out = nav.project(g); link = next(e for e in out['links'] if e['type'] == 'attempted_correction_for')
        self.assertEqual(link['source'], out['visits'][1]['id']); self.assertEqual(link['target'], out['visits'][0]['id'])
        self.assertEqual(link['declaration_unit_id'], declaration['id']); self.assertEqual(link['edge_ids'], [source['id']])

    def test_method_dispute_and_future_evidence_do_not_create_return(self):
        _, g, a = example(); edge(g, a[2], a[0], 'same_action_target')
        method(g, a[2], a[0], 'different_work')
        self.assertFalse(any(e['type'] == 'same_work_return' for e in nav.project(g)['links']))
        _, g, a = example(('A', 'A', 'B')); edge(g, a[1], a[0], 'same_action_target', evidence=[a[2]['source']])
        self.assertEqual(len(nav.project(g)['visits']), 3)

    def test_scope_change_preserves_visits_and_shared_membership(self):
        run, g, a = example(('A', 'A')); edge(g, a[1], a[0], 'same_action_target')
        first = unit_at(g, run['events'][0]['id']); later = unit_at(g, run['events'][3]['id'])
        for sid, u in [('scope:1', first), ('scope:2', later)]:
            g['nodes'].append({'id': sid, 'kind': 'work_scope', 'properties': {'source': u['source'], 'text': sid}})
        edge(g, a[0], 'scope:1', 'in_work_scope'); edge(g, a[1], 'scope:1', 'in_work_scope'); edge(g, a[1], 'scope:2', 'in_work_scope')
        out = nav.project(g); self.assertEqual(len(out['visits']), 2)
        self.assertEqual(out['visits'][1]['scope_ids'], ['scope:1', 'scope:2'])
        edge(g, a[0], 'scope:2', 'in_work_scope')
        self.assertEqual(nav.project(g)['visits'][0]['scope_ids'], ['scope:1'])

    def test_parallel_lanes_do_not_create_order_or_identity(self):
        _, g, a = example(); edge(g, a[2], a[0], 'same_action_target')
        for n in g['nodes']:
            if n['kind'] == 'event' and n['properties']['id'] == a[1]['source']['event_id']:
                n['properties']['trajectory_id'] = 'other'
        out = nav.project(g); self.assertEqual(len(out['paths']), 2)
        lookup = {v['id']: v['trajectory_id'] for v in out['visits']}
        self.assertTrue(all(lookup[e['source']] == lookup[e['target']] for e in out['links']))

    def test_projection_is_cached_without_new_inference_and_input_is_immutable(self):
        run, g, a = example(); edge(g, a[2], a[0], 'same_action_target'); before = copy.deepcopy(g)
        nav.project(g); self.assertEqual(g, before)
        g.pop('id'); g['edges'].sort(key=lambda e:e['id']); g = {'id': 'graph-' + digest(g), **g}
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'test.sqlite'); store.add([run])
            with store.connect() as c: graph_store.save(c, g)
            plan = {'schema': plans.VERSION, 'nodes': [{'name': 'navigation', 'op': 'work_navigation', 'inputs': [],
                'params': {'graph_id': g['id'], 'run_id': run['id'], 'source_hash': digest(run)}}]}
            first = plans.execute(store, plan); second = plans.execute(store, plan)
            self.assertEqual(first['outputs'], second['outputs']); self.assertEqual(second['execution']['cache_hits'], 1)
            self.assertEqual(second['execution']['inference_calls'], 0)
            plan['nodes'][0]['params']['source_hash'] = 'changed'
            with self.assertRaises(InputError): plans.execute(store, plan)
