"""Project selected target links and their recorded context into readable paths.

No new semantic inference occurs here. A source association is not causation,
an assessment is an agent claim, and a plan-stage link is not completion.
"""
from .schema import InputError

VERSION='work-path-projection/1'


def build(run,document):
    result={'schema':VERSION,'available':bool(document.get('action_target_review')),'paths':[],
      'limits':'Paths group selected same-work identities. Context may appear in several paths, but each unit appears once within a path. Shared context is not extra activity. Source order is not a causal chain. Plan stages remain intended work; assessments are unvalidated agent interpretations.'}
    if not result['available']:return result
    units={u['id']:u for u in document['units']};events={e['id']:e for e in run['events']}
    def order(uid):
        u=units[uid];return (events[u['source']['event_id']]['index'],u['source']['start'],u['source']['end'])
    actions={uid for uid,u in units.items() if u['kind']=='action'}
    previous={}
    for edge in document['relations']:
        if edge['type']!='same_action_target':continue
        a,b=edge['from'],edge['to']
        if a not in actions or b not in actions:raise InputError('Work identity must connect dispatch units')
        if (units[a]['actor']!=units[b]['actor'] or units[a]['trajectory_id']!=units[b]['trajectory_id'] or order(b)>=order(a)):
            raise InputError('Work identity must point to an earlier action by the same actor in the same trajectory')
        if a in previous and previous[a]!=b:raise InputError('Conflicting work identities')
        previous[a]=b
    groups={}
    for uid in sorted(actions,key=order):
        root=uid
        while root in previous:root=previous[root]
        groups.setdefault(root,[]).append(uid)
    relations=document['relations'];reviews={r['action_unit_id']:r for r in document['action_target_review']}
    for root,members in groups.items():
        roles={uid:{'dispatch'} for uid in members};member_set=set(members)
        def add(uid,role):
            if uid not in units:raise InputError('Path relation references a missing unit')
            roles.setdefault(uid,set()).add(role)
        for edge in relations:
            if edge['type']=='feedback_for' and edge['to'] in member_set:add(edge['from'],'recorded_response')
            elif edge['type']=='recorded_with' and edge['to'] in member_set:add(edge['from'],'recorded_expression')
        response_ids={uid for uid,rs in roles.items() if 'recorded_response' in rs}
        for edge in relations:
            if edge['type']=='assesses' and edge['to'] in response_ids:add(edge['from'],'response_assessment')
        stages={}
        for edge in relations:
            if edge['from'] not in member_set or not edge.get('plan_step_id'):continue
            key=(edge['to'],edge['plan_step_id']);plan=units.get(edge['to'])
            if not plan or not any(s['id']==edge['plan_step_id'] for s in plan.get('plan_structure',{}).get('steps',[])):
                raise InputError('Path plan stage is not an established local stage')
            stage=stages.setdefault(key,{'plan_unit_id':edge['to'],'step_id':edge['plan_step_id'],
                'text':edge['plan_step_text'],'target':edge['plan_step_target'],'action_roles':[]})
            stage['action_roles'].append({'unit_id':edge['from'],'relation':edge['type']})
        sequence=[{'unit_id':uid,'roles':sorted(roles[uid])} for uid in sorted(roles,key=order)]
        seen=set(roles);plans={s['plan_unit_id'] for s in stages.values()}
        path={'id':'path-'+root,'target':units[root]['content']['target']['text'],
          'dispatch_unit_ids':members,'timeline':sequence,'plan_stages':list(stages.values()),
          'related_unit_ids':sorted(seen|plans,key=order),
          'counts':{'dispatches':len(members),'source_responses':len(response_ids),
                    'prose_contributions':sum(units[uid]['kind']=='semantic' for uid in seen),
                    'unique_timeline_units':len(sequence)},
          'identity_selections':[reviews[uid] for uid in members if uid in reviews],
          'disputed_identity':any(n.get('kind')=='relation_review' and
              (not n.get('relation_ref') or n['relation_ref'].get('type')=='same_action_target') and
              set(n.get('unit_ids',[]))&member_set for n in document['review_notes'])}
        result['paths'].append(path)
    covered=[uid for p in result['paths'] for uid in p['dispatch_unit_ids']]
    if len(covered)!=len(actions) or set(covered)!=actions:raise InputError('Path dispatch coverage differs')
    result['dispatch_coverage']={'recorded_selected_actions':len(actions),'actions_in_paths':len(covered),'each_action_once':True}
    return result
