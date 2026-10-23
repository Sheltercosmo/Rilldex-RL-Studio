"""Resumable work comparisons with complete, bounded evidence packets.

Paging changes capacity, not pair semantics. A path identity is published only
after all eligible predecessors of that action have been inspected.
"""
from . import action_targets as targets, action_scope_pairs as pairs
from .capabilities import recorded_scope
from .schema import InputError, digest
from .semantic_pages import bounded_requests
from .semantic_extraction import checked_span
from .work_order import Evidence

VERSION = 'action-target-correspondence/6'
MAX_BYTES = 180_000


def candidate_scope(run, extraction, action, ordering=None):
    current = checked_span(run, action['source'])
    ordering = ordering or Evidence({e['id']: e for e in run['events']})
    pool, excluded = [], []
    for prior in targets.candidates(run, extraction, action):
        event = checked_span(run, prior['source'])
        reason = None
        if recorded_scope(event) != recorded_scope(current):
            reason = 'different_recorded_context'
        elif event['id'] in ordering.groups.get(current['id'], []):
            reason = 'same_recorded_dispatch_batch'
        elif event.get('order_known') is False or current.get('order_known') is False:
            reason = 'source_order_unestablished'
        if reason:
            excluded.append(dict(unit_id=prior['unit_id'], event_id=event['id'], reason=reason))
        else:
            pool.append(prior)
    pool.sort(key=lambda p: (checked_span(run, p['source'])['index'], p['source']['end'], p['unit_id']))
    return [{**p, 'id': 'a'+str(i)} for i, p in enumerate(pool)], excluded


def request(run, action, pool):
    req = pairs.request(run, action, pool)
    req['state'].update(relation_harness=VERSION,
        candidate_scope='One deterministic page of earlier selected dispatches by this actor in the same recorded trajectory and context. Same-batch siblings and explicitly unordered endpoints are excluded. Each pair is independent; other pages may contain additional matches.',
        page_limits=dict(pairs=pairs.LIMIT, input_bytes=MAX_BYTES))
    return req


def pages(run, action, pool):
    """Split by pair count and exact payload size; never shorten cited evidence."""
    yield from bounded_requests(pool,lambda chunk:request(run,action,chunk),count=pairs.LIMIT,max_bytes=MAX_BYTES)


def coverage(result):
    rows = result['actions']
    observed = [p for row in rows for p in row['pairs']]
    return dict(actions=len(rows), candidate_pairs=sum(r['candidate_count'] for r in rows),
        compared_pairs=len(observed), pending_pairs=sum(r['candidate_count']-len(r['pairs']) for r in rows),
        unresolved_pairs=sum(p['choice']=='unresolved' for p in observed),
        completed_actions=sum(r['status'] in {'compared','unresolved','no_ordered_prior_action','no_prior_selected_action'} for r in rows),
        excluded_pairs=sum(len(r['excluded_candidates']) for r in rows),
        same_batch_excluded_pairs=sum(p['reason']=='same_recorded_dispatch_batch' for r in rows for p in r['excluded_candidates']),
        oversized_pairs=sum(len(r.get('oversized_pairs', [])) for r in rows))


def build(run, extraction, decide, *, progress=None):
    if extraction['status'] != 'complete_local_extraction':
        raise InputError('Complete local selection is required before scope comparison')
    ordering = Evidence({e['id']:e for e in run['events']})
    work = [(a, *candidate_scope(run, extraction, a, ordering))
            for a in extraction['units'] if a['kind']=='action' and a['status']=='selected']
    result = dict(schema=VERSION, run_id=run['id'], source_hash=digest(run),
        extraction_hash=digest(extraction), candidate_limit=pairs.LIMIT, page_byte_limit=MAX_BYTES,
        evidence_layout=targets.SCOPED_LAYOUT, status='running', actions=[], relations=[],
        identity_projection='Publish the most recent positive whole-target predecessor only after all eligible pairs for this action have been inspected. Retain every pair judgment.',
        limits='Source-ordered correspondence, not causal retry, progress, success or strategy. Uninspected and unresolved pairs are not negative results.')
    for action, pool, excluded in work:
        result['actions'].append(dict(action_unit_id=action['id'], candidate_count=len(pool),
            excluded_candidates=excluded, pairs=[], pages=[], status='pending'))

    def publish():
        result['coverage'] = coverage(result)
        if progress: progress(result)

    publish()
    types = {'same_work_target':'same_action_target', 'partial_work_overlap':'overlapping_work_scope',
             'different_work_same_subject':'different_work_same_subject', 'different_instance':'similar_operation_distinct_target'}
    for row, (action, pool, excluded) in zip(result['actions'], work):
        if not pool:
            row['status'] = ('unresolved' if any(p['reason']=='source_order_unestablished' for p in excluded)
                             else 'no_ordered_prior_action' if excluded else 'no_prior_selected_action')
            publish(); continue
        row['status'] = 'inspecting'
        for chunk, req in pages(run, action, pool):
            if req is None:
                row.setdefault('oversized_pairs', []).extend(p['unit_id'] for p in chunk)
                publish(); continue
            row['next_request'] = digest(req)
            publish()
            answers, key = decide(req)
            if set(answers) != set(req['questions']):
                raise InputError('Scope comparison answers differ from requested pairs')
            if any(a['value'] not in targets.SCOPE_PAIR_TYPES for a in answers.values()):
                raise InputError('Unknown scope relation choice')
            row['pairs'].extend(dict(prior_unit_id=p['unit_id'], question_id=p['id'],
                choice=answers[p['id']]['value'], request=key, edge_emitted=False) for p in chunk)
            row['pages'].append(dict(request=key, compared_pairs=len(chunk)))
            row.pop('next_request', None)
            publish()
        if len(row['pairs']) != len(pool):
            row['status'] = 'evidence_too_large'; publish(); continue
        same = [p for p in row['pairs'] if p['choice']=='same_work_target']
        latest = same[-1] if same else None
        by_id = {p['unit_id']:p for p in pool}
        if latest:
            batch=ordering.groups.get(by_id[latest['prior_unit_id']]['source']['event_id'],[])
            if sum(by_id[p['prior_unit_id']]['source']['event_id'] in batch for p in same)>1:
                # Multiple matching siblings have no most-recent member. Keep
                # the positive pair judgments without inventing a path anchor.
                row['identity_selection']='unordered_matching_predecessors'
                latest=None
        unknown=(not latest and (bool(same) or any(p['choice']=='unresolved' for p in row['pairs'])
                 or any(p['reason']=='source_order_unestablished' for p in excluded)))
        row.update(status='unresolved' if unknown else 'compared',
                   identity_prior_unit_id=latest['prior_unit_id'] if latest else None)
        for judgment in row['pairs']:
            choice = judgment['choice']
            if choice not in types or (choice=='same_work_target' and judgment is not latest): continue
            prior = by_id[judgment['prior_unit_id']]; judgment['edge_emitted'] = True
            result['relations'].append({
                'from':action['id'], 'to':prior['unit_id'], 'type':types[choice],
                'basis':'jev_raw_argmax', 'request':judgment['request'], 'question_id':judgment['question_id'],
                'pair_request':judgment['request'], 'pair_choice':choice,
                'explanation':targets.SCOPE_PAIR_TYPES[choice], 'evidence':[prior['source'],action['source']],
                'argument_delta':targets.argument_delta(checked_span(run,prior['source']),checked_span(run,action['source'])),
                'cutoff':{'event_id':action['source']['event_id'], 'end':action['source']['end']}})
        publish()
    result['status'] = 'needs_evidence' if coverage(result)['pending_pairs'] else 'complete'
    publish()
    return result
