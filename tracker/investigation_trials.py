"""Pinned trial designs and producer-reported results for investigation checks.

The callback runs in the researcher's process. This module never launches a
trainer, restores an environment, or treats requested settings as applied ones.
"""
from copy import deepcopy
import json
import math
from statistics import mean

from . import configuration_comparison, failure_investigations
from .investigation_cases import population
from .schema import InputError, digest, dumps

VERSION = 'investigation-trial/1'
STATES = {'model', 'optimizer', 'scheduler', 'rng', 'data', 'environment', 'agent'}
MODES = {'replay', 'evaluate', 'train'}


def _text(value, label, maximum=6000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or not empty and not value.strip():
        raise InputError('Invalid ' + label)
    return value.strip()


def _object(value, label):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value): raise InputError(label + ' must be a JSON object with text keys')
    try:
        if len(dumps(value)) > 64000: raise ValueError()
    except (ValueError, TypeError, RecursionError) as error:
        raise InputError(label + ' must be finite JSON up to 64 KB') from error
    return deepcopy(value)


def _source(store, run_id):
    with store.connect() as c:
        row = c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row: raise InputError('Rollout source is unavailable')
    return json.loads(row[0])


def options(store, investigation_id, run_id=None):
    doc = failure_investigations.read(store, investigation_id)
    members = population(doc)
    # Searchable native select with bounded labels; source text is fetched only
    # for the chosen rollout, rather than copying all traces into the form.
    rows = []
    with store.connect() as c:
        for rid, cohort in members.items():
            row = c.execute("SELECT json_extract(document,'$.metadata') FROM runs WHERE id=?", (rid,)).fetchone()
            if row:
                meta = json.loads(row[0] or '{}')
                rows.append(dict(run_id=rid, cohort=cohort, metadata=meta))
    selected = run_id or next((r['run_id'] for r in rows if r['cohort'] == 'focus'), rows[0]['run_id'] if rows else None)
    if selected is None: return dict(rollouts=rows, selected=None, events=[], configurations=[])
    if selected not in members: raise InputError('Choose a rollout in this saved comparison')
    source = _source(store, selected)
    experiment = source.get('metadata', {}).get('experiment')
    with store.connect() as c:
        configurations, total = configuration_comparison._inventory(c, experiment, None) if experiment else ([], 0)
    return dict(rollouts=rows, selected=selected, source_hash=digest(source),
        events=[dict(id=e['id'], label=(e.get('actor', '') + ' · ' + e.get('text', '')[:100])) for e in source['events']],
        configurations=configurations, configuration_count=total)


def prepare(store, parent, raw):
    if not isinstance(raw, dict) or set(raw) - {'mode', 'run_id', 'through_event_id', 'configuration', 'checkpoint', 'variants', 'seeds', 'budget', 'measure'}:
        raise InputError('Unexpected trial design fields')
    mode = raw.get('mode')
    if not isinstance(mode, str) or mode not in MODES: raise InputError('Choose replay, evaluate or train')
    run_id = raw.get('run_id')
    if not isinstance(run_id, str) or run_id not in population(parent): raise InputError('Choose a rollout in this saved comparison')
    source = _source(store, run_id)
    events = source['events']
    through = raw.get('through_event_id')
    if not events or not isinstance(through, str) or through not in {e['id'] for e in events}: raise InputError('Choose the last included source event')
    index = next(i for i, e in enumerate(events) if e['id'] == through)
    if mode == 'evaluate' and index != len(events) - 1: raise InputError('Rescoring uses the complete captured rollout')
    config = raw.get('configuration')
    if not isinstance(config, dict): raise InputError('Choose recorded configuration or provide base settings')
    if set(config) == {'source_id'}:
        experiment = source.get('metadata', {}).get('experiment')
        with store.connect() as c:
            resolved = configuration_comparison._resolve(c, experiment, config['source_id'], None)
        config = dict(origin='recorded', reference=resolved, values=resolved['config'])
    elif set(config) == {'values'}:
        config = dict(origin='provided', values=_object(config['values'], 'Base settings'))
    else: raise InputError('Use source_id or values for the base configuration')
    checkpoint = raw.get('checkpoint') or {}
    if not isinstance(checkpoint, dict) or set(checkpoint) - {'reference', 'available_state', 'reset_state'}: raise InputError('Invalid restore point')
    reference = _text(checkpoint.get('reference', ''), 'checkpoint reference', 2000, empty=True)
    state = checkpoint.get('available_state', [])
    if not isinstance(state, list) or any(not isinstance(s, str) or s not in STATES for s in state) or len(set(state)) != len(state):
        raise InputError('Choose known checkpoint state components')
    resets = checkpoint.get('reset_state', [])
    if not isinstance(resets, list) or any(not isinstance(s, str) or s not in STATES for s in resets) or len(set(resets)) != len(resets):
        raise InputError('Choose known state components to restart')
    if set(resets) & set(state): raise InputError('A state component cannot be restored and restarted')
    if mode == 'train' and 'model' in resets: raise InputError('Training from a checkpoint must restore the model')
    if mode == 'train' and not reference: raise InputError('Resumed training needs a checkpoint reference')
    if (state or resets) and not reference: raise InputError('State components need a checkpoint reference')
    variants = raw.get('variants')
    if not isinstance(variants, list) or not 1 <= len(variants) <= 8: raise InputError('Add 1–8 variants; the unchanged reference is included automatically')
    arms = [dict(name='Reference', parameters={}, context_append='')]
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) - {'name', 'parameters', 'context_append'}: raise InputError('Invalid variant')
        arm = dict(name=_text(variant.get('name'), 'variant name', 80),
                   parameters=_object(variant.get('parameters', {}), 'Parameter overrides'),
                   context_append=_text(variant.get('context_append', ''), 'additional context', empty=True))
        if arm['name'].casefold() in {a['name'].casefold() for a in arms}: raise InputError('Variant names must be distinct')
        if not arm['parameters'] and not arm['context_append']: raise InputError('A variant needs a parameter or context change')
        if mode != 'replay' and arm['context_append']: raise InputError('Additional rollout context is supported in replay mode')
        arms.append(arm)
    seeds = raw.get('seeds')
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 32 or any(type(s) is not int or not 0 <= s <= 2**32-1 for s in seeds) or len(set(seeds)) != len(seeds):
        raise InputError('Use 1–32 distinct integer seeds')
    budget = raw.get('budget')
    if not isinstance(budget, dict) or set(budget) != {'max_trials', 'max_steps', 'max_tokens'}: raise InputError('Set trial, step and token limits')
    for k, v in budget.items():
        if type(v) is not int or not 1 <= v <= 1000000000: raise InputError('Budget limits must be positive integers')
    if len(arms) * len(seeds) > budget['max_trials']: raise InputError('Planned trials exceed the trial limit')
    measure = raw.get('measure')
    if not isinstance(measure, dict) or set(measure) != {'key', 'label', 'unit'}: raise InputError('Name the primary result metric and unit')
    measure = {k: _text(v, 'metric ' + k, 160) for k, v in measure.items()}
    metadata = {k:deepcopy(v) for k,v in source.get('metadata', {}).items() if k in {
        'experiment','task_id','environment','environment_version','checkpoint','training_step','training_clock','training_step_basis','seed','split'}}
    value = dict(schema=VERSION, mode=mode, source=dict(run_id=run_id, source_hash=digest(source), through_event_id=through,
        event_count=index + 1, prefix_hash=digest(events[:index + 1]), metadata=metadata), configuration=config,
        checkpoint=dict(reference=reference, available_state=sorted(state)), arms=arms, seeds=seeds, budget=deepcopy(budget), measure=measure)
    if resets: value['checkpoint']['reset_state'] = sorted(resets)
    value['id'] = 'trial-' + digest(value)
    return value


def overlay(base, overrides):
    """Recursive object overlay; arrays and null replace the original value."""
    result = deepcopy(base)
    for key, value in overrides.items():
        result[key] = overlay(result.get(key, {}), value) if isinstance(value, dict) and isinstance(result.get(key, {}), dict) else deepcopy(value)
    return result


def jobs(trial):
    for seed in trial['seeds']:
        for arm in trial['arms']:
            yield dict(id='trial-job-' + digest([trial['id'], arm['name'], seed]), arm=arm['name'], seed=seed,
                mode=trial['mode'], configuration=overlay(trial['configuration']['values'], arm['parameters']),
                context_append=arm['context_append'], checkpoint=deepcopy(trial['checkpoint']), budget=deepcopy(trial['budget']))


def manifest(store, investigation_id, check_id):
    doc = failure_investigations.read(store, investigation_id)
    check = next((c for c in doc.get('follow_up', {}).get('checks', []) if c['id'] == check_id), None)
    if not check or not check.get('trial'): raise InputError('This check has no trial design')
    trial = check['trial']; source = _source(store, trial['source']['run_id'])
    if digest(source) != trial['source']['source_hash']: raise InputError('The pinned source revision is unavailable')
    # Do not send later events, raw documents, or logged outcomes to the callback.
    prefix = deepcopy(source['events'][:trial['source']['event_count']])
    return dict(schema='trial-handoff/1', investigation_id=doc['id'], check_id=check_id, trial=deepcopy(trial),
        prefix=prefix, jobs=list(jobs(trial)), results=deepcopy(check.get('trial_results', [])),
        comparison=compare(check), boundary='Recorded prefix is diagnostic input. Restore and budget enforcement belong to your adapter; receipts report what it actually applied.')


def receipt(store, check, raw):
    if not isinstance(raw, dict) or set(raw) - {'job_id', 'status', 'metrics', 'applied', 'note', 'experiment', 'rollout_ids'}:
        raise InputError('Unexpected trial result fields')
    job = next((j for j in jobs(check['trial']) if j['id'] == raw.get('job_id')), None)
    if job is None: raise InputError('Result does not belong to a planned trial')
    status = raw.get('status')
    if not isinstance(status, str) or status not in {'completed', 'error', 'blocked', 'incomplete'}: raise InputError('Invalid trial result status')
    metrics = _object(raw.get('metrics', {}), 'Metrics')
    if len(metrics) > 64 or any(not k or len(k) > 160 or type(v) not in (int, float) or not math.isfinite(v) for k, v in metrics.items()):
        raise InputError('Metrics must contain up to 64 named finite numbers')
    applied = _object(raw.get('applied', {}), 'Applied settings')
    allowed = {'configuration', 'context_append', 'checkpoint_reference', 'restored_state', 'reset_state', 'seed'}
    if set(applied) - allowed: raise InputError('Unexpected applied settings')
    if 'configuration' in applied: _object(applied['configuration'], 'Applied configuration')
    for key in ('context_append', 'checkpoint_reference'):
        if key in applied: _text(applied[key], key, empty=True)
    if 'seed' in applied and type(applied['seed']) is not int: raise InputError('Applied seed must be an integer')
    if 'restored_state' in applied and (not isinstance(applied['restored_state'], list) or any(not isinstance(s, str) or s not in STATES for s in applied['restored_state'])):
        raise InputError('Invalid restored state components')
    if 'reset_state' in applied and (not isinstance(applied['reset_state'], list) or any(not isinstance(s, str) or s not in STATES for s in applied['reset_state'])):
        raise InputError('Invalid restarted state components')
    if set(applied.get('reset_state', [])) & set(applied.get('restored_state', [])):
        raise InputError('Applied state cannot be both restored and restarted')
    experiment = raw.get('experiment')
    if experiment is not None: experiment = _text(experiment, 'returned experiment', 512)
    result = dict(job_id=job['id'], status=status, metrics=metrics, applied=applied,
        note=_text(raw.get('note', ''), 'result note', empty=True), experiment=experiment)
    if 'rollout_ids' in raw:
        ids=raw['rollout_ids']
        if not isinstance(ids,list) or len(ids)>64 or any(not isinstance(r,str) or not r or len(r)>256 for r in ids) or len(set(ids))!=len(ids):
            raise InputError('Return up to 64 distinct rollout identities per trial')
        result['rollout_ids']=list(ids)
    result['id'] = 'trial-result-' + digest(result)
    return result


def compare(check):
    trial = check['trial']; records = {r['job_id']: r for r in check.get('trial_results', [])}
    rows = []; by_arm = {}
    for job in jobs(trial):
        result = records.get(job['id']); issues = []
        if result:
            applied = result['applied']
            for k, expected in [('configuration', job['configuration']), ('context_append', job['context_append']),
                                ('checkpoint_reference', job['checkpoint']['reference']), ('seed', job['seed'])]:
                if k not in applied: issues.append('Unreported ' + k.replace('_', ' '))
                elif dumps(applied[k]) != dumps(expected): issues.append('Different ' + k.replace('_', ' '))
            required = set(job['checkpoint']['available_state'])
            if trial['mode'] == 'train': required |= {'model', 'optimizer', 'scheduler', 'rng', 'data'}
            resets = set(job['checkpoint'].get('reset_state', []))
            required -= resets
            if set(applied.get('reset_state', [])) != resets:
                issues.append('Different restarted state')
            if required - set(applied.get('restored_state', [])):
                issues.append('Unrestored state: ' + ', '.join(sorted(required - set(applied.get('restored_state', [])))))
        value = result['metrics'].get(trial['measure']['key']) if result else None
        comparable = bool(result and result['status'] == 'completed' and value is not None and not issues)
        row = dict(job_id=job['id'], arm=job['arm'], seed=job['seed'], status=result['status'] if result else 'pending',
            value=value, comparable=comparable, issues=issues, result=result)
        rows.append(row); by_arm.setdefault(job['arm'], {})[job['seed']] = row
    contrasts = []
    for arm in trial['arms'][1:]:
        paired = [(by_arm['Reference'][s], by_arm[arm['name']][s]) for s in trial['seeds']]
        complete = [(a, b) for a, b in paired if a['comparable'] and b['comparable']]
        differences = [dict(seed=a['seed'], difference=b['value']-a['value']) for a,b in complete]
        finite = [d for d in differences if math.isfinite(d['difference'])]
        contrasts.append(dict(arm=arm['name'], paired=len(finite), planned=len(paired),
            unrepresentable_differences=len(differences)-len(finite),
            mean_difference=mean(d['difference'] for d in finite) if finite else None, differences=finite))
    return dict(rows=rows, contrasts=contrasts, measure=trial['measure'],
        interpretation='Paired by requested seed on one pinned case. Applied settings and restore state are adapter-reported; differences are descriptive, not a causal or generalization claim.',
        replay_scope='Environment/agent state requested' if {'environment', 'agent'} <= set(trial['checkpoint']['available_state']) else 'Text prefix only; environment/agent restoration is not established')
