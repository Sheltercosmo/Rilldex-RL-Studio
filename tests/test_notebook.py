import json
from pathlib import Path
import tempfile
import time
import unittest

from tracker.notebook import open_workspace
from tracker.workspace_snapshot import restore
from tracker.store import Store


class NotebookTests(unittest.TestCase):
    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.05)
        self.fail('Notebook collector did not reach expected state')

    def test_cell_rerun_stop_new_output_restart_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = root / 'outputs'
            outputs.mkdir()
            db = root / 'db.sqlite'
            session = open_workspace(db)
            try:
                config = dict(producer='notebook/w0', experiment='test', interval=.2)
                session.watch(outputs, **config)
                session.start()
                self.assertIs(open_workspace(db).start(), session)
                self.assertFalse(session.watch(outputs, **config)['created'])
                raw = json.dumps({'input': 'Q', 'output': 'A', 'step': 1}) + '\n'
                path = outputs / 'rows.jsonl'
                path.write_text(raw, encoding='utf-8')
                self.wait(lambda: session.status()['captured_rollouts'] == 1)
                session.stop()
                self.assertFalse(session.status()['running'])
                path.write_text(raw * 2, encoding='utf-8')
                session.start()
                self.wait(lambda: session.status()['captured_rollouts'] == 2)
                self.assertEqual(session.status()['connections'][0]['received']['received_rollouts'], 2)
                archive = root / 'portable.rilldex.zip'
                session.snapshot(archive)
                restored = root / 'restored.sqlite'
                restore(archive, restored)
                self.assertEqual(len(Store(restored).list()), 2)
                from tracker.connections import definitions
                self.assertFalse(definitions(Store(restored))[0]['enabled'])
            finally:
                session.stop()


if __name__ == '__main__': unittest.main()
