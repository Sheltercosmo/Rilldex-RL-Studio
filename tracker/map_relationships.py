"""Necessary source conditions for displayed semantic relationships.

Passing these checks is not semantic entailment. Selected wording and relation
meaning still require review. No label, argmax or stored edge is rewritten.
"""
REVIEW_TYPES={'assesses','uses_evidence','revises'}
VERSION='map-relationship-boundaries/3'


def inspect(graph):
    from .graph_sequence import Ordering
    order=Ordering(graph)
    nodes={n['id']:n for n in graph['nodes']}
    events={n['properties']['id']:n for n in graph['nodes'] if n['kind']=='event' and 'id' in n['properties']}
    recipients={}
    for edge in graph['edges']:
        if edge['type'] in {'feedback_for','response_to'}:
            recipients.setdefault(edge['source'],set()).add(edge['target'])
    def event(n):return events.get(n['properties'].get('source',{}).get('event_id'),n)
    def lane(n):return n.get('trajectory_id'),event(n)['properties'].get('context_id')
    def invisible(n):
        p=event(n)['properties']
        return p.get('agent_visible') is False or p.get('agent_visibility')=='not_established' or p.get('copied_context') or p.get('kind','').startswith('external_')
    def before(a,b):
        if a.get('event_index') is None or b.get('event_index') is None:return False
        if a['event_index']!=b['event_index']:return a['event_index']<b['event_index']
        sa=a['properties'].get('source',{});sb=b['properties'].get('source',{})
        return (sa.get('event_id')==sb.get('event_id') and type(sa.get('end')) is int
                and type(sb.get('start')) is int and sa['end']<=sb['start'])
    results=[]
    for e in sorted(graph['edges'],key=lambda e:e['id']):
        if e['type'] not in REVIEW_TYPES:continue
        a=nodes.get(e['source']);b=nodes.get(e['target']);problem=None
        if not a or not b:problem='missing_endpoint'
        elif lane(a)!=lane(b):problem='cross_context_or_trajectory'
        elif (any(event(n)['properties'].get('order_known') is False for n in (a,b))
              and not (order.event_id(a) is not None and order.event_id(a)==order.event_id(b))):problem='unresolved_source_order'
        elif order.parallel_siblings(a,b):problem='parallel_dispatch_reference'
        elif any(invisible(n) for n in (a,b)):problem='unestablished_visibility'
        elif not before(b,a):problem='referent_not_earlier'
        elif e['type']=='assesses' or e['type']=='uses_evidence' and b['properties'].get('kind')=='feedback':
            origins=recipients.get(b['id'],set())
            origin=nodes.get(next(iter(origins))) if len(origins)==1 else None
            if b['properties'].get('kind')!='feedback':problem='assessment_target_not_feedback'
            elif not origin or origin['properties'].get('kind')!='action':problem='feedback_recipient_unresolved'
            elif (a['properties'].get('actor')!=origin['properties'].get('actor')
                  or lane(a)!=lane(origin)):problem='assessment_actor_differs'
            elif event(origin)['properties'].get('order_known') is False:problem='unresolved_source_order'
            elif invisible(origin):problem='unestablished_visibility'
            elif not before(origin,b):problem='feedback_not_after_dispatch'
        elif a['properties'].get('actor')!=b['properties'].get('actor'):problem='cross_actor_reference'
        if not problem:
            props=e.get('properties',{})
            for name in ('evidence','context_evidence'):
                refs=props.get(name,[])
                if not isinstance(refs,list):problem='invalid_relationship_citations';break
                for ref in refs:
                    source=events.get(ref.get('event_id')) if isinstance(ref,dict) else None
                    if not source:problem='missing_relationship_source';break
                    p=source['properties'];lo,hi=ref.get('start'),ref.get('end')
                    if (type(lo) is not int or type(hi) is not int or not 0<=lo<hi<=len(p.get('text',''))
                            or p['text'][lo:hi]!=ref.get('text') or p.get('source_pointer')!=ref.get('source_pointer')):
                        problem='relationship_quote_mismatch';break
                    if lane(source)!=lane(a):problem='cross_context_relationship_source';break
                    if invisible(source):problem='relationship_source_not_visible';break
                    if p.get('order_known') is False and p.get('id')!=order.event_id(a):problem='unresolved_source_order';break
                    end=a['properties'].get('source',{}).get('end',len(event(a)['properties'].get('text','')))
                    if type(source.get('event_index')) is not int or type(end) is not int:problem='unresolved_source_order';break
                    if (source['event_index'],hi)>(a['event_index'],end):problem='future_relationship_source';break
                if problem:break
        results.append(dict(edge_id=e['id'],type=e['type'],source=e['source'],target=e['target'],
                            status='incompatible' if problem else 'compatible',reason=problem))
    return dict(schema=VERSION,graph_id=graph['id'],relationships=results,
        checked=len(results),incompatible=sum(r['status']=='incompatible' for r in results),
        boundary='Necessary source/actor/order conditions and exact supplied citations only, not validation of semantic entailment. Other relationship families are outside this audit. Missing context IDs share an unspecified scope; isolation cannot be verified if the source omits it.')
