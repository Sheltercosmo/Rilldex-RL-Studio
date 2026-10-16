"""Materialize historical requested objects without inventing semantic judgments.

Clauses are content objects shared by record versions, never extra activities.
Availability at dispatch does not establish applicability or satisfaction.
"""
from copy import deepcopy
from collections import Counter
from .schema import InputError, digest

VERSION='requested-version-history/1'
LIMIT=('Source-attributed requested records and condition clauses. A recorded revision is not a '
       'semantic term change. Requirements, requested checks and attributed claims remain distinct. '
       'Membership or retirement does not establish applicability, permission, satisfaction or completion.')


def materialize(run,document,graph,observations=None,observation_schema=None):
    from .request_changes import changes
    ledger=changes(run,document)
    inspected={c['id']:c for c in observations or []}
    if observations is not None and (len(inspected)!=len(observations) or set(inspected)!={c['id'] for c in ledger}):
        raise InputError('Requested comparison coverage differs from recorded history')
    nodes={n['id']:n for n in graph['nodes']};edges={e['id']:e for e in graph['edges']}
    events={e['id']:e for e in run['events']};units={u['id']:u for u in document['units']}
    def node(identifier,kind,properties,owner):
        value={'id':identifier,'kind':kind,'activity':None,'trajectory_id':owner['trajectory_id'],
               'event_index':events[owner['source']['event_id']]['index'],'properties':deepcopy(properties)}
        if identifier in nodes and nodes[identifier]!=value:raise InputError('Requested object content collision')
        nodes[identifier]=value
    def edge(source,target,kind,properties):
        if source not in nodes or target not in nodes:raise InputError('Missing requested object endpoint')
        value={'source':source,'target':target,'type':kind,'properties':deepcopy(properties)}
        key='edge-'+digest(value);edges[key]={'id':key,**value}
    for change in ledger:
        for record in [r for r in (change['before'],change['after']) if r]:
            rid='requested-version:'+record['version_id'];owner=units[record['source_unit_id']]
            node(rid,'requested_work_version',record,owner)
            edge(owner['id'],rid,'expresses_requested_version',{'basis':'saved requested-work extraction','evidence':record['evidence']})
            for index,clause in enumerate(record.get('clauses',[])):
                cid='requested-clause:'+clause['version_id'];origin=units[clause['source_unit_id']]
                node(cid,'requested_clause_version',{**clause,'record_id':record['id']},origin)
                edge(rid,cid,'contains_requested_clause',{'position':index,'basis':'saved condition contents'})
                edge(origin['id'],cid,'expresses_requested_clause',{'basis':'saved condition contents','evidence':clause['evidence']})
        after,before=change['after'],change['before'];after_id='requested-version:'+after['version_id']
        if before:
            review=inspected.get(change['id'],{})
            edge(after_id,'requested-version:'+before['version_id'],'updates_requested_version',
                 {'operation':change['operation'],'status':review.get('status','not_inspected'),
                  'selections':review.get('selections',{}),'requests':review.get('requests',{}),
                  'source_unit_id':change['source_unit_id'],'cutoff':change['source'],
                  'basis':observation_schema or VERSION,'evidence':[change['source']],
                  'limit':'Requested terms only; no active-goal, drift, execution or fulfillment assertion.'})
            previous={c['id']:c for c in before.get('clauses',[])}
            for clause in after.get('clauses',[]):
                old=previous.get(clause['id'])
                if old and old['version_id']!=clause['version_id']:
                    edge('requested-clause:'+clause['version_id'],'requested-clause:'+old['version_id'],
                         'updates_requested_clause',{'source_unit_id':change['source_unit_id'],
                          'cutoff':change['source'],'basis':'saved condition edit','evidence':clause['evidence'],
                          'limit':'Recorded content revision; semantic equivalence has not been assessed.'})
        for retired in change.get('retired_clauses',[]):
            edge(after_id,'requested-clause:'+retired['previous']['version_id'],'retires_requested_clause',
                 {'reason':retired['reason'],'evidence':retired['evidence'],'source_unit_id':change['source_unit_id'],
                  'cutoff':change['source'],'basis':'saved explicit clause retirement',
                  'limit':'No longer in these recorded terms; not proof of fulfillment or falsity.'})
    clauses=[n for n in nodes.values() if n['kind']=='requested_clause_version']
    versions=[n for n in nodes.values() if n['kind']=='requested_work_version']
    counts={'records':len({(c['trajectory_id'],c['record_id']) for c in ledger}),
            'record_versions':len(versions),'revisions':sum(c['operation']=='revise' for c in ledger),
            'clause_versions':len(clauses),'clause_kinds':dict(Counter(n['properties']['kind'] for n in clauses)),
            'clause_retirements':sum(e['type']=='retires_requested_clause' for e in edges.values()),
            'condition_versions_without_clauses':sum(n['properties']['kind']=='condition' and 'clauses' not in n['properties'] for n in versions)}
    header={'schema':VERSION,'requested_work_hash':digest(document['requested_work']),
            'term_comparison':observation_schema or 'uninspected','counts':counts,'limits':LIMIT}
    graph['nodes']=list(nodes.values());graph['edges']=list(edges.values())
    graph['semantic_context']['requested_history']=header
    return header


def finish(graph,annotation):
    from . import graph_store
    graph['annotation_hash']=digest(annotation)
    graph['nodes'].sort(key=lambda n:n['id']);graph['edges'].sort(key=lambda e:e['id'])
    graph['counts']={'nodes':len(graph['nodes']),'edges':len(graph['edges']),
                     'unresolved_endpoints':sum(n['kind']=='unresolved_reference' for n in graph['nodes'])}
    graph.pop('id',None);graph={'id':'graph-'+digest(graph),**graph};graph_store.validate(graph)
    return graph


def export_graph(run,document):
    """Export already-selected records; no model or term-comparison call occurs."""
    from . import graph_store,request_dispatch
    graph=graph_store.build(run,{'observer':{'id':'requested-history-'+digest([VERSION,document])[:24],
        'label':'Requested conditions and action context · experimental'},'document':document},include_requested=False)
    history=materialize(run,document,graph)
    dispatch=request_dispatch.materialize(run,document,graph)
    return finish(graph,[document,history,dispatch])
