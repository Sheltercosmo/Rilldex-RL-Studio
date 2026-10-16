"""Bound the local JSON proposer process, without retrying provider work.

This is process lifecycle management, not a sandbox or an API billing limit.
The Windows launcher waits for a gate before starting the user's command, so
job assignment cannot race with that command spawning its own children.
"""
import codecs
from dataclasses import dataclass
import math
import os
import signal
import subprocess
import sys
import threading
import time

from .schema import InputError

POLICY = 'bounded-candidate-process/1'
MAX_STDOUT_CHARACTERS = 2_000_000
MAX_STDERR_BYTES = 2_000_000
CHUNK = 8192
_WINDOWS_GATE = "import os,subprocess,sys; sys.exit(subprocess.call(sys.argv[1:]) if os.read(0,1)==b'\\0' else 125)"


class CandidateProcessError(InputError):
    def __init__(self, message, details):
        self.details = details
        super().__init__(message)


def failure_details(exc):
    return dict(exc.details) if isinstance(exc, CandidateProcessError) else None


def validate_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise InputError('Candidate timeout must be a positive finite number of seconds')
    return value


class _WindowsJob:
    """Own descendants even after their immediate parent has exited."""
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                        ('Flags', w.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                        ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcesses', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('Priority', w.DWORD), ('Scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t),
                        ('JobMemory', ctypes.c_size_t), ('PeakProcessMemory', ctypes.c_size_t),
                        ('PeakJobMemory', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, arguments, result in (
            ('CreateJobObjectW', [w.LPVOID, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL),
        ):
            function = getattr(self.kernel, name)
            function.argtypes = arguments
            function.restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = Extended()
            info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = self.kernel.OpenProcess(0x0100 | 0x0001, False, process.pid)  # SET_QUOTA | TERMINATE
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.kernel.CloseHandle(handle)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@dataclass
class ProcessResult:
    stdout: str
    details: dict


def run(command, *, input, env, timeout, max_stdout_characters=MAX_STDOUT_CHARACTERS,
        max_stderr_bytes=MAX_STDERR_BYTES):
    """One invocation; capture bounded UTF-8 stdout, count/discard stderr.

    Deadline covers stdin delivery, both pipes and process exit. OS process
    creation itself may not be interruptible. Child cleanup gets five seconds.
    Commands must not detach from the process group or launch remote jobs.
    """
    validate_timeout(timeout)
    for value in (max_stdout_characters, max_stderr_bytes):
        if type(value) is not int or value <= 0:
            raise InputError('Candidate output limits must be positive integers')
    payload = input.encode('utf-8')
    details = {'provider': 'candidate', 'execution_policy': POLICY, 'outcome': 'not_started',
               'stdout_bytes_observed': 0, 'stdout_characters': 0, 'stderr_bytes_observed': 0,
               'input_bytes_written': 0, 'timeout_seconds': timeout,
               'stdout_character_limit': max_stdout_characters, 'stderr_byte_limit': max_stderr_bytes,
               'usage': 'Unknown unless reported by the provider; stopping a process does not cancel remote work.'}
    process = None
    job = None
    threads = []
    outputs = []
    errors = []
    stop = threading.Event()
    start = time.monotonic()

    def fail(category, message):
        errors.append((category, message))
        stop.set()

    def read_stdout():
        decoder = codecs.getincrementaldecoder('utf-8')()
        try:
            while not stop.is_set():
                chunk = process.stdout.read(CHUNK)
                details['stdout_bytes_observed'] += len(chunk)
                decoded = decoder.decode(chunk, final=not chunk)
                details['stdout_characters'] += len(decoded)
                if details['stdout_characters'] > max_stdout_characters:
                    fail('stdout_limit', 'Candidate response exceeds its character limit')
                    return
                outputs.append(decoded)
                if not chunk:
                    return
        except UnicodeError:
            fail('invalid_utf8', 'Candidate response is not valid UTF-8')
        except (OSError, ValueError):
            if not stop.is_set():
                fail('pipe_error', 'Candidate response pipe failed')

    def read_stderr():
        try:
            while not stop.is_set():
                chunk = process.stderr.read(CHUNK)
                details['stderr_bytes_observed'] += len(chunk)
                if details['stderr_bytes_observed'] > max_stderr_bytes:
                    fail('stderr_limit', 'Candidate stderr exceeds its byte limit; stderr is not persisted')
                    return
                if not chunk:
                    return
        except (OSError, ValueError):
            if not stop.is_set():
                fail('pipe_error', 'Candidate stderr pipe failed; stderr is not persisted')

    def write_input():
        # No target can start on Windows until job assignment succeeds.
        wire = memoryview((b'\0' if os.name == 'nt' else b'') + payload)
        sent = 0
        try:
            while sent < len(wire) and not stop.is_set():
                sent += process.stdin.write(wire[sent:sent + CHUNK])
                details['input_bytes_written'] = max(0, sent - (1 if os.name == 'nt' else 0))
        except BrokenPipeError:
            pass  # The exit code / incomplete input check supplies the reason.
        except (OSError, ValueError):
            if not stop.is_set():
                fail('pipe_error', 'Candidate request pipe failed')
        finally:
            process.stdin.close()

    try:
        launch = [sys.executable, '-I', '-c', _WINDOWS_GATE, *command] if os.name == 'nt' else command
        process = subprocess.Popen(launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, env=env, shell=False,
                                   start_new_session=os.name != 'nt',
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if os.name == 'nt':
            job = _WindowsJob(process)
        details['outcome'] = 'unknown'
        for target in (read_stdout, read_stderr, write_input):
            thread = threading.Thread(target=target, daemon=True, name='candidate-' + target.__name__)
            threads.append(thread)
            thread.start()
        while True:
            if errors:
                category, message = errors[0]
                raise CandidateProcessError(message, {**details, 'category': category})
            if process.poll() is not None and all(not thread.is_alive() for thread in threads):
                break
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                raise CandidateProcessError('Candidate process timed out; no stdout/stderr persisted',
                                            {**details, 'category': 'timeout'})
            stop.wait(min(0.02, remaining))
        if errors:
            category, message = errors[0]
            raise CandidateProcessError(message, {**details, 'category': category})
        details.update(outcome='process_returned', exit_code=process.returncode)
        if process.returncode:
            raise CandidateProcessError(f'Candidate process failed with exit code {process.returncode}; stderr is not persisted',
                                        {**details, 'category': 'exit_code'})
        if details['input_bytes_written'] != len(payload):
            raise CandidateProcessError('Candidate process exited before the complete request was delivered',
                                        {**details, 'category': 'incomplete_input'})
        return ProcessResult(''.join(outputs), details)
    except OSError:
        raise CandidateProcessError('Candidate process could not be started or contained; command arguments are not persisted',
                                    {**details, 'category': 'startup'}) from None
    finally:
        stop.set()
        if job is not None:
            job.close()
        elif process is not None and os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None:
            if process.poll() is None:
                process.kill()
            deadline = time.monotonic() + 5
            process.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=max(0, deadline - time.monotonic()))
            # Raw (unbuffered) handles: closing does not acquire a reader lock.
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()

