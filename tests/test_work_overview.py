"""Projection fidelity controls; these authored bindings are not accuracy data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import action_reading, work_navigation, work_order, work_overview, work_subjects
from tracker.schema import InputError
from tracker.store import Store
from test_work_subjects import fixture, annotation
from test_work_episodes import example, edge
from test_work_scope_audit import case as disputed_case
from test_parallel_work_returns import fixture as parallel_fixture, graph as parallel_graph


class WorkOverviewTests(unittest.TestCase):
    def test_reasoning_only_flow_keeps_each_return_and_exact_deep_link(self):
        run, graph, units = fixture(one_event=True)
        graph = work_subjects.fork(graph, annotation(graph, units))
        before = deepcopy(graph)
        with tempfile.TemporaryDirectory() as directory, patch('tracker.jev.JevClient._post', side_effect=AssertionError('No inference')):
            store = Store(Path(directory)/'source.sqlite'); store.add([run])
            result = action_reading.flow(store, run['id'], graph=graph)
        self.assertEqual(result['coverage']['total'], 0)
        work = result['work']; self.assertTrue(work['available'])
        self.assertEqual(work['counts']['assigned'], 3)
        self.assertEqual(work['counts']['returned'], 1)
        self.assertEqual(work['episodes'][0]['id'], work_navigation.project(graph)['episodes'][0]['id'])
        self.assertEqual(work['episodes'][0]['current']['unit_id'], units[-1]['id'])
        self.assertEqual(work['episodes'][0]['current']['start'], units[-1]['source']['start'])
        self.assertEqual(graph, before)

    def test_equal_commands_without_identity_do_not_create_work_return(self):
        run, graph, _ = example(('A','B','A'))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'source.sqlite'); store.add([run])
            result = action_reading.flow(store, run['id'], graph=graph)
        self.assertIsNotNone(result['actions'][-1]['same_dispatch_as'])
        self.assertEqual(result['actions'][-1]['work_returns'], [])
        self.assertFalse(result['work']['available'])
        self.assertEqual(result['work']['counts']['assigned'], 0)

    def test_different_commands_can_return_when_saved_identity_supports_it(self):
        run, graph, units = example(('read initial report','check another issue','open revised report'))
        edge(graph, units[2], units[0], 'same_action_target')
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'source.sqlite'); store.add([run])
            result = action_reading.flow(store, run['id'], graph=graph)
        self.assertIsNone(result['actions'][-1]['same_dispatch_as'])
        self.assertEqual(len(result['actions'][-1]['work_returns']), 1)
        self.assertEqual(result['actions'][-1]['work_returns'][0], result['work']['episodes'][0]['id'])

    def test_missing_identity_is_not_a_supported_return(self):
        _, graph, units = fixture()
        graph = work_subjects.fork(graph, annotation(graph, units, ('A',None,'A')))
        result = work_overview.project(graph)
        self.assertEqual(result['counts']['returned'], 0)
        self.assertEqual(result['counts']['interrupted'], 1)
        self.assertEqual(result['counts']['assigned'], 2)
        self.assertEqual(result['counts']['positions'], 3)

    def test_conflicting_saved_memberships_are_visible_but_not_counted_as_returns(self):
        graph, _, _ = disputed_case()
        result = work_overview.project(graph)
        self.assertEqual(result['counts']['disputed'], 1)
        self.assertEqual(result['counts']['continued'], 0)
        self.assertEqual(result['episodes'][0]['state'], 'disputed')
        self.assertEqual(result['episodes'][0]['category'], 'continued')

    def test_parallel_policy_and_exact_episode_identifiers_are_preserved(self):
        run, units = parallel_fixture(); graph = parallel_graph(run, units)
        old = work_overview.project(graph)
        current = work_overview.project(graph, recurrence_order=work_order.VERSION)
        self.assertEqual(old['counts']['interrupted'], 1)
        self.assertEqual(current['counts']['returned'], 1)
        self.assertEqual(current['episodes'][0]['ordering']['status'], 'bracketed_parallel')
        self.assertEqual(current['episodes'][0]['id'], work_navigation.project(graph, recurrence_order=work_order.VERSION)['episodes'][0]['id'])
        self.assertNotEqual(old['episodes'][0]['id'], current['episodes'][0]['id'])

    def test_overview_cannot_mix_different_source_snapshots(self):
        run, graph, units = fixture(); graph['source_hash'] = 'different'
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'source.sqlite'); store.add([run])
            with self.assertRaisesRegex(InputError, 'same rollout source'):
                action_reading.flow(store, run['id'], graph=graph)

