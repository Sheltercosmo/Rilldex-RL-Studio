"""Reviewed work structure over immutable source evidence.

Items are enduring work, not new semantic units. A review can describe a goal,
subgoal, approach or hypothesis without changing the base activity taxonomy.
Structural validation cannot establish that a review is semantically correct.
"""
from copy import deepcopy
import json
import re

from . import graph_store
from .schema import InputError, digest

VERSION = 'work-outline/1'
BINDING_VERSION = 'work-outline/2'
KINDS = {'objective', 'subgoal', 'approach', 'hypothesis'}
LINKS = {
    'part_of': 'This work contributes to the broader target; it does not imply adoption or completion.',
    'alternative_to': 'A distinct candidate approach to the same target; neither is automatically chosen.',
    'depends_on': 'A stated prerequisite, not merely earlier work.',
    'replaces': 'An explicit replacement of earlier work; a different description alone is insufficient.',
}
DECISIONS = {
    'pursue': 'Explicit decision to pursue this work, not a successful execution.',
    'defer': 'Explicit decision to postpone this work; lack of activity is insufficient.',
    'stop': 'Explicit decision not to continue this work; failure alone is insufficient.',
    'resume': 'Explicit decision to return to this work, not merely a repeated command.',
    'reported_complete': 'Agent reports this work complete; this is not independent verification.',
    'reported_failed': 'Agent reports failure at this work scope; do not propagate a child failure.',
}
STATES = {'pursue': 'Chosen for work', 'defer': 'Explicitly deferred', 'stop': 'Explicitly stopped',
    'resume': 'Explicitly resumed', 'reported_complete': 'Reported complete', 'reported_failed': 'Reported failed'}
LIMIT = ('Source-linked review, not independently validated extraction. Work structure does not change base units. '
    'Decisions are attributed statements, not observed execution or verified outcomes. '
    'No activity does not establish abandonment; child states do not determine parent state.')


def require(ok, message):
    if not ok: raise InputError('Work outline: '+message)


def source_index(graph):
    return {n['properties']['id']: n for n in graph['nodes'] if n['kind'] == 'event'}


def anchor(ref, events):
    require(isinstance(ref, dict) and set(ref) == {'event_id','start','end','text'}, 'exact source citation required')
    require(isinstance(ref['event_id'],str) and isinstance(ref['text'],str),'invalid citation values')
    n = events.get(ref['event_id']); require(n is not None, 'unknown source record')
    p = n['properties']; a,b = ref['start'],ref['end']
    require(type(a) is int and type(b) is int and 0<=a<b<=len(p.get('text','')) and
        p['text'][a:b] == ref['text'] and bool(ref['text'].strip()), 'source span does not match')
    require(not p.get('copied_context') and p.get('agent_visibility') != 'not_established' and
        p.get('actor') in {'agent','user'}, 'citation is not an attributable participant contribution')
    return n


def position(ref, events):
    return events[ref['event_id']]['event_index'],ref['end']


def lane(ref, events):
    n=events[ref['event_id']];return n['trajectory_id'], n['properties'].get('context_id')


def binding_scopes(graph):
    """Existing semantic plan scopes, not proposed semantic matches."""
    nodes={n['id']:n for n in graph['nodes']};out=[]
    for plan in graph['nodes']:
        if plan['kind']!='unit' or plan.get('activity')!='plan' or not plan['properties'].get('plan_structure'):continue
        p=plan['properties'];raw=p.get('source')
        if not raw:continue
        ref={k:raw[k] for k in ('event_id','start','end','text')}
        target=p.get('content',{}).get('target');label=target.get('text') if isinstance(target,dict) else target
        out.append(dict(id=plan['id'],kind='plan',label=label or ref['text'],
            plan_id=plan['id'],evidence=deepcopy(ref)))
        for step in p['plan_structure']['steps']:
            sid=plan['id']+':'+step['id']
            if sid not in nodes or nodes[sid]['kind']!='plan_step' or not any(e['type']=='contains_plan_step' and e['source']==plan['id'] and e['target']==sid for e in graph['edges']):continue
            out.append(dict(id=sid,kind='plan_step',label=step['text'],plan_id=plan['id'],evidence=deepcopy(ref)))
    return out


def validate(graph, document):
    require(isinstance(document,dict), 'invalid document')
    fields={'schema','base_graph_id','revision','items','links','decisions'}
    if document.get('schema')==BINDING_VERSION:fields.add('bindings')
    require(set(document)==fields, 'invalid document fields')
    require(document['schema'] in {VERSION,BINDING_VERSION} and document['base_graph_id']==graph['id'], 'exact graph binding required')
    r=document['revision']
    require(isinstance(r,dict) and set(r)=={'author','note'} and all(isinstance(r[k],str) and 0<len(r[k].strip())<=2400 for k in r), 'named review and rationale required')
    for name,bound in [('items',500),('links',2000),('decisions',2000)]:
        require(isinstance(document[name],list) and len(document[name])<=bound, 'invalid or oversized '+name)
    events=source_index(graph);items={}
    for item in document['items']:
        require(isinstance(item,dict) and set(item)=={'id','kind','label','evidence'}, 'invalid work item')
        require(isinstance(item['id'],str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,159}',item['id']) and item['id'] not in items, 'unique simple work ID required')
        require(isinstance(item['kind'],str) and item['kind'] in KINDS, 'unknown work kind')
        require(isinstance(item['label'],str) and 0<len(item['label'].strip())<=1200, 'readable work target required')
        n=anchor(item['evidence'],events)
        require(n['properties']['actor']=='agent' or item['kind'] in {'objective','subgoal'}, 'user request cannot declare an agent approach or hypothesis')
        items[item['id']]=item
    seen=set();hierarchy={k:set() for k in items};dependencies={k:set() for k in items}
    for link in document['links']:
        require(isinstance(link,dict) and set(link)=={'from','to','type','evidence'}, 'invalid work connection')
        a,b,k=link['from'],link['to'],link['type']
        require(all(isinstance(v,str) for v in (a,b,k)) and k in LINKS and a in items and b in items and a!=b, 'invalid connection endpoints')
        require((a,b,k) not in seen, 'duplicate connection');seen.add((a,b,k))
        ref=link['evidence'];n=anchor(ref,events)
        require(lane(ref,events)==lane(items[a]['evidence'],events)==lane(items[b]['evidence'],events), 'connection crosses source contexts')
        require(position(ref,events)>=max(position(items[x]['evidence'],events) for x in (a,b)), 'connection precedes a declaration')
        if k=='part_of':hierarchy[a].add(b)
        if k=='depends_on':dependencies[a].add(b)
        if k in {'alternative_to','replaces'}:
            require(items[a]['kind']==items[b]['kind'], 'alternatives/replacements must use the same work scale')
        if k=='replaces':
            require(n['properties']['actor']=='agent', 'replacement requires an explicit agent statement')
    for adjacency in (hierarchy,dependencies):
        done=set()
        def visit(k,stack):
            require(k not in stack,'cyclic hierarchy or prerequisite')
            if k in done:return
            for nxt in adjacency[k]:visit(nxt,stack|{k})
            done.add(k)
        for k in adjacency:visit(k,set())
    seen=set()
    for decision in document['decisions']:
        require(isinstance(decision,dict) and set(decision)=={'item_id','type','evidence'}, 'invalid branch decision')
        k=decision['item_id'];kind=decision['type']
        require(isinstance(k,str) and k in items and isinstance(kind,str) and kind in DECISIONS, 'unknown decision target/type')
        ref=decision['evidence'];n=anchor(ref,events)
        require(n['properties']['actor']=='agent', 'branch decisions must retain agent attribution')
        require(lane(ref,events)==lane(items[k]['evidence'],events) and position(ref,events)>=position(items[k]['evidence'],events), 'decision crosses context or precedes work')
        key=digest(decision);require(key not in seen,'duplicate branch decision');seen.add(key)
    if document['schema']==BINDING_VERSION:
        require(isinstance(document['bindings'],list) and len(document['bindings'])<=2000,'invalid scope bindings')
        scopes={s['id']:s for s in binding_scopes(graph)};seen=set()
        for binding in document['bindings']:
            require(isinstance(binding,dict) and set(binding)=={'item_id','scope_node_id','evidence','note'},'invalid scope binding')
            a,b=binding['item_id'],binding['scope_node_id']
            require(isinstance(a,str) and a in items and isinstance(b,str) and b in scopes,'binding needs an existing work item and plan scope')
            require(items[a]['kind']!='hypothesis','a hypothesis is not an executable work scope; bind the stated work that tests it')
            require((a,b) not in seen,'duplicate scope binding');seen.add((a,b))
            require(isinstance(binding['note'],str) and 0<len(binding['note'].strip())<=2400,'scope equivalence rationale required')
            ref=binding['evidence'];n=anchor(ref,events);scope=scopes[b]
            require(anchor(scope['evidence'],events)['properties']['actor']=='agent','plan scope must retain agent attribution')
            require(n['properties']['actor']=='agent','scope correspondence requires an agent contribution')
            require(lane(ref,events)==lane(items[a]['evidence'],events)==lane(scope['evidence'],events),'scope binding crosses source contexts')
            require(position(ref,events)>=max(position(items[a]['evidence'],events),position(scope['evidence'],events)),'scope binding precedes its work or plan')
    return deepcopy(document)


def fork(graph, document):
    graph_store.validate(graph);d=validate(graph,document);g=deepcopy(graph);g.pop('id')
    ctx=g.get('semantic_context') or {};g['semantic_context']=ctx;old=ctx.get('work_outline',{})
    removed={n['id'] for n in g['nodes'] if n['kind'].startswith('work_outline_')}
    g['nodes']=[n for n in g['nodes'] if n['id'] not in removed]
    g['edges']=[e for e in g['edges'] if e['source'] not in removed and e['target'] not in removed]
    scope_id=old.get('scope_id') or digest([VERSION,graph['id']])[:20]
    prefix='outline:'+scope_id+':'
    events=source_index(graph)
    def node(k,kind,props,ref):
        n=events[ref['event_id']]
        g['nodes'].append(dict(id=k,kind=kind,activity=None,event_index=n['event_index'],trajectory_id=n['trajectory_id'],properties=deepcopy(props)))
    def edge(a,b,kind,ref):
        row=dict(source=a,target=b,type=kind,properties=dict(basis=d['schema'],evidence=[deepcopy(ref)],review=deepcopy(d['revision'])))
        g['edges'].append(dict(id='edge-'+digest(row),**row))
    for item in d['items']:
        k=prefix+item['id'];node(k,'work_outline_item',item,item['evidence'])
        edge(k,'event:'+item['evidence']['event_id'],'outline_evidence',item['evidence'])
    for link in d['links']:edge(prefix+link['from'],prefix+link['to'],'outline_'+link['type'],link['evidence'])
    for binding in d.get('bindings',[]):edge(prefix+binding['item_id'],binding['scope_node_id'],'outline_same_scope',binding['evidence'])
    for decision in d['decisions']:
        k=prefix+'decision:'+digest(decision);node(k,'work_outline_decision',decision,decision['evidence'])
        edge(prefix+decision['item_id'],k,'outline_decision',decision['evidence'])
        edge(k,'event:'+decision['evidence']['event_id'],'outline_evidence',decision['evidence'])
    ctx['work_outline']=dict(document=d,scope_id=scope_id,base_observer=old.get('base_observer',graph['observer']),
        base_label=old.get('base_label',graph['observer_label']),root_graph_id=old.get('root_graph_id',graph['id']),limit=LIMIT)
    g['observer']='work-outline-'+digest([d['schema'],ctx['work_outline']['base_observer']])[:20]
    g['observer_label']='Reviewed work outline · '+ctx['work_outline']['base_label']
    g['annotation_hash']=digest([graph['annotation_hash'],d]);g['coverage']={**g['coverage'],'work_outline':'reviewed_partial'}
    g['nodes'].sort(key=lambda n:n['id']);g['edges'].sort(key=lambda e:e['id'])
    g['counts']={**g['counts'],'nodes':len(g['nodes']),'edges':len(g['edges'])}
    result=dict(id='graph-'+digest(g),**g);graph_store.validate(result);return result


def template(graph):
    old=(graph.get('semantic_context') or {}).get('work_outline',{})
    d=deepcopy(old.get('document') or dict(schema=VERSION,revision=dict(author='',note=''),items=[],links=[],decisions=[]))
    d['base_graph_id']=graph['id']
    if old.get('selection'):
        d['revision']={'author':'','note':'Review of the model-selected work outline.'}
    return dict(document=d,kinds=sorted(KINDS),links=LINKS,decisions=DECISIONS,limit=LIMIT,
        binding_schema=BINDING_VERSION,binding_scopes=binding_scopes(graph))


def receive(store, document):
    require(isinstance(document,dict) and isinstance(document.get('base_graph_id'),str),'base graph required')
    base=graph_store.read(store,document['base_graph_id']);validate(base,document)
    old=(base.get('semantic_context') or {}).get('work_outline',{}).get('document')
    unchanged=old is not None and {k:v for k,v in old.items() if k!='base_graph_id'}=={k:v for k,v in document.items() if k!='base_graph_id'}
    result=base if unchanged else fork(base,document)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT document FROM runs WHERE id=?',(base['run_id'],)).fetchone()
        require(row and digest(json.loads(row[0]))==base['source_hash'],'source changed since this review')
        exists=c.execute('SELECT 1 FROM rollout_graphs WHERE id=?',(result['id'],)).fetchone()
        latest=c.execute('SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? ORDER BY rowid DESC LIMIT 1',(base['run_id'],result['observer'])).fetchone()
        require(exists or not latest or latest[0]==base['id'],'a newer outline exists; reopen it before editing')
        graph_store.save(c,result)
    return dict(graph_id=result['id'],observer=result['observer'],run_id=result['run_id'],new_model_calls=0)


def project(graph, cutoff):
    info=(graph.get('semantic_context') or {}).get('work_outline')
    require(info is not None,'missing outline provenance')
    validate(graph,{**info['document'],'base_graph_id':graph['id']})
    checked(graph)
    events=source_index(graph);nodes={n['id']:n for n in graph['nodes'] if n['kind']=='work_outline_item' and n['event_index']<=cutoff}
    items=[];links=[];bindings=[];decisions={k:[] for k in nodes}
    lookup={n['id']:n for n in graph['nodes']}
    for e in graph['edges']:
        if e['source'] not in nodes or not e['type'].startswith('outline_'):continue
        refs=e['properties'].get('evidence',[])
        if not refs or any(events[r['event_id']]['event_index']>cutoff for r in refs):continue
        if e['type']=='outline_same_scope':
            if lookup[e['target']]['event_index']<=cutoff:
                note=next(b['note'] for b in info['document']['bindings'] if b['item_id']==nodes[e['source']]['properties']['id'] and b['scope_node_id']==e['target'])
                bindings.append(dict(id=e['id'],item_id=e['source'],scope_node_id=e['target'],evidence=deepcopy(refs),note=note))
        elif e['type']=='outline_decision':
            n=lookup[e['target']];decisions[e['source']].append(dict(id=n['id'],**n['properties'],event_index=n['event_index']))
        elif e['target'] in nodes:
            links.append(dict(id=e['id'],source=e['source'],target=e['target'],type=e['type'][8:],evidence=refs))
    for k,n in nodes.items():
        p=n['properties'];history=sorted(decisions[k],key=lambda d:position(d['evidence'],events))
        recent=[d for d in history if position(d['evidence'],events)==position(history[-1]['evidence'],events)] if history else []
        states={d['type'] for d in recent};state='Conflicting decisions' if len(states)>1 else STATES[next(iter(states))] if states else 'No decision recorded'
        related_units=[u['id'] for u in graph['nodes'] if u['kind']=='unit' and u['properties'].get('source',{}).get('event_id')==p['evidence']['event_id']
            and u['properties']['source']['start']<=p['evidence']['start'] and p['evidence']['end']<=u['properties']['source']['end']]
        items.append(dict(id=k,kind='outline_item',work_kind=p['kind'],label=p['label'],state=state,
            source_actor=events[p['evidence']['event_id']]['properties']['actor'],
            event_index=n['event_index'],evidence=[p['evidence']],source_text=p['evidence']['text'],
            source_node_ids=related_units or ['event:'+p['evidence']['event_id']],decisions=history))
    declaration_order={i['id']:index for index,i in enumerate(info['document']['items'])}
    order={k:(n['event_index'],n['properties']['evidence']['start'],declaration_order[n['properties']['id']]) for k,n in nodes.items()}
    items.sort(key=lambda i:order[i['id']])
    links.sort(key=lambda e:(position(e['evidence'][0],events),order[e['source']],order[e['target']]))
    result=dict(items=items,links=links,cutoff_event_index=cutoff,roots=[k for k in nodes if not any(e['source']==k and e['type']=='part_of' for e in links)],
        revision=info.get('document',{}).get('revision'),limit=LIMIT,
        basis='model_selected' if info.get('selection') else 'reviewed')
    if info.get('selection'):
        result['selection']={k:info['selection'][k] for k in ('producer','choice','request_hash')}
        result['selection']['cutoff_event_id']=info['selection']['packet']['cutoff_event_id']
        result['selection']['cutoff_record']=info['selection']['packet']['cutoff_event_index']+1
    if info['document']['schema']==BINDING_VERSION:
        result['binding_mode']='reviewed_scopes';result['bindings']=bindings
    return result


def checked(graph):
    """Verify that the review document, graph nodes and relations agree."""
    info=graph['semantic_context']['work_outline'];d=info['document'];prefix='outline:'+info['scope_id']+':'
    events=source_index(graph);expected_nodes={};expected_edges={}
    def node(k,kind,p,ref):
        n=events[ref['event_id']]
        expected_nodes[k]=dict(id=k,kind=kind,activity=None,event_index=n['event_index'],trajectory_id=n['trajectory_id'],properties=p)
    def edge(a,b,kind,ref):
        e=dict(source=a,target=b,type=kind,properties=dict(basis=d['schema'],evidence=[ref],review=d['revision']))
        k='edge-'+digest(e);expected_edges[k]=dict(id=k,**e)
    for i in d['items']:
        k=prefix+i['id'];node(k,'work_outline_item',i,i['evidence']);edge(k,'event:'+i['evidence']['event_id'],'outline_evidence',i['evidence'])
    for e in d['links']:edge(prefix+e['from'],prefix+e['to'],'outline_'+e['type'],e['evidence'])
    for b in d.get('bindings',[]):edge(prefix+b['item_id'],b['scope_node_id'],'outline_same_scope',b['evidence'])
    for r in d['decisions']:
        k=prefix+'decision:'+digest(r);node(k,'work_outline_decision',r,r['evidence'])
        edge(prefix+r['item_id'],k,'outline_decision',r['evidence']);edge(k,'event:'+r['evidence']['event_id'],'outline_evidence',r['evidence'])
    actual_nodes={n['id']:n for n in graph['nodes'] if n['kind'].startswith('work_outline_')}
    actual_edges={e['id']:e for e in graph['edges'] if e['source'] in actual_nodes or e['target'] in actual_nodes}
    require(actual_nodes==expected_nodes and actual_edges==expected_edges,'graph structure differs from the saved source review')
    if info.get('selection'):
        from .work_outline_candidates import audit_selection
        audit_selection(graph)
