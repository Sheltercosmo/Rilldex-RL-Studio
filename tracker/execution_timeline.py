"""Recorded execution time, native signals and exact sample lineage in one snapshot."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math

from .schema import InputError, digest, dumps
from . import policy_age, training_samples

VERSION = 'training-execution/1'


def _key(producer, identifier):
    return dumps([producer, identifier])


def _lineage(c, experiment, use_refs, rollout_refs):
    """Bound reads to referenced samples; never scan all experiments' traces."""
    use_keys = dumps([dict(producer=p, id=i) for p, i in use_refs])
    rollout_keys = dumps([dict(producer=p, id=i) for p, i in rollout_refs])
    uses = defaultdict(list); samples = []; by_source = defaultdict(list)
    for table, field, schema in [('training_records', 'rollout_id', 'training-records/1'),
                                 ('training_sample_records', 'sample_id', 'training-records/2')]:
        if not c.execute('SELECT 1 FROM sqlite_schema WHERE name=?', (table,)).fetchone(): continue
        selected_uses = c.execute(f'''SELECT t.* FROM {table} t JOIN json_each(?) k
            ON t.producer=json_extract(k.value,'$.producer') AND t.record_id=json_extract(k.value,'$.id')
            WHERE t.experiment=? AND t.kind='use' AND t.revision=0''', (use_keys, experiment)).fetchall()
        identities = {(r['sample_producer'], r[field]) for r in selected_uses}
        # Also include unused/rejected samples with an explicit execution source.
        mapping = ("t.sample_producer=json_extract(k.value,'$.producer') AND t.rollout_id=json_extract(k.value,'$.id')"
                   if schema.endswith('/1') else "json_extract(t.document,'$.data.source.producer')=json_extract(k.value,'$.producer') AND json_extract(t.document,'$.data.source.rollout_id')=json_extract(k.value,'$.id')")
        source_samples = c.execute(f'''SELECT t.sample_producer,t.{field} FROM {table} t JOIN json_each(?) k
            ON {mapping} WHERE t.experiment=? AND t.kind='sample' LIMIT 20001''', (rollout_keys, experiment)).fetchall()
        if len(source_samples)>20000: raise InputError('Too many source samples; narrow the execution interval')
        identities.update((r['sample_producer'], r[field]) for r in source_samples)
        rows = c.execute(f'''SELECT t.* FROM {table} t JOIN json_each(?) k
            ON t.sample_producer=json_extract(k.value,'$.producer') AND t.{field}=json_extract(k.value,'$.id')
            WHERE t.experiment=? AND t.revision=(SELECT max(p.revision) FROM {table} p
            WHERE p.experiment=t.experiment AND p.producer=t.producer AND p.record_id=t.record_id)
            LIMIT 50001''', (dumps([dict(producer=p,id=i) for p,i in sorted(identities)]),experiment)).fetchall()
        if len(rows)>50000: raise InputError('Too many sample facts; narrow the execution interval')
        groups=defaultdict(list)
        for row in rows: groups[(row['sample_producer'],row[field])].append(row)
        for identity, facts in groups.items():
            declarations=[r for r in facts if r['kind']=='sample']
            if len(declarations)!=1: continue
            declaration=json.loads(declarations[0]['document']); data=declaration['data']
            source=(data.get('source') if schema.endswith('/2') else
                    dict(producer=identity[0],rollout_id=identity[1],revision=declaration['evidence'].get('source_revision')))
            run_id,status=_source(c,experiment,source)
            if run_id and schema.endswith('/2'):
                document=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(run_id,)).fetchone()[0])
                if training_samples.binding_status(document,source)=='invalid_source_spans':run_id=None;status='invalid_source_spans'
            item=dict(id=dumps([schema,*identity]),schema=schema,producer=identity[0],sample_id=identity[1],
                      source=source,run_id=run_id,source_status=status,split=data['split'],
                      policy_history=data.get('policy_history'),scores=[],selections=[],uses=[])
            for row in facts:
                record=json.loads(row['document']); kind=record['kind']
                if kind not in {'score','selection','use'}:continue
                value=dict(producer=row['producer'],id=row['record_id'],revision=row['revision'],data=record['data'])
                if kind=='use':
                    value['data']={k:v for k,v in record['data'].items() if k in
                        {'stage','batch_id','learner_step','model_tokens','loss_tokens','learner_policy','recipe','advantage'}}
                item[{'score':'scores','selection':'selections','use':'uses'}[kind]].append(value)
                if kind=='use':
                    value['policy_age']=policy_age.observe(data.get('policy_history'),value['data'].get('learner_policy'),value['data'].get('model_tokens'))
                    uses[(row['producer'],row['record_id'])].append((item,value))
            samples.append(item)
            if source: by_source[(source['producer'],source['rollout_id'],source.get('revision'))].append(item['id'])
    return samples,uses,by_source


def _source(c,experiment,source):
    if not source or source.get('revision') is None:return None,'source_revision_not_declared'
    row=c.execute('''SELECT v.run_id,json_extract(r.document,'$.metadata.experiment') experiment
        FROM rollout_revisions v JOIN runs r ON r.id=v.run_id
        WHERE v.producer=? AND v.rollout_id=? AND v.revision=?''',
        (source['producer'],source['rollout_id'],source['revision'])).fetchone()
    if not row:return None,'source_not_delivered'
    if row['experiment'] is not None and row['experiment']!=experiment:return None,'experiment_conflict'
    return row['run_id'],'matched'


def snapshot(store, *, experiment, environment=None, clock=None, start=None, end=None, limit=1000):
    if not isinstance(experiment,str) or not experiment.strip():raise InputError('Select one experiment')
    if type(limit) is not int or not 1<=limit<=5000:raise InputError('Select 1–5,000 execution records')
    for value in (start,end):
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):raise InputError('Interval coordinates must be finite seconds')
    if (start is not None or end is not None) and not clock:raise InputError('Select a clock before an interval')
    if start is not None and end is not None and start>end:raise InputError('Interval end precedes start')
    with store.read_snapshot() as saved:
        with saved.connect() as c:
            available=c.execute("SELECT 1 FROM sqlite_schema WHERE name='execution_records'").fetchone()
            if not available:return dict(schema=VERSION,available=False,executions=[],logs=[],samples=[],clocks=[])
            base='''FROM execution_records t WHERE experiment=? AND revision=(SELECT max(p.revision)
                FROM execution_records p WHERE p.producer=t.producer AND p.experiment=t.experiment AND p.record_id=t.record_id)
                AND (? IS NULL OR json_extract(document,'$.context.environment')=?
                OR (json_extract(document,'$.context.environment') IS NULL AND kind IN ('learner_update','weight_sync','configuration')))'''
            args=[experiment,environment,environment]
            clocks=[dict(r) for r in c.execute('''SELECT json_extract(document,'$.timing.clock') clock,
                count(*) records,min(json_extract(document,'$.timing.start')) start,
                max(coalesce(json_extract(document,'$.timing.end'),json_extract(document,'$.timing.start'))) end '''+base+
                " GROUP BY json_extract(document,'$.timing.clock') ORDER BY clock",args)]
            query=base
            if clock:
                query+=" AND json_extract(document,'$.timing.clock')=?";args.append(clock)
            if start is not None:
                query+=" AND (json_extract(document,'$.timing.end')>=? OR json_extract(document,'$.timing.end') IS NULL)";args.append(start)
            if end is not None:
                query+=" AND json_extract(document,'$.timing.start')<=?";args.append(end)
            rows=c.execute('SELECT * '+query+" ORDER BY json_extract(document,'$.timing.start') DESC,producer,record_id LIMIT ?",(*args,limit+1)).fetchall()
            executions=[];refs=set();rollouts=set()
            for row in rows[:limit]:
                record=json.loads(row['document']);rollout=record['rollout']
                source=dict(producer=rollout['producer'],rollout_id=rollout['id'],revision=record.get('source_revision')) if rollout else None
                run_id,status=_source(c,experiment,source)
                executions.append(dict(id=_key(row['producer'],record['id']),producer=row['producer'],record=record,
                                       run_id=run_id,source_status=status if rollout else 'not_a_rollout',sample_ids=[]))
                refs.update((r['producer'],r['id']) for r in record.get('telemetry',[]))
                if rollout:rollouts.add((rollout['producer'],rollout['id']))
            samples,uses,by_source=_lineage(c,experiment,[],rollouts) if not refs else (None,None,None)
            logs=[];use_refs=set()
            for producer,identifier in sorted(refs):
                row=c.execute('SELECT document FROM trainer_telemetry WHERE experiment=? AND producer=? AND record_id=?',
                              (experiment,producer,identifier)).fetchone()
                if row:
                    record=json.loads(row[0]);use_refs.update((r['producer'],r['id']) for r in record.get('training_uses',{}).get('records',[]))
                    logs.append(dict(id=_key(producer,identifier),producer=producer,record=record))
            if refs:samples,uses,by_source=_lineage(c,experiment,use_refs,rollouts)
            for execution in executions:
                r=execution['record'];source=r['rollout']
                if source:execution['sample_ids']=by_source.get((source['producer'],source['id'],r.get('source_revision')),[])
            for log in logs:
                linked=log['record'].get('training_uses',{});selected=[];missing=[];ages=[]
                for ref in linked.get('records',[]):
                    candidates=uses.get((ref['producer'],ref['id']),[])
                    if len(candidates)!=1:missing.append(ref);continue
                    sample,use=candidates[0];selected.append(sample['id']);ages.append({'policy_age':use['policy_age']})
                log.update(sample_ids=sorted(set(selected)),unresolved_uses=missing,declared_uses=len(linked.get('records',[])),
                           coverage=linked.get('coverage','not_declared'),policy_age=policy_age.summarize(ages))
            logkeys={log['id'] for log in logs}
            missing_logs=[dict(producer=p,id=i) for p,i in refs if _key(p,i) not in logkeys]
            result=dict(schema=VERSION,available=True,experiment=experiment,environment=environment,
                captured_at=datetime.now(timezone.utc).isoformat(),selection=dict(clock=clock,start=start,end=end),
                clocks=clocks,executions=executions,logs=logs,samples=samples,missing_logs=missing_logs,
                truncated=len(rows)>limit,limit=limit,
                counts=dict(executions=len(executions),states=dict(Counter(e['record']['state'] for e in executions)),
                            linked_logs=len(logs),linked_samples=len(samples),source_linked_samples=sum(bool(s['run_id']) for s in samples)),
                boundary='Time coordinates share only a producer-declared clock. Native batch metrics stay whole; exact IDs establish links. No cross-clock alignment, causal verdict or stability threshold is inferred.')
            result['snapshot_id']='execution-view-'+digest({k:v for k,v in result.items() if k!='captured_at'})
            if len(dumps(result).encode())>16*1024*1024:raise InputError('Execution view exceeds 16 MiB; narrow the interval or limit')
            return result


def save(store, **selection):
    value=snapshot(store,**selection)
    with store.connect() as c:
        c.execute('INSERT OR IGNORE INTO execution_views VALUES (?,?,?)',(value['snapshot_id'],value['captured_at'],dumps(value)))
    return load(store,value['snapshot_id'])


def load(store, identifier):
    with store.connect() as c:
        row=c.execute('SELECT document FROM execution_views WHERE id=?',(identifier,)).fetchone()
    if not row:raise InputError('Unknown saved execution view')
    return {**json.loads(row[0]),'saved':identifier}
