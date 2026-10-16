"""Behavior of source rollouts on native generation and use coordinates.

No span attribution, causal credit or admission inference. Reuse contributes at
each recorded coordinate, but never multiplies a source's weight inside a point.
"""
from collections import Counter
from .schema import dumps, digest, InputError
from .population_statistics import summary

VERSION = 'training-behavior-timeline/1'
LIMIT = ('Each bound source rollout counts once within a point. Several samples or repeated uses '
         'do not multiply its weight. A source may appear at multiple positions. These are whole-rollout '
         'observations, not the behavior of selected spans, gradient credit or a causal training effect. '
         'Missing receipts do not establish non-use. Task mix and annotation coverage can change the curve.')


def project(samples, sample_ref, *, receipts=None, opportunity_ratio=False):
    """Inputs are already isolated by generation cohort and exact use stream."""
    indexed={dumps(sample_ref(s)):s for s in samples}
    if len(indexed)!=len(samples):raise InputError('Duplicate sample identity in behavior timeline')

    def point(members, uses, *, cases=True):
        eligible=[s for s in members if s['monitor_population']=='included']
        result=summary(eligible,opportunity_ratio,source_weighted=True)
        by_sample={dumps(sample_ref(s)):[] for s in members}
        for use in uses:
            by_sample[dumps(use['sample'])].append({k:use[k] for k in ('id','revision','record_producer','record_schema') if k in use})
        result.update(declared_samples=len(members), use_receipts=len(uses),
            unbound_samples=sum(not s.get('run_id') for s in members),
            monitor_scope=dict(Counter(s['monitor_population'] for s in members)),
            samples=[{**sample_ref(s), 'task_id':s.get('task_id'), 'policy_version':s.get('policy_version'),
                'source':s.get('source'), 'source_mapping_status':s.get('source_mapping_status',s.get('join_status')),
                'monitor_population':s['monitor_population'], 'measurement':s.get('measurement'),
                'uses':by_sample[dumps(sample_ref(s))]} for s in members] if cases else [])
        return result

    points=[]
    if receipts is None:
        for step in sorted({s['step'] for s in samples if 'step' in s}):
            points.append({'step':step,**point([s for s in samples if s.get('step')==step],[])})
        unplaced=point([s for s in samples if 'step' not in s],[])
        total=point(samples,[],cases=False)
    else:
        def members(uses):return [indexed[k] for k in sorted({dumps(r['sample']) for r in uses})]
        for step in sorted({r['data']['learner_step'] for r in receipts}):
            uses=[r for r in receipts if r['data']['learner_step']==step]
            points.append({'step':step,**point(members(uses),uses)})
        unplaced=point([],[]);total=point(members(receipts),receipts,cases=False)
    result={'schema':VERSION,'coordinate':'generation' if receipts is None else 'learner',
            'points':points,'unplaced':unplaced,'total':total,'limit':LIMIT}
    return {**result,'id':'behavior-timeline-'+digest(result)}
