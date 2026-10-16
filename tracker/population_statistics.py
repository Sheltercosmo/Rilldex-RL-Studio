"""Shared descriptive reducers; no inference, matching or population selection."""
import math
import statistics
from collections import Counter
from .schema import InputError
from . import training_samples


def measured(row):
    m = row.get('measurement')
    return m if m and m['status'] == 'available' and m['value'] is not None else None


def source_rows(rows):
    """One source-context observation per immutable rollout, never per sample.

    Conflicting copies indicate a broken binding; choosing the first would make
    results arrival-dependent. Unbound samples have no source observation.
    """
    sources = {}
    fields = ('status', 'value', 'numerator', 'denominator', 'opportunities', 'unknown')
    for row in rows:
        rid = row.get('run_id')
        if not rid: continue
        if rid in sources:
            a = sources[rid].get('measurement') or {}; b = row.get('measurement') or {}
            if any(a.get(k) != b.get(k) for k in fields):
                raise InputError('Conflicting measurements for the same source rollout')
        else: sources[rid] = row
    return list(sources.values())


def summary(rows, opportunity_ratio, *, source_weighted=False):
    source_weighted = source_weighted or any(r.get('sample_identity_schema') == training_samples.VERSION for r in rows)
    observations = source_rows(rows) if source_weighted else rows
    known = [measured(r) for r in rows]; known = [m for m in known if m]
    observed = [measured(r) for r in observations if measured(r)]
    reasons = Counter((r.get('measurement') or {}).get('status', 'not_materialized') for r in rows if not measured(r))
    result = {'population': len(rows), 'measured': len(known), 'missing': len(rows)-len(known),
              'missing_statuses': dict(reasons), 'mean_per_rollout': sum(m['value'] for m in observed)/len(observed) if observed else None,
              'pooled_opportunities': None}
    if source_weighted:
        result.update(weighting='unique_source_rollout', measurement_grain='source_rollout_context',
            source_rollouts=len(observations), source_measured=len(observed),
            samples_without_source=sum(not r.get('run_id') for r in rows))
    if opportunity_ratio:
        complete = [r['measurement'] for r in observations if r.get('measurement') and
                    all(type(r['measurement'].get(k)) is int and r['measurement'][k] >= 0
                        for k in ('numerator', 'denominator', 'opportunities', 'unknown')) and
                    r['measurement']['numerator'] <= r['measurement']['denominator'] and
                    r['measurement']['denominator'] + r['measurement']['unknown'] == r['measurement']['opportunities']]
        n = sum(m['numerator'] for m in complete); d = sum(m['denominator'] for m in complete)
        result['pooled_opportunities'] = {'value': n/d if d else None, 'numerator': n, 'denominator': d,
            'opportunities': sum(m['opportunities'] for m in complete), 'unknown': sum(m['unknown'] for m in complete),
            'rollouts_with_counts': len(complete), 'rollouts_without_counts': len(observations)-len(complete)}
    return result


def spearman(pairs):
    """Average ranks for ties; exploratory coefficient, never a significance test."""
    if len(pairs)<5:return {'rho':None,'n':len(pairs),'reason':'At least five paired rollouts required'}
    def ranks(values):
        positions={}
        for rank,value in enumerate(sorted(values),1):positions.setdefault(value,[]).append(rank)
        return [statistics.fmean(positions[v]) for v in values]
    x=ranks([p[0] for p in pairs]);y=ranks([p[1] for p in pairs]);mx=statistics.fmean(x);my=statistics.fmean(y)
    dx=[v-mx for v in x];dy=[v-my for v in y];den=math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    if not den:return {'rho':None,'n':len(pairs),'reason':'One or both metrics are constant in the paired sample'}
    return {'rho':max(-1,min(1,sum(a*b for a,b in zip(dx,dy))/den)),'n':len(pairs),'reason':None}
