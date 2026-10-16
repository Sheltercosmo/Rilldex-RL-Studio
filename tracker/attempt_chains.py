"""Failure-triggered attempts across rollouts, from explicit producer lineage.

This is execution bookkeeping, not inferred semantic recovery. Missing attempts
stay unresolved; sampled rewards are never converted to pass/fail labels.
"""
from collections import Counter, defaultdict
import json
from .schema import InputError, digest, dumps
from .population_statistics import summary as behavior_summary
from . import task_comparisons

VERSION = 'attempt-chains/2'
LINEAGE = 'recovery-attempt/1'
OUTCOME = 'attempt-outcome/1'


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 500


def validate_attempt(a):
    fields = {'schema', 'producer', 'chain_id', 'attempt_id', 'position', 'budget',
              'previous_attempt_id', 'protocol', 'context', 'reset'}
    if not isinstance(a, dict) or set(a) != fields or a['schema'] != LINEAGE:
        raise InputError('Recovery attempt requires the complete recovery-attempt/1 declaration')
    if not all(_text(a[k]) for k in ('producer', 'chain_id', 'attempt_id', 'protocol')):
        raise InputError('Recovery attempt identities and protocol must be nonempty bounded strings')
    if any(type(a[k]) is not int for k in ('position', 'budget')) or not 1 <= a['position'] <= a['budget'] <= 1000:
        raise InputError('Recovery attempt position must be within the declared budget (1–1,000)')
    if a['position'] == 1:
        if a['previous_attempt_id'] is not None or a['context'] != 'initial':
            raise InputError('Initial attempt has initial context and no predecessor')
    elif not _text(a['previous_attempt_id']) or a['previous_attempt_id'] == a['attempt_id'] or a['context'] not in {
            'failure_feedback', 'fresh_retry', 'other', 'unrecorded'}:
        raise InputError('Recovery attempt needs a distinct predecessor and declared context')
    if a['reset'] not in {'original_state', 'continued_state', 'unrecorded'}:
        raise InputError('Recovery attempt reset must be original_state, continued_state or unrecorded')


def validate_outcome(o):
    if (not isinstance(o, dict) or set(o) != {'schema', 'attempt_id', 'result'}
            or o['schema'] != OUTCOME or not _text(o['attempt_id'])
            or o['result'] not in {'passed', 'failed', 'unknown'}):
        raise InputError('Attempt outcome requires schema, attempt_id and passed/failed/unknown result')


def ratio(values):
    n = values.count('passed'); d = n + values.count('failed')
    return dict(value=n / d if d else None, numerator=n, denominator=d,
                unknown=len(values)-d, opportunities=len(values),
                lower=n/len(values) if values else None,
                upper=(n+len(values)-d)/len(values) if values else None)


def outcome(samples, key):
    records = [r for s in samples for r in s['records'] if r['kind'] == 'score'
               and {k: r['data'][k] for k in ('component', 'definition')} == {k: key[k] for k in ('component', 'definition')}
               and r['record_producer'] == key['producer'] and 'attempt_outcome' in r['data']]
    results = []
    for r in records:
        o = r['data']['attempt_outcome']
        if o['attempt_id'] != samples[0]['attempt']['attempt_id']:
            return 'unknown', 'outcome_identity_mismatch', records
        results.append(o['result'] if r['data']['status'] == 'scored' else 'unknown')
    # Several training samples may carry the same attempt result. Agreement is
    # deduplicated; disagreement, including explicitly unknown results, is shown.
    if not results: return 'unknown', 'outcome_not_recorded', records
    if len(set(results)) != 1: return 'unknown', 'conflicting_outcomes', records
    return results[0], None if results[0] != 'unknown' else 'outcome_unknown', records


def _at(chain, position):
    return next((a for a in chain['attempts'] if a['position'] == position), None)


def _cumulative(chain, budget):
    if chain['issues']: return 'unknown'
    for pos in range(1, budget + 1):
        a = _at(chain, pos)
        if not a or a['result'] == 'unknown': return 'unknown'
        if a['result'] == 'passed': return 'passed'
    return 'failed'


def summarize(chains, budget):
    rooted = [c for c in chains if c['has_initial']]
    first = ['unknown' if c['issues'] else _at(c, 1)['result'] for c in rooted]
    recovered = []; failure_chains = 0
    for c in rooted:
        if c['issues'] or _at(c, 1)['result'] != 'failed': continue
        failure_chains += 1
        if budget > 1:
            a = _at(c, 2); recovered.append(a['result'] if a else 'unknown')
    return {'chains': len(chains), 'initial_attempts': len(rooted),
            'missing_initial': len(chains)-len(rooted),
            'invalid_chains': sum(bool(c['issues']) for c in chains),
            'first_success': ratio(first), 'first_retry_success': ratio(recovered),
            'first_failures': failure_chains,
            'within_budget_success': ratio([_cumulative(c, budget) for c in rooted]),
            'by_budget': [{'budget': k, **ratio([_cumulative(c, k) for c in rooted])} for k in range(1, budget+1)],
            'attempts': sum(len(c['attempts']) for c in chains),
            'context_counts': dict(Counter(a['context'] for c in chains for a in c['attempts'] if a['position'] > 1)),
            'reset_counts': dict(Counter(a['reset'] for c in chains for a in c['attempts'] if a['position'] > 1))}


def comparison_rows(chains, metric):
    rows = []
    for c in chains:
        if not c['has_initial']: continue
        initial = _at(c, 1)
        if metric == 'first_retry_success':
            if c['issues'] or initial['result'] != 'failed' or c['budget'] < 2: continue
            retry = _at(c, 2); result = retry['result'] if retry else 'unknown'
        elif metric == 'first_success': result = 'unknown' if c['issues'] else initial['result']
        elif metric == 'within_budget_success': result = _cumulative(c, c['budget'])
        else: raise InputError('Unknown attempt comparison metric')
        rows.append(dict(id=dumps([c['producer'],c['chain_id']]),
                         task_id=c['task_ids'][0] if len(c['task_ids']) == 1 else None, outcome=result))
    return rows


def window_comparisons(chains):
    steps = sorted({c['root_step'] for c in chains if c['root_step'] is not None})
    maximum = len(steps)//2
    if not maximum: return dict(default_width=None, windows=[])
    default = min(5, maximum)
    widths = sorted({w for w in (1,2,5,10,20,default) if w <= maximum})
    windows = []
    for width in widths:
        coordinates = dict(focus=steps[-width:], reference=steps[-2*width:-width])
        groups = {name:[c for c in chains if c['root_step'] in selected] for name,selected in coordinates.items()}
        contexts = {}
        for name, cases in groups.items():
            eligible = [c for c in cases if not c['issues'] and c['has_initial'] and _at(c,1)['result']=='failed' and c['budget']>=2]
            counts = Counter((_at(c,2)['context'],_at(c,2)['reset']) if _at(c,2) else ('retry_missing','unrecorded') for c in eligible)
            contexts[name] = [dict(context=k[0], reset=k[1], chains=n) for k,n in sorted(counts.items())]
        measures = {m: task_comparisons.compare(comparison_rows(groups['focus'],m),comparison_rows(groups['reference'],m))
                    for m in ('first_success','first_retry_success','within_budget_success')}
        distributions = {name:{(x['context'],x['reset']):x['chains'] for x in rows} for name,rows in contexts.items()}
        totals = {name:sum(d.values()) for name,d in distributions.items()}
        context_differs = None
        if all(totals.values()):
            context_differs = any(distributions['focus'].get(k,0)*totals['reference'] != distributions['reference'].get(k,0)*totals['focus']
                                  for k in set(distributions['focus'])|set(distributions['reference']))
        windows.append(dict(width=width, coordinates=coordinates,
            chain_ids={name:[[c['producer'],c['chain_id']] for c in cases] for name,cases in groups.items()},
            retry_context=contexts, retry_context_differs=context_differs, measures=measures))
    return dict(default_width=default, windows=windows,
                definition='Recent N distinct recorded initial-generation coordinates versus the immediately preceding N. Width counts observed coordinates, not elapsed time or contiguous training updates. Both sides belong to the same selected population, protocol, budget and verifier stream.')


def project(samples, reference, *, monitor=False):
    captured = [s for s in samples if 'attempt' in s]
    if not captured: return []
    streams = {}
    for s in captured:
        for r in s['records']:
            if r['kind'] == 'score' and 'attempt_outcome' in r['data']:
                key = dict(producer=r['record_producer'], component=r['data']['component'], definition=r['data']['definition'])
                streams[dumps(key)] = key
    # A declaration without a delivered result remains visible and actionable.
    if not streams: streams[dumps(None)] = None
    grouped = defaultdict(list)
    owners = defaultdict(set)
    for s in captured:
        a = s['attempt']; grouped[(a['producer'], a['chain_id'])].append(s)
        owners[(a['producer'], a['attempt_id'])].add(a['chain_id'])
    views = defaultdict(list)
    for key in streams.values():
        for (producer, chain_id), members in sorted(grouped.items()):
            identities = defaultdict(list)
            for s in members: identities[s['attempt']['attempt_id']].append(s)
            attempts = []; issues = []
            for aid, rows in sorted(identities.items()):
                a = rows[0]['attempt']
                if len(owners[(producer, aid)]) > 1: issues.append('attempt_in_multiple_chains')
                if len({dumps(s['attempt']) for s in rows}) > 1: issues.append('conflicting_attempt_declarations')
                result, reason, receipts = outcome(rows, key) if key else ('unknown', 'outcome_not_recorded', [])
                attempts.append({**a, 'result': result, 'reason': reason,
                    'samples': [reference(s) for s in rows], 'outcome_records': receipts,
                    'sources': sorted({s['run_id'] for s in rows if s.get('run_id')}),
                    'generation_steps': sorted({s['step'] for s in rows if 'step' in s}),
                    'policy_versions': sorted({s['policy_version'] for s in rows if s.get('policy_version')})})
            attempts.sort(key=lambda a: (a['position'], a['attempt_id']))
            initial = [a for a in attempts if a['position'] == 1]
            anchor = initial[0] if initial else attempts[0]
            if len({a['position'] for a in attempts}) != len(attempts): issues.append('duplicate_attempt_position')
            if len({(a['protocol'], a['budget']) for a in attempts}) > 1: issues.append('protocol_or_budget_conflict')
            if len({s['task_id'] for s in members}) > 1: issues.append('task_identity_conflict')
            if not initial: issues.append('initial_attempt_missing')
            for a in attempts:
                if a['position'] == 1: continue
                previous = [p for p in attempts if p['attempt_id'] == a['previous_attempt_id'] and p['position'] == a['position'] - 1]
                if len(previous) != 1: issues.append('predecessor_missing_or_wrong_position')
                elif previous[0]['result'] != 'failed': issues.append('failure_trigger_not_established')
            chain = {'producer': producer, 'chain_id': chain_id, 'protocol': anchor['protocol'],
                     'budget': anchor['budget'], 'task_ids': sorted({s['task_id'] for s in members}),
                     'attempts': attempts, 'issues': sorted(set(issues)), 'has_initial': len(initial) == 1,
                     'root_step': initial[0]['generation_steps'][0] if len(initial) == 1 and len(initial[0]['generation_steps']) == 1 else None,
                     'policy_versions': sorted({v for a in attempts for v in a['policy_versions']})}
            views[dumps(dict(outcome=key, protocol=anchor['protocol'], budget=anchor['budget']))].append(chain)
    result = []
    for serialized, chains in sorted(views.items()):
        context = json.loads(serialized); budget = context['budget']
        points = []
        for step in sorted({c['root_step'] for c in chains if c['root_step'] is not None}):
            subset = [c for c in chains if c['root_step'] == step]
            points.append(dict(step=step, chain_ids=[(c['producer'], c['chain_id']) for c in subset], **summarize(subset, budget)))
        behavior = []
        if monitor:
            for position in sorted({a['position'] for c in chains if not c['issues'] for a in c['attempts']}):
                ids = {dumps(s) for c in chains if not c['issues'] for a in c['attempts'] if a['position'] == position for s in a['samples']}
                rows = [s for s in samples if dumps(reference(s)) in ids]
                eligible = [s for s in rows if s.get('monitor_population') == 'included']
                behavior.append(dict(position=position, **behavior_summary(eligible, False, source_weighted=True),
                                     outside_monitor_scope=len(rows)-len(eligible),
                                     samples=[dict(reference(s), measurement=s.get('measurement')) for s in eligible]))
        value = dict(schema=VERSION, **context, **summarize(chains, budget), cases=chains, points=points,
                     window_comparisons=window_comparisons(chains),
                     behavior_by_position=behavior,
                     missing_root_step=sum(c['root_step'] is None for c in chains),
                     undeclared_samples=len(samples)-len(captured),
                     scope='One chain per initial attempt; one attempt may supply several samples. Only producer-declared failure-triggered lineage and explicit attempt outcomes are counted. Missing retries remain unresolved. Trends use the initial attempt generation coordinate. Outcome-dependent samples are not independent Pass@k trials; these rates do not establish a benefit of feedback or semantic revision.')
        result.append(dict(id='attempt-chains-'+digest(context), **value))
    return result
