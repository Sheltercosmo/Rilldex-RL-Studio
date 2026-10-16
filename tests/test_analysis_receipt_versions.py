"""Historical evidence stays verifiable when extraction dependencies advance."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import analysis_metrics, investigation_plans, monitoring, monitor_evidence, work_state
from tracker.schema import InputError
from tracker.store import Store
from test_investigation_process import captured


class AnalysisReceiptVersionsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'study.sqlite')
        self.run = captured()
        self.store.add([self.run])

    def recorded(self, measure):
        monitor = monitoring.create(self.store, dict(name=measure, kind='analysis',
            observer='source', analysis={'measure': measure}))
        result = monitoring.sync(self.store, [monitor['id']])
        self.assertEqual(result['errors'], 0)
        value = monitoring.values(self.store, monitor['id'], [self.run['id']])[self.run['id']]
        return monitor, value

    def test_saved_recovery_and_retry_receipts_do_not_require_current_dependencies(self):
        for measure in ('criterion_recovery_window', 'next_check_success'):
            with self.subTest(measure=measure):
                monitor, value = self.recorded(measure)
                original = monitor_evidence.read(self.store, value['id'])
                with patch.object(work_state, 'VERSION', 'work-state/999'), patch.dict(
                        investigation_plans.OPS, {'recovery_windows': 'recovery-windows/999'}), patch.object(
                        investigation_plans, 'execute', side_effect=AssertionError('No recalculation')):
                    loaded = monitor_evidence.read(self.store, value['id'])
                self.assertEqual(loaded, original)

    def test_pinned_dependency_versions_and_hashes_still_must_match(self):
        for measure in ('criterion_recovery_window', 'next_check_success'):
            monitor, value = self.recorded(measure)
            original = investigation_plans.read_plan(self.store, value['analysis']['plan_id'])
            for index in range(len(original['nodes']) - 1):
                for field, bad in [('version', 'unrelated/1'), ('output_hash', 'corrupted')]:
                    with self.subTest(measure=measure, index=index, field=field):
                        changed = copy.deepcopy(original)
                        changed['nodes'][index][field] = bad
                        with patch.object(investigation_plans, 'read_plan', return_value=changed):
                            with self.assertRaises(InputError):
                                analysis_metrics.receipt(self.store, value, monitor)


if __name__ == '__main__':
    unittest.main()
