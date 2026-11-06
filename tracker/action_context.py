"""Retrieve older source feedback for a current dispatch, without domain labels."""
from .capabilities import recorded_scope
from .feedback_retrieval import FeedbackIndex, CONTEXT_VERSION

VERSION = 'action-lookback/1'


def visible_before(event, current):
    return (recorded_scope(event) == recorded_scope(current) and event['index'] < current['index'] and
            not event['kind'].startswith('external_') and event.get('agent_visible') is not False and
            event.get('agent_visibility') != 'not_established' and event.get('order_known') is not False)


def older_feedback(run, current, linked, recent, query_text):
    """Use the existing feedback index with native calls as its source records.

    Matches are context candidates, not inferred state identities or relationships.
    Recent history keeps its original role; older hits cannot become the previous
    action for retry/revision measurements.
    """
    events = {e['id']: e for e in run['events']}
    records = []
    for pair in linked['records']:
        action, feedback = events[pair['action_id']], events[pair['feedback_id']]
        if any(not visible_before(e, current) or e.get('copied_context') for e in (action, feedback)):
            continue
        records.append({'unit_id': feedback['id'], 'event': feedback,
            'action': {'actor': action['actor'], 'source': {'event_id': action['id'], 'text': action['text']},
                       'content': {'summary': {'text': ''}}}})
    if not records:
        return [], {'schema': VERSION, 'selected': [], 'eligible_prior_responses': 0}
    subject = {'actor': current['actor'], 'trajectory_id': current['trajectory_id'],
               'source': {'event_id': current['id']}}
    if current.get('copied_context') or current.get('order_known') is False or current.get('agent_visibility') == 'not_established' or current.get('agent_visible') is False:
        return [], {'schema': VERSION, 'selected': [], 'eligible_prior_responses': 0}
    with FeedbackIndex(records, run['events']) as index:
        selected, report = index.select(subject, current['index'], version=CONTEXT_VERSION, query_text=query_text)
    recent_ids = {e['id'] for e in recent}
    older_ids = {r['action']['source']['event_id'] for r in selected} - recent_ids
    older = sorted((events[eid] for eid in older_ids), key=lambda e: e['index'])
    return older, {'schema': VERSION, 'retrieval': report,
        'selected': [e['id'] for e in older],
        'scope': 'Selected earlier calls and their recorded results, in source order. Not adjacent actions, '
                 'not a complete state snapshot. Later observations may supersede earlier values. '
                 'A lexical match does not establish a semantic relationship.'}
