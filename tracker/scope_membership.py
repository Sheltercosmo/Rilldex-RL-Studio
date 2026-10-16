"""Prefix-local work groups from complete, compatible pair observations.

No learned decision is made here. Missing pairs are unknown, not negative;
inconsistent pair choices cannot be repaired by a transitive union.
"""
from collections import Counter
from copy import deepcopy

from . import contribution_scope_pairs as pairs, contribution_work as cw, work_subjects as ws
from .jev import validate_answers
from .schema import InputError, digest
from .semantic_extraction import checked_span

VERSION = 'pair-derived-work/1'
PROFILE = dict(id='pair-derived-work', version=VERSION, label='Work targets · pair evidence',
    definition='The same complete immediate question or requested outcome for the same particular '
    'referents and instance, independently of activity. Membership requires every eligible ordered '
    'predecessor to have a compatible, resolved pair judgment. Missing or contradictory evidence stays unresolved.')


def replay(run, graph):
    from .contribution_scope_graph import VERSION as layer_version
    layer = (graph.get('semantic_context') or {}).get('contribution_scope')
    if not layer or layer['schema'] != layer_version or layer['protocol'] != pairs.TARGET_VERSION:
        raise InputError('Work grouping requires the activity-independent target-pair protocol, version 2')
    if digest(run) != graph['source_hash']:
        raise InputError('Work grouping source differs from its graph')
    _, units, _, issues = ws.evidence_index(graph)
    if issues or any(u.get('status') != 'selected' for u in units.values()):
        raise InputError('Repair invalid, overlapping or unselected units before grouping work')
    for unit in units.values():
        checked_span(run, unit['source'])
        for ref in cw.immediate_target(unit, cw.GRAPH_INPUT).get('evidence', []):
            checked_span(run, ref, unit['source'])
    observations = []; lookup = {}
    for saved in layer['receipts']:
        if set(saved) != {'current', 'priors', 'request', 'response'}:
            raise InputError('Invalid target-pair receipt')
        if any(units.get(u['id']) != u for u in [saved['current'], *saved['priors']]):
            raise InputError('Target-pair unit changed; dependent grouping is stale')
        def decide(req):
            if req != saved['request'] or saved['response'].get('model') != req['model']:
                raise InputError('Target-pair request or model changed')
            return validate_answers(saved['response'], req), digest(req)
        observation = pairs.compare(run, saved['current'], saved['priors'], decide, version=pairs.TARGET_VERSION)
        observations.append(observation)
        for row in observation['pairs']:
            key = row['current_unit_id'], row['prior_unit_id']
            if key in lookup: raise InputError('Duplicate target-pair evidence')
            lookup[key] = row
    if observations != layer['observations'] or len(lookup) != layer['pair_count']:
        raise InputError('Target-pair observations differ from raw-argmax replay')
    return units, lookup


def derive(run, graph):
    units, lookup = replay(run, graph)
    events = {e['id']: e for e in run['events']}
    ordered = sorted(units.values(), key=lambda u: ws.position(u, events))
    def ordered_prior(prior, current):
        # Units have exact validated source spans. Avoid rescanning all source
        # events inside every pair comparison; ordering matches the selector.
        a, b = events[prior['source']['event_id']], events[current['source']['event_id']]
        if prior['id']==current['id'] or ws.lane(prior,events)!=ws.lane(current,events): return False
        if (a['index'],prior['source']['end']) > (b['index'],current['source']['start']): return False
        if a['kind']==b['kind']=='action' and (
            a.get('parent_id') and a['parent_id']==b.get('parent_id') or
            a.get('source_message_index') is not None and a.get('source_message_index')==b.get('source_message_index')): return False
        return True
    subjects = []; bindings = []; records = []; bound = {}; members = {}
    for current in ordered:
        uid = current['id']; target = cw.immediate_target(current, cw.GRAPH_INPUT)
        priors = [p for p in ordered if ordered_prior(p,current)]
        evidence = [lookup[(uid, p['id'])] for p in priors if (uid, p['id']) in lookup]
        missing = [p['id'] for p in priors if (uid, p['id']) not in lookup]
        unknown = [r['prior_unit_id'] for r in evidence if r['choice'] == 'unresolved']
        selected = {r['prior_unit_id']: r['choice'] for r in evidence}
        same = [p for p, choice in selected.items() if choice == 'same_work_target']
        same_groups = {bound[p] for p in same if p in bound}
        sid = None; conflict = []
        if target.get('status') != 'expressed' or not 0 < len(target.get('text', '').strip()) <= 1200:
            reason = 'readable_target_unavailable'
        elif missing:
            reason = 'missing_pair_evidence'
        elif unknown:
            reason = 'unresolved_pair_evidence'
        elif len(same_groups) > 1:
            reason = 'identity_bridges_distinct_groups'; conflict = same
        elif any(p not in bound for p in same):
            reason = 'earlier_membership_unresolved'
        elif same_groups:
            candidate = next(iter(same_groups))
            conflict = [p for p in members[candidate] if p in selected and selected[p] != 'same_work_target']
            if conflict:
                reason = 'identity_conflicts_with_group_member'
            else:
                sid = candidate; reason = 'complete_pair_identity'
        else:
            sid = 'subject-'+digest([VERSION, graph['source_hash'], uid, target])[:24]
            subjects.append(dict(id=sid, label=target['text'].strip(), origin_unit_id=uid))
            reason = 'first_comparable_target' if not priors else 'distinct_from_compared_targets'
        if sid:
            bound[uid] = sid; members.setdefault(sid, []).append(uid)
        binding = dict(unit_id=uid, status='bound' if sid else 'unresolved', subject_id=sid,
            note='Deterministic grouping from saved target-pair choices: '+reason+'. No unobserved pair is assumed negative.',
            provenance=dict(kind='pair_derivation', author='Saved pair evidence', protocol=VERSION))
        bindings.append(binding)
        records.append(dict(unit_id=uid, source=deepcopy(current['source']), status=binding['status'],
            subject_id=sid, reason=reason, eligible_prior_unit_ids=[p['id'] for p in priors],
            observed_pairs=deepcopy(evidence), missing_prior_unit_ids=missing,
            unresolved_prior_unit_ids=unknown, conflicting_prior_unit_ids=conflict))
    counts = dict(Counter(r['status'] for r in records))
    counts.update(units=len(units), groups=len(subjects), observed_pairs=len(lookup),
        eligible_pairs=sum(len(r['eligible_prior_unit_ids']) for r in records),
        missing_pairs=sum(len(r['missing_prior_unit_ids']) for r in records),
        unresolved_pairs=sum(len(r['unresolved_prior_unit_ids']) for r in records),
        conflicting_units=sum(bool(r['conflicting_prior_unit_ids']) for r in records))
    return dict(schema=VERSION, profile=deepcopy(PROFILE), source_hash=graph['source_hash'],
        relation_layer_hash=digest(graph['semantic_context']['contribution_scope']),
        subjects=subjects, bindings=bindings, records=records, counts=counts,
        limits='Complete eligible ordered pair coverage is required for each bound contribution. '
               'Parallel dispatches remain unordered and interrupt recurrence. Groups are prefix-local '
               'annotations, not globally distinct semantic targets. No future evidence repairs earlier '
               'membership, and agreement is not independent semantic accuracy.')


def document(run, graph):
    result = derive(run, graph)
    return dict(schema=ws.DERIVED_VERSION, profile=deepcopy(PROFILE), base_graph_id=graph['id'],
        subjects=deepcopy(result['subjects']), bindings=deepcopy(result['bindings']),
        derivation=dict(schema=VERSION, run=deepcopy(run), result=result))


def validate(graph, doc):
    receipt = doc['derivation']
    if receipt.get('schema') != VERSION or doc['profile'] != PROFILE:
        raise InputError('Unknown pair-derived work contract')
    result = derive(receipt['run'], graph)
    if result != receipt['result']:
        raise InputError('Work grouping differs from replayed pair evidence')
    original = {r['unit_id']: r for r in result['bindings']}
    rows = {r['unit_id']: r for r in doc['bindings']}
    if set(rows) != set(original):
        raise InputError('Pair-derived work must retain every eligible contribution')
    for uid, row in rows.items():
        if row['provenance']['kind'] != 'review' and row != original[uid]:
            raise InputError('Derived work binding changed without a named review')
    expected = {s['id']: s for s in result['subjects']}
    for subject in doc['subjects']:
        if rows[subject['origin_unit_id']]['provenance']['kind'] != 'review' and expected.get(subject['id']) != subject:
            raise InputError('Derived target changed without a named review')
    return result


def pending_requests(run, graph):
    """Build only missing comparisons. No clients, keys, or provider calls."""
    result = derive(run, graph)
    _, units, _, _ = ws.evidence_index(graph)
    requests = []; unavailable = []
    for row in result['records']:
        ids = row['missing_prior_unit_ids']
        for start in range(0, len(ids), pairs.LIMIT):
            batch = ids[start:start+pairs.LIMIT]
            try:
                req = pairs.request(run, units[row['unit_id']], [units[p] for p in batch], version=pairs.TARGET_VERSION)
            except InputError as error:
                unavailable.append(dict(unit_id=row['unit_id'], prior_unit_ids=batch, reason=str(error))); continue
            requests.append(dict(request_hash=digest(req), request=req, current=deepcopy(units[row['unit_id']]),
                priors=[deepcopy(units[p]) for p in batch]))
    return dict(schema='pair-work-preflight/1', graph_id=graph['id'], source_hash=graph['source_hash'],
        counts=result['counts'], requests=requests, unavailable=unavailable, provider_calls=0,
        limits='Only missing pairs are proposed. Existing unresolved decisions require a changed question or source review, not an unchanged retry.')


def receive(store, payload):
    from . import graph_store
    if not isinstance(payload, dict) or set(payload) != {'base_graph_id'} or not isinstance(payload['base_graph_id'], str):
        raise InputError('Work grouping requires one saved base graph')
    base = graph_store.read(store, payload['base_graph_id'])
    if (base.get('semantic_context') or {}).get('work_subjects'):
        raise InputError('Group from the saved pair graph before membership or named work reviews')
    run = store.get(base['run_id'], raw=True)['run']
    doc = document(run, base); graph = ws.fork(base, doc)
    with store.connect() as c:
        graph_store.save(c, graph)
    return dict(graph_id=graph['id'], run_id=graph['run_id'], observer=graph['observer'],
        counts=doc['derivation']['result']['counts'], new_model_calls=0)
