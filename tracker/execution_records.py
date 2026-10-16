"""Producer-reported execution attempts, independent of traces and training uses."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math

from .schema import InputError, digest, dumps

VERSION = 'execution-records/1'
STATES = ('queued','running','suspended','completed','failed','cancelled')
TERMINAL = {'completed','failed','cancelled'}
CONTEXT = ('split','framework','framework_version','environment','environment_version','harness','harness_version',
           'worker','backend','backend_version','server','pool','model','model_role','policy_version','task_id','group_id')
METRICS = ('duration_ms','queue_ms','elapsed_ms','input_tokens','output_tokens')
DEFAULT_GROUPS = ('split','environment','environment_version','backend','model','model_role')
COLUMNS = ('producer','experiment','record_id','revision','kind','rollout_producer','rollout_id','state',
           *CONTEXT,*METRICS,'source_revision','parent_producer','parent_id','retry_producer','retry_id',
           'observed_at','received_at','document_json','is_latest')
EMPTY_SQL = 'SELECT '+','.join('NULL AS '+k for k in COLUMNS)+' WHERE 0'
VIEW_SQL = '''SELECT e.producer,e.experiment,e.record_id,e.revision,e.kind,e.rollout_producer,e.rollout_id,e.state,
  '''+','.join("json_extract(e.document,'$.context."+k+"') "+k for k in CONTEXT)+','+','.join(
    "json_extract(e.document,'$.metrics."+k+"') "+k for k in METRICS)+''',
  json_extract(e.document,'$.source_revision') source_revision,
  json_extract(e.document,'$.parent.producer') parent_producer,json_extract(e.document,'$.parent.id') parent_id,
  json_extract(e.document,'$.retry_of.producer') retry_producer,json_extract(e.document,'$.retry_of.id') retry_id,
  json_extract(e.document,'$.observed_at') observed_at,e.received_at,e.document document_json,
  e.revision=(SELECT max(p.revision) FROM execution_records p WHERE p.producer=e.producer
    AND p.experiment=e.experiment AND p.record_id=e.record_id) is_latest FROM execution_records e'''


def initialize(connection):
    connection.executescript('''CREATE TABLE IF NOT EXISTS execution_records (
      producer TEXT NOT NULL,experiment TEXT NOT NULL,record_id TEXT NOT NULL,revision INTEGER NOT NULL,
      kind TEXT NOT NULL,rollout_producer TEXT NOT NULL,rollout_id TEXT NOT NULL,state TEXT NOT NULL,
      document TEXT NOT NULL,received_at TEXT NOT NULL,PRIMARY KEY(producer,experiment,record_id,revision));
      CREATE INDEX IF NOT EXISTS execution_rollout ON execution_records(experiment,rollout_producer,rollout_id);
    ''')


def _text(value, name):
    if not isinstance(value,str) or not value.strip() or len(value)>500:
        raise InputError(name+' must be nonempty text of at most 500 characters')


def _reference(value, name):
    if not isinstance(value,dict) or set(value)!={'producer','id'}:
        raise InputError(name+' needs producer and id')
    for k,v in value.items(): _text(v,name+' '+k)


def validate(packet):
    if not isinstance(packet,dict) or set(packet)!={'schema','producer','experiment','records'} or packet['schema']!=VERSION:
        raise InputError('Use execution-records/1 with producer, experiment and records')
    _text(packet['producer'],'producer');_text(packet['experiment'],'experiment')
    if not isinstance(packet['records'],list) or not 1<=len(packet['records'])<=1000:
        raise InputError('Supply 1–1,000 execution records')
    seen=set()
    for r in packet['records']:
        required={'id','revision','kind','rollout','state','context','evidence'}
        if not isinstance(r,dict) or not required<=set(r) or set(r)-required-{'parent','retry_of','source_revision','metrics','observed_at','reason'}:
            raise InputError('Invalid execution record fields')
        _text(r['id'],'execution id');_text(r['evidence'],'capture evidence')
        if type(r['revision']) is not int or r['revision']<0:raise InputError('Execution revision must be a nonnegative integer')
        identity=(r['id'],r['revision'])
        if identity in seen:raise InputError('Duplicate execution identity in packet')
        seen.add(identity)
        if r['kind'] not in ('rollout','inference','environment','verification'):raise InputError('Invalid execution kind')
        if r['state'] not in STATES:raise InputError('Invalid execution state')
        _reference(r['rollout'],'rollout')
        for k in ('parent','retry_of'):
            if k in r:
                _reference(r[k],k)
                if r[k]=={'producer':packet['producer'],'id':r['id']}:raise InputError('Execution cannot reference itself')
        if not isinstance(r['context'],dict) or set(r['context'])-set(CONTEXT):raise InputError('Invalid execution context fields')
        for k,v in r['context'].items():_text(v,'context '+k)
        if 'source_revision' in r and (type(r['source_revision']) is not int or r['source_revision']<0):
            raise InputError('source_revision must be a nonnegative integer')
        if 'reason' in r:_text(r['reason'],'reason')
        if 'observed_at' in r:
            try:
                stamp=datetime.fromisoformat(r['observed_at'])
                if stamp.utcoffset() is None:raise ValueError()
            except (TypeError,ValueError):raise InputError('observed_at needs an ISO timestamp with timezone')
        metrics=r.get('metrics',{})
        if not isinstance(metrics,dict) or set(metrics)-set(METRICS):raise InputError('Invalid execution metrics')
        for k,v in metrics.items():
            if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise InputError('Execution metrics must be finite and nonnegative')
            if k.endswith('_tokens') and type(v) is not int:raise InputError('Token counts must be integers')
        if 'duration_ms' in metrics and r['state'] not in TERMINAL:raise InputError('duration_ms is a terminal duration; use elapsed_ms for unfinished work')
    return packet


def _compatible(old, new):
    if old['revision']==new['revision']:return old==new
    low,high=sorted((old,new),key=lambda r:r['revision'])
    if any(low[k]!=high[k] for k in ('kind','rollout')):return False
    for k in ('parent','retry_of','source_revision'):
        if k in low and low[k]!=high.get(k):return False
    if any(v!=high['context'].get(k) for k,v in low['context'].items()):return False
    if low['state'] in TERMINAL and high['state']!=low['state']:return False
    if low['state']!='queued' and high['state']=='queued':return False
    return True


def receive(store, packet):
    from .store import ReviewConflict
    validate(packet);inserted=0
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in packet['records']:
            key=(packet['producer'],packet['experiment'],r['id'])
            # Adjacent explicit revisions suffice: stable-field and terminal rules are transitive.
            previous=c.execute('SELECT document FROM execution_records WHERE producer=? AND experiment=? AND record_id=? AND revision<=? ORDER BY revision DESC LIMIT 1',(*key,r['revision'])).fetchone()
            following=c.execute('SELECT document FROM execution_records WHERE producer=? AND experiment=? AND record_id=? AND revision>? ORDER BY revision LIMIT 1',(*key,r['revision'])).fetchone()
            if any(p and not _compatible(json.loads(p[0]),r) for p in (previous,following)):
                raise ReviewConflict('Execution identity, context or lifecycle conflicts with retained evidence; use a new attempt/segment ID')
            inserted+=c.execute('INSERT OR IGNORE INTO execution_records VALUES (?,?,?,?,?,?,?,?,?,?)',
                (*key,r['revision'],r['kind'],r['rollout']['producer'],r['rollout']['id'],r['state'],dumps(r),datetime.now(timezone.utc).isoformat())).rowcount
    return dict(id='execution-packet-'+digest(packet),revision=0,inserted=inserted,records=len(packet['records']))


def summary(data, *, experiment, kind='rollout', group_by=DEFAULT_GROUPS, limit=100000):
    """Observed attempts, not success rates or actual cluster liveness.

Latency quantiles use nearest rank, with explicit measured/eligible counts.
No cross-host timestamp subtraction, no training-clock inference.
"""
    _text(experiment,'experiment')
    if kind not in ('rollout','inference','environment','verification'):raise InputError('Choose one execution kind')
    if not isinstance(group_by,(list,tuple)) or not group_by or len(group_by)>8 or len(set(group_by))!=len(group_by) or any(k not in CONTEXT for k in group_by):
        raise InputError('Choose 1–8 distinct execution context fields')
    with data.snapshot() as snapshot:
        if not snapshot.available('executions'):raise InputError('Execution records are unavailable in this workspace/dataset; upgrade the collector or export with this table')
        columns=','.join(group_by)
        selected=snapshot.query('SELECT '+columns+''',state,duration_ms,queue_ms,elapsed_ms,output_tokens,
          retry_id FROM rl_executions WHERE is_latest=1 AND experiment=? AND kind=?''',(experiment,kind),limit=limit)
    if selected['truncated']:raise InputError('Execution population exceeds limit; narrow the experiment or use scoped SQL')
    return _summary_rows(selected['rows'],experiment,kind,group_by,selected['captured_at'])


def overview(store, experiment, environment=None, limit=100000):
    """Whole-experiment lifecycle context. Never pretend it has step coordinates.

    Uses the caller's snapshot when present; no competing read connection.
    Retries remain attempts, not independent rollout outcomes.
    """
    if not experiment or experiment=='__unassigned__':
        return dict(available=False,reason='Select one experiment to inspect execution reports.')
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_schema WHERE name='execution_records'").fetchone():
            return dict(available=False,reason='Execution lifecycle reports have not been collected.')
        rows=c.execute('SELECT * FROM ('+VIEW_SQL+''') WHERE is_latest=1 AND experiment=? AND kind='rollout'
            AND (? IS NULL OR environment=?) LIMIT ?''',(experiment,environment,environment,limit+1)).fetchall()
    if len(rows)>limit:return dict(available=False,reason='Too many execution reports; narrow the environment or use scoped SQL.')
    result=_summary_rows([dict(r) for r in rows],experiment,'rollout',DEFAULT_GROUPS+('policy_version',),datetime.now(timezone.utc).isoformat())
    return dict(available=True,**result,latest_received_at=max((r['received_at'] for r in rows),default=None),
        scope='Entire selected experiment/environment, not the selected comparison steps.',population_closed=None)


def _summary_rows(selected,experiment,kind,group_by,captured_at):
    groups=defaultdict(list)
    for row in selected:groups[tuple(row[k] for k in group_by)].append(row)
    total=len(selected);completed=sum(r['state']=='completed' for r in selected)
    result=[]
    for key,rows in groups.items():
        counts=Counter(r['state'] for r in rows)
        def distribution(field,eligible):
            values=sorted(r[field] for r in eligible if r[field] is not None)
            quantile=lambda p:values[max(0,math.ceil(p*len(values))-1)] if values else None
            return dict(measured=len(values),eligible=len(eligible),p50=quantile(.5),p95=quantile(.95),max=values[-1] if values else None)
        admitted=len(rows)/total if total else None
        completed_share=counts['completed']/completed if completed else None
        result.append(dict(context=dict(zip(group_by,key)),attempts=len(rows),states={s:counts[s] for s in STATES},
            unfinished=sum(counts[s] for s in ('queued','running','suspended')),
            explicit_retry_attempts=sum(r['retry_id'] is not None for r in rows),
            observed_share=admitted,completed_share=completed_share,
            completion_mix_shift=completed_share-admitted if completed_share is not None else None,
            completed_duration_ms=distribution('duration_ms',[r for r in rows if r['state']=='completed']),
            completed_output_tokens=distribution('output_tokens',[r for r in rows if r['state']=='completed']),
            queue_ms=distribution('queue_ms',rows),
            unfinished_elapsed_ms=distribution('elapsed_ms',[r for r in rows if r['state'] not in TERMINAL])))
    return dict(schema='execution-summary/1',captured_at=captured_at,experiment=experiment,kind=kind,
        group_by=list(group_by),observed_attempts=total,groups=result,
        notes=['Counts cover reported attempts only; missing instrumentation is not zero workload.',
               'States are latest reported states, not heartbeats; stale running records do not prove active work.',
               'Completed is execution completion, not task success or learner consumption.',
               'Completion mix shift compares completed versus all observed attempts; it is descriptive, not causal.',
               'Durations/elapsed values are producer measurements; host timestamps are not subtracted.'])
