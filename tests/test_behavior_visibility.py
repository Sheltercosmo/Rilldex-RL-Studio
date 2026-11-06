"""Recorded visibility must survive maps, repeated work and behavior measures."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import action_comparison, adaptation_patterns, analysis_metrics, repeated_work, work_episodes
from tracker import behavior_distributions, execution_reports, graph_store, monitoring, monitor_evidence
from tracker.schema import digest
from tracker.store import Store
from tests.test_work_episodes import example, edge
from tests.test_approach_feedback import fixture


MARKERS = ({'agent_visible': False}, {'agent_visibility': 'not_established'})


def mark(graph, event_id, marker):
    event = next(n for n in graph['nodes'] if n['id'] == 'event:' + event_id)
    event['properties'].update(marker)


class BehaviorVisibilityTests(unittest.TestCase):
    def test_private_endpoints_cannot_supply_recurrence_or_input_differences(self):
        for marker in MARKERS:
            for endpoint in (0, 1):
                with self.subTest(marker=marker, endpoint=endpoint):
                    _, graph, actions = example(('A', 'A'))
                    edge(graph, actions[1], actions[0], 'same_action_target')
                    mark(graph, actions[endpoint]['source']['event_id'], marker)
                    before = deepcopy(graph)
                    result = work_episodes.project(graph)
                    self.assertEqual(result['episodes'], [])
                    self.assertEqual(result['counts']['represented_actions'], 1)
                    self.assertEqual(action_comparison.compare(graph, actions[0]['id'], actions[1]['id'])['status'], 'unavailable')
                    self.assertEqual(graph, before)

    def test_private_intervening_action_remains_a_gap_without_its_content(self):
        for marker in MARKERS:
            with self.subTest(marker=marker):
                _, graph, actions = example(('A', 'HIDDEN_OPERATION', 'A'))
                edge(graph, actions[2], actions[0], 'same_action_target')
                mark(graph, actions[1]['source']['event_id'], marker)
                result = work_episodes.project(graph)
                episode = result['episodes'][0]
                self.assertEqual(episode['category'], 'interrupted')
                self.assertEqual(episode['intervening'][0]['unit_id'], None)
                self.assertNotIn('HIDDEN_OPERATION', str(episode))
                self.assertEqual(result['counts']['recorded_actions'], 3)

    def test_private_followup_is_unknown_in_comparisons_and_measures(self):
        for marker in MARKERS:
            with self.subTest(marker=marker):
                _, graph, _, reports = fixture(('reported', 'not_reported'))
                response = reports['observations'][1]['response_event_id']
                baseline = adaptation_patterns.project(graph)
                self.assertEqual(baseline['records'][0]['error_followup']['category'], 'no_reported_error')
                mark(graph, response, marker)
                repeated = repeated_work.project(graph)['rows'][0]
                self.assertIsNone(repeated['inputs_and_feedback_match'])
                self.assertEqual(repeated['feedback']['current']['node_ids'], [])
                self.assertEqual(repeated['feedback']['current']['excluded_node_ids'], ['event:' + response])
                projection = adaptation_patterns.project(graph)
                row = projection['records'][0]
                self.assertEqual(row['response_context']['current']['records'], [])
                self.assertEqual(row['error_followup']['category'], 'followup_unknown')
                measured = analysis_metrics.measure(projection, analysis_metrics.catalog()['error_report_repeat_fraction'])
                self.assertIsNone(measured['value'])
                self.assertEqual((measured['denominator'], measured['opportunities'], measured['unknown']), (0, 1, 1))

    def test_private_prior_feedback_cannot_establish_an_error_opportunity(self):
        for marker in MARKERS:
            with self.subTest(marker=marker):
                _, graph, _, reports = fixture()
                mark(graph, reports['observations'][0]['response_event_id'], marker)
                projection = adaptation_patterns.project(graph)
                self.assertEqual(projection['records'][0]['response_context']['previous']['records'], [])
                self.assertEqual(projection['records'][0]['error_followup']['category'], 'unknown')

    def test_saved_native_visibility_agrees_across_distributions_and_monitor_receipts(self):
        for marker in MARKERS:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                run, original, actions, reports = fixture()
                response_id = reports['observations'][1]['response_event_id']
                next(e for e in run['events'] if e['id'] == response_id).update(marker)
                reports = execution_reports.build(run, lambda request: (
                    {'error': {'value': 'reported'}, 'warning': {'value': 'not_reported'}},
                    'authored-report'))
                self.assertEqual(len(reports['observations']), 1)
                document = {
                    'schema': 'semantic-unit-map/1', 'source_hash': digest(run),
                    'units': [n['properties'] for n in original['nodes'] if n['kind'] == 'unit'],
                    'relations': [{'from': actions[1]['id'], 'to': actions[0]['id'], 'type': 'same_action_target'}],
                    'execution_reports': reports,
                }
                graph = graph_store.build(run, {'observer': {'id': 'test', 'label': 'Test'}, 'document': document})
                store = Store(Path(tmp) / 'study.sqlite')
                store.add([run])
                with store.connect() as connection:
                    graph_store.save(connection, graph)
                monitor = monitoring.create(store, dict(name='Errors after retry', kind='analysis',
                    observer='test', analysis={'measure': 'error_report_repeat_fraction'}))
                self.assertEqual(monitoring.sync(store, [monitor['id']])['errors'], 0)
                value = monitoring.values(store, monitor['id'], [run['id']])[run['id']]
                self.assertIsNone(value['value'])
                self.assertEqual((value['denominator'], value['opportunities'], value['unknown']), (0, 1, 1))
                revisit = behavior_distributions.work_inputs(store, 'revisit', [run['id']])
                self.assertEqual(revisit[0]['records'][0]['category'], 'feedback_unknown')
                procedure = behavior_distributions.work_inputs(store, 'procedure', [run['id']])
                row = procedure[0]['records'][0]
                self.assertEqual(row['error_followup']['category'], 'followup_unknown')
                self.assertEqual(row['response_context']['current']['records'], [])
                receipt = monitor_evidence.read(store, value['id'])
                reopened = monitor_evidence.read(Store(store.path), value['id'])
                for key in ('graph', 'explanation', 'measurement'):
                    self.assertEqual(reopened[key], receipt[key])


if __name__ == '__main__':
    unittest.main()
