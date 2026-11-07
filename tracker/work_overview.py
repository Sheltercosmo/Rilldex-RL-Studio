"""Compact entry points into the exact saved work route, including reasoning."""
from collections import Counter

from . import work_navigation, work_scope_audit


def project(graph, *, recurrence_order=None):
    route = work_navigation.project(graph, recurrence_order=recurrence_order)
    audit = work_scope_audit.project(graph)
    disputed = set(audit.get('affected_subject_ids', []))
    nodes = {n['id']: n for n in graph['nodes']}
    positions = [p for v in route['visits'] for p in v['occurrences']]
    by_unit = {p['unit_id']: p for p in positions if p['unit_id']}
    visit_by_unit = {uid: v['id'] for v in route['visits'] for uid in v['unit_ids']}
    episodes = []
    for episode in route['episodes']:
        previous, current = episode['previous_unit_id'], episode['current_unit_id']
        groups = {by_unit.get(uid, {}).get('group_id') for uid in (previous, current)}
        state = 'disputed' if groups & disputed else episode['category']
        endpoints = []
        for uid in (previous, current):
            source = nodes.get(uid, {}).get('properties', {}).get('source', {})
            endpoints.append({'unit_id': uid, 'event_id': source.get('event_id'),
                              'start': source.get('start'), 'end': source.get('end')})
        episodes.append({'id': episode['id'], 'state': state, 'category': episode['category'],
                         'target': episode['target'], 'previous': endpoints[0], 'current': endpoints[1],
                         'visit_id': visit_by_unit.get(current), 'edge_ids': episode['edge_ids'],
                         'ordering': episode.get('ordering'), 'method': episode.get('method')})
    counts = Counter(e['state'] for e in episodes)
    identified = {p['unit_id'] for p in positions if p.get('identity_status') == 'bound'}
    identified.update(endpoint['unit_id'] for e in episodes for endpoint in (e['previous'], e['current']))
    return {'graph_id': graph['id'], 'source_hash': graph['source_hash'], 'observer': graph['observer'],
            'recurrence_order': recurrence_order, 'axis': route.get('axis', 'actions'),
            'counts': {'positions': len(positions), 'represented': sum(bool(p['unit_id']) for p in positions),
                       'assigned': sum(p['unit_id'] in identified for p in positions if p['unit_id']),
                       **{k: counts[k] for k in ('continued', 'returned', 'resumed', 'interrupted', 'disputed')}},
            'episodes': episodes, 'available': bool(identified),
            'scope': 'Saved immediate-work identities. Returns require intervening work; missing or disputed identity and unknown order are separate. A return does not establish wasted effort, revision or successful recovery.'}
