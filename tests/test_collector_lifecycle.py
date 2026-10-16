import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tracker import connections
from tracker.cli import main
from tracker.collector_lock import ProducerLock
from tracker.notebook import open_workspace
from tracker.schema import InputError
from tracker.store import Store


class Monitor:
    def wake(self): pass
    def status(self): return {}


class ReaderGate:
    """An uninterruptible first read, as with a stalled filesystem/SDK call."""
    def __init__(self, producer):
        self.producer = producer
        self.validate = connections.validate
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls, self.active, self.peak = 0, 0, 0
        self.lock = threading.Lock()

    def __call__(self, store, config):
        config, reader = self.validate(store, config)
        if config['producer'] != self.producer:
            return config, reader
        gate = self

        class GatedReader:
            def poll(self, stop=None):
                with gate.lock:
                    gate.calls += 1
                    gate.active += 1
                    gate.peak = max(gate.peak, gate.active)
                try:
                    gate.entered.set()
                    if not gate.release.wait(15):
                        raise RuntimeError('Test did not release the controlled reader')
                    return reader.poll(stop)
                finally:
                    with gate.lock:
                        gate.active -= 1
        return config, GatedReader()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.outputs = self.root / 'outputs'
        self.outputs.mkdir()
        self.store = Store(self.root / 'db.sqlite')
        self.config = dict(root=str(self.outputs), producer='worker-a', mode='exports',
                           metadata={'experiment': 'test'}, interval=.2)
        self.raw = json.dumps({'input': 'Q', 'output': 'A', 'step': 1}) + '\n'

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.02)
        self.fail('Lifecycle did not reach the expected state')

    def test_os_ownership_is_per_workspace_producer_and_marker_is_not_a_lock(self):
        first = ProducerLock(self.store, 'a')
        second = ProducerLock(self.store, 'a')
        other = ProducerLock(self.store, 'b')
        separate = ProducerLock(Store(self.root/'separate.sqlite'), 'a')
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            self.assertTrue(other.acquire())
            self.assertTrue(separate.acquire())
            first.close()
            self.assertTrue(first.path.exists())
            self.assertTrue(second.acquire())
        finally:
            for lock in (first, second, other, separate): lock.close()

    def test_other_process_contention_and_crash_release(self):
        # Windows venv python.exe can be a launcher with a separate child. Kill
        # the actual lock owner, not just that launcher; imports here are stdlib.
        executable = getattr(sys, '_base_executable', sys.executable)
        code = """from types import SimpleNamespace
import sys
from tracker.collector_lock import ProducerLock
lock = ProducerLock(SimpleNamespace(path=sys.argv[1]), 'worker-a')
acquired = lock.acquire()
print('owned' if acquired else 'busy', flush=True)
if acquired and sys.argv[2] == 'hold': sys.stdin.read()
"""
        lock = ProducerLock(self.store, 'worker-a')
        with lock:
            result = subprocess.run([executable, '-c', code, str(self.store.path), 'probe'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, 'busy'), result.stderr)
        child = subprocess.Popen([executable, '-c', code, str(self.store.path), 'hold'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready, lines = threading.Event(), []
        def read_ready():
            lines.append(child.stdout.readline().strip())
            ready.set()
        reader = threading.Thread(target=read_ready, daemon=True)
        reader.start()
        try:
            self.assertTrue(ready.wait(10))
            self.assertEqual(lines, ['owned'])
            self.assertFalse(lock.acquire())
            child.kill()  # Only this disposable helper, to exercise crash release.
            child.wait(timeout=10)
            self.assertTrue(lock.acquire())
        finally:
            if child.poll() is None: child.kill()
            child.communicate(timeout=10)
            reader.join(timeout=2)
            lock.close()

    @unittest.skipUnless(hasattr(os, 'fork'), 'POSIX fork contract; Windows uses process creation')
    def test_forked_training_child_does_not_retain_parent_ownership(self):
        lock = ProducerLock(self.store, 'worker-a')
        self.assertTrue(lock.acquire())
        read_ready, write_ready = os.pipe()
        read_exit, write_exit = os.pipe()
        child = os.fork()
        if child == 0:
            try:
                os.close(read_ready); os.close(write_exit)
                os.write(write_ready, b'1')
                os.read(read_exit, 1)
            finally:
                os._exit(0)
        os.close(write_ready); os.close(read_exit)
        try:
            import select
            self.assertTrue(select.select([read_ready], [], [], 5)[0])
            self.assertEqual(os.read(read_ready, 1), b'1')
            lock.close()
            # The child is still alive; its inherited descriptor cannot own this.
            self.assertTrue(lock.acquire())
        finally:
            os.close(read_ready); os.close(write_exit)
            os.waitpid(child, 0)
            lock.close()

    def test_pausing_slow_reader_keeps_other_sources_live_and_resume_waits(self):
        cid = connections.create(self.store, self.config)['id']
        other = self.root/'other'; other.mkdir()
        connections.create(self.store, {**self.config, 'root': str(other), 'producer': 'worker-b'})
        gate = ReaderGate('worker-a')
        with patch('tracker.connections.validate', side_effect=gate):
            service = connections.Service(self.store, Monitor())
            try:
                self.assertTrue(gate.entered.wait(5))
                connections.set_enabled(self.store, cid, False)
                self.wait(lambda: service.runtime(cid)['stopping'])
                (other/'one.jsonl').write_text(self.raw, encoding='utf-8')
                self.wait(lambda: len(self.store.list()) == 1)
                with self.assertRaisesRegex(InputError, 'still being collected'):
                    connections.relocate(self.store, cid, {'root': str(other)})
                connections.set_enabled(self.store, cid, True)
                (self.outputs/'one.jsonl').write_text(self.raw, encoding='utf-8')
                time.sleep(1.1)
                self.assertEqual(gate.calls, 1)
                gate.release.set()
                self.wait(lambda: len(self.store.list()) == 2)
                self.assertEqual(gate.peak, 1)
                self.assertFalse(service.runtime(cid)['stopping'])
            finally:
                gate.release.set()
                self.assertTrue(service.close())

    def test_separate_managers_wait_for_actual_reader_exit(self):
        cid = connections.create(self.store, self.config)['id']
        gate = ReaderGate('worker-a')
        with patch('tracker.connections.validate', side_effect=gate):
            first = connections.Service(self.store, Monitor())
            second = None
            try:
                self.assertTrue(gate.entered.wait(5))
                second = connections.Service(self.store, Monitor())
                self.wait(lambda: second.runtime(cid)['waiting_for_owner'])
                started = time.monotonic()
                self.assertFalse(first.close(timeout=.02))
                self.assertLess(time.monotonic() - started, .5)
                self.assertTrue(first.runtime(cid)['stopping'])
                self.assertEqual(gate.calls, 1)
                gate.release.set()
                self.wait(lambda: gate.calls > 1)
                self.assertEqual(gate.peak, 1)
                self.assertTrue(first.close())
            finally:
                gate.release.set(); first.close()
                if second: second.close()

    def test_notebook_retains_stopping_owner_and_catches_up_after_exit(self):
        session = open_workspace(self.store.path)
        session.watch(self.outputs, producer='worker-a', experiment='test', interval=.2)
        gate = ReaderGate('worker-a')
        with patch('tracker.connections.validate', side_effect=gate):
            try:
                session.start(); self.assertTrue(gate.entered.wait(5))
                self.assertEqual(session.stop(timeout=.02)['state'], 'stopping')
                self.assertEqual(session.status()['state'], 'stopping')
                with self.assertRaisesRegex(InputError, 'still stopping'): session.start()
                self.assertEqual(gate.calls, 1)
                (self.outputs/'one.jsonl').write_text(self.raw, encoding='utf-8')
                gate.release.set()
                self.wait(lambda: session.status()['state'] == 'stopped')
                session.start()
                self.wait(lambda: session.status()['captured_rollouts'] == 1)
                self.assertEqual(gate.peak, 1)
                self.assertEqual(session.stop()['state'], 'stopped')
            finally:
                gate.release.set(); session.stop()

    def test_cli_replay_rejects_owned_producer_but_preflight_remains_read_only(self):
        (self.outputs/'one.jsonl').write_text(self.raw, encoding='utf-8')
        args = ['rilldex', '--db', str(self.store.path), 'watch', str(self.outputs),
                '--mode', 'exports', '--experiment', 'test', '--producer', 'worker-a']
        with ProducerLock(self.store, 'worker-a'), contextlib.redirect_stdout(io.StringIO()):
            with patch('sys.argv', args+['--once']), contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as caught: main()
            self.assertEqual(caught.exception.code, 1)
            self.assertIn('still being collected', error.getvalue())
            with patch('sys.argv', args+['--check']): main()
            self.assertEqual(self.store.list(), [])
        with patch('sys.argv', args+['--once']), contextlib.redirect_stdout(io.StringIO()): main()
        self.assertEqual(len(self.store.list()), 1)


if __name__ == '__main__': unittest.main()
