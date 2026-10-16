"""Bounded source excerpts for checks, shared by file import and collectors.

No semantic labels, proximity joins, model calls or database writes. Relations
use the same explicit action/result correspondence as the persisted source map.
"""
from collections import Counter, defaultdict
from .capabilities import links

EVENT_LIMIT = 12
TEXT_LIMIT = 700


def preview(run):
    local = [event for event in run['events'] if not event.get('copied_context')]
    selected = local[:EVENT_LIMIT]
    visible = {event['id'] for event in selected}
    linked = links(run)
    children = defaultdict(Counter)
    for event in local:
        if event.get('parent_id'):
            children[event['parent_id']][event['kind']] += 1
    relations = [record for record in linked['records']
                 if record['action_id'] in visible and record['feedback_id'] in visible]
    events = []
    for event in selected:
        text = event.get('text', '')
        events.append({key: event[key] for key in
                       ('id', 'index', 'kind', 'actor', 'trajectory_id', 'source_pointer', 'tool')
                       if key in event} | {
            'text': text[:TEXT_LIMIT], 'omitted_characters': max(0, len(text) - TEXT_LIMIT),
            'media_count': len(event.get('media') or []),
            'unlinked_response': event['id'] in linked['unlinked_ids'],
            'child_counts': dict(children[event['id']]),
        })
    metadata = run['metadata']
    return {'schema': 'source-preview/1', 'events': events, 'relations': relations,
            'identity': {key: metadata[key] for key in
                         ('experiment', 'task_id', 'sample_id', 'logical_rollout_id',
                          'producer', 'source_export_path', 'source_line') if key in metadata},
            'total_events': len(local), 'omitted_events': len(local) - len(events),
            'copied_context_events': len(run['events']) - len(local),
            'omitted_relations': len(linked['records']) - len(relations),
            'event_limit': EVENT_LIMIT, 'text_limit': TEXT_LIMIT,
            'note': 'First recorded events, in source order. Simultaneous actions may share a message; '
                    'their display order does not establish execution order. Plans and semantic '
                    'relationships require separate observation.'}
