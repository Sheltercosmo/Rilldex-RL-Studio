"""Offline implementation refresh for a worker's unchanged, pinned protocol."""
import json
from pathlib import Path

from .schema import InputError, digest, dumps
from .semantic_extraction import read


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS semantic_worker_refreshes (
        worker_id TEXT NOT NULL, fingerprint TEXT NOT NULL, document TEXT NOT NULL,
        PRIMARY KEY(worker_id,fingerprint))''')


def state(store, identifier, definition, current):
    if current==definition['extractor_fingerprint']:
        return {'status':'current','fingerprint':current}
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_worker_refreshes'").fetchone():
            row=None
        else:row=c.execute('SELECT document FROM semantic_worker_refreshes WHERE worker_id=? AND fingerprint=?',(identifier,current)).fetchone()
    if row:
        receipt=json.loads(row[0])
        return {'status':'current','fingerprint':current,'refresh':receipt}
    return {'status':'needs_refresh','fingerprint':current,
            'message':'Package implementation changed. Run semantic watch-refresh to replay saved evidence offline; protocols and spending limits stay pinned.'}


def refresh(store,directory,*,progress=None):
    from . import semantic_watch as worker,semantic_workspace as workspace,observer_archive
    root=Path(directory).resolve()
    with workspace.exclusive(root):
        identifier,definition,_=worker.load(store,root)
        current=worker.fingerprint(definition['workspace_options'])
        existing=state(store,identifier,definition,current)
        if existing['status']=='current':return dict(observer=identifier,implementation=existing,provider_calls=0)
        rows=[]
        for job in worker._jobs(store,identifier).values():
            job_root=root/'runs'/job['run_id']
            if not (job_root/'workspace.json').exists():
                if job['status']=='published':raise InputError('Published worker workspace is missing; restore it before refreshing')
                rows.append(dict(run_id=job['run_id'],state='not_started'));continue
            config,run=workspace.load(job_root)
            if digest(run)!=job['source_hash']:raise InputError('Saved worker source changed')
            audit=workspace.audit(job_root)
            row=dict(run_id=run['id'],state='saved_work_replayed',saved_decisions=audit['saved_decisions'])
            if job['status']=='published':
                replay=worker.materialize(identifier,definition,run,job_root)
                original=observer_archive.load(store,run,identifier)
                if original is None or digest(replay)!=original['archive']['result_hash']:
                    raise InputError('Published behavior map differs under this implementation; retain this worker and create a new observer for changed measurements')
                row.update(state='published_map_unchanged',result_hash=digest(replay))
            rows.append(row)
            if progress:progress(dict(checked=len(rows),run_id=run['id'],state=row['state']))
        # Nothing is enabled until every saved workspace and publication passes.
        # No job status, provider reservation, graph, or measurement is replaced.
        if worker.fingerprint(definition['workspace_options'])!=current:
            raise InputError('Implementation changed during refresh; run the offline refresh again')
        receipt=dict(schema='semantic-worker-refresh/1',at=worker.now(),
                     fingerprint=current,original_fingerprint=definition['extractor_fingerprint'],
                     workspace_options=definition['workspace_options'],jobs=rows,provider_calls=0)
        with store.connect() as c:
            initialize(c)
            c.execute('INSERT OR IGNORE INTO semantic_worker_refreshes VALUES (?,?,?)',(identifier,current,dumps(receipt)))
    return dict(observer=identifier,implementation=state(store,identifier,definition,current),provider_calls=0)
