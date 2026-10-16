"""Source-order overview of already selected immediate-work identities.

This projection has no semantic classifier. A repeated assignment needs a
positive identity link; missing links never prove novelty or a target switch.
"""
from collections import Counter
from .schema import InputError,digest

VERSION='work-history-projection/2'
LIMITS=('This overview groups dispatched operations using saved immediate-target identities. '
        'Missing identity links are not evidence of new work. Recurrence is not a failed retry, '
        'exploration, exploitation, causal response, progress or successful completion. '
        'Positions are source order within one actor and trajectory, not elapsed time. '
        'One operation counts once even if it relates to several requests, plans or checks.')
OPEN_STATUSES={'unresolved','multiple_distinct_targets','needs_target_candidate_retrieval'}


def build(run,document):
    paths=document.get('work_paths',{})
    result={'schema':VERSION,'available':bool(paths.get('available')),'streams':[],
            'recurrences':[],'limits':LIMITS}
    if not result['available']:
        result['reason']='Selected action-target identities have not been projected.'
        return result
    units={u['id']:u for u in document['units']};events={e['id']:e for e in run['events']}
    def order(uid):
        u=units[uid];ref=u['source']
        return events[ref['event_id']]['index'],ref['start'],ref['end']
    actions=sorted((u['id'] for u in units.values() if u['kind']=='action'),key=order)
    reviews={r['action_unit_id']:r for r in document.get('action_target_review',[])}
    identities={}
    for edge in document['relations']:
        if edge['type']!='same_action_target':continue
        current,prior=edge['from'],edge['to']
        if current not in actions or prior not in actions:raise InputError('History identity must connect actions')
        if (order(prior)>=order(current) or
            (units[current]['actor'],units[current]['trajectory_id'])!=(units[prior]['actor'],units[prior]['trajectory_id'])):
            raise InputError('History identity must connect earlier work in the same actor trajectory')
        if current in identities:raise InputError('Duplicate history identity')
        identities[current]=edge
    group_for={};groups={}
    for path in paths['paths']:
        if path['id'] in groups:raise InputError('Duplicate history group')
        members=path['dispatch_unit_ids']
        if not members or members!=sorted(members,key=order):raise InputError('History group must be ordered')
        for uid in members:
            if uid not in actions or uid in group_for:raise InputError('Each history action must belong to one group')
            group_for[uid]=path['id']
        groups[path['id']]=path
    if set(group_for)!=set(actions):raise InputError('History groups do not cover selected actions')
    for uid in actions:
        # The grouping must be exactly supported, not merely a supplied label.
        root=uid
        while root in identities:root=identities[root]['to']
        if groups[group_for[uid]]['dispatch_unit_ids'][0]!=root:
            raise InputError('History group differs from selected identity closure')
    lanes={}
    for uid in actions:
        u=units[uid];lanes.setdefault((u['actor'],u['trajectory_id']),[]).append(uid)
    def support(uid):
        chain=[]
        while uid in identities:
            edge=identities[uid]
            chain.append({'from':edge['from'],'to':edge['to'],'type':edge['type'],
                          **{k:edge[k] for k in ('request','pair_request') if k in edge}})
            uid=edge['to']
        return chain
    for (actor,trajectory),members in lanes.items():
        lane={'actor':actor,'trajectory_id':trajectory,'action_unit_ids':members,'groups':[],'segments':[],
              'identity_status_counts':dict(Counter(reviews.get(uid,{}).get('status','not_inspected') for uid in members))}
        lane['id']='stream-'+digest([actor,trajectory])[:20]
        represented_events={units[uid]['source']['event_id'] for uid in members}
        first,last=order(members[0])[0],order(members[-1])[0]
        omitted=[e for e in run['events'] if e.get('kind')=='action' and
                 e.get('actor')==actor and e.get('trajectory_id')==trajectory and
                 first<=e['index']<=last and e['id'] not in represented_events]
        axis=[{'unit_id':uid,'event_id':units[uid]['source']['event_id'],'order':order(uid)} for uid in members]
        axis.extend({'unit_id':None,'event_id':e['id'],'order':(e['index'],0,len(e.get('text','')))} for e in omitted)
        axis.sort(key=lambda item:item['order'])
        lane['positions']=[{k:v for k,v in item.items() if k!='order'} for item in axis]
        lane['unrepresented_action_event_ids']=[e['id'] for e in omitted]
        lane['position_count']=len(axis)
        positions={item['unit_id']:i for i,item in enumerate(axis) if item['unit_id'] is not None};previous={};group_rows={}
        for uid in members:
            group_id=group_for[uid];path=groups[group_id];position=positions[uid]
            group=group_rows.setdefault(group_id,{'id':group_id,'target':path['target'],
                'disputed_identity':path.get('disputed_identity',False),'occurrences':[],
                'consecutive_recurrences':0,'spaced_recurrences':0})
            occurrence={'unit_id':uid,'position':position+1,'event_id':units[uid]['source']['event_id'],
                'identity_status':reviews.get(uid,{}).get('status','not_inspected')}
            group['occurrences'].append(occurrence)
            if (not lane['segments'] or lane['segments'][-1]['group_id']!=group_id or
                lane['segments'][-1]['end_position']!=position):
                lane['segments'].append({'group_id':group_id,'action_unit_ids':[],'start_position':position+1})
            lane['segments'][-1]['action_unit_ids'].append(uid)
            lane['segments'][-1]['end_position']=position+1
            if group_id in previous:
                prior=previous[group_id];between=axis[positions[prior]+1:position]
                intervening=[p['unit_id'] for p in between if p['unit_id'] is not None]
                unrepresented=[p['event_id'] for p in between if p['unit_id'] is None]
                if uid not in identities:raise InputError('Repeated assignment needs a selected identity')
                support_edges=list({digest(e):e for e in [*support(prior),*support(uid)]}.values())
                recurrence={'unit_id':uid,'previous_group_unit_id':prior,
                    'selected_prior_unit_id':identities[uid]['to'],'group_id':group_id,'stream_id':lane['id'],
                    'intervening_action_unit_ids':intervening,'supporting_identity_relations':support_edges,
                    'intervening_unrepresented_action_event_ids':unrepresented,
                    'relation_basis':'selected identity closure; previous group occurrence chosen by source order',
                    'pattern':'with_intervening_operations' if between else 'consecutive_operations'}
                from .recurrence_context import build as build_context
                recurrence['context']=build_context(run,document,prior,uid)
                result['recurrences'].append(recurrence)
                occurrence['recurrence_index']=len(result['recurrences'])-1
                group['spaced_recurrences' if between else 'consecutive_recurrences']+=1
            previous[group_id]=uid
        lane['groups']=list(group_rows.values())
        lane['counts']={'operations':len(members),'selected_target_groups':len(group_rows),
            'recurring_groups':sum(len(g['occurrences'])>1 for g in lane['groups']),
            'recurring_assignments':sum(len(g['occurrences'])-1 for g in lane['groups']),
            'consecutive_recurrences':sum(g['consecutive_recurrences'] for g in lane['groups']),
            'spaced_recurrences':sum(g['spaced_recurrences'] for g in lane['groups']),
            'unresolved_or_uninspected':sum(reviews.get(uid,{}).get('status','not_inspected') in OPEN_STATUSES|{'not_inspected'} for uid in members),
            'unrepresented_operations':len(omitted)}
        result['streams'].append(lane)
    result['counts']={key:sum(s['counts'][key] for s in result['streams']) for key in
        ('operations','selected_target_groups','recurring_groups','recurring_assignments',
         'consecutive_recurrences','spaced_recurrences','unresolved_or_uninspected','unrepresented_operations')}
    result['dependencies']={'source_hash':digest(run),'work_paths_hash':digest(paths),
        'identity_relations_hash':digest(list(identities.values()))}
    result['operation_grain']='Selected dispatch unit, deduplicated by unit ID; not a check, relation or response count.'
    return result
