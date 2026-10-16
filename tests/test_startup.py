import io
import json
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tracker.cli import main
from tracker.connections import definitions
from tracker.startup import doctor
from tracker.store import Store


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'local data' / 'db.sqlite'

    def run_cli(self, *args):
        output = io.StringIO()
        with patch('sys.argv', ['rilldex', '--db', str(self.db), *args]), redirect_stdout(output):
            main()
        return output.getvalue()

    def test_doctor_leaves_no_database_or_probe_files(self):
        self.assertTrue(doctor(self.db, 0)['ready'])
        self.assertFalse(self.db.exists())
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertTrue(json.loads(self.run_cli('doctor', '--port', '0'))['ready'])

    def test_busy_port_gives_recovery_command(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            s.listen()
            result = doctor(self.db, s.getsockname()[1])
        self.assertFalse(result['ready'])
        self.assertIn('--port 0', result['checks'][-1]['detail'])

    def test_doctor_rejects_directory_and_non_sqlite_database_without_modifying(self):
        self.assertFalse(doctor(self.root,0)['ready'])
        bad=self.root/'bad.sqlite';bad.write_bytes(b'not a sqlite database')
        self.assertFalse(doctor(bad,0)['ready'])
        self.assertEqual(bad.read_bytes(),b'not a sqlite database')
        Store(self.db)
        self.assertTrue(doctor(self.db,0)['ready'])

    def test_start_creates_and_resumes_the_same_connection_without_inference(self):
        output = self.root / 'output'
        output.mkdir()
        args = ('start', '--port', '0', '--watch', str(output), '--mode', 'exports',
                '--experiment', 'experiment', '--producer', 'worker')
        with patch('tracker.server.serve') as serve:
            self.run_cli(*args)
            self.run_cli(*args)
            self.assertEqual(serve.call_count, 2)
        self.assertEqual(serve.call_args.kwargs, {'port':0,'open_browser':False,'container':False})
        rows = definitions(Store(self.db))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['enabled'])

    def test_batch_command_drains_bounded_pages_and_continues_live_without_duplicates(self):
        root = self.root / 'exports'
        root.mkdir()
        row = {'input':'P','output':'C','step':1,'score':0}
        path = root / 'worker.jsonl'
        path.write_text((json.dumps(row) + '\n') * 3, encoding='utf-8')
        args = ('watch', str(root), '--mode', 'exports', '--experiment', 'e', '--producer', 'p', '--once', '--max-records', '2')
        self.run_cli(*args)
        self.assertEqual(len(Store(self.db).list()), 3)
        self.run_cli(*args)
        self.assertEqual(len(Store(self.db).list()), 3)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row))
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(*args)
        self.assertEqual(caught.exception.code, 1)
        with path.open('a', encoding='utf-8') as f:
            f.write('\n')
        self.run_cli(*args)
        self.assertEqual(len(Store(self.db).list()), 4)

    def test_start_snapshot_defaults_select_json_and_resume(self):
        root = self.root / 'json'
        root.mkdir()
        with patch('tracker.server.serve'):
            for _ in range(2):
                self.run_cli('start', '--watch', str(root), '--mode', 'snapshots',
                             '--experiment', 'e', '--producer', 'p')
        rows = definitions(Store(self.db))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['config']['pattern'], '*.json')
        self.assertEqual(rows[0]['config']['snapshot_state'], 'in_progress')


if __name__ == '__main__':
    unittest.main()
