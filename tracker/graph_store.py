"""Versioned property graphs over immutable rollout and observer snapshots.

SQLite is the embedded graph database: typed nodes, directed edges and adjacency
indexes are persistent data. Rendering never owns relationships.
"""
import json
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
from .schema import digest, dumps, InputError

VERSION = 'rollout-property-graph/1'


def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS rollout_graphs (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
      observer TEXT NOT NULL, source_hash TEXT NOT NULL, annotation_hash TEXT,
      document TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS graph_run_observer ON rollout_graphs(run_id,observer,created_at);
    CREATE TABLE IF NOT EXISTS graph_nodes (
      graph_id TEXT NOT NULL REFERENCES rollout_graphs(id), id TEXT NOT NULL,
      kind TEXT NOT NULL, activity TEXT, trajectory_id TEXT, event_index INTEGER,
      document TEXT NOT NULL, PRIMARY KEY(graph_id,id));
    CREATE INDEX IF NOT EXISTS graph_node_activity ON graph_nodes(graph_id,activity,event_index);
    CREATE TABLE IF NOT EXISTS graph_edges (
      graph_id TEXT NOT NULL, id TEXT NOT NULL, source TEXT NOT NULL,
      target TEXT NOT NULL, type TEXT NOT NULL, document TEXT NOT NULL,
      PRIMARY KEY(graph_id,id),
      FOREIGN KEY(graph_id,source) REFERENCES graph_nodes(graph_id,id),
      FOREIGN KEY(graph_id,target) REFERENCES graph_nodes(graph_id,id));
    CREATE INDEX IF NOT EXISTS graph_outgoing ON graph_edges(graph_id,source,type);
    CREATE INDEX IF NOT EXISTS graph_incoming ON graph_edges(graph_id,target,type);
    CREATE INDEX IF NOT EXISTS graph_relation_type ON graph_edges(graph_id,type);
    CREATE TABLE IF NOT EXISTS graph_requirements (
      id TEXT PRIMARY KEY, document TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')


def build(run, bundle=None, *, include_requested=True):
    nodes = {}; edges = {}; events = {e['id']: e for e in run['events']}
    def node(identifier, kind, properties, event=None, activity=None):
        if identifier in nodes: raise InputError('Duplicate graph node identity')
        nodes[identifier] = {'id': identifier, 'kind': kind, 'activity': activity,
            'trajectory_id': (event or {}).get('trajectory_id'),
            'event_index': (event or {}).get('index'), 'properties': properties}
    def edge(source, target, kind, properties):
        value = {'source': source, 'target': target, 'type': kind, 'properties': properties}
        identifier = 'edge-' + digest(value)
        edges[identifier] = {'id': identifier, **value}
    previous = {}
    for e in run['events']:
        identifier = 'event:' + e['id']; node(identifier, 'event', e, e)
        trajectory = e['trajectory_id']
        if trajectory in previous:
            edge(previous[trajectory], identifier, 'next_record', {'basis': 'source_order', 'causal': False})
        previous[trajectory] = identifier
    if run.get('adapter_version') == 'environment-episode/2':
        for e in run['events']:
            parent = events.get(e.get('parent_id'))
            if (e['kind'] == 'action' and parent and parent['kind'] == 'message'
                    and parent['trajectory_id'] == e['trajectory_id'] and parent['index'] < e['index']):
                edge('event:'+parent['id'], 'event:'+e['id'], 'parent_message',
                     {'basis':e['parent_link_basis'], 'semantic_causality':False})
    # Source-native action/result identity remains useful without semantic tags.
    if run.get('adapter') == 'weave':
        for e in run['events']:
            if e.get('native_parent_event_id') in events:
                edge('event:'+e['native_parent_event_id'], 'event:'+e['id'], 'contains_call',
                     {'basis':'weave_parent_id', 'semantic_causality':False})
            if e.get('call_event_id') in events:
                edge('event:'+e['call_event_id'], 'event:'+e['id'], 'call_'+e['weave_record_role'],
                     {'basis':'weave_record_field', 'source_pointer':e['source_pointer'], 'semantic_causality':False})
    from .capabilities import links
    for action, responses in links(run)['by_action'].items():
        for response in responses:
            rid = response['id'] if isinstance(response, dict) else response
            if action in events and rid in events:
                edge('event:'+rid, 'event:'+action, 'response_to', {'basis': 'source_action_result_identity'})
    observer = {'id': 'source', 'label': 'Recorded source'}; annotation_hash = None; semantic_context = None
    if bundle is not None:
        d = bundle['document']
        if d['source_hash'] != digest(run): raise InputError('Graph annotation source mismatch')
        observer = bundle['observer']; annotation_hash = digest(d)
        semantic_context = {'schema':d.get('schema'),'provenance':d.get('provenance'),
                            'review_notes':d.get('review_notes',[]),
                            'notice':'Review notes are retained alongside raw selected relations. They are not silently applied as replacement edges.'}
        # Retain the observations needed to interpret identity edges, including
        # independent disagreement. A missing comparison is not same procedure.
        semantic_context['work_observations']={
            'identity_reviews':d.get('action_target_review',[]),
            'method_schema':d.get('method_comparison',{}).get('schema'),
            'method_observations':d.get('method_comparison',{}).get('observations',[])}
        if d.get('operation_outcomes'):
            from .operation_outcomes import action_outcomes, VERSION as OUTCOME_VERSION
            if d['operation_outcomes'].get('schema') == OUTCOME_VERSION:
                semantic_context['operation_results'] = deepcopy(action_outcomes(run, d['operation_outcomes']))
        if d.get('execution_reports'):
            from .execution_reports import validate, VERSION as REPORT_VERSION
            if d['execution_reports'].get('schema')==REPORT_VERSION:validate(run,d['execution_reports'])
            semantic_context['execution_reports']=deepcopy(d['execution_reports'])
        if d.get('check_correspondence'):
            checks=d['check_correspondence']
            if checks.get('source_hash')!=digest(run) or checks.get('requested_work_hash')!=digest(d.get('requested_work')):
                raise InputError('Requested-check observations have different source or request dependencies')
            semantic_context['requested_check_observations']=deepcopy(checks)
        if d.get('provenance',{}).get('assessment_scope'):
            semantic_context['feedback_observations']={
                'scope_version':d['provenance']['assessment_scope'],
                'observations':d.get('assessment_review',[])}
        for u in d.get('units', []):
            event = events.get(u.get('source', {}).get('event_id'))
            node(u['id'], 'unit', u, event, u.get('activity'))
            if event: edge(u['id'], 'event:'+event['id'], 'grounded_in', {'basis': 'source_span', 'source': u.get('source')})
            for step in (u.get('plan_structure') or {}).get('steps', []):
                sid = u['id']+':'+step['id']
                node(sid, 'plan_step', step, event)
                edge(u['id'], sid, 'contains_plan_step', {'basis': 'selected_plan_content'})
        # Keep every recorded relation, including endpoints not yet materialized by
        # a source adapter. Such endpoints are explicit references, never fake units.
        for rel in d.get('relations', []):
            source, target = rel.get('from'), rel.get('to')
            if not isinstance(source, str) or not isinstance(target, str) or not isinstance(rel.get('type'), str):
                raise InputError('Relation needs typed directed endpoints')
            for endpoint in (source, target):
                if endpoint not in nodes:
                    node(endpoint, 'unresolved_reference', {'label': endpoint, 'reason': 'Endpoint content not materialized by this projection'})
            edge(source, target, rel['type'], rel)
        if d.get('work_context'):
            from .work_scopes import materialize
            semantic_context['work_scopes'] = materialize(run,d,node,edge)
    from .declared_work_tree import materialize as materialize_declared_work
    materialize_declared_work(run, node, edge)
    header = {'schema': VERSION, 'run_id': run['id'], 'observer': observer['id'],
        'observer_label': observer['label'], 'source_hash': digest(run),
        'annotation_hash': annotation_hash, 'metadata': run['metadata'],
        'semantic_context':semantic_context,
        'adapter_version': run['adapter_version'],
        'coverage': {'semantic_relations': 'partial' if bundle else 'unavailable',
                     'new_exploration': 'unavailable',
                     'note': 'Stored edges are observations. Missing semantic edges do not establish absence; temporal order does not establish causality.'},
        'counts': {'nodes': len(nodes), 'edges': len(edges),
                   'unresolved_endpoints': sum(n['kind']=='unresolved_reference' for n in nodes.values())}}
    from .work_state import capture
    captured_state = capture(run)
    if captured_state is not None:
        header['work_state_capture'] = deepcopy(captured_state)
    if bundle is not None:
        from .measurement_lineage import semantic_input_hash
        header['metric_input_hash']=semantic_input_hash(bundle['document'])
    content = {**header, 'nodes': sorted(nodes.values(), key=lambda n:n['id']), 'edges': sorted(edges.values(), key=lambda e:e['id'])}
    if include_requested and bundle and bundle['document'].get('requested_work',{}).get('status')=='complete':
        from . import requested_graph, request_dispatch
        history=requested_graph.materialize(run,bundle['document'],content)
        dispatch=request_dispatch.materialize(run,bundle['document'],content)
        return requested_graph.finish(content,[bundle['document'],history,dispatch])
    return {'id': 'graph-'+digest(content), **content}


def validate(graph):
    content={k:v for k,v in graph.items() if k!='id'}
    content['nodes']=sorted(content['nodes'],key=lambda n:n['id'])
    content['edges']=sorted(content['edges'],key=lambda e:e['id'])
    if graph['id']!='graph-'+digest(content): raise InputError('Graph content does not match its immutable identity')


def save(c, graph):
    validate(graph)
    identifier = graph['id']
    if c.execute('SELECT 1 FROM rollout_graphs WHERE id=?', (identifier,)).fetchone(): return identifier
    header = {k:v for k,v in graph.items() if k not in {'nodes','edges'}}
    c.execute('INSERT INTO rollout_graphs VALUES (?,?,?,?,?,?,?)', (identifier, graph['run_id'], graph['observer'],
        graph['source_hash'], graph['annotation_hash'], dumps(header), datetime.now(timezone.utc).isoformat()))
    c.executemany('INSERT INTO graph_nodes VALUES (?,?,?,?,?,?,?)', [(identifier,n['id'],n['kind'],n.get('activity'),n.get('trajectory_id'),n.get('event_index'),dumps(n)) for n in graph['nodes']])
    c.executemany('INSERT INTO graph_edges VALUES (?,?,?,?,?,?)', [(identifier,e['id'],e['source'],e['target'],e['type'],dumps(e)) for e in graph['edges']])
    return identifier


def read(store, identifier):
    with store.connect() as c:
        row = c.execute('SELECT document FROM rollout_graphs WHERE id=?', (identifier,)).fetchone()
        if row is None: raise KeyError(identifier)
        value = json.loads(row[0])
        value['nodes'] = [json.loads(r[0]) for r in c.execute('SELECT document FROM graph_nodes WHERE graph_id=? ORDER BY event_index,id',(identifier,))]
        value['edges'] = [json.loads(r[0]) for r in c.execute('SELECT document FROM graph_edges WHERE graph_id=? ORDER BY id',(identifier,))]
    validate(value)
    return value


def catalog(store, *, run_id=None, run_ids=None):
    # Query latest producer snapshots without loading every trace or rebuilding maps.
    # Database insertion order breaks wall-clock ties between annotation versions.
    # This is review history, never a rollout/training clock.
    if run_id is not None and (not isinstance(run_id,str) or not run_id):
        raise InputError('Choose a nonempty rollout snapshot ID')
    if run_ids is not None and (run_id is not None or not isinstance(run_ids,(list,tuple)) or len(run_ids)>20000
            or any(not isinstance(i,str) or not i for i in run_ids)):
        raise InputError('Choose at most 20,000 exact rollout snapshot IDs')
    # An exact detail view must still open an older immutable source snapshot.
    # Keep the ordinary catalog restricted to current producer revisions.
    where='g.run_id=?' if run_id is not None else '''(NOT EXISTS (SELECT 1 FROM rollout_revisions r WHERE r.run_id=g.run_id)
            OR EXISTS (SELECT 1 FROM rollout_revisions r WHERE r.run_id=g.run_id AND r.revision=(
              SELECT max(r2.revision) FROM rollout_revisions r2 WHERE r2.producer=r.producer AND r2.rollout_id=r.rollout_id)))'''
    args=(run_id,) if run_id is not None else ()
    if run_ids is not None:
        where='g.run_id IN (SELECT value FROM json_each(?))'; args=(json.dumps(run_ids),)
    with store.connect() as c:
        rows = c.execute('SELECT g.document,g.created_at FROM rollout_graphs g WHERE '+where+'''
            AND g.rowid=(SELECT max(h.rowid) FROM rollout_graphs h WHERE h.run_id=g.run_id AND h.observer=g.observer)
            ORDER BY g.rowid''',
                         args).fetchall()
        count = c.execute('SELECT count(*) FROM rollout_graphs').fetchone()[0]
    latest = {}
    for row in rows:
        value = json.loads(row[0]); value['created_at'] = row[1]
        # Catalog carries identities/counts; full provenance/review notes remain
        # available from the immutable graph detail endpoint.
        value.pop('semantic_context',None)
        latest[(value['run_id'],value['observer'])] = value
    values = list(latest.values())
    return {'schema':VERSION,'graphs':values,'stored_versions':count,
            'indexed_rollouts':len({g['run_id'] for g in values}),
            'semantic_graphs':sum(g['observer']!='source' for g in values)}


def matrices(graph):
    from .graph_sequence import Ordering,VERSION as ORDER_VERSION
    order=Ordering(graph)
    by_id = {n['id']:n for n in graph['nodes']}; relation = Counter(); transitions = Counter()
    for e in graph['edges']:
        if e['type'] in {'grounded_in','next_record'}: continue
        a,b = by_id[e['source']],by_id[e['target']]
        relation[(a.get('activity') or a['kind'],e['type'],b.get('activity') or b['kind'])] += 1
    previous = {};excluded=Counter();possible=0
    units = sorted((n for n in graph['nodes'] if n['kind']=='unit' and n['event_index'] is not None),
                   key=lambda n:(n['event_index'],n['properties'].get('source',{}).get('start',0),n['id']))
    for n in units:
        t = order.scope(n); old = previous.get(t)
        # Unknown activities break the sequence; never bridge omitted labels.
        if old and old.get('activity') and n.get('activity'):
            possible+=1;reason=order.before(old,n)
            if reason:excluded[reason]+=1
            else:transitions[(old['activity'], n['activity'])] += 1
        previous[t] = n
    return {'relations':[{'source':a,'relation':r,'target':b,'count':n} for (a,r,b),n in sorted(relation.items())],
            'transitions':[{'source':a,'target':b,'count':n} for (a,b),n in sorted(transitions.items())],
            'transition_coverage':dict(policy=ORDER_VERSION,possible_pairs=possible,observed_pairs=sum(transitions.values()),
                                       excluded_pairs=sum(excluded.values()),reasons=dict(sorted(excluded.items()))),
            'note':'Transition counts describe adjacent annotated units with established source order within one trajectory and recorded context. Unknown order, parallel dispatches and overlapping spans do not form transitions. Relation counts describe directed stored edges; neither implies causation.'}


def status(store):
    with store.connect() as c:
        sources = c.execute('SELECT count(*),max(imported_at) FROM runs').fetchone()
        graphs = c.execute('SELECT count(*),max(created_at) FROM rollout_graphs').fetchone()
        observations = c.execute('SELECT count(*),max(created_at) FROM rollout_measurements').fetchone()
        jobs = dict(c.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall())
    value = {'imported_snapshots':sources[0],'last_import':sources[1], 'graph_versions':graphs[0],
             'last_graph_update':graphs[1], 'measurement_versions':observations[0],
             'last_measurement_update':observations[1], 'jobs':jobs}
    return {**value,'fingerprint':digest(value),'checked_at':datetime.now(timezone.utc).isoformat()}
