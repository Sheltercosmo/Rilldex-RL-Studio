"""Descriptive binary comparisons under a fixed, inspectable task weighting.

No resampling, independence, causal effect or unobserved task equivalence is
assumed. Callers supply exact opportunity identities and frozen populations.
"""
from collections import defaultdict
from statistics import fmean
from .schema import InputError

VERSION = 'binary-task-comparison/1'


def rate(rows):
    n = sum(r['outcome'] == 'passed' for r in rows)
    d = sum(r['outcome'] != 'unknown' for r in rows)
    total = len(rows)
    return dict(value=n/d if d else None, numerator=n, denominator=d,
                opportunities=total, unknown=total-d,
                lower=n/total if total else None,
                upper=(n+total-d)/total if total else None)


def difference(a, b):
    return a-b if a is not None and b is not None else None


def compare(focus, reference):
    groups = {}; tables = {}; all_ids = {}
    for name, rows in [('focus', focus), ('reference', reference)]:
        if any(set(r) != {'id','task_id','outcome'} or not isinstance(r['id'],str)
               or not r['id'] or r['outcome'] not in {'passed','failed','unknown'}
               or r['task_id'] is not None and (not isinstance(r['task_id'],str) or not r['task_id'].strip()) for r in rows):
            raise InputError('Task comparison needs unique opportunity IDs, explicit task IDs or null, and binary/unknown outcomes')
        ids = [r['id'] for r in rows]
        if len(set(ids)) != len(ids): raise InputError('Duplicate opportunity in task comparison')
        all_ids[name] = set(ids)
        by_task = defaultdict(list)
        for r in rows:
            if r['task_id'] is not None: by_task[r['task_id']].append(r)
        tables[name] = by_task
        groups[name] = dict(**rate(rows), task_count=len(by_task), missing_task=sum(r['task_id'] is None for r in rows))
    shared = sorted(set(tables['focus']) & set(tables['reference']))
    task_rows = []
    for task in sorted(set(tables['focus']) | set(tables['reference'])):
        task_rows.append(dict(task_id=task, shared=task in shared,
            **{name: dict(**rate(tables[name].get(task, [])), ids=sorted(r['id'] for r in tables[name].get(task, [])))
               for name in ('focus','reference')}))
    standardized = {}
    for name in ('focus','reference'):
        rates = [rate(tables[name][task]) for task in shared]
        standardized[name] = dict(
            value=fmean(r['value'] for r in rates) if rates and all(r['value'] is not None for r in rates) else None,
            lower=fmean(r['lower'] for r in rates) if rates else None,
            upper=fmean(r['upper'] for r in rates) if rates else None,
            tasks_without_decidable_outcomes=sum(r['value'] is None for r in rates),
            opportunities=sum(r['opportunities'] for r in rates), unknown=sum(r['unknown'] for r in rates),
            excluded_opportunities=groups[name]['opportunities']-sum(r['opportunities'] for r in rates))
    adjusted_delta = difference(standardized['focus']['value'],standardized['reference']['value'])
    raw_delta = difference(groups['focus']['value'],groups['reference']['value'])
    return dict(schema=VERSION, raw=groups, raw_difference=raw_delta,
        shared_tasks=shared, tasks=task_rows, equal_task_weight=standardized,
        equal_task_difference=adjusted_delta,
        difference_lower=difference(standardized['focus']['lower'],standardized['reference']['upper']),
        difference_upper=difference(standardized['focus']['upper'],standardized['reference']['lower']),
        direction_reverses=raw_delta is not None and adjusted_delta is not None and raw_delta*adjusted_delta < 0,
        shared_opportunity_ids=sorted(all_ids['focus'] & all_ids['reference']),
        status='no_shared_tasks' if not shared else 'undecidable_tasks' if adjusted_delta is None else 'available',
        definition='Each shared recorded task receives equal weight in both populations. The point estimate is unavailable if any shared task has no decidable outcomes on either side. Lower/upper values allow unresolved outcomes to fail/pass; they are not confidence intervals. Unshared tasks remain outside this comparison. Task identity alone does not establish equal difficulty, task revision, model context or independent trials.')
