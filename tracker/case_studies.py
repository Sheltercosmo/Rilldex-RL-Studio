"""Freeze task-matched rollout evidence from two independently selected runs."""
from collections import defaultdict
from copy import deepcopy
import json

from . import case_behavior, case_comparisons, case_outcomes, failure_investigations, monitoring
from .monitor_comparisons import window
from .schema import InputError, digest

VERSION = 'case-investigation/1'
MAX_ROLLOUTS = 20000


def selection(raw):
    if not isinstance(raw, dict) or set(raw) - {'experiment', 'environment', 'checkpoint', 'steps', 'clock', 'basis', 'evaluation'}:
        raise InputError('Choose a run, optional checkpoint or recorded rollout step range')
    result = {}
    for key in ('experiment', 'environment', 'checkpoint', 'clock', 'basis'):
        value = raw.get(key)
        if value is None: continue
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise InputError('Invalid comparison ' + key)
        result[key] = value
    if 'experiment' not in result: raise InputError('Select a run on both sides')
    if raw.get('steps') is not None:
        result['steps'] = window(raw['steps'], 'rollout')
        if not result.get('clock') or not result.get('basis'):
            raise InputError('A step range needs its recorded rollout clock and basis')
    elif result.get('clock') or result.get('basis'):
        raise InputError('Use clock and basis with a rollout step range')
    if raw.get('evaluation') is not None: result['evaluation'] = case_outcomes.selection(raw['evaluation'])
    return result


def matches(row, scope):
    meta = row['metadata']
    if any(meta.get(k) != v for k, v in scope.items() if k in {'experiment', 'environment', 'checkpoint'}):
        return False
    if 'steps' not in scope: return True
    step = meta.get('training_step')
    return (type(step) is int and scope['steps'][0] <= step <= scope['steps'][1]
        and meta.get('training_clock') == scope['clock'] and meta.get('training_step_basis') == scope['basis'])


def catalog(store):
    with store.read_snapshot() as saved:
        return _catalog(saved)


def _catalog(store):
    experiments = defaultdict(lambda: dict(rollouts=0, checkpoints=set(), coordinates={}, evaluations={}))
    population = monitoring.population(store)
    reports = case_outcomes.records(store, (r['id'] for r in population), summaries=True)
    for row in population:
        meta = row['metadata']; name = meta.get('experiment')
        if not isinstance(name, str) or not name.strip(): continue
        group = experiments[name]; group['rollouts'] += 1
        for key in {(r['producer'], r['label'], r['purpose']) for r in reports[row['id']]}:
            group['evaluations'][key] = group['evaluations'].get(key, 0) + 1
        checkpoint = meta.get('checkpoint')
        if isinstance(checkpoint, str) and checkpoint.strip(): group['checkpoints'].add(checkpoint)
        clock, basis, step = (meta.get(k) for k in ('training_clock', 'training_step_basis', 'training_step'))
        if not all(isinstance(v, str) and v for v in (clock, basis)) or type(step) is not int or step < 0: continue
        coordinate = group['coordinates'].setdefault((clock, basis), dict(clock=clock, basis=basis, first=step, last=step, rollouts=0))
        coordinate['first'] = min(coordinate['first'], step); coordinate['last'] = max(coordinate['last'], step)
        coordinate['rollouts'] += 1
    return dict(experiments=[dict(name=name, rollouts=g['rollouts'], checkpoints=sorted(g['checkpoints']),
        evaluations=[dict(producer=k[0], label=k[1], purpose=k[2], rollouts=n) for k,n in sorted(g['evaluations'].items())],
        coordinates=sorted(g['coordinates'].values(), key=lambda c: (c['clock'], c['basis']))) for name, g in sorted(experiments.items())])


def capture(store, raw):
    if not isinstance(raw, dict) or set(raw) - {'reference', 'selected', 'title', 'hypothesis', 'parent_id', 'monitor_ids'}:
        raise InputError('Unexpected case comparison fields')
    scopes = {side: selection(raw.get(key)) for side, key in (('baseline', 'reference'), ('current', 'selected'))}
    title = raw.get('title') or 'Rollout case comparison'
    hypothesis = raw.get('hypothesis', '')
    if not isinstance(title, str) or not title.strip() or len(title) > 120 or not isinstance(hypothesis, str) or len(hypothesis) > 6000:
        raise InputError('Use a title up to 120 characters and notes up to 6,000 characters')
    if raw.get('parent_id'):
        parent = failure_investigations.read(store, raw['parent_id'])
        if parent['schema'] != VERSION: raise InputError('Choose a saved rollout case comparison')
    with store.read_snapshot() as saved:
        population = monitoring.population(saved)
        sides = {side: [r for r in population if matches(r, scope)] for side, scope in scopes.items()}
        if not all(sides.values()): raise InputError('No captured rollouts match one selection. Check the run, checkpoint and rollout coordinates.')
        members = {side: [r['id'] for r in rows] for side, rows in sides.items()}
        if set(members['baseline']) & set(members['current']):
            raise InputError('The selections overlap. Choose different runs, checkpoints or rollout ranges.')
        sources = sides['baseline'] + sides['current']
        if len(sources) > MAX_ROLLOUTS: raise InputError('Choose checkpoints or step ranges covering at most 20,000 rollouts')
        with saved.connect() as c:
            sources = [dict(r, outcome=json.loads(c.execute('SELECT document FROM runs WHERE id=?', (r['id'],)).fetchone()[0]).get('outcome', {})) for r in sources]
        if any(s.get('evaluation') for s in scopes.values()):
            reports = case_outcomes.records(saved, (r['id'] for r in sources))
            selections = {rid: scopes[side].get('evaluation') for side, ids in members.items() for rid in ids}
            sources = [case_outcomes.freeze(r, selections[r['id']], reports[r['id']]) if selections[r['id']] else r for r in sources]
        snapshot = dict(captured_at=monitoring.now(), scope=scopes, population=members, source_rows=sources,
            case_evidence=case_comparisons.capture(saved, sources),
            behavior=case_behavior.capture(saved,sources,members,raw.get('monitor_ids')),
            clock_boundary="Each side uses its own recorded rollout selection. Equal step numbers do not establish aligned learner updates or elapsed time.")
    snapshot['snapshot_id'] = 'case-snapshot-' + digest(snapshot)
    value = dict(schema=VERSION, title=title, hypothesis=hypothesis,
        hypothesis_status='Researcher hypothesis; not a verified cause', scope=scopes, snapshot=snapshot,
        controls=dict(reference=deepcopy(scopes['baseline']), selected=deepcopy(scopes['current']),monitor_ids=snapshot['behavior']['monitor_ids']), inference_calls=0,
        limits=['Frozen source revisions and graph versions; late arrivals require a new comparison.',
                'Matches use recorded task and evaluation context. Missing context, repeated trials and unmatched tasks remain visible.',
                'Reported outcomes and rewards are distinct. A paired outcome change does not establish a causal effect or statistical significance.'])
    if raw.get('parent_id'): value['parent_id'] = raw['parent_id']
    return value


def save(store, raw):
    return failure_investigations.persist(store, capture(store, raw))
