"""Retrieve older source feedback for a current dispatch, without domain labels."""
from .capabilities import recorded_scope
from .feedback_retrieval import FeedbackIndex, CONTEXT_VERSION
from .schema import InputError
from .work_order import Evidence

VERSION = 'action-lookback/1'
DISPATCH_VERSION = 'recorded-dispatch/1'


def visible_record(event):
    return (not event.get('copied_context') and not event['kind'].startswith('external_') and
            event.get('agent_visible') is not False and event.get('agent_visibility') != 'not_established')


def native_dispatch(run, event_id):
    """Retain native co-issued calls and message content, without ordering siblings.

    This describes the captured dispatch, not a claim that the export contains
    every call or that any call executed. No names or text infer membership.
    """
    events = {e['id']: e for e in run['events']}
    selected = events.get(event_id)
    if not selected or selected['actor'] != 'agent' or selected['kind'] != 'action' or not visible_record(selected):
        raise InputError('Select an original agent-visible action')
    lane = {eid: e for eid, e in events.items() if recorded_scope(e) == recorded_scope(selected)
            and e['actor'] == selected['actor'] and visible_record(e)}
    order = Evidence(lane)
    actions = sorted((lane[eid] for eid in order.groups[event_id]), key=lambda e: e['index'])
    parents = {e['parent_id'] for e in actions if e.get('parent_id')}
    message_indices = {e['source_message_index'] for e in actions if e.get('source_message_index') is not None}
    messages = sorted((e for e in lane.values() if e['kind'] == 'message' and
                       (e['id'] in parents or e.get('source_message_index') in message_indices)),
                      key=lambda e: e['index'])
    declared = max((e.get('batch_size') or 0 for e in actions), default=0)
    return {'schema': DISPATCH_VERSION, 'selected_action_id': event_id,
            'action_ids': [e['id'] for e in actions], 'message_ids': [e['id'] for e in messages],
            'message_with_text_ids': [e['id'] for e in messages if e['text'].strip()],
            'recorded_action_count': len(actions), 'declared_action_count': declared or None,
            'declared_members_missing': max(0, declared - len(actions)),
            'first_source_index': min(e['index'] for e in [*actions, *messages]),
            'last_source_index': max(e['index'] for e in [*actions, *messages]),
            'membership_basis': 'native parent/message identity' if parents or message_indices else 'selected action only',
            'order': 'Native message content and calls are co-issued; serialized positions do not establish execution order.'}


def dispatch_prefix(run, event_id):
    """Visible earlier context plus the complete captured native model output."""
    dispatch = native_dispatch(run, event_id)
    current = next(e for e in run['events'] if e['id'] == event_id)
    members = set(dispatch['action_ids'] + dispatch['message_ids'])
    return [e for e in run['events'] if visible_record(e) and recorded_scope(e) == recorded_scope(current)
            and (e['id'] in members or current.get('order_known') is not False
                 and e['index'] < dispatch['first_source_index'] and e.get('order_known') is not False)]


def native_definitions(event):
    """Preserve recorded action/observation meanings, with media still unread."""
    from .readable_context import project, VERSION as TEXT_VERSION
    fields = {k: event[k] for k in ('tool_contract', 'observation_contract') if k in event}
    if not fields: return {}
    view = project({'id': event['id'], 'kind': event['kind'], 'actor': event['actor'], 'text': '', **fields},
                   {'schema': TEXT_VERSION, 'max_event_chars': 128, 'extra_ranges': []},
                   {'event_id': event['id']})
    return {k: view[k] for k in (*fields, 'unobserved_auxiliary_media') if k in view}


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
