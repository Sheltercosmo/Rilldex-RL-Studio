"""Source-bound hierarchical work capture, independent of the trajectory adapter.

The producer supplies parentage and scope. Validation establishes referential
integrity, not semantic truth. Reports never become verified outcomes, and native
control declarations never become inferred execution dependencies.
"""
from copy import deepcopy

from .schema import InputError, digest

VERSION = 'declared-work-tree/1'
CONTROLS = {'sequence', 'fallback', 'parallel'}
RECORDS = {'entered', 'operation', 'observation', 'statement', 'reported_complete', 'reported_failed'}


def capture(run):
    raw = run.get('raw', {})
    value = raw.get('declared_work_tree', (raw.get('extra') or {}).get('declared_work_tree'))
    if value is None:
        return None
    def require(condition, message):
        if not condition:
            raise InputError('Declared work tree: ' + message)
    require(isinstance(value, dict) and value.get('schema') == VERSION, 'unsupported schema')
    require(set(value) == {'schema', 'producer', 'nodes', 'records'}, 'unexpected or missing fields')
    require(isinstance(value['producer'], str) and bool(value['producer'].strip()), 'producer must be named')
    events = {e['id']: e for e in run['events']}
    def citation(ref):
        require(isinstance(ref, dict) and set(ref) == {'event_id', 'start', 'end', 'text'}, 'citation needs exact event span')
        require(isinstance(ref.get('event_id'),str), 'invalid citation event identity')
        e = events.get(ref.get('event_id'))
        require(e is not None and not e.get('copied_context'), 'citation event unavailable')
        a, b = ref['start'], ref['end']
        require(type(a) is int and type(b) is int and 0 <= a < b <= len(e['text']), 'invalid citation offsets')
        require(e['text'][a:b] == ref['text'], 'citation text differs from source')
        return e
    def position(ref):
        return events[ref['event_id']]['index'], ref['start']
    require(isinstance(value['nodes'], list) and 0 < len(value['nodes']) <= 10000, 'nodes must be a nonempty bounded list')
    nodes = {}
    for n in value['nodes']:
        require(isinstance(n, dict) and set(n) == {'id', 'kind', 'label', 'parent_id', 'evidence'}, 'invalid node fields')
        require(isinstance(n['id'], str) and bool(n['id']) and n['id'] not in nodes, 'duplicate or missing node ID')
        require(isinstance(n['kind'],str) and n['kind'] in {'goal', *CONTROLS}, 'unsupported node kind')
        citation(n['evidence'])
        require(n['label'] == n['evidence']['text'], 'labels must retain the cited wording')
        require(n['kind']=='goal' or n['label']==n['kind'], 'control label must identify its declared type')
        require(n['parent_id'] is None or isinstance(n['parent_id'], str), 'invalid parent identity')
        nodes[n['id']] = n
    for n in nodes.values():
        parent = nodes.get(n['parent_id'])
        require(n['parent_id'] is None or parent is not None, 'missing parent')
        if parent:
            require((parent['kind'] == 'goal') != (n['kind'] == 'goal'), 'goals and control declarations must alternate')
            require(events[parent['evidence']['event_id']]['trajectory_id'] == events[n['evidence']['event_id']]['trajectory_id'], 'parent belongs to another trajectory')
            require(position(parent['evidence']) <= position(n['evidence']), 'parent declaration follows child')
        else:
            require(n['kind'] == 'goal', 'root must be a goal')
        seen = {n['id']}; p = parent
        while p:
            require(p['id'] not in seen, 'cyclic parentage')
            seen.add(p['id']); p = nodes.get(p['parent_id'])
    require(isinstance(value['records'], list) and len(value['records']) <= 100000, 'invalid record list')
    seen = set()
    for r in value['records']:
        require(isinstance(r, dict) and set(r) == {'node_id', 'kind', 'evidence'}, 'invalid record fields')
        require(isinstance(r['node_id'], str) and r['node_id'] in nodes and nodes[r['node_id']]['kind'] == 'goal', 'records require a declared goal')
        require(isinstance(r['kind'],str) and r['kind'] in RECORDS, 'unsupported record kind')
        e = citation(r['evidence']); n = nodes[r['node_id']]
        require(e['trajectory_id'] == events[n['evidence']['event_id']]['trajectory_id'], 'record belongs to another trajectory')
        require(position(n['evidence']) <= position(r['evidence']), 'record precedes declaration')
        key = digest(r)
        require(key not in seen, 'duplicate record'); seen.add(key)
    return deepcopy(value)


def materialize(run, node, edge):
    value = capture(run)
    if value is None:
        return
    events = {e['id']: e for e in run['events']}
    # Namespaced by capture identity; a revised declaration never overwrites history.
    prefix = 'work-tree:' + digest(value)[:20] + ':'
    for n in value['nodes']:
        e = events[n['evidence']['event_id']]
        node(prefix+n['id'], 'declared_work_node', dict(n, producer=value['producer'], capture_version=VERSION), e)
        edge(prefix+n['id'], 'event:'+e['id'], 'declared_work_at', {'evidence':[n['evidence']]})
    for order,n in enumerate(value['nodes']):
        if n['parent_id'] is not None:
            edge(prefix+n['parent_id'], prefix+n['id'], 'contains_declared_work',
                 {'basis':'producer_declared_parentage', 'declaration_order':order, 'evidence':[n['evidence']]})
    for r in value['records']:
        e = events[r['evidence']['event_id']]; rid = prefix+'record:'+digest(r)
        node(rid, 'declared_work_record', dict(r, producer=value['producer']), e)
        edge(prefix+r['node_id'], rid, 'scopes_declared_work_record',
             {'basis':'producer_declared_scope', 'evidence':[r['evidence']]})
        edge(rid, 'event:'+e['id'], 'declared_work_at', {'evidence':[r['evidence']]})


def project(visible, eligible, items, links, roots):
    """Append nested structure to the same map; do not roll up child outcomes."""
    nodes = {k:n for k,n in visible.items() if n['kind'] == 'declared_work_node'}
    if not nodes:
        return None
    incoming = {}; children = {}
    for e in eligible:
        if e['type'] == 'contains_declared_work' and e['source'] in nodes and e['target'] in nodes:
            incoming[e['target']] = e['source']; children.setdefault(e['source'], []).append(e['target'])
            links.append(dict(e, type='contains', label='Declared subgoal' if nodes[e['target']]['properties']['kind']=='goal' else 'Declared control',
                edge_ids=[e['id']], evidence=e['properties'].get('evidence',[]), order=e['properties']['declaration_order']))
    scoped = {k:[] for k in nodes}
    for e in eligible:
        if e['type'] == 'scopes_declared_work_record' and e['source'] in nodes and visible[e['target']]['kind'] == 'declared_work_record':
            n = visible[e['target']]; p = n['properties']
            scoped[e['source']].append(dict(id=n['id'], occurrence_id='work-occurrence-'+digest([p['kind'],p['evidence']]),
                kind=p['kind'], event_index=n['event_index'], evidence=p['evidence']))
    for k,n in nodes.items():
        p = n['properties']; records = sorted(scoped[k], key=lambda r:(r['event_index'],r['evidence']['start'],r['id']))
        reports = [r for r in records if r['kind'] in {'reported_complete','reported_failed'}]
        last = reports[-1] if reports else None
        entered = any(r['kind'] in {'entered','operation','statement','observation'} for r in records)
        state = ('Reported complete' if last['kind']=='reported_complete' else 'Reported failed') if last else (
            'Expanded into subgoals' if children.get(k) and p['kind']=='goal' else 'Recorded work' if entered else 'No recorded visit')
        if p['kind'] in CONTROLS:
            state = {'sequence':'Ordered subgoals', 'fallback':'Try alternatives until one succeeds', 'parallel':'Independent subgoals; concurrency not established'}[p['kind']]
        # Any later activity can reopen a reported state; preserve the report as history.
        if last and any((r['event_index'],r['evidence']['start']) > (last['event_index'],last['evidence']['start']) and r['kind'] in {'entered','operation'} for r in records):
            state = 'Work after earlier report'
        elif last and len({r['kind'] for r in reports if (r['event_index'],r['evidence']['start']) == (last['event_index'],last['evidence']['start'])}) > 1:
            state = 'Conflicting reports'
        items[k] = dict(id=k, kind='native_goal' if p['kind']=='goal' else 'native_control', control=p['kind'] if p['kind'] in CONTROLS else None,
            label=p['label'], state=state, actor=None, trajectory_id=n['trajectory_id'], event_index=n['event_index'],
            source_node_ids=[k], evidence=[p['evidence']], source_text=p['evidence']['text'], history=[],
            records=records, producer=p['producer'], last_report=None if state=='Conflicting reports' else last,
            operation_count=sum(r['kind']=='operation' for r in records))
        if k not in incoming:
            roots.append(k)
    # Source order is only for stable presentation; controls carry their own meaning.
    return dict(roots=sum(k not in incoming for k in nodes), nodes=len(nodes),
                goals=sum(n['properties']['kind']=='goal' for n in nodes.values()),
                records=sum(map(len,scoped.values())))
