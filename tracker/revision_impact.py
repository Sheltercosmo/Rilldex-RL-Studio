"""Benefits and regressions beside each recorded revision, without causal credit."""
from .schema import digest
from .graph_sequence import Ordering

VERSION = 'revision-impact/2'
LIMIT = ('First comparable follow-up only; later success does not erase an earlier failure. '
         'Check results and executor completion are separate. These are recorded before/after '
         'associations, not causal effects or independent verification of the evaluator.')
MEASURES = {
    'revision_operation_gain': ('operations', 'gain', 'Revisions · operations recovered'),
    'revision_operation_regression': ('operations', 'harm', 'Revisions · operations regressed'),
    'revision_check_gain': ('checks', 'gain', 'Revisions · checks improved'),
    'revision_check_regression': ('checks', 'harm', 'Revisions · checks regressed'),
    'revision_followup_unresolved': ('followup', 'unknown', 'Revisions · unresolved follow-up'),
}
DESCRIPTIONS = {
    'operations': 'Same-work revisions with failed → completed or completed → failed first operation results / revisions with two comparable binary operation outcomes. Partial and missing results stay unknown. Completion does not establish task correctness.',
    'checks': 'Failed → passed or passed → failed first rechecks around a linked captured edit / comparable binary check pairs. Criterion/version, environment, object scope and exact before/after state bindings must match. Missing or changed evaluators remain unknown. Benefits and harms use the same denominator and can occur in one revision.',
    'followup': 'Revision episodes without a decidable first same-work operation comparison / all saved revision episodes, including declarations and plan replacements without linked implementation. Check coverage is reported separately.',
}


def description(key):
    scope, target, _ = MEASURES[key]
    if scope == 'followup':
        return DESCRIPTIONS[scope]
    change = ('failed → completed' if target == 'gain' else 'completed → failed') if scope == 'operations' else ('failed → passed' if target == 'gain' else 'passed → failed')
    population = 'comparable same-work revisions' if scope == 'operations' else 'comparable before/after check pairs'
    return f'First follow-ups that changed {change} / all {population}. ' + DESCRIPTIONS[scope].split('. ', 1)[1]


def transition(before, after, positive='completed'):
    if before not in {positive, 'failed'} or after not in {positive, 'failed'}:
        return 'unknown'
    if before != after:
        return 'gain' if after == positive else 'harm'
    return 'retained' if after == positive else 'still_failed'


def enrich(graph, visible, episodes):
    """Use only visible, source-bound evidence. Never scan later results for a pass."""
    order = Ordering(graph)
    capture = graph.get('work_state_capture') or {}
    snapshots = {s['id']: s for s in capture.get('snapshots', [])}
    checks = capture.get('checks', [])

    def ev(eid):
        return visible.get('event:' + str(eid))

    def before(a, b):
        return bool(a and b and order.before(a, b) is None)

    def event_id(uid):
        return order.event_id(visible[uid]) if uid in visible else None

    def applicable(check, snap):
        bound = snapshots.get(check.get('snapshot_id'))
        scope = check.get('required_objects', [])
        return bool(bound and snap and ev(bound['event_id']) and check.get('state_stable') is True
                    and bound['environment'] == snap['environment'] and scope
                    and all(bound['objects'].get(k) == snap['objects'].get(k) and k in snap['objects'] for k in scope))

    for episode in episodes:
        first = next(iter(episode['results']), None)
        operation = dict(before=episode['prior_outcome'], after=first['outcome'] if first else 'not_established',
                         status=transition(episode['prior_outcome'], first['outcome'] if first else None),
                         before_node_ids=[episode['previous_id']],
                         after_node_ids=[first['action_id'], *first['response_ids']] if first else [],
                         node_ids=list(dict.fromkeys([episode['previous_id'], *([first['action_id'], *first['response_ids']] if first else [])])))
        implementations = {event_id(uid) for s in episode['stages'] if s['label'] == 'Implementation' for uid in s['node_ids']}
        comparisons, seen = [], set()
        for edit in capture.get('edits', []):
            if edit['action_id'] not in implementations or not ev(edit['result_event_id']):
                continue
            start, end = snapshots[edit['before_snapshot_id']], snapshots[edit['after_snapshot_id']]
            changed = {k for k in start['objects'].keys() | end['objects'].keys() if start['objects'].get(k) != end['objects'].get(k)}
            baselines = {}
            for check in checks:
                if (not changed.intersection(check['required_objects']) or not applicable(check, start)
                        or not before(ev(check['action_id']), ev(check['result_event_id']))
                        or not before(ev(check['result_event_id']), ev(edit['action_id']))):
                    continue
                key = (check['criterion_id'], tuple(sorted(check['required_objects'])))
                previous = baselines.get(key)
                if previous is None or before(ev(previous['result_event_id']), ev(check['result_event_id'])):
                    baselines[key] = check
            for (criterion, _), baseline in baselines.items():
                candidates = [q for q in checks if q['criterion_id'] == criterion
                              and set(q['required_objects']).intersection(baseline['required_objects'])
                              and snapshots[q['snapshot_id']]['environment'] == end['environment']
                              and before(ev(edit['result_event_id']), ev(q['action_id']))]
                candidates.sort(key=lambda q: order.key(ev(q['action_id'])))
                followup = next(iter(candidates), None)
                reason = None
                if followup is None:
                    reason = 'No recorded recheck of this criterion'
                elif not before(ev(followup['action_id']), ev(followup['result_event_id'])):
                    reason = 'Recheck result has not arrived'
                elif (baseline['criterion_version'] != followup['criterion_version']
                      or set(baseline['required_objects']) != set(followup['required_objects'])):
                    reason = 'Check definition or input scope changed'
                elif not applicable(followup, end):
                    reason = 'Recheck is not bound to this change’s resulting state'
                status = 'unknown' if reason else transition(baseline['result'], followup['result'], 'passed')
                key = (criterion, baseline['criterion_version'], tuple(sorted(baseline['required_objects'])),
                       baseline['action_id'], baseline['result_event_id'],
                       followup['action_id'] if followup else None, followup['result_event_id'] if followup else None,
                       end['environment'], tuple(sorted((k,end['objects'].get(k)) for k in baseline['required_objects'])))
                if key in seen:
                    continue
                seen.add(key)
                refs = [baseline['action_id'], baseline['result_event_id'], edit['action_id'], edit['result_event_id']]
                if followup:
                    refs += [followup['action_id'], followup['result_event_id']]
                pair_id='revision-check-' + digest([graph['run_id'], key])
                comparisons.append(dict(id=pair_id, pair_id=pair_id, criterion=criterion,
                    version=baseline['criterion_version'], before=baseline['result'], after=followup['result'] if followup and ev(followup['result_event_id']) else 'unknown',
                    status=status, reason=reason, required_objects=sorted(baseline['required_objects']), changed_objects=sorted(changed.intersection(baseline['required_objects'])),
                    before_node_ids=['event:' + r for r in [baseline['action_id'], baseline['result_event_id']] if ev(r)],
                    after_node_ids=['event:' + r for r in [followup['action_id'], followup['result_event_id']] if ev(r)] if followup else [],
                    node_ids=list(dict.fromkeys('event:' + r for r in refs if ev(r)))))
        effects = {c['status'] for c in comparisons}
        episode['impact'] = dict(operation=operation, checks=comparisons,
            check_status='mixed' if {'gain', 'harm'} <= effects else 'gain' if 'gain' in effects else 'harm' if 'harm' in effects else 'unknown' if not effects or 'unknown' in effects else 'unchanged',
            checks_unknown=sum(c['status'] == 'unknown' for c in comparisons),
            check_coverage=dict(measured=sum(c['status']!='unknown' for c in comparisons),total=len(comparisons),unknown=sum(c['status']=='unknown' for c in comparisons)),
            implementation_dispatches=len(implementations - {None}),
            followup_dispatches=len({event_id(r['action_id']) for r in episode['results']} - {None}),
            later_results=episode['results'][1:], limits=LIMIT)
        episode['node_ids'] = list(dict.fromkeys(episode['node_ids'] + [n for c in comparisons for n in c['node_ids']]))
    return episodes


def project(graph):
    from .work_hierarchy import build
    hierarchy = build(graph)
    value = dict(schema=VERSION, graph_id=graph['id'], run_id=graph['run_id'], source_hash=graph['source_hash'],
                 episodes=hierarchy['revision_episodes']['episodes'], limits=[LIMIT])
    return dict(id='revision-impact-' + digest(value), **value)


def measure(output, key):
    scope, target, _ = MEASURES[key]
    cases = []
    by_pair = {}
    for episode in output['episodes']:
        rows = episode['impact']['checks'] if scope == 'checks' else [dict(episode['impact']['operation'], id=episode['id'])]
        for row in rows:
            identity=row.get('pair_id',row['id']) if scope=='checks' else row['id']
            if scope=='checks' and identity in by_pair:
                case=by_pair[identity]
                case['episode_ids'].append(episode['id'])
                case['node_ids']=list(dict.fromkeys(case['node_ids']+episode['node_ids']+row['node_ids']))
                case['edge_ids']=list(dict.fromkeys(case['edge_ids']+episode['edge_ids']))
                continue
            taken = (row['status'] == 'unknown') if scope == 'followup' else None if row['status'] == 'unknown' else row['status'] == target
            case=dict(id=identity, label=(row.get('criterion') or 'Revision') + ' · ' + row['status'].replace('_', ' '),
                taken=taken, status=row['status'], node_ids=list(dict.fromkeys(episode['node_ids'] + row['node_ids'])),
                edge_ids=list(episode['edge_ids']), revision_impact=episode, record=row)
            if output.get('schema')==VERSION:
                case['episode_ids']=[episode['id']]
            cases.append(case)
            if scope=='checks':by_pair[identity]=case
    n = sum(c['taken'] is True for c in cases)
    d = sum(c['taken'] is not None for c in cases)
    check_pairs={r.get('pair_id',r['id']) for e in output['episodes'] for r in e['impact']['checks']}
    return dict(value=n/d if d else None, numerator=n, denominator=d, opportunities=len(cases), unknown=len(cases)-d,
                cases=cases, coverage=dict(episodes=len(output['episodes']), check_pairs=len(check_pairs)),
                reason=None if d else 'No comparable revision follow-up yet. Inspect linked changes and capture before/after check states.')
