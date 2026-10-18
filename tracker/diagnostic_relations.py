"""Recorded trajectory scope and action/result evidence for diagnostic v10.

No adjacency joins, inferred task inheritance, or interpretation of role-like
text. Legacy capture and v8/v9 context remain unchanged for exact replay.
"""
from collections import defaultdict
from copy import deepcopy
import json

from . import diagnostic_context as context, diagnostic_monitors as base
from .schema import digest, dumps

VERSION = 'diagnostic-relations/1'
LINK_LIMIT = 12000
IDENTITY_FIELDS = ('trajectory_id', 'call_id', 'source_call_id', 'related_action_ids',
                   'parent_id', 'source_pointer', 'feedback_origin', 'link_basis')


def from_run(run):
    source = base.from_run(run)
    events = {e['id']: e for e in run['events']}
    rows = json.loads(source['trace'])
    for row in rows:
        event = events[row['id']]
        row.update({key: deepcopy(event[key]) for key in IDENTITY_FIELDS if key in event})
    source['trace'] = dumps(rows)
    source['provenance']['capture'] = VERSION
    return source


def records(source):
    indexed = context.records(source)
    for record in indexed:
        # Native envelope and trajectory are independent namespaces. A missing
        # trajectory cannot inherit a neighboring agent's task or call IDs.
        trajectory = record['value'].get('trajectory_id')
        record['scope'] = [*record['scope'], 'trajectory', dumps(trajectory)]
    return indexed


def overlaps(record, fragment):
    return (fragment['origin'] == 'trace' and record['start'] < fragment['end']
            and record['end'] > fragment['start'])


def annotate(fragments, indexed):
    """Expose native scope on source fragments, without changing their text."""
    for fragment in fragments:
        matches = [r for r in indexed if overlaps(r, fragment)]
        if len(matches) == 1:
            record = matches[0]
            fragment['native_scope'] = record['scope']
            fragment['record_id'] = record['id']
            if 'trajectory_id' in record['value']:
                fragment['trajectory_id'] = record['value']['trajectory_id']
    return fragments


def links(indexed):
    calls, actions = defaultdict(list), defaultdict(list)
    for record in indexed:
        if record['kind'] != 'action' or record['actor'] not in {'agent', 'assistant'}: continue
        value = record['value']; scope = tuple(record['scope'])
        if value.get('call_id'): calls[(scope, dumps(value['call_id']))].append(record)
        if record['event_id'] is not None: actions[(scope, dumps(record['event_id']))].append(record)
    result = []
    for feedback in indexed:
        if feedback['kind'] not in {'feedback', 'tool_result'} or feedback['actor'] not in {'environment', 'tool', 'user'}: continue
        value = feedback['value']; scope = tuple(feedback['scope'])
        if value.get('source_call_id'):
            targets = calls[(scope, dumps(value['source_call_id']))]; basis = 'recorded_call_id'
        else:
            refs = value.get('related_action_ids', [])
            targets = actions[(scope, dumps(refs[0]))] if isinstance(refs, list) and len(refs) == 1 else []
            basis = 'recorded_action_reference'
        if len(targets) != 1 or targets[0]['end'] > feedback['start']: continue
        result.append((targets[0], feedback, basis))
    return result


def packet(source, fragments, *, indexed=None):
    indexed = records(source) if indexed is None else indexed
    selected = {r['id']: r for r in indexed if any(overlaps(r, f) for f in fragments)}
    tasks, bindings, used = {}, {}, 0
    omitted_tasks = []
    for fragment in fragments:
        anchors = [r for r in selected.values() if overlaps(r, fragment) and r['actor'] in {'agent', 'assistant'}]
        if len(anchors) != 1: continue
        anchor = anchors[0]
        # Use the whole enclosing record as the cutoff; fragment length cannot
        # change which prior instructions govern the same action.
        task = context.task(source, [dict(origin='trace', start=anchor['start'], end=anchor['end'], id=fragment['id'])], indexed=indexed)
        if task is None: continue
        key = 'task-' + digest(task)[:20]
        cost = 0 if key in tasks else len(dumps(task))
        if used + cost > context.TASK_LIMIT:
            omitted_tasks.append(fragment['id']); continue
        tasks[key] = task; bindings[fragment['id']] = key; used += cost
    result = dict(recorded_result_links=[], linked_source_records=[], omitted_linked_record_ids=[],
                  omitted_task_fragment_ids=omitted_tasks)
    agent_fragments = {f['id'] for f in fragments if any(overlaps(r, f) and r['actor'] in {'agent', 'assistant'} for r in selected.values())}
    if len(tasks) == 1 and set(bindings) == agent_fragments:
        result['complete_recorded_task'] = next(iter(tasks.values()))
        result['candidate_task_ids'] = bindings
        result['shared_task_id'] = next(iter(tasks))
    elif tasks:
        result.update(recorded_tasks=tasks, candidate_task_ids=bindings)
    used, added = 0, set()
    for action, feedback, basis in links(indexed):
        if action['id'] not in selected and feedback['id'] not in selected: continue
        result['recorded_result_links'].append(dict(action_record_id=action['id'], feedback_record_id=feedback['id'],
            action_event_id=action['event_id'], feedback_event_id=feedback['event_id'], basis=basis,
            native_scope=action['scope']))
        for record in (action, feedback):
            if record['id'] in added: continue
            added.add(record['id'])
            # Only add text absent from the selected ranges; an in-page record
            # can still be partial when a source page splits a long message.
            spans = sorted((max(record['start'], f['start']), min(record['end'], f['end']))
                           for f in fragments if overlaps(record, f))
            cursor = record['start']
            for start, end in spans:
                if start > cursor: break
                cursor = max(cursor, end)
            if cursor >= record['end']: continue
            view = context.readable(record)
            view.update(event_id=record['event_id'], native_scope=record['scope'])
            cost = len(dumps(view))
            if used + cost > LINK_LIMIT:
                result['omitted_linked_record_ids'].append(record['id']); continue
            result['linked_source_records'].append(view); used += cost
    return result
