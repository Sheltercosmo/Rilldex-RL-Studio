import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen
from unittest.mock import patch

from tracker import capture_bundle, generation_cohorts
from tracker.analysis_mirror import FeedMirror
from tracker.analytics import Analysis
from tracker.capture import Outbox
from tracker.schema import InputError
from tracker.store import Store
from tracker.workspace_analysis import Workspace


def declaration(revision=0, *, members=None, sealed=False, identifier='batch', index=2):
    return {'id': identifier, 'revision': revision, 'label': 'scheduled',
        'coordinate': {'clock': 'generation', 'basis': 'batch index', 'index': index},
        'context': {'environment': 'terminal'}, 'sealed': sealed,
        'members': members or [], 'evidence': 'scheduler manifest'}


def population_packet(producer='scheduler', experiment='exp', rows=None):
    return {'schema': generation_cohorts.VERSION, 'producer': producer, 'experiment': experiment,
        'cohorts': rows if rows is not None else [declaration()]}


SERVER = '''
import sys, threading
from tracker import server
from tracker.store import Store
original = server.LocalServer
def managed(*args, **kwargs):
    instance = original(*args, **kwargs)
    def stop_on_eof():
        sys.stdin.read()
        instance.shutdown()
    threading.Thread(target=stop_on_eof, daemon=True).start()
    return instance
server.LocalServer = managed
server.serve(Store(sys.argv[1]), port=0)
'''


class GenerationCohortTransportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / 'workspace.sqlite'
        self.store = Store(self.db)

    def start_server(self):
        log = self.root / 'server.log'
        stream = log.open('w', encoding='utf-8')
        process = subprocess.Popen([sys.executable, *(['-I'] if sys.flags.isolated else []), '-c', SERVER, str(self.db)],
            stdin=subprocess.PIPE, stdout=stream, stderr=stream, text=True,
            env=dict(os.environ, PYTHONUTF8='1'),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.addCleanup(self.stop_server, process, stream)
        deadline = time.monotonic() + 15
        endpoint = None
        while time.monotonic() < deadline and process.poll() is None:
            content = log.read_text(encoding='utf-8')
            match = re.search(r'Rilldex: (http://127\.0\.0\.1:\d+)', content)
            if match:
                endpoint = match.group(1); break
            time.sleep(.05)
        self.assertIsNotNone(endpoint, log.read_text(encoding='utf-8'))
        return endpoint

    @staticmethod
    def stop_server(process, stream):
        if process.poll() is None:
            process.stdin.close()
            process.wait(timeout=10)
        stream.close()

    def test_outbox_http_delivery_and_snapshot_api(self):
        endpoint = self.start_server()
        box = Outbox(self.root / 'worker.sqlite', producer='scheduler', endpoint=endpoint)
        box.log_cohorts('exp', [declaration(1, members=[{'producer': 'generator',
            'rollout_id': 'missing', 'generation_state': 'completed', 'context': {}}], sealed=True)])
        self.assertEqual(box.drain()['sent_now'], 1)
        with urlopen(endpoint + '/api/generation-cohorts?experiment=exp&members=1') as response:
            result = json.loads(response.read())
        self.assertEqual(result['distinct_declared_rollouts'], 1)
        self.assertEqual(result['cohorts'][0]['declared'], 1)
        self.assertEqual(result['cohorts'][0]['delivered'], 0)
        self.assertEqual(result['cohorts'][0]['members'][0]['source_status'], 'not_delivered')

    def test_outbox_restart_and_lost_ack_replay_are_idempotent(self):
        endpoint = self.start_server()
        path = self.root / 'durable.sqlite'
        box = Outbox(path, producer='scheduler', endpoint=endpoint)
        packet = [declaration(1, sealed=True)]
        box.log_cohorts('exp', packet)
        original = __import__('tracker.capture', fromlist=['urlopen']).urlopen
        lost = {'once': True}
        def deliver_then_lose_ack(request, **kwargs):
            response = original(request, **kwargs)
            response.read(); response.close()
            if lost['once']:
                lost['once'] = False
                raise OSError('simulated lost acknowledgment')
            return original(request, **kwargs)
        with patch('tracker.capture.urlopen', side_effect=deliver_then_lose_ack):
            box.drain()
        restarted = Outbox(path, producer='scheduler', endpoint=endpoint)
        self.assertEqual(restarted.status()['pending'], 1)
        self.assertEqual(restarted.drain()['sent_now'], 1)
        self.assertEqual(restarted.drain()['sent_now'], 0)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM generation_cohorts').fetchone()[0], 1)

    def test_capture_bundle_import_replay_and_acknowledgment(self):
        box = Outbox(self.root / 'offline.sqlite', producer='scheduler')
        box.log_cohorts('exp', [declaration(1, sealed=True)])
        archive = self.root / 'cohorts.zip'
        capture_bundle.export(box.path, archive)
        self.assertEqual(capture_bundle.inspect(archive)['kinds'], {'generation_cohorts': 1})
        received = capture_bundle.receive(self.store, archive, with_receipts=True)
        self.assertEqual((received['accepted'], received['already_present']), (1, 0))
        self.assertEqual(capture_bundle.receive(self.store, archive)['already_present'], 1)
        receipt_file = self.root / 'receipts.json'
        receipt_file.write_text(json.dumps({'schema': 'jev-capture-receipts/1',
            'acknowledgments': received['acknowledgments']}), encoding='utf-8')
        self.assertEqual(capture_bundle.acknowledge(box.path, receipt_file)['acknowledged'], 1)
        self.assertEqual(box.status()['pending'], 0)

    def test_analysis_table_history_feed_and_scoped_workspace_sql(self):
        packet = population_packet(rows=[declaration(0, identifier='batch', index=2),
            declaration(2, identifier='batch', index=2)])
        generation_cohorts.receive(self.store, packet)
        generation_cohorts.receive(self.store, population_packet(experiment='other',
            rows=[declaration(identifier='other-exp', index=9)]))
        table = Analysis(self.db).table('generation_cohorts', experiment='exp')
        self.assertEqual(len(table['rows']), 1)
        history = Analysis(self.db).table('generation_cohorts', experiment='exp', history=True)
        self.assertEqual(len(history['rows']), 2)
        feed = Analysis(self.db).changes('generation_cohorts')
        self.assertEqual(len(feed['rows']), 3)
        workspace = Workspace(self.db, experiment='exp', history=True)
        rows = workspace.sql('SELECT experiment,cohort_id,revision FROM generation_cohorts ORDER BY revision')
        self.assertEqual([(r['experiment'], r['cohort_id'], r['revision']) for r in rows['rows']],
            [('exp', 'batch', 0), ('exp', 'batch', 2)])
        mirror = FeedMirror(Analysis(self.db), self.root / 'mirror.sqlite')
        self.assertEqual(mirror.sync(feeds=['generation_cohorts'])['feeds'][0]['inserted'], 3)

    def test_research_database_read_and_old_schema_fallback(self):
        generation_cohorts.receive(self.store, population_packet())
        frozen_path = self.root / 'research.sqlite'
        Analysis(self.db).database(frozen_path, experiment='exp')
        frozen = Analysis(frozen_path)
        self.assertEqual(len(frozen.table('generation_cohorts')['rows']), 1)
        self.assertEqual(frozen.query('SELECT count(*) n FROM rl_generation_cohorts')['rows'][0]['n'], 1)

        old_path = self.root / 'old.sqlite'
        old_store = Store(old_path)
        with old_store.connect() as c:
            c.execute('DROP TABLE generation_cohorts')
        old = Analysis(old_path)
        self.assertFalse(old.table('generation_cohorts')['available'])
        self.assertNotIn('generation_cohorts', old.catalog()['feeds'])
        with self.assertRaises(InputError): old.changes('generation_cohorts')
        old_frozen_path = self.root / 'old-research.sqlite'
        old.database(old_frozen_path)
        old_frozen = Analysis(old_frozen_path)
        self.assertFalse(old_frozen.table('generation_cohorts')['available'])


if __name__ == '__main__':
    unittest.main()
