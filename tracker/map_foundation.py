"""Reproducible map foundation checks, separate from semantic correctness."""
from . import annotation_changes, map_relationships
from .schema import InputError, digest

VERSION='map-foundation/2'


def content_sources(graph):
    """A faithful quote must also be available in the unit's local context."""
    events={n['properties']['id']:{**n['properties'],
        'index':n['properties'].get('index',n.get('event_index')),
        'trajectory_id':n['properties'].get('trajectory_id',n.get('trajectory_id'))}
        for n in graph['nodes'] if n['kind']=='event'}
    def refs(value,path=''):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in {'evidence','context_evidence'} and isinstance(v,list):
                    for r in v:yield path+'.'+k,r
                else:yield from refs(v,path+'.'+k)
        elif isinstance(value,list):
            for i,v in enumerate(value):yield from refs(v,path+f'[{i}]')
    findings=[];checked=0
    for n in graph['nodes']:
        if n['kind']!='unit':continue
        p=n['properties'];s=p.get('source',{});owner=events.get(s.get('event_id'))
        if not owner:continue
        for field,ref in refs({'content':p.get('content',{}),'plan_structure':p.get('plan_structure',{})}):
            checked+=1;problem=None
            e=events.get(ref.get('event_id')) if isinstance(ref,dict) else None
            if not e:problem='missing_content_source'
            else:
                a,b=ref.get('start'),ref.get('end')
                if (type(a) is not int or type(b) is not int or not 0<=a<b<=len(e['text'])
                        or e['text'][a:b]!=ref.get('text') or e.get('source_pointer')!=ref.get('source_pointer')):
                    problem='content_quote_mismatch'
                elif (e['index'],b)>(owner['index'],s['end']):problem='future_content_source'
                elif (e['trajectory_id'],e.get('context_id'))!=(owner['trajectory_id'],owner.get('context_id')):problem='cross_context_content_source'
                elif e.get('copied_context') or e.get('agent_visibility')=='not_established':problem='content_source_not_visible'
            if problem:findings.append(dict(unit_id=n['id'],field=field,reason=problem,evidence=ref))
    return dict(checked_references=checked,issues=findings,excluded_unit_ids=sorted({r['unit_id'] for r in findings}))


def inspect(graph, run=None):
    inventory=annotation_changes._inventory(graph)
    if run is not None:
        if run['id']!=graph['run_id'] or digest(run)!=graph['source_hash']:
            raise InputError('Foundation audit source differs from the graph')
        stored={key:n['properties'] for key,n in inventory['events'].items()}
        if stored!={e['id']:e for e in run['events']}:
            raise InputError('Map source events differ from the captured rollout')
    units=list(inventory['units'].values())
    named=[n['id'] for n in units if n['properties'].get('provenance',{}).get('kind')=='named_review']
    relationships=map_relationships.inspect(graph)
    contents=content_sources(graph)
    return dict(schema=VERSION,graph_id=graph['id'],source_hash=graph['source_hash'],
        source_checks=dict(status='passed',units=len(units),events=len(inventory['events']),
            scope='original rollout and embedded source anchors' if run is not None else 'embedded source anchors only',
            checks=['unique identities','exact source spans','non-overlapping units','source actor and position','matching activity fields','relationship endpoints']),
        relationships=relationships,
        content_sources=contents,
        excluded_edge_ids=[r['edge_id'] for r in relationships['relationships'] if r['status']=='incompatible'],
        semantic_review=dict(status='not_independently_validated',named_review_unit_ids=named,
            unreviewed_unit_count=len(units)-len(named)),
        boundary='Passing source checks does not establish correct unit boundaries, activity meanings, target entailment or relationship semantics. Named reviews are annotations, not independent accuracy evidence.')
