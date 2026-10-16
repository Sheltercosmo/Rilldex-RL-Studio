"""Explicit scheduler populations; completion is never inferred from arrivals.

Membership snapshots are bounded and append-only until sealed. Producer-declared
generation state, delivered sources and observation availability have separate
grains. All projections use the caller's read transaction and perform no writes.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json

from .schema import InputError, digest, dumps

VERSION = 'generation-cohorts/1'
STATES = ('admitted', 'completed', 'failed', 'cancelled')
CONTEXT = ('split', 'environment', 'environment_version', 'task_revision', 'sampling', 'reward_definition')
MEMBER_CONTEXT = ('task_id', 'policy_version', 'environment', 'environment_version')
COLUMNS = ('producer','experiment','cohort_id','revision','label','clock','basis','coordinate',
           'sealed','document_json','received_at','is_latest')
VIEW_SQL = '''SELECT producer,experiment,cohort_id,revision,
  json_extract(document,'$.label') label,json_extract(document,'$.coordinate.clock') clock,
  json_extract(document,'$.coordinate.basis') basis,json_extract(document,'$.coordinate.index') coordinate,
  json_extract(document,'$.sealed') sealed,document document_json,received_at,
  revision=(SELECT max(p.revision) FROM generation_cohorts p WHERE p.producer=g.producer
    AND p.experiment=g.experiment AND p.cohort_id=g.cohort_id) is_latest FROM generation_cohorts g'''
EMPTY_SQL = 'SELECT '+','.join('NULL AS '+k for k in COLUMNS)+' WHERE 0'


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS generation_cohorts (
      producer TEXT NOT NULL,experiment TEXT NOT NULL,cohort_id TEXT NOT NULL,
      revision INTEGER NOT NULL,document TEXT NOT NULL,received_at TEXT NOT NULL,
      PRIMARY KEY(producer,experiment,cohort_id,revision));''')


def _text(value, name):
    if not isinstance(value,str) or not value.strip() or len(value)>500:
        raise InputError(name+' must be nonempty text of at most 500 characters')


def _integer(value, name):
    if type(value) is not int or value<0:raise InputError(name+' must be a nonnegative integer')


def member_key(member):
    return member['producer'],member['rollout_id']


def validate(packet):
    if not isinstance(packet,dict) or set(packet)!={'schema','producer','experiment','cohorts'} or packet['schema']!=VERSION:
        raise InputError('Use generation-cohorts/1 with producer, experiment and cohorts')
    _text(packet['producer'],'producer');_text(packet['experiment'],'experiment')
    if not isinstance(packet['cohorts'],list) or not 1<=len(packet['cohorts'])<=100:
        raise InputError('Supply 1–100 cohort snapshots')
    seen=set();total=0
    for row in packet['cohorts']:
        if not isinstance(row,dict) or set(row)!={'id','revision','label','coordinate','context','sealed','members','evidence'}:
            raise InputError('Cohort needs id, revision, label, coordinate, context, sealed, members and evidence')
        for k in ('id','label','evidence'):_text(row[k],k)
        _integer(row['revision'],'revision')
        identity=row['id'],row['revision']
        if identity in seen:raise InputError('Duplicate cohort revision in packet')
        seen.add(identity)
        coordinate=row['coordinate']
        if not isinstance(coordinate,dict) or set(coordinate)!={'clock','basis','index'}:
            raise InputError('Coordinate needs clock, basis and index')
        _text(coordinate['clock'],'clock');_text(coordinate['basis'],'basis');_integer(coordinate['index'],'index')
        if not isinstance(row['context'],dict) or set(row['context'])-set(CONTEXT):raise InputError('Invalid cohort context')
        for k,v in row['context'].items():_text(v,k)
        if type(row['sealed']) is not bool:raise InputError('sealed must be an explicit boolean')
        if not isinstance(row['members'],list):raise InputError('Members must be a list, including an explicit empty list')
        total+=len(row['members'])
        if total>10000:raise InputError('Packet exceeds 10,000 declared members; use bounded generation windows')
        keys=set()
        for member in row['members']:
            if not isinstance(member,dict) or set(member)!={'producer','rollout_id','generation_state','context'}:
                raise InputError('Member needs producer, rollout_id, generation_state and context')
            _text(member['producer'],'member producer');_text(member['rollout_id'],'member rollout_id')
            if member_key(member) in keys:raise InputError('Duplicate member in cohort')
            keys.add(member_key(member))
            if member['generation_state'] not in STATES:raise InputError('Invalid generation state')
            if not isinstance(member['context'],dict) or set(member['context'])-set(MEMBER_CONTEXT):raise InputError('Invalid member context')
            for k,v in member['context'].items():_text(v,k)
            if any(k in row['context'] and row['context'][k]!=v for k,v in member['context'].items()):
                raise InputError('Member context conflicts with cohort context')
    dumps(packet)
    return packet


def _compatible(a,b):
    if a['revision']==b['revision']:return a==b
    low,high=sorted((a,b),key=lambda r:r['revision'])
    if any(low[k]!=high[k] for k in ('id','label','coordinate','context')):return False
    before={member_key(m):m for m in low['members']};after={member_key(m):m for m in high['members']}
    if not before.keys()<=after.keys():return False
    if low['sealed'] and (not high['sealed'] or before.keys()!=after.keys()):return False
    for key,member in before.items():
        later=after[key]
        if member['context']!=later['context']:return False
        if member['generation_state']!='admitted' and member['generation_state']!=later['generation_state']:return False
    return True


def receive(store,packet):
    from .store import ReviewConflict
    validate(packet);inserted=0
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for row in packet['cohorts']:
            key=packet['producer'],packet['experiment'],row['id']
            neighbors=[c.execute('SELECT document FROM generation_cohorts WHERE producer=? AND experiment=? AND cohort_id=? AND revision'+op+'? ORDER BY revision '+order+' LIMIT 1',(*key,row['revision'])).fetchone()
                       for op,order in [('<=','DESC'),('>','ASC')]]
            if any(old and not _compatible(json.loads(old[0]),row) for old in neighbors):
                raise ReviewConflict('Cohort coordinate, membership or generation state conflicts with retained evidence')
            inserted+=c.execute('INSERT OR IGNORE INTO generation_cohorts VALUES (?,?,?,?,?,?)',
                (*key,row['revision'],dumps(row),datetime.now(timezone.utc).isoformat())).rowcount
    return dict(id='cohort-packet-'+digest(packet),revision=0,inserted=inserted,cohorts=len(packet['cohorts']))


def snapshot(store, *, experiment, environment=None, monitor=None, windows=None, include_members=False, clock=None, basis=None, limit=100, cohort_id=None, producer=None):
    """One read snapshot, including declared members whose traces never arrived."""
    with store.read_snapshot() as saved:
        return project(saved,experiment=experiment,environment=environment,monitor=monitor,windows=windows,
            include_members=include_members,clock=clock,basis=basis,limit=limit,cohort_id=cohort_id,producer=producer)


def project(store, *, experiment, environment=None, monitor=None, windows=None, include_members=False, clock=None, basis=None, limit=100, cohort_id=None, producer=None):
    from . import monitoring
    if not experiment or experiment=='__unassigned__':
        return dict(available=False,reason='Select an experiment to inspect declared generation cohorts.',cohorts=[])
    _text(experiment,'experiment')
    if type(limit) is not int or not 1<=limit<=1000:raise InputError('limit must be 1–1,000 cohorts')
    for name,value in [('clock',clock),('basis',basis),('environment',environment),('cohort_id',cohort_id),('producer',producer)]:
        if value is not None:_text(value,name)
    if type(include_members) is not bool:raise InputError('include_members must be boolean')
    if windows is not None:
        if not isinstance(windows,dict) or not 1<=len(windows)<=32:raise InputError('Use 1–32 named coordinate ranges')
        for name,bounds in windows.items():
            _text(name,'window name')
            if not isinstance(bounds,(list,tuple)) or len(bounds)!=2 or any(type(v) is not int or v<0 for v in bounds) or bounds[0]>bounds[1]:
                raise InputError('Window bounds must be ordered nonnegative integer pairs')
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_schema WHERE name='generation_cohorts'").fetchone():
            return dict(available=False,reason='No generation-cohort contract in this workspace.',cohorts=[])
        conditions=['is_latest=1','experiment=?'];parameters=[experiment]
        for name,value in [('clock',clock),('basis',basis),('cohort_id',cohort_id),('producer',producer)]:
            if value is not None:conditions.append(name+'=?');parameters.append(value)
        if windows:
            conditions.append('('+' OR '.join('coordinate BETWEEN ? AND ?' for _ in windows)+')')
            parameters.extend(v for bounds in windows.values() for v in bounds)
        if environment is not None:
            conditions.append("(json_extract(document_json,'$.context.environment')=? OR EXISTS (SELECT 1 FROM json_each(document_json,'$.members') m WHERE json_extract(m.value,'$.context.environment')=?))")
            parameters.extend([environment,environment])
        declarations=c.execute('SELECT * FROM ('+VIEW_SQL+') WHERE '+' AND '.join(conditions)+
            ' ORDER BY coordinate DESC,clock,basis,producer,cohort_id LIMIT ?',(*parameters,limit+1)).fetchall()
        truncated=len(declarations)>limit;selected=[];member_count=0
        for declaration in declarations[:limit]:
            row=json.loads(declaration['document_json'])
            if windows is not None and not any(a<=row['coordinate']['index']<=b for a,b in windows.values()):continue
            members=[m for m in row['members'] if environment is None or m['context'].get('environment',row['context'].get('environment'))==environment]
            if environment is not None and not members and row['context'].get('environment')!=environment:continue
            if member_count+len(members)>100000:truncated=True;break
            member_count+=len(members)
            selected.append((declaration,row,members))
        sources={member_key(m):None for _,_,members in selected for m in members}
        # Resolve only declared identities; never associate by timestamps or task text.
        identities=dumps(list(sources))
        for saved in c.execute('''SELECT v.*,json_extract(r.document,'$.metadata') metadata,
            json_extract(r.document,'$.outcome') outcome,r.imported_at FROM json_each(?) ids
            JOIN rollout_revisions v ON v.producer=json_extract(ids.value,'$[0]')
                AND v.rollout_id=json_extract(ids.value,'$[1]')
            JOIN runs r ON r.id=v.run_id WHERE v.revision=(SELECT max(w.revision)
                FROM rollout_revisions w WHERE w.producer=v.producer AND w.rollout_id=v.rollout_id)''',(identities,)):
            sources[(saved['producer'],saved['rollout_id'])]=dict(saved)
        executions=defaultdict(list)
        if c.execute("SELECT 1 FROM sqlite_schema WHERE name='execution_records'").fetchone():
            from .execution_records import VIEW_SQL as execution_sql
            attempts=c.execute("SELECT e.* FROM ("+execution_sql+") e JOIN json_each(?) ids ON e.rollout_producer=json_extract(ids.value,'$[0]') AND e.rollout_id=json_extract(ids.value,'$[1]') WHERE is_latest=1 AND experiment=? AND kind='rollout' LIMIT 100001",(identities,experiment)).fetchall()
            if len(attempts)>100000:raise InputError('Execution projection exceeds 100,000 attempts')
            for attempt in attempts:executions[(attempt['rollout_producer'],attempt['rollout_id'])].append(dict(attempt))
    definition=None;values={};runs={}
    for source in sources.values():
        if source:
            run=dict(id=source['run_id'],metadata=json.loads(source['metadata']),outcome=json.loads(source['outcome'] or '{}'))
            runs[run['id']]={**run,'state':source['state'],'imported_at':source['imported_at']}
    if monitor:
        definition=next((m for m in monitoring.definitions(store) if m['id']==monitor),None)
        if definition is None:raise InputError('Unknown cohort monitor')
        eligible=[r for r in runs.values() if monitoring.in_population(definition,r)]
        values=monitoring.current_values(store,definition,eligible)
    cohorts=[];union=set();delivered_union=set();overlap=Counter()
    for declaration,row,members in selected:
        cases=[]
        for member in members:
            key=member_key(member);overlap[key]+=1;union.add(key)
            source=sources[key];run=runs.get(source['run_id']) if source else None
            meta=run['metadata'] if run else {};expected={**row['context'],**member['context']}
            conflicts=[k for k,v in expected.items() if meta.get(k) is not None and meta[k]!=v] if run else []
            if run and meta.get('experiment') not in (None,experiment):conflicts.append('experiment')
            coordinate={'training_clock':row['coordinate']['clock'],'training_step_basis':row['coordinate']['basis'],'training_step':row['coordinate']['index']}
            same_clock=bool(run and meta.get('training_clock')==coordinate['training_clock'] and meta.get('training_step_basis')==coordinate['training_step_basis'])
            different_clock=bool(run and any(meta.get(k) is not None and meta[k]!=coordinate[k] for k in ('training_clock','training_step_basis')))
            coordinate_conflicts=['training_step'] if same_clock and meta.get('training_step') is not None and meta['training_step']!=coordinate['training_step'] else []
            conflicts+=coordinate_conflicts
            linked=bool(run and not conflicts)
            if linked:delivered_union.add(key)
            measured=values.get(run['id']) if linked and source['state']=='complete' and definition and monitoring.in_population(definition,run) else None
            outcome=run.get('outcome',{}) if linked and source['state'] not in ('in_progress','failed') else {}
            attempts=executions[key]
            cases.append(dict(**member,source_status='conflicting_context' if conflicts else 'delivered' if run else 'not_delivered',
                conflicts=conflicts,population_context=expected,run_id=run['id'] if run else None,source_revision=source['revision'] if source else None,
                capture_state=source['state'] if source else None,
                coordinate_alignment='conflicting' if coordinate_conflicts else 'different_clock' if different_clock else 'matching' if run and all(meta.get(k)==v for k,v in coordinate.items()) else 'unrecorded',
                outcome=dict(recorded_reward=outcome.get('recorded_reward'),verified_success=outcome.get('verified_success')),
                measurement=measured,
                measurement_status=measured['status'] if measured else 'outside_monitor_population' if linked and definition and not monitoring.in_population(definition,run) else 'capture_incomplete' if linked and definition and source['state']!='complete' else 'pending' if linked and definition else 'unavailable' if definition else 'not_requested',
                attempts=[dict(producer=a['producer'],id=a['record_id'],revision=a['revision'],state=a['state'],retry_of=a['retry_id']) for a in attempts]))
        states=Counter(m['generation_state'] for m in members);all_states=Counter(m['generation_state'] for m in row['members']);delivered=[case for case in cases if case['source_status']=='delivered']
        known=[case for case in cases if case['measurement'] and case['measurement'].get('value') is not None]
        monitor_value=None
        if known:
            if monitoring.aggregation(definition) in ('opportunity_ratio','anchor_ratio'):
                denominator=sum(case['measurement'].get('denominator') or 0 for case in known)
                monitor_value=sum(case['measurement'].get('numerator') or 0 for case in known)/denominator if denominator else None
            else:monitor_value=sum(case['measurement']['value'] for case in known)/len(known)
        count=len(members)
        cohorts.append(dict(producer=declaration['producer'],id=row['id'],revision=row['revision'],label=row['label'],
            coordinate=row['coordinate'],context=row['context'],sealed=row['sealed'],declared=count,
            windows=[name for name,(a,b) in (windows or {}).items() if a<=row['coordinate']['index']<=b],
            membership_scope='environment subset' if environment else 'entire declared cohort',
            generation_states={state:states[state] for state in STATES},
            generation_settled=bool(row['sealed'] and not all_states['admitted']),
            selected_generation_settled=bool(row['sealed'] and not states['admitted']),
            whole_cohort_declared=len(row['members']),whole_cohort_pending=all_states['admitted'],
            delivered=len(delivered),source_conflicts=sum(bool(case['conflicts']) for case in cases),
            complete_captures=sum(case['capture_state']=='complete' for case in delivered),
            reward_available=sum(case['outcome']['recorded_reward'] is not None for case in cases),
            success_available=sum(type(case['outcome']['verified_success']) is bool for case in cases),
            recorded_reward_mean=_mean([case['outcome']['recorded_reward'] for case in cases]),
            verified_success_rate=_mean([int(case['outcome']['verified_success']) for case in cases if type(case['outcome']['verified_success']) is bool]),
            outcome_support=outcome_support(cases, sealed=row['sealed']),
            outcome_selection=outcome_selection(cases),
            monitor_value=monitor_value,measured=len(known),measurement_coverage=len(known)/count if count and definition else None,
            measurement_statuses=dict(Counter(case['measurement_status'] for case in cases)),
            coordinate_alignment=dict(Counter(case['coordinate_alignment'] for case in cases)),
            execution_attempts=sum(len(case['attempts']) for case in cases),
            task_mix=[dict(task_id=task,declared=sum(m['context'].get('task_id')==task for m in members),
                delivered=sum(case['context'].get('task_id')==task for case in delivered),measured=sum(case['context'].get('task_id')==task for case in known))
                for task in sorted({m['context'].get('task_id') for m in members},key=lambda t:str(t))],
            **({'members':cases} if include_members else {})))
    cohorts.sort(key=lambda r:(r['coordinate']['clock'],r['coordinate']['basis'],r['coordinate']['index'],r['producer'],r['id']))
    core=dict(schema='generation-cohort-evidence/1',experiment=experiment,environment=environment,monitor=monitor,
        clock=clock,basis=basis,windows=windows,limit=limit,truncated=truncated,cohort_id=cohort_id,producer=producer,
        available=bool(cohorts),reason=None if cohorts else 'No declared generation cohorts in this scope.',cohorts=cohorts,
        distinct_declared_rollouts=len(union),overlapping_members=sum(n>1 for n in overlap.values()),
        distinct_delivered_rollouts=len(delivered_union),
        scope='Producer-declared workload only. Cohorts may overlap; they are never summed as independent samples. Sealing fixes membership, not scoring, observation or learner-use completeness.',
        clock_boundary='Windows use declared cohort coordinates. Source chart alignment is checked separately; clocks are never inferred from receipt order.',
        limits=['Generation states are scheduler declarations, not task outcomes or live heartbeats.',
                'Outcome availability is not scorer closure. No learner non-use is inferred from missing records.',
                'Monitor means use available declared members; missing members remain in coverage counts.'])
    return {**core,'snapshot_id':'cohort-evidence-'+digest(core)}


def outcome_support(cases, *, sealed):
    """Logical bounds for the fixed declared set, never a confidence interval.

    A failed/cancelled execution has an unknown task outcome unless an explicit
    compatible completed/imported source supplies it. In-progress and failed
    captures never supply a final source outcome. Overlapping cohorts must be deduplicated by
    the caller before using this function for a population summary.
    """
    known=[c['outcome']['verified_success'] for c in cases if type(c['outcome']['verified_success']) is bool]
    total=len(cases);success=sum(known);unknown=total-len(known)
    return dict(declared=total,known=len(known),successes=success,unknown=unknown,
        observed_rate=success/len(known) if known else None,
        coverage=len(known)/total if total else None,
        fixed_membership=sealed,
        lower=success/total if total and sealed else None,
        upper=(success+unknown)/total if total and sealed else None,
        complete=bool(total and sealed and not unknown),
        boundary='Bounds assign every unknown declared outcome failure or success. They are not confidence intervals, predictions, or an assumption that cancelled work will be scored. Open membership has no final-population bound.')


def outcome_selection(cases):
    """Expose observed outcome mix against declarations, without difficulty labels."""
    result=[];total=len(cases)
    for field in ('environment','task_id','policy_version'):
        groups=defaultdict(list)
        for case in cases:groups[case.get('population_context',case['context']).get(field)].append(case)
        if not any(key is not None for key in groups):continue
        known_total=sum(type(c['outcome']['verified_success']) is bool for c in cases)
        rows=[]
        for key,group in sorted(groups.items(),key=lambda kv:str(kv[0])):
            known=[c['outcome']['verified_success'] for c in group if type(c['outcome']['verified_success']) is bool]
            rows.append(dict(value=key,declared=len(group),known=len(known),
                declared_share=len(group)/total,observed_share=len(known)/known_total if known_total else None,
                success_rate=sum(known)/len(known) if known else None))
        result.append(dict(field=field,groups=rows,
            representation_distance=sum(abs(g['declared_share']-g['observed_share']) for g in rows)/2 if known_total else None,
            boundary='Total variation distance between declared and outcome-observed group shares. A difference describes selection, not its cause or task difficulty.'))
    return result


def _mean(values):
    known=[v for v in values if type(v) in (int,float)]
    return sum(known)/len(known) if known else None


def review(evidence):
    """Population checks, not a causal diagnosis or a stop/continue instruction."""
    if not evidence.get('available'):
        return [dict(code='scheduled_population_unknown',title='Scheduled membership is not recorded',
            evidence='This comparison can describe received sources, but cannot count work that has not reported.',
            next_check='Record scheduler cohort membership or compare a known fixed evaluation population. Do not treat source coverage as scheduler closure.')]
    cohorts=evidence['cohorts'];unsettled=sum(not r['generation_settled'] for r in cohorts)
    missing=evidence['distinct_declared_rollouts']-evidence['distinct_delivered_rollouts']
    checks=[]
    if missing or unsettled:
        checks.append(dict(code='declared_population_incomplete',title='Declared work is not fully represented',
            evidence=f"{evidence['distinct_delivered_rollouts']}/{evidence['distinct_declared_rollouts']} declared rollout identities have compatible sources; {unsettled}/{len(cohorts)} cohorts are open or have pending generation.",
            next_check='Inspect pending members and task delivery mix, then compare the same windows after late evidence arrives. Check learner-use records separately: waiting cannot undo a change to optimizer inputs.'))
    if evidence.get('truncated'):
        checks.append(dict(code='declared_population_truncated',title='Declared population view is bounded',evidence='Some cohort declarations were omitted by the cohort or member read limit.',
            next_check='Narrow the generation clock and windows through Workspace.cohort_readiness before drawing a whole-experiment conclusion.'))
    return checks
