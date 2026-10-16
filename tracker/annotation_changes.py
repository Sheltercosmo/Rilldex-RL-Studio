"""Source-aligned annotation changes and their effect on recorded graph measures.

Neither graph is promoted to ground truth. No model calls, fuzzy text matching,
or transfer of relationships across changed boundaries takes place here.
"""
from collections import Counter, defaultdict

from . import graph_store, graph_queries
from .schema import InputError, digest

VERSION = 'annotation-changes/1'
STRUCTURAL = {'grounded_in', 'next_record', 'next_unit'}


def _inventory(graph):
    graph_store.validate(graph)
    nodes = {n['id']: n for n in graph['nodes']}
    if len(nodes) != len(graph['nodes']):
        raise InputError('Duplicate graph node identity')
    events = {n['properties']['id']: n for n in nodes.values() if n['kind'] == 'event'}
    if len(events) != sum(n['kind'] == 'event' for n in nodes.values()):
        raise InputError('Duplicate source event identity')
    units, by_event, keys = {}, defaultdict(list), {}
    for n in nodes.values():
        if n['kind'] == 'event':
            keys[n['id']] = ('event', n['properties']['id'])
        elif n['kind'] == 'unit':
            p = n['properties']; ref = p.get('source', {})
            e = events.get(ref.get('event_id'))
            start, end = ref.get('start'), ref.get('end')
            if (e is None or type(start) is not int or type(end) is not int or
                    not 0 <= start < end <= len(e['properties']['text']) or
                    ref.get('text') != e['properties']['text'][start:end] or
                    ref.get('source_pointer') != e['properties'].get('source_pointer')):
                raise InputError('Annotation comparison requires exact source-bound units')
            if (n.get('trajectory_id') != e.get('trajectory_id') or
                    p.get('trajectory_id') != e.get('trajectory_id') or
                    n.get('event_index') != e.get('event_index') or
                    p.get('actor') != e['properties'].get('actor') or
                    n.get('activity') != p.get('activity')):
                raise InputError('Unit attribution or activity differs from its stored source')
            key = ('unit', n['trajectory_id'], ref['event_id'], start, end)
            if key in units:
                raise InputError('Duplicate unit source span')
            units[key] = n; by_event[ref['event_id']].append(n); keys[n['id']] = key
        else:
            # A derived object is comparable only if its identity AND content
            # survive unchanged. Never guess that similarly named targets match.
            keys[n['id']] = ('object', n['kind'], n['id'], digest(n))
    for group in by_event.values():
        group.sort(key=lambda n: n['properties']['source']['start'])
        if any(a['properties']['source']['end'] > b['properties']['source']['start']
               for a, b in zip(group, group[1:])):
            raise InputError('Overlapping source units cannot be aligned unambiguously')
    edge_ids = set()
    for e in graph['edges']:
        if e['id'] in edge_ids or e['source'] not in nodes or e['target'] not in nodes:
            raise InputError('Duplicate or dangling graph relationship')
        edge_ids.add(e['id'])
    return dict(nodes=nodes, events=events, units=units, by_event=by_event, keys=keys)


def _unit(n):
    p = n['properties']
    return dict(id=n['id'], activity=n.get('activity'), kind=p.get('kind'),
                actor=p.get('actor'), status=p.get('status'), source=p['source'])


def _field_changes(a, b):
    left, right = a['properties'], b['properties']
    fields = []
    for key in sorted(set(left.get('content', {})) | set(right.get('content', {}))):
        x, y = left.get('content', {}).get(key), right.get('content', {}).get(key)
        if x != y:
            fields.append(dict(field=key, baseline=x, current=y))
    if left.get('plan_structure') != right.get('plan_structure'):
        fields.append(dict(field='plan_structure', baseline=left.get('plan_structure'),
                           current=right.get('plan_structure')))
    return fields


def _span_components(left, right):
    """Linear sweep after sorting; touching spans are distinct, not overlapping."""
    rows = sorted([(n['properties']['source']['start'], n['properties']['source']['end'], side, n)
                   for side, units in [('baseline', left), ('current', right)] for n in units],
                  key=lambda row: (row[0], row[1], row[2]))
    component, end = [], -1
    for row in rows:
        if component and row[0] >= end:
            yield component
            component = []
        component.append(row); end = max(end, row[1])
    if component:
        yield component


def _delta_counts(left, right, names):
    return [dict(zip(names, key if isinstance(key, tuple) else (key,)),
                 baseline=left[key], current=right[key], delta=right[key]-left[key])
            for key in sorted(set(left) | set(right), key=lambda k: str(k))]


def _patterns(inventory):
    activities = Counter(); transitions = Counter(); streams = defaultdict(list)
    for n in inventory['units'].values():
        if n['properties'].get('actor') != 'agent' or n['properties'].get('kind') == 'feedback':
            continue
        activities[n.get('activity')] += 1
        streams[n['trajectory_id']].append(n)
    for stream in streams.values():
        stream.sort(key=lambda n: (n['event_index'], n['properties']['source']['start']))
        transitions.update((a.get('activity'), b.get('activity')) for a, b in zip(stream, stream[1:]))
    return activities, transitions


def _relations(graph, inventory):
    groups = defaultdict(list)
    for e in graph['edges']:
        if e['type'] not in STRUCTURAL:
            groups[(e['type'], inventory['keys'][e['source']], inventory['keys'][e['target']])].append(e)
    return groups


def compare(baseline, current, *, requirements=()):
    """Compare immutable graphs of the SAME source revision, without writes.

    Exact spans separate boundary errors from activity/content disagreements.
    Overlap groups are review aids, never relaxed matches. Query results retain
    recorded-match semantics and their denominators, not a claim of behavior rate.
    """
    if (baseline.get('run_id'), baseline.get('source_hash')) != (current.get('run_id'), current.get('source_hash')):
        raise InputError('Compare annotations of the same rollout source revision')
    if not isinstance(requirements, (list, tuple)) or len(requirements) > 10:
        raise InputError('Supply at most ten explicit graph requirements')
    requirements = [graph_queries.validate(q) for q in requirements]
    before, after = _inventory(baseline), _inventory(current)
    if before['events'] != after['events']:
        raise InputError('Source events differ between annotation snapshots')
    matched = []; boundary_changes = []; changed = set(); aligned = set()
    for key in sorted(set(before['units']) & set(after['units']), key=str):
        a, b = before['units'][key], after['units'][key]
        fields = _field_changes(a, b)
        activity_changed = a.get('activity') != b.get('activity')
        kind_changed = a['properties'].get('kind') != b['properties'].get('kind')
        status_changed = a['properties'].get('status') != b['properties'].get('status')
        matched.append(dict(baseline=_unit(a), current=_unit(b),
                            activity_changed=activity_changed, kind_changed=kind_changed, status_changed=status_changed,
                            content_changes=fields))
        aligned.add(key)
        if fields or activity_changed or kind_changed or status_changed:
            changed.add(key)
    for event in sorted(set(before['by_event']) | set(after['by_event'])):
        left = [n for n in before['by_event'].get(event, []) if before['keys'][n['id']] not in aligned]
        right = [n for n in after['by_event'].get(event, []) if after['keys'][n['id']] not in aligned]
        for group in _span_components(left, right):
            a = [n for _, _, side, n in group if side == 'baseline']
            b = [n for _, _, side, n in group if side == 'current']
            kind = ('added' if not a else 'removed' if not b else
                    'split' if len(a) == 1 and len(b) > 1 else
                    'merged' if len(a) > 1 and len(b) == 1 else 'resegmented')
            boundary_changes.append(dict(event_id=event, kind=kind,
                                         baseline=[_unit(n) for n in a], current=[_unit(n) for n in b]))

    a_activities, a_transitions = _patterns(before); b_activities, b_transitions = _patterns(after)
    a_relations, b_relations = _relations(baseline, before), _relations(current, after)
    relation_changes = []; retained = 0; evidence_changed = []
    for key in sorted(set(a_relations) | set(b_relations), key=str):
        a, b = a_relations[key], b_relations[key]
        common = min(len(a), len(b)); retained += common
        if len(a) != len(b):
            relation_changes.append(dict(type=key[0], source_anchor=list(key[1]), target_anchor=list(key[2]),
                baseline_edge_ids=[e['id'] for e in a], current_edge_ids=[e['id'] for e in b],
                baseline=len(a), current=len(b), delta=len(b)-len(a)))
        if common and sorted(digest(e['properties']) for e in a) != sorted(digest(e['properties']) for e in b):
            evidence_changed.append(dict(type=key[0], baseline_edge_ids=[e['id'] for e in a],
                                         current_edge_ids=[e['id'] for e in b]))
    measures = []
    for q in requirements:
        a, b = graph_queries.evaluate(baseline, q), graph_queries.evaluate(current, q)
        x, y = a['recorded_match_fraction'], b['recorded_match_fraction']
        # Exact anchor alignment exposes denominator churn even at equal counts.
        ac = {before['keys'][row['anchor']]: row for row in a['cases']}
        bc = {after['keys'][row['anchor']]: row for row in b['cases']}
        cases = []
        for key in sorted(set(ac) | set(bc), key=str):
            ar, br = ac.get(key), bc.get(key)
            status = ('anchor_added' if ar is None else 'anchor_removed' if br is None else
                      'match_changed' if bool(ar['matches']) != bool(br['matches']) else 'unchanged')
            if status != 'unchanged':
                cases.append(dict(anchor=list(key), change=status, baseline=ar, current=br))
        measures.append(dict(requirement=q, baseline=a, current=b, changed_cases=cases,
            delta=dict(anchors=b['anchors']-a['anchors'], matched_anchors=b['matched_anchors']-a['matched_anchors'],
                       recorded_match_fraction=y-x if x is not None and y is not None else None),
            same_anchor_population=set(ac) == set(bc)))
    review = (current.get('semantic_context') or {}).get('unit_reviews', {})
    return dict(schema=VERSION, run_id=baseline['run_id'], source_hash=baseline['source_hash'],
        baseline_graph_id=baseline['id'], current_graph_id=current['id'],
        observers=dict(baseline=baseline['observer'], current=current['observer']),
        coverage=dict(baseline=baseline.get('coverage'), current=current.get('coverage')),
        review=dict(provenance=(current.get('semantic_context') or {}).get('provenance'),
                    latest_unit_review=review.get('document'), dependency_impact=review.get('impact')),
        units=dict(baseline=len(before['units']), current=len(after['units']), exact_span_matches=len(aligned),
                   changed_aligned_units=len(changed), aligned=matched, boundary_changes=boundary_changes),
        activity_counts=_delta_counts(a_activities, b_activities, ('activity',)),
        observed_transitions=_delta_counts(a_transitions, b_transitions, ('from_activity', 'to_activity')),
        relationships=dict(retained_structure=retained, changes=relation_changes,
                           evidence_or_provenance_changes=evidence_changed,
                           excluded_types=sorted(STRUCTURAL)),
        measurements=measures, new_model_calls=0,
        limitations=[
            'Agreement and change, not accuracy: neither snapshot is an independent reference by default.',
            'Only exact source spans align. Split/merge groups aid review and never transfer relationships.',
            'Content changes are exact field differences, not judgments of paraphrase quality or entailment.',
            'Counts cover observed agent units. Consecutive recorded units may have unannotated source between them.',
            'Added/removed links are annotation changes; missing or invalidated links do not establish absent behavior.',
            'Derived objects align only when identity and content are unchanged; target-name similarity is not identity.',
            'Graph measures count recorded matches and retain unknowns. A changed unit-window length can change a match.',
            'This full-snapshot comparison does not measure online prefix accuracy or causal training effects.'])


def summary(report):
    """Compact preview; full evidence remains available through compare()."""
    links = Counter()
    for row in report['relationships']['changes']:
        links[row['type']] += row['delta']
    return dict(status='available', changed_aligned_units=report['units']['changed_aligned_units'],
                boundary_changes=dict(Counter(r['kind'] for r in report['units']['boundary_changes'])),
                activities=[r for r in report['activity_counts'] if r['delta']],
                transitions=[r for r in report['observed_transitions'] if r['delta']],
                relationships=[dict(type=k, delta=v) for k, v in sorted(links.items()) if v],
                relationship_groups_changed=len(report['relationships']['changes']),
                note='Changes describe annotations and dependency invalidation, not proven changes in agent behavior.')
