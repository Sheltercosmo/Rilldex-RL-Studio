"""Matched-task inspection within a frozen interval investigation."""
from collections import Counter
from . import failure_investigations, graph_store
from .schema import InputError, digest, dumps
from .case_outcomes import outcome

CONTEXT = ('task_id', 'task_revision', 'environment', 'environment_version', 'split', 'reward_definition')


def capture(store, sources):
    """Pin available graph versions at capture, never when a case is opened."""
    ids = {r['id'] for r in sources}
    result = {rid: {'graphs': []} for rid in ids}
    for graph in graph_store.catalog(store,run_ids=sorted(ids))['graphs']:
        if graph['run_id'] in ids:
            result[graph['run_id']]['graphs'].append({k: graph.get(k) for k in
                ('id', 'observer', 'observer_label', 'source_hash', 'annotation_hash', 'coverage')})
    return {'version': 'case-comparison/2', 'sources': result}


def _parent(store, identifier):
    parent = failure_investigations.read(store, identifier)
    if parent['schema'] not in {'interval-investigation/1', 'case-investigation/1'}:
        raise InputError('Select a saved interval or rollout case comparison')
    return parent


def _status(a, b):
    if a['state'] not in ('complete', 'imported_snapshot') or b['state'] not in ('complete', 'imported_snapshot'):
        return 'unresolved'
    first, second = outcome(a).get('verified_success'), outcome(b).get('verified_success')
    if type(first) is not bool or type(second) is not bool:
        return 'unresolved'
    return 'unchanged' if first == second else 'improved' if second else 'regressed'


def _groups(parent):
    snapshot = parent['snapshot']; membership = snapshot['population']
    baseline = set(membership['baseline']); current = set(membership['current'])
    groups = {}
    for row in snapshot['source_rows']:
        if row['id'] not in baseline and row['id'] not in current: continue
        meta = row['metadata']; context = {k: meta.get(k) for k in CONTEXT}
        # Missing task identity cannot make unrelated rollouts a shared task.
        # Capture adapters encode transport, not task identity. Cross-adapter
        # matching requires all recorded context fields; v1 captures stay fixed.
        complete = all(v is not None and v != '' for v in context.values())
        cross_adapter = snapshot.get('case_evidence', {}).get('version') == 'case-comparison/2' and complete
        key = digest([None if cross_adapter else row['adapter'], context, row['id'] if not context['task_id'] else None])
        group = groups.setdefault(key, dict(id=key, context=context, baseline=[], current=[]))
        if row['id'] in baseline: group['baseline'].append(row)
        if row['id'] in current: group['current'].append(row)
    for group in groups.values():
        a, b = group['baseline'], group['current']
        group['missing_context'] = [k for k, v in group['context'].items() if v is None or v == '']
        group['status'] = ('unmatched' if not a or not b else
            _status(a[0], b[0]) if len(a) == len(b) == 1 else 'choose_rollouts')
    return sorted(groups.values(), key=lambda g: (str(g['context']['task_id'] or ''), g['id']))


def listing(store, identifier, *, status='all', offset=0, limit=20):
    if status not in ('all', 'improved', 'regressed', 'unchanged', 'unresolved', 'choose_rollouts', 'unmatched'):
        raise InputError('Unknown case filter')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise InputError('Invalid comparison page')
    parent = _parent(store, identifier)
    if not parent['snapshot'].get('case_evidence'):
        return {'available': False, 'reason': 'This investigation predates case capture. Create a new comparison to pin its rollout evidence.'}
    groups = _groups(parent); counts = Counter(g['status'] for g in groups)
    selected = [g for g in groups if status == 'all' or g['status'] == status]
    def option(row):
        return {k: row.get(k) for k in ('id', 'metadata', 'state', 'outcome', 'comparison_outcome', 'outcome_evaluation') if k in row}
    return {'available': True, 'counts': dict(counts), 'total_contexts': len(groups), 'filtered_contexts': len(selected),
            'source_counts': {k: len(v) for k, v in parent['snapshot']['population'].items()},
            'context_incomplete': sum(bool(g['missing_context']) for g in groups),
            'offset': offset, 'limit': limit,
            'groups': [{**g, 'baseline': [option(r) for r in g['baseline']], 'current': [option(r) for r in g['current']]} for g in selected[offset:offset+limit]]}


def pair(store, identifier, reference, selected, *, observer=None):
    parent = _parent(store, identifier); snapshot = parent['snapshot']; frozen = snapshot.get('case_evidence')
    if not frozen: raise InputError('Create a new comparison to pin case evidence')
    group = next((g for g in _groups(parent) if reference in {r['id'] for r in g['baseline']} and selected in {r['id'] for r in g['current']}), None)
    if group is None: raise InputError('Choose reference and selected rollouts in the same recorded task context')
    a = next(r for r in group['baseline'] if r['id'] == reference); b = next(r for r in group['current'] if r['id'] == selected)
    available = [frozen['sources'].get(row['id'], {}).get('graphs', []) for row in (a, b)]
    common = set(g['observer'] for g in available[0]) & set(g['observer'] for g in available[1])
    if observer is None:
        semantic = [name for name in sorted(common) if all(any(g['observer'] == name and g['coverage'].get('semantic_relations') != 'unavailable' for g in graphs) for graphs in available)]
        observer = next(iter(semantic), None) or ('source' if 'source' in common else next(iter(sorted(common)), None))
    if observer not in common: raise InputError('This observation protocol is not pinned on both rollouts')
    sides = []
    for row, graphs in zip((a, b), available):
        header = next(g for g in graphs if g['observer'] == observer)
        graph = graph_store.read(store, header['id'])
        if graph['run_id'] != row['id'] or graph['source_hash'] != header['source_hash']:
            raise InputError('Saved case evidence does not match its source')
        sides.append({'run': row, 'graph': header})
    fields = sorted(set(a['metadata']) | set(b['metadata']))
    return {'investigation_id': identifier, 'status': _status(a, b), 'context': group['context'],
            'missing_context': group['missing_context'], 'reference': sides[0], 'selected': sides[1],
            'protocols': [{'id': name, 'label': next(g['observer_label'] for g in available[0] if g['observer'] == name)} for name in sorted(common)],
            'configuration_changes': ([{'field': 'capture_adapter', 'reference': a['adapter'], 'selected': b['adapter']}] if a['adapter'] != b['adapter'] else []) +
                [{'field': k, 'reference': a['metadata'].get(k), 'selected': b['metadata'].get(k)} for k in fields if dumps(a['metadata'].get(k)) != dumps(b['metadata'].get(k))],
            'basis': 'Outcome labels compare reported Boolean success. Reward values are shown separately. Task and context matching do not establish an independent evaluation or a causal effect.'}
