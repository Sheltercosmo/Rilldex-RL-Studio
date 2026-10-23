"""Built-in operator registrations; domain behavior stays out of the DAG engine."""
from .schema import digest
from . import graph_store, behavior_sequences, work_state, work_episodes, repair_phases
from . import work_navigation, adaptation_patterns, history_evidence, feedback_opportunities, feedback_timing, work_order
from . import recovery_windows, retry_outcomes, graph_queries, work_visits, work_subjects, work_return_references
from . import declared_plans, work_consistency, work_structure_metrics, work_hierarchy
from . import repeated_work
from . import source_evidence, requested_evidence
from .capabilities import CAPABILITY_VERSION
from .analysis_contracts import CONTRACTS
from .analysis_registry import Registry, Operation, Parameters, Dependencies, Dependency, Binding


def save_graph(store, graph):
    with store.connect() as connection:
        graph_store.save(connection, graph)
    return graph['id']


def recorded_state(ctx):
    value = work_state.derive(ctx.run)
    value['graph_id'] = work_graph(ctx.store, ctx.run, value)
    return value


def recorded_history(ctx):
    value = history_evidence.evaluate(ctx.run, ctx.params['query'])
    value['graph_id'] = save_graph(ctx.store, history_evidence.graph(ctx.run, value))
    return value


def recorded_plans(ctx):
    value=declared_plans.project(ctx.run)
    value['graph_id']=save_graph(ctx.store,declared_plans.evidence_graph(ctx.run,value))
    return value


def recovery(ctx):
    state = ctx.inputs[0]
    value = recovery_windows.project(state, ctx.graph)
    evidence = recovery_windows.evidence_graph(
        ctx.graph, graph_store.read(ctx.store, state['graph_id']), value)
    value['graph_id'] = save_graph(ctx.store, evidence)
    return {'id': 'recovery-windows-' + digest(value), **value}


def next_check(ctx):
    prior = ctx.inputs[0]
    value = retry_outcomes.project(prior, ctx.graph)
    # Start from source + state, not the recovery graph's later-check edges.
    from .investigation_plans import read_output
    state = read_output(ctx.store, prior['state_projection_id'])
    evidence = recovery_windows.evidence_graph(
        ctx.graph, graph_store.read(ctx.store, state['graph_id']), value,
        version=retry_outcomes.VERSION, observer='next-check-evidence/1',
        label='First recheck with independent outcome and captured input change',
        opportunity_key='next_check_opportunity_id')
    value['graph_id'] = save_graph(ctx.store, evidence)
    return {'id': 'retry-outcomes-' + digest(value), **value}


def work_graph(store,run,result):
    """Store state objects and relations as graph data, preserving source graphs."""
    g=graph_store.build(run);nodes=g['nodes'];edges=g['edges'];by_event={e['id']:e for e in run['events']}
    def node(key,kind,properties,eid):
        e=by_event[eid];nodes.append({'id':key,'kind':kind,'activity':None,'trajectory_id':e['trajectory_id'],
                                    'event_index':e['index'],'properties':properties})
    def edge(a,b,kind):
        v={'source':a,'target':b,'type':kind,'properties':{'basis':'recorded work-state evidence','version':work_state.VERSION}}
        edges.append({'id':'edge-'+digest(v),**v})
    for s in result['snapshots']:
        sid='snapshot:'+s['id'];node(sid,'artifact_snapshot',s,s['event_id']);edge(sid,'event:'+s['event_id'],'grounded_in')
        for obj,version in s['objects'].items():
            oid='object-version:'+digest([s['id'],obj,version]);node(oid,'object_version',{'object':obj,'version':version},s['event_id']);edge(sid,oid,'contains_version')
    for v in result['file_views']:
        key='file-view:'+v['event_id'];node(key,'file_view',v,v['event_id']);edge(key,'event:'+v['event_id'],'grounded_in')
    for q in result['checks']:
        key='check:'+q['action_id'];node(key,'check',q,q['action_id']);edge(key,'event:'+q['action_id'],'requested_by')
        if q['result_event_id']:edge(key,'event:'+q['result_event_id'],'result_recorded_at')
        if q['snapshot_id']:edge(key,'snapshot:'+q['snapshot_id'],'checked_snapshot')
    for e in result['edits']:
        edge('event:'+e['action_id'],'snapshot:'+e['before_snapshot_id'],'input_snapshot')
        edge('event:'+e['result_event_id'],'snapshot:'+e['after_snapshot_id'],'effect_snapshot')
    for d in result['deliveries']:
        key='delivery-verification:'+digest([d['event_id'],d['requirement']])
        node(key,'delivery_verification',d,d['event_id']);edge(key,'event:'+d['event_id'],'grounded_in')
        edge(key,'snapshot:'+d['snapshot_id'],'delivered_snapshot')
        for q in d['check_history']:
            if q['availability']=='pending_at_delivery':edge(key,'event:'+q['action_id'],'pending_check_at_delivery')
            else:edge(key,'check:'+q['action_id'],'considers_check_at_delivery')
    g.update(observer=work_state.VERSION,observer_label='Recorded work state',annotation_hash=digest(result),
             semantic_context={'schema':work_state.VERSION,'notice':'Recorded object state; no new semantic activity labels'},
             counts={'nodes':len(nodes),'edges':len(edges),'unresolved_endpoints':0})
    g.pop('id');g['nodes']=sorted(nodes,key=lambda n:n['id']);g['edges']=sorted({e['id']:e for e in edges}.values(),key=lambda e:e['id'])
    g['counts']['edges']=len(g['edges']);g={'id':'graph-'+digest(g),**g}
    with store.connect() as c:graph_store.save(c,g)
    return g['id']


def compare_work(values,focus,reference):
    groups={}
    for name,ids in [('focus',focus),('reference',reference)]:
        selected=[v for v in values if v['run_id'] in ids];metrics={}
        for key in ('recovery','applicable_verification','check_binding'):
            ms=[v['metrics'][key] for v in selected];n=sum(m['numerator'] for m in ms);d=sum(m['denominator'] for m in ms)
            metrics[key]={'numerator':n,'denominator':d,'opportunities':sum(m['opportunities'] for m in ms),
                          'unknown':sum(m['unknown'] for m in ms),'value':n/d if d else None,
                          'mean_rollout_value':sum(m['value'] for m in ms if m['value'] is not None)/sum(m['value'] is not None for m in ms) if any(m['value'] is not None for m in ms) else None}
        groups[name]={'rollouts':len(ids),'measured_rollouts':len(selected),'metrics':metrics}
    return {'groups':groups,'records':values,'definition':'Primary rates pool eligible opportunities; mean rollout rates are retained separately. Unknown opportunities are shown, never treated as failures.'}


REGISTRY = Registry()
SOURCE_GRAPH = Parameters(('run_id', 'source_hash', 'graph_id'),
                          identifiers=('run_id', 'source_hash', 'graph_id'))
COMPARISON = Parameters(('focus', 'reference'), ('width',), comparison=True)


def add(name, version, execute, *, parameters=SOURCE_GRAPH,
        dependencies=Dependencies(), binding=Binding()):
    REGISTRY.register(Operation(name, version, CONTRACTS[name], parameters, execute,
                                dependencies, binding))


add('work_structure', work_structure_metrics.VERSION+'|'+work_hierarchy.VERSION, lambda c: work_structure_metrics.project(c.graph))
add('sequence', behavior_sequences.VERSION, lambda c: behavior_sequences.project(c.graph))
add('work_state', work_state.VERSION, recorded_state)
add('evidence_search', source_evidence.VERSION, lambda c: source_evidence.search(c.run, c.params['query']),
    parameters=Parameters(('run_id','source_hash','query'), identifiers=('run_id','source_hash'),
        validators=(('query',source_evidence.validate),)))
add('requested_evidence', requested_evidence.VERSION+'|'+source_evidence.VERSION,
    lambda c: requested_evidence.review(c.run, c.graph, c.params['query']),
    parameters=Parameters(('run_id','source_hash','graph_id','query'),
        identifiers=('run_id','source_hash','graph_id'), validators=(('query',requested_evidence.validate),)))
add('declared_plans', declared_plans.VERSION, recorded_plans,
    parameters=Parameters(('run_id','source_hash'),identifiers=('run_id','source_hash')))
add('work_return_references', work_return_references.VERSION + '|' + work_navigation.VERSION + '|' + work_visits.VERSION,
    lambda c: work_return_references.evaluate(c.graph, c.params['query'], recurrence_order=c.params.get('recurrence_order'),scope_consistency=c.params.get('scope_consistency')),
    parameters=Parameters(('run_id', 'source_hash', 'graph_id', 'query'), ('recurrence_order','scope_consistency'),
        identifiers=('run_id', 'source_hash', 'graph_id'), validators=(('query', work_return_references.validate), ('recurrence_order',work_order.validate),('scope_consistency',work_consistency.validate))))
add('work_visits', work_visits.VERSION + '|' + work_subjects.NAV_VERSION,
    lambda c: work_visits.project(c.graph,recurrence_order=c.params.get('recurrence_order'),scope_consistency=c.params.get('scope_consistency')),
    parameters=Parameters(('run_id','source_hash','graph_id'),('recurrence_order','scope_consistency'),
        identifiers=('run_id','source_hash','graph_id'),validators=(('recurrence_order',work_order.validate),('scope_consistency',work_consistency.validate))))
add('work_episodes', work_episodes.VERSION, lambda c: work_episodes.project(c.graph))
add('repeated_work', repeated_work.RECIPE, lambda c: repeated_work.project(c.graph))
add('repair_phases', repair_phases.VERSION, lambda c: repair_phases.project(c.run, c.graph['id']))
add('work_navigation', work_navigation.VERSION, lambda c: work_navigation.project(c.graph,target_relations=c.params.get('target_relations'),recurrence_order=c.params.get('recurrence_order')),
    parameters=Parameters(('run_id','source_hash','graph_id'),('target_relations','recurrence_order'),
        identifiers=('run_id','source_hash','graph_id'),validators=(('target_relations',work_navigation.validate_target_relations),('recurrence_order',work_order.validate))))
add('adaptation_patterns', adaptation_patterns.VERSION, lambda c: adaptation_patterns.project(c.graph))
add('feedback_opportunities', feedback_opportunities.VERSION, lambda c: feedback_opportunities.project(c.graph))
add('feedback_timing', feedback_timing.VERSION, lambda c: feedback_timing.project(c.graph))
add('recovery_windows', recovery_windows.VERSION + '|' + work_state.VERSION + '|' + feedback_opportunities.VERSION,
    recovery, parameters=Parameters(('graph_id',), identifiers=('graph_id',)),
    dependencies=Dependencies((Dependency('work_state', 'recorded_state'),)),
    binding=Binding('dependency', source_input=0))
add('retry_outcomes', retry_outcomes.VERSION + '|' + REGISTRY.versions['recovery_windows'],
    next_check, parameters=Parameters(('graph_id',), identifiers=('graph_id',)),
    dependencies=Dependencies((Dependency('recovery_windows', 'recovery'),)),
    binding=Binding('dependency', source_input=0))
add('relation_query', graph_queries.ENGINE_VERSION,
    lambda c: graph_queries.evaluate(c.graph, c.params['query']),
    parameters=Parameters(('run_id', 'source_hash', 'graph_id', 'query'),
        identifiers=('run_id', 'source_hash', 'graph_id'), validators=(('query', graph_queries.validate),)))
add('history_evidence', history_evidence.VERSION + '|' + CAPABILITY_VERSION + '|' + history_evidence.GRAPH_VERSION,
    recorded_history, parameters=Parameters(('run_id', 'source_hash', 'query'),
        identifiers=('run_id', 'source_hash'), validators=(('query', history_evidence.validate),)))

for name, version, function, complete in [
    ('compare_sequences', behavior_sequences.VERSION,
     lambda c: behavior_sequences.compare(c.inputs, c.params['focus'], c.params['reference'], c.params.get('width', 10)), False),
    ('compare_work', 'work-comparison/1',
     lambda c: compare_work(c.inputs, c.params['focus'], c.params['reference']), True),
    ('compare_episodes', work_episodes.VERSION,
     lambda c: work_episodes.compare(c.inputs, c.params['focus'], c.params['reference']), False),
    ('compare_repair_phases', repair_phases.VERSION,
     lambda c: repair_phases.compare(c.inputs, c.params['focus'], c.params['reference']), False),
    ('compare_adaptation', adaptation_patterns.VERSION,
     lambda c: adaptation_patterns.compare(c.inputs, c.params['focus'], c.params['reference']), False),
    ('compare_recovery_windows', recovery_windows.VERSION,
     lambda c: recovery_windows.compare(c.inputs, c.params['focus'], c.params['reference']), True),
]:
    add(name, version, function, parameters=COMPARISON,
        dependencies=Dependencies(variadic=CONTRACTS[name]['dependency_operation']),
        binding=Binding('population', complete_population=complete))
