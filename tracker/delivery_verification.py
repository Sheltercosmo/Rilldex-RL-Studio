"""Verification at a delivery boundary, preserving conflicting captured results.

Agreement is about recorded criterion/scope/input identities. It neither proves
those captures complete nor identifies the cause of disagreeing outcomes.
"""
from collections import Counter, defaultdict
from copy import deepcopy


def value(status):
    return True if status=='applicable_pass' else False if status in {'checked_failure','changed_inputs'} else None


def inspect(delivery, requirement, checks, snapshots, events, applicability):
    def position(eid):return events[eid]['index'] if eid in events else -1
    def lane(eid):
        e=events[eid];return e['trajectory_id'],e.get('context_id')
    cutoff=position(delivery['event_id']); target=snapshots[delivery['snapshot_id']]
    history=[]
    for check in sorted(checks,key=lambda q:(position(q['action_id']),q['action_id'])):
        if (check['criterion_id']!=requirement['criterion_id'] or
                check.get('criterion_version')!=requirement['criterion_version'] or
                not 0<=position(check['action_id'])<cutoff or lane(check['action_id'])!=lane(delivery['event_id'])):continue
        result=events.get(check.get('result_event_id')); action=events[check['action_id']]
        available=result is not None and 0<=result['index']<cutoff
        issues=[]
        if not available:issues.append('result_not_available_at_delivery')
        elif result['index']<=action['index']:issues.append('result_not_after_dispatch')
        elif lane(result['id'])!=lane(action['id']):issues.append('result_context_differs')
        if any(e.get('order_known') is False for e in [action,events[delivery['event_id']],*([result] if available else [])]):issues.append('source_order_unresolved')
        if any(e.get('agent_visibility')=='not_established' for e in [action,*([result] if available else [])]):issues.append('agent_visibility_unestablished')
        state=applicability(check,target) if not issues else 'unknown'
        row=dict(action_id=check['action_id'],result_event_id=result['id'] if available else None,
            result=check['result'] if available else 'unknown',snapshot_id=check.get('snapshot_id'),
            required_objects=sorted(check.get('required_objects',[])),applicability=state,issues=issues,
            availability='recorded_before_delivery' if available else 'pending_at_delivery')
        history.append(row)

    applicable=[r for r in history if r['applicability']=='matching_inputs']
    groups=defaultdict(list)
    for row in applicable:groups[tuple(row['required_objects'])].append(row)
    conflicts=[]
    for scope,rows in sorted(groups.items()):
        if {'passed','failed'}<={r['result'] for r in rows}:
            conflicts.append(dict(required_objects=list(scope),environment=target['environment'],
                object_versions={k:target['objects'][k] for k in scope},
                action_ids=[r['action_id'] for r in rows if r['result'] in {'passed','failed'}],
                result_event_ids=[r['result_event_id'] for r in rows if r['result'] in {'passed','failed'}]))
    completed=[r for r in history if r['availability']=='recorded_before_delivery']
    selected=(applicable or completed or [None])[-1]
    if conflicts:status='conflicting_check_results';selected=None
    elif len(groups)>1:status='inconsistent_check_scope';selected=None
    elif selected and selected['applicability']=='matching_inputs':
        status={'passed':'applicable_pass','failed':'checked_failure','unknown':'unresolved_check'}[selected['result']]
    elif selected and selected['applicability']=='changed_inputs':status='changed_inputs'
    else:status='unknown'
    coverage=dict(checks=len(history),applicable=len(applicable),pending=sum(r['availability']=='pending_at_delivery' for r in history),
        unknown_inputs=sum(r['applicability']=='unknown' for r in history),applicable_results=dict(Counter(r['result'] for r in applicable)))
    event_ids=list(dict.fromkeys([eid for r in history for eid in (r['action_id'],r['result_event_id']) if eid]+[delivery['event_id']]))
    return dict(**deepcopy(delivery),requirement=deepcopy(requirement),status=status,
        check_action_id=selected['action_id'] if selected else None,
        check_history=history,conflicts=conflicts,coverage=coverage,event_ids=event_ids,
        interpretation='Same captured inputs can hide unrecorded dependencies or nondeterminism. Disagreement is not proof of evaluator error, model failure or reward hacking.')
