"""A complete work-level route over source-bound units and positive relations.

This is a view of recorded work identity, not an exploration/goal-drift judge.
Only consecutive occurrences with a positive identity link can share a visit.
"""
from copy import deepcopy
from collections import defaultdict
from . import work_episodes
from .schema import digest, InputError
from . import work_subjects
from . import work_route_context
from . import work_order

VERSION = 'work-navigation/3|' + work_episodes.VERSION + '|' + work_subjects.NAV_VERSION + '|' + work_route_context.VERSION
LIMIT = ('Cards group consecutive observed attempts on the same immediate work only where a saved identity '
         'relation supports that grouping. Separate cards do not establish new work, alternatives, or exploration. '
         'Dashed arrows are recording order; return and correction links are recorded semantic relationships. '
         'A correction attempt does not prove that a failure was fixed. Goal drift and approach identity require '
         'separate observations. Every native action retains a position, including gaps and unordered batches.')


def validate_target_relations(value):
    if value != 'contribution-scope-pairs/2': raise InputError('Unknown work-map target relation projection')


def project(graph, *, target_relations=None, recurrence_order=None):
    if recurrence_order is not None:
        work_order.validate(recurrence_order)
        if not (graph.get('semantic_context') or {}).get('work_subjects'):
            raise InputError('Parallel-work recurrence requires contribution work bindings')
    if target_relations is not None:
        validate_target_relations(target_relations)
        ctx=graph.get('semantic_context') or {}
        if not ctx.get('work_subjects') or ctx.get('contribution_scope',{}).get('protocol')!=target_relations:
            raise InputError('Target relation projection requires compatible saved work and pair evidence')
    if (graph.get('semantic_context') or {}).get('work_subjects'):
        value = work_route_context.enrich(graph, work_subjects.project(graph,recurrence_order=recurrence_order),target_relations=target_relations is not None)
        value.pop('id'); value['schema'] = VERSION+('|'+target_relations if target_relations else '')
        return {'id': 'work-navigation-'+digest(value), **value}
    episodes = work_episodes.project(graph)
    nodes = {n['id']: n for n in graph['nodes']}
    events = {n['properties']['id']: n['properties'] for n in nodes.values() if n['kind'] == 'event'}
    scopes = {n['id']: n for n in nodes.values() if n['kind'] == 'work_scope'}
    memberships = defaultdict(list)
    for e in graph['edges']:
        if e['type'] != 'in_work_scope' or e['source'] not in nodes or e['target'] not in scopes:
            continue
        unit = nodes[e['source']]['properties']; scope = scopes[e['target']]['properties']
        a, b = unit.get('source', {}), scope.get('source', {})
        ea, eb = events.get(a.get('event_id')), events.get(b.get('event_id'))
        if (not ea or not eb or ea['trajectory_id'] != eb['trajectory_id'] or eb.get('copied_context') or
                type(a.get('end')) is not int or type(b.get('end')) is not int or
                (eb['index'], b['end']) > (ea['index'], a['end'])):
            continue
        if any(type(s.get('start')) is not int or not 0 <= s['start'] < s['end'] <= len(ev['text']) or
               ev['text'][s['start']:s['end']] != s.get('text') for s, ev in [(a, ea), (b, eb)]):
            continue
        memberships[e['source']].append({'scope_id': e['target'], 'edge_id': e['id']})
    episode_by_id = {e['id']: e for e in episodes['episodes']}
    paths = []; visits = []; unit_visit = {}; links = []
    for path in episodes['paths']:
        route = []
        for index, p in enumerate(path['positions']):
            uid = p['unit_id']; scope_ids = sorted({v['scope_id'] for v in memberships[uid]})
            stages = deepcopy(p['plan_stages'])
            stage_key = sorted((s['plan_unit_id'], s['step_id'], s['role']) for s in stages)
            previous = route[-1] if route else None
            recurrence = episode_by_id.get(p['episode_id'])
            merge = bool(previous and uid and p['group_id'] and p['order_known'] and
                         previous['group_id'] == p['group_id'] and previous['scope_ids'] == scope_ids and
                         previous['stage_key'] == stage_key and recurrence and recurrence['category'] == 'continued' and
                         recurrence['previous_unit_id'] == previous['unit_ids'][-1])
            if not merge:
                value = {'trajectory_id': path['trajectory_id'], 'actor': path['actor'], 'first_event_id': p['event_id']}
                previous = {'id': 'work-visit-' + digest([graph['id'], value]), **value,
                            'group_id': p['group_id'], 'target': p['target'] or 'Action without a usable work observation',
                            'scope_ids': scope_ids, 'plan_stages': stages, 'stage_key': stage_key,
                            'unit_ids': [], 'event_ids': [], 'positions': [], 'occurrences': [],
                            'episode_ids': [], 'order_known': p['order_known']}
                route.append(previous); visits.append(previous)
            previous['event_ids'].append(p['event_id']); previous['positions'].append(index + 1)
            previous['occurrences'].append(deepcopy(p))
            if uid:
                previous['unit_ids'].append(uid); unit_visit[uid] = previous['id']
            if p['episode_id']: previous['episode_ids'].append(p['episode_id'])
        for a, b in zip(route, route[1:]):
            # Keep the raw order, while explicitly refusing an execution-order
            # claim for unordered batches. No transition crosses trajectories.
            links.append({'type': 'recorded_next', 'source': a['id'], 'target': b['id'],
                          'order_known': a['order_known'] and b['order_known'], 'edge_ids': []})
        paths.append({'trajectory_id': path['trajectory_id'], 'actor': path['actor'], 'visit_ids': [v['id'] for v in route]})
    for episode in episodes['episodes']:
        a, b = unit_visit.get(episode['previous_unit_id']), unit_visit.get(episode['current_unit_id'])
        if not a or not b: continue
        links.append({'type': 'same_work_return', 'source': b, 'target': a, 'episode_id': episode['id'],
                      'category': episode['category'], 'edge_ids': episode['edge_ids'],
                      'method': deepcopy(episode['method'])})
        for adjustment in episode['adjustments']:
            via = unit_visit.get(adjustment['action'])
            if via:
                links.append({'type': 'attempted_correction_for', 'source': via, 'target': a,
                              'episode_id': episode['id'], 'edge_ids': [adjustment['edge_id']],
                              'declaration_unit_id': adjustment['declaration'], 'retry_unit_id': episode['current_unit_id'],
                              'work': adjustment['work'], 'timing': adjustment['timing']})
    for link in links: link['id'] = 'work-link-' + digest(link)
    for visit in visits: visit.pop('stage_key')
    used = {sid for v in visits for sid in v['scope_ids']}
    value = {'schema': VERSION, 'run_id': graph['run_id'], 'source_hash': graph['source_hash'], 'graph_id': graph['id'],
             'observer': graph['observer'], 'paths': paths, 'visits': visits, 'links': links,
             'scopes': [deepcopy(scopes[sid]) for sid in sorted(used)], 'episodes': episodes['episodes'],
             'counts': {**episodes['counts'], 'visits': len(visits),
                        'collapsed_consecutive_actions': episodes['counts']['recorded_actions'] - len(visits)},
             'issues': episodes['issues'], 'available': bool(episodes['counts']['represented_actions']), 'limit': LIMIT}
    value = work_route_context.enrich(graph, value, only_declared=True)
    return {'id': 'work-navigation-' + digest(value), **value}
