"""Frozen, source-bound observer results for portable inspection snapshots.

These are preserved audit receipts, not a new extraction or a rerun of the
original candidate/decision workspace audit. Live databases need not use them.
"""
import json
from datetime import datetime, timezone

from .schema import InputError, digest, dumps


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS observer_archives (
        observer TEXT NOT NULL,run_id TEXT NOT NULL,source_hash TEXT NOT NULL,
        result_hash TEXT NOT NULL,document TEXT NOT NULL,captured_at TEXT NOT NULL,
        PRIMARY KEY(observer,run_id))''')


def rows(store):
    if store is None or not hasattr(store, 'connect'):
        return []
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='observer_archives' AND type='table'").fetchone():
            return []
        return [dict(r) for r in c.execute('SELECT observer,run_id,source_hash,result_hash,captured_at FROM observer_archives')]


def load(store, run, observer):
    if store is None or not hasattr(store, 'connect'):
        return None
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='observer_archives' AND type='table'").fetchone():
            return None
        row = c.execute('SELECT * FROM observer_archives WHERE observer=? AND run_id=?', (observer,run['id'])).fetchone()
    if row is None:
        return None
    result = json.loads(row['document'])
    if row['source_hash'] != digest(run) or row['result_hash'] != digest(result):
        raise InputError('Archived observer source or content changed')
    if result.get('observer', {}).get('id') != observer or not result.get('available'):
        raise InputError('Invalid archived observer identity')
    from .semantic_catalog import export_payload
    if result.get('export_digest') != digest(export_payload(result)):
        raise InputError('Archived observer export digest changed')
    return {**result, 'archive': {'schema':'observer-archive/1','captured_at':row['captured_at'],
            'result_hash':row['result_hash'], 'audit':'Preserved structural audit receipt; original extraction workspace is not rerun'}}


def save(store, run, observer, result):
    from .semantic_catalog import export_payload
    if not result.get('available') or result.get('observer',{}).get('id') != observer:
        raise InputError('Only available, identified observer results can be archived')
    result = {k:v for k,v in result.items() if k != 'archive'}
    if result.get('export_digest') != digest(export_payload(result)):
        raise InputError('Observer export changed before archival')
    with store.connect() as c:
        initialize(c)
        previous = c.execute('SELECT result_hash FROM observer_archives WHERE observer=? AND run_id=?', (observer,run['id'])).fetchone()
        if previous and previous[0] != digest(result):
            raise InputError('A different archived observer result already exists')
        c.execute('INSERT OR IGNORE INTO observer_archives VALUES (?,?,?,?,?,?)',
                  (observer,run['id'],digest(run),digest(result),dumps(result),datetime.now(timezone.utc).isoformat()))


def catalog_rows(store):
    output = []
    for row in rows(store):
        run = store.get(row['run_id'], raw=True)['run']
        result = load(store,run,row['observer'])
        output.append({'run_id':run['id'],'observer':row['observer'],'observer_label':result['observer']['label'],
            'task':run.get('metadata',{}).get('task_id') or run['id'],'adapter':run['adapter'],
            'source_hash':row['source_hash'],'extraction_hash':digest(result.get('raw_extraction',result['document'])),
            'storage':'archived','captured_at':row['captured_at']})
    return output
