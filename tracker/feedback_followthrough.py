"""Read saved feedback references alongside subsequent dispatches and outputs.

This is a graph projection, not a recovery classifier. Source order chooses the
next dispatch; it does not establish that the dispatch responds to the feedback.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from .schema import InputError, digest
from .graph_store import validate

VERSION = 'feedback-followthrough/2'
REFERENCES = {'assesses', 'uses_evidence', 'responds_to'}
LIMIT = ('References are saved semantic observations. Next actions are selected by recording order in the same '
         'actor, trajectory and context, not inferred intent. Changed dispatch fields do not establish a changed '
         'strategy or effective correction. Returned output does not establish a comparable passing check. '
         'Missing references and outputs remain unknown; these counts are not a recovery rate.')


def project(graph, cutoff_event_id=None):
    validate(graph)
    from . import map_relationships
    rejected={r['edge_id']:r for r in map_relationships.inspect(graph)['relationships'] if r['status']=='incompatible'}
    nodes = {n['id']: n for n in graph['nodes']}
    events = {n['properties']['id']: n['properties'] for n in nodes.values() if n['kind'] == 'event'}
    if cutoff_event_id is not None and cutoff_event_id not in events:
        raise InputError('Unknown feedback review cutoff event')
    cutoff = events[cutoff_event_id] if cutoff_event_id else None

    def visible(e):
        return bool(e and not e.get('copied_context') and e.get('agent_visibility') != 'not_established'
                    and not e['kind'].startswith('external_') and
                    (cutoff is None or e['trajectory_id'] == cutoff['trajectory_id'] and e['index'] <= cutoff['index']))

    def lane(e): return (e['trajectory_id'], e.get('context_id'))

    def unit(nid):
        n = nodes.get(nid, {}); p = n.get('properties', {}); ref = p.get('source', {})
        e = events.get(ref.get('event_id')); a, b = ref.get('start'), ref.get('end')
        if (n.get('kind') != 'unit' or not visible(e) or p.get('actor') != e.get('actor') or type(a) is not int or type(b) is not int
                or not 0 <= a < b <= len(e['text']) or e['text'][a:b] != ref.get('text')):
            return None
        return p, e

    def record(e, node_id=None):
        return dict(event_id=e['id'], node_id=node_id or 'event:'+e['id'], index=e['index'],
                    actor=e['actor'], kind=e['kind'], text=e['text'], trajectory_id=e['trajectory_id'],
                    context_id=e.get('context_id'), tool=deepcopy(e.get('tool')),
                    arguments=deepcopy(e.get('arguments')))

    def ordered(a, b):
        return lane(a) == lane(b) and a['index'] < b['index']

    # Native bindings work even when the next action has not been semantically
    # annotated. Do not skip it in favour of a later, annotated action.
    origins = defaultdict(set); outputs = defaultdict(set); action_units = defaultdict(list)
    for n in nodes.values():
        checked = unit(n['id'])
        if checked and checked[0].get('kind') == 'action': action_units[checked[1]['id']].append(n['id'])
    for edge in graph['edges']:
        if edge['type'] == 'response_to':
            a = nodes.get(edge['target'], {}); b = nodes.get(edge['source'], {})
            if a.get('kind') != 'event' or b.get('kind') != 'event': continue
            action, feedback = a['properties'], b['properties']
        elif edge['type'] == 'feedback_for':
            a, b = unit(edge['target']), unit(edge['source'])
            if not a or not b or b[0].get('kind') != 'feedback': continue
            action, feedback = a[1], b[1]
        else: continue
        if visible(action) and visible(feedback) and action['kind'] == 'action' and ordered(action, feedback):
            origins[feedback['id']].add(action['id']); outputs[action['id']].add(feedback['id'])

    actions = sorted([e for e in events.values() if visible(e) and e['kind'] == 'action'], key=lambda e:e['index'])
    def action_record(e):
        ids = action_units[e['id']]
        value = record(e, ids[0] if len(ids) == 1 else None)
        value['outputs'] = [record(events[f]) for f in sorted(outputs[e['id']], key=lambda k:events[k]['index'])]
        return value

    rows = []; excluded = []; seen = {}
    for edge in graph['edges']:
        if edge['type'] not in REFERENCES: continue
        a, b = unit(edge['source']), unit(edge['target'])
        if not a or not b or b[0].get('kind') != 'feedback' or a[0].get('actor') != 'agent':
            excluded.append(dict(edge_id=edge['id'], reason='Missing or unavailable source-bound endpoints')); continue
        contribution, current = a; _, feedback = b
        if edge['id'] in rejected:
            excluded.append(dict(edge_id=edge['id'],reason=rejected[edge['id']]['reason']));continue
        if not ordered(feedback, current):
            excluded.append(dict(edge_id=edge['id'], reason='Feedback is not earlier in this context')); continue
        # A relation whose evidence is unavailable at the referring contribution
        # cannot be used merely because its endpoints look plausible.
        valid = True; properties = edge.get('properties', {})
        references = []
        inspector = properties.get('inspector_context') or {}
        if not isinstance(inspector, dict): valid = False; inspector = {}
        for refs in [properties.get('evidence', []), properties.get('context_evidence', []), inspector.get('source_ranges', [])]:
            if not isinstance(refs, list): valid = False
            else: references.extend(refs)
        if properties.get('cutoff') is not None:
            ref = properties['cutoff']
            references.append({**ref, 'start':ref.get('start',0)} if isinstance(ref,dict) else ref)
        for ref in references:
            e = events.get(ref.get('event_id')) if isinstance(ref, dict) else None
            start, end = (ref.get('start'), ref.get('end')) if isinstance(ref, dict) else (None, None)
            if (not visible(e) or lane(e) != lane(current) or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(e['text']) or e['index'] > current['index']
                    or e['index'] == current['index'] and end > contribution['source']['end']
                    or 'text' in ref and e['text'][start:end] != ref['text']): valid = False; break
        if not valid:
            excluded.append(dict(edge_id=edge['id'], reason='Reference evidence is invalid or uses later context')); continue
        key = (edge['source'], edge['target'])
        if key in seen:
            seen[key]['relation_ids'].append(edge['id']); continue
        prior = sorted(origins[feedback['id']])
        previous = events[prior[0]] if len(prior) == 1 else None
        if previous and previous['actor'] != current['actor']: previous = None
        if current['kind'] == 'action':
            following = [current]; selection = 'referencing_dispatch'
        else:
            following = [e for e in actions if ordered(current, e) and e['actor'] == current['actor']]
            first = following[0] if following else None
            # Preserve sibling calls as an unordered batch, never pick a winner.
            following = [e for e in following if first and (e['id'] == first['id'] or
                first.get('parent_id') and e.get('parent_id') == first['parent_id'] or
                first.get('source_message_index') is not None and e.get('source_message_index') == first['source_message_index'])]
            shared_generation = bool(first and (first.get('parent_id') == current['id'] or
                first.get('source_message_index') is not None and first.get('source_message_index') == current.get('source_message_index')))
            selection = 'same_response_dispatches' if shared_generation else 'next_recorded_batch' if len(following) > 1 else 'next_recorded_action' if following else 'not_recorded'
        later = []
        for e in following:
            value = action_record(e)
            fields = ['tool', 'arguments', 'text']
            changed = [k for k in fields if previous and previous.get(k) != e.get(k)]
            value['dispatch_comparison'] = dict(status='unavailable' if previous is None else 'changed' if changed else 'identical',
                changed_fields=changed, basis='Exact recorded tool, arguments and text; not semantic strategy identity')
            later.append(value)
        row = dict(reference_unit_id=edge['source'], feedback_unit_id=edge['target'],
            relation_ids=[edge['id']],
            reference=record(current, edge['source']), feedback=record(feedback, edge['target']),
            original_action=action_record(previous) if previous else None,
            origin_status='unique' if previous else 'ambiguous' if prior else 'unbound',
            following_selection=selection, following=later,
            next_check='Compare the reported constraint with the next dispatch and its output. Establish a common criterion before judging recovery.')
        # The semantic contribution can occupy only part of the source message.
        row['reference']['text'] = contribution['source']['text']
        row['id'] = 'feedback-trail-'+digest([edge['source'], edge['target']])
        rows.append(row); seen[key] = row
    rows.sort(key=lambda r:(r['reference']['trajectory_id'],r['reference']['index'],r['id']))
    counts = Counter(r['following_selection'] for r in rows)
    value = dict(schema=VERSION, graph_id=graph['id'], run_id=graph['run_id'], observer=graph['observer'],
        cutoff_event_id=cutoff_event_id, rows=rows, excluded=excluded,
        counts=dict(referenced_feedback=len({r['feedback']['event_id'] for r in rows}),reference_pairs=len(rows),
                    with_following_action=sum(bool(r['following']) for r in rows),
                    with_returned_output=sum(any(a['outputs'] for a in r['following']) for r in rows),
                    unbound_original_actions=sum(r['original_action'] is None for r in rows),selections=dict(counts)),
        limit=LIMIT, provider_calls=0)
    return {'id':'feedback-review-'+digest(value),**value}
