"""Saved workspaces remain analyzable without migrating their producer schema."""
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from rilldex import Workspace
from tracker.analytics import Analysis, TRAINING_COLUMNS
from tracker.schema import InputError
from tracker.store import Store


class AnalysisCompatibilityTests(unittest.TestCase):
    def test_training_versions_can_be_present_independently_without_blocking_graph_access(self):
        for present in ((), ('training_records',), ('training_sample_records',), ('training_records','training_sample_records')):
            with self.subTest(present=present), TemporaryDirectory() as directory:
                path = Path(directory)/'old.sqlite'; Store(path)
                with closing(sqlite3.connect(path)) as c, c:
                    for table in ('training_records','training_sample_records'):
                        if table not in present:
                            c.execute('DROP TABLE '+table)
                        else:
                            c.execute('INSERT INTO '+table+' VALUES (?,?,?,?,?,?,?,?,?)',
                                      ('trainer','trial','row',0,'sample','actor','sample-1','{}','2026-10-01'))
                initial = hashlib.sha256(path.read_bytes()).hexdigest()
                ws = Workspace(path, experiment='trial'); data = Analysis(path)
                self.assertEqual(ws.graphs().rows, [])
                result = ws.table('training_records')
                self.assertEqual(result['available'], bool(present))
                self.assertEqual(len(result.rows), len(present))
                self.assertEqual(set(result['columns']), set(TRAINING_COLUMNS)-{'record_json'}|{'record'})
                self.assertEqual(len(result['source_coverage']['unavailable_schemas']), 2-len(present))
                self.assertEqual(len(data.table('training_records')['rows']), len(present))
                self.assertEqual(data.table('training_records',experiment='other')['rows'], [])
                catalog = data.catalog()
                for table, feed in [('training_records','training_records'),('training_sample_records','training_samples')]:
                    if table in present:
                        self.assertIn(feed, catalog['feeds'])
                        self.assertEqual(len(data.changes(feed)['rows']), 1)
                    else:
                        self.assertNotIn(feed, catalog['feeds'])
                        with self.assertRaisesRegex(InputError, 'unavailable'): data.changes(feed)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), initial)

    def test_partial_schema_coverage_survives_frozen_dataset_and_missing_tables_stay_unavailable(self):
        for present in (True, False):
            with self.subTest(present=present), TemporaryDirectory() as directory:
                path = Path(directory)/'old.sqlite'; Store(path)
                with closing(sqlite3.connect(path)) as c, c:
                    c.execute('DROP TABLE training_sample_records')
                    if not present: c.execute('DROP TABLE training_records')
                source = Analysis(path); target = Path(directory)/'frozen.sqlite'
                source.database(target)
                frozen = Analysis(target).table('training_records')
                self.assertEqual(frozen['available'], present)
                self.assertEqual(frozen['source_coverage'], source.table('training_records')['source_coverage'])
                self.assertEqual(Analysis(target).catalog()['feeds'], [])
                # A frozen dataset still supports the convenient scoped interface.
                self.assertEqual(Workspace(target).graphs().rows, [])


if __name__ == '__main__': unittest.main()
