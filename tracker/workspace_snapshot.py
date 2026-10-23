"""Consistent, inspectable workspace transfer without model calls or overwrites."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .schema import InputError, dumps

VERSION = 'inspection-workspace/1'
MAX_DATABASE_BYTES = 8 * 1024**3


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _counts(store):
    with store.connect() as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name:c.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}


def _freeze_observers(store):
    from . import semantic_catalog, observer_archive
    profiles = {**semantic_catalog.PROFILES, **semantic_catalog.registered(store)}
    pairs = set()
    with store.connect() as c:
        pairs.update((r[0],r[1]) for r in c.execute('SELECT DISTINCT observer,run_id FROM rollout_graphs') if r[0] in profiles)
    for observer, profile in semantic_catalog.registered(store).items():
        pairs.update((observer,rid) for rid in profile.get('members',{}))
        if profile.get('run_id'):
            pairs.add((observer,profile['run_id']))
    unavailable = []
    for observer, rid in sorted(pairs):
        try:
            run = store.get(rid,raw=True)['run']
            result = semantic_catalog.load(run,observer,store)
            if not result.get('available'):
                raise InputError('Original observer result is unavailable')
            observer_archive.save(store,run,observer,result)
        except (InputError, KeyError, OSError, ValueError) as e:
            unavailable.append({'observer':observer,'run_id':rid,'reason':str(e)})
    return {'archived':len(observer_archive.rows(store)),'unavailable':unavailable,
            'scope':'Available saved results and their structural audit receipts; no provider rerun or original candidate-workspace relocation'}


def _publish_new(source, destination):
    """Publish a completed local artifact atomically, without replacing a file."""
    try:
        os.link(source,destination)
    except FileExistsError:
        raise InputError('Destination already exists; choose a new path') from None
    except OSError as e:
        raise InputError('Could not publish the new file atomically; use a local filesystem supporting hard links: '+str(e)) from e


def export(store, destination):
    from .store import Store
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise InputError('Destination already exists; choose a new snapshot path')
    destination.parent.mkdir(parents=True,exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='.jev-snapshot-',dir=destination.parent) as tmp:
        database = Path(tmp)/'workspace.sqlite'
        # Copy through SQLite, including committed WAL pages. Do not copy a live
        # .sqlite file with filesystem tools or mutate the source database.
        with store.connect() as source, closing(sqlite3.connect(database)) as target:
            page_size = source.execute('PRAGMA page_size').fetchone()[0]
            # Pin a WAL read snapshot before copying chunks. Without this,
            # each collector heartbeat can restart a large backup from page 1.
            # Readers retain a consistent version while the collector writes.
            source.execute('BEGIN')
            source.execute('SELECT rootpage FROM sqlite_schema LIMIT 1').fetchone()
            def progress(status, remaining, total):
                if time.monotonic()-started > 120:
                    raise InputError('Snapshot could not finish within 120 seconds; retry during a quieter collection window')
                if total * page_size > MAX_DATABASE_BYTES:
                    raise InputError('Workspace exceeds the portable snapshot size limit')
            source.backup(target,pages=256,progress=progress,sleep=.05)
        snapshot = Store(database)
        with snapshot.connect() as c:
            connections = c.execute('SELECT count(*) FROM data_connections WHERE enabled=1').fetchone()[0]
            jobs = c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            c.execute('UPDATE data_connections SET enabled=0')
            c.execute("UPDATE jobs SET status='paused',error='Paused in portable snapshot; submit a new job explicitly to continue' WHERE status IN ('queued','running')")
        observers = _freeze_observers(snapshot)
        counts = _counts(snapshot)
        # Archive is one SQLite file, independent of transient WAL/SHM files.
        with snapshot.connect() as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if c.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise InputError('Snapshot database integrity check failed')
        if database.stat().st_size > MAX_DATABASE_BYTES:
            raise InputError('Workspace exceeds the 8 GiB portable snapshot size limit')
        manifest = {'schema':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),
            'database':{'name':'workspace.sqlite','bytes':database.stat().st_size,'sha256':file_hash(database)},
            'tables':counts,'observers':observers,'paused':{'connections':connections,'inference_jobs':jobs},
            'preserved':['sources','revision receipts','graphs','review notes','measurements','investigations','training facts'],
            'excluded':['external worker outboxes','training output directories','externally referenced artifact bytes (their metadata is preserved)','candidate-generation and audit workspace files'],
            'restore':'Restore to a new database path. Connections and pending inference are paused; resume only the intended producers.'}
        archive = Path(tmp)/'snapshot.rilldex.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            z.writestr('manifest.json',dumps(manifest))
            z.write(database,'workspace.sqlite')
        _publish_new(archive,destination)
    return manifest


def _members(z):
    if sorted(z.namelist()) != ['manifest.json','workspace.sqlite']:
        raise InputError('Snapshot must contain exactly manifest.json and workspace.sqlite')
    info = z.getinfo('manifest.json')
    database = z.getinfo('workspace.sqlite')
    if info.file_size > 4*1024*1024 or database.file_size > MAX_DATABASE_BYTES:
        raise InputError('Snapshot exceeds the manifest or 8 GiB database limit')
    if info.flag_bits & 1 or database.flag_bits & 1:
        raise InputError('Encrypted snapshots are not supported')
    try:
        manifest = json.loads(z.read('manifest.json'))
    except (ValueError, UnicodeError) as e:
        raise InputError('Invalid snapshot manifest') from e
    if not isinstance(manifest,dict) or manifest.get('schema') != VERSION:
        raise InputError('Unknown workspace snapshot schema')
    spec = manifest.get('database')
    if not isinstance(spec,dict) or spec.get('name') != 'workspace.sqlite' or spec.get('bytes') != database.file_size:
        raise InputError('Snapshot database size/name differs from its manifest')
    return manifest


def inspect(path):
    try:
        with zipfile.ZipFile(path) as z:
            manifest = _members(z)
            sha = hashlib.sha256()
            with z.open('workspace.sqlite') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):
                    sha.update(chunk)
            if sha.hexdigest() != manifest['database'].get('sha256'):
                raise InputError('Snapshot database checksum does not match')
        return manifest
    except (zipfile.BadZipFile, RuntimeError) as e:
        raise InputError('Unreadable workspace snapshot: '+str(e)) from e


def restore(path, destination):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise InputError('Destination database already exists; restore into a new path')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.jev-restore-',dir=destination.parent) as tmp:
        database = Path(tmp)/'workspace.sqlite'
        try:
            with zipfile.ZipFile(path) as z:
                manifest = _members(z)
                with z.open('workspace.sqlite') as source, database.open('xb') as target:
                    shutil.copyfileobj(source,target,length=1024*1024)
            if file_hash(database) != manifest['database'].get('sha256'):
                raise InputError('Snapshot database checksum does not match')
            with closing(sqlite3.connect(database)) as c:
                c.execute('PRAGMA trusted_schema=OFF')
                if c.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise InputError('Snapshot database integrity check failed')
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'runs','rollout_graphs','graph_nodes','graph_edges','jobs','data_connections'} <= tables:
                    raise InputError('Snapshot lacks required tracker tables')
                c.execute('UPDATE data_connections SET enabled=0')
                c.execute("UPDATE jobs SET status='paused',error='Paused on workspace restore' WHERE status IN ('queued','running')")
                c.commit()
                c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            _publish_new(database,destination)
        except (zipfile.BadZipFile, sqlite3.Error, RuntimeError) as e:
            raise InputError('Cannot restore workspace snapshot: '+str(e)) from e
    return {'database':str(destination),'manifest':manifest,'status':'restored','inference_started':False}
