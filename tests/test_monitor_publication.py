"""Publication races after workers compute from the same stale cache."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tempfile
from pathlib import Path
import unittest
from tracker import monitoring
from tracker.store import Store
from tracker.adapters import normalize
from tracker.schema import InputError, digest, dumps
from tests.test_tracker import harbor


class MonitorPublicationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name)/'test.sqlite')
        self.run = normalize(harbor(), 'harbor')[0]; self.store.add([self.run])
        self.monitor = monitoring.create(self.store, dict(name='Publication control', kind='metric',
            observer='source', metric='actions'))

    def publish(self, value, key='same-input', barrier=None):
        doc = dict(value=value, input_hash=key, monitor_id=self.monitor['id'], run_id=self.run['id'])
        vid = 'value-'+digest(doc)
        pending = [(vid, self.monitor['id'], self.run['id'], key, dumps(doc), monitoring.now())]
        if barrier: barrier.wait(timeout=5)
        with self.store.connect() as c:
            return monitoring.publish_values(c, pending, [(self.monitor['id'], self.run['id'], vid)])

    def test_two_workers_with_stale_caches_publish_one_identical_receipt(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.publish, 1, barrier=barrier) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=10) for f in futures), [0, 1])
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM monitor_values WHERE monitor_id=?', (self.monitor['id'],)).fetchone()[0], 1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_conflicting_workers_fail_clearly_and_preserve_committed_receipt(self):
        self.publish(1)
        before = monitoring.values(self.store, self.monitor['id'], {self.run['id']})
        with self.assertRaisesRegex(InputError, 'Conflicting monitor results.*Check worker versions'):
            self.publish(2)
        self.assertEqual(before, monitoring.values(self.store, self.monitor['id'], {self.run['id']}))
        self.assertEqual(self.publish(2, key='new-version-input'), 1)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM monitor_values WHERE monitor_id=?', (self.monitor['id'],)).fetchone()[0], 2)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__': unittest.main()
