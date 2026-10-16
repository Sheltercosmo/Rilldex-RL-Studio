"""Pin training-sample evidence for source rollouts in a comparison.

This is a pure projection over an already captured training-lineage snapshot.
It joins only by the snapshot's exact ``run_id``; training steps, rollout names,
and similar metadata are never used as fallback keys. Missing stage records are
unknown and are not treated as rejection or non-use.
"""
from collections import Counter
from copy import deepcopy

from .schema import InputError


VERSION = 'comparison-training-lineage/1'
STAGES = ('generated', 'scored', 'admitted', 'backward', 'optimizer')
WINDOWS = ('baseline', 'current')


def _run_id(value):
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        identifier = value.get('run_id', value.get('id'))
        if isinstance(identifier, str) and identifier:
            return identifier
    raise InputError('Selected source rollouts must be run IDs or objects with run_id')


def _selected(selected_runs):
    if not isinstance(selected_runs, dict) or set(selected_runs) != set(WINDOWS):
        raise InputError('Select baseline and current source rollout IDs')
    result = {}
    for window in WINDOWS:
        values = selected_runs[window]
        if not isinstance(values, (list, tuple)):
            raise InputError(window + ' source rollouts must be a list')
        # A rollout belongs to one window once, regardless of repeated points.
        result[window] = list(dict.fromkeys(_run_id(value) for value in values))
    overlap = set(result['baseline']) & set(result['current'])
    if overlap:
        raise InputError('A source rollout cannot belong to both comparison windows')
    return result


def _stage_state(sample, stage):
    """Return observed membership, explicit nonmembership, or unknown."""
    records = sample.get('records') or []
    if stage == 'generated':
        return 'member'
    if stage == 'scored':
        relevant = [r for r in records if r.get('kind') == 'score']
        if any((r.get('data') or {}).get('status') == 'scored' for r in relevant):
            return 'member'
        return 'nonmember' if relevant and all((r.get('data') or {}).get('status') in {'unavailable', 'error'} for r in relevant) else 'unknown'
    if stage == 'admitted':
        relevant = [r for r in records if r.get('kind') == 'selection']
        if any((r.get('data') or {}).get('decision') == 'admitted' for r in relevant):
            return 'member'
        return 'nonmember' if relevant and all((r.get('data') or {}).get('decision') == 'rejected' for r in relevant) else 'unknown'
    observed_kind = 'backward_completed' if stage == 'backward' else 'optimizer_step_completed'
    return 'member' if any(r.get('kind') == 'use' and (r.get('data') or {}).get('stage') == observed_kind
                           for r in records) else 'unknown'


def _sample_projection(sample):
    """Keep the exact declared sample and source-bound facts for the receipt."""
    return deepcopy(sample)


def _rollout_record(run_id, samples):
    if not samples:
        return {'run_id': run_id, 'join_status': 'no_exact_sample_join', 'sample_count': 0,
                'stages': {stage: {'membership': 'unknown', 'member_samples': 0,
                                   'unknown_samples': 0, 'explicit_nonmember_samples': 0}
                           for stage in STAGES},
                'samples': []}
    sample_rows = []
    states = {stage: [] for stage in STAGES}
    for sample in samples:
        projected = _sample_projection(sample)
        projected['stage_membership'] = {}
        for stage in STAGES:
            state = _stage_state(sample, stage)
            projected['stage_membership'][stage] = state
            states[stage].append(state)
        sample_rows.append(projected)
    stage_summary = {}
    for stage, values in states.items():
        members = values.count('member')
        unknown = values.count('unknown')
        nonmembers = values.count('nonmember')
        stage_summary[stage] = {
            'membership': 'observed' if members else 'unknown' if unknown else 'no_observed_membership',
            'member_samples': members,
            'unknown_samples': unknown,
            'explicit_nonmember_samples': nonmembers,
        }
    return {'run_id': run_id, 'join_status': 'exact_source_run_id', 'sample_count': len(samples),
            'stages': stage_summary, 'samples': sample_rows}


def _window_record(run_ids, by_run):
    rollouts = [_rollout_record(run_id, by_run.get(run_id, [])) for run_id in run_ids]
    joined = [r for r in rollouts if r['sample_count']]
    stage_counts = {}
    for stage in STAGES:
        stage_counts[stage] = {
            # Unique source rollouts, not sample records or repeated uses.
            'member_rollouts': sum(r['stages'][stage]['membership'] == 'observed' for r in rollouts),
            'unknown_rollouts': sum(r['stages'][stage]['membership'] == 'unknown' for r in rollouts),
            'no_observed_membership_rollouts': sum(r['stages'][stage]['membership'] == 'no_observed_membership' for r in rollouts),
            'member_samples': sum(r['stages'][stage]['member_samples'] for r in rollouts),
            'unknown_samples': sum(r['stages'][stage]['unknown_samples'] for r in rollouts),
            'explicit_nonmember_samples': sum(r['stages'][stage]['explicit_nonmember_samples'] for r in rollouts),
        }
    return {
        'source_rollouts': len(run_ids),
        'joined_source_rollouts': len(joined),
        'source_rollouts_without_joined_samples': [r['run_id'] for r in rollouts if not r['sample_count']],
        'sample_count': sum(r['sample_count'] for r in joined),
        'stages': stage_counts,
        'rollouts': rollouts,
    }


def capture(selected_runs, training_snapshot):
    """Freeze exact training records for selected baseline/current source runs.

    ``selected_runs`` is ``{'baseline': [run_id, ...], 'current': [...]}``.
    The snapshot is already scoped by its caller; this function further limits
    evidence to its exact selected source run IDs and never matches on step.
    A matched sample row must itself declare ``join_status == 'matched'``.
    """
    selected = _selected(selected_runs)
    if not isinstance(training_snapshot, dict) or not isinstance(training_snapshot.get('samples'), list):
        raise InputError('Supply an already-read training lineage snapshot')
    selected_ids = set(selected['baseline']) | set(selected['current'])
    by_run = {run_id: [] for run_id in selected_ids}
    for sample in training_snapshot['samples']:
        if not isinstance(sample, dict):
            continue
        run_id = sample.get('run_id')
        if run_id in selected_ids and sample.get('join_status') == 'matched':
            by_run[run_id].append(sample)
    return {
        'schema': VERSION,
        'training_snapshot_id': training_snapshot.get('snapshot_id'),
        'training_snapshot_revision': training_snapshot.get('revision'),
        'join_basis': 'Exact matched training-lineage run_id only; no step/name/clock fallback.',
        'membership_boundary': 'Stage membership is observed when producer facts establish it. Missing facts remain unknown; explicit score errors/unavailability and rejected selections are reported as nonmembership evidence.',
        'windows': {window: _window_record(selected[window], by_run) for window in WINDOWS},
    }
