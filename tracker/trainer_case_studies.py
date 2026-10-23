"""Frozen rollout comparisons selected through exact native trainer references."""
from collections import Counter
from copy import deepcopy
import json

from . import case_behavior, case_comparisons, case_studies, failure_investigations, monitoring
from . import telemetry_evidence, telemetry_queries, training_lineage
from .schema import InputError, digest

BOUNDARY = ('Rollouts are linked through producer-declared training-use records and exact source revisions. '
            'Each rollout counts once per selection, regardless of reuse or token count. '
            'Rollouts linked on both sides are shown separately, not treated as new trials. '
            'These links provide log context, not attribution of an aggregate metric to a rollout.')


def selection(raw):
    if not isinstance(raw, dict) or set(raw)-{'series_id','as_of','start','end'} or not {'series_id','as_of'}<=set(raw):
        raise InputError('Select a metric series, capture cutoff and optional start/end steps')
    if not isinstance(raw['series_id'], str) or not 1<=len(raw['series_id'])<=100:
        raise InputError('Select a recorded metric series')
    telemetry_queries._range(raw.get('start'), raw.get('end'))
    return deepcopy(raw)


def _cohort(store, selected, indices):
    data = telemetry_queries.selected_records(store, **selected)
    experiment = data['series']['context']['experiment']
    references = sum(len(json.loads(r['document']).get('training_uses',{}).get('records',[])) for r in data['rows'])
    if references>50000:
        raise InputError('Narrow each interval to at most 50,000 declared training-use references')
    if references and experiment not in indices:
        indices[experiment] = telemetry_evidence._index({'recorded': training_lineage.snapshot(store, experiment=experiment)['samples']})
    logs = [telemetry_evidence._project(r, indices.get(experiment,{})) for r in data['rows']]
    coverage = Counter(r['declared_coverage'] for r in logs)
    states = Counter(ref['status'] for r in logs for ref in r['references'])
    return dict(selection=selected, series=data['series'], coordinates=data['coordinates'],
        records=len(logs), reference_inventory=dict(coverage), references=dict(states),
        run_ids=sorted({rid for r in logs for rid in r['run_ids']}),
        # Retain exact provenance without duplicating all native metric payloads.
        logs=[dict(producer=r['producer'], record_id=r['record']['id'], step=r['record']['step'],
                   declared_coverage=r['declared_coverage'], references=r['references']) for r in logs])


def capture(store, raw):
    if not isinstance(raw, dict) or set(raw)-{'reference','selected','title','hypothesis','parent_id','return_to','monitor_ids'}:
        raise InputError('Unexpected trainer comparison fields')
    selections = {side:selection(raw.get(key)) for side,key in (('baseline','reference'),('current','selected'))}
    title = raw.get('title') or 'Linked rollout comparison'
    hypothesis = raw.get('hypothesis', '')
    if not isinstance(title,str) or not title.strip() or len(title)>120 or not isinstance(hypothesis,str) or len(hypothesis)>6000:
        raise InputError('Use a title up to 120 characters and notes up to 6,000 characters')
    return_to = raw.get('return_to')
    if return_to is not None and (not isinstance(return_to,str) or not return_to.startswith('/?') or len(return_to)>16000):
        raise InputError('Return to a local training chart')
    if raw.get('parent_id'):
        parent = failure_investigations.read(store,raw['parent_id'])
        if not parent.get('snapshot',{}).get('trainer_selection'):
            raise InputError('Choose a saved trainer-linked comparison')
    for selected in selections.values(): telemetry_queries.ensure_index(store,selected['as_of'])
    with store.read_snapshot() as saved:
        indices = {}
        cohorts = {side:_cohort(saved,selected,indices) for side,selected in selections.items()}
        common = sorted(set(cohorts['baseline']['run_ids']) & set(cohorts['current']['run_ids']))
        members = {side:sorted(set(c['run_ids'])-set(common)) for side,c in cohorts.items()}
        ids = sorted(set(common).union(*members.values()))
        if len(ids)>case_studies.MAX_ROLLOUTS: raise InputError('Choose intervals covering at most 20,000 rollouts')
        # monitoring.population contains only latest sources. The learner may
        # have consumed an older revision, so read its exact immutable run ID.
        with saved.connect() as c:
            rows = c.execute('''SELECT r.*,
                coalesce((SELECT state FROM rollout_revisions WHERE run_id=r.id ORDER BY revision DESC LIMIT 1),'imported_snapshot') state
                FROM runs r JOIN json_each(?) j ON r.id=j.value ORDER BY r.id''',(json.dumps(ids),)).fetchall()
        sources = []
        for row in rows:
            run = json.loads(row['document'])
            sources.append(dict(id=row['id'],imported_at=row['imported_at'],state=row['state'],
                metadata=run['metadata'],adapter=run['adapter'],outcome=run.get('outcome',{})))
        scopes = {side:dict(experiment=c['series']['context']['experiment'],native=selections[side],
            clock=c['series']['context']['clock']) for side,c in cohorts.items()}
        snapshot = dict(captured_at=monitoring.now(),scope=scopes,population=members,source_rows=sources,
            case_evidence=case_comparisons.capture(saved,sources),clock_boundary=BOUNDARY,
            behavior=case_behavior.capture(saved,sources,members,raw.get('monitor_ids')),
            trainer_selection=dict(version='trainer-linked-cases/1',cohorts=cohorts,shared_run_ids=common,
                boundary=BOUNDARY,return_to=return_to))
    snapshot['snapshot_id'] = 'case-snapshot-'+digest(snapshot)
    value = dict(schema=case_studies.VERSION,title=title,hypothesis=hypothesis,
        hypothesis_status='Researcher hypothesis; not a verified cause',scope=scopes,snapshot=snapshot,
        controls=dict(reference=selections['baseline'],selected=selections['current'],monitor_ids=snapshot['behavior']['monitor_ids'],**({'return_to':return_to} if return_to else {})),
        inference_calls=0,limits=[BOUNDARY,
            'Metric definitions, worker sessions, log cutoffs, source revisions and saved graph versions are pinned.',
            'Missing, conflicting or partial links remain visible. Unlinked logs do not imply unused or unsuccessful rollouts.',
            'Only logs containing the selected metric definition enter each cohort; missing-definition coordinates are counted separately.',
            'This is an observed rollout comparison, not a causal or statistical estimate of policy improvement.'])
    if raw.get('parent_id'): value['parent_id']=raw['parent_id']
    return value


def save(store, raw):
    return failure_investigations.persist(store,capture(store,raw))
