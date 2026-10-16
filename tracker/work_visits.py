"""Macro work visits, their coverage and returns among observable switches.

Visits collapse consecutive same-subject contributions. This reduces dependence
on segmentation granularity; it does not make incorrect memberships accurate.
"""
from collections import Counter
from copy import deepcopy
from .schema import InputError, digest
from . import work_subjects

VERSION = 'work-visit-observations/1'
ENTRY_VERSION = 'work-switch-entry-evidence/1'
LIMIT = ('These are annotated immediate-work visits, not inferred exploration, exploitation, deviation or quality. '
         'A first recorded subject is not necessarily novel. Return share is conditional on decidable switches; '
         'unknown history is excluded and reported, and can bias the estimate. No universal desirable target is defined.')


def entry_evidence(graph, output, case):
    """Describe a saved switch at visit entry without rewriting its measurement.

    A full visit is useful map context. The return predicate is established at
    its first contribution, so later contributions are not decision evidence.
    This bounds review evidence; it does not certify how bindings were inferred.
    """
    if output.get('schema') != VERSION or output.get('graph_id') != graph['id']:
        raise InputError('Switch evidence requires its saved work-visit projection')
    switch = next((r for r in output['switches'] if r['id'] == case['id']), None)
    if switch is None or case['node_ids'] != switch['node_ids'] or case['edge_ids'] != switch['edge_ids']:
        raise InputError('Switch case differs from its saved projection')
    record = next(r for r in output['records'] if r['id'] == switch['visit_id'])
    visit = record['visit']; entry = visit['occurrences'][0]
    nodes = {n['id']:n for n in graph['nodes']}
    events = {n['properties']['id']:n['properties'] for n in graph['nodes'] if n['kind']=='event'}
    ref = entry['source']; event = events[ref['event_id']]
    def lane(e): return e['trajectory_id'], e.get('actor'), e.get('context_id')
    def position(r): return events[r['event_id']]['index'], r['end']
    cutoff = position(ref); source_refs = []; node_ids = []
    for nid in switch['node_ids']:
        node = nodes[nid]
        if node['kind'] != 'unit': continue
        source = node['properties'].get('source')
        if not source: continue
        origin = events[source['event_id']]
        if lane(origin) != lane(event): raise InputError('Switch witness crosses a work lane')
        if position(source) <= cutoff:
            node_ids.append(nid); source_refs.append(deepcopy(source))
    if entry['unit_id'] not in node_ids:
        raise InputError('Switch entry has no exact source witness')
    source_refs.sort(key=lambda s:(events[s['event_id']]['index'],s['start'],s['end']))
    visible = set(node_ids); edges = {e['id']:e for e in graph['edges']}
    edge_ids = [eid for eid in switch['edge_ids'] if edges[eid]['source'] in visible]
    result = dict(schema=ENTRY_VERSION, graph_id=graph['id'], case_id=case['id'],
        entry_unit_id=entry['unit_id'], cutoff=deepcopy(ref),
        trajectory_id=event['trajectory_id'], actor=event['actor'], context_id=event.get('context_id'),
        order_known=entry['order_known'], node_ids=node_ids, edge_ids=edge_ids, source_refs=source_refs,
        excluded_later_unit_ids=[nid for nid in switch['node_ids'] if nodes[nid]['kind']=='unit' and nid not in visible],
        basis='Saved work identity at the first contribution of this visit; binding inference may be retrospective.')
    return {'id':'switch-entry-'+digest(result), **result}


def project(graph, *, recurrence_order=None, scope_consistency=None):
    from . import work_order
    if recurrence_order is not None: work_order.validate(recurrence_order)
    if scope_consistency is not None:
        from . import work_consistency
        work_consistency.validate(scope_consistency)
    info = (graph.get('semantic_context') or {}).get('work_subjects')
    records = []; switches = []; counts = {}; route = None
    if info:
        route = work_subjects.project(graph,recurrence_order=recurrence_order); counts = route['counts']
        visits = {v['id']: v for v in route['visits']}; episodes = {e['id']: e for e in route['episodes']}
        bindings = {e['source']: e['id'] for e in graph['edges'] if e['type']=='about_work_subject'}
        for path in route['paths']:
            last_bound = None; complete_history = True; prefix = []
            for vid in path['visit_ids']:
                visit = visits[vid]; p = visit['occurrences'][0]; sid = visit['group_id']; category = p['category']
                if sid and category=='first_or_unresolved': category = 'first_seen'
                elif not sid: category = 'not_applicable' if p['identity_status']=='not_applicable' else 'unknown'
                ep = episodes.get(p['episode_id'])
                nodes = list(dict.fromkeys(visit['unit_ids']+['event:'+eid for eid in visit['event_ids']]))
                edges = [bindings[uid] for uid in visit['unit_ids'] if uid in bindings]
                if ep:
                    nodes = list(dict.fromkeys(nodes+[c['unit_id'] for c in ep['cards']]))
                    edges = list(dict.fromkeys(edges+ep['edge_ids']))
                record = dict(id=vid, category=category, target=visit['target'], node_ids=nodes, edge_ids=edges,
                    unit_ids=visit['unit_ids'], event_ids=visit['event_ids'], trajectory_id=path['trajectory_id'],
                    context_id=path.get('context_id'), visit=visit, episode=ep, history_complete=complete_history)
                records.append(record)
                if sid and last_bound is not None and (sid != last_bound['group_id'] or category=='interrupted'):
                    # Positives have an explicit prior same-subject witness and
                    # complete intervening work. A first-seen subject is negative
                    # only when all earlier eligible source in this lane is reviewed.
                    value = True if category=='returned' else False if category=='first_seen' and complete_history and p['order_known'] else None
                    # Include the prefix for negatives/unknowns so the claimed
                    # absence or missing coverage can actually be inspected.
                    if value is True:
                        at = next(i for i, r in enumerate(prefix) if ep['previous_unit_id'] in r['unit_ids'])
                        proof = [*prefix[at:], record]
                    else: proof = [*prefix, record]
                    switches.append(dict(id='work-switch-'+digest([graph['id'], vid]), visit_id=vid,
                        value=value, status='return' if value is True else 'first_recorded_subject' if value is False else 'unknown',
                        target=visit['target'], previous_visit_id=last_bound['id'], category=category,
                        node_ids=list(dict.fromkeys(n for r in proof for n in r['node_ids'])),
                        edge_ids=list(dict.fromkeys(e for r in proof for e in r['edge_ids'])),
                        episode=ep, history_complete=complete_history))
                    if value is True:
                        record['node_ids'] = switches[-1]['node_ids']
                        record['edge_ids'] = switches[-1]['edge_ids']
                if sid: last_bound = visit
                if category=='unknown' or not all(p['order_known'] for p in visit['occurrences']): complete_history=False
                prefix.append(record)
    numerator = sum(r['value'] is True for r in switches); denominator = sum(r['value'] is not None for r in switches)
    value = dict(schema=VERSION, run_id=graph['run_id'], source_hash=graph['source_hash'], graph_id=graph['id'],
        observer=graph['observer'], navigation_id=route['id'] if route else None, records=records, switches=switches,
        counts=dict(Counter(r['category'] for r in records)), coverage=counts,
        profile=info['document'].get('profile') if info else None,
        observed=bool(counts.get('bound')), available=info is not None,
        metrics=dict(value=numerator/denominator if denominator else None, numerator=numerator, denominator=denominator,
                     opportunities=len(switches), unknown=len(switches)-denominator), limits=LIMIT)
    if recurrence_order:
        value['recurrence_order'] = recurrence_order
        value['limits'] += (' Complete parallel dispatch groups may intervene between ordered recurrence endpoints. '
            'Unordered switch entries remain unknown; their display order does not create negative opportunities.')
    if scope_consistency is not None: work_consistency.qualify(graph, value)
    return {'id':'work-visits-'+digest(value), **value}
