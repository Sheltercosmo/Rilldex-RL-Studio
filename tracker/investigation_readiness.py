"""Question-specific evidence checks over one read-only database snapshot.

No parsing, observation, materialization or accuracy certification. All counts
retain their grain; training samples never stand in for independent rollouts.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import json
from urllib.parse import urlencode

from . import analysis_contracts, monitoring, training_lineage, training_selection
from .schema import InputError, digest

VERSION = 'investigation-readiness/1'
RECIPES = {
    'selection': {'label': 'Selection comparison',
        'description': 'Compare a saved measure across one named admission rule, keeping missing sources and decisions visible.',
        'grain': 'declared sample', 'operation': None},
    'recovery': {'label': 'Recovery after a recorded change',
        'description': 'Inspect comparable failed-check opportunities and their recorded follow-up. This is local criterion recovery, not task success.',
        'grain': 'latest source rollout', 'operation': 'recovery_windows',
        'opportunity_label': 'recorded failed-check opportunities'},
    'next_check': {'label': 'First-retry outcomes',
        'description': 'Compare first-recheck outcomes independently of captured input changes. Unknown retries and input membership remain visible; this is not causal revision benefit.',
        'grain': 'latest source rollout', 'operation': 'retry_outcomes',
        'opportunity_label': 'recorded failed-check opportunities'},
}


class _ReadSnapshot:
    def __init__(self, connection): self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


def _accepts(recipe, monitor):
    op = RECIPES[recipe]['operation']
    return op is None or monitor.get('analysis_definition', {}).get('operation') == op


def options(store):
    with store.connect() as c:
        c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
        view = _ReadSnapshot(c)
        experiments = {r[0] for r in c.execute("SELECT DISTINCT json_extract(document,'$.metadata.experiment') FROM runs") if r[0]}
        for table in ('training_records', 'training_sample_records'):
            if c.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                experiments.update(r[0] for r in c.execute('SELECT DISTINCT experiment FROM ' + table))
        monitors = monitoring.definitions(view)
        return {'schema': VERSION, 'experiments': sorted(experiments),
            'recipes': [{'id': k, **v} for k, v in RECIPES.items()],
            'monitors': [{k: m[k] for k in ('id', 'name', 'observer', 'enabled')} |
                         {'recipes': [r for r in RECIPES if _accepts(r, m)]} for m in monitors]}


def _validate(raw):
    if not isinstance(raw, dict) or set(raw) - {'recipe', 'experiment', 'monitor', 'selection', 'offset', 'limit', 'expected_revision'}:
        raise InputError('Provide an analysis, experiment and optional monitor, named filter and page')
    if not isinstance(raw.get('recipe'), str) or raw['recipe'] not in RECIPES:
        raise InputError('Choose a supported analysis')
    if not isinstance(raw.get('experiment'), str) or not raw['experiment'].strip() or len(raw['experiment']) > 240:
        raise InputError('Choose an explicit experiment')
    for key in ('monitor', 'selection', 'expected_revision'):
        if key in raw and (not isinstance(raw[key], str) or not raw[key] or len(raw[key]) > 240):
            raise InputError('Invalid ' + key)
    if raw['recipe'] != 'selection' and 'selection' in raw:
        raise InputError('A named admission filter requires Selection comparison')
    offset, limit = raw.get('offset', 0), raw.get('limit', 20)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise InputError('Offset must be nonnegative and page size must be 1–100')
    return offset, limit


def _measurement(run, monitor, value, inputs):
    if not run: return {'status': 'source_missing'}
    if not monitor: return {'status': 'choose_measure'}
    if not monitoring.in_population(monitor, run): return {'status': 'outside_measure_population'}
    binding = monitoring.observation_binding(monitor, run, inputs)
    base = {'source_hash': (binding['source'] or {}).get('source_hash'), 'input_id': binding['input_id']}
    if run['state'] in {'in_progress', 'failed'}: return {**base, 'status': 'incomplete_source'}
    if not binding['source']: return {**base, 'status': 'source_graph_missing'}
    if not binding['input_id']: return {**base, 'status': 'observation_missing'}
    if not value: return {**base, 'status': 'not_materialized'}
    if value.get('input_hash') != binding['input_hash']: return {**base, 'status': 'stale_measurement', 'previous_value_id': value['id']}
    summary = {k: value.get(k) for k in ('id', 'value', 'numerator', 'denominator', 'opportunities', 'unknown', 'reason')}
    state = value['status']
    if state == 'unavailable' and value.get('unknown', 0): state = 'unresolved_followup'
    elif state == 'unavailable' and value.get('opportunities') == 0: state = 'no_recorded_opportunities'
    return {**base, **summary, 'status': state}


def _validation(monitor):
    if monitor is None: return {'status': 'not_assessed', 'detail': 'Choose a measure to see its definition and validation boundary.'}
    op = monitor.get('analysis_definition', {}).get('operation')
    contract = analysis_contracts.registered().get(op, {})
    return {'status': 'not_certified', 'detail': contract.get('validation') or
        ('Source measurements describe recorded fields; capture fidelity and interpretation need validation for this producer.'
         if monitor['observer'] == 'source' else 'Saved observations do not establish independent semantic accuracy for this population.'),
        'boundary': contract.get('boundary') or monitoring.description(monitor)}


def check(store, raw):
    offset, limit = _validate(raw)
    with store.connect() as c:
        # Nested readers share this transaction; live ingestion cannot change
        # populations halfway through the check. query_only forbids hidden writes.
        c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
        result = _check(_ReadSnapshot(c), raw)
    revision = digest(result)
    if raw.get('expected_revision') is not None and raw['expected_revision'] != revision:
        raise InputError('Question evidence changed. Refresh the check from the first page.')
    rows = result.pop('rows')
    return {**result, 'revision': revision, 'rows': rows[offset:offset+limit],
        'total_rows': len(rows), 'offset': offset, 'limit': limit,
        'next_offset': offset+limit if offset+limit < len(rows) else None,
        'persisted': False, 'new_model_calls': 0}


def _check(store, raw):
    recipe = raw['recipe']; experiment = raw['experiment']
    monitors = monitoring.definitions(store)
    monitor = next((m for m in monitors if m['id'] == raw.get('monitor')), None)
    if raw.get('monitor') and (monitor is None or not _accepts(recipe, monitor)):
        raise InputError('Selected measure does not implement this question')
    with store.connect() as c:
        # Include pinned historical revisions for independent training mappings.
        all_runs = {r['id']: {'id': r['id'], 'metadata': json.loads(r['metadata']), 'state': r['state']} for r in c.execute('''
            SELECT id,json_extract(document,'$.metadata') metadata,
            coalesce((SELECT state FROM rollout_revisions WHERE run_id=r.id ORDER BY revision DESC LIMIT 1),'imported_snapshot') state
            FROM runs r''')}
        latest_graphs = {}
        for g in c.execute('SELECT id,run_id,observer,source_hash FROM rollout_graphs ORDER BY rowid'):
            latest_graphs[(g['run_id'], g['observer'])] = dict(g)
        ledger_available = bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='training_records'").fetchone())
    latest = [r for r in monitoring.population(store) if r['metadata'].get('experiment') == experiment]
    inputs = monitoring.observation_inputs(store, monitor, {'graphs': list(latest_graphs.values())}) if monitor else None
    values = monitoring.values(store, monitor['id'], set(all_runs)) if monitor else {}
    if not ledger_available and raw.get('selection'):
        raise InputError('Training records are unavailable in this collector schema; no named filter can be selected')
    training = (training_lineage.snapshot(store, experiment=experiment, selection=raw.get('selection')) if ledger_available else
                {'samples':[], 'cohorts':[], 'selection':None, 'selection_options':[], 'orphan_samples':0, 'conflicting_samples':0})
    if not latest and not training['samples'] and not training['orphan_samples'] and not training['conflicting_samples']:
        raise InputError('No recorded sources or training facts for this experiment')
    selected_filter = training['selection']
    rows = []
    source_measurements = {}
    subjects = training['samples'] if recipe == 'selection' else latest
    for subject in subjects:
        rid = subject['run_id'] if recipe == 'selection' else subject['id']
        run = all_runs.get(rid)
        measurement = _measurement(run, monitor, values.get(rid), inputs)
        if rid: source_measurements[rid] = measurement
        row = {'run_id': rid, 'task_id': (run or {}).get('metadata', {}).get('task_id'), 'measurement': measurement}
        if recipe == 'selection':
            row.update(sample_id=subject.get('sample_id', subject['rollout_id']), producer=subject['producer'],
                       identity_schema=subject.get('sample_identity_schema', training_lineage.VERSION),
                       join_status=subject['join_status'], sample_source=subject.get('source'),
                       decision=training_selection.decision(subject, selected_filter)['state'] if selected_filter else 'choose_filter',
                       populations=subject['populations'])
        if rid:
            q = {'run': rid, 'observer': monitor['observer'] if monitor and measurement.get('id') else 'source'}
            if measurement.get('id'): q['value'] = measurement['id']
            source_graph = latest_graphs.get((rid, 'source'))
            if 'value' not in q and source_graph: q['graph'] = source_graph['id']
            q['return_to'] = '/connections?' + urlencode({k: raw[k] for k in ('recipe','experiment','monitor','selection') if k in raw}) + '#question-section'
            row['evidence_url'] = '/semantic-map?' + urlencode(q)
        rows.append(row)
    scope = {k: raw[k] for k in ('recipe', 'experiment', 'monitor', 'selection') if k in raw}
    status_counts = dict(Counter(r['measurement']['status'] for r in rows))
    distinct_counts = dict(Counter(m['status'] for m in source_measurements.values()))
    samples = training['samples']
    scorer_counts = Counter(r['data']['status'] for s in samples for r in s['records'] if r['kind'] == 'score')
    requirements = [
        {'id': 'capture', 'label': 'Captured population', 'state': 'recorded' if subjects else 'missing',
         'detail': f'{len(subjects)} {RECIPES[recipe]["grain"]} records; {len(source_measurements)} distinct joined source rollouts. Expected producer totals are not established.'},
        {'id': 'measure', 'label': 'Measurement definition', 'state': 'selected' if monitor else 'choose',
         'detail': monitoring.description(monitor) if monitor else 'Choose a saved measure. Checking evidence will not create or run an observer.'},
        {'id': 'observations', 'label': 'Saved calculation coverage', 'state': 'partial' if distinct_counts.get('available') else 'missing',
         'detail': f'{distinct_counts.get("available",0)} distinct source rollouts have a current numeric measurement. Missing and unresolved cases remain separate.'},
        {'id': 'validation', 'label': 'Validity of the measure', 'state': 'not_certified', 'detail': _validation(monitor)['detail']},
    ]
    if source_measurements and distinct_counts.get('available') == len(source_measurements): requirements[2]['state'] = 'recorded'
    selection_info = None
    if recipe == 'selection':
        decisions = dict(Counter(r['decision'] for r in rows))
        matched_sides = 0; cohorts = []
        for cohort in training['cohorts']:
            pairs = [(s, r) for s, r in zip(samples, rows) if all(s.get(k) == v for k, v in cohort['cohort'].items())]
            sides = {r['decision'] for _, r in pairs if r['measurement']['status'] == 'available'}
            matched_sides += {'admitted', 'rejected'} <= sides
            a = {r['run_id'] for _, r in pairs if r['decision']=='admitted' and r['run_id']}
            b = {r['run_id'] for _, r in pairs if r['decision']=='rejected' and r['run_id']}
            cohorts.append({'cohort':cohort['cohort'], 'samples':len(pairs),
                'decisions':dict(Counter(r['decision'] for _, r in pairs)),
                'measurement_statuses':dict(Counter(r['measurement']['status'] for _, r in pairs)),
                'both_sides_measured':{'admitted','rejected'} <= sides, 'shared_source_rollouts':len(a & b)})
        selection_info = {'filter': selected_filter, 'decisions': decisions, 'cohorts_with_measured_sides': matched_sides,
            'cohorts':cohorts, 'orphans': training['orphan_samples'], 'conflicting_declarations': training['conflicting_samples']}
        requirements.insert(1, {'id': 'selection', 'label': 'Named selection rule', 'state': 'selected' if selected_filter else 'choose',
            'detail': f'{matched_sides} recorded cohorts have current measurements on both admitted and rejected samples. This does not establish task matching or causal effects.' if selected_filter else 'Choose one producer, filter and definition. Missing decisions are not rejections.'})
    current = [m for m in source_measurements.values() if m.get('id')]
    opportunities = {k: (sum(m[k] for m in current if type(m.get(k)) is int)
                         if any(type(m.get(k)) is int for m in current) else None)
                     for k in ('opportunities', 'denominator', 'unknown')}
    base_link = {'experiment': experiment}
    if monitor: base_link['monitor'] = monitor['id']
    if selected_filter: base_link['selection'] = selected_filter['id']
    return {'schema': VERSION, 'scope': scope, 'recipe': deepcopy(RECIPES[recipe]), 'monitor': monitor,
        'selection_options': training['selection_options'] if recipe == 'selection' else [],
        'requirements': requirements, 'validation': _validation(monitor), 'selection': selection_info,
        'summary': {'row_statuses': status_counts, 'source_statuses': distinct_counts, 'distinct_sources': len(source_measurements),
                    'latest_experiment_sources': len(latest), 'opportunity_totals': opportunities},
        'training_health': {'capture_status':'recorded_schema' if ledger_available else 'schema_unavailable',
            'declared_samples': len(samples) if ledger_available else None, 'score_record_statuses': dict(scorer_counts),
            'samples_without_score_records': sum(s['score_state'] == 'unknown' for s in samples) if ledger_available else None,
            'samples_with_optimizer_membership': sum(s['populations']['optimizer'] for s in samples) if ledger_available else None,
            'detail': ('Score statuses count component records, not samples. A scored record does not prove a healthy verifier. Missing use records do not prove exclusion.' if ledger_available else
                       'This collector database has no training ledger. Sample, score and use counts are unavailable; source investigations remain possible. No schema migration ran.')},
        'continue_url': '/?' + urlencode({'view':'training', **base_link}) if recipe == 'selection' else '/?' + urlencode(base_link),
        'configure_url': '/monitors?' + urlencode({'experiment':experiment}), 'rows': rows,
        'notice': 'A read-only evidence check, not a readiness or accuracy certificate. Counts cover recorded identities, not expected total generation. No observer or monitor jobs ran. Current means the input identity matches the retained calculation; it does not establish correct interpretation.'}
