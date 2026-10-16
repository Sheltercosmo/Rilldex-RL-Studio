"""Query saved references during a supported return to earlier work.

Counts recorded witnesses; missing relations never certify behavioral absence.
Uses the existing work-visit and source/prefix-validated connection projections.
"""
from copy import deepcopy
from .schema import InputError, digest
from . import work_visits, work_navigation, work_route_context

VERSION = 'work-return-references/1'
SCOPES = {
    'same_work_history': 'Earlier visits to the returned work',
    'intervening_work': 'Work between the previous visit and this return',
    'all_prior_work': 'Any earlier work in the same context',
}
DEFAULT_QUERY = dict(schema=VERSION, name='Returns revising earlier work',
    relation_types=['revises'], referent_scope='same_work_history')
LIMIT = ('Count of supported return visits with at least one selected saved relationship. '
         'One return counts once even when several contributions or edges match. No matching '
         'edge means not established, not no revision or no evidence use. Targets are earlier '
         'work visits in the same actor/context route; feedback targets use their recorded '
         'originating action. References may occur anywhere within the returned visit, so they '
         'do not establish why the agent returned. This is not exploration, progress or quality.')


def supported_relation(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and (
        value in work_route_context.RELATIONS or value.startswith('reasoningflow:backref:') and
        len(value) > len('reasoningflow:backref:'))


def validate(query):
    if (not isinstance(query, dict) or set(query) != set(DEFAULT_QUERY) or query['schema'] != VERSION
            or not isinstance(query['name'], str) or not query['name'].strip() or len(query['name']) > 200
            or not isinstance(query['referent_scope'], str) or query['referent_scope'] not in SCOPES
            or not isinstance(query['relation_types'], list) or not 1 <= len(query['relation_types']) <= 16
            or any(not supported_relation(t) for t in query['relation_types'])):
        raise InputError('Work-return query needs a name, 1–16 supported exact relationship types and an earlier-work scope')
    if len(set(query['relation_types'])) != len(query['relation_types']):
        raise InputError('Duplicate work-return relationship type')
    return {**deepcopy(query), 'relation_types': sorted(query['relation_types'])}


def evaluate(graph, query, *, recurrence_order=None, scope_consistency=None):
    query = validate(query)
    base = work_visits.project(graph, recurrence_order=recurrence_order, scope_consistency=scope_consistency)
    records = []; context = None
    if base['available']:
        route = work_navigation.project(graph, recurrence_order=recurrence_order); context = route.get('context')
        by_visit = {r['id']: r for r in base['records']}
        for path in route['paths']:
            prior = []
            for vid in path['visit_ids']:
                current = by_visit[vid]
                if current.get('unqualified_category', current['category']) == 'returned':
                    subject = current['visit']['group_id']
                    same = [i for i, r in enumerate(prior) if r['visit']['group_id'] == subject]
                    if not same: raise InputError('Return has no prior same-work visit')
                    if query['referent_scope'] == 'same_work_history':
                        targets = [prior[i] for i in same]
                    elif query['referent_scope'] == 'intervening_work':
                        targets = prior[same[-1]+1:]
                    else:
                        targets = prior
                    target_ids = {r['id'] for r in targets if r['visit']['group_id']}
                    links = [e for e in route['links'] if e['type'] == 'work_relation'
                        and e['source'] == vid and e['target'] in target_ids
                        and e['relation_type'] in query['relation_types']]
                    # Keep the return's complete witness and every exact relation
                    # endpoint. Context/feedback cards never become extra visits.
                    row = dict(visit_id=vid, target=current['target'],
                        status='recorded_reference' if links else 'not_established',
                        references=deepcopy(links), target_visit_ids=sorted(target_ids),
                        node_ids=list(dict.fromkeys(current['node_ids']+[n for e in links for n in e['node_ids']])),
                        edge_ids=list(dict.fromkeys(current['edge_ids']+[i for e in links for i in e['edge_ids']])),
                        visit=deepcopy(current['visit']), episode=deepcopy(current['episode']))
                    relevant = [current, *[by_visit[e['target']] for e in links]]
                    conflicts = {c['id']:c for r in relevant for c in r.get('work_conflicts', [])}
                    if conflicts:
                        row['work_conflicts'] = deepcopy(list(conflicts.values()))
                        row['status'] = 'disputed_work_identity'
                    row['id'] = 'work-return-reference-' + digest([graph['id'], query, row])
                    records.append(row)
                prior.append(current)
    matched = sum(bool(r['references']) and not r.get('work_conflicts') for r in records)
    result = dict(schema=VERSION, graph_id=graph['id'], run_id=graph['run_id'], source_hash=graph['source_hash'],
        observer=graph['observer'], query=query, records=records, available=base['available'], observed=base['observed'],
        value=matched if base['observed'] else None,
        coverage={**base['coverage'], 'recorded_returns':len(records), 'returns_with_reference':matched,
            'returns_without_established_reference':len(records)-matched,
            'unresolved_work_switches':base['metrics']['unknown'],
            'rejected_relationships':context['unprojected'] if context else 0},
        limits=LIMIT)
    if recurrence_order:
        result['recurrence_order'] = recurrence_order
        result['limits'] += (' Returns may bracket complete observed parallel dispatch groups. '
            'Sibling order is unresolved; every reference still needs a saved source-bound relationship.')
    if scope_consistency is not None:
        from . import work_consistency
        result['scope_consistency'] = scope_consistency
        result['work_consistency'] = deepcopy(base['work_consistency'])
        result['coverage']['disputed_return_references'] = sum(bool(r.get('work_conflicts')) for r in records)
        result['coverage']['returns_without_established_reference'] = sum(not r['references'] and not r.get('work_conflicts') for r in records)
        result['limits'] += ' ' + work_consistency.LIMIT
        if base['coverage']['disputed_work_visits']:
            result['value'] = None
    return {'id':'work-return-references-'+digest(result), **result}
