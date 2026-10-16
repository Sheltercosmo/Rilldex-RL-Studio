"""Durable producer outbox; log() performs no network or model calls.

Use one outbox per producer/worker. The SQLite file is the restart identity;
keep it across retries. Delivery is at least once, with server-side idempotency.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .adapters import FORMATS
from .schema import InputError, digest, dumps, metadata as normalize_metadata


class Outbox:
    def __init__(self, path, *, endpoint='http://127.0.0.1:8765', producer,
                 max_pending_bytes=256*1024*1024, timeout=10):
        url = urlsplit(endpoint)
        if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise InputError('Use a tracker HTTP(S) endpoint without embedded credentials or query parameters')
        if url.scheme=='http' and url.hostname not in {'localhost','127.0.0.1','::1'}:
            raise InputError('Use loopback HTTP with an SSH tunnel, or HTTPS')
        if not isinstance(producer,str) or not producer.strip() or len(producer)>240:
            raise InputError('producer must contain 1–240 characters')
        if not isinstance(max_pending_bytes,int) or max_pending_bytes<1 or not 0<timeout<=60:
            raise InputError('Supply a positive pending-byte limit and timeout of at most 60s')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.producer,self.endpoint=producer,endpoint.rstrip('/')
        self.max_pending_bytes,self.timeout=max_pending_bytes,timeout
        self.stop=threading.Event();self.changed=threading.Event();self.thread=None
        self.report_thread=None;self.report_interval=5;self.report_error=None
        self.lock=threading.Lock()
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('BEGIN IMMEDIATE')
            c.execute('''CREATE TABLE IF NOT EXISTS identity (producer TEXT NOT NULL)''')
            row=c.execute('SELECT producer FROM identity').fetchone()
            if row and row[0]!=producer:raise InputError('This outbox belongs to a different producer')
            if row is None:c.execute('INSERT INTO identity(producer) VALUES (?)',(producer,))
            columns={r[1] for r in c.execute('PRAGMA table_info(identity)')}
            if 'outbox_id' not in columns:c.execute('ALTER TABLE identity ADD COLUMN outbox_id TEXT')
            if 'report_sequence' not in columns:c.execute('ALTER TABLE identity ADD COLUMN report_sequence INTEGER NOT NULL DEFAULT 0')
            c.execute('UPDATE identity SET outbox_id=? WHERE outbox_id IS NULL',(uuid.uuid4().hex,))
            c.execute('''CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY, rollout TEXT NOT NULL, revision INTEGER NOT NULL,
                hash TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', error TEXT, receipt TEXT,
                created REAL NOT NULL, sent REAL, UNIQUE(rollout,revision))''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def log(self, rollout_id, document, *, state, format='auto', metadata=None, sources=None):
        return self.log_many([dict(rollout_id=rollout_id,document=document,state=state,format=format,
                                   metadata=metadata,sources=sources)])[0]

    def _payload(self, rollout_id, document, *, state, format='auto', metadata=None, sources=None):
        if not isinstance(rollout_id,str) or not rollout_id.strip() or len(rollout_id)>240:
            raise InputError('rollout_id must contain 1–240 characters')
        if rollout_id.startswith(('@training/','@execution/','@cohorts/','@telemetry/')):
            raise InputError('This rollout prefix is reserved for fact-packet transport')
        if state not in {'in_progress','complete','failed'} or format not in FORMATS:
            raise InputError('Supply an explicit state and supported source format')
        if not isinstance(document,dict) or metadata is not None and not isinstance(metadata,dict):
            raise InputError('Document and metadata must be objects')
        value=dict(producer=self.producer,rollout_id=rollout_id,document=document,state=state,
                   format=format,metadata=normalize_metadata(metadata))
        if sources is not None:value['sources']=sources
        return value

    def log_many(self, snapshots):
        """Atomically enqueue 1–1,000 snapshots; no partial batch on backpressure.

        Delivery still occurs per rollout revision. Atomic local enqueue does
        not imply that all rows become visible on the receiving server at once.
        """
        if not isinstance(snapshots,(list,tuple)) or not 1<=len(snapshots)<=1000 or any(not isinstance(s,dict) for s in snapshots):
            raise InputError('Supply 1–1,000 snapshot objects')
        return self._enqueue([self._payload(**s) for s in snapshots])

    def log_training(self, experiment, records, *, schema=None):
        """Queue an immutable fact packet using the same bounded/retry transport.

        Version 1 references rollout identities. Opt-in training-records/2 uses
        independent sample IDs with optional pinned source mappings. Records may
        arrive before sources or after a restart through the same transport.
        """
        from .training_lineage import VERSION, validate
        packet=validate({'schema':schema or VERSION,'producer':self.producer,'experiment':experiment,'records':records})
        return self._enqueue([{'rollout_id':'@training/'+digest(packet),'training_records':packet}])[0]

    def log_execution(self, experiment, records):
        """Durably queue lifecycle facts without waiting for traces or other workers."""
        from .execution_records import VERSION, validate
        packet=validate(dict(schema=VERSION,producer=self.producer,experiment=experiment,records=records))
        return self._enqueue([{'rollout_id':'@execution/'+digest(packet),'execution_records':packet}])[0]

    def log_telemetry(self, experiment, records, *, schema=None):
        """Queue native trainer scalars independently of rollout identities."""
        from .trainer_telemetry import VERSION, validate
        packet=validate(dict(schema=schema or VERSION,producer=self.producer,experiment=experiment,records=records))
        return self._enqueue([{'rollout_id':'@telemetry/'+digest(packet),'trainer_telemetry':packet}])[0]

    def log_cohorts(self, experiment, cohorts):
        """Queue scheduler membership snapshots, including work not yet delivered.

        Reuse cohort IDs and increment their revision when membership or state
        changes. Sealing fixes membership; it does not declare scoring complete.
        """
        from .generation_cohorts import VERSION, validate
        packet=validate(dict(schema=VERSION,producer=self.producer,experiment=experiment,cohorts=cohorts))
        return self._enqueue([{'rollout_id':'@cohorts/'+digest(packet),'generation_cohorts':packet}])[0]

    def _enqueue(self, prepared):
        receipts=[]
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            pending=c.execute("SELECT coalesce(sum(bytes),0) FROM queue WHERE state!='sent'").fetchone()[0]
            for value in prepared:
                rollout_id=value['rollout_id'];content_hash=digest(value)
                prior=c.execute('SELECT * FROM queue WHERE rollout=? ORDER BY revision DESC LIMIT 1',(rollout_id,)).fetchone()
                if prior and prior['hash']==content_hash:
                    receipts.append({'queued_id':prior['id'],'revision':prior['revision'],'duplicate':True});continue
                value['revision']=prior['revision']+1 if prior else 0
                payload=dumps(value);size=len(payload.encode())
                if size>20*1024*1024:raise InputError('Snapshot exceeds the server 20 MiB request limit')
                if pending+size>self.max_pending_bytes:
                    raise BufferError('Tracker outbox is full; this batch was not queued. Retain source files and drain it before retrying. No queued data was dropped.')
                cursor=c.execute('INSERT INTO queue(rollout,revision,hash,payload,bytes,created) VALUES (?,?,?,?,?,?)',
                    (rollout_id,value['revision'],content_hash,payload,size,time.time()))
                pending+=size
                receipts.append({'queued_id':cursor.lastrowid,'revision':value['revision'],'duplicate':False})
        self.changed.set()
        return receipts

    def log_recipes(self, experiment, recipes):
        """Queue producer declarations with the same durable delivery semantics."""
        from .training_recipes import VERSION, validate
        packet=validate({'schema':VERSION,'producer':self.producer,'experiment':experiment,'recipes':recipes})
        return self._enqueue([{'rollout_id':'@training/recipes/'+digest(packet),'training_recipes':packet}])[0]

    def log_continuation_studies(self, experiment, studies):
        """Queue immutable prefix-experiment designs; outcomes arrive as training facts."""
        from .continuation_studies import VERSION, validate
        packet=validate({'schema':VERSION,'producer':self.producer,'experiment':experiment,'studies':studies})
        return self._enqueue([{'rollout_id':'@training/continuations/'+digest(packet),'continuation_studies':packet}])[0]

    def drain(self, limit=50):
        """Deliver eligible snapshots; permanent errors block only their rollout."""
        sent=0;retryable_error=False
        with self.lock:
            for _ in range(limit):
                if self.stop.is_set():break
                with self.connect() as c:
                    row=c.execute("""SELECT * FROM queue q WHERE state='pending' AND NOT EXISTS
                        (SELECT 1 FROM queue p WHERE p.rollout=q.rollout AND p.revision<q.revision AND p.state!='sent')
                        ORDER BY id LIMIT 1""").fetchone()
                if row is None:break
                error=None;state='pending';receipt=None
                try:
                    envelope=json.loads(row['payload']);training=envelope.get('training_records');recipes=envelope.get('training_recipes');continuations=envelope.get('continuation_studies');executions=envelope.get('execution_records')
                    cohorts=envelope.get('generation_cohorts')
                    endpoint='/api/generation-cohorts' if cohorts else '/api/execution-records' if executions else '/api/continuation-studies' if continuations else '/api/training-recipes' if recipes else '/api/training-records' if training else '/api/ingest'
                    telemetry=envelope.get('trainer_telemetry')
                    if telemetry:endpoint='/api/trainer-telemetry'
                    packet=telemetry or cohorts or executions or continuations or recipes or training
                    payload=dumps(packet).encode() if packet else row['payload'].encode()
                    request=Request(self.endpoint+endpoint,data=payload,headers={'Content-Type':'application/json'})
                    with urlopen(request,timeout=self.timeout) as response:
                        receipt=json.loads(response.read(65536))
                    if not isinstance(receipt,dict) or receipt.get('revision')!=row['revision'] or not receipt.get('id'):
                        raise ValueError('Tracker returned an invalid ingestion receipt')
                    if training and receipt['id']!='training-packet-'+digest(training):
                        raise ValueError('Tracker acknowledged a different training packet')
                    if telemetry and receipt['id']!='telemetry-packet-'+digest(telemetry):
                        raise ValueError('Tracker acknowledged a different telemetry packet')
                    if executions and receipt['id']!='execution-packet-'+digest(executions):
                        raise ValueError('Tracker acknowledged a different execution packet')
                    if cohorts and receipt['id']!='cohort-packet-'+digest(cohorts):
                        raise ValueError('Tracker acknowledged a different generation-cohort packet')
                    if recipes and receipt['id']!='recipe-packet-'+digest(recipes):
                        raise ValueError('Tracker acknowledged a different recipe packet')
                    if continuations and receipt['id']!='continuation-packet-'+digest(continuations):
                        raise ValueError('Tracker acknowledged a different continuation packet')
                    state='sent';sent+=1
                except HTTPError as exc:
                    error=f'HTTP {exc.code}: '+exc.read(1024).decode('utf-8',errors='replace')
                    state='pending' if exc.code==429 or exc.code>=500 else 'blocked'
                except (OSError,URLError,ValueError) as exc:
                    error=str(exc)
                with self.connect() as c:
                    c.execute("UPDATE queue SET state=?,error=?,receipt=?,sent=? WHERE id=? AND state!='sent'",
                        (state,error,dumps(receipt) if receipt else None,time.time() if state=='sent' else None,row['id']))
                    if state=='sent':
                        c.execute("UPDATE queue SET payload='',bytes=0 WHERE id=? AND state='sent'",(row['id'],))
                if error and state=='pending':retryable_error=True;break
        return {**self.status(),'sent_now':sent,'retryable_error':retryable_error}

    def status(self):
        with self.connect() as c:
            counts={r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM queue GROUP BY state')}
            pending=c.execute("SELECT coalesce(sum(bytes),0),min(created) FROM queue WHERE state!='sent'").fetchone()
            errors=[dict(r) for r in c.execute("SELECT id,rollout,revision,state,error FROM queue WHERE error IS NOT NULL AND state!='sent' ORDER BY id LIMIT 20")]
        return {'producer':self.producer,'pending':counts.get('pending',0),'blocked':counts.get('blocked',0),
                'sent':counts.get('sent',0),'pending_bytes':pending[0],
                'oldest_pending_seconds':round(max(0,time.time()-pending[1]),2) if pending[1] else None,'errors':errors,
                'delivery_report_error':self.report_error}

    def report_status(self, *, phase='running'):
        """Best-effort health report; failure never changes queued delivery.

        Only counters are sent. Reports exclude raw errors, source data and
        local paths. A durable sequence prevents delayed HTTP reports from
        overwriting a more recent report after a producer restart.
        """
        from .producer_health import VERSION
        try:
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute('UPDATE identity SET report_sequence=report_sequence+1')
                identity=c.execute('SELECT outbox_id,report_sequence FROM identity').fetchone()
                counts={r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM queue GROUP BY state')}
                size,oldest=c.execute("SELECT coalesce(sum(bytes),0),min(created) FROM queue WHERE state!='sent'").fetchone()
            report={'schema':VERSION,'producer':self.producer,'outbox_id':identity['outbox_id'],
                'sequence':identity['report_sequence'],'phase':phase,'interval_seconds':self.report_interval,
                'pending':counts.get('pending',0),'blocked':counts.get('blocked',0),'sent':counts.get('sent',0),
                'pending_bytes':size,'max_pending_bytes':self.max_pending_bytes,
                'oldest_pending_seconds':round(max(0,time.time()-oldest),2) if oldest is not None else None}
            request=Request(self.endpoint+'/api/producers/report',data=dumps(report).encode(),headers={'Content-Type':'application/json'})
            with urlopen(request,timeout=min(self.timeout,2)) as r:receipt=json.loads(r.read(65536))
            if not isinstance(receipt,dict) or receipt.get('producer')!=self.producer or receipt.get('sequence')!=report['sequence'] or type(receipt.get('accepted')) is not bool:
                raise ValueError('Invalid delivery report receipt')
            self.report_error=None
            return receipt
        except (OSError,URLError,ValueError,sqlite3.Error) as exc:
            self.report_error=str(exc)
            return {'error':self.report_error}

    def retry_blocked(self):
        """Explicit retry of unchanged payloads after fixing the receiver/config."""
        with self.connect() as c:
            count=c.execute("UPDATE queue SET state='pending',error=NULL WHERE state='blocked'").rowcount
        self.changed.set()
        return count

    def start(self, *, report_status=False, report_interval=5):
        if type(report_status) is not bool or type(report_interval) not in (int,float) or not .2<=report_interval<=300:
            raise InputError('Use a boolean report_status and report interval of 0.2–300 seconds')
        if self.thread and self.thread.is_alive():return self
        self.stop.clear()
        self.report_thread=None
        def loop():
            backoff=1
            while not self.stop.is_set():
                self.changed.clear()
                try:
                    result=self.drain()
                    retry=result['retryable_error']
                except (OSError,sqlite3.Error):retry=True
                if retry:
                    # New capture must not defeat transient-server backoff.
                    self.stop.wait(backoff);backoff=min(30,backoff*2)
                else:
                    backoff=1
                    # Continue successful batches immediately. A blocked
                    # rollout does not throttle unrelated eligible streams.
                    if result['sent_now'] and result['pending']:continue
                    self.changed.wait(1)
        self.thread=threading.Thread(target=loop,name='tracker-outbox',daemon=True);self.thread.start()
        self.report_interval=report_interval
        if report_status:
            def reports():
                while not self.stop.is_set():
                    self.report_status()
                    self.stop.wait(self.report_interval)
            self.report_thread=threading.Thread(target=reports,name='tracker-delivery-reports',daemon=True);self.report_thread.start()
        return self

    def close(self):
        self.stop.set();self.changed.set()
        if self.thread:self.thread.join(timeout=self.timeout+1)
        if self.report_thread:
            self.report_thread.join(timeout=3)
            self.report_status(phase='stopped')
        return self.status()

    def __enter__(self):return self.start()
    def __exit__(self,*args):self.close()
