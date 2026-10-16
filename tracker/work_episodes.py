"""Prefix-grounded work episodes above saved semantic units and relationships.

No inferred novelty, goal deviation or method change from command equality.
Each recurrence is a positive identity witness; missing observations remain
unresolved. Method comparison is independent of target correspondence.
"""
from collections import Counter,defaultdict
from .schema import digest

VERSION='work-episodes/3'
LABELS={'continued':'Consecutive same-work recurrence','returned':'Return after intervening operations',
        'interrupted':'Same-work recurrence across an observation gap'}
METHODS={'same_procedure':'Same dispatched procedure','reconfigured_procedure':'Reconfigured procedure',
         'different_procedure':'Different procedure','unresolved':'Method unresolved'}


def project(graph):
    if ((graph.get('semantic_context') or {}).get('procedure_reviews') or
            any(m.get('basis')=='procedure-review/1' for m in
                (graph.get('semantic_context') or {}).get('work_observations',{}).get('method_observations',[]))):
        from .procedure_reviews import checked
        checked(graph)
    nodes={n['id']:n for n in graph['nodes']};events={n['properties']['id']:n['properties'] for n in nodes.values() if n['kind']=='event'}
    units={n['id']:n['properties'] for n in nodes.values() if n['kind']=='unit'}
    edges=graph['edges'];issues=[]
    observations=(graph.get('semantic_context') or {}).get('work_observations',{})
    reviews={r['action_unit_id']:r for r in observations.get('identity_reviews',[])}
    methods=observations.get('method_observations',[])
    def source(uid):return units[uid].get('source',{})
    def position(uid):
        s=source(uid);return (events[s['event_id']]['index'],s['start'],s['end'])
    def valid(uid):
        s=source(uid);e=events.get(s.get('event_id'))
        return bool(e and not e.get('copied_context') and type(s.get('start')) is int and type(s.get('end')) is int and 0<=s['start']<s['end']<=len(e['text']) and e['text'][s['start']:s['end']]==s.get('text'))
    valid_units={uid for uid in units if valid(uid)}
    actions={uid for uid in valid_units if units[uid].get('kind')=='action' and units[uid].get('actor')=='agent'}
    def lane(uid):
        e=events[source(uid)['event_id']];return (e.get('actor'),e['trajectory_id'])
    def earlier(a,b):
        pa,pb=position(a),position(b)
        return lane(a)[1]==lane(b)[1] and (pa[0]<pb[0] or pa[0]==pb[0] and pa[2]<=pb[1])
    def available(edge,at):
        p=edge.get('properties',edge);refs=[p.get('cutoff')]+p.get('evidence',[])+p.get('context_evidence',[])
        refs += (p.get('inspector_context') or {}).get('source_ranges',[])
        for ref in refs:
            if not isinstance(ref,dict) or 'event_id' not in ref:continue
            event=events.get(ref['event_id']);start=ref.get('start',0) if ref is p.get('cutoff') else ref.get('start');end=ref.get('end')
            if not event or event.get('copied_context') or event['trajectory_id']!=lane(at)[1]:return False
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(event['text']):return False
            if 'text' in ref and event['text'][start:end]!=ref['text']:return False
            if (event['index'],end)>(position(at)[0],position(at)[2]):return False
        return True
    previous={};bad=set()
    for edge in edges:
        if edge['type']!='same_action_target':continue
        a,b=edge['source'],edge['target']
        if a not in actions or b not in actions or not earlier(b,a) or not available(edge,a):
            issues.append({'edge_id':edge['id'],'reason':'Identity endpoints/order/prefix are unsupported'});bad.add(a);continue
        if a in previous and previous[a]['target']!=b:
            issues.append({'edge_id':edge['id'],'reason':'Conflicting prior identities'});bad.add(a);continue
        previous[a]=edge
    # An identity dispute at a later dispatch must not relabel earlier episodes.
    disputed=set()
    for m in methods:
        a,b=m.get('current_unit_id'),m.get('previous_unit_id')
        if a not in actions or b not in actions or not earlier(b,a) or not available(m,a):continue
        if m.get('comparison')=='different_work' or m.get('work_instance')=='different_work_instance' or m.get('upstream_identity_disputed'):
            disputed.add(a)
    roots={};chains={}
    for uid in sorted(actions,key=position):
        e=previous.get(uid)
        if uid in bad or uid in disputed:roots[uid]=None;chains[uid]=[]
        elif e:
            roots[uid]=roots.get(e['target']);chains[uid]=[e['id'],*chains.get(e['target'],[])]
        else:roots[uid]=uid;chains[uid]=[]
    actions_at=defaultdict(list)
    for uid in actions:actions_at[source(uid)['event_id']].append(uid)
    batches=Counter((e['trajectory_id'],e.get('parent_id')) for e in events.values() if e['kind']=='action' and e.get('parent_id'))
    streams=defaultdict(list)
    # Every native action occupies the axis, including omitted/ambiguous units.
    for e in sorted(events.values(),key=lambda e:e['index']):
        if e['kind']!='action' or e.get('actor')!='agent' or e.get('copied_context'):continue
        candidates=actions_at[e['id']];uid=candidates[0] if len(candidates)==1 else None
        ambiguous=e.get('batch_size',0)>1 or batches[(e['trajectory_id'],e.get('parent_id'))]>1
        if uid and (source(uid)['start']!=0 or source(uid)['end']!=len(e['text'])):uid=None
        streams[(e['actor'],e['trajectory_id'])].append({'unit_id':uid,'event_id':e['id'],
            'group_id':roots.get(uid) if not ambiguous else None,'order_known':not ambiguous})
    def content(uid):
        c=units[uid].get('content',{})
        for key in ('target','local_target','summary','situation'):
            if isinstance(c.get(key),dict) and c[key].get('text'):return c[key]['text']
        return source(uid).get('text','')
    def card(uid,role):
        label=content(uid)
        if units[uid].get('kind')=='feedback':
            label=units[uid].get('content',{}).get('recorded_response',{}).get('text') or source(uid)['text']
        return {'unit_id':uid,'event_id':source(uid)['event_id'],'role':role,'activity':units[uid].get('activity'),
                'label':label,'text':source(uid)['text'],'source_pointer':source(uid).get('source_pointer')}
    def stage_edges(uid):
        result=[]
        for e in edges:
            p=e['properties'];plan=units.get(e['target']);sid=p.get('plan_step_id')
            if e['source']!=uid or e['type'] not in {'attempts_plan_step','prepares_plan_step','checks_plan_step'} or e['target'] not in valid_units or not earlier(e['target'],uid) or not available(e,uid):continue
            stage=next((s for s in (plan.get('plan_structure') or {}).get('steps',[]) if s['id']==sid),None)
            if stage:result.append({'plan_unit_id':e['target'],'step_id':sid,'text':stage['text'],'target':stage.get('target'), 'role':e['type'],'edge_id':e['id']})
        return result
    episodes=[];paths=[]
    for (actor,trajectory),positions in sorted(streams.items()):
        last={};groups={}
        for index,p in enumerate(positions):
            uid=p['unit_id'];root=p['group_id'];p['identity_status']=reviews.get(uid,{}).get('status','not_recorded')
            p['target']=content(uid) if uid else None;p['plan_stages']=stage_edges(uid) if uid else []
            p['category']='first_or_unresolved';p['episode_id']=None
            if root is None:continue
            group=groups.setdefault(root,{'id':root,'target':content(root),'unit_ids':[]});group['unit_ids'].append(uid)
            if root in last:
                earlier_index=last[root];prior=positions[earlier_index]['unit_id'];between=positions[earlier_index+1:index]
                gap=any(v['unit_id'] is None or v['group_id'] is None or not v['order_known'] for v in between)
                category='interrupted' if gap else 'returned' if between else 'continued'
                p['category']=category
                responses=[e for e in edges if e['type']=='feedback_for' and e['target']==prior and e['source'] in valid_units and earlier(prior,e['source']) and earlier(e['source'],uid) and available(e,uid)]
                response_ids={e['source'] for e in responses}
                assessments=[e for e in edges if e['type']=='assesses' and e['target'] in response_ids and e['source'] in valid_units and earlier(e['target'],e['source']) and earlier(e['source'],uid) and available(e,uid)]
                adjustments=[]
                for e in edges:
                    p0=e['properties'];via=p0.get('via_action')
                    # This relation points to the earlier attempt; retry_unit_id
                    # identifies the recurrence. The correction may be the retry
                    # itself, or an intervening prerequisite operation.
                    if (e['type']=='adjustment_before_retry' and e['target']==prior and p0.get('retry_unit_id')==uid
                        and e['source'] in valid_units and via in actions and earlier(prior,e['source'])
                        and earlier(e['source'],via) and (via==uid or earlier(via,uid)) and available(e,uid)):
                        adjustments.append({'declaration':e['source'],'action':via,'work':p0.get('work_text'),
                            'scope':p0.get('scope'),'timing':'at_recurrence' if via==uid else 'before_recurrence','edge_id':e['id']})
                matches=[m for m in methods if m.get('current_unit_id')==uid and m.get('previous_unit_id')==prior and available(m,uid)]
                method=matches[0] if len(matches)==1 else None
                member_ids={prior,uid,*[v['unit_id'] for v in between if v['unit_id']],*response_ids,*[e['source'] for e in assessments]}
                for a in adjustments:member_ids.update((a['declaration'],a['action']))
                roles={prior:'Earlier attempt',uid:'Current recurrence'}
                roles.update({r:'Returned feedback' for r in response_ids});roles.update({e['source']:'Assessment of earlier feedback' for e in assessments})
                for a in adjustments:
                    roles[a['declaration']]='Stated adjustment'
                    roles[a['action']]='Current recurrence · adjustment attempt' if a['action']==uid else 'Adjustment attempt'
                cards=[card(i,roles.get(i,'Intervening operation')) for i in sorted(member_ids,key=position)]
                evidence_ids=list(dict.fromkeys([*chains[uid],*chains[prior],*[e['id'] for e in responses+assessments],*[a['edge_id'] for a in adjustments]]))
                connections=[{k:e[k] for k in ('id','source','target','type')} for e in edges
                             if e['id'] in evidence_ids and e['source'] in member_ids and e['target'] in member_ids]
                value={'graph_id':graph['id'],'run_id':graph['run_id'],'actor':actor,'trajectory_id':trajectory,
                    'category':category,'target':group['target'],'previous_unit_id':prior,'current_unit_id':uid,'group_id':root,
                    'start_position':earlier_index+1,'end_position':index+1,'intervening':between,'cards':cards,
                    'previous_plan_stages':stage_edges(prior),'current_plan_stages':stage_edges(uid),
                    'feedback_unit_ids':sorted(response_ids,key=position),
                    'assessment_unit_ids':sorted({e['source'] for e in assessments},key=position),'adjustments':adjustments,
                    'method':{k:method.get(k) for k in ('comparison','work_instance','request','work_request','cutoff')} if method else None,
                    'edge_ids':evidence_ids,'connections':connections,
                    'interpretation':'Recorded recurrence; failure, progress, deviation and exploration are separate questions.'}
                if method and method.get('basis')=='procedure-review/1':
                    value['method'].update(basis=method['basis'],review=method['review'])
                eid='work-episode-'+digest(value);p['episode_id']=eid;episodes.append({'id':eid,**value})
            last[root]=index
        paths.append({'actor':actor,'trajectory_id':trajectory,'positions':positions,'groups':list(groups.values())})
    positions=[v for p in paths for v in p['positions']]
    counts={k:sum(e['category']==k for e in episodes) for k in LABELS}
    counts.update(recorded_actions=len(positions),represented_actions=sum(bool(v['unit_id']) for v in positions),
        identity_reviewed=sum(v['identity_status']!='not_recorded' for v in positions),
        first_or_unresolved=sum(v['category']=='first_or_unresolved' for v in positions),
        recurrences_with_assessment=sum(bool(e['assessment_unit_ids']) for e in episodes),
        recurrences_with_feedback=sum(bool(e['feedback_unit_ids']) for e in episodes),
        recurrences_with_adjustment=sum(bool(e['adjustments']) for e in episodes),
        method_compared=sum(bool(e['method']) for e in episodes))
    value={'schema':VERSION,'run_id':graph['run_id'],'graph_id':graph['id'],'source_hash':graph['source_hash'],
        'observer':graph['observer'],'metadata':graph.get('metadata',{}),'paths':paths,'episodes':episodes,'counts':counts,'issues':issues,
        'disputed_identity_units':sorted(disputed),'labels':LABELS,'method_labels':METHODS,
        'limits':['Immediate work targets are not overarching objectives or approaches.',
                  'No earlier identity link means first or unresolved, not new exploration.',
                  'No assessment/adjustment link means not established, not an observed absence.',
                  'Method comparisons apply to the exact inspected pair; they are not transitive.',
                  'Counts describe recorded witnesses and retain annotation coverage. They are not validated behavior prevalence.']}
    return {'id':'work-episodes-'+digest(value),**value}


def compare(records,focus,reference):
    groups={}
    for label,ids in [('focus',focus),('reference',reference)]:
        selected=[r for r in records if r['run_id'] in ids];counts=Counter()
        for r in selected:counts.update(r['counts'])
        groups[label]={'rollouts':len(ids),'graphs':len(selected),'counts':dict(counts),
                      'episode_ids':[e['id'] for r in selected for e in r['episodes']]}
    return {'schema':VERSION,'groups':groups,'records':records,'labels':LABELS,
            'definition':'Recorded work-identity witnesses, with coverage. No missing relation is counted as novelty, deviation, or failed recovery.'}
