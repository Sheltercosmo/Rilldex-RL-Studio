"""Conditional retry measurements from saved work identity and operation outcomes.

No inference calls. Payload changes are observable action changes, not proof of
semantic revision, causal learning, correctness, or whole-task recovery.
"""
from copy import deepcopy
from .operation_outcomes import action_outcomes

VERSION = 'same-work-retry/2'
DEFINITIONS = {
    'changed_retry_completion_fraction': ('Changed retries completed · experimental',
        'Completed first recorded same-target retries with changed tool/arguments / such retries with a complete terminal operation outcome. Failure feedback must precede the retry. Partial outcomes count as not completed; unknowns are excluded. A payload change is not necessarily a semantic revision; completion is not task success.'),
    'unchanged_retry_fraction': ('Retries repeating the failed dispatch · experimental',
        'Identical tool/argument retries / first recorded same-target retries after a known failure with comparable dispatch payloads. Repetition may be appropriate for transient failures; this is not a waste rate.'),
    'changed_retry_unknown_fraction': ('Changed retries with unknown results',
        'Changed first recorded same-target retries without a complete terminal operation outcome / all such changed retries. Missing results are unknown, never failed or successful.'),
}


def payload(event):
    if event.get('arguments_available') is False or not event.get('tool') or not isinstance(event.get('arguments'), dict):
        return None
    return event['tool'], event['arguments']


def inspect(run, document):
    """Count a failed anchor once, using its earliest selected same-target return.

    Missing identity links cannot establish absence of retry. Failed anchors
    without a selected return are retained separately, outside conditional rates.
    """
    observed = document.get('operation_outcomes')
    history = document.get('work_history', {})
    if not observed or not history.get('available'):
        return None
    outcomes = action_outcomes(run, observed)
    events = {e['id']: e for e in run['events']}
    units = {u['id']: u for u in document['units']}
    disputed = {g['id'] for s in history.get('streams', []) for g in s.get('groups', []) if g.get('disputed_identity')}
    candidates = {}
    for r in history.get('recurrences', []):
        a, b = units.get(r['previous_group_unit_id']), units.get(r['unit_id'])
        if r['group_id'] in disputed or not r.get('supporting_identity_relations') or not a or not b:
            continue
        previous, current = events[a['source']['event_id']], events[b['source']['event_id']]
        if a['kind'] != 'action' or b['kind'] != 'action' or previous['actor'] != 'agent' or current['actor'] != 'agent':
            continue
        if previous['trajectory_id'] != current['trajectory_id'] or previous['index'] >= current['index']:
            continue
        old = outcomes.get(previous['id'], {})
        if old.get('outcome') != 'failed' or not old.get('observations'):
            continue
        if any(events[o['response_event_id']]['index'] >= current['index'] for o in old['observations']):
            continue
        candidates.setdefault(previous['id'], []).append((current['index'], a, b, r))
    episodes = []
    for aid, choices in candidates.items():
        _, a, b, recurrence = min(choices, key=lambda x: (x[0], x[2]['id']))
        previous, current = events[aid], events[b['source']['event_id']]
        old, new = outcomes[aid], outcomes.get(current['id'], {})
        before, after = payload(previous), payload(current)
        changed = None if before is None or after is None else before != after
        evidence = list(dict.fromkeys([a['id'], b['id'], aid, current['id'],
            *[o['response_event_id'] for o in old['observations']],
            *[o['response_event_id'] for o in new.get('observations', [])]]))
        episodes.append({'failed_unit_id': a['id'], 'retry_unit_id': b['id'],
            'failed_event_id': aid, 'retry_event_id': current['id'],
            'payload_changed': changed, 'retry_outcome': new.get('outcome', 'not_established'),
            'identity_relations': recurrence['supporting_identity_relations'],
            'evidence_ids': evidence})
    failed = {a for a, o in outcomes.items() if o['outcome'] == 'failed'}
    return summarize(episodes, sorted(failed - candidates.keys()))


def refresh(run, observed):
    """Repair payload comparability while preserving saved identities/outcomes."""
    events = {e['id']: e for e in run['events']}
    episodes = deepcopy(observed['episodes'])
    for e in episodes:
        before, after = payload(events[e['failed_event_id']]), payload(events[e['retry_event_id']])
        e['payload_changed'] = None if before is None or after is None else before != after
    return summarize(episodes, observed['failed_calls_without_selected_retry'])


def summarize(episodes, missing):
    changed = [e for e in episodes if e['payload_changed'] is True]
    known = [e for e in changed if e['retry_outcome'] in {'completed', 'failed', 'partial'}]
    comparable = [e for e in episodes if e['payload_changed'] is not None]
    def ratio(rows, denominator):
        return {'numerator': len(rows), 'denominator': len(denominator),
            'evidence': list(dict.fromkeys(i for e in denominator for i in e['evidence_ids']))}
    return {'schema': VERSION, 'episodes': episodes,
        'failed_calls_without_selected_retry': missing,
        'unknown_payload_count': len(episodes) - len(comparable),
        'metrics': {
            'changed_retry_completion_fraction': ratio([e for e in known if e['retry_outcome'] == 'completed'], known),
            'unchanged_retry_fraction': ratio([e for e in comparable if not e['payload_changed']], comparable),
            'changed_retry_unknown_fraction': ratio([e for e in changed if e not in known], changed)},
        'scope': 'First recorded same-target return after observed operation failure. Only selected identities; omitted returns are not negatives. No semantic revision or whole-task recovery is inferred.'}
