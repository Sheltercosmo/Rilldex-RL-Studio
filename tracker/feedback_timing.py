"""Timing of supported saved assessments, measured in recorded dispatches.

The earliest eligible saved link is not necessarily the agent's first actual
assessment. Missing links never establish absence, neglect or delayed learning.
"""
from collections import Counter, defaultdict

from .schema import digest
from .work_order import Evidence

VERSION = 'feedback-assessment-timing/2'
LIMITS = ('One visible native-bound text response per opportunity. Measures whether at least one same-recipient '
    'dispatch is recorded between that response and its earliest eligible saved assessment. '
    'The fraction is conditional on supported links and comparable order, not all feedback or model uptake. '
    'Missing links, ambiguous recipients/context, copied records and incomplete parallel batches remain unknown. '
    'Counts concern recorded dispatches, not execution latency or token time. A later saved reference does not '
    'establish the first actual assessment, ignored feedback, incorrect behavior or causal use.')


def project(graph):
    from . import relation_reviews,map_relationships
    reviews = relation_reviews.checked(graph)
    rejected={r['edge_id']:r for r in map_relationships.inspect(graph)['relationships'] if r['status']=='incompatible'}
    events = {n['properties']['id']:n['properties'] for n in graph['nodes'] if n['kind']=='event'}
    units = {n['id']:n['properties'] for n in graph['nodes'] if n['kind']=='unit'}
    order = Evidence(events)

    def visible(e):
        return not e.get('copied_context') and e.get('agent_visibility')!='not_established'

    def valid(u):
        s=u.get('source',{});e=events.get(s.get('event_id'))
        return bool(e and visible(e) and u.get('actor')==e['actor'] and u.get('trajectory_id')==e['trajectory_id']
            and type(s.get('start')) is int and type(s.get('end')) is int
            and 0<=s['start']<s['end']<=len(e['text']) and e['text'][s['start']:s['end']]==s.get('text'))

    bound=defaultdict(set);binding_edges=defaultdict(list)
    for edge in graph['edges']:
        if edge['type']!='response_to' or not edge['source'].startswith('event:') or not edge['target'].startswith('event:'):continue
        rid,aid=edge['source'][6:],edge['target'][6:];r,a=events.get(rid),events.get(aid)
        if (r and a and r['kind']=='feedback' and r['actor']=='environment' and a['kind']=='action' and a['actor'] not in {'user','system','developer','environment'}
            and r['trajectory_id']==a['trajectory_id'] and r['index']>a['index'] and visible(r) and visible(a) and r['text'].strip()):
            bound[rid].add(aid);binding_edges[rid].append(edge['id'])
    feedback=defaultdict(set);feedback_edges=defaultdict(list)
    for e in graph['edges']:
        f,a=units.get(e['source']),units.get(e['target'])
        if e['type']=='feedback_for' and f and a and valid(f) and valid(a) and f.get('kind')=='feedback' and a.get('kind')=='action':
            rid,aid=f['source']['event_id'],a['source']['event_id']
            if aid in bound.get(rid,set()):feedback[rid].add(e['source']);feedback_edges[(rid,e['source'])].append(e['id'])
    by_feedback={fid:rid for rid,fids in feedback.items() for fid in fids}
    candidates=defaultdict(list);excluded=[]
    for edge in graph['edges']:
        if edge['type']!='assesses' or edge['target'] not in by_feedback:continue
        rid=by_feedback[edge['target']];r=events[rid];u=units.get(edge['source']);p=edge['properties']
        if edge['id'] in rejected:
            excluded.append(dict(edge_id=edge['id'],response_event_id=rid,reason=rejected[edge['id']]['reason']));continue
        reason=None
        if not u or not valid(u) or u.get('kind')!='semantic' or u.get('status')!='selected':reason='assessment_unit_unavailable'
        else:
            s=u['source'];e=events[s['event_id']];actors={events[a]['actor'] for a in bound[rid]}
            reviewed=reviews.get((edge['source'],edge['target'],'assesses'))
            if e['actor'] not in actors or e['trajectory_id']!=r['trajectory_id']:reason='different_recipient_or_trajectory'
            elif e['index']<=r['index']:reason='assessment_not_recorded_after_response'
            elif not ((p.get('basis')=='jev_raw_argmax' and p.get('request') and not reviewed) or
                      (p.get('basis')==relation_reviews.VERSION and reviewed and reviewed['status']=='present')):reason='assessment_provenance_unestablished'
            else:
                refs=p.get('evidence',[])+p.get('context_evidence',[])
                def prior(ref):
                    event=events.get(ref.get('event_id'));start,end=ref.get('start'),ref.get('end')
                    return bool(event and visible(event) and event['trajectory_id']==r['trajectory_id']
                        and type(start) is int and type(end) is int and 0<=start<end<=len(event['text'])
                        and event['text'][start:end]==ref.get('text') and (event['index'],end)<=(e['index'],s['end']))
                fs=units[edge['target']]['source']
                if (not refs or not all(prior(ref) for ref in refs)
                    or not any(ref['event_id']==rid and fs['start']<=ref['start']<ref['end']<=fs['end'] for ref in p.get('context_evidence',[]))
                    or not any(ref['event_id']==e['id'] and s['start']<=ref['start']<ref['end']<=s['end'] for ref in p.get('evidence',[]))):reason='assessment_evidence_unestablished'
        if reason:excluded.append(dict(edge_id=edge['id'],response_event_id=rid,reason=reason))
        else:candidates[rid].append(edge)

    rows=[]
    for rid,aids in sorted(bound.items(),key=lambda x:(events[x[0]]['index'],x[0])):
        r=events[rid];reasons=[];chosen=None;between=[];parallel=[]
        eligible=sorted(candidates[rid],key=lambda x:(events[units[x['source']]['source']['event_id']]['index'],units[x['source']]['source']['start'],x['id']))
        if len(aids)!=1:reasons.append('response_origin_ambiguous')
        if not eligible:reasons.append('no_supported_saved_assessment')
        else:
            chosen=eligible[0];assessment=units[chosen['source']];end=events[assessment['source']['event_id']]
            action=events[sorted(aids)[0]];actor=action['actor']
            if action.get('context_id')!=end.get('context_id'):reasons.append('recipient_context_changed')
            interval=[e for e in events.values() if e['trajectory_id']==r['trajectory_id'] and r['index']<e['index']<end['index']]
            between=sorted([e for e in interval if e['kind']=='action' and e['actor']==actor],key=lambda e:(e['index'],e['id']))
            if any(not visible(e) or e.get('context_id')!=action.get('context_id') for e in between):reasons.append('intervening_dispatch_context_unavailable')
            if any(e['actor']==actor and e.get('copied_context') for e in interval):reasons.append('copied_context_in_interval')
            seen=set();inside={e['id'] for e in between}
            for e in between:
                members=order.groups.get(e['id'],[e['id']]);key=tuple(members)
                # Calls emitted with the assessment share a generation, even if an adapter places them first.
                if e.get('parent_id')==end['id'] or (e.get('source_message_index') is not None and e.get('source_message_index')==end.get('source_message_index')):
                    reasons.append('dispatch_shares_assessment_message')
                if key in seen:continue
                seen.add(key);declared=max(events[mid].get('batch_size',0) or 0 for mid in members)
                if len(members)>1 or declared>1:
                    complete=set(members)<=inside and len(members)>=declared
                    parallel.append(dict(event_ids=members,complete=complete,mutual_order='unknown'))
                    if not complete:reasons.append('parallel_group_crosses_interval_or_is_incomplete')
        gap=len(between) if chosen and not reasons else None
        value=gap>0 if gap is not None else None
        node_ids=['event:'+rid,*['event:'+aid for aid in sorted(aids)],*['event:'+e['id'] for e in between]]
        edge_ids=list(binding_edges[rid])
        if chosen:
            node_ids.extend([chosen['target'],chosen['source'],'event:'+units[chosen['source']]['source']['event_id']])
            # feedback_for connects the source action unit as well as the response unit.
            selected_edges=feedback_edges[(rid,chosen['target'])]
            node_ids.extend(e['target'] for e in graph['edges'] if e['id'] in selected_edges)
            edge_ids.extend([chosen['id'],*selected_edges])
        rows.append(dict(id='feedback-timing-'+digest([graph['id'],rid]),response_event_id=rid,action_event_ids=sorted(aids),
            value=value,status='after_other_actions' if value is True else 'before_other_actions' if value is False else 'unknown',
            assessment_unit_id=chosen['source'] if chosen else None,response_unit_id=chosen['target'] if chosen else None,
            assessment_edge_id=chosen['id'] if chosen else None,supported_assessment_count=len(eligible),
            intervening_dispatches=gap,intervening_action_event_ids=[e['id'] for e in between],parallel_groups=parallel,
            unknown_reasons=sorted(set(reasons)),node_ids=list(dict.fromkeys(node_ids)),edge_ids=list(dict.fromkeys(edge_ids))))
    n=sum(r['value'] is True for r in rows);d=sum(r['value'] is not None for r in rows)
    result=dict(schema=VERSION,run_id=graph['run_id'],graph_id=graph['id'],source_hash=graph['source_hash'],observations=rows,
        metrics=dict(value=n/d if d else None,numerator=n,denominator=d,opportunities=len(rows),unknown=len(rows)-d),
        coverage=dict(responses=len(rows),with_supported_assessment=sum(bool(r['assessment_unit_id']) for r in rows),
            timing_comparable=d,unknown_reasons=dict(Counter(reason for row in rows for reason in row['unknown_reasons'])),excluded_links=excluded),
        limits=LIMITS)
    return dict(id='feedback-timing-projection-'+digest(result),**result)
