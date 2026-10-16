"""Trace an aggregate change back to its eligible tasks and recorded actions."""
from .compare import compare, _flatten, MODES, SCOPES, RESPONSES, TRANSITIONS
from .schema import InputError, digest


class ComparisonChanged(InputError):
    pass


def measurement(row, metric):
    m = row['metrics']
    if metric.startswith('purpose.') and metric[8:] in MODES:
        return m['mode_counts'][metric[8:]], m['actions']
    if metric.startswith('task_relation.') and metric[14:] in SCOPES:
        return m.get('goal_scope_counts',{}).get(metric[14:],0), m['actions']
    if metric.startswith('feedback.') and metric[9:] in RESPONSES:
        return m.get('feedback_response_counts',{}).get(metric[9:],0), m.get('feedback_opportunities',0)
    if metric.startswith('transition.') and metric[11:] in TRANSITIONS:
        sequence = m.get('sequence',{})
        return sequence.get('counts',{}).get(metric[11:],0), sequence.get('observed_pairs',0)
    if metric in {'repeat_rate','goal_assignment_rate','action_count'}:
        key = {'repeat_rate':'exact_repeats','goal_assignment_rate':'goal_assignments','action_count':'actions'}[metric]
        return m.get(key,0), 1 if metric=='action_count' else m['actions']
    raise InputError('Unknown comparison metric')


def task_value(task, metric):
    if metric.startswith('feedback.'):
        return task['feedback'][metric[9:]]
    if metric.startswith('transition.'):
        return task['sequence'][metric[11:]] if task['sequence'] is not None else None
    return _flatten(task)[metric]


def action_matches(analysis, metric):
    if metric.startswith('transition.'):
        return [[p['from_event_id'],p['to_event_id']] for p in analysis.get('sequence',{}).get('pairs',[])
                if p['source']+'.'+p['target']==metric[11:]]
    matches = []
    for a in analysis['actions']:
        selected = (metric=='action_count'
                    or metric=='repeat_rate' and a['exact_repeat']
                    or metric=='goal_assignment_rate' and a.get('focus_goal_id') is not None
                    or metric.startswith('purpose.') and a['mode']==metric[8:]
                    or metric.startswith('task_relation.') and a['macro']['goal_scope']['value']==metric[14:])
        if metric.startswith('feedback.') and a['feedback_opportunity']:
            observed = a['semantic'].get('feedback_response',{})
            value = observed.get('value') if observed.get('status')=='decided' else 'unresolved'
            selected = value==metric[9:]
        if selected:
            matches.append(([a['previous_occurrence']] if metric=='repeat_rate' else [])+[a['event_id']])
    return matches


def evidence(runs, load_run, *, comparison_id, metric, checkpoint, reference=None,
             task_id=None, before_run=None, after_run=None, filters=None):
    result = compare(runs, **(filters or {}))
    if result['status']!='ok' or result['comparison_id']!=comparison_id:
        raise ComparisonChanged('The comparison cohort or observations changed. Refresh the comparison before inspecting its evidence.')
    if reference!=result['reference_checkpoint']:
        raise InputError('Evidence reference must match the displayed comparison')
    pair = next((p for p in result['paired_deltas'] if p['checkpoint']==checkpoint),None)
    if pair is None or metric not in pair['metrics']:
        raise InputError('This comparison does not contain the requested metric and checkpoint pair')
    checkpoints = {cp['checkpoint']:cp for cp in result['checkpoints']}
    left = {t['task_id']:t for t in checkpoints[reference]['tasks']}
    right = {t['task_id']:t for t in checkpoints[checkpoint]['tasks']}
    tasks = []
    for tid in result['matched_tasks']:
        before, after = task_value(left[tid],metric), task_value(right[tid],metric)
        if before is None or after is None:
            continue
        tasks.append({'task_id':tid,'before':before,'after':after,'delta':after-before,
                      'before_rollouts':left[tid]['rollouts'],'after_rollouts':right[tid]['rollouts']})
    tasks.sort(key=lambda t:(-abs(t['delta']),t['task_id']))
    if not tasks:
        raise InputError('No paired tasks have an opportunity for this metric')
    selected_task = task_id or tasks[0]['task_id']
    if selected_task not in {t['task_id'] for t in tasks}:
        raise InputError('Task is not eligible for this metric at both checkpoints')
    for task in tasks:
        task['contribution_to_mean'] = task['delta']/len(tasks)
    by_id = {r['id']:r for r in runs}
    columns = {}
    for side, cp, summaries, chosen in [('before',reference,left,before_run),('after',checkpoint,right,after_run)]:
        rollouts = []
        for rid in summaries[selected_task]['run_ids']:
            row = by_id[rid]
            numerator, denominator = measurement(row,metric)
            rollouts.append({'id':rid,'numerator':numerator,'denominator':denominator,
                             'value':numerator/denominator if denominator else None,
                             'seed':row['metadata'].get('seed'),'outcome':row.get('outcome',{})})
        if chosen is not None and chosen not in {r['id'] for r in rollouts}:
            raise InputError('Selected rollout is outside the matched task and checkpoint')
        selected = next(r for r in rollouts if r['id']==chosen) if chosen else next((r for r in rollouts if r['denominator']),rollouts[0])
        bundle = load_run(selected['id'])
        analysis = bundle['analysis']; listed = by_id[selected['id']]
        # Refuse a source drill-down if a job/review refreshed its observations
        # after the aggregate was computed, even within this single request.
        if (digest(analysis['metrics'])!=digest(listed['metrics'])
            or analysis['inspector_signature']!=listed.get('inspector_signature','heuristic')
            or analysis['harness_version']!=listed['harness_version']
            or analysis.get('reviewed_actions',0)!=listed.get('reviewed_actions',0)
            or bundle.get('ingestion') and not bundle['ingestion']['is_latest']):
            raise ComparisonChanged('Observations changed while loading evidence. Refresh the comparison.')
        matches = action_matches(analysis,metric)
        if len(matches)!=selected['numerator']:
            raise ComparisonChanged('The stored metric does not match its action evidence. Reindex and refresh the comparison.')
        events = {e['id']:e for e in bundle['run']['events']}
        observations = {a['event_id']:a for a in analysis['actions']}
        previews = []
        for match in matches[:12]:
            previews.append([{'event_id':eid,'text':events[eid]['text'][:500],'truncated':len(events[eid]['text'])>500,
                              'source_pointer':events[eid]['source_pointer'],'trajectory_id':events[eid]['trajectory_id'],
                              'purpose':observations[eid]['mode'],'basis':observations[eid]['mode_basis']} for eid in match])
        columns[side] = {'checkpoint':cp,'rollouts':rollouts,'selected_run':selected,'matches':previews,'match_count':len(matches),
                         'preview_policy':'First 12 matching observations in recorded order; previews are not a representative sample.',
                         'sequence_coverage':analysis['metrics'].get('sequence'),
                         'verified_success':bundle['run']['outcome'].get('verified_success'),
                         'termination':bundle['run']['outcome'].get('termination'),
                         'rewards':bundle['run']['outcome'].get('rewards')}
    return {'comparison_id':comparison_id,'metric':metric,'task_id':selected_task,'tasks':tasks,
            'aggregate':pair['metrics'][metric],**columns,
            'definition':'Rollout rates are averaged within each eligible task; tasks receive equal weight. Task contribution is its paired delta divided by the eligible task count. Rollouts are not assumed to be seed-matched.'}
