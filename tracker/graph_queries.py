"""Explicit relation requirements; never execute SQL or prose supplied by a user."""
import json
from datetime import datetime, timezone
from collections import defaultdict
from .schema import digest, dumps, InputError
from . import graph_store

VERSION = 'graph-requirement/1'
PATH_VERSION = 'graph-requirement/2'
ENGINE_VERSION = 'graph-pattern-evaluation/3'
MAX_PATH_EDGE_VISITS = 50000
PRESETS = {
 'assessment_of_inspection_feedback': {'schema':PATH_VERSION,
    'question':'How often does the agent assess feedback returned by that inspection?',
    'anchor_activity':'inspect','relation':'assesses','within_units':8,'require_new_exploration':False,
    'evidence_path':{'start':'relation_target','hops':[{'direction':'outgoing','relations':['feedback_for']}]}},
 'revision_using_inspection_feedback': {'schema':PATH_VERSION,
    'question':'How often does a later revision use feedback returned by that inspection?',
    'anchor_activity':'inspect','relation':'revises','within_units':8,'require_new_exploration':False,
    'evidence_path':{'start':'relation_source','hops':[
        {'direction':'outgoing','relations':['uses_evidence','responds_to']},
        {'direction':'outgoing','relations':['feedback_for']}]}},
 'assessment_after_inspect': {'question':'How often is an inspection followed by an assessment of recorded feedback?',
    'anchor_activity':'inspect','relation':'assesses','within_units':8,'require_evidence_link':False,'require_new_exploration':False},
 'revision_after_inspect': {'question':'How often is information seeking followed by an explicit revision?',
    'anchor_activity':'inspect','relation':'revises','within_units':8,'require_evidence_link':False,'require_new_exploration':False},
 'revision_after_new_exploration': {'question':'What is the revision ratio after a new exploration?',
    'anchor_activity':'inspect','relation':'revises','within_units':8,'require_evidence_link':True,'require_new_exploration':True},
}


def validate(raw):
    if not isinstance(raw,dict): raise InputError('Requirement must be an object')
    version=raw.get('schema',VERSION)
    if not isinstance(version,str) or version not in {VERSION,PATH_VERSION}: raise InputError('Unsupported requirement schema')
    allowed={'schema','question','anchor_activity','relation','within_units','require_new_exploration'}
    allowed.add('evidence_path' if version==PATH_VERSION else 'require_evidence_link')
    if set(raw)-allowed: raise InputError('Unknown requirement fields: '+', '.join(sorted(set(raw)-allowed)))
    q={**raw,'schema':version}
    for key in ('question','anchor_activity','relation'):
        if not isinstance(q.get(key),str) or not q[key].strip() or len(q[key])>1000:
            raise InputError('Provide a nonempty '+key)
    if type(q.get('within_units')) is not int or not 1<=q['within_units']<=1000: raise InputError('Window must contain 1–1000 subsequent units')
    for key in (('require_new_exploration',) if version==PATH_VERSION else ('require_evidence_link','require_new_exploration')):
        if type(q.get(key)) is not bool: raise InputError(key+' must be true or false')
    if version==PATH_VERSION:
        if 'evidence_path' not in q: raise InputError('Specify evidence_path, or null for temporal association only')
        p=q['evidence_path']
        if p is not None:
            if not isinstance(p,dict) or set(p)!={'start','hops'} or not isinstance(p['start'],str) or p['start'] not in {'relation_source','relation_target'}:
                raise InputError('Evidence path starts at relation_source or relation_target')
            if not isinstance(p['hops'],list) or not 1<=len(p['hops'])<=3:
                raise InputError('Evidence paths require 1–3 explicit relationship hops')
            for hop in p['hops']:
                if (not isinstance(hop,dict) or set(hop)!={'direction','relations'}
                        or not isinstance(hop['direction'],str) or hop['direction'] not in {'outgoing','incoming'}
                        or not isinstance(hop['relations'],list) or not 1<=len(hop['relations'])<=8
                        or any(not isinstance(r,str) or not r.strip() or len(r)>100 for r in hop['relations'])
                        or len(set(hop['relations']))!=len(hop['relations'])):
                    raise InputError('Each path hop needs a direction and 1–8 distinct relationship names')
    return q


def path_definition(q):
    if q['schema']==PATH_VERSION: return q['evidence_path']
    if q['require_evidence_link']:
        return {'start':'relation_source','hops':[{'direction':'outgoing','relations':['uses_evidence','responds_to']}]}
    return None


def node_end(n):
    end=n['properties'].get('source',{}).get('end')
    if type(end) is int and end>=0:return end
    if n['kind']=='event' and isinstance(n['properties'].get('text'),str):return len(n['properties']['text'])
    # Source order can establish availability from an earlier event. Missing
    # within-event offsets cannot establish availability at a same-event cutoff.
    return float('inf')


def edge_available(edge, later, event_indices):
    cutoff=edge['properties'].get('cutoff')
    if cutoff is None:return True
    if not isinstance(cutoff,dict) or type(cutoff.get('end')) is not int:return False
    position=event_indices.get(cutoff.get('event_id'))
    return position is not None and (position,cutoff['end'])<=(later['event_index'],node_end(later))


def path_witness(spec, relation, anchor, later, by_id, adjacency, budget, event_indices, context):
    """Return one complete witness, not a sum of all combinatorial paths.

    Every hop must use a stored edge and materialized same-trajectory object
    available by the later unit's cutoff. An exhausted search fails the query;
    it never turns unfinished search into a negative observation.
    """
    start=relation['source'] if spec['start']=='relation_source' else relation['target']
    cutoff=(later['event_index'],node_end(later))
    def available(n):
        return (n is not None and n['kind']!='unresolved_reference' and n['event_index'] is not None
                and n['trajectory_id']==later['trajectory_id']
                and context(n)==context(later)
                and (n['event_index'],node_end(n))<=cutoff)
    if not available(by_id.get(start)): return None
    def visit(current, depth, nodes, traversals):
        if depth==len(spec['hops']):
            if current==anchor['id']:
                return {'node_ids':nodes,'edge_ids':[t['edge_id'] for t in traversals],'traversals':traversals}
            return None
        hop=spec['hops'][depth]
        for kind in hop['relations']:
            for edge in adjacency[hop['direction']].get((current,kind),[]):
                budget[0]+=1
                if budget[0]>MAX_PATH_EDGE_VISITS: raise InputError('Evidence-path search limit reached; narrow the graph population or path. No partial rate was produced.')
                following=edge['target'] if hop['direction']=='outgoing' else edge['source']
                if following in nodes or not available(by_id.get(following)) or not edge_available(edge,later,event_indices): continue
                witness=visit(following,depth+1,[*nodes,following],[*traversals,{
                    'edge_id':edge['id'],'from':current,'to':following,'direction':hop['direction']}])
                if witness: return witness
        return None
    return visit(start,0,[start],[])


def evaluate(graph, raw):
    q=validate(raw); by_id={n['id']:n for n in graph['nodes']}; streams=defaultdict(list)
    from . import map_relationships
    audit=map_relationships.inspect(graph)
    rejected={r['edge_id']:r for r in audit['relationships'] if r['status']=='incompatible'}
    events={n['properties']['id']:n['properties'] for n in graph['nodes'] if n['kind']=='event' and 'id' in n['properties']}
    def context(n):return events.get(n['properties'].get('source',{}).get('event_id'),n['properties']).get('context_id')
    for n in graph['nodes']:
        if n['kind']=='unit' and n['event_index'] is not None and n['properties'].get('actor')=='agent':
            streams[(n['trajectory_id'],context(n))].append(n)
    for nodes in streams.values(): nodes.sort(key=lambda n:(n['event_index'],n['properties'].get('source',{}).get('start',0),n['id']))
    outgoing=defaultdict(list); adjacency={'outgoing':defaultdict(list),'incoming':defaultdict(list)}
    for e in sorted(graph['edges'],key=lambda x:x['id']):
        if e['id'] in rejected:continue
        outgoing[e['source']].append(e)
        adjacency['outgoing'][(e['source'],e['type'])].append(e)
        adjacency['incoming'][(e['target'],e['type'])].append(e)
    spec=path_definition(q); budget=[0]
    event_indices={n['properties']['id']:n['event_index'] for n in graph['nodes'] if n['kind']=='event' and 'id' in n['properties']}
    event_indices.update({n['properties']['source']['event_id']:n['event_index'] for n in graph['nodes']
                          if n['event_index'] is not None and n['properties'].get('source',{}).get('event_id')})
    cases=[]; missing_newness=0
    for nodes in streams.values():
        for i,anchor in enumerate(nodes):
            if anchor.get('activity')!=q['anchor_activity']: continue
            if q['require_new_exploration']:
                novelty=anchor['properties'].get('facets',{}).get('new_exploration')
                if novelty is not True:
                    if novelty is not False: missing_newness+=1
                    continue
            later=nodes[i+1:i+1+q['within_units']]; matches=[]
            for n in later:
                for e in outgoing[n['id']]:
                    if e['type']!=q['relation']: continue
                    if not edge_available(e,n,event_indices):continue
                    target=by_id[e['target']]
                    # A revision/assessment points to its earlier object. A future
                    # or unmaterialized object cannot establish this requirement.
                    if target['event_index'] is None or target['trajectory_id']!=n['trajectory_id']: continue
                    nstart=n['properties'].get('source',{}).get('start',0)
                    tend=node_end(target)
                    if (target['event_index'],tend)>(n['event_index'],nstart): continue
                    witness=path_witness(spec,e,anchor,n,by_id,adjacency,budget,event_indices,context) if spec else None
                    if spec and witness is None: continue
                    anchors=[x for x in outgoing[n['id']] if x['target']==anchor['id'] and x['type'] in {'uses_evidence','responds_to'}]
                    matches.append({'edge_id':e['id'],'source':e['source'],'target':e['target'],
                                    'evidence_links':witness['edge_ids'] if witness else [x['id'] for x in anchors],
                                    **({'evidence_path':witness} if witness else {})})
            cases.append({'anchor':anchor['id'],'matches':matches,'status':'matched' if matches else 'no_recorded_match',
                          'inspected_window':[n['id'] for n in later]})
    positive=sum(bool(c['matches']) for c in cases)
    return {'graph_id':graph['id'],'run_id':graph['run_id'],'observer':graph['observer'],'metadata':graph['metadata'],
        'requirement_hash':digest(q),'requirement':q,'anchors':len(cases),'matched_anchors':positive,
        'without_recorded_match':len(cases)-positive,'unclassified_newness':missing_newness,
        'recorded_match_fraction':positive/len(cases) if cases else None,
        'behavior_rate':None,'status':'recorded_matches_only' if cases else 'required_evidence_unavailable',
        'cases':cases,'engine_version':ENGINE_VERSION,'path_edge_visits':budget[0],'rejected_relationships':list(rejected.values()),
        'association':'stored_evidence_path' if spec else 'temporal_only',
        'limitations':['The fraction counts recorded graph matches, not all actual behavior. Missing semantic edges are not negatives.',
            'The question text is a saved research note. The explicit fields below it are the executed definition.',
            'An explicit path binds the later relationship to the starting unit. Without a path, the match is temporal association only. Neither proves causation.',
            'Each matched relationship retains one complete path witness, not every possible path. Intermediate objects must be materialized in the same trajectory by the later unit cutoff.',
            'New exploration requires an explicit new_exploration facet. Inspect is not automatically a new direction.']}


def run(store, body):
    q=validate(body.get('requirement')); ids=body.get('graph_ids')
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(x,str) for x in ids):
        raise InputError('Select 1–100 graph snapshots')
    ids=list(dict.fromkeys(ids)); graphs=[graph_store.read(store,i) for i in ids]
    if len({g['observer'] for g in graphs})!=1: raise InputError('Use one observer definition per query population')
    if len({g['run_id'] for g in graphs})!=len(graphs): raise InputError('Choose one annotation snapshot per rollout')
    results=[evaluate(g,q) for g in graphs]
    current={g['id'] for g in graph_store.catalog(store)['graphs']}
    with store.connect() as c:
        state={g['run_id']:c.execute('SELECT state FROM rollout_revisions WHERE run_id=? ORDER BY created_at DESC,revision DESC LIMIT 1',(g['run_id'],)).fetchone() for g in graphs}
    groups=defaultdict(list); excluded=0; incomplete=0; historical=0
    for r in results:
        r['snapshot_state']=state[r['run_id']][0] if state[r['run_id']] else 'imported_snapshot'
        if r['graph_id'] not in current:historical+=1;continue
        if r['snapshot_state'] in {'in_progress','failed'}:incomplete+=1;continue
        m=r['metadata']; step=m.get('training_step')
        if not m.get('experiment') or type(step) is not int or step<0: excluded+=1;continue
        cohort={k:m.get(k) for k in ('experiment','environment','environment_version','split','task_revision','sampling','training_step_basis','reward_definition','source_selection')}
        cohort['observer']=r['observer']
        cohort['graph_schema']=graph_store.VERSION
        cohort['query_engine']=ENGINE_VERSION
        groups[dumps(cohort)].append(r)
    series=[]
    for key,items in groups.items():
        steps=defaultdict(list)
        for r in items: steps[r['metadata']['training_step']].append(r)
        bins=[]
        for step,rows in sorted(steps.items()):
            denominator=sum(r['anchors'] for r in rows); numerator=sum(r['matched_anchors'] for r in rows)
            bins.append({'step':step,'numerator':numerator,'denominator':denominator,
                'value':numerator/denominator if denominator else None,'rollouts':len(rows),
                'missing_newness':sum(r['unclassified_newness'] for r in rows)})
        series.append({'cohort':json.loads(key),'bins':bins})
    return {'schema':q['schema'],'engine_version':ENGINE_VERSION,'requirement':q,'requirement_hash':digest(q),'results':results,'training':series,
            'missing_training_coordinates':excluded,'incomplete_snapshots':incomplete,'historical_graphs':historical}


def save(store, raw):
    q=validate(raw); identifier='requirement-'+digest(q)
    with store.connect() as c:
        c.execute('INSERT OR IGNORE INTO graph_requirements VALUES (?,?,?)',(identifier,dumps(q),datetime.now(timezone.utc).isoformat()))
    return {'id':identifier,'requirement':q}


def saved(store):
    with store.connect() as c:
        return [{'id':r['id'],'requirement':json.loads(r['document'])} for r in c.execute('SELECT * FROM graph_requirements ORDER BY created_at')]
