import tempfile
import unittest
from pathlib import Path

from tracker import graph_store, map_inspection
from tracker.schema import InputError
from tracker.store import Store
from test_recovery_windows import captured, check, change


class MapInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')
        self.run = captured([check(), change(), check('passed', version='2'), check('passed')])
        self.store.add([self.run])
        self.graph = graph_store.build(self.run)

    def test_recorded_checks_reuse_cached_operators_and_keep_source_identity(self):
        request = {'run_id': self.run['id'], 'graph_id': self.graph['id']}
        result = map_inspection.prepare_checks(self.store, request)
        self.assertEqual(result['checks'], 3)
        self.assertEqual(result['failed_checks'], 1)
        self.assertEqual(result['execution']['inference_calls'], 0)
        graph = graph_store.read(self.store, result['graph_id'])
        self.assertEqual(graph['source_hash'], self.graph['source_hash'])
        self.assertTrue(any(e['type'] == 'recorded_recheck_of' and not e['properties']['comparable'] for e in graph['edges']))
        again = map_inspection.prepare_checks(self.store, request)
        self.assertEqual(again['graph_id'], result['graph_id'])
        self.assertEqual(again['execution'], {'cache_hits': 2, 'computed': 0, 'inference_calls': 0})

    def test_no_checks_is_an_explicit_empty_result(self):
        run = captured([change()]); self.store.add([run])
        result = map_inspection.prepare_checks(self.store, {'run_id': run['id'], 'graph_id': graph_store.build(run)['id']})
        self.assertEqual(result['checks'], 0)
        self.assertEqual(result['failed_checks'], 0)

    def test_wrong_source_and_unexpected_options_are_rejected(self):
        for request in [{'run_id': 'wrong', 'graph_id': self.graph['id']},
                        {'run_id': self.run['id'], 'graph_id': self.graph['id'], 'model': 'arbitrary'},
                        {'run_id': None, 'graph_id': self.graph['id']}]:
            with self.subTest(request=request), self.assertRaises(InputError):
                map_inspection.prepare_checks(self.store, request)


if __name__ == '__main__':
    unittest.main()
