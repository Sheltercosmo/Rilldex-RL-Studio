"""Keep selected evidence attached to its enclosing record and native call."""
from copy import deepcopy

from .action_context import dispatch_prefix, native_dispatch
from .capabilities import links
from .readable_context import project, VERSION as TEXT_VERSION
from .schema import InputError, digest, dumps

VERSION = 'criterion-dispatch-review/2'
FIELDS = ('id', 'index', 'actor', 'kind', 'text', 'tool', 'arguments', 'trajectory_id',
          'context_id', 'source_pointer', 'parent_id', 'source_message_index',
          'call_id', 'source_call_id', 'related_action_ids', 'tool_contract',
          'observation_contract', 'media')


def expand(run, request, *, max_bytes=60000):
    """Restore source context without changing the selected criterion or quotes.

    Relationships come only from recorded identifiers. Whole records are added
    without text truncation; oversized records stay available through source IDs.
    Nothing here determines relevance, state freshness or a compliance verdict.
    """
    from .criterion_review import DISPATCH_VERSION, make_dispatch_request
    state = request['state']
    if state.get('harness') != DISPATCH_VERSION or state.get('source_hash') != digest(run):
        raise InputError('Source context needs an unchanged dispatch comparison')
    if type(max_bytes) is not int or max_bytes < 1:
        raise InputError('Comparison byte budget must be a positive integer')
    def ref(value):
        return {k: value[k] for k in ('event_id', 'start', 'end', 'text', 'source_pointer')}
    original = make_dispatch_request(run, state['selected_action_id'], ref(state['criterion']),
        context=[ref(r) for r in state['context']], model=request['model'])
    if request != original:
        raise InputError('Dispatch comparison differs from its bound source')
    eligible = {e['id']: e for e in dispatch_prefix(run, state['selected_action_id'])}
    native = set(state['native_dispatch']['action_ids'] + state['native_dispatch']['message_ids'])
    selected = {r['event_id'] for r in [state['criterion'], *state['context']]} - native
    reasons = {eid: [{'kind': 'enclosing_selected_range', 'event_id': eid}] for eid in selected}
    relations = []
    for link in links(run)['records']:
        aid, fid = link['action_id'], link['feedback_id']
        if fid not in selected or aid not in eligible or fid not in eligible:
            continue
        relations.append(deepcopy(link))
        reasons.setdefault(aid, []).append({'kind': 'recorded_source_call', 'event_id': fid})
    # One native parent layer, not an inferred chain through unrelated history.
    for eid in sorted(list(reasons), key=lambda key: eligible[key]['index']):
        if eligible[eid]['kind'] != 'action' or eligible[eid]['actor'] != 'agent':
            continue
        for parent in native_dispatch(run, eid)['message_ids']:
            if parent in eligible and parent not in native:
                reasons.setdefault(parent, []).append({'kind': 'native_call_message', 'event_id': eid})
    result = deepcopy(request)
    result['state']['harness'] = VERSION
    context = result['state']['source_context'] = {
        'records': [], 'links': relations, 'not_included': [],
        'scope': ('Enclosing selected records and their recorded calls/messages only. '
                  'Other relevant records and later state changes may be missing. '
                  'Native linkage does not prove semantic identity, success or full-policy coverage.')}
    result['questions']['alignment']['instructions'] += (
        ' Use source_context to inspect identities, alternatives, qualifiers and the scope of recorded calls. '
        'Keep the selected criterion unchanged. A larger source record is context, not a new verdict target. '
        'Check the identifiers and ordering in the source; native links alone do not establish semantic ownership. '
        'Omitted records and unseen changes remain unknown.')
    # Reserve omission metadata for every candidate before allocating text.
    pending = []
    for eid in sorted(reasons, key=lambda key: eligible[key]['index']):
        event = eligible[eid]
        pending.append({'event_id': eid, 'source_pointer': event.get('source_pointer'),
                        'source_chars': len(event['text']), 'reason': 'byte_budget',
                        'relationship': reasons[eid]})
    context['not_included'] = pending.copy()
    if len(dumps(result).encode('utf8')) > max_bytes:
        raise InputError('Comparison context metadata exceeds byte budget; select fewer ranges or increase the budget')
    # Small native calls first, then enclosing evidence, then the governing text.
    priority = sorted(pending, key=lambda r: (r['event_id'] == state['criterion']['event_id'],
                      r['event_id'] in selected, eligible[r['event_id']]['index']))
    for item in priority:
        event = eligible[item['event_id']]
        record = project({k: deepcopy(event[k]) for k in FIELDS if k in event},
                         {'schema': TEXT_VERSION, 'max_event_chars': 128, 'extra_ranges': []},
                         {'event_id': event['id']})
        record.update(source_chars=len(event['text']), relationship=reasons[event['id']], timing='prior')
        context['not_included'].remove(item)
        context['records'].append(record)
        if len(dumps(result).encode('utf8')) > max_bytes:
            context['records'].pop()
            context['not_included'].append(item)
    context['records'].sort(key=lambda r: r['index'])
    context['not_included'].sort(key=lambda r: eligible[r['event_id']]['index'])
    return result
