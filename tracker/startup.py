"""Portable startup checks; no trainer, network service or model key required."""
import importlib.util
import platform
import socket
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from .schema import InputError


def doctor(db, port=8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise InputError('Port must be between 0 and 65535; 0 selects a free port')
    path = Path(db).expanduser().resolve()
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    checks = []
    checks.append({'name': 'Python', 'ok': sys.version_info >= (3, 11), 'detail': platform.python_version()})
    assets = Path(__file__).parent / 'web'
    missing = [name for name in ('monitoring.html', 'monitoring.js', 'connections.html', 'connections.js',
                                 'rollout-map.html', 'rollout-map.js') if not (assets / name).is_file()]
    checks.append({'name': 'Packaged application', 'ok': not missing, 'detail': ', '.join(missing) if missing else 'Web assets installed'})
    try:
        if path.exists():
            if not path.is_file():raise ValueError('Database path is a directory; select a .sqlite file inside it')
            if path.stat().st_size:
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as existing:
                    existing.execute('SELECT name FROM sqlite_master LIMIT 1').fetchone()
            # Check the actual file's write access, not just its parent directory.
            with path.open('r+b'):pass
        checks.append({'name':'Workspace path','ok':True,'detail':str(path)})
    except (OSError,ValueError,sqlite3.Error) as e:
        checks.append({'name':'Workspace path','ok':False,'detail':str(e)})
    try:
        with tempfile.TemporaryDirectory(prefix='jev-check-', dir=parent) as tmp:
            with closing(sqlite3.connect(str(Path(tmp) / 'probe.sqlite'))) as c:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE TABLE probe(value TEXT)')
                c.execute('INSERT INTO probe VALUES (?)', ('ok',))
                c.commit()
        checks.append({'name': 'Local storage', 'ok': True, 'detail': str(parent)})
    except (OSError, sqlite3.Error) as e:
        checks.append({'name': 'Local storage', 'ok': False, 'detail': str(e)})
    try:
        with socket.socket() as sock:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', port))
        checks.append({'name': 'Local port', 'ok': True, 'detail': 'Automatic free port' if port == 0 else str(port)})
    except OSError:
        checks.append({'name': 'Local port', 'ok': False, 'detail': f'Port {port} unavailable; use --port 0 or choose another port'})
    return {'ready': all(c['ok'] for c in checks), 'platform': platform.system(), 'database': str(path),
            'checks': checks, 'optional_tool_schema_checks': importlib.util.find_spec('jsonschema') is not None,
            'note': 'No training process or model provider contacted. SQLite should live on a local disk; remote output can be mounted read-only.'}
