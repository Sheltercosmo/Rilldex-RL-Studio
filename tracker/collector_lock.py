"""Local OS ownership for a producer's file collector, released on process exit.

The marker remains on disk; its existence is never interpreted as ownership.
Do not unlink it: another process may still hold the original file descriptor.
"""
import errno
import os
from pathlib import Path
from weakref import WeakSet

from .schema import InputError, digest

_owners = WeakSet()


def _after_fork():
    # A notebook may fork training/data-loader workers after starting capture.
    # Those children must not keep a parent's ownership alive after it exits.
    for owner in list(_owners):
        owner.close()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


class ProducerLock:
    def __init__(self, store, producer):
        database = Path(store.path).resolve()
        self.path = database.parent / '.jev-capture-locks' / (digest([os.path.normcase(database.name), producer]) + '.lock')
        self.producer, self.stream = producer, None

    def acquire(self):
        if self.stream is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            # msvcrt permits locking beyond EOF; no write/truncate races needed.
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise
        self.stream = stream
        _owners.add(self)
        return True

    def close(self):
        if self.stream is not None:
            # Closing the owner descriptor releases the OS lock, on both OS paths.
            self.stream.close()
            self.stream = None
            _owners.discard(self)

    def __enter__(self):
        if not self.acquire():
            raise InputError(f'Producer {self.producer!r} is still being collected in this workspace. Pause its connection and wait for collection to stop, or stop the other watch process. Do not delete lock files.')
        return self

    def __exit__(self, *args):
        self.close()
