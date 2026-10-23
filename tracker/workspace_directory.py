"""Local workspace directory. Every open database keeps its own intake endpoint."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler

from .schema import InputError

VIEWS = {'/', '/dashboard', '/runs', '/semantic-map', '/source', '/monitors',
         '/investigate', '/connections', '/integration-guide', '/measurement-review', '/relations',
         '/rollouts', '/studies', '/components', '/detector-validation'}


def identity(path):
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()


def view_path(value):
    if not isinstance(value, str) or len(value) > 16000 or any(c in value for c in '\\\r\n'):
        raise InputError('Choose a local workspace page')
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path not in VIEWS or not value.startswith('/'):
        raise InputError('Choose a local workspace page')
    return value


def database_path(value, *, base=None):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise InputError('Enter a workspace database path')
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(base or Path.cwd()) / path
    return path.resolve()


def validate_name(name):
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 120):
        raise InputError('Use a workspace name between 1 and 120 characters')


def validate_database(path):
    if not path.is_file():
        raise InputError('Workspace database does not exist; use Create workspace for a new study')
    try:
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)
        try:
            columns = {r[1] for r in connection.execute('PRAGMA table_info(runs)')}
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        if not {'id', 'imported_at', 'document', 'analysis'} <= columns or 'semantic_observers' not in tables:
            raise InputError('This file is not a Rilldex workspace')
    except sqlite3.Error as error:
        raise InputError('Cannot open this Rilldex workspace: ' + str(error)) from None


def alive(row):
    endpoint = row.get('endpoint')
    if not endpoint or not row.get('instance'):
        return False
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.path:
        return False
    try:
        # Local control requests must not travel through the model/cloud proxy.
        with build_opener(ProxyHandler({})).open(endpoint + '/api/workspace-identity', timeout=.7) as response:
            result = json.loads(response.read(4096))
        return result.get('identity') == row['id'] and result.get('instance') == row.get('instance')
    except (OSError, ValueError):
        return False


class Directory:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('RILLDEX_WORKSPACE_REGISTRY') or
                         Path.home() / '.rilldex' / 'workspaces.sqlite').expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                endpoint TEXT, instance TEXT, last_view TEXT NOT NULL DEFAULT '/',
                last_opened REAL NOT NULL, opening_until REAL NOT NULL DEFAULT 0)''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def remember(self, path, name=None):
        path = Path(path).resolve()
        validate_name(name)
        key = identity(path)
        with self.connect() as connection:
            connection.execute('''INSERT INTO workspaces(id,path,name,last_opened) VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET last_opened=excluded.last_opened''',
                (key, str(path), name.strip() if name else path.stem, time.time()))
            if name is not None:
                connection.execute('UPDATE workspaces SET name=? WHERE id=?', (name.strip(), key))
        return self.get(key)

    def get(self, key):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM workspaces WHERE id=?', (key,)).fetchone()
        if row is None:
            raise InputError('Workspace is no longer in the recent list')
        return dict(row)

    def attach(self, path, endpoint, instance):
        row = self.remember(path)
        with self.connect() as connection:
            connection.execute('UPDATE workspaces SET endpoint=?,instance=?,opening_until=0 WHERE id=?',
                               (endpoint, instance, row['id']))

    def detach(self, key, instance):
        with self.connect() as connection:
            connection.execute('UPDATE workspaces SET instance=NULL WHERE id=? AND instance=?', (key, instance))

    def ports(self):
        with self.connect() as connection:
            endpoints = [r[0] for r in connection.execute('SELECT endpoint FROM workspaces WHERE endpoint IS NOT NULL')]
        return {urlsplit(endpoint).port for endpoint in endpoints}

    def save_view(self, key, view):
        view = view_path(view)
        with self.connect() as connection:
            connection.execute('UPDATE workspaces SET last_view=? WHERE id=?', (view, key))

    def list(self, current):
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute('SELECT * FROM workspaces ORDER BY last_opened DESC')]
        def state(row):
            row['current'] = row['id'] == current
            row['state'] = ('current' if row['current'] else 'missing' if not Path(row['path']).is_file()
                            else 'open' if alive(row) else 'opening' if row['opening_until'] > time.time() else 'closed')
            return row
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(state, rows))

    def claim(self, key):
        with self.connect() as connection:
            changed = connection.execute('UPDATE workspaces SET opening_until=? WHERE id=? AND opening_until<?',
                                         (time.time()+45, key, time.time())).rowcount
        if not changed:
            raise InputError('This workspace is opening; try again in a moment')

    def release(self, key):
        with self.connect() as connection:
            connection.execute('UPDATE workspaces SET opening_until=0 WHERE id=?', (key,))

    def forget(self, key):
        with self.connect() as connection:
            connection.execute('DELETE FROM workspaces WHERE id=?', (key,))


class WorkspaceManager:
    def __init__(self, store, endpoint, instance, *, directory=None, enabled=True):
        self.store, self.endpoint, self.instance = store, endpoint, instance
        self.enabled = enabled
        self.directory = directory or Directory()
        self.key = identity(store.path)
        self.children = []
        self.lock = threading.RLock()
        self.closed = False
        self.directory.attach(store.path, endpoint, instance)

    def catalog(self):
        return dict(current=self.key, path=str(self.store.path.resolve()),
                    can_open=self.enabled, rows=self.directory.list(self.key))

    def open(self, *, key=None, path=None, name=None, create=False, current_view='/'):
        if not self.enabled:
            raise InputError('Workspace switching is available on local servers. Start a separate server for a container workspace.')
        self.directory.save_view(self.key, current_view)
        with self.lock:
            validate_name(name)
            if self.closed:
                raise InputError('The workspace server is stopping')
            if bool(key) == bool(path):
                raise InputError('Choose a recent workspace or enter a database path')
            if key:
                if create or name is not None:
                    raise InputError('Open an existing recent workspace without creation options')
                row = self.directory.get(key)
                target = Path(row['path'])
            else:
                target = database_path(path, base=self.store.path.resolve().parent)
                if target == self.directory.path:
                    raise InputError('Choose a workspace database, not the recent-workspace directory')
                if create:
                    # Reserve exclusively; never reuse or overwrite an existing database.
                    if not target.parent.is_dir():
                        raise InputError('Choose an existing parent directory')
                    try:
                        with target.open('xb'):
                            pass
                    except FileExistsError:
                        raise InputError('This path already exists; use Open existing') from None
                    from .store import Store
                    Store(target)
                validate_database(target)
                row = self.directory.remember(target, name)
            validate_database(target)
            if row['id'] == self.key:
                return dict(url=self.endpoint + self.directory.get(self.key)['last_view'], reused=True)
            if alive(row):
                self.directory.remember(target)
                return dict(url=row['endpoint'] + view_path(row['last_view']), reused=True)
            self.directory.claim(row['id'])
            port = urlsplit(row['endpoint']).port if row.get('endpoint') else 0
            ready, stop = threading.Event(), threading.Event()
            result = {}
            def on_ready(url):
                result['url'] = url
                ready.set()
            def run():
                try:
                    from .server import serve
                    from .store import Store
                    serve(Store(target), port=port, workspace_directory=self.directory,
                          stop_event=stop, on_ready=on_ready)
                except Exception as error:
                    result['error'] = str(error)
                    ready.set()
                finally:
                    self.directory.release(row['id'])
            thread = threading.Thread(target=run, name='rilldex-workspace', daemon=True)
            self.children.append((stop, thread))
            thread.start()
            if not ready.wait(30):
                stop.set()
                raise InputError('Workspace startup is taking too long; inspect its database and retry')
            if 'error' in result:
                raise InputError('Workspace could not start' + (f' on its saved capture port {port}. Close the conflicting server or start this database on a new port and update its collectors' if port else '') + ': ' + result['error'])
            return dict(url=result['url'] + view_path(row['last_view']), reused=False)

    def forget(self, key):
        if key == self.key:
            raise InputError('The current workspace stays in the recent list')
        row = self.directory.get(key)
        if alive(row) or row['opening_until'] > time.time():
            raise InputError('Close the workspace server before removing it from recents')
        self.directory.forget(key)
        return dict(removed=True)

    def close(self):
        with self.lock:
            self.closed = True
            children = list(self.children)
        for stop, _ in children:
            stop.set()
        for _, thread in children:
            thread.join(timeout=15)
        self.directory.detach(self.key, self.instance)
