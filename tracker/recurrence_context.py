"""Evidence for comparing two occurrences of already matched work.

The interval preserves prose, other participants and responses, not just tool
calls. It does not classify strategy, causation, progress or feedback quality.
"""
from copy import deepcopy
from .schema import InputError, digest

VERSION = 'recurrence-context/2'


def build(run, document, previous_id, current_id):
    events = {e['id']: e for e in run['events']}
    units = {u['id']: u for u in document['units']}
    before, after = units[previous_id], units[current_id]

    def order(u):
        ref = u['source']
        return events[ref['event_id']]['index'], ref['start'], ref['end']

    def available(u, cutoff=after):
        a, b = order(u), order(cutoff)
        return a[0] < b[0] or a[0] == b[0] and a[2] <= b[2]

    if (before['kind'] != 'action' or after['kind'] != 'action' or
        (before['actor'], before['trajectory_id']) != (after['actor'], after['trajectory_id']) or
        order(before) >= order(after)):
        raise InputError('Recurrence context requires earlier and later actions in one actor trajectory')
    if order(before)[0] == order(after)[0] and order(before)[2] > order(after)[1]:
        raise InputError('Recurrence endpoints must not overlap')

    trajectory = after['trajectory_id']

    def ordered(ids):
        return sorted(set(ids), key=lambda uid: order(units[uid]))

    def endpoint(action):
        expressions, responses = [], []
        for relation in document['relations']:
            if relation['to'] != action['id'] or relation['type'] not in {'recorded_with', 'feedback_for'}:
                continue
            source = units.get(relation['from'])
            if source is None or source['trajectory_id'] != trajectory:
                raise InputError('Recurrence context binding has a missing or cross-trajectory source')
            if relation['type'] == 'feedback_for':
                if source['kind'] != 'feedback' or order(source) <= order(action):
                    raise InputError('Recurrence response must follow its dispatch')
                responses.append(source['id'])
            else:
                expressions.append(source['id'])
        return {'action_unit_id': action['id'],
                'recorded_expression_unit_ids': ordered(expressions),
                'expression_timing': {uid: 'at_or_before_dispatch' if available(units[uid], action) else 'after_dispatch' for uid in expressions},
                'response_unit_ids': ordered(responses)}

    earlier, current = endpoint(before), endpoint(after)
    between = ordered(u['id'] for u in units.values() if u['trajectory_id'] == trajectory and
                      order(before) < order(u) < order(after) and available(u))
    focus = ordered([previous_id, current_id, *between,
                     *earlier['recorded_expression_unit_ids'], *earlier['response_unit_ids'],
                     *current['recorded_expression_unit_ids'], *current['response_unit_ids']])
    at_cutoff = [uid for uid in focus if available(units[uid])]
    later = [uid for uid in focus if not available(units[uid])]
    cutoff_ids = set(at_cutoff)
    # Retain actual selected assessment links; adjacency alone supplies none.
    assessments = [i for i, r in enumerate(document['relations']) if r['type'] == 'assesses' and
                   r['from'] in cutoff_ids and r['to'] in cutoff_ids and r['from'] in between]

    first, last = order(before), order(after)
    missing, empty = [], []
    for event in run['events']:
        if event.get('trajectory_id') != trajectory or not first[0] <= event['index'] <= last[0]:
            continue
        text = event.get('text', '')
        lo = before['source']['start'] if event['id'] == before['source']['event_id'] else 0
        hi = after['source']['end'] if event['id'] == after['source']['event_id'] else len(text)
        spans = sorted((max(lo, u['source']['start']), min(hi, u['source']['end']))
                       for u in units.values() if u['source']['event_id'] == event['id'] and
                       u['trajectory_id'] == trajectory and u['source']['end'] > lo and u['source']['start'] < hi)
        if not text:
            empty.append(event['id'])
        cursor = lo
        for start, end in [*spans, (hi, hi)]:
            if start > cursor and text[cursor:start].strip():
                missing.append({'event_id': event['id'], 'start': cursor, 'end': start,
                                'source_pointer': event.get('source_pointer'), 'text': text[cursor:start]})
            cursor = max(cursor, end)

    a, b = events[before['source']['event_id']], events[after['source']['event_id']]
    # JSON hashing keeps true distinct from 1, ignores object key order, and
    # retains ordered list values. Missing arguments are not equal arguments.
    structured = (a.get('argument_status') == b.get('argument_status') == 'json_object' and
                  isinstance(a.get('arguments'), dict) and isinstance(b.get('arguments'), dict) and
                  isinstance(a.get('tool'), str) and bool(a['tool']) and
                  isinstance(b.get('tool'), str) and bool(b['tool']))
    comparison = {'status': 'not_comparable',
                  'reason': 'Both recorded tool names and structured argument objects are required.'}
    if structured:
        tool_changed = a['tool'] != b['tool']
        arguments_changed = digest(a['arguments']) != digest(b['arguments'])
        keys = sorted(a['arguments'].keys() | b['arguments'].keys())
        comparison = {'status': 'changed' if tool_changed or arguments_changed else 'identical',
                      'tool_before': a['tool'], 'tool_after': b['tool'], 'tool_changed': tool_changed,
                      'changed_top_level_arguments': [key for key in keys if key not in a['arguments'] or
                          key not in b['arguments'] or digest(a['arguments'][key]) != digest(b['arguments'][key])],
                      'before_arguments': deepcopy(a['arguments']), 'after_arguments': deepcopy(b['arguments'])}
    comparison['meaning'] = ('Recorded invocation equality only. Identical calls can follow changed artifacts, '
                             'new evidence or authorization; argument changes need not change strategy.')
    earlier_text = a.get('text', '')[before['source']['start']:before['source']['end']]
    later_text = b.get('text', '')[after['source']['start']:after['source']['end']]
    comparison['source_text_status'] = ('identical' if earlier_text == later_text else 'different') if earlier_text and later_text else 'unavailable'
    comparison['source_text_meaning'] = 'Exact recorded action text only; a publisher description does not establish native invocation equality.'
    from .scope_context import build as requested_scope
    return {'schema': VERSION, 'previous': earlier, 'current': current,
            'requested_scope':requested_scope(run,document,before,after),
            'between_unit_ids': between, 'focus_unit_ids': focus,
            'available_at_current_dispatch_unit_ids': at_cutoff,
            'after_current_dispatch_unit_ids': later,
            'assessment_relation_indices': assessments,
            'dispatch_comparison': comparison,
            'unrepresented_source_ranges': missing, 'events_without_text': empty,
            'cutoff': dict(after['source']),
            'scope': 'One recorded trajectory, including all participants between the occurrences. Endpoint expressions and linked responses are also included; responses after the later dispatch are explicitly separated.',
            'limits': 'Selected local meanings and links, not new semantic judgments. An assessment is the agent\'s claim. Source coverage is not semantic accuracy; missing text or units remain unobserved. No causal response, active goal, failed loop or strategy change is inferred.'}
