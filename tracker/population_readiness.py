"""Evidence availability, separate from task outcomes and population closure.

These are source/measurement facts, not an estimator of unreported work. The
same reducer is used for chart bins, frozen comparisons and code consumers.
"""
from collections import Counter
import json
from .schema import dumps


def value_state(point):
    """Why a scalar is absent; a saved unresolved observation is still evidence."""
    if point.get('value') is not None:
        return 'numeric_value'
    if point.get('status') == 'error':
        return 'measurement_error'
    if not point.get('value_id'):
        return 'no_receipt'
    if (point.get('unknown_opportunities') or 0) > 0:
        return 'unresolved_evidence'
    if point.get('opportunities') == 0:
        return 'no_opportunities'
    return 'no_value'


def summarize(points, *, include_mix=True):
    measured = [p for p in points if p.get('value') is not None]
    states = Counter(p.get('capture_state', 'unknown') for p in points)
    missing = [p for p in points if p.get('value') is None]
    mixes = []
    for field in (('task_id', 'policy_version') if include_mix else ()):
        all_counts = Counter(dumps(p.get(field)) for p in points)
        counts = Counter(dumps(p.get(field)) for p in measured)
        distance = (sum(abs(counts[k]/len(measured)-n/len(points))
                        for k, n in all_counts.items())/2 if measured and points else None)
        mixes.append(dict(field=field, missing_context=all_counts.get('null', 0),
            measured_mix_distance=distance,
            groups=[dict(value=json.loads(k), observed=n, measured=counts[k])
                    for k, n in sorted(all_counts.items(), key=lambda r: (-r[1], str(r[0])))]))
    return dict(observed=len(points), measured=len(measured),
        measurement_coverage=len(measured)/len(points) if points else None,
        capture_states=dict(states), unfinished=states['in_progress'], failed_capture=states['failed'],
        completed_unmeasured=sum(p.get('capture_state') == 'complete' for p in missing),
        imported_unmeasured=sum(p.get('capture_state') == 'imported_snapshot' for p in missing),
        missing_by_status=dict(Counter(p.get('status', 'unknown') for p in missing)),
        value_states=dict(Counter(value_state(p) for p in points)),
        arrived_value_states=dict(Counter(value_state(p) for p in missing
            if p.get('capture_state') in {'complete', 'imported_snapshot'})),
        selection=mixes, population_closed=None,
        boundary='Observed sources only. Unreported jobs and final population size are unknown. Capture completion is not task success.')


def review(cohorts):
    """Checks suggest discriminating evidence, never a training intervention."""
    checks = []
    def add(code, title, evidence, action):
        checks.append(dict(code=code, title=title, evidence=evidence, next_check=action))
    for side in ('baseline', 'current'):
        summaries = [r[side]['readiness'] for r in cohorts]
        unfinished = sum(s['unfinished'] for s in summaries)
        # Old frozen summaries have no reason partition. Preserve their meaning
        # rather than inferring an observation that was never saved.
        unmeasured = sum(sum(s['arrived_value_states'].get(k, 0) for k in ('no_receipt', 'no_value'))
            if 'arrived_value_states' in s else s['completed_unmeasured'] + s['imported_unmeasured']
            for s in summaries)
        if unfinished:
            add(side+'_unfinished', side.title()+' has unfinished source captures',
                f'{unfinished} latest source captures are in progress.',
                'Save this comparison, then repeat the same windows after more reports arrive; inspect which tasks and policies are still represented less.')
        if unmeasured:
            add(side+'_unmeasured', side.title()+' has arrived sources without measurements',
                f'{unmeasured} completed captures or imported snapshots have no value for this monitor.',
                'Inspect missing cases: a delayed score, missing semantic observation and capture delay require different fixes.')
        for state, title, action in [
            ('unresolved_evidence', 'has recorded but unresolved evidence',
             'Inspect the saved witnesses and unresolved opportunities. Conflicting or incomplete evidence is excluded from the numeric rate; it is not a missing observation.'),
            ('no_opportunities', 'has observations with no eligible opportunities',
             'Check whether the behavior was applicable in these tasks. A recorded absence of opportunities is neither failure nor an unmeasured rollout.'),
            ('measurement_error', 'has measurement errors',
             'Inspect the saved measurement error before interpreting the curve; this is not a model failure.')]:
            count = sum(s.get('arrived_value_states', {}).get(state, 0) for s in summaries)
            if count:
                add(side+'_'+state, side.title()+' '+title,
                    f'{count} completed captures or imported snapshots have no numeric value for this reason.', action)
        if any(s['failed_capture'] for s in summaries):
            add(side+'_capture_failed', side.title()+' has failed source captures',
                f"{sum(s['failed_capture'] for s in summaries)} capture failures are missing, not task failures.",
                'Inspect collector and execution evidence before interpreting a change in task success.')
        for field in ('task_id', 'policy_version'):
            affected = sum(any(g['field']==field and (g['measured_mix_distance'] or 0)>0 for g in s['selection']) for s in summaries)
            if affected:
                add(side+'_'+field+'_selection', side.title()+' measured population differs',
                    f'{affected} cohorts have different {field.replace("_", " ")} proportions among measured and observed sources.',
                    'Compare within recorded task/policy groups. A changed sample mix can move the curve in either direction; length alone does not establish difficulty.')
    if any((r['task_mix']['recorded_task_mix_distance'] or 0)>0 for r in cohorts):
        add('task_mix', 'Task composition changed between windows',
            'Recorded task proportions differ in at least one cohort.',
            'Compare a fixed task set or held-out evaluation under the same harness; environment reweighting alone does not control task mix.')
    unknown = [k.replace('_',' ') for k in ('training_step_basis','split','sampling','reward_definition')
               if any(r['cohort'].get(k) is None for r in cohorts)]
    if unknown:
        add('comparison_context', 'Some comparison settings are not recorded',
            'Missing in at least one cohort: '+', '.join(unknown)+'.',
            'Record these settings before treating the windows as equivalent. Generation steps, learner updates and evaluation batches are different coordinates.')
    add('separate_training_use', 'Check what the learner actually consumed',
        'Source measurements describe observed rollouts, not optimizer updates.',
        'Open Training samples to compare generated, selected and used samples, and Training health for generation-policy age and learner coordinates.')
    return checks
