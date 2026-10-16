"""Real subprocess fault controls; no model calls or accuracy claims."""
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

from tracker import candidate_process as runner
from tracker.candidate_worker import CommandCandidates
from tracker.schema import InputError, dumps
from tracker.semantic_extraction import generation_request, read, windows
from tracker.semantic_budget import ExecutionBudget
from tests.test_candidate_worker import GENERATOR
from tests.test_semantic_extraction import fixture


class CandidateProcessTests(unittest.TestCase):
    def execute(self, code, *, input='{}', timeout=3, **limits):
        return runner.run([sys.executable, '-I', '-c', code], input=input,
                          env=dict(os.environ), timeout=timeout, **limits)

    def test_bidirectional_output_and_utf8_survive_pipe_backpressure(self):
        # Writing stdout before reading a larger-than-pipe stdin used to be a
        # common deadlock in sequential replacement runners. Unicode straddles chunks.
        code = "import sys; sys.stdout.buffer.write(('界'*20000).encode()); sys.stdout.flush(); data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
        source = dumps({'source': 'é😀' * 30000})
        result = self.execute(code, input=source)
        self.assertEqual(result.stdout, '界' * 20000 + source)
        self.assertEqual(result.details['input_bytes_written'], len(source.encode()))
        self.assertEqual(result.details['stdout_bytes_observed'], len(result.stdout.encode()))

    def test_stream_limits_stop_producers_before_they_exit(self):
        for name, stream, limits in (
            ('stdout_limit', 'stdout', {'max_stdout_characters': 10000}),
            ('stderr_limit', 'stderr', {'max_stderr_bytes': 10000}),
        ):
            with self.subTest(name=name):
                start = time.monotonic()
                with self.assertRaises(runner.CandidateProcessError) as caught:
                    self.execute(f"import sys,time; sys.{stream}.buffer.write(b'x'*20000); sys.{stream}.flush(); time.sleep(20)", **limits)
                self.assertEqual(caught.exception.details['category'], name)
                self.assertLess(time.monotonic() - start, 3)
                self.assertNotIn('x' * 100, str(caught.exception))
                self.assertLessEqual(caught.exception.details[stream + '_bytes_observed'], 10000 + runner.CHUNK)

    def test_limits_count_characters_and_stderr_does_not_need_utf8(self):
        result = self.execute("import sys; sys.stdin.read(); sys.stdout.buffer.write(('😀'*20).encode()); sys.stderr.buffer.write(b'\\xff'*20)",
                              max_stdout_characters=20, max_stderr_bytes=20)
        self.assertEqual(result.stdout, '😀' * 20)
        self.assertEqual(result.details['stderr_bytes_observed'], 20)

    def test_invalid_utf8_including_partial_codepoint_is_safe_failure(self):
        for value in ("b'\\xff'", "b'\\xf0\\x9f'"):
            with self.subTest(value=value):
                with self.assertRaises(runner.CandidateProcessError) as caught:
                    self.execute(f'import sys; sys.stdin.read(); sys.stdout.buffer.write({value})')
                self.assertEqual(caught.exception.details['category'], 'invalid_utf8')

    def test_timeout_includes_a_child_that_never_reads_the_request(self):
        start = time.monotonic()
        with self.assertRaises(runner.CandidateProcessError) as caught:
            self.execute('import time; time.sleep(20)', input='x' * 1_000_000, timeout=0.3)
        self.assertEqual(caught.exception.details['category'], 'timeout')
        self.assertLess(time.monotonic() - start, 3)
        self.assertLess(caught.exception.details['input_bytes_written'], 1_000_000)

    def test_direct_and_descendant_exit_on_timeout_and_normal_completion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # The heartbeat makes an orphan visible even if it no longer owns
            # the pipes. The PID enables cleanup should the assertion fail.
            child = root/'child.py'
            child.write_text("import os,sys,time\nfrom pathlib import Path\np=Path(sys.argv[1]); p.with_suffix('.pid').write_text(str(os.getpid()))\nfor i in range(400):\n p.write_text(str(i)); time.sleep(.05)\n", encoding='utf-8')
            for mode in ('timeout', 'parent_exits', 'normal'):
                with self.subTest(mode=mode):
                    heartbeat = root/mode
                    code = ("import subprocess,sys,time\nfrom pathlib import Path\n"
                            f"p=Path({str(heartbeat)!r})\n"
                            f"subprocess.Popen([sys.executable,{str(child)!r},str(p)]"
                            + (",stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL" if mode=='normal' else '') + ")\n"
                            "while not p.exists(): time.sleep(.01)\n"
                            + ("time.sleep(20)" if mode=='timeout' else "sys.stdin.read(); print('{}')"))
                    try:
                        if mode=='normal':
                            self.assertEqual(self.execute(code).stdout.strip(), '{}')
                        else:
                            with self.assertRaises(runner.CandidateProcessError) as caught:
                                self.execute(code, timeout=0.7)
                            self.assertEqual(caught.exception.details['category'], 'timeout')
                        self.assertTrue(heartbeat.exists())
                        before = heartbeat.read_text()
                        time.sleep(0.2)
                        self.assertEqual(heartbeat.read_text(), before, 'Descendant is still running')
                        self.assertFalse(any(t.name.startswith('candidate-') for t in threading.enumerate()))
                    finally:
                        pidfile = heartbeat.with_suffix('.pid')
                        if pidfile.exists():
                            pid = int(pidfile.read_text())
                            if os.name == 'nt':
                                # Only the exact PID created by this fixture.
                                subprocess.run(['taskkill', '/PID', str(pid), '/F'], stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, timeout=5)
                            else:
                                try: os.kill(pid, 9)
                                except ProcessLookupError: pass

    def test_reject_invalid_timeout_without_launch(self):
        for value in (0, -1, float('nan'), float('inf'), True, '120'):
            with self.subTest(value=value), patch.object(runner.subprocess, 'Popen', side_effect=AssertionError('Must not launch')):
                with self.assertRaises(InputError):
                    self.execute('pass', timeout=value)

    @unittest.skipUnless(os.name == 'nt', 'Windows job assignment gate')
    def test_failed_job_assignment_cannot_start_the_configured_command(self):
        with tempfile.TemporaryDirectory() as d:
            marker=Path(d)/'must-not-start'
            with patch.object(runner, '_WindowsJob', side_effect=OSError('private host detail')):
                with self.assertRaises(runner.CandidateProcessError) as caught:
                    self.execute(f'from pathlib import Path; Path({str(marker)!r}).touch()')
            self.assertEqual(caught.exception.details['outcome'], 'not_started')
            self.assertFalse(marker.exists())
            self.assertNotIn('private host detail', str(caught.exception))

    def test_exit_and_startup_errors_never_expose_arguments_or_stderr(self):
        with self.assertRaises(runner.CandidateProcessError) as caught:
            self.execute("import sys; sys.stderr.write('PRIVATE_STDERR'); sys.exit(7)")
        self.assertEqual(caught.exception.details['category'], 'exit_code')
        self.assertEqual(caught.exception.details['exit_code'], 7)
        self.assertNotIn('PRIVATE_STDERR', dumps(caught.exception.details))
        with self.assertRaises(runner.CandidateProcessError) as caught:
            runner.run(['missing-program-PRIVATE_ARGUMENT'], input='{}', env=dict(os.environ), timeout=3)
        self.assertNotIn('PRIVATE_ARGUMENT', str(caught.exception))

    def test_retry_keeps_failed_receipt_and_budget_and_reuses_success(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); script = root/'generator.py'; flag = root/'failed'
            script.write_text(f"from pathlib import Path\np=Path({str(flag)!r})\nif not p.exists():\n p.touch(); __import__('sys').stdout.buffer.write(b'\\xff'); raise SystemExit(0)\n" + GENERATOR, encoding='utf-8')
            budget = ExecutionBudget(root/'budget', 1)
            provider = CommandCandidates(root/'candidates', [sys.executable, str(script)], 'fault control/1', execution_budget=budget)
            source = fixture(); unit = windows(source)[0]
            with self.assertRaises(runner.CandidateProcessError):
                provider.content(source, unit, 'orient')
            self.assertEqual(budget.used['candidate_requests'], 1)
            self.assertFalse((root/'candidates/responses').exists())
            attempt = read(next((root/'budget/attempts').glob('*.json')))
            self.assertEqual(attempt['provider_failure']['category'], 'invalid_utf8')
            # Explicit retry: the old receipt remains, and a new attempt is spent.
            self.assertEqual(provider.content(source, unit, 'orient')['status'], 'ready')
            receipts = [read(path) for path in (root/'candidates/receipts/attempts').glob('*.json')]
            self.assertCountEqual([r['status'] for r in receipts], ['failed', 'candidate_ready'])
            self.assertEqual(budget.used['candidate_requests'], 2)
            with patch.object(runner, 'run', side_effect=AssertionError('Cache hit must not launch')):
                self.assertEqual(provider.content(source, unit, 'orient')['status'], 'ready')
            self.assertEqual(budget.used['candidate_requests'], 2)

    def test_legacy_receipt_is_preserved_without_trusting_its_path(self):
        from tracker.schema import digest
        from tracker.semantic_extraction import write
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text(GENERATOR,encoding='utf-8')
            provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'fixture')
            source=fixture();unit=windows(source)[0];req=generation_request(source,unit,'orient')
            legacy={'schema':'candidate-worker-receipt/1','status':'failed','attempt_id':'../../outside'}
            write(root/'candidates/receipts'/f'{digest(req)}.json',legacy)
            self.assertEqual(provider.content(source,unit,'orient')['status'],'ready')
            self.assertEqual(read(root/'candidates/receipts/attempts'/f'legacy-{digest(legacy)}.json'),legacy)
            self.assertFalse((root/'candidates/outside.json').exists())


if __name__ == '__main__':
    unittest.main()
