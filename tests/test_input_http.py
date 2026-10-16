"""Real loopback delivery of common records and a pinned non-software trajectory."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from rilldex import Outbox
from tracker.adapters import normalize
from tracker.store import Store
import test_input_generalization as contracts

records = contracts.records
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


class InputHTTPTests(unittest.TestCase):
    def test_mixed_workers_deliver_restart_and_match_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, log = root / 'workspace.sqlite', root / 'server.log'
            env = dict(os.environ, PYTHONUTF8='1')
            env.pop('JEV_API_KEY', None)
            with log.open('w', encoding='utf-8') as stream:
                process = subprocess.Popen(
                    [sys.executable, '-c', SERVER, str(db)],
                    stdin=subprocess.PIPE, stdout=stream, stderr=stream, text=True, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                try:
                    endpoint = None
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline and process.poll() is None:
                        match = re.search(r'Rilldex: (http://127\.0\.0\.1:\d+)', log.read_text(encoding='utf-8'))
                        if match:
                            endpoint = match.group(1)
                            break
                        time.sleep(.05)
                    self.assertIsNotNone(endpoint, log.read_text(encoding='utf-8'))
                    store = Store(db)
                    for index, (name, doc) in enumerate(records().items()):
                        producer = f'mixed/worker-{index}'
                        path = root / f'worker-{index}.sqlite'
                        client = Outbox(path, producer=producer, endpoint=endpoint)
                        # Workers may use the same local rollout ID; identities must not collide.
                        client.log('sample-42', doc, state='in_progress')
                        self.assertEqual(client.drain()['sent_now'], 1)
                        restarted = Outbox(path, producer=producer, endpoint=endpoint)
                        restarted.log('sample-42', doc, state='complete')
                        self.assertEqual(restarted.drain()['sent_now'], 1)
                        self.assertEqual(restarted.drain()['sent_now'], 0)
                        row = next(r for r in store.list() if r['metadata']['producer'] == producer)
                        self.assertEqual(row['ingestion']['revision'], 1, name)
                        contracts.GeneralizationTests.assert_evidence_equal(self, normalize(doc)[0],
                                                                 store.get(row['id'], raw=True)['run'])
                    self.assertEqual(len(store.list()), len(records()))
                    ambiguous = dict(input='p', output='c', step=1, prompt='p', completion='c')
                    request = Request(endpoint + '/api/ingest', data=json.dumps(dict(
                        producer='mixed/bad', rollout_id='a', revision=0, state='complete',
                        document=ambiguous)).encode(), headers={'Content-Type': 'application/json'})
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(request, timeout=5)
                    self.assertEqual(caught.exception.code, 400)
                    self.assertIn('Ambiguous', caught.exception.read().decode())
                    self.assertEqual(len(store.list()), len(records()))
                finally:
                    try:
                        process.communicate(input='', timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
