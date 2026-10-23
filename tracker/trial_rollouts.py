"""Connect explicit trial output identities to frozen behavior comparisons."""
from copy import deepcopy
import json

from . import case_behavior, case_comparisons, case_studies, failure_investigations, monitoring
from .investigation_trials import compare, jobs
from .schema import InputError, digest

VERSION='trial-rollouts/1'


def check_in(doc, check_id):
    check=next((c for c in doc.get('follow_up',{}).get('checks',[]) if c['id']==check_id),None)
    if not check or not check.get('trial'):raise InputError('Choose a check with a saved trial')
    return check


def _sources(store, ids):
    with store.connect() as c:
        rows=c.execute('''SELECT r.*,coalesce((SELECT state FROM rollout_revisions WHERE run_id=r.id
            ORDER BY revision DESC LIMIT 1),'imported_snapshot') state
            FROM runs r JOIN json_each(?) j ON r.id=j.value ORDER BY r.id''',(json.dumps(sorted(ids)),)).fetchall()
    result={}
    for row in rows:
        run=json.loads(row['document'])
        result[row['id']]=dict(id=row['id'],source_hash=digest(run),imported_at=row['imported_at'],state=row['state'],
            metadata=deepcopy(run['metadata']),adapter=run['adapter'],outcome=deepcopy(run.get('outcome',{})))
    return result


def capture(store, check):
    """Resolve only producer-declared IDs; never infer membership by time/run name."""
    latest={r['job_id']:r for r in check.get('trial_results',[])}
    ids={rid for r in latest.values() for rid in r.get('rollout_ids',[])}
    with store.read_snapshot() as saved:
        sources=_sources(saved,ids)
        graphs=case_comparisons.capture(saved,list(sources.values()))['sources'] if sources else {}
    bindings=[]
    for job in jobs(check['trial']):
        result=latest.get(job['id']);linked=[]
        for rid in result.get('rollout_ids',[]) if result else []:
            source=sources.get(rid);reasons=[]
            if source:
                meta=source['metadata']
                if result.get('experiment') and meta.get('experiment')!=result['experiment']:reasons.append('Different experiment')
                if meta.get('trial_job_id') is not None and meta['trial_job_id']!=job['id']:reasons.append('Different recorded trial job')
                if meta.get('seed') is not None and str(meta['seed'])!=str(job['seed']):reasons.append('Different recorded seed')
            linked.append(dict(run_id=rid,status='unavailable' if not source else 'mismatch' if reasons else 'available',
                reasons=reasons,source=deepcopy(source),graphs=deepcopy(graphs.get(rid,{}).get('graphs',[]))))
        bindings.append(dict(job_id=job['id'],arm=job['arm'],seed=job['seed'],result_id=result['id'] if result else None,
            execution=result['status'] if result else 'pending',rollouts=linked))
    return dict(schema=VERSION,jobs=bindings,
        declared=len(ids),available=len({r['run_id'] for j in bindings for r in j['rollouts'] if r['status']=='available'}),
        boundary='Explicit callback links to immutable source revisions. Association is producer-reported; matching task names or nearby timestamps do not create a link.')


def comparison(store, raw):
    """Save the existing case-comparison product over a named trial contrast."""
    if not isinstance(raw,dict) or set(raw)-{'investigation_id','check_id','arm','selection','monitor_ids','parent_id'}:
        raise InputError('Unexpected trial comparison fields')
    if not isinstance(raw.get('investigation_id'),str) or len(raw['investigation_id'])>120:raise InputError('Choose a saved trial investigation')
    doc=failure_investigations.read(store,raw['investigation_id'])
    check=check_in(doc,raw.get('check_id'));trial=check['trial']
    arm=raw.get('arm')
    if arm not in [a['name'] for a in trial['arms'][1:]]:raise InputError('Choose a variant to compare with Reference')
    selection=raw.get('selection','paired')
    if not isinstance(selection,str) or selection not in {'paired','returned'}:raise InputError('Choose paired completed trials or all returned evidence')
    if raw.get('parent_id'):
        if not isinstance(raw['parent_id'],str) or len(raw['parent_id'])>120:raise InputError('Choose a saved trial comparison')
        prior=failure_investigations.read(store,raw['parent_id'])
        prior_scope=prior.get('snapshot',{}).get('trial_selection',{})
        if any(prior_scope.get(k)!=v for k,v in [('investigation_id',doc['id']),('check_id',check['id']),('arm',arm),('selection',selection)]):
            raise InputError('Choose an earlier comparison of this trial selection')
    evidence=check.get('trial_evidence')
    if not evidence:raise InputError('Refresh rollout evidence on the trial before comparing')
    measured=compare(check)
    by_job={r['job_id']:r for r in measured['rows']}
    by_arm={name:{j['seed']:j for j in evidence['jobs'] if j['arm']==name} for name in ('Reference',arm)}
    eligible=[]
    for seed in trial['seeds']:
        pair=[by_arm[name][seed] for name in ('Reference',arm)]
        if selection=='returned' or all(by_job[j['job_id']]['comparable'] and j['rollouts'] and
            all(r['status']=='available' and r['source']['state'] in {'complete','imported_snapshot'} for r in j['rollouts']) for j in pair):eligible.append(seed)
    cohorts={side:[by_arm[name][seed] for seed in eligible] for side,name in [('baseline','Reference'),('current',arm)]}
    linked={side:sorted({r['run_id'] for j in group for r in j['rollouts'] if r['status']=='available'}) for side,group in cohorts.items()}
    shared=sorted(set(linked['baseline']) & set(linked['current']))
    members={side:[rid for rid in ids if rid not in shared] for side,ids in linked.items()}
    if not eligible or not any(linked.values()):raise InputError('No returned rollouts match this selection. Import their traces, refresh rollout evidence, or inspect all returned evidence.')
    selected_ids=sorted(set(shared).union(*members.values()))
    if len(selected_ids)>case_studies.MAX_ROLLOUTS:raise InputError('Choose a smaller trial selection')
    pinned={r['run_id']:r for j in evidence['jobs'] for r in j['rollouts'] if r['status']=='available'}
    with store.read_snapshot() as saved:
        sources=_sources(saved,selected_ids)
        if any(rid not in sources or sources[rid]['source_hash']!=pinned[rid]['source']['source_hash'] for rid in selected_ids):
            raise InputError('A pinned rollout revision is unavailable')
        rows=[sources[rid] for rid in selected_ids]
        scope={side:dict(arm='Reference' if side=='baseline' else arm,trial_id=trial['id']) for side in members}
        snapshot=dict(captured_at=monitoring.now(),scope=scope,population=members,source_rows=rows,
            clock_boundary='Selection follows explicit trial jobs and immutable rollout identities; no temporal alignment is inferred.',
            case_evidence=case_comparisons.capture(saved,rows),behavior=case_behavior.capture(saved,rows,members,raw.get('monitor_ids')),
            trial_selection=dict(version='trial-case-selection/1',investigation_id=doc['id'],check_id=check['id'],arm=arm,selection=selection,
                trial_id=trial['id'],seeds=eligible,planned_seeds=trial['seeds'],shared_run_ids=shared,
                cohorts={side:deepcopy(group) for side,group in cohorts.items()},
                excluded_jobs=[deepcopy(j) for j in evidence['jobs'] if j['arm'] in ('Reference',arm) and j['seed'] not in eligible],
                boundary='Rollouts are selected by explicit trial receipts. Seed pairing defines the job selection, not one-to-one rollout or task matching. Saved behavior measures retain their own populations and coverage.'))
    snapshot['snapshot_id']='case-snapshot-'+digest(snapshot)
    controls=dict(investigation_id=doc['id'],check_id=check['id'],arm=arm,selection=selection,monitor_ids=snapshot['behavior']['monitor_ids'])
    value=dict(schema=case_studies.VERSION,title=(arm+' · returned behavior')[:120],hypothesis=check['hypothesis'],
        hypothesis_status='Researcher hypothesis; not a verified cause',scope=scope,snapshot=snapshot,controls=controls,inference_calls=0,
        limits=[snapshot['trial_selection']['boundary'],'Shared source revisions appear separately and are excluded from changes in behavior and recorded outcome.'])
    if raw.get('parent_id'):value['parent_id']=raw['parent_id']
    return failure_investigations.persist(store,value)
