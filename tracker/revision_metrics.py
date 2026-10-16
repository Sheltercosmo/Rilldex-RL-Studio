"""Conditional operation outcomes after source-bound, enacted declarations.

This joins saved relations and outcomes. No new model call or confidence gate.
"""
from .operation_outcomes import action_outcomes
from .attempt_revision import change_kinds

VERSION='enacted-attempt-change/1'
DEFINITIONS={
    'enacted_revision_completion_fraction':('Completed retries after stated-change attempts · experimental',
        'Completed operations / retries with known terminal outcomes after observed failure, an explicit related change, and a matching recorded action. Uses consecutive selected same-work attempts. The change and its implementing action must follow failure feedback and precede or implement the retry. Prerequisite repairs and procedure changes both qualify. Operation completion is not verified task recovery or a causal effect.'),
    'enacted_revision_unknown_fraction':('Unknown results after stated-change attempts',
        'Retries without a complete terminal outcome / eligible retries after observed failure and a source-linked expressed and enacted change. Unknowns are excluded from the completion fraction, not counted as failures.'),
}


def inspect(run,document):
    observed=document.get('attempt_revisions')
    if not observed or not document.get('operation_outcomes'):return None
    events={e['id']:e for e in run['events']};units={u['id']:u for u in document['units']}
    outcomes=action_outcomes(run,document['operation_outcomes']);episodes=[];excluded=[];seen=set()
    def order(u):return events[u['source']['event_id']]['index'],u['source']['start']
    for row in observed['observations']:
        a,b=units[row['previous_unit_id']],units[row['current_unit_id']]
        old,new=outcomes.get(a['source']['event_id'],{}),outcomes.get(b['source']['event_id'],{})
        if old.get('outcome')!='failed':continue
        key=(a['id'],b['id'])
        if key in seen:continue
        seen.add(key)
        responses=[events[o['response_event_id']] for o in old.get('observations',[])]
        eligible=(row['status']=='inspected' and row.get('work_instance')=='same_work_instance' and
            a['kind']==b['kind']=='action' and a['actor']==b['actor']=='agent' and
            a['trajectory_id']==b['trajectory_id'] and responses and
            all(e['trajectory_id']==b['trajectory_id'] and e['index']<order(b)[0] for e in responses))
        if not eligible:
            excluded.append({'pair':list(key),'reason':'Failure, source ordering or same-work inspection is incomplete'});continue
        feedback_end=max((e['index'],len(e.get('text',''))) for e in responses);matches=[]
        for change in row['declarations']:
            statement=units[change['unit_id']]
            if not (feedback_end<order(statement)<order(b)):continue
            for kind in change_kinds(change['selection']):
                selected=change.get('executions',{}).get(kind,{})
                action=units.get(selected.get('selection'))
                if not action or action['kind']!='action' or action['actor']!='agent' or action['trajectory_id']!=b['trajectory_id']:continue
                if not (feedback_end<order(action)<=order(b)):continue
                matches.append({'declaration_unit_id':statement['id'],'execution_unit_id':action['id'],
                    'change_kind':kind,'declaration_request_hash':change['request_hash'],'execution_request_hash':selected['request_hash']})
        if not matches:
            excluded.append({'pair':list(key),'reason':'No selected declaration and enactment after observed failure; absence is not a behavioral negative'});continue
        evidence=list(dict.fromkeys([a['id'],b['id'],*[e['id'] for e in responses],
            *[i for m in matches for i in (m['declaration_unit_id'],m['execution_unit_id'])],
            *[o['response_event_id'] for o in new.get('observations',[])]]))
        episodes.append({'failed_unit_id':a['id'],'retry_unit_id':b['id'],
            'failed_event_id':a['source']['event_id'],'retry_event_id':b['source']['event_id'],
            'changes':matches,'retry_outcome':new.get('outcome','not_established'),'evidence_ids':evidence,
            'complete_candidate_window':row['complete_candidate_window']})
    known=[e for e in episodes if e['retry_outcome'] in {'completed','failed','partial'}]
    def ratio(n,rows):return {'numerator':n,'denominator':len(rows),'evidence':list(dict.fromkeys(i for e in rows for i in e['evidence_ids']))}
    return {'schema':VERSION,'episodes':episodes,'excluded_failed_pairs':excluded,'metrics':{
        'enacted_revision_completion_fraction':ratio(sum(e['retry_outcome']=='completed' for e in known),known),
        'enacted_revision_unknown_fraction':ratio(len(episodes)-len(known),episodes)},
        'scope':'A failed operation, a stated related change, a matching dispatch and the next selected same-work attempt. This records a temporal evidence chain, not verified task recovery or the effect of the change.'}
