"""Immutable, receipt-backed pair relations on the existing unit graph.

This partial layer does not create work memberships or population measurements.
"""
from copy import deepcopy

from . import contribution_scope_pairs as pairs, contribution_work as cw, graph_store
from .jev import validate_answers
from .schema import InputError, digest

VERSION = 'contribution-scope-graph/1'
EDGE_TYPES = {'same_work_target': 'same_work_target', 'partial_work_overlap': 'overlapping_work_scope',
              'different_work_same_subject': 'different_work_same_subject',
              'different_instance': 'similar_operation_distinct_target'}
REPLACED_TYPES = {*EDGE_TYPES.values(), 'same_action_target'}
EXPLANATIONS = {
    'same_work_target': 'These contributions concern the same complete immediate question or requested outcome. Their activities remain distinct; this does not establish correctness or successful execution.',
    'partial_work_overlap': 'Some immediate work is shared, but the complete scopes differ. Keep the targets distinct.',
    'different_work_same_subject': 'Different immediate questions or requested outcomes concern the same subject. A dependency or causal response is not established.',
    'different_instance': 'Similar work concerns distinct particular task instances. The targets must remain distinct.'}


def fork(run, base, receipts):
    graph_store.validate(base)
    if digest(run) != base['source_hash'] or not receipts:
        raise InputError('Scope graph requires matching source and nonempty receipts')
    if (base.get('semantic_context') or {}).get('contribution_scope'):
        raise InputError('Apply scope observations to their preserved base graph')
    units = {u['id']: u for u in cw.inputs(base)}
    observations = []; seen = set(); protocols = set()
    for saved in receipts:
        if set(saved) != {'current', 'priors', 'request', 'response'}:
            raise InputError('Scope receipt requires endpoints, exact request and raw response')
        current, priors = saved['current'], saved['priors']
        if any(units.get(u['id']) != u for u in [current, *priors]):
            raise InputError('Scope endpoint contents changed; dependent observations are stale')
        protocol = saved['request']['state']['relation_harness']; protocols.add(protocol)
        def decide(req):
            if req != saved['request'] or saved['response'].get('model') != req['model']:
                raise InputError('Scope receipt request/model differs')
            return validate_answers(saved['response'], req), digest(req)
        observation = pairs.compare(run, current, priors, decide, version=protocol)
        for pair in observation['pairs']:
            key = (pair['current_unit_id'], pair['prior_unit_id'])
            if key in seen: raise InputError('Duplicate scope pair; choose a version explicitly')
            seen.add(key)
        observations.append(observation)
    if len(protocols) != 1: raise InputError('Do not pool scope protocols in one new relation layer')
    protocol = next(iter(protocols)); graph = deepcopy(base); graph.pop('id')
    replaced = [e for e in graph['edges'] if (e['source'], e['target']) in seen and e['type'] in REPLACED_TYPES]
    graph['edges'] = [e for e in graph['edges'] if e not in replaced]
    for observation in observations:
        for pair in observation['pairs']:
            if pair['choice'] not in EDGE_TYPES: continue
            value = {'source': pair['current_unit_id'], 'target': pair['prior_unit_id'],
                'type': EDGE_TYPES[pair['choice']],
                'properties': {**deepcopy(pair), 'basis': 'jev_raw_argmax', 'protocol': protocol, 'scope_layer': VERSION,
                    'explanation': EXPLANATIONS[pair['choice']],
                    'candidate_scope': 'Only the explicit supplied pair was judged; no unobserved pair is negative.'}}
            graph['edges'].append({'id': 'edge-'+digest(value), **value})
    context = graph.get('semantic_context') or {}; graph['semantic_context'] = context
    context['contribution_scope'] = {'schema': VERSION, 'protocol': protocol, 'base_graph_id': base['id'],
        'receipts': deepcopy(receipts), 'observations': observations, 'replaced_edges': replaced,
        'pair_count': len(seen), 'coverage': 'explicit_pairs_only',
        'no_membership_or_population_inference': True}
    context.setdefault('review_notes', []).append({'basis': VERSION, 'review_scope': 'Experimental target relations — partial comparison coverage',
        'unit_ids': sorted({uid for pair in seen for uid in pair}),
        'text': f'{len(seen)} explicit unit pairs were selected under {protocol}. Activity and work target are separate axes. '
                'Every new relation replays from a saved raw response. Other base-graph relationships retain their original protocols. '
                'Uncompared pairs are unobserved; these targeted development cases do not establish general accuracy, work groups or training metrics.',
        'evidence': []})
    graph['observer'] = 'scope-pairs-'+digest([base['observer'], protocol])[:20]
    graph['observer_label'] = 'Target relations · '+protocol.rsplit('/', 1)[-1]+' · partial experiment'
    graph['annotation_hash'] = digest([base['annotation_hash'], protocol, receipts])
    graph['coverage']['semantic_relations'] = 'partial'
    graph['counts'].update(nodes=len(graph['nodes']), edges=len(graph['edges']))
    graph['nodes'].sort(key=lambda n: n['id']); graph['edges'].sort(key=lambda e: e['id'])
    return {'id': 'graph-'+digest(graph), **graph}


def register(store, run, base, receipts):
    if digest(store.get(run['id'], raw=True)['run']) != digest(run):
        raise InputError('Stored source differs from scope evidence')
    graph = fork(run, base, receipts)
    with store.connect() as c:
        graph_store.save(c, base); graph_store.save(c, graph)
    return {'graph_id': graph['id'], 'observer': graph['observer'], 'run_id': run['id'],
            'url': '/semantic-map?run='+run['id']+'&observer='+graph['observer']+'&graph='+graph['id']+'&level=units'}
