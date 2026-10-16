"""Notebook-owned capture and analysis; no subprocess, public tunnel or model calls."""
import atexit
import time
from pathlib import Path

from . import connections
from .store import Store
from .schema import InputError

_sessions = {}


class NotebookWorkspace:
    def __init__(self, path):
        self.store = Store(path)
        self.intake = self.monitor = None

    def watch(self, root, *, producer, experiment, mode='exports', **options):
        """Replay existing output and continue with new output, using saved cursors."""
        meta = {**options.pop('metadata', {}), 'experiment': experiment}
        return connections.create(self.store, dict(root=str(root), producer=producer,
            metadata=meta, mode=mode, **options))

    def start(self):
        for name in ('intake', 'monitor'):
            service = getattr(self, name)
            if service and service.stop.is_set():
                if service.thread.is_alive():
                    raise InputError('Workspace is still stopping. Wait for status()["state"] to become "stopped", then start again. An in-flight storage read or analysis is still finishing.')
                setattr(self, name, None)
        if self.intake is None:
            from .monitoring import Service
            self.monitor = Service(self.store)
            try:
                self.intake = connections.Service(self.store, self.monitor)
            except Exception:
                self.monitor.close()
                self.monitor = None
                raise
        return self

    def stop(self, timeout=10):
        """Request stop, wait a bounded time, and report readers still finishing."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 300:
            raise InputError('Stop timeout must be between 0 and 300 seconds')
        deadline = time.monotonic() + timeout
        if self.monitor:
            self.monitor.close(timeout=0)
        if self.intake:
            if self.intake.close(timeout=max(0, deadline - time.monotonic())):
                self.intake = None
        if self.monitor:
            if self.monitor.close(timeout=max(0, deadline - time.monotonic())):
                self.monitor = None
        return {'state': self._state()}

    def _state(self):
        services = [s for s in (self.intake, self.monitor) if s and s.thread.is_alive()]
        return 'stopping' if any(s.stop.is_set() for s in services) else 'running' if services else 'stopped'

    def pause(self, connection_id):
        return connections.set_enabled(self.store, connection_id, False)

    def resume(self, connection_id):
        return connections.set_enabled(self.store, connection_id, True)

    def status(self):
        rows = connections.definitions(self.store)
        from .producer_health import snapshot
        received = {p['producer']: {k: p[k] for k in ('received_revisions', 'received_rollouts', 'last_receipt_at')} for p in snapshot(self.store)}
        return dict(running=self._state() == 'running', state=self._state(), database=str(self.store.path),
                    connections=[dict(id=r['id'], producer=r['producer'], enabled=bool(r['enabled']),
                                      source=r['config']['root'], **r['status'],
                                      received=received.get(r['producer'], dict(received_revisions=0, received_rollouts=0, last_receipt_at=None)),
                                      **(self.intake.runtime(r['id']) if self.intake else {})) for r in rows],
                    captured_rollouts=len(self.store.list()))

    def rollouts(self, limit=20):
        return self.store.list()[:limit]

    def snapshot(self, destination):
        """Export a new local workspace archive, including saved observations."""
        from .workspace_snapshot import export
        return export(self.store, destination)

    @property
    def analysis(self):
        """Read saved tables/graphs or SQL without starting collectors or inference."""
        from .analytics import Analysis
        return Analysis(self.store.path)

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()


def open_workspace(path='.tracker/notebook.sqlite'):
    """Rerunning a cell returns the same owner instead of adding collector threads."""
    key = str(Path(path).expanduser().resolve())
    if key not in _sessions:
        _sessions[key] = NotebookWorkspace(key)
    return _sessions[key]


@atexit.register
def _close():
    for session in _sessions.values():
        session.stop()
