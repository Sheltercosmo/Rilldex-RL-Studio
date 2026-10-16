"""Descriptive behavior comparisons with fixed, explicit task weights.

These estimates concern the shared observed tasks, not all training prompts or
an independent evaluation population. No causal effect or interval is inferred.
"""
from collections import Counter, defaultdict
from .schema import digest

VERSION = 'behavior-task-mix/1'


def identity(metadata):
    task = metadata.get('task_id')
    if not isinstance(task, str) or not task.strip():
        return None
    value = {'task_id': task, 'task_revision': metadata.get('task_revision')}
    return {'id': 'task-stratum-' + digest(value), **value}


def compare(points, population, categories, weighting, earlier, later, steps, aggregate):
    """Equal task weights, selected weighting inside each task, no imputation."""
    def inside(row, bounds):
        step = row.get('step')
        return step is not None and bounds[0] is not None and bounds[0] <= step <= bounds[1]

    observed = [[p for p in points if inside(p, w)] for w in (earlier, later)]
    imported = [[p for p in population if inside(p, w)] for w in (earlier, later)]
    def group(ps):
        buckets = defaultdict(list)
        for p in ps:
            if p.get('task'): buckets[p['task']['id']].append(p)
        return buckets
    grouped = [group(ps) for ps in observed]
    imported_counts = [Counter(p['task']['id'] for p in ps if p.get('task')) for ps in imported]
    tasks = {p['task']['id']: p['task'] for rows in imported for p in rows if p.get('task')}
    ordered = earlier[1] is not None and later[0] is not None and earlier[1] < later[0]
    rows = []
    for key, task in sorted(tasks.items()):
        a, b = [aggregate(ps[key], categories, weighting) for ps in grouped]
        sizes = [ps[key] for ps in imported_counts]
        status = 'shared' if a['eligible_rollouts'] and b['eligible_rollouts'] else 'earlier_only' if a['eligible_rollouts'] else 'later_only' if b['eligible_rollouts'] else 'unobserved'
        rows.append({'task': task, 'status': status, 'earlier': {**a, 'population': sizes[0]},
                     'later': {**b, 'population': sizes[1]},
                     'pp': {k: 100 * (b['shares'][k] - a['shares'][k]) if status == 'shared' and ordered else None for k in categories}})
    shared = [r['task']['id'] for r in rows if r['status'] == 'shared']
    shared_set = set(shared)
    available = bool(shared and ordered)

    def fixed(ps):
        buckets = group(ps)
        by_task = [aggregate(buckets[t], categories, weighting) for t in shared]
        complete = bool(by_task) and all(x['eligible_rollouts'] for x in by_task)
        matched = [p for p in ps if (p.get('task') or {}).get('id') in shared_set]
        result = aggregate(matched, categories, weighting)
        result['shares'] = {k: sum(x['shares'][k] for x in by_task) / len(by_task) if complete else None for k in categories}
        result.update(tasks_observed=sum(bool(x['eligible_rollouts']) for x in by_task), tasks_required=len(shared), complete=complete)
        return result

    a, b = [fixed(ps) for ps in observed]
    raw_a, raw_b = [aggregate(ps, categories, weighting) for ps in observed]
    raw_comparable = bool(ordered and raw_a['eligible_rollouts'] and raw_b['eligible_rollouts'])
    by_step = defaultdict(list)
    for p in points: by_step[p['step']].append(p)
    trend = [{'step': step, **fixed(by_step[step])} for step in steps]
    return {'schema': VERSION, 'available': available,
            'reason': None if available else 'Use non-overlapping windows with at least one identified task observed in both.',
            'shared_task_ids': shared, 'weights': {t: 1 / len(shared) for t in shared},
            'tasks': rows, 'earlier': a, 'later': b, 'raw_earlier': raw_a, 'raw_later': raw_b,
            'deltas': [{'id': k, 'raw_pp': 100 * (raw_b['shares'][k] - raw_a['shares'][k]) if raw_comparable else None,
                        'fixed_pp': 100 * (b['shares'][k] - a['shares'][k]) if available else None} for k in categories],
            'bins': trend,
            'unidentified_rollouts': [sum(not p.get('task') for p in ps) for ps in imported],
            'unobserved_rollouts': [len(ps) - len(obs) for ps, obs in zip(imported, observed)],
            'definition': 'Equal weight for each task and revision with eligible observations in both windows; '
                          + ('each rollout has equal weight within its task.' if weighting == 'rollout' else 'opportunities are pooled within each task.'),
            'limit': 'Descriptive comparison on shared observed tasks. Selection, annotation coverage, unrecorded configuration and sampling noise can still differ. '
                     'No causal adjustment, significance claim or claim of generalization. Missing tasks break the fixed-task step curve; they are not assigned zero.'}
