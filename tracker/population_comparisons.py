"""Descriptive comparisons over explicit members and retained observations.

No trainer, activity taxonomy or domain-specific outcome is assumed. Sample
identities, group context and observation definitions are supplied by callers.
"""
import math
from collections import Counter, defaultdict
from .population_statistics import summary, spearman
from .schema import InputError
from . import training_samples

VERSION = 'population-measure-comparison/1'


def available(value):
    return value.get('status') == 'available' and type(value.get('value')) in (float, int) and math.isfinite(value['value'])


def summarize(ids, values, ratio, members=None):
    rows = [{**(members[k] if members else {}),'measurement': values.get(k)} for k in ids]
    return summary(rows, ratio, source_weighted=members is not None)


def contrast(focus, reference, values, ratio, members=None):
    a = summarize(focus, values, ratio, members); b = summarize(reference, values, ratio, members)
    return {'focus': a, 'reference': b, 'difference': a['mean_per_rollout'] - b['mean_per_rollout']
            if a['mean_per_rollout'] is not None and b['mean_per_rollout'] is not None else None,
            **({'shared_source_rollouts':len({members[k]['run_id'] for k in focus if members[k].get('run_id')} &
                {members[k]['run_id'] for k in reference if members[k].get('run_id')})} if members is not None else {})}


def within_groups(samples, focus, reference, values, source_members=None):
    groups = defaultdict(list); missing = 0; excluded = Counter(); comparisons = []
    for s in samples:
        if s['id'] not in focus | reference: continue
        if not s.get('group_id'): missing += 1
        else: groups[(s['experiment'], s['group_id'])].append(s)
    for (experiment, group), members in sorted(groups.items()):
        # No group namespace/producer-equivalence contract has been supplied.
        # Do not merge coincident worker-local identifiers or invent equivalence.
        if len({s['producer'] for s in members}) > 1:
            excluded['ambiguous_group_namespace'] += 1; continue
        context = ('task_id', 'policy_version', 'step')
        if any(len({s.get(k) for s in members}) > 1 for k in context):
            excluded['conflicting_recorded_context'] += 1; continue
        left = [s['id'] for s in members if s['id'] in focus]
        right = [s['id'] for s in members if s['id'] in reference]
        if not left or not right: excluded['no_population_overlap_within_group'] += 1; continue
        result = contrast(left, right, values, False, source_members)
        if result['difference'] is None: excluded['missing_measure_on_one_side'] += 1; continue
        comparisons.append({'experiment': experiment, 'group_id': group, 'producer': members[0]['producer'],
            **result, 'unrecorded_context': [k for k in context if members[0].get(k) is None]})
    return {'groups': len(groups), 'compared_groups': len(comparisons), 'missing_group_samples': missing,
        'excluded_groups': dict(excluded), 'comparisons': comparisons,
        'groups_with_unrecorded_context': sum(bool(c['unrecorded_context']) for c in comparisons),
        'mean_group_difference': sum(c['difference'] for c in comparisons)/len(comparisons) if comparisons else None,
        'definition': 'Equal-weight mean of within-recorded-group focus minus reference '+('unique source-rollout means' if source_members is not None else 'sample means')+'. Incompatible contexts and ambiguous producer namespaces are excluded. This does not establish a controlled or causal comparison.'}


def compare(samples, focus, reference, measures):
    ids = {s['id'] for s in samples}
    if len(ids) != len(samples) or not (set(focus) | set(reference)) <= ids or not measures:
        raise InputError('Unique samples, bound population members and measures are required')
    if any(v.get('status') == 'available' and not available(v) for m in measures for v in m['values'].values()):
        raise InputError('Available measurements must be finite numbers')
    focus = set(focus); reference = set(reference); union = focus | reference
    independent=any(s.get('sample_identity_schema')==training_samples.VERSION for s in samples)
    if independent and any(s.get('sample_identity_schema')!=training_samples.VERSION for s in samples):
        raise InputError('Compare one sample identity contract at a time')
    members={s['id']:s for s in samples} if independent else None
    sources = defaultdict(list)
    for s in samples:
        if s['id'] in union and s.get('run_id'): sources[s['run_id']].append(s['id'])
    bound = sum(len(v) for v in sources.values())
    common = {s for s in union if all(available(m['values'].get(s, {})) for m in measures)}
    results = []
    for m in measures:
        values = m['values']; ratio = m['aggregation'] == 'opportunity_ratio'
        # Validate copies across both sides too, even if each side has one sample.
        if independent:summarize(sorted(union),values,ratio,members)
        results.append({**m, **contrast(sorted(focus), sorted(reference), values, ratio,members),
            'common_support': contrast(sorted(focus & common), sorted(reference & common), values, ratio,members),
            'within_group': within_groups(samples, focus, reference, values,members),
            'common_within_group': within_groups(samples, focus & common, reference & common, values,members)})
    associations = []
    for i, a in enumerate(measures):
        for b in measures[i+1:]:
            paired = sorted(k for k in union if available(a['values'].get(k, {})) and available(b['values'].get(k, {})))
            weighted = list({members[k]['run_id']:k for k in paired if members[k].get('run_id')}.values()) if independent else paired
            associations.append({'x': a['monitor']['id'], 'y': b['monitor']['id'], 'sample_ids': paired,
                **spearman([(a['values'][k]['value'], b['values'][k]['value']) for k in weighted]),
                **({'weighting':'unique_source_rollout','paired_samples':len(paired),
                    'source_run_ids':sorted(members[k]['run_id'] for k in weighted)} if independent else {})})
    return {'schema': 'population-measure-comparison/2' if independent else VERSION, 'samples': samples, 'focus_ids': sorted(focus), 'reference_ids': sorted(reference),
        'source_coverage': {'sample_members':len(union),'source_bound_samples':bound,'unique_source_rollouts':len(sources),
            'samples_without_source':len(union)-bound,
            'shared_sources':[{'run_id':k,'sample_ids':sorted(v)} for k,v in sorted(sources.items()) if len(v)>1]},
        'overlap_ids': sorted(focus & reference), 'common_support_ids': sorted(common), 'metrics': results,
        'associations': associations,
        **({'weighting':'unique_source_rollout','measurement_grain':'source_rollout_context'} if independent else {}),
        'limits': [('Stage counts count samples; means, pooled opportunities and associations weight unique bound source rollouts. Whole-source behavior is context, not behavior attributed to sample spans.' if independent else 'Each declared sample has one weight; repeated trainer uses do not add weight. Multiple samples may still share one rollout source.'),
            'Available-only means can use different samples. Common support keeps samples measured by every selected monitor, but can still be a biased subset.',
            'A missing training-use record does not establish non-use; stage comparisons show recorded membership only.',
            'Overlap, task mix, group dependence and observation coverage limit interpretation. No causal effect or statistical significance is claimed.',
            ('Pairwise rank associations use unique bound source rollouts in the union; all paired sample IDs are retained. Shared episodes are not independent sample observations.' if independent else 'Pairwise rank associations use unique members of the union and their own paired coverage, not the common-support subset.')]}
