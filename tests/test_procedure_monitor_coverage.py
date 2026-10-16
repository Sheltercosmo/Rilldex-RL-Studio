"""Current eligibility and historical measurement replay must remain distinct."""
import copy
import tempfile
import unittest
from pathlib import Path

from tracker import analysis_metrics as am, adaptation_patterns as ap, work_episodes
from tracker import monitoring, monitor_evidence, graph_store
from tracker.store import Store
from tests.test_adaptation_patterns import example, edge, comparison, saved_graph


class ProcedureMonitorCoverageTests(unittest.TestCase):
    def test_counts_share_distribution_eligibility(self):
        for name, category in [('same_procedure_recurrences', 'same_procedure'),
                               ('reconfigured_recurrences', 'reconfigured_procedure')]:
            for mode in ('selected', 'partial', 'legacy', 'instance', 'future', 'duplicate'):
                with self.subTest(name=name, mode=mode):
                    _, graph, actions = example(('A', 'A', 'B'))
                    edge(graph, actions[1], actions[0], 'same_action_target')
                    m = comparison(graph, actions[1], actions[0], category)
                    if mode == 'partial': m['status'] = 'needs_context_selection'
                    if mode == 'legacy': graph['semantic_context']['work_observations']['method_schema'] = 'work-method-comparison/1'
                    if mode == 'instance': m['work_instance'] = 'unresolved_work'
                    if mode == 'future': m['inspector_context'] = {'source_ranges': [actions[2]['source']]}
                    if mode == 'duplicate': graph['semantic_context']['work_observations']['method_observations'].append(copy.deepcopy(m))
                    output = ap.project(graph)
                    current = am.measure(output, am.catalog()[name])
                    self.assertEqual(current['value'], int(mode == 'selected'))
                    self.assertEqual(current['coverage']['procedure_compared'], int(mode == 'selected'))
                    self.assertEqual(current['coverage']['procedure_unknown'], int(mode != 'selected'))

    def test_historical_receipt_survives_current_replacement(self):
        run, graph, actions = example(('A', 'A'))
        edge(graph, actions[1], actions[0], 'same_action_target')
        comparison(graph, actions[1], actions[0])['status'] = 'needs_context_selection'
        graph = saved_graph(graph)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'tracker.sqlite'); store.add([run])
            with store.connect() as conn: graph_store.save(conn, graph)
            name = 'same_procedure_recurrences'
            raw = {'name': 'Same procedure', 'kind': 'analysis', 'observer': 'test',
                   'analysis': {'measure': name, 'version': am.catalog(legacy=True)[name]['version']}}
            old = monitoring.create(store, raw); monitoring.sync(store)
            before = monitoring.values(store, old['id'], {run['id']})[run['id']]
            self.assertEqual(before['value'], 1)
            receipt = monitor_evidence.read(store, before['id'])
            self.assertEqual(receipt['explanation']['definition_notice']['kind'], 'historical_procedure_rules')
            raw['analysis'] = {'measure': name}
            current = monitoring.create(store, raw, replace=old['id']); monitoring.sync(store)
            after = monitoring.values(store, current['id'], {run['id']})[run['id']]
            self.assertNotEqual(old['id'], current['id'])
            self.assertEqual(after['value'], 0)
            self.assertEqual(after['coverage']['procedure_unknown'], 1)
            self.assertEqual(before, monitoring.values(store, old['id'], {run['id']})[run['id']])
            self.assertEqual(receipt['measurement'], monitor_evidence.read(store, before['id'])['measurement'])
            self.assertNotIn('definition_notice', monitor_evidence.read(store, after['id'])['explanation'])
            rows = {m['id']: m for m in monitoring.snapshot(store)['monitors']}
            self.assertFalse(rows[old['id']]['enabled'])
            self.assertIn('definition_notice', rows[old['id']])
            self.assertEqual(rows[current['id']]['coverage']['procedure_comparisons'],
                             {'total': 1, 'compared': 0, 'unresolved': 1, 'observed_rollouts': 1, 'total_rollouts': 1})

    def test_coverage_keeps_unknown_null_and_missing_rollouts_separate(self):
        spec = am.catalog()['procedure_change_fraction']
        monitor = {'kind': 'analysis', 'analysis_definition': spec}
        runs = [{'id': str(i), 'adapter': 'test', 'metadata': {'experiment': 'x', 'training_step': 4}} for i in range(4)]
        rows = {
            '0': {'status': 'available', 'value': .5, 'numerator': 1, 'denominator': 2,
                  'coverage': {'recurrences': 3, 'procedure_compared': 2, 'procedure_unknown': 1}},
            '1': {'status': 'unavailable', 'value': None,
                  'coverage': {'recurrences': 2, 'procedure_compared': 0, 'procedure_unknown': 2}},
            '2': {'status': 'available', 'value': 1, 'numerator': 1, 'denominator': 1},
        }
        chart = monitoring.chart(monitor, runs, rows)
        expected = {'total': 5, 'compared': 2, 'unresolved': 3, 'observed_rollouts': 2, 'total_rollouts': 4}
        self.assertEqual(chart['coverage']['procedure_comparisons'], expected)
        self.assertEqual(chart['series'][0]['bins'][0]['procedure_comparisons'], expected)
        self.assertEqual(chart['series'][0]['bins'][0]['value'], 2 / 3)
        self.assertEqual(chart['series'][0]['points'][1]['procedure_comparisons']['unresolved'], 2)
        runs[0]['metadata'] = {}
        chart = monitoring.chart(monitor, runs, rows)
        self.assertEqual(chart['unplaced_points'][0]['procedure_comparisons']['compared'], 2)
        self.assertEqual(chart['coverage']['procedure_comparisons'], expected)

    def test_invalid_coverage_is_missing_not_zero_opportunities(self):
        for coverage in ({}, {'recurrences': 1, 'procedure_compared': True, 'procedure_unknown': 0},
                         {'recurrences': 1, 'procedure_compared': 2, 'procedure_unknown': -1},
                         {'recurrences': 3, 'procedure_compared': 1, 'procedure_unknown': 1}):
            self.assertEqual(monitoring.procedure_coverage({'coverage': coverage})['observed_rollouts'], 0)
        empty = {'recurrences': 0, 'procedure_compared': 0, 'procedure_unknown': 0}
        self.assertEqual(monitoring.procedure_coverage({'coverage': empty})['observed_rollouts'], 1)


if __name__ == '__main__': unittest.main()
