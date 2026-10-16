"""Descriptive behavior comparisons for one explicitly named producer filter.

No filter decision, group identity, training use or causal credit is inferred.
Inputs are the lineage snapshot's latest records and pinned monitor values.
"""
from collections import Counter, defaultdict
from .schema import digest, dumps
from .population_statistics import measured, summary
from . import training_samples

VERSION = 'training-selection-comparison/1'
STATES = ('admitted', 'rejected', 'unknown', 'conflicting', 'varies_by_batch', 'not_recorded')


def filter_key(record):
    d = record['data']
    return {'producer': record['record_producer'], 'filter': d['filter'], 'definition': d['definition']}


def options(samples):
    found = {}
    for sample in samples:
        for r in sample['records']:
            if r['kind'] == 'selection':
                key = filter_key(r); identifier = 'filter-' + digest(key)
                found[identifier] = {'id': identifier, **key}
    return sorted(found.values(), key=lambda r: (r['filter'], r['definition'], r['producer']))


def decision(sample, selected):
    batches = defaultdict(list)
    for r in sample['records']:
        if r['kind'] == 'selection' and filter_key(r) == {k: selected[k] for k in ('producer', 'filter', 'definition')}:
            batches[r['data']['batch_id']].append(r)
    states = set(); evidence = []
    for batch, records in sorted(batches.items()):
        values = {r['data']['decision'] for r in records}
        state = next(iter(values)) if len(values) == 1 else 'conflicting'
        states.add(state)
        evidence.append({'batch_id': batch, 'decision': state, 'records': [
            {'producer': r['record_producer'], 'id': r['id'], 'revision': r['revision'],
             'decision': r['data']['decision']} for r in records]})
    state = ('not_recorded' if not states else 'conflicting' if 'conflicting' in states else
             'varies_by_batch' if {'admitted', 'rejected'} <= states else
             'unknown' if 'unknown' in states else next(iter(states)))
    return {'state': state, 'batches': evidence}






def matched_groups(rows):
    groups = defaultdict(list); missing_group = 0
    for r in rows:
        if not r.get('group_id'): missing_group += 1
        else: groups[r['group_id']].append(r)
    comparisons = []; excluded = Counter(); missing_context = 0
    for group, members in sorted(groups.items()):
        independent=any(r.get('sample_identity_schema')==training_samples.VERSION for r in members)
        if independent and len({r['producer'] for r in members})>1:
            excluded['ambiguous_group_namespace'] += 1; continue
        # A native group must not silently merge explicitly different contexts.
        if any(len({dumps(r.get(k)) for r in members}) > 1 for k in ('task_id', 'policy_version', 'step')):
            excluded['conflicting_recorded_context'] += 1; continue
        a = [r for r in members if r['filter_decision']['state'] == 'admitted']
        b = [r for r in members if r['filter_decision']['state'] == 'rejected']
        if not a or not b: excluded['no_admitted_rejected_overlap'] += 1; continue
        ma = [measured(r) for r in a if measured(r)]; mb = [measured(r) for r in b if measured(r)]
        if not ma or not mb: excluded['missing_behavior_on_one_side'] += 1; continue
        missing = [k for k in ('task_id', 'policy_version', 'step') if members[0].get(k) is None]
        missing_context += bool(missing)
        left_summary=summary(a,False);right_summary=summary(b,False)
        left=left_summary['mean_per_rollout'];right=right_summary['mean_per_rollout']
        if left is None or right is None:excluded['missing_behavior_on_one_side'] += 1;continue
        comparisons.append({'group_id': group, 'admitted_mean': left, 'rejected_mean': right,
            'difference': left-right, 'admitted_measured': len(ma), 'admitted_population': len(a),
            'rejected_measured': len(mb), 'rejected_population': len(b), 'unrecorded_context': missing,
            **({'weighting':'unique_source_rollout','admitted_sources':left_summary['source_rollouts'],
                'rejected_sources':right_summary['source_rollouts'],
                'shared_source_rollouts':len({r['run_id'] for r in a if r['run_id']} & {r['run_id'] for r in b if r['run_id']})} if independent else {})})
    return {'groups': len(groups), 'compared_groups': len(comparisons), 'excluded_groups': dict(excluded),
        'missing_group_samples': missing_group, 'compared_groups_with_unrecorded_context': missing_context,
        'mean_group_difference': sum(r['difference'] for r in comparisons)/len(comparisons) if comparisons else None,
        'comparisons': comparisons,
        'definition': 'Equal-weight mean of within-recorded-prompt-group admitted minus rejected rollout means. Only measured values on each side contribute. No overlap is unavailable, not zero; recorded group membership does not establish causal control.'}


def project(rows, selected, *, opportunity_ratio=False):
    independent=any(r.get('sample_identity_schema')==training_samples.VERSION for r in rows)
    for r in rows: r['filter_decision'] = decision(r, selected)
    by_state = {state: summary([r for r in rows if r['filter_decision']['state'] == state], opportunity_ratio,source_weighted=independent) for state in STATES}
    bins = []
    for step in sorted({r['step'] for r in rows if 'step' in r}):
        points = [r for r in rows if r.get('step') == step]
        bins.append({'step': step, 'states': {state: summary([r for r in points if r['filter_decision']['state'] == state], opportunity_ratio,source_weighted=independent) for state in ('admitted', 'rejected')}})
    content = {'schema': VERSION, 'filter': selected, 'states': by_state, 'bins': bins, 'within_group': matched_groups(rows),
        'missing_step': sum('step' not in r for r in rows),
        'inputs': [{'sample': training_samples.reference(r),
            'run_id': r['run_id'], 'monitor_value_id': (r.get('measurement') or {}).get('id'),
            'decision': r['filter_decision']} for r in rows],
        'definition': 'One sample per comparison. Latest explicit record revisions only. Repeated agreeing decisions count once; contradictory decisions in one batch, disagreement across batches, explicit unknown and absent records remain separate. Selection does not establish actual training use. Differences can reflect task mix and missing observations.'}
    if independent:
        content['schema']='training-selection-comparison/2'
        content['definition']='Stage membership counts independent samples. Behavior means and opportunities weight unique bound source rollouts within each population. These are whole-source context, not behavior attributed to the selected sample spans. '+content['definition'].removeprefix('One sample per comparison. ')
    return {'id': 'selection-comparison-' + digest(content), **content}
