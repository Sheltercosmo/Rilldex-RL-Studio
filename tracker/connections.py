"""Managed, restartable local collectors. Source files are never modified."""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone

from .schema import InputError, digest, dumps, metadata
from .watch import DirectoryWatcher
from .collector_lock import ProducerLock


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS data_connections (
        id TEXT PRIMARY KEY, producer TEXT NOT NULL UNIQUE, config TEXT NOT NULL,
        enabled INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)''')


def validate(store, body):
    if not isinstance(body, dict) or set(body)-{'root','producer','format','metadata','interval','max_files','task_root','mode','pattern','max_records','snapshot_state'}:
        raise InputError('Supply root, producer, format, metadata and optional collection limits')
    interval = body.get('interval', 2)
    limit = body.get('max_files', 10000)
    if isinstance(interval, bool) or not isinstance(interval, (int,float)) or not 0.2 <= interval <= 300:
        raise InputError('Collection interval must be between 0.2 and 300 seconds')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100000:
        raise InputError('File limit must be between 1 and 100000')
    if not isinstance(body.get('root'), str) or not body['root'].strip():
        raise InputError('Enter the output directory on the tracker host')
    if '://' in body['root']:
        from pathlib import Path
        from .cloud_watch import CloudWatcher, source
        source(body['root'])
        # Stable cache path lives beside the workspace, never on an object mount.
        cache = Path(store.path).resolve().parent / 'cloud-cache' / digest([body['root'], body.get('producer')])
        cache.mkdir(parents=True, exist_ok=True)
        config, local = validate(store, {**body, 'root': str(cache)})
        return {**config, 'root': body['root']}, CloudWatcher(local, body['root'])
    raw_meta = body.get('metadata', {})
    if not isinstance(raw_meta, dict):
        raise InputError('Metadata defaults must be a JSON object')
    mode = body.get('mode', 'native')
    if mode not in {'native', 'exports', 'snapshots'}:
        raise InputError('Collection mode must be native, exports or snapshots')
    if mode == 'snapshots':
        from .snapshot_watch import SnapshotWatcher
        if body.get('task_root') or 'max_records' in body:
            raise InputError('Snapshot collection does not use task roots or JSONL row limits')
        watcher = SnapshotWatcher(store, body['root'], producer=body.get('producer'),
            format=body.get('format','auto'), metadata=raw_meta, max_files=limit,
            pattern=body.get('pattern','*.json'), snapshot_state=body.get('snapshot_state','in_progress'))
        return dict(root=str(watcher.root), producer=watcher.producer, format=watcher.format,
                    metadata=watcher.metadata, interval=interval, max_files=limit, mode=mode,
                    pattern=watcher.pattern, snapshot_state=watcher.snapshot_state), watcher
    if 'snapshot_state' in body:
        raise InputError('Snapshot state is only used by JSON snapshot collection')
    if mode == 'exports':
        from .export_watch import ExportWatcher
        if body.get('task_root'):
            raise InputError('Task root is only used by native directory collection')
        watcher = ExportWatcher(store, body['root'], producer=body.get('producer'),
            format=body.get('format','auto'), metadata=raw_meta, max_files=limit,
            pattern=body.get('pattern','*.jsonl'), max_records=body.get('max_records',100))
        return dict(root=str(watcher.root),producer=watcher.producer,format=watcher.format,
                    metadata=watcher.metadata,interval=interval,max_files=limit,mode=mode,
                    pattern=watcher.pattern,max_records=watcher.max_records), watcher
    if 'pattern' in body or 'max_records' in body:
        raise InputError('Pattern and record limits are only used by JSONL export collection')
    watcher = DirectoryWatcher(store, body['root'], producer=body.get('producer'),
        format=body.get('format','auto'), metadata=metadata(raw_meta),
        task_root=body.get('task_root'), max_files=limit)
    config = dict(root=str(watcher.root),producer=watcher.producer,format=watcher.format,
                  metadata=watcher.metadata,interval=interval,max_files=limit,
                  task_root=str(watcher.task_root) if watcher.task_root else None)
    return config, watcher


def preview(store, body):
    if isinstance(body, dict) and '://' in str(body.get('root', '')):
        import tempfile
        from .cloud_watch import CloudWatcher, source
        source(body['root'])
        with tempfile.TemporaryDirectory(prefix='jev-cloud-check-') as tmp:
            config, local = validate(store, {**body, 'root': tmp})
            remote = CloudWatcher(local, body['root']).mirror(limit=5, byte_budget=32 * 1024 * 1024)
            report = preview(store, {**body, 'root': tmp})
            report['config'] = {**config, 'root': body['root']}
            report['cloud'] = remote
            return report
    from .connection_check import check
    config, watcher = validate(store, body)
    paths = watcher._paths()
    return {'config':config,'files':len(paths),
            'sample':[str(p.relative_to(watcher.root)).replace('\\','/') for p in paths[:8]],
            **check(watcher, paths)}


def create(store, body):
    config, _ = validate(store, body)
    cid = 'connection-' + digest(config)
    with store.connect() as c:
        prior = c.execute('SELECT * FROM data_connections WHERE producer=?',(config['producer'],)).fetchone()
        if prior:
            if json.loads(prior['config']) != config:
                raise InputError('This producer already has a connection. Use its existing configuration or a different producer name.')
            c.execute('UPDATE data_connections SET enabled=1 WHERE id=?',(prior['id'],))
            return {'id':prior['id'],'created':False}
        c.execute('INSERT INTO data_connections VALUES (?,?,?,?,?,?)',
            (cid,config['producer'],dumps(config),1,dumps({'phase':'waiting','received_revisions':0}),now()))
    return {'id':cid,'created':True}


def set_enabled(store, cid, enabled):
    if not isinstance(enabled, bool):
        raise InputError('enabled must be true or false')
    with store.connect() as c:
        if not c.execute('UPDATE data_connections SET enabled=? WHERE id=?',(int(enabled),cid)).rowcount:
            raise KeyError(cid)
    return {'id':cid,'enabled':enabled}


def relocate(store, cid, body):
    """Change a paused collector's mount without changing producer/row identity."""
    if not isinstance(body,dict) or set(body)-{'root','task_root'} or not body.get('root'):
        raise InputError('Supply the new output root and optional task root')
    with store.connect() as c:
        row = c.execute('SELECT * FROM data_connections WHERE id=?',(cid,)).fetchone()
    if row is None:raise KeyError(cid)
    if row['enabled']:raise InputError('Pause collection before changing its output directory')
    previous = json.loads(row['config'])
    config, _ = validate(store,{**previous,**body})
    # A paused setting is a request, not proof an in-flight read has returned.
    with ProducerLock(store, row['producer']), store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        current = c.execute('SELECT enabled,config FROM data_connections WHERE id=?',(cid,)).fetchone()
        if current['enabled'] or current['config'] != row['config']:
            raise InputError('Connection changed; reload before changing its output directory')
        status = json.loads(row['status'])
        status.update(phase='paused',error=None,errors=[],deferred=0,waiting=0,backlog=0,
                      relocated_at=now(),previous_root=previous['root'])
        c.execute('UPDATE data_connections SET config=?,status=? WHERE id=?',(dumps(config),dumps(status),cid))
    return {'id':cid,'config':config,'enabled':False,
            'note':'Producer identity and receipts retained. Resume to validate and follow the relocated output.'}


def definitions(store):
    with store.connect() as c:
        return [{**dict(r),'config':json.loads(r['config']),'status':json.loads(r['status'])}
                for r in c.execute('SELECT * FROM data_connections ORDER BY created_at,id')]


class Collector:
    def __init__(self, store, row, notify):
        self.store, self.row, self.notify = store, row, notify
        self.stop = threading.Event()
        self.waiting_for_owner = False
        self.error = None
        self.thread = threading.Thread(target=self.loop, name='collector-'+row['producer'], daemon=True)
        self.thread.start()

    def loop(self):
        ownership = ProducerLock(self.store, self.row['producer'])
        try:
            while not self.stop.is_set():
                try:
                    if ownership.acquire():
                        self.waiting_for_owner = False
                        self.error = None
                        return self.collect()
                    self.waiting_for_owner = True
                except OSError as error:
                    self.error = str(error)
                self.stop.wait(self.row['config']['interval'])
        finally:
            ownership.close()

    def collect(self):
        config = self.row['config']
        with self.store.connect() as c:
            current = c.execute('SELECT * FROM data_connections WHERE id=?', (self.row['id'],)).fetchone()
        if not current or not current['enabled'] or json.loads(current['config']) != config:
            return
        status = json.loads(current['status'])
        watcher = None
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                if watcher is None:
                    _, watcher = validate(self.store, config)
                report = watcher.poll(self.stop)
                ingested = [r for r in report['entries'] if r['status']=='ingested']
                errors = [r for r in report['entries'] if r['status']=='deferred']
                status = {**status,'phase':'retrying' if errors else 'watching','error':None,
                    'checked_at':now(),'scan_seconds':round(time.monotonic()-started,3),
                    'files':report['scanned'],'deferred':report['deferred'],
                    'waiting':report.get('waiting',0),'backlog':report.get('backlog',0),
                    'cloud': report.get('cloud'),
                    'received_revisions':status.get('received_revisions',0)+len(ingested),
                    'errors':errors[:20]}
                if (report.get('cloud') or {}).get('state') == 'current':
                    status['last_cloud_sync_at'] = now()
                if ingested:
                    status['last_received_at'] = now()
                    status['recent'] = (ingested + status.get('recent',[]))[:20]
                    self.notify()
            except Exception as error:
                # A missing mount, invalid file, or failed scan does not stop
                # other connections. Retain the last valid committed revision.
                status = {**status,'phase':'error','error':str(error),'checked_at':now()}
                watcher = None
            with self.store.connect() as c:
                c.execute('UPDATE data_connections SET status=? WHERE id=? AND config=?',
                          (dumps(status),self.row['id'],dumps(config)))
            self.stop.wait(max(0.05, config['interval']-(time.monotonic()-started)))

    def close(self, timeout=10):
        self.stop.set()
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()


class Service:
    """One manager, independent collectors, and one shared change stream.

    SSE is a current-state notification, not an event ledger. Reconnect always
    sends the latest state; immutable rollout revisions remain the data ledger.
    """
    def __init__(self, store, monitor):
        self.store, self.monitor = store, monitor
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.collectors = {}
        self.sequence = 0
        self.session = uuid.uuid4().hex
        self.state = None
        self.thread = threading.Thread(target=self.loop,name='live-intake-manager',daemon=True)
        self.thread.start()

    def snapshot(self):
        from .producer_health import snapshot as producer_snapshot
        rows = definitions(self.store)
        with self.store.connect() as c:
            # Append-only identity and state revisions, independent of slow
            # semantic materialization. Also notices imports from another CLI.
            source = [tuple(c.execute('SELECT count(*),max(imported_at) FROM runs').fetchone()),
                      tuple(c.execute('SELECT count(*),max(rowid) FROM rollout_revisions').fetchone())]
            from .training_lineage import revision as training_revision
            training = training_revision(c)
            telemetry = c.execute('SELECT count(*),max(received_at) FROM trainer_telemetry').fetchone()
            training = digest([training,list(telemetry)])
            execution = digest(tuple(c.execute('SELECT count(*),max(rowid) FROM execution_records').fetchone()))
            cohort = digest(tuple(c.execute('SELECT count(*),max(rowid) FROM generation_cohorts').fetchone()))
            semantic = digest(tuple(c.execute('SELECT count(*),max(updated_at) FROM semantic_watch_jobs').fetchone())) if c.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_watch_jobs'").fetchone() else None
            latest = [dict(r) for r in c.execute('''SELECT rr.producer,rr.rollout_id,rr.revision,rr.state,rr.run_id,
                rr.created_at, json_extract(r.document,'$.metadata.training_step') training_step,
                json_extract(r.document,'$.metadata.experiment') experiment,
                json_extract(r.document,'$.metadata.source_export_path') export_path,
                json_extract(r.document,'$.metadata.source_line') source_line
                FROM rollout_revisions rr JOIN runs r ON r.id=rr.run_id
                WHERE rr.revision=(SELECT max(revision) FROM rollout_revisions
                  WHERE producer=rr.producer AND rollout_id=rr.rollout_id)
                ORDER BY rr.created_at DESC LIMIT 30''')]
        producers = producer_snapshot(self.store)
        received = {p['producer']: {k: p[k] for k in ('received_revisions', 'received_rollouts', 'last_receipt_at')} for p in producers}
        for row in rows:
            row.update(self.runtime(row['id']))
            row['received'] = received.get(row['producer'], dict(received_revisions=0, received_rollouts=0, last_receipt_at=None))
        return {'source_revision':digest(source),'training_revision':training,'execution_revision':execution,'cohort_revision':cohort,'semantic_revision':semantic,'connections':rows,'recent_rollouts':latest,'producers':producers,
                'analysis':self.monitor.status(),'checked_at':now(),
                'transport':'server-sent events','inference':'No automatic model calls; semantic coverage is shown separately.'}

    def runtime(self, cid):
        collector = self.collectors.get(cid)
        alive = bool(collector and collector.thread.is_alive())
        stopping = bool(alive and collector.stop.is_set())
        waiting = bool(alive and collector.waiting_for_owner and not stopping)
        return dict(running=bool(alive and not stopping and not waiting and not collector.error),
                    stopping=stopping, waiting_for_owner=waiting,
                    collector_error=collector.error if alive else None)

    def loop(self):
        try:
            self.manage()
        finally:
            # Signal all readers first. The manager retains their ownership until
            # they actually exit, even if close(timeout) has returned to the caller.
            collectors = tuple(self.collectors.values())
            for collector in collectors:
                collector.stop.set()
            for collector in collectors:
                collector.close(timeout=None)

    def manage(self):
        prior_source = None
        while not self.stop.is_set():
            try:
                rows = definitions(self.store)
                desired = {r['id']:r for r in rows if r['enabled']}
                for cid in list(self.collectors):
                    collector = self.collectors[cid]
                    if cid not in desired or collector.row['config'] != desired[cid]['config']:
                        collector.stop.set()
                    if not collector.thread.is_alive():
                        del self.collectors[cid]
                for cid,row in desired.items():
                    if cid not in self.collectors and not self.stop.is_set():
                        self.collectors[cid] = Collector(self.store,row,self.monitor.wake)
                state = self.snapshot()
                if state['source_revision'] != prior_source:
                    self.monitor.wake()
                    prior_source = state['source_revision']
            except Exception as error:
                state = {**(self.state or {}),'error':str(error),'checked_at':now()}
            with self.condition:
                self.state = state
                self.sequence += 1
                self.condition.notify_all()
            self.stop.wait(1)

    def wait(self, after=None):
        with self.condition:
            self.condition.wait_for(lambda:self.state is not None and self.sequence!=after or self.stop.is_set(),timeout=15)
            return self.sequence, self.state

    def close(self, timeout=10):
        self.stop.set()
        for collector in tuple(self.collectors.values()):
            collector.stop.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()
