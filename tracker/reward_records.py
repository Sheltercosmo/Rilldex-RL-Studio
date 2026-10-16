"""Deterministic inspection of recorded rubric feedback, outside agent context.

The generic rubric-evaluation/1 envelope is framework-independent. The CHERRL
HealthBench decoder maps its positional exported verdicts into that envelope.
No clinical judgment, evaluator call or model-behavior diagnosis is made here.
"""
from collections import defaultdict
import json
import math

from .schema import digest

VERSION = 'reward-record-inspection/3'
CONTRACT = 'rubric-evaluation/1'
DEFINITIONS = {
    'reward_record_invalid': ('Invalid reward feedback record', 'Recognized rubric or component feedback has malformed fields or contradictory recorded counts/identities. Unsupported feedback is unavailable. This diagnoses the inspection input, not the agent.'),
    'reward_verdict_coverage': ('Recorded rubric judgment coverage', 'Criteria with a valid recorded yes/no verdict / recorded rubric criteria. Unknown or missing verdicts are excluded from the numerator. Not judge accuracy.'),
    'reward_positive_attainment': ('Judge-reported positive rubric credit', 'Positive criterion weights marked met / all positive criterion weights, for complete valid verdict sets. This is recorded judge feedback, not independently verified correctness.'),
    'reward_penalty_fraction': ('Judge-reported rubric penalty load', 'Absolute negative criterion weights marked met / all positive criterion weights, for complete valid verdict sets. Can exceed one. This is a recorded penalty, not a confirmed agent failure.'),
    'reward_penalty_observed': ('Rollouts with a recorded rubric penalty', 'One if any negative-weight criterion is recorded as met; zero only if all negative criteria have valid false verdicts. Unknown negative criteria keep an otherwise negative observation unavailable.'),
    'reward_score_gap': ('Logged score minus rubric score', 'Logged score minus the unclipped signed weighted rubric score. A nonzero gap can reflect an intended reward transform; it is not automatically a scoring bug.'),
    'reward_zero_with_negative_rubric': ('Zero reward with a negative rubric score', 'One when logged reward is exactly zero while the complete signed rubric score is negative. This exposes penalty differences hidden at zero; it does not infer the producer clipping implementation or diagnose reward hacking.'),
    'reward_timeout_reported': ('Reward evaluation timeout reported', 'Explicit boolean timeout in the recorded evaluation feedback. Missing or malformed flags are unavailable; this is not inferred from output length.'),
    'reward_error_reported': ('Reward evaluation error reported', 'Whether the recorded evaluation error string is nonempty. Missing or malformed fields are unavailable; not an agent behavior classification.'),
}
INDICATORS = {'reward_record_invalid', 'reward_penalty_observed', 'reward_zero_with_negative_rubric', 'reward_timeout_reported', 'reward_error_reported'}
from . import evaluation_components
DEFINITIONS.update(evaluation_components.DEFINITIONS)
INDICATORS.update(evaluation_components.INDICATORS)
LIMITS = ('Recorded evaluator feedback only. Rubrics and verdicts are not agent-visible trace evidence, '
          'independent correctness labels or confirmed reward hacking. The signed rubric calculation '
          'does not assume the producer used that formula without clipping or other reward transforms.')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def inspect(run, *, include_criteria=True):
    if evaluation_components.matches(run):
        return evaluation_components.inspect(run, include_criteria=include_criteria)
    raw = run.get('raw', {}); issues = []; rows = []; refs = []
    result = {'schema': VERSION, 'run_id': run['id'], 'source_hash': digest(run),
              'available': False, 'protocol': None, 'status': 'unavailable', 'issues': issues,
              'criteria': rows, 'categories': [], 'metrics': {}, 'limits': LIMITS}
    metrics = result['metrics']
    def metric(name, value=None, *, numerator=None, denominator=None, evidence=(), reason=None):
        if denominator is not None:
            value = numerator / denominator if denominator else None
            if not denominator: reason = reason or 'No eligible denominator'
        metrics[name] = {'value': value, 'numerator': numerator, 'denominator': denominator,
                         'evidence': list(evidence), 'reason': reason}
    for name in DEFINITIONS: metric(name, reason='No recognized recorded evaluator feedback')
    def problem(code, pointer, note):
        issues.append({'code': code, 'pointer': pointer, 'note': note})
    def decode(value, pointer):
        if isinstance(value, str):
            try: return json.loads(value)
            except (ValueError, TypeError): problem('invalid_json', pointer, 'Recorded JSON cannot be parsed.'); return None
        return value
    native = raw.get('reward_evaluation')
    if native is not None:
        if not isinstance(native, dict) or native.get('schema') != CONTRACT:
            result['reason'] = 'Unsupported reward_evaluation schema'; return result
        result.update(available=True, protocol=VERSION + '/' + CONTRACT)
        criteria = native.get('criteria'); verdicts = native.get('verdicts')
        cp, vp = '/reward_evaluation/criteria', '/reward_evaluation/verdicts'
        summary = native.get('reported_counts', {})
        count_fields = {'criteria': ('criteria', '/reward_evaluation/reported_counts/criteria'),
                        'verdicts': ('verdicts', '/reward_evaluation/reported_counts/verdicts'),
                        'met': ('met', '/reward_evaluation/reported_counts/met')}
        status = native; status_root = '/reward_evaluation/'
        score, score_ref = native.get('score'), '/reward_evaluation/score'
    elif any(k in raw for k in ('healthbench_rubric_items', 'healthbench_verdict_vector', 'healthbench_rubric_count')):
        result.update(available=True, protocol=VERSION + '/cherrl-healthbench-export/1')
        cp, vp = '/healthbench_rubric_items', '/healthbench_verdict_vector'
        items = decode(raw.get('healthbench_rubric_items'), cp)
        vector = decode(raw.get('healthbench_verdict_vector'), vp)
        criteria = [dict(id=str(i+1), weight=item.get('points'), description=item.get('criterion'),
                         category=item.get('tags', {}).get('axis') if isinstance(item.get('tags'), dict) else None)
                    if isinstance(item, dict) else item for i, item in enumerate(items)] if isinstance(items, list) else items
        verdicts = [{'criterion_id': str(i+1), 'met': v} for i, v in enumerate(vector)] if isinstance(vector, list) else vector
        # A short positional array cannot identify omitted positions reliably.
        if isinstance(criteria, list) and isinstance(verdicts, list) and len(criteria) != len(verdicts):
            problem('positional_length_mismatch', vp, 'A positional verdict vector must cover every rubric position; no padding or guessed alignment is applied.')
        summary = raw
        count_fields = {'criteria': ('healthbench_rubric_count', '/healthbench_rubric_count'),
                        'verdicts': ('healthbench_verdict_count', '/healthbench_verdict_count'),
                        'met': ('healthbench_met_count', '/healthbench_met_count')}
        status = raw; status_root = '/'
        score, score_ref = raw.get('score'), '/score'
    else:
        result['reason'] = 'No recognized recorded evaluator feedback'; return result
    refs = [cp, vp]
    for name in DEFINITIONS: metric(name, reason='Recorded rubric feedback is incomplete or invalid')
    if not isinstance(criteria, list): problem('invalid_criteria', cp, 'Expected an array of criteria.'); criteria = []
    if not isinstance(verdicts, list): problem('invalid_verdicts', vp, 'Expected an array of verdicts.'); verdicts = []
    by_id = {}; judgments = {}
    for i, item in enumerate(criteria):
        pointer = cp + '#' + str(i)
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
                or not finite(item.get('weight')) or not isinstance(item.get('description'), str)):
            problem('invalid_criterion', pointer, 'A criterion needs a unique string ID, description and finite numeric weight.'); continue
        if item['id'] in by_id: problem('duplicate_criterion_id', pointer, 'Criterion identity is duplicated.'); continue
        by_id[item['id']] = {**item, 'source_reference': pointer, 'met': None, 'verdict_reference': None}
    for i, verdict in enumerate(verdicts):
        pointer = vp + '#' + str(i)
        if not isinstance(verdict, dict) or not isinstance(verdict.get('criterion_id'), str):
            problem('invalid_verdict', pointer, 'A verdict needs a criterion ID.'); continue
        identity = verdict['criterion_id']; met = verdict.get('met')
        if identity not in by_id: problem('unknown_criterion_id', pointer, 'Verdict names a criterion absent from the rubric.'); continue
        if identity in judgments: problem('duplicate_verdict', pointer, 'More than one verdict names this criterion.'); continue
        if met is not None and not (type(met) is bool or type(met) is int and met in (0, 1)):
            problem('invalid_verdict_value', pointer, 'Met must be boolean, 0/1 or explicit null for unknown.'); continue
        judgments[identity] = None if met is None else bool(met)
        by_id[identity].update(met=judgments[identity], verdict_reference=pointer)
    if not isinstance(summary, dict): problem('invalid_counts', status_root + 'reported_counts', 'Expected a counts object.'); summary = {}
    actual = {'criteria': len(criteria), 'verdicts': len(verdicts), 'met': sum(v is True for v in judgments.values())}
    for field, (key, pointer) in count_fields.items():
        if key not in summary: continue
        value = summary[key]
        if type(value) is not int or value < 0 or value != actual[field]:
            problem('count_mismatch', pointer, 'Reported count differs from the recorded arrays or has an invalid type.')
        refs.append(pointer)
    for name, field in (('reward_timeout_reported', 'timeout'), ('reward_error_reported', 'error')):
        value = status.get(field); pointer = status_root + field
        valid = type(value) is bool if field == 'timeout' else isinstance(value, str)
        if valid: metric(name, int(value) if field == 'timeout' else int(bool(value.strip())), evidence=[pointer])
        else: metric(name, reason='No explicit valid evaluation ' + field + ' field')
    rows.extend(by_id.values())
    complete = len(judgments) == len(rows) and all(r['met'] is not None for r in rows)
    weights = [r['weight'] for r in rows]
    if weights and not finite(sum(abs(w) for w in weights)):
        problem('nonfinite_weight_total', cp, 'Criterion weights overflow a finite total.')
    result['status'] = 'invalid' if issues else 'complete' if complete and rows else 'partial'
    result['counts'] = {'criteria': len(rows), 'known_verdicts': sum(r['met'] is not None for r in rows),
                        'met': sum(r['met'] is True for r in rows), 'unknown_verdicts': sum(r['met'] is None for r in rows)}
    metric('reward_record_invalid', int(bool(issues)), evidence=refs)
    result['logged_score'] = score if finite(score) else None; result['logged_score_reference'] = score_ref
    if not issues:
        metric('reward_verdict_coverage', numerator=result['counts']['known_verdicts'], denominator=len(rows), evidence=refs)
        penalties = [r for r in rows if r['weight'] < 0]
        positive_penalty = any(r['met'] is True for r in penalties)
        penalty_decidable = positive_penalty or bool(rows) and all(r['met'] is not None for r in penalties)
        metric('reward_penalty_observed', int(positive_penalty) if penalty_decidable else None, evidence=refs,
               reason=None if penalty_decidable else 'Negative criteria have unknown verdicts or no rubric is recorded')
        def components(items):
            denominator = sum(r['weight'] for r in items if r['weight'] > 0)
            positive = sum(r['weight'] for r in items if r['weight'] > 0 and r['met'] is True)
            penalty = sum(-r['weight'] for r in items if r['weight'] < 0 and r['met'] is True)
            known = bool(items) and all(r['met'] is not None for r in items)
            return {'positive_weight': denominator, 'positive_met_weight': positive if known else None,
                    'penalty_met_weight': penalty if known else None, 'complete': known,
                    'rubric_score': (positive-penalty)/denominator if denominator and known else None}
        calculation = components(rows); result['calculation'] = calculation
        if complete and calculation['positive_weight']:
            for name, numerator in (('reward_positive_attainment', calculation['positive_met_weight']), ('reward_penalty_fraction', calculation['penalty_met_weight'])):
                metric(name, numerator=numerator, denominator=calculation['positive_weight'], evidence=refs)
            if finite(score):
                metric('reward_score_gap', score-calculation['rubric_score'], evidence=[score_ref, *refs])
                metric('reward_zero_with_negative_rubric', int(score == 0 and calculation['rubric_score'] < 0), evidence=[score_ref, *refs])
        grouped = defaultdict(list)
        for row in rows:
            category = row.get('category'); grouped[category if isinstance(category, str) and category else 'Uncategorized'].append(row)
        result['categories'] = [{'category': category, 'criteria': len(items), **components(items)} for category, items in sorted(grouped.items())]
    if include_criteria:
        result['source_fields'] = ({'/reward_evaluation': native} if native is not None else
            {'/' + k: raw[k] for k in ('healthbench_rubric_items', 'healthbench_verdict_vector',
                'healthbench_rubric_count', 'healthbench_verdict_count', 'healthbench_met_count',
                'timeout', 'error', 'score', 'genrm_response') if k in raw})
    else: result['criteria'] = []
    return result
