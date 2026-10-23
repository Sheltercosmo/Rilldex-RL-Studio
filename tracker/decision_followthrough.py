"""Source-record windows connecting reviewed decisions to saved execution.

This is a deterministic join, not an intent, compliance or success classifier.
No linked action is never treated as evidence that the agent ignored a decision.
"""
from collections import defaultdict
from copy import deepcopy

from .schema import digest
from . import work_dispatches

VERSION = 'decision-followthrough/2'
LIMIT = ('Counts saved action links within a source-record window, not causal effects of a decision. '
         'Unlinked execution remains unobserved. Parent scope can include descendants. '
         'Checks, returned feedback and completion statements do not establish success.')


def attach(graph, outline):
    """Enrich each decision without changing the immutable graph or its labels."""
    nodes = {n['id']: n for n in graph['nodes']}
    events = {n['properties']['id']: n for n in graph['nodes'] if n['kind'] == 'event'}
    cutoff = outline['cutoff_event_index']

    def location(node_id):
        n = nodes.get(node_id)
        if not n: return None
        ref = n['properties'].get('source')
        event = events.get(ref.get('event_id')) if ref else n if n['kind'] == 'event' else None
        if not event or event['event_index'] > cutoff: return None
        p = event['properties']
        if p.get('copied_context'): return None
        return dict(index=event['event_index'], start=ref.get('start') if ref else None,
                    end=ref.get('end') if ref else None, actor=p.get('actor'),
                    lane=(event['trajectory_id'], p.get('context_id')),
                    order_known=p.get('order_known') is not False,
                    event_id=p['id'])

    def in_window(loc, start, end):
        if not loc or loc['lane'] != start['lane']: return 'unresolved'
        if loc['index'] < start['index'] or (end and loc['index'] > end['index']): return 'outside'
        if not loc['order_known']: return 'unresolved'
        if loc['index'] == start['index']:
            if loc['end'] is not None and loc['end'] <= start['start']: return 'outside'
            if loc['start'] is None or loc['start'] < start['end']: return 'unresolved'
        if end and loc['index'] == end['index']:
            if loc['start'] is not None and loc['start'] >= end['end']: return 'outside'
            if loc['end'] is None or loc['end'] > end['start']: return 'unresolved'
        return 'inside'

    for item in outline['items']:
        groups = []
        for d in sorted(item['decisions'], key=lambda d: (d['event_index'], d['evidence']['start'], d['evidence']['end'])):
            ref = d['evidence']
            # Overlapping decision citations cannot define separate intervals.
            if groups and groups[-1]['index'] == d['event_index'] and ref['start'] < groups[-1]['end']:
                groups[-1]['end'] = max(groups[-1]['end'], ref['end'])
                groups[-1]['decisions'].append(d)
            else:
                e = events[ref['event_id']]
                groups.append(dict(index=d['event_index'], start=ref['start'], end=ref['end'],
                                   lane=(e['trajectory_id'], e['properties'].get('context_id')),
                                   order_known=e['properties'].get('order_known') is not False,
                                   event_id=ref['event_id'], decisions=[d]))
        execution = item.get('execution_summary')
        for index, group in enumerate(groups):
            end = groups[index + 1] if index + 1 < len(groups) else None
            types = {d['type'] for d in group['decisions']}
            status = ('conflicting_statements' if len(types) > 1 else
                      'order_unresolved' if not group['order_known'] or (end and not end['order_known']) else
                      'execution_unmapped' if execution is None else 'mapped')
            rows, unresolved = [], defaultdict(list)
            if status == 'mapped':
                for row in execution['rows']:
                    loc = location(row['action_id'])
                    membership = in_window(loc, group, end)
                    if membership == 'outside': continue
                    if membership != 'inside' or loc['actor'] != 'agent':
                        unresolved['actions'].append(row['action_id']); continue
                    copy = deepcopy(row); copy['responses'] = []
                    for response in row['responses']:
                        rloc = location(response['node_id']); membership = in_window(rloc, group, end)
                        if membership == 'outside': continue
                        if membership != 'inside' or rloc['index'] < loc['index']:
                            unresolved['feedback'].append(response['node_id']); continue
                        r = deepcopy(response); r['assessments'] = []
                        for assessment in response['assessments']:
                            aloc = location(assessment['node_id']); membership = in_window(aloc, group, end)
                            if membership == 'outside': continue
                            if membership == 'inside' and aloc['actor'] == 'agent' and aloc['index'] >= rloc['index']:
                                r['assessments'].append(deepcopy(assessment))
                            else: unresolved['assessments'].append(assessment['node_id'])
                        copy['responses'].append(r)
                    rows.append(copy)
            counts = None if status != 'mapped' else work_dispatches.counts(rows)
            value = dict(schema=VERSION, status=status, item_id=item['id'],
                decision_ids=[d['id'] for d in group['decisions']],
                window=dict(start_event_id=group['event_id'], start_event_index=group['index'],
                    start_offset=group['end'], end_event_id=end['event_id'] if end else None,
                    end_event_index=end['index'] if end else cutoff, end_offset=end['start'] if end else None,
                    boundary='next_statement' if end else 'observation_cutoff',
                    next_decision_ids=[d['id'] for d in end['decisions']] if end else []),
                counts=counts, rows=rows, unresolved={k: sorted(set(v)) for k, v in unresolved.items()},
                scope=execution['scope'] if execution else None,
                binding_basis=execution.get('binding_basis') if execution else None,
                binding_ids=execution.get('binding_ids', []) if execution else [], limits=LIMIT)
            value = dict(id='decision-window-' + digest([graph['id'], value]), **value)
            for decision in group['decisions']: decision['followthrough'] = value


def windows(outline):
    """One row per item/decision window, even when citations conflict."""
    unique = {}
    for item in (outline or {}).get('items', []):
        for d in item['decisions']:
            if d.get('followthrough'):
                value = d['followthrough']
                unique[value['id']] = dict(label=item['label'], decision_types=sorted({
                    v['type'] for v in item['decisions'] if v['id'] in value['decision_ids']}), **value)
    return list(unique.values())
