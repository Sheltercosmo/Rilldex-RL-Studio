"""Descriptive episode profiles over immutable saved observations, without inference.

Profiles never pool different observers or task/configuration cohorts. Payload
changes remain payload changes; missing relationships never become negatives.
"""
from collections import Counter
from datetime import datetime, timezone
import json
from urllib.parse import urlencode

from .schema import InputError, digest, dumps

VERSION = 'strategy-profile/2'
FAMILIES = {
    'failure': {
        'label': 'Response after failure',
        'question': 'What changes when the agent tries the same work again?',
        'categories': {'changed': 'Changed dispatch', 'unchanged': 'Same dispatch', 'unknown': 'Dispatch comparison unresolved'},
        'primary': 'changed', 'primary_label': 'Changed dispatch among comparable retries',
        'limit': 'Dispatch differences do not establish a new approach. Completion is an operation outcome, not verified task recovery.',
    },
    'feedback': {
        'label': 'Feedback to action',
        'question': 'Does returned feedback receive an expressed assessment before the next action?',
        'categories': {'assessed': 'Assessed before acting', 'unassessed': 'No expressed assessment before acting', 'unknown': 'Window or assessment unresolved'},
        'primary': 'assessed', 'primary_label': 'Assessment among closed, decidable windows',
        'limit': 'An expressed assessment may be wrong. No assessment in the recorded window does not establish a lack of understanding.',
    },
}
COHORT_FIELDS = ('experiment', 'task_id', 'environment', 'environment_version',
                 'task_revision', 'split', 'model', 'policy_version', 'checkpoint',
                 'sampling', 'harness', 'harness_version', 'system_prompt_hash',
                 'tool_configuration', 'reward_definition', 'source_selection', 'training_step_basis')
MEASURES = {
    'failure': {
        'adjustment_completion': 'Operation completion after linked adjustment and retry',
        'dispatch_change': 'Changed dispatch among comparable retries',
    },
    'feedback': {'assessment': 'Assessment among closed, decidable windows'},
}


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS strategy_profile_observations(
        id TEXT PRIMARY KEY, input_id TEXT NOT NULL REFERENCES rollout_measurements(id),
        run_id TEXT NOT NULL REFERENCES runs(id), observer TEXT NOT NULL,
        version TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(input_id,version));
        CREATE INDEX IF NOT EXISTS strategy_profile_input ON strategy_profile_observations(input_id,version);
    ''')


def derive(record):
    families = {}
    retry = record.get('retry_observation')
    if retry:
        cases = []; seen = set()
        changes = {(e['failed_event_id'], e['retry_event_id']): e['changes']
                   for e in record.get('linked_adjustment_observation', {}).get('episodes', [])}
        for e in retry['episodes']:
            aid = e['failed_event_id']
            if aid in seen: raise InputError('Duplicate failed anchor in retry observation')
            seen.add(aid)
            change = e.get('payload_changed')
            category = 'changed' if change is True else 'unchanged' if change is False else 'unknown'
            adjustment = changes.get((aid, e['retry_event_id']), [])
            stages = [dict(label='Failed operation', ref=e.get('failed_unit_id'), event_id=aid)]
            if adjustment:
                declarations = list(dict.fromkeys(a['declaration_unit_id'] for a in adjustment))
                attempts = list(dict.fromkeys(a['execution_unit_id'] for a in adjustment))
                stages.append(dict(label='Stated adjustment' if len(declarations)==1 else str(len(declarations))+' adjustment contributions', refs=declarations))
                stages.append(dict(label='Adjustment attempted' if len(attempts)==1 else str(len(attempts))+' adjustment attempts', refs=attempts))
            stages.append(dict(label='Same-work retry', ref=e.get('retry_unit_id'), event_id=e['retry_event_id']))
            stages.append(dict(label=e['retry_outcome'].replace('_', ' ').capitalize(), ref=e.get('retry_unit_id')))
            cases.append({'anchor': aid, 'category': category, 'outcome': e['retry_outcome'], 'selected_retry': True,
                          'stages': stages, 'adjustments': adjustment, 'evidence_ids': e['evidence_ids'], 'adjustment_observed': bool(adjustment),
                          'reason': 'Dispatch payload comparison unavailable' if change is None else None})
        for aid in retry['failed_calls_without_selected_retry']:
            if aid in seen: raise InputError('Failed anchor counted with and without retry')
            seen.add(aid)
            cases.append({'anchor': aid, 'category': 'unknown', 'outcome': 'not_established', 'selected_retry': False,
                          'stages': [{'label': 'Failed operation', 'event_id': aid}, {'label': 'No selected retry link'}],
                          'evidence_ids': [aid], 'adjustment_observed': False,
                          'reason': 'A missing selected return does not establish stopping, switching or no retry'})
        families['failure'] = cases
    feedback = record.get('feedback_assessment')
    if feedback and feedback.get('schema') in {'feedback-assessment/2','feedback-assessment/3'}:
        cases = []; seen = set()
        for e in feedback['observations']:
            aid = e['action_event_id']
            if aid in seen: raise InputError('Duplicate feedback anchor')
            seen.add(aid)
            # The pattern concerns a next action, so even positive open windows
            # stay out of this denominator. Preserve the positive as evidence.
            closed = e['closed_window'] and e['complete_readable_evidence']
            category = ('assessed' if e['value'] == 1 else 'unassessed' if e['value'] == 0 else 'unknown') if closed else 'unknown'
            stages = [{'label': 'Returned feedback', 'event_id': e['response_event_ids'][0]}]
            if e.get('assessment_event_id'):
                stages.append({'label': 'Expressed assessment', 'event_id': e['assessment_event_id']})
            elif category == 'unassessed': stages.append({'label': 'No expressed assessment in closed window'})
            if e['closed_window']: stages.append({'label': 'Next action', 'event_id': e['boundary_event_id']})
            else: stages.append({'label': 'No closed next-action window'})
            cases.append({'anchor': aid, 'category': category, 'outcome': 'not_measured', 'stages': stages,
                          'evidence_ids': list(dict.fromkeys([aid, *e['response_event_ids'], *e['expression_event_ids'],
                                                            *([e['boundary_event_id']] if e['boundary_event_id'] else [])])),
                          'reason': e.get('reason') or (None if closed else 'Trace end or user intervention leaves this pattern open')})
        families['feedback'] = cases
    for family, cases in families.items():
        for e in cases: e['id'] = 'episode-' + digest({'input': digest(record), 'family': family, 'anchor': e['anchor']})
    return {'schema': VERSION, 'run_id': record['run_id'], 'observer': record['observer'],
            'observer_label': record.get('observer_label', record['observer']),
            'source_hash': record['source_hash'], 'graph_id': record.get('graph_id'), 'families': families}


def latest_inputs(c):
    from .rollout_metrics import VERSION as METRIC_VERSION
    return c.execute('''SELECT m.id,m.run_id,m.observer,m.document,m.created_at FROM rollout_measurements m
        WHERE m.observer!='source' AND json_extract(m.document,'$.schema')=?
        AND NOT EXISTS(SELECT 1 FROM rollout_measurements newer
            WHERE newer.run_id=m.run_id AND newer.observer=m.observer
            AND json_extract(newer.document,'$.schema')=?
            AND (newer.created_at>m.created_at OR (newer.created_at=m.created_at AND newer.id>m.id)))''',
        (METRIC_VERSION, METRIC_VERSION)).fetchall()


def sync(store):
    from .measurement_lineage import resolve
    current=resolve(store)['records']
    with store.connect() as c:
        rows = {r['id']:r for r in latest_inputs(c)}
        # A slower old worker may be the latest publication. Materialize the
        # matching observation too, without losing retained historical profiles.
        for r in current.values():
            if r['observer']!='source' and r['id'] not in rows:
                rows[r['id']]=c.execute('SELECT id,run_id,observer,document,created_at FROM rollout_measurements WHERE id=?',(r['id'],)).fetchone()
        known = {r[0] for r in c.execute('SELECT input_id FROM strategy_profile_observations WHERE version=?', (VERSION,))}
        pending = []
        for row in rows.values():
            if row['id'] in known: continue
            doc = derive(json.loads(row['document']))
            if not doc['families']: continue
            doc['input_id'] = row['id']; doc['id'] = 'profile-' + digest(doc)
            pending.append((doc['id'], row['id'], row['run_id'], row['observer'], VERSION, dumps(doc), datetime.now(timezone.utc).isoformat()))
        c.executemany('INSERT OR IGNORE INTO strategy_profile_observations VALUES (?,?,?,?,?,?,?)', pending)
    return len(pending)


def counts(cases, family, measure=None):
    categories = Counter(e['category'] for e in cases)
    known = sum(n for k, n in categories.items() if k != 'unknown')
    outcome_cases = [e for e in cases if e.get('selected_retry')] if family == 'failure' else [e for e in cases if e['category'] != 'unknown']
    outcomes = Counter(e['outcome'] for e in outcome_cases)
    terminal = sum(outcomes[k] for k in ('completed', 'failed', 'partial'))
    numerator, denominator = categories[FAMILIES[family]['primary']], known
    measure_unknown = categories['unknown']
    if measure == 'adjustment_completion':
        eligible = [e for e in outcome_cases if e.get('adjustment_observed') and e['outcome'] in ('completed', 'failed', 'partial')]
        numerator, denominator = sum(e['outcome']=='completed' for e in eligible), len(eligible)
        measure_unknown = sum(bool(e.get('adjustment_observed')) for e in outcome_cases)-denominator
    return {'categories': {k: categories[k] for k in FAMILIES[family]['categories']}, 'total': len(cases),
            'known': known, 'unknown': categories['unknown'], 'numerator': numerator,
            'denominator': denominator, 'value': numerator/denominator if denominator else None,
            'measure_unknown': measure_unknown,
            'outcomes': dict(outcomes), 'completed': outcomes['completed'], 'terminal': terminal,
            'outcome_unknown': len(outcome_cases)-terminal if family == 'failure' else known,
            'selected_retries': sum(e.get('selected_retry', False) for e in cases),
            'adjustment_observed': sum(e.get('adjustment_observed', False) for e in cases)}


def cohort(metadata, run_id):
    d = {k: metadata.get(k) for k in COHORT_FIELDS}
    # Unknown task identity cannot silently make unrelated tasks comparable.
    if not metadata.get('task_id'): d['unidentified_task_run'] = run_id
    return d


def profile_cohort(metadata,run_id,comparison):
    value=cohort(metadata,run_id)
    if metadata.get('training_clock') is not None:value['training_clock']=metadata['training_clock']
    if comparison=='training' and metadata.get('experiment') and type(metadata.get('training_step')) is int and metadata['training_step']>=0:
        value.pop('policy_version',None);value.pop('checkpoint',None)
        value['comparison_basis']='logged steps within one experiment'
    return value


def snapshot(store, **options):
    with store.read_snapshot() as saved:
        return _snapshot(saved,**options)


def _snapshot(store, *, family='failure', measure=None, observer=None, cohort_id=None, experiment=None, environment=None, comparison='fixed_policy'):
    if family not in FAMILIES: raise InputError('Unknown strategy family')
    if comparison not in {'fixed_policy','training'}:raise InputError('Choose training or fixed_policy comparison')
    measure = measure or ('dispatch_change' if family=='failure' else 'assessment')
    if measure not in MEASURES[family]: raise InputError('Unknown measure for strategy family')
    from .monitoring import population, scoped
    from .measurement_lineage import resolve
    runs = scoped(population(store), experiment, environment); run_by_id = {r['id']: r for r in runs}
    resolved=resolve(store,run_ids=run_by_id)
    latest={r['id']:r['created_at'] for r in resolved['records'].values()}
    with store.connect() as c:
        rows = c.execute('SELECT document FROM strategy_profile_observations WHERE version=?', (VERSION,)).fetchall()
        sources = {r['run_id']: r['source_hash'] for r in c.execute("SELECT run_id,source_hash FROM rollout_graphs WHERE observer='source'")}
    docs = [json.loads(r[0]) for r in rows]
    retained = [d for d in docs if d['run_id'] in run_by_id
                and d['source_hash']==sources.get(d['run_id']) and family in d['families']]
    docs = [d for d in retained if d['input_id'] in latest
            and run_by_id[d['run_id']]['state'] not in {'in_progress','failed'}]
    observers = {}
    for d in retained:
        observers.setdefault(d['observer'],{'id':d['observer'],'label':d['observer_label'],'rollouts':0,'episodes':0,'updated_at':''})
    for d in docs:
        entry = observers[d['observer']]
        entry['rollouts'] += 1; entry['episodes'] += len(d['families'][family])
        entry['updated_at'] = max(entry['updated_at'], latest[d['input_id']])
    choices = sorted(observers.values(), key=lambda x: (x['updated_at'], x['id']), reverse=True)
    selected = observer if observer is not None else choices[0]['id'] if choices else None
    docs = [d for d in docs if d['observer'] == selected]
    groups = {}
    by_run={d['run_id']:d for d in docs}
    if selected:
        for r in runs:
            scope=profile_cohort(r['metadata'],r['id'],comparison);cid='cohort-'+digest(scope)
            g=groups.setdefault(cid,{'id':cid,'metadata':scope,'documents':[],'runs':[],'episodes':0})
            g['runs'].append(r)
            if r['id'] in by_run:
                d=by_run[r['id']];g['documents'].append(d);g['episodes']+=len(d['families'][family])
    ordered = sorted(groups.values(), key=lambda g: (-g['episodes'], g['id']))
    chosen = cohort_id if cohort_id is not None else ordered[0]['id'] if ordered else None
    group = groups.get(chosen)
    included = group['documents'] if group else []
    scope_runs=group['runs'] if group else []
    points = []; cases = []; coverage=Counter()
    for r in scope_runs:
        d=by_run.get(r['id']);m=r['metadata'];es=d['families'][family] if d else []
        key=(r['id'],selected)
        status=('available' if d else 'incomplete' if r['state']=='in_progress' else
                'capture_failed' if r['state']=='failed' else 'stale_observation' if key in resolved['unavailable'] else
                'awaiting_observation' if key not in resolved['records'] else 'no_episode_observation')
        reasons={'incomplete':'Capture is still in progress.', 'capture_failed':'Capture did not complete.',
                 'stale_observation':'Saved episodes refer to an earlier semantic map.',
                 'awaiting_observation':'No matching observation is saved for this protocol.',
                 'no_episode_observation':'The current observation has no compatible saved episode profile.'}
        coverage[status]+=1
        step = m.get('training_step'); step = step if type(step) is int and step >= 0 and m.get('experiment') else None
        point = {'run_id':r['id'],'profile_id':d['id'] if d else None,'step':step,'status':status,
                 'reason':reasons.get(status),'policy_version':m.get('policy_version'),'checkpoint':m.get('checkpoint'),
                 **counts(es,family,measure)}
        points.append(point)
        for e in es:
            evidence_url = '/api/strategies/observations/' + d['id']
            cases.append({**e, 'run_id': r['id'], 'step': step, 'profile_id': d['id'], 'evidence_url': evidence_url,
                          'map_url': '/semantic-map?' + urlencode({'run': r['id'], 'observer': selected,
                                                                'profile': d['id'], 'episode': e['id'],
                                                                **({'graph':d['graph_id']} if d.get('graph_id') else {})})})
    points.sort(key=lambda p: (p['step'] is None, p['step'] or 0, p['run_id']))
    bins = []
    for step in sorted({p['step'] for p in points if p['step'] is not None}):
        ps = [p for p in points if p['step'] == step]; numerator = sum(p['numerator'] for p in ps); denominator = sum(p['denominator'] for p in ps)
        bins.append({'step': step, 'numerator': numerator, 'denominator': denominator,
                     'value': numerator/denominator if denominator else None,
                     'unknown': sum(p['measure_unknown'] for p in ps), 'rollouts': len(ps),
                     'measured_rollouts':sum(p['status']=='available' for p in ps),
                     'coverage':sum(p['status']=='available' for p in ps)/len(ps),
                     'policies':list({dumps({'policy_version':p['policy_version'],'checkpoint':p['checkpoint']}):
                                      {'policy_version':p['policy_version'],'checkpoint':p['checkpoint']} for p in ps
                                      if p['policy_version'] is not None or p['checkpoint'] is not None}.values()),
                     'policy_missing_rollouts':sum(p['policy_version'] is None and p['checkpoint'] is None for p in ps)})
    return {'schema': VERSION, 'family': family, 'measure': measure, 'measures': MEASURES[family],
            'definition': {**FAMILIES[family], 'primary_label': MEASURES[family][measure]}, 'families': FAMILIES,
            'observer': selected, 'observers': choices, 'cohort_id': chosen,'comparison':comparison,
            'cohorts': [{'id': g['id'], 'metadata': g['metadata'], 'rollouts': len(g['documents']), 'population':len(g['runs']), 'episodes': g['episodes']} for g in ordered],
            'metadata': group['metadata'] if group else None, 'population': len(scope_runs), 'measured_rollouts': len(included),
            'counts': counts(cases, family, measure), 'points': points, 'bins': bins, 'cases': cases,'coverage':dict(coverage),
            'missing_training_coordinates': sum(p['step'] is None and p['status']=='available' for p in points),
            'pending_dimensions': ['Approach switching and search breadth require reviewed approach identities.',
                                   'Verified task recovery requires goal-scoped acceptance evidence.'],
            'inference_calls': 0, 'accuracy': 'Experimental saved observations; independent semantic accuracy is not established.'}


def read(store, identifier):
    with store.connect() as c:
        row = c.execute('SELECT document FROM strategy_profile_observations WHERE id=?', (identifier,)).fetchone()
        if not row: raise KeyError(identifier)
        d = json.loads(row[0])
        source = c.execute('SELECT document FROM rollout_measurements WHERE id=?', (d['input_id'],)).fetchone()
        raw = c.execute('SELECT document FROM runs WHERE id=?', (d['run_id'],)).fetchone()
    record = json.loads(source[0]); run = json.loads(raw[0])
    if digest(record) != d['input_id'] or digest(run) != d['source_hash']:
        raise InputError('Strategy source or observation identity mismatch')
    expected = derive(record); expected['input_id'] = d['input_id']; expected['id'] = 'profile-' + digest(expected)
    if expected != d: raise InputError('Strategy observation differs from its saved input')
    from .graph_store import read as read_graph
    graph = read_graph(store, d['graph_id']) if d.get('graph_id') else None
    if graph and (graph['source_hash'] != d['source_hash'] or graph['observer'] != d['observer'] or graph['run_id'] != d['run_id']):
        raise InputError('Strategy graph identity mismatch')
    return {**d, 'input_observation': record, 'run': run, 'graph': graph}
