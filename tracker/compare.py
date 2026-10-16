"""Equal-task comparisons with paired task bootstrap and explicit exclusions."""
from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean

from .observe import MODES
from .schema import digest, InputError
from .sequence import SEQUENCE_VERSION, DEFINITION as SEQUENCE_DEFINITION

COMPARISON_VERSION = 'matched-tasks/4'
BOOTSTRAP_SAMPLES = 2000
MIN_INTERVAL_TASKS = 5
SCOPES = ('connected', 'outside', 'conflicting', 'unresolved')
RESPONSES = ('repeat', 'parameter_change', 'method_change', 'gather_information', 'continue', 'unresolved')
TRANSITIONS = tuple(source+'.'+target for source in MODES for target in MODES)


def _stop(status, message, excluded):
    return {'status': status, 'message': message, 'checkpoints': [], 'excluded': excluded,
            'version': COMPARISON_VERSION}


def _task_summary(task_id, rows):
    feedback_rows = [r for r in rows if r['metrics'].get('feedback_opportunities', 0)]
    sequence_rows = [r for r in rows if r['metrics'].get('sequence',{}).get('version')==SEQUENCE_VERSION
                     and r['metrics']['sequence'].get('observed_pairs',0)>0]
    return {
        'task_id': task_id, 'rollouts': len(rows),
        'run_ids': sorted(r['id'] for r in rows),
        'modes': {m: mean(r['metrics']['mode_counts'][m] / r['metrics']['actions'] for r in rows) for m in MODES},
        'scopes': {m: mean(r['metrics'].get('goal_scope_counts', {}).get(m, 0) / r['metrics']['actions'] for r in rows) for m in SCOPES},
        'repeat_rate': mean(r['metrics']['exact_repeats'] / r['metrics']['actions'] for r in rows),
        'action_count': mean(r['metrics']['actions'] for r in rows),
        'goal_assignment_rate': mean(r['metrics'].get('goal_assignments', 0) / r['metrics']['actions'] for r in rows),
        'feedback': {m: mean(r['metrics'].get('feedback_response_counts', {}).get(m, 0) / r['metrics']['feedback_opportunities'] for r in feedback_rows) if feedback_rows else None for m in RESPONSES},
        'feedback_rollouts': len(feedback_rows),
        'feedback_opportunities': sum(r['metrics'].get('feedback_opportunities', 0) for r in rows),
        'sequence': {key:mean(r['metrics']['sequence']['counts'].get(key,0)/r['metrics']['sequence']['observed_pairs'] for r in sequence_rows)
                     for key in TRANSITIONS} if sequence_rows else None,
        'sequence_rollouts':len(sequence_rows),
        'sequence_coverage':{key:sum(r['metrics'].get('sequence',{}).get(key,0) for r in rows)
                             for key in ('possible_pairs','observed_pairs','excluded_batch_pairs','unresolved_pairs')},
    }


def _flatten(task):
    return {**{'purpose.' + k: v for k,v in task['modes'].items()},
            **{'task_relation.' + k: v for k,v in task['scopes'].items()},
            'repeat_rate': task['repeat_rate'], 'action_count': task['action_count'],
            'goal_assignment_rate': task['goal_assignment_rate']}


def _paired_delta(before, after):
    """Resample paired tasks as clusters, never individual actions.

    Rollouts within a task are averaged first. Intervals describe variation
    across tasks, not within-task rollout variance or inspector uncertainty.
    """
    left = {t['task_id']: t for t in before['tasks']}
    right = {t['task_id']: t for t in after['tasks']}
    task_ids = sorted(left.keys() & right.keys())
    vectors = {tid: {k: v - _flatten(left[tid])[k] for k,v in _flatten(right[tid]).items()} for tid in task_ids}
    feedback_ids = [tid for tid in task_ids if left[tid]['feedback_rollouts'] and right[tid]['feedback_rollouts']]
    for tid in feedback_ids:
        for key in RESPONSES:
            vectors[tid]['feedback.' + key] = right[tid]['feedback'][key] - left[tid]['feedback'][key]
    sequence_ids = [tid for tid in task_ids if left[tid]['sequence'] is not None and right[tid]['sequence'] is not None]
    for tid in sequence_ids:
        for key in TRANSITIONS:
            vectors[tid]['transition.'+key] = right[tid]['sequence'][key]-left[tid]['sequence'][key]
    seed = int(digest({'version': COMPARISON_VERSION, 'before': before['checkpoint'], 'after': after['checkpoint'], 'tasks': task_ids})[:16], 16)
    estimates = {}
    keys = sorted(set().union(*(v.keys() for v in vectors.values())))
    for key in keys:
        values = [vectors[tid][key] for tid in task_ids if key in vectors[tid]]
        n = len(values)
        interval = None
        if n >= MIN_INTERVAL_TASKS:
            # Equal eligible cohorts use the same draws across metrics.
            rng = random.Random(seed)
            draws = sorted(sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(BOOTSTRAP_SAMPLES))
            interval = [draws[int(.025 * BOOTSTRAP_SAMPLES)], draws[int(.975 * BOOTSTRAP_SAMPLES)-1]]
        estimates[key] = {'delta': mean(values), 'task_count': n, 'interval_95': interval,
                          'interval_status': 'estimated' if interval else 'fewer_than_5_tasks'}
    sequence = {'task_ids':sequence_ids,'excluded_task_ids':[tid for tid in task_ids if tid not in sequence_ids],
                'before':{key:mean(left[tid]['sequence'][key] for tid in sequence_ids) for key in TRANSITIONS} if sequence_ids else None,
                'after':{key:mean(right[tid]['sequence'][key] for tid in sequence_ids) for key in TRANSITIONS} if sequence_ids else None,
                'coverage':{},'definition':SEQUENCE_DEFINITION}
    for label, source in [('before',left),('after',right)]:
        sequence['coverage'][label] = {'eligible_rollouts':sum(source[t]['sequence_rollouts'] for t in sequence_ids),
                                     'total_rollouts':sum(source[t]['rollouts'] for t in sequence_ids),
                                     **{key:sum(source[t]['sequence_coverage'][key] for t in sequence_ids)
                                        for key in ('possible_pairs','observed_pairs','excluded_batch_pairs','unresolved_pairs')}}
    return {'reference': before['checkpoint'], 'checkpoint': after['checkpoint'], 'metrics': estimates, 'sequence':sequence,
            'feedback_matched_tasks': feedback_ids,
            'feedback_excluded_tasks': [tid for tid in task_ids if tid not in feedback_ids],
            'method': 'Paired task-cluster percentile bootstrap; 2,000 draws, deterministic seed, pointwise 95% intervals. No interval below five tasks. This minimum is a display policy, not a guarantee of reliable small-sample inference.'}


def compare(runs: list[dict], *, experiment=None, environment=None, environment_version=None, split=None,
            inspector_signature=None, sampling_hash=None, checkpoints=None, reference=None):
    fields = {'experiment':experiment,'environment':environment,'environment_version':environment_version,'split':split}
    selected = [r for r in runs if all(value is None or r['metadata'].get(key)==value for key,value in fields.items())
                and (not inspector_signature or r.get('inspector_signature','heuristic')==inspector_signature)
                and (not sampling_hash or digest(r['metadata'].get('sampling',{}))==sampling_hash)
                and (checkpoints is None or r['metadata'].get('checkpoint') in checkpoints)]
    groups, excluded = defaultdict(list), []
    for r in selected:
        m = r['metadata']
        ingestion = r.get('ingestion')
        if ingestion and (not ingestion['is_latest'] or ingestion['state'] == 'in_progress'):
            excluded.append({'id': r['id'], 'reason': 'Superseded or incomplete producer snapshot'})
            continue
        missing = [k for k in ('task_id', 'checkpoint', 'environment', 'environment_version', 'experiment', 'split') if not m.get(k)]
        if missing:
            excluded.append({'id': r['id'], 'reason': 'Missing ' + ', '.join(missing)})
        elif r['metrics']['actions'] == 0:
            excluded.append({'id': r['id'], 'reason': 'No recorded actions'})
        else:
            groups[m['checkpoint']].append(r)
    if len(groups) < 2:
        return _stop('insufficient_checkpoints', 'At least two policy checkpoints with task, environment version, experiment and split identities are required.', excluded)
    if reference is not None and reference not in groups:
        raise InputError('Reference checkpoint is not in the selected comparison')
    common = set.intersection(*[{r['metadata']['task_id'] for r in rs} for rs in groups.values()])
    if not common:
        return _stop('no_matched_tasks', 'There are no task IDs shared by all selected checkpoints.', excluded)
    for checkpoint, rows in groups.items():
        excluded.extend({'id': r['id'], 'reason': 'Task absent from another checkpoint'} for r in rows if r['metadata']['task_id'] not in common)
        groups[checkpoint] = [r for r in rows if r['metadata']['task_id'] in common]
    eligible = [r for rows in groups.values() for r in rows]
    for task in common:
        versions = {(r['metadata'].get('task_revision'),r.get('environment_context_hash'),r.get('adapter_version'))
                    for r in eligible if r['metadata']['task_id']==task}
        if len(versions)>1:
            return _stop('task_context_changed', 'A matched task has changed task revision, recorded environment configuration or adapter version. Align these contexts before comparing behavior.', excluded)
    if any(r.get('semantic_coverage', 0) not in (0, r['metrics']['actions']) for r in eligible):
        return _stop('incomplete_observations', 'Finish semantic observation of matched runs before comparing mixed observation coverage.', excluded)
    if any(len(r.get('inspector_profiles', [])) > 1 for r in eligible):
        return _stop('mixed_inspector_profiles', 'Matched runs contain multiple observer profiles. Use one pinned harness, model and selection policy before comparing.', excluded)
    if any(r.get('reviewed_actions', 0) for r in eligible):
        return _stop('selective_reviews', 'Selected runs contain retrospective review overrides. A matched annotation protocol is required before these corrections can be used as training trends.', excluded)
    configurations = {(r['metadata']['experiment'], r['metadata']['environment'],
                       r['metadata']['environment_version'], r['metadata']['split'], r['harness_version'],
                       r.get('inspector_signature', 'heuristic'), digest(r['metadata'].get('sampling', {}))) for r in eligible}
    if len(configurations) != 1:
        return _stop('incompatible_cohort', 'Filter to one experiment, environment version, split, sampling setup and inspector configuration before comparing.', excluded)
    output = []
    for checkpoint, rows in groups.items():
        by_task = defaultdict(list)
        for r in rows:
            by_task[r['metadata']['task_id']].append(r)
        tasks = [_task_summary(tid, rs) for tid,rs in sorted(by_task.items())]
        steps = {r['metadata'].get('training_step') for r in rows}
        if len(steps) > 1:
            return _stop('inconsistent_checkpoint_step', 'A policy checkpoint maps to multiple or partly missing training steps. Correct its provenance before comparing.', excluded)
        feedback_tasks = [t for t in tasks if t['feedback_rollouts']]
        output.append({'checkpoint': checkpoint, 'training_step': next(iter(steps)),
                       'tasks': tasks, 'task_count': len(tasks), 'rollout_count': sum(t['rollouts'] for t in tasks),
                       'modes': {m: mean(t['modes'][m] for t in tasks) for m in MODES},
                       'scopes': {m: mean(t['scopes'][m] for t in tasks) for m in SCOPES},
                       'repeat_rate': mean(t['repeat_rate'] for t in tasks),
                       'action_count': mean(t['action_count'] for t in tasks),
                       'goal_assignment_rate': mean(t['goal_assignment_rate'] for t in tasks),
                       'feedback': {m: mean(t['feedback'][m] for t in feedback_tasks) if feedback_tasks else None for m in RESPONSES},
                       'feedback_task_count': len(feedback_tasks),
                       'feedback_opportunities': sum(t['feedback_opportunities'] for t in tasks)})
    ordered = all(c['training_step'] is not None for c in output) and len({c['training_step'] for c in output}) == len(output)
    output.sort(key=lambda x: (x['training_step'] if ordered else 0, x['checkpoint']))
    baseline = next((cp for cp in output if cp['checkpoint']==reference),output[0])
    deltas = [_paired_delta(baseline, other) for other in output if other is not baseline]
    comparison_id = digest({'version':COMPARISON_VERSION,'runs':sorted(eligible,key=lambda r:r['id']),'reference':baseline['checkpoint']})
    return {'status': 'ok', 'version': COMPARISON_VERSION, 'checkpoints': output, 'matched_tasks': sorted(common), 'excluded': excluded,
            'comparison_id':comparison_id,
            'selection':{'imported_rollouts':len(runs),'selected_rollouts':len(selected),'matched_rollouts':len(eligible)},
            'ordered_by_training_step': ordered, 'reference_checkpoint': baseline['checkpoint'], 'paired_deltas': deltas,
            'definition': 'Equal weight per matched task; rollout rates averaged within each task. Unresolved actions stay in denominators. Feedback deltas use paired tasks with recorded response opportunities at both checkpoints.',
            'limitations': ['Observed association, not a causal training effect.',
                            'Intervals measure variation across paired tasks; they do not estimate inspector accuracy or within-task rollout uncertainty.',
                            'Intervals are pointwise, with no multiple-comparison correction. Use effect sizes and evidence rather than automatic significance alerts.',
                            'A training axis is shown only when all policy checkpoint steps are recorded and distinct.']}
