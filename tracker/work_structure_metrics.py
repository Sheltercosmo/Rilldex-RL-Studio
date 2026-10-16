"""Recorded work structure and effort, shared by maps and rollout monitors.

Keep evidence bases separate. Native visits are not semantic Plan attempts, and
an explicit resume decision is not an executed retry. Counts describe saved
witnesses, never inferred exploration quality or abandoned work.
"""
from collections import defaultdict, deque

from .schema import digest, InputError

VERSION = 'work-structure-measures/1'
LIMIT = ('Recorded structure only. Unlinked or unvisited work remains unobserved, not ignored or abandoned. '
         'Native operation requests do not prove execution; linked Plan attempts do not prove completion. '
         'Stop, defer and resume are attributed decisions. Depth and effort depend on the captured hierarchy; '
         'shared work is counted once in aggregate, and branch totals may overlap. This does not establish '
         'exploration, exploitation, strategy quality or independent semantic accuracy.')

MEASURES = {
    'plan_steps_attempted': ('plan_steps', 'Plan steps with linked attempts',
        'Distinct declared semantic Plan steps with at least one saved attempts_plan_step witness. Other steps are unobserved, not failed or ignored.'),
    'plan_attempt_dispatches': ('plan_steps', 'Distinct dispatches linked as Plan attempts',
        'Distinct action identities linked as attempts to any declared semantic Plan step. Shared attempts count once across steps; preparations and checks alone are excluded.'),
    'native_goals_visited': ('declared_tree', 'Declared goals with recorded visits',
        'Distinct producer-declared goals with an entered or operation record in their own scope. Child visits are not promoted into parent visits.'),
    'native_operation_requests': ('declared_tree', 'Native goal operation requests',
        'Distinct source operation occurrences in the producer-declared goal tree. The same occurrence scoped to several goals counts once. These are native requests, not proven executed tool calls.'),
    'work_resume_decisions': ('work_outline', 'Explicit work-resume decisions',
        'Distinct source-bound resume decisions in the reviewed objective/approach outline. This counts decisions, not successful resumption or repeated command text.'),
    'work_stop_decisions': ('work_outline', 'Explicit work-stop decisions',
        'Distinct source-bound stop decisions in the reviewed work outline. A failed attempt or absence of later activity is not a stop decision.'),
    'work_defer_decisions': ('work_outline', 'Explicit work-deferral decisions',
        'Distinct source-bound defer decisions in the reviewed work outline. Unmentioned branches are not counted as deferred.'),
}


def depths(ids, parents):
    """Min/max depth in a DAG; shared parentage must not select one path."""
    incoming = {k: set(parents.get(k, ())) & ids for k in ids}
    children = defaultdict(set)
    for k, ps in incoming.items():
        for p in ps:
            children[p].add(k)
    queue = deque(sorted(k for k in ids if not incoming[k]))
    remaining = {k: len(ps) for k, ps in incoming.items()}
    result = {}
    while queue:
        k = queue.popleft()
        ps = incoming[k]
        result[k] = (min(result[p][0] for p in ps) + 1, max(result[p][1] for p in ps) + 1) if ps else (0, 0)
        for child in sorted(children[k]):
            remaining[child] -= 1
            if not remaining[child]:
                queue.append(child)
    if len(result) != len(ids):
        raise InputError('Work structure contains cyclic parentage')
    return result


def summarize(graph, hierarchy):
    source = {n['id']: n for n in graph['nodes']}
    items = {n['id']: n for n in hierarchy['nodes']}
    edge_by_id = {e['id']: e for e in graph['edges']}
    edges_from, edges_to = defaultdict(list), defaultdict(list)
    for e in graph['edges']:
        edges_from[e['source']].append(e)
        edges_to[e['target']].append(e)
    rows, cases = [], {key: [] for key in MEASURES}
    profiles = {}

    def witness(identifier, label, nodes, edges=(), **extra):
        return dict(id=identifier, label=label, taken=True, status='recorded', node_ids=sorted(set(nodes) & source.keys()),
                    edge_ids=sorted(set(edges)), **extra)

    # One row per semantic Plan step, with exact action membership retained.
    paths = {p['stage_id']: p for p in hierarchy['stage_paths']}
    steps = [n for n in items.values() if n['kind'] == 'plan_step']
    dispatches = defaultdict(list)
    for step in steps:
        path = paths.get(step['id'], {})
        attempts = [r for r in path.get('rows', []) if 'attempts_plan_step' in r['roles']]
        ids = sorted({r['action_id'] for r in attempts})
        links = sorted({eid for r in attempts for eid in r['role_link_ids']
                        if edge_by_id.get(eid, {}).get('type') == 'attempts_plan_step'})
        row = dict(id=step['id'], profile='plan_steps', label=step['label'], state=step['state'],
                   effort=len(ids), effort_unit='linked attempt dispatches', direct_effort=len(ids),
                   depth_min=1, depth_max=1, observed=bool(ids), node_ids=[step['id'], *ids], edge_ids=links)
        rows.append(row)
        if ids:
            cases['plan_steps_attempted'].append(witness(step['id'], step['label'], row['node_ids'], links,
                work_structure=dict(profile='plan_steps', focus=step['id'], effort=len(ids))))
        for aid in ids:
            dispatches[aid].append(row)
    for aid, owners in sorted(dispatches.items()):
        cases['plan_attempt_dispatches'].append(witness(aid, 'Plan attempt · ' + aid,
            [aid, *(r['id'] for r in owners)], {eid for r in owners for eid in r['edge_ids'] if edge_by_id[eid]['source'] == aid},
            work_structure=dict(profile='plan_steps', focus=owners[0]['id'], shared_scopes=[r['id'] for r in owners])))
    profiles['plan_steps'] = dict(available=bool(hierarchy['counts']['plans']), declared=len(steps), observed=sum(r['observed'] for r in rows),
                                 distinct_effort=len(dispatches), effort_unit='linked attempt dispatches')

    # Native goals have explicit record scope. Control nodes are not goal depth.
    goals = {k: n for k, n in items.items() if n['kind'] == 'native_goal'}
    native = {k for k,n in items.items() if n['kind'] in {'native_goal','native_control'}}
    parent = {}
    for e in hierarchy['links']:
        if e['type'] != 'contains' or e['source'] not in native or e['target'] not in native:
            continue
        if e['target'] in parent and parent[e['target']] != e['source']:
            raise InputError('Native work nodes require one declared parent')
        parent[e['target']] = e['source']
    goal_parents = {}
    for k in goals:
        p = parent.get(k)
        seen = {k}
        while p and p not in goals:
            if p in seen: raise InputError('Native work contains cyclic parentage')
            seen.add(p)
            p = parent.get(p)
        goal_parents[k] = [p] if p else []
    level = depths(set(goals), goal_parents)
    operations = defaultdict(list)
    for k, goal in goals.items():
        records = goal.get('records', [])
        own = {r['occurrence_id']: r for r in records if r['kind'] == 'operation'}
        visits = [r for r in records if r['kind'] in {'entered', 'operation'}]
        nodes = [k, *[r['id'] for r in visits], *['event:' + r['evidence']['event_id'] for r in visits]]
        edges = [e['id'] for e in edges_from[k] if e['type'] == 'scopes_declared_work_record'
                 and e['target'] in nodes]
        row = dict(id=k, profile='declared_tree', label=goal['label'], state=goal['state'],
                   depth_min=level[k][0], depth_max=level[k][1], observed=bool(visits),
                   direct_effort=len(own), effort_unit='native operation requests', node_ids=nodes, edge_ids=edges)
        rows.append(row)
        if visits:
            cases['native_goals_visited'].append(witness(k, goal['label'], nodes, edges,
                work_structure=dict(profile='declared_tree', focus=k, depth=list(level[k]))))
        for oid, occurrence in own.items():
            operations[oid].append((k, occurrence))
    # Roll up source occurrence sets, not counts or completion states.
    scoped = {k: set() for k in goals}
    for oid, owners in operations.items():
        for k, _ in owners:
            current = k
            while current:
                scoped[current].add(oid)
                current = next(iter(goal_parents[current]), None)
        nodes = [n for k, r in owners for n in (k, r['id'], 'event:' + r['evidence']['event_id'])]
        cases['native_operation_requests'].append(witness(oid, owners[0][1]['evidence']['text'], nodes,
            [e['id'] for nid in nodes for e in edges_to[nid] if e['type'] == 'scopes_declared_work_record'],
            work_structure=dict(profile='declared_tree', focus=owners[0][0], shared_scopes=[k for k, _ in owners])))
    for row in rows:
        if row['profile'] == 'declared_tree':
            row['effort'] = len(scoped[row['id']])
    profiles['declared_tree'] = dict(available=bool(goals), declared=len(goals),
        observed=len(cases['native_goals_visited']), distinct_effort=len(operations), effort_unit='native operation requests')

    outline = hierarchy.get('work_outline')
    work_items = outline['items'] if outline else []
    outline_parents = defaultdict(set)
    if outline:
        for e in outline['links']:
            if e['type'] == 'part_of':
                outline_parents[e['source']].add(e['target'])
    level = depths({n['id'] for n in work_items}, outline_parents)
    all_actions = set()
    for item in work_items:
        k = item['id']
        execution = item.get('execution_summary', {})
        ids = {r['action_id'] for r in execution.get('rows', [])}
        all_actions.update(ids)
        rows.append(dict(id=k, profile='work_outline', label=item['label'], state=item['state'],
                         depth_min=level[k][0], depth_max=level[k][1], observed=bool(ids), effort=len(ids),
                         direct_effort=None, effort_unit='linked dispatches (including descendants)',
                         node_ids=[k, *sorted(ids)], edge_ids=[]))
        for decision in item['decisions']:
            key = {'resume': 'work_resume_decisions', 'stop': 'work_stop_decisions',
                   'defer': 'work_defer_decisions'}.get(decision['type'])
            if key:
                cases[key].append(witness(decision['id'], item['label'] + ' · ' + decision['type'],
                    [k, decision['id'], 'event:' + decision['evidence']['event_id']],
                    [e['id'] for e in edges_from[k] if e['target'] == decision['id']],
                    work_structure=dict(profile='work_outline', focus=k, decision=decision['type'])))
    profiles['work_outline'] = dict(available=outline is not None, declared=len(work_items),
        observed=sum(r['profile'] == 'work_outline' and r['observed'] for r in rows),
        distinct_effort=len(all_actions), effort_unit='linked dispatches')
    from .decision_followthrough import windows
    return dict(schema=VERSION, profiles=profiles, rows=rows, cases=cases,
                decision_windows=windows(outline), limits=LIMIT)


def project(graph, cutoff_event_id=None):
    from .work_hierarchy import build
    hierarchy = build(graph, cutoff_event_id)
    value = dict(**hierarchy['work_measures'], graph_id=graph['id'], run_id=graph['run_id'],
                 source_hash=graph['source_hash'], cutoff_event_id=cutoff_event_id,
                 cutoff_event_index=hierarchy['cutoff_event_index'])
    return {'id': 'work-measures-' + digest(value), **value}


def measure(output, key):
    profile = output['profiles'][MEASURES[key][0]]
    cases = output['cases'][key]
    return dict(value=len(cases) if profile['available'] else None, numerator=None, denominator=None,
                opportunities=None, unknown=None, cases=cases, coverage=profile,
                reason=None if profile['available'] else 'The selected graph has no supported ' + MEASURES[key][0].replace('_', ' ') + ' evidence.')
