"""Typed deterministic investigation DAG over immutable stored evidence.

Registered operators own domain behavior. The engine validates dependencies and
source bindings before any cache write; HTTP plans cannot import executable code.
"""
import json
from copy import deepcopy
from .schema import InputError, digest, dumps
from . import graph_store, analysis_contracts, analysis_operations
from .analysis_registry import Context
# Compatibility imports for callers of the existing concrete helpers/modules.
from .analysis_operations import work_graph, compare_work, behavior_sequences, repair_phases

VERSION = 'investigation-plan/1'
OPS = analysis_operations.REGISTRY.versions


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS investigation_nodes(
        id TEXT PRIMARY KEY, operation TEXT NOT NULL, document TEXT NOT NULL,
        output_hash TEXT NOT NULL, output_id TEXT);
        CREATE INDEX IF NOT EXISTS investigation_output ON investigation_nodes(output_id);
        CREATE TABLE IF NOT EXISTS investigation_plans(id TEXT PRIMARY KEY, document TEXT NOT NULL);''')


def run_source(store,rid):
    with store.connect() as c:r=c.execute('SELECT document FROM runs WHERE id=?',(rid,)).fetchone()
    if not r:raise InputError('Unknown source rollout')
    return json.loads(r[0])


def registry_or_default(registry):
    return analysis_operations.REGISTRY if registry is None else registry


def validate_plan(plan, *, registry=None):
    """Validate the complete DAG and all parameters before any cache writes."""
    registry = registry_or_default(registry)
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'nodes'}
            or plan['schema'] != VERSION or not isinstance(plan['nodes'], list)
            or not 1 <= len(plan['nodes']) <= 1542):
        raise InputError('Invalid investigation plan')
    preceding = {}
    for node in plan['nodes']:
        if (not isinstance(node, dict) or set(node) != {'name', 'op', 'inputs', 'params'}
                or not isinstance(node['name'], str) or node['name'] in preceding
                or not isinstance(node['op'], str) or node['op'] not in registry
                or not isinstance(node['inputs'], list)
                or any(not isinstance(i, str) for i in node['inputs'])
                or not isinstance(node['params'], dict)):
            raise InputError('Invalid plan node')
        if any(name not in preceding for name in node['inputs']):
            raise InputError('Dependencies must precede their consumer; no cycles')
        operator = registry.get(node['op'])
        operator.dependencies.validate(node['inputs'], preceding)
        operator.parameters.validate(node['params'])
        preceding[node['name']] = node['op']


def bound_sources(store, plan, *, registry=None):
    """Verify every input, including inputs to cached and dependent nodes."""
    registry = registry_or_default(registry)
    validate_plan(plan, registry=registry)
    bindings = {}; runs = {}; graphs = {}
    for node in plan['nodes']:
        params = node['params']; operator = registry.get(node['op'])
        rule = operator.binding
        if rule.mode == 'population':
            ids = [bindings[name]['run']['id'] for name in node['inputs']]
            if len(set(ids)) != len(ids):
                raise InputError('Duplicate rollout contribution')
            if rule.complete_population and set(params['focus'] + params['reference']) != set(ids):
                raise InputError('Work comparison must account for every selected rollout')
            continue
        if rule.mode == 'dependency':
            run = bindings[node['inputs'][rule.source_input]]['run']
            source_hash = digest(run)
        else:
            if params['run_id'] not in runs:
                runs[params['run_id']] = run_source(store, params['run_id'])
            run = runs[params['run_id']]
            source_hash = params['source_hash']
        if digest(run) != source_hash:
            raise InputError('Analysis source binding mismatch')
        for name in node['inputs']:
            upstream = bindings[name]['run']
            if upstream['id'] != run['id'] or digest(upstream) != source_hash:
                raise InputError('Analysis dependency source binding mismatch')
        graph = None
        if 'graph_id' in params:
            if params['graph_id'] not in graphs:
                try:
                    graphs[params['graph_id']] = graph_store.read(store, params['graph_id'])
                except KeyError as exc:
                    raise InputError('Unknown analysis evidence graph') from exc
            graph = graphs[params['graph_id']]
            if graph['source_hash'] != source_hash or graph['run_id'] != run['id']:
                raise InputError('Analysis source binding mismatch')
        bindings[node['name']] = {'run': run, 'graph': graph}
    return bindings


def catalog(*, registry=None):
    return registry_or_default(registry).catalog(analysis_contracts.VERSION)


def preflight(store, plan, *, registry=None):
    registry = registry_or_default(registry)
    bindings = bound_sources(store, plan, registry=registry); nodes = []
    for node in plan['nodes']:
        operator = registry.get(node['op']); spec = operator.contract
        binding = bindings.get(node['name'])
        counts = None; missing = []
        if binding:
            graph = binding['graph'] or {'nodes': [], 'semantic_context': {}}
            counts = analysis_contracts.inventory(binding['run'], graph)
            missing = [key for key in spec['evidence_needs'] if not counts.get(key, 0)]
        nodes.append({
            'name': node['name'], 'operation': node['op'], 'version': registry.versions[node['op']],
            'inputs': node['inputs'], 'grain': spec['grain'], 'evidence_needs': spec['evidence_needs'],
            'recorded_counts': counts, 'missing_evidence': missing,
            'evidence_status': 'inspect_dependencies' if not binding else 'missing_inputs' if missing else 'presence_only',
            'boundary': spec['boundary'], 'validation': spec['validation'], 'new_model_calls': 0,
            'operator': operator.describe(),
        })
    return {
        'schema': 'investigation-preflight/1', 'contract_schema': analysis_contracts.VERSION,
        'definition_hash': digest(plan), 'valid': True, 'persisted': False, 'new_model_calls': 0,
        'nodes': nodes,
        'notice': 'Source identities and DAG types checked. Structural presence is not measurement readiness or semantic accuracy. Projections still validate evidence, eligibility and unknowns. No analysis/cache/model job was run.',
    }


def execute(store, plan, *, registry=None, cache_store=None):
    # Pure projections can read a pinned snapshot while publishing immutable
    # cache entries through the owning workspace. Operator context still uses
    # the read store; operators which themselves write need a writable store.
    cache_store = store if cache_store is None else cache_store
    registry = registry_or_default(registry)
    bindings = bound_sources(store, plan, registry=registry)
    values = {}; receipts = []; hits = 0
    for node in plan['nodes']:
        inputs = [values[name] for name in node['inputs']]
        version = registry.versions[node['op']]
        key = {'operation': node['op'], 'version': version, 'params': node['params'],
               'inputs': [digest(value) for value in inputs]}
        identifier = 'analysis-node-' + digest(key)
        with store.connect() as connection:
            row = connection.execute('SELECT document,output_hash FROM investigation_nodes WHERE id=?', (identifier,)).fetchone()
        if row:
            value = json.loads(row[0])
            if digest(value) != row[1]:
                raise InputError('Cached analysis output changed')
            hits += 1
        else:
            binding = bindings.get(node['name'], {})
            context = Context(store, deepcopy(node['params']), deepcopy(inputs),
                              deepcopy(binding.get('run')), deepcopy(binding.get('graph')))
            value = deepcopy(registry.get(node['op']).execute(context))
            if not isinstance(value, dict):
                raise InputError('Analysis operators must return a JSON object')
            encoded = dumps(value)
            with cache_store.connect() as connection:
                connection.execute('INSERT OR IGNORE INTO investigation_nodes VALUES (?,?,?,?,?)',
                                   (identifier, node['op'], encoded, digest(value), value.get('id')))
        values[node['name']] = value
        receipts.append({'name': node['name'], 'id': identifier, 'operation': node['op'], 'version': version,
                         'inputs': node['inputs'], 'output_hash': digest(value), 'status': 'complete', 'inference_calls': 0})
    manifest = {'schema': VERSION, 'definition': plan, 'nodes': receipts}
    identifier = 'analysis-plan-' + digest(manifest)
    with cache_store.connect() as connection:
        connection.execute('INSERT OR IGNORE INTO investigation_plans VALUES (?,?)', (identifier, dumps(manifest)))
    return {'id': identifier, 'manifest': manifest, 'outputs': values,
            'execution': {'cache_hits': hits, 'computed': len(receipts) - hits, 'inference_calls': 0}}


def build(store,rows,observer,sources,*,selected_graphs=None):
    nodes=[];focus=[r['id'] for r in rows if r['focus']];reference=[r['id'] for r in rows if r['reference']]
    ids=focus+reference
    if selected_graphs is None:
        with store.connect() as c:
            candidates=c.execute('SELECT id,run_id,source_hash FROM rollout_graphs WHERE observer=? ORDER BY rowid',(observer,)).fetchall()
    else:candidates=selected_graphs.values()
    chosen={r['run_id']:dict(r) for r in candidates if r['run_id'] in ids and r['source_hash']==sources.get(r['run_id'],{}).get('source_hash')}
    sequence_names=[];work_names=[];episode_names=[];phase_names=[];adaptation_names=[];recovery_names=[]
    for i,rid in enumerate(ids):
        source=sources.get(rid)
        if not source:continue
        p={'run_id':rid,'source_hash':source['source_hash'],'graph_id':source['id']};name='state'+str(i)
        nodes.append({'name':name,'op':'work_state','inputs':[],'params':p});work_names.append(name)
        recovery='recovery'+str(i)
        nodes.append({'name':recovery,'op':'recovery_windows','inputs':[name],
                      'params':{'graph_id':chosen.get(rid,source)['id']}});recovery_names.append(recovery)
        # Domain applicability is explicit import metadata, never guessed from
        # a framework name, activity tag, or the presence of programming tools.
        if run_source(store,rid).get('metadata',{}).get('task_family')==repair_phases.PROFILE:
            name='repair'+str(i);nodes.append({'name':name,'op':'repair_phases','inputs':[],'params':p});phase_names.append(name)
        if rid in chosen:
            name='sequence'+str(i);nodes.append({'name':name,'op':'sequence','inputs':[],'params':{**p,'graph_id':chosen[rid]['id']}});sequence_names.append(name)
            name='episodes'+str(i);nodes.append({'name':name,'op':'work_episodes','inputs':[],'params':{**p,'graph_id':chosen[rid]['id']}});episode_names.append(name)
            name='adaptation'+str(i);nodes.append({'name':name,'op':'adaptation_patterns','inputs':[],'params':{**p,'graph_id':chosen[rid]['id']}});adaptation_names.append(name)
    for name,op,dependencies in [('flows','compare_sequences',sequence_names),('work','compare_work',work_names),('episodes','compare_episodes',episode_names)]:
        nodes.append({'name':name,'op':op,'inputs':dependencies,'params':{'focus':focus,'reference':reference}})
    if phase_names:nodes.append({'name':'repair_phases','op':'compare_repair_phases','inputs':phase_names,'params':{'focus':focus,'reference':reference}})
    nodes.append({'name':'adaptation','op':'compare_adaptation','inputs':adaptation_names,'params':{'focus':focus,'reference':reference}})
    nodes.append({'name':'recovery','op':'compare_recovery_windows','inputs':recovery_names,'params':{'focus':focus,'reference':reference}})
    result=execute(store,{'schema':VERSION,'nodes':nodes})
    return {'schema':VERSION,'plan_id':result['id'],'plan':result['manifest'],
            'flows':result['outputs']['flows'],'work':result['outputs']['work'],'episodes':result['outputs']['episodes'],
            'repair_phases':result['outputs'].get('repair_phases'),'adaptation':result['outputs']['adaptation'],
            'recovery':result['outputs']['recovery'],'inference_calls':0}


def read_output(store,identifier):
    with store.connect() as c:r=c.execute('SELECT document,output_hash FROM investigation_nodes WHERE output_id=?',(identifier,)).fetchone()
    if not r:raise KeyError(identifier)
    value=json.loads(r[0])
    if digest(value)!=r[1]:raise InputError('Analysis output identity mismatch')
    return value


def read_plan(store,identifier):
    with store.connect() as c:r=c.execute('SELECT document FROM investigation_plans WHERE id=?',(identifier,)).fetchone()
    if not r:raise KeyError(identifier)
    value=json.loads(r[0])
    if identifier!='analysis-plan-'+digest(value):raise InputError('Analysis plan identity mismatch')
    return {'id':identifier,**value}
