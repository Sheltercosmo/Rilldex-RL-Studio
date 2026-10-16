"""Producer-reported delivery state, separate from server-confirmed receipts.

Reports never establish capture completeness, model progress or training health.
Their durable sequence prevents delayed reports from refreshing old status.
"""
import json
import math
import re
import time
from datetime import datetime, timezone

from .schema import InputError, dumps

VERSION='producer-delivery/1'


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS producer_delivery (
        producer TEXT PRIMARY KEY, outbox_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        received REAL NOT NULL, document TEXT NOT NULL)''')


def validate(body):
    fields={'schema','producer','outbox_id','sequence','phase','interval_seconds','pending','blocked','sent',
            'pending_bytes','max_pending_bytes','oldest_pending_seconds'}
    if not isinstance(body,dict) or set(body)!=fields or body['schema']!=VERSION:
        raise InputError('Supply a producer-delivery/1 report with exactly the documented fields')
    if not isinstance(body['producer'],str) or not body['producer'].strip() or len(body['producer'])>240:
        raise InputError('Invalid producer identity')
    if not isinstance(body['outbox_id'],str) or not re.fullmatch('[a-f0-9]{32}',body['outbox_id']):
        raise InputError('Invalid durable outbox identity')
    for key in ('sequence','pending','blocked','sent','pending_bytes','max_pending_bytes'):
        if type(body[key]) is not int or not 0<=body[key]<2**63:raise InputError('Invalid delivery counter: '+key)
    if body['sequence']<1 or body['max_pending_bytes']<1 or body['phase'] not in {'running','stopped'}:
        raise InputError('Invalid report sequence, capacity or sender phase')
    interval=body['interval_seconds'];age=body['oldest_pending_seconds']
    if type(interval) not in (int,float) or not math.isfinite(interval) or not .2<=interval<=300:
        raise InputError('Report interval must be 0.2–300 seconds')
    if age is not None and (type(age) not in (int,float) or not math.isfinite(age) or age<0):
        raise InputError('Invalid oldest pending age')
    return body


def receive(store,body):
    from .store import ReviewConflict
    value=validate(body);stamp=time.time()
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM producer_delivery WHERE producer=?',(value['producer'],)).fetchone()
        if old and old['outbox_id']!=value['outbox_id']:
            raise ReviewConflict('Producer already reports another outbox. Resume the original queue or use a fresh producer namespace.')
        if old and value['sequence']<=old['sequence']:
            if value['sequence']==old['sequence'] and dumps(value)!=old['document']:
                raise ReviewConflict('Delivery report sequence reused with different content')
            return {'producer':value['producer'],'sequence':value['sequence'],'accepted':False}
        c.execute('INSERT OR REPLACE INTO producer_delivery VALUES (?,?,?,?,?)',
            (value['producer'],value['outbox_id'],value['sequence'],stamp,dumps(value)))
    return {'producer':value['producer'],'sequence':value['sequence'],'accepted':True}


def snapshot(store):
    stamp=time.time()
    with store.connect() as c:
        reports={r['producer']:dict(r) for r in c.execute('SELECT * FROM producer_delivery')}
        receipts={r['producer']:dict(r) for r in c.execute('''SELECT producer,count(*) received_revisions,
            count(DISTINCT rollout_id) received_rollouts,max(created_at) last_receipt_at
            FROM rollout_revisions GROUP BY producer''')}
    rows=[]
    for producer in sorted(reports.keys()|receipts.keys()):
        row={'producer':producer,**receipts.get(producer,{'received_revisions':0,'received_rollouts':0,'last_receipt_at':None})}
        saved=reports.get(producer)
        if saved:
            report=json.loads(saved['document']);age=max(0,stamp-saved['received'])
            status='stopped' if report['phase']=='stopped' else 'stale' if age>max(15,3*report['interval_seconds']) else 'blocked' if report['blocked'] else 'pending' if report['pending'] else 'current'
            row.update(report=report,status=status,report_age_seconds=round(age,1),
                reported_at=datetime.fromtimestamp(saved['received'],timezone.utc).isoformat())
        else:row.update(report=None,status='unreported',report_age_seconds=None,reported_at=None)
        rows.append(row)
    return rows
