import copy
import tempfile
import unittest
from pathlib import Path

from tracker import adaptation_patterns as ap, analysis_metrics as am, graph_store as gs
from tracker import investigation_plans as plans, monitoring, monitor_evidence
from tracker.schema import digest, InputError
from tracker.store import Store
from tests.test_work_episodes import example, edge, method, unit_at


def comparison(g, current, previous, selected='same_procedure', **kw):
    g['semantic_context']['work_observations']['method_schema'] = 'work-method-comparison/3'
    return method(g, current, previous, selected, status='selected', work_instance='same_work_instance',
                  request='request-current', work_request='request-instance', **kw)


def correction(run, g, actions, timing='before', **kw):
    via = actions[1] if timing == 'before' else actions[-1]
    event_index = next(i for i, e in enumerate(run['events']) if e['id'] == via['source']['event_id'])
    declaration = unit_at(g, run['events'][event_index - 1]['id'])
    return edge(g, declaration, actions[0], 'adjustment_before_retry',
                via_action=via['id'], retry_unit_id=actions[-1]['id'], work_text='Correct the input',
                scope='preparation_for_shared_work' if timing == 'before' else 'retry_dispatch', **kw)


def saved_graph(g):
    value = {k: v for k, v in g.items() if k != 'id'}
    value['edges'].sort(key=lambda e: e['id'])
    return {'id': 'graph-' + digest(value), **value}


class AdaptationTests(unittest.TestCase):
    def test_same_dispatch_after_separate_correction_is_not_a_method_switch(self):
        run, g, a = example(); edge(g, a[-1], a[0], 'same_action_target')
        comparison(g, a[-1], a[0]); corr = correction(run, g, a)
        before = copy.deepcopy(g); result = ap.project(g); row = result['records'][0]
        self.assertEqual(g, before)
        self.assertEqual((row['procedure'], row['correction_location']), ('same_procedure', 'before_recurrence'))
        self.assertEqual(row['preparation_edge_ids'], [corr['id']])
        self.assertEqual(result['procedure_change']['value'], 0)
        self.assertEqual(am.measure(result, am.catalog()['resume_after_preparation'])['value'], 1)

    def test_actual_jev_alternative_option_counts_not_just_a_similar_invented_name(self):
        _, g, a = example(('A', 'A')); edge(g, a[-1], a[0], 'same_action_target')
        m = comparison(g, a[-1], a[0], 'alternative_procedure')
        result = ap.project(g)
        self.assertEqual(result['procedure_change']['value'], 1)
        self.assertEqual(am.measure(result, am.catalog()['different_procedure_recurrences'])['value'], 1)
        m['comparison'] = 'different_procedure'
        self.assertIsNone(ap.project(g)['procedure_change']['value'])

    def test_missing_links_are_not_no_correction_and_unknown_is_not_unchanged(self):
        _, g, a = example(); edge(g, a[-1], a[0], 'same_action_target')
        result = ap.project(g)
        self.assertEqual(result['records'][0]['correction_location'], 'not_established')
        self.assertEqual(result['records'][0]['procedure'], 'unresolved')
        self.assertEqual(result['procedure_change'], {'numerator': 0, 'denominator': 0, 'opportunities': 1, 'unknown': 1, 'value': None})
        self.assertEqual(sum(c['count'] for c in result['cells']), 1)

    def test_partial_legacy_future_duplicate_and_unresolved_instance_are_not_comparisons(self):
        for mode in ['partial', 'legacy', 'future', 'duplicate', 'instance']:
            run, g, a = example(('A', 'A', 'B')); edge(g, a[1], a[0], 'same_action_target')
            m = comparison(g, a[1], a[0])
            if mode == 'partial': m['status'] = 'needs_context_selection'
            elif mode == 'legacy': g['semantic_context']['work_observations']['method_schema'] = 'work-method-comparison/1'
            elif mode == 'future': m['inspector_context'] = {'source_ranges': [a[2]['source']]}
            elif mode == 'duplicate': g['semantic_context']['work_observations']['method_observations'].append(copy.deepcopy(m))
            else: m['work_instance'] = 'unresolved_work'
            self.assertEqual(ap.project(g)['coverage']['procedure_unknown'], 1, mode)

    def test_correction_location_is_exclusive_and_retains_all_witnesses(self):
        run, g, a = example(); edge(g, a[-1], a[0], 'same_action_target')
        comparison(g, a[-1], a[0], 'reconfigured_procedure')
        left = correction(run, g, a); right = correction(run, g, a, 'at')
        result = ap.project(g); row = result['records'][0]
        self.assertEqual(row['correction_location'], 'both')
        self.assertEqual(row['preparation_edge_ids'], [left['id']])
        self.assertEqual(row['retry_correction_edge_ids'], [right['id']])
        self.assertEqual(sum(c['count'] for c in result['cells']), 1)
        self.assertEqual(result['procedure_change']['value'], 1)

    def test_unscoped_future_or_other_retry_correction_does_not_count(self):
        for mode in ['scope', 'future', 'retry']:
            run, g, a = example(('A', 'B', 'A', 'C')); edge(g, a[2], a[0], 'same_action_target')
            comparison(g, a[2], a[0]); c = correction(run, g, a[:3])
            if mode == 'scope': c['properties']['scope'] = 'unspecified'
            elif mode == 'future': c['properties']['evidence'] = [a[3]['source']]
            else: c['properties']['retry_unit_id'] = a[3]['id']
            self.assertEqual(ap.project(g)['records'][0]['correction_location'], 'not_established')

    def test_cohort_shares_weight_rollouts_not_the_number_of_episodes(self):
        _, g1, a = example(('A', 'A')); edge(g1, a[1], a[0], 'same_action_target')
        comparison(g1, a[1], a[0], 'alternative_procedure'); r1 = ap.project(g1)
        _, g2, a = example(('B', 'B', 'B', 'B')); g2['run_id'] = 'other'
        for before, after in zip(a, a[1:]):
            edge(g2, after, before, 'same_action_target'); comparison(g2, after, before)
        r2 = ap.project(g2)
        result = ap.compare([r1, r2], [r1['run_id'], r2['run_id']], ['missing'])
        group = result['groups']['focus']
        cell = next(c for c in group['cells'] if c['procedure'] == 'alternative_procedure' and c['correction_location'] == 'not_established')
        self.assertEqual(cell['count'], 1); self.assertEqual(cell['mean_rollout_share'], .5)
        self.assertEqual(group['procedure_change']['value'], .25)
        self.assertAlmostEqual(sum(c['mean_rollout_share'] for c in group['cells']), 1)
        self.assertIsNone(result['groups']['reference']['cells'][0]['mean_rollout_share'])

    def test_no_annotations_remain_unavailable_and_reviewed_zero_is_distinct(self):
        _, g, a = example(('A',)); result = ap.project(g)
        self.assertFalse(result['observed'])
        self.assertIsNone(am.measure(result, am.catalog()['resume_after_preparation'])['value'])
        g['semantic_context']['work_observations']['identity_reviews'] = [{'action_unit_id': a[0]['id'], 'status': 'no_prior_selected_action'}]
        result = ap.project(g)
        self.assertEqual(am.measure(result, am.catalog()['resume_after_preparation'])['value'], 0)
        self.assertIsNone(am.measure(result, am.catalog()['procedure_change_fraction'])['value'])

    def test_plan_cache_monitor_arithmetic_and_evidence_reconcile(self):
        run, g, a = example(); edge(g, a[-1], a[0], 'same_action_target')
        comparison(g, a[-1], a[0], 'reconfigured_procedure'); correction(run, g, a, 'at')
        g = saved_graph(g)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'tracker.sqlite'); store.add([run])
            with store.connect() as c: gs.save(c, g)
            plan = {'schema': plans.VERSION, 'nodes': [{'name': 'a', 'op': 'adaptation_patterns', 'inputs': [],
                    'params': {'run_id': run['id'], 'source_hash': digest(run), 'graph_id': g['id']}},
                    {'name': 'c', 'op': 'compare_adaptation', 'inputs': ['a'], 'params': {'focus': [run['id']], 'reference': []}}]}
            first = plans.execute(store, plan); again = plans.execute(store, plan)
            self.assertEqual(first['id'], again['id']); self.assertEqual(again['execution']['cache_hits'], 2)
            monitor = monitoring.create(store, {'name': 'Change fraction', 'kind': 'analysis', 'observer': 'test',
                                                'analysis': {'measure': 'procedure_change_fraction'}})
            monitoring.sync(store)
            v = monitoring.values(store, monitor['id'], {run['id']})[run['id']]
            self.assertEqual((v['value'], v['numerator'], v['denominator'], v['unknown']), (1, 1, 1, 0))
            receipt = monitor_evidence.read(store, v['id'])
            self.assertEqual(len(receipt['explanation']['analysis_cases']), 1)
            self.assertEqual(receipt['explanation']['analysis_cases'][0]['adaptation']['procedure'], 'reconfigured_procedure')
            broken = copy.deepcopy(plan); broken['nodes'][0]['params']['source_hash'] = 'wrong'
            with self.assertRaises(InputError): plans.execute(store, broken)


if __name__ == '__main__': unittest.main()
