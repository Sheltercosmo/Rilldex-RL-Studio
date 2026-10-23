"""Turn supported work recurrences into inspectable recorded-input comparisons.

No inference is run here. Work identity comes from the saved observer; native
dispatches, outputs and their equality come from the bound source graph.
"""
from collections import Counter, defaultdict
import re

from . import action_comparison, work_episodes
from .schema import digest

VERSION = 'repeated-work-comparisons/1'
RECIPE = VERSION + '|' + work_episodes.VERSION + '|' + action_comparison.VERSION
LIMIT = ('Recorded same-work pairs only; unlinked actions are outside this population. '
         'Unchanged calls may follow changed files, state or prerequisites. Matching captured '
         'feedback does not establish identical effects, a failed loop or wasted compute. '
         'Input changes do not establish a new strategy or successful recovery.')
MEASURES = {
    'revisit_input_change_fraction': ('inputs_changed', 'Changed inputs on work revisits',
        'Revisits with changed recorded inputs / comparable saved same-work pairs. Uses native tool and arguments when both are captured; otherwise full recorded action text. Gaps and unsupported comparisons remain unknown.'),
    'revisit_exact_repeat_fraction': ('inputs_and_feedback_match', 'Repeated inputs and feedback',
        'Same-work pairs repeating both captured inputs and full ordered feedback / pairs with comparable inputs and source-bound feedback. Missing, shared, empty, late earlier feedback and observation gaps remain unknown. This is not a failure rate.'),
}
_META = re.compile(r'^(?:\[(?:Python Interpreter:|Jupyter |this is the (?:beginning|end) of the file)|\(this is the (?:beginning|end) of the file\)|\S+@\S+:.*\$)', re.I)
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def _has_content(text):
    # Only exclude recognized environment wrappers; compare original bytes below.
    return any(line.strip() and not _META.match(line.strip()) for line in _ANSI.sub('', text).splitlines())


def project(graph, *, _episodes=None):
    episodes = work_episodes.project(graph) if _episodes is None else _episodes
    compare = action_comparison.comparator(graph)
    resolve = action_comparison.source_resolver(graph)
    nodes = {n['id']: n for n in graph['nodes']}
    responses, targets = defaultdict(dict), defaultdict(set)
    for edge in graph['edges']:
        a, f = nodes.get(edge['target']), nodes.get(edge['source'])
        if edge['type'] != 'response_to' or not a or not f or a['kind'] != 'event' or f['kind'] != 'event':
            continue
        if a['properties'].get('kind') != 'action' or f['properties'].get('kind') != 'feedback':
            continue
        responses[a['id']][f['id']] = edge['id']
        targets[f['id']].add(a['id'])

    def feedback(action, before=None):
        bindings = responses.get(action['node_id'], {})
        ids = sorted(bindings, key=lambda k: (nodes[k]['event_index'], k))
        reasons = []
        if not ids: reasons.append('No source-bound feedback recorded')
        for nid in ids:
            n = nodes[nid]; p = n['properties']
            if len(targets[nid]) != 1: reasons.append('Feedback is shared between dispatches')
            if (n['trajectory_id'] != action['trajectory_id'] or p.get('context_id') != action.get('context_id')
                    or p.get('copied_context') or p.get('agent_visibility') == 'not_established'):
                reasons.append('Feedback scope or visibility is unresolved')
            if (n['event_index'] <= action['index'] or p.get('order_known') is False
                    or before is not None and n['event_index'] >= before):
                reasons.append('Earlier feedback was not recorded before the revisit' if before is not None else 'Feedback order is unresolved')
            if not isinstance(p.get('text'), str) or not _has_content(p['text']):
                reasons.append('Feedback is empty or contains only environment metadata')
        return dict(node_ids=ids, edge_ids=[bindings[k] for k in ids], reasons=list(dict.fromkeys(reasons)),
                    hashes=[digest(nodes[k]['properties'].get('text')) for k in ids])

    rows = []
    for episode in episodes['episodes']:
        previous, current = episode['previous_unit_id'], episode['current_unit_id']
        dispatch = compare(previous, current)
        a, b = resolve(previous), resolve(current)
        before = feedback(a, b['index']) if a and b else dict(node_ids=[], edge_ids=[], reasons=['Action source binding unavailable'], hashes=[])
        after = feedback(b) if b else dict(node_ids=[], edge_ids=[], reasons=['Action source binding unavailable'], hashes=[])
        reasons = []
        if episode['category'] == 'interrupted': reasons.append('Intervening action observations or order are incomplete')
        if dispatch['status'] == 'unavailable': reasons.append(dispatch['reason'])
        inputs = None if reasons else dispatch['status'] == 'changed'
        feedback_reasons = [*reasons, *before['reasons'], *after['reasons']]
        same_feedback = None if feedback_reasons else before['hashes'] == after['hashes']
        both = None if inputs is None or same_feedback is None else not inputs and same_feedback
        row = dict(id='repeat-'+digest([graph['id'], previous, current]), episode=episode,
            previous_node_id=previous, current_node_id=current, dispatch=dispatch,
            feedback=dict(status='unavailable' if same_feedback is None else 'unchanged' if same_feedback else 'changed',
                previous=before, current=after, reasons=list(dict.fromkeys(feedback_reasons))),
            inputs_changed=inputs, inputs_and_feedback_match=both, input_reasons=reasons,
            node_ids=sorted({previous, current, *[c['unit_id'] for c in episode['cards']],
                             *before['node_ids'], *after['node_ids'], *[s['node_id'] for s in dispatch.get('sources', [])]}),
            edge_ids=sorted({*episode['edge_ids'], *before['edge_ids'], *after['edge_ids']}))
        # Identity closure can refer to an older member beyond the consecutive pair.
        row['node_ids'] = sorted(set(row['node_ids']) | {n for e in graph['edges'] if e['id'] in row['edge_ids'] for n in (e['source'], e['target'])})
        rows.append(row)
    coverage = dict(episodes['counts'], pairs=len(rows), input_comparisons=sum(r['inputs_changed'] is not None for r in rows),
        feedback_comparisons=sum(r['inputs_and_feedback_match'] is not None for r in rows),
        comparison_bases=dict(Counter(r['dispatch']['basis'] for r in rows if r['inputs_changed'] is not None)),
        disputed_identity_units=len(episodes['disputed_identity_units']), invalid_identity_links=len(episodes['issues']))
    value = dict(schema=VERSION, run_id=graph['run_id'], graph_id=graph['id'], source_hash=graph['source_hash'],
                 rows=rows, coverage=coverage, limits=LIMIT)
    return dict(id='repeated-work-'+digest(value), **value)


def measure(output, key):
    cases = []
    for row in output['rows']:
        taken = row[key]
        status = ('inputs_changed' if taken else 'inputs_unchanged') if key == 'inputs_changed' else ('inputs_and_feedback_match' if taken else 'records_differ')
        cases.append(dict(id=row['id'], label=row['episode']['target'], taken=taken,
            status='unknown' if taken is None else status,
            node_ids=row['node_ids'], edge_ids=row['edge_ids'], repeated_work=row))
    n = sum(c['taken'] is True for c in cases); d = sum(c['taken'] is not None for c in cases)
    return dict(value=n/d if d else None, numerator=n, denominator=d, opportunities=len(cases), unknown=len(cases)-d,
        cases=cases, coverage=output['coverage'], reason=None if d else 'No comparable saved same-work pairs. Open coverage to inspect missing inputs and links.')
