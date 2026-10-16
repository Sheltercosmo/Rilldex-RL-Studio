"""Explicit response references, with source-defined opportunities and censoring.

No inference runs here. A selected edge is a positive witness, not proof of
comprehension. A negative requires complete coverage of a fixed text window.
"""
from collections import Counter,defaultdict
from .schema import digest
from .feedback_assessments import CONTRIBUTION_SCOPE
from .readable_context import subtract,DATA_URI

VERSION='feedback-reference-opportunities/2'
WINDOW=3
LIMITS=('Visible source-bound tool responses, within the next three nonempty agent text events in the same actor/trajectory/context. '
    'Measures explicit description or interpretation, not correct interpretation, silent action uptake, causal influence, revision or recovery. '
    'No-response reasoning is not applicable. Missing or incomplete windows, segmentation, inspection, candidates or response text remain unknown. '
    'Rates exclude unknowns; compare coverage alongside the rate. Counts and rates are conditional on the selected observer.')


def project(graph):
    from . import relation_reviews,map_relationships
    annotations=relation_reviews.checked(graph)
    audit=map_relationships.inspect(graph)
    rejected={r['edge_id']:r for r in audit['relationships'] if r['status']=='incompatible'}
    events={n['properties']['id']:n['properties'] for n in graph['nodes'] if n['kind']=='event'}
    units={n['id']:n['properties'] for n in graph['nodes'] if n['kind']=='unit'}
    edges=graph['edges'];problems=[]
    def valid(u):
        s=u.get('source',{});e=events.get(s.get('event_id'))
        return bool(e and not e.get('copied_context') and u.get('actor')==e['actor'] and u.get('trajectory_id')==e['trajectory_id'] and
            type(s.get('start')) is int and type(s.get('end')) is int and 0<=s['start']<s['end']<=len(e['text']) and
            e['text'][s['start']:s['end']]==s.get('text'))
    semantic={uid:u for uid,u in units.items() if valid(u) and u.get('kind')=='semantic' and u.get('status')=='selected'}
    by_event=defaultdict(list)
    for uid,u in semantic.items():by_event[u['source']['event_id']].append(uid)
    # The opportunity denominator comes from native bindings, including actions
    # that have no selected semantic unit. Observer gaps cannot shrink it.
    responses=defaultdict(set)
    for edge in edges:
        if edge['type']!='response_to' or not edge['source'].startswith('event:') or not edge['target'].startswith('event:'):continue
        rid,aid=edge['source'][6:],edge['target'][6:];r,a=events.get(rid),events.get(aid)
        if (r and a and r['kind']=='feedback' and a['kind']=='action' and r['index']>a['index'] and
            r['trajectory_id']==a['trajectory_id'] and r.get('context_id')==a.get('context_id') and r.get('agent_visibility')!='not_established' and
            not r.get('copied_context') and not a.get('copied_context') and r['text'].strip()):responses[rid].add(aid)
    context=(graph.get('semantic_context') or {}).get('feedback_observations',{})
    reviews={}
    if context.get('scope_version')==CONTRIBUTION_SCOPE:
        for row in context.get('observations',[]):reviews.setdefault(row['unit_id'],[]).append(row)
    feedback=defaultdict(set)
    for edge in edges:
        f,a=units.get(edge['source']),units.get(edge['target'])
        if edge['type']=='feedback_for' and f and a and valid(f) and valid(a):
            rid,aid=f['source']['event_id'],a['source']['event_id']
            if aid in responses.get(rid,set()):feedback[rid].add(edge['source'])
    rows=[]
    for rid,aids in sorted(responses.items(),key=lambda p:events[p[0]]['index']):
        r=events[rid];actors={events[aid]['actor'] for aid in aids}
        if len(actors)!=1:
            problems.append({'response_event_id':rid,'reason':'Response recipient is ambiguous'});continue
        actor=next(iter(actors))
        if actor in {'user','system','developer','environment'}:continue
        window=sorted([e for e in events.values() if e['index']>r['index'] and e['trajectory_id']==r['trajectory_id'] and
            e.get('context_id')==r.get('context_id') and
            e['actor']==actor and e['kind'] in {'message','reasoning'} and e['text'].strip() and
            not e.get('copied_context') and e.get('agent_visibility')!='not_established'],key=lambda e:e['index'])[:WINDOW]
        uids=[uid for e in window for uid in by_event[e['id']]];fids=feedback[rid]
        found=[]
        for edge in edges:
            if edge['type']!='assesses' or edge['source'] not in uids or edge['target'] not in fids:continue
            if edge['id'] in rejected:continue
            p=edge['properties'];u=semantic[edge['source']];s=u['source']
            reviewed=annotations.get((edge['source'],edge['target'],'assesses'))
            if not (p.get('basis')=='jev_raw_argmax' and p.get('request') or
                    p.get('basis')==relation_reviews.VERSION and reviewed and reviewed['status']=='present'):continue
            refs=p.get('evidence',[])+p.get('context_evidence',[])
            def prior(ref):
                e=events.get(ref.get('event_id'))
                return bool(e and e['trajectory_id']==r['trajectory_id'] and not e.get('copied_context') and
                    type(ref.get('start')) is int and type(ref.get('end')) is int and 0<=ref['start']<ref['end']<=len(e['text']) and
                    e['text'][ref['start']:ref['end']]==ref.get('text') and
                    (e['index'],ref['end'])<=(events[s['event_id']]['index'],s['end']))
            if (refs and all(prior(ref) for ref in refs) and any(ref['event_id']==rid for ref in p.get('context_evidence',[])) and
                any(ref['event_id']==s['event_id'] for ref in p.get('evidence',[]))):found.append(edge)
        reasons=[]
        if not found:
            if r.get('order_known') is False or any(events[aid].get('order_known') is False for aid in aids) or any(e.get('order_known') is False for e in window):reasons.append('source_order_unresolved')
            if any(edge['id'] in rejected and edge['type']=='assesses' and edge['target'] in fids for edge in edges):reasons.append('incompatible_reference_evidence')
            if len(window)<WINDOW:reasons.append('window_not_fully_observed')
            if not fids:reasons.append('response_unit_not_selected')
            for e in window:
                spans=sorted((semantic[uid]['source']['start'],semantic[uid]['source']['end']) for uid in by_event[e['id']])
                if any(e['text'][a:b].strip() for a,b in subtract([(0,len(e['text']))],spans)) or any(b>c for (_,b),(c,_) in zip(spans,spans[1:])):
                    reasons.append('text_segmentation_incomplete')
                if e.get('media') or DATA_URI.search(e['text']):reasons.append('unobserved_contribution_media')
            for uid in uids:
                manual=[annotations[(uid,fid,'assesses')] for fid in fids if (uid,fid,'assesses') in annotations]
                if manual:
                    if len(manual)!=1 or manual[0]['status']!='absent':reasons.append('reference_unresolved')
                    if r.get('media') or DATA_URI.search(r['text']):reasons.append('response_text_incomplete')
                    continue
                selected=reviews.get(uid,[])
                if len(selected)!=1:reasons.append('contribution_not_reviewed');continue
                review=selected[0]
                if review.get('scope_version')!=CONTRIBUTION_SCOPE or review.get('status') not in {'linked','none_of_these'}:
                    reasons.append('reference_unresolved');continue
                if not review.get('request') or review.get('contribution_context_complete') is not True:reasons.append('contribution_context_incomplete')
                offered=set(review.get('offered_feedback_units',[]))
                if not fids&offered:reasons.append('response_not_offered')
                if fids&set(review.get('incomplete_feedback_units',[])):reasons.append('response_text_incomplete')
                if fids&set(review.get('target_feedback_units',[])):reasons.append('selected_reference_edge_missing')
        value=True if found else None if reasons else False
        node_ids=list(dict.fromkeys(['event:'+rid,*['event:'+aid for aid in sorted(aids)],*['event:'+e['id'] for e in window],*sorted(fids),*uids]))
        rows.append({'id':'feedback-opportunity-'+digest([graph['id'],rid,WINDOW]),'response_event_id':rid,
            'action_event_ids':sorted(aids),'actor':actor,'trajectory_id':r['trajectory_id'],
            'window_event_ids':[e['id'] for e in window],'contribution_unit_ids':uids,
            'value':value,'status':'referenced' if value is True else 'no_reference_in_window' if value is False else 'unknown',
            'unknown_reasons':sorted(set(reasons)),'node_ids':node_ids,'edge_ids':[e['id'] for e in found]})
    n=sum(row['value'] is True for row in rows);d=sum(row['value'] is not None for row in rows)
    value={'schema':VERSION,'run_id':graph['run_id'],'source_hash':graph['source_hash'],'graph_id':graph['id'],
        'window':{'unit':'agent_text_events','count':WINDOW,'actor':'response recipient','trajectory':'same','context':'same'},
        'observations':rows,'metrics':{'value':n/d if d else None,'numerator':n,'denominator':d,'opportunities':len(rows),'unknown':len(rows)-d},
        'coverage':{'decidable_fraction':d/len(rows) if rows else None,
            'unknown_reasons':dict(Counter(reason for row in rows for reason in row['unknown_reasons'])),
            'excluded_responses':problems,'excluded_links':list(rejected.values())},'limits':LIMITS,
        'applicability':'applicable' if rows else 'no_visible_bound_tool_responses'}
    return {'id':'feedback-opportunities-'+digest(value),**value}
