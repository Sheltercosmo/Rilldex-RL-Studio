"""Recorded reward components and diagnostic-only checks, never agent activities.

Native tau-bench feedback and an explicit portable component-evaluation/1
contract share this projection. No rubric weights or task success are inferred.
"""
import math
from .schema import digest, dumps

VERSION = 'evaluation-components/1'
CONTRACT = 'component-evaluation/1'
DEFINITIONS = {
    'reward_component_coverage': ('Reward component coverage', 'Finite recorded scores / explicitly declared reward components. Missing component scores remain unknown.'),
    'reward_component_zero_observed': ('Zero-valued reward component', 'One if a declared reward component is recorded as zero; zero only when every declared component has a finite nonzero score. Not a universal task-failure judgment.'),
    'reward_diagnostic_failure_observed': ('Unmet checks outside the reward', 'One if a recorded diagnostic-only check is not met; zero only if all such checks are recorded as met. No diagnostic checks or unknown verdicts leave this unavailable. Does not diagnose reward hacking.'),
    'reward_aggregation_gap': ('Logged reward minus component aggregate', 'Logged reward minus the explicitly declared product or sum of complete recorded reward components. Unsupported transforms and incomplete scores remain unavailable.'),
}
INDICATORS = {'reward_component_zero_observed', 'reward_diagnostic_failure_observed'}
LIMITS = ('Recorded evaluator evidence, outside agent-visible context. A tool returning without error, '
          'an evaluator passing, and a task being solved are separate claims. Diagnostic-only checks '
          'do not contribute to the declared reward. Reference action sequences are not prescribed '
          'agent plans unless the reward contract explicitly requires action matching.')


def finite(x):return type(x) in (int, float) and math.isfinite(x)
def named(x):return isinstance(x, str) and bool(x.strip())
def pointer(x):return x.replace('~', '~0').replace('/', '~1')


def matches(run):
    raw = run.get('raw', {})
    explicit = raw.get('reward_evaluation')
    simulation = raw.get('simulation', raw)
    return (isinstance(explicit, dict) and explicit.get('schema') == CONTRACT or
            run.get('adapter') == 'tau-bench' and isinstance(simulation, dict) and simulation.get('reward_info') is not None)


def _tau(run):
    raw = run['raw']; native = raw.get('simulation', raw).get('reward_info')
    base = '/simulation/reward_info' if 'simulation' in raw else '/reward_info'
    native = native if isinstance(native, dict) else {}
    basis = native.get('reward_basis'); breakdown = native.get('reward_breakdown')
    components = []; checks = []
    if isinstance(basis, list) and all(named(n) for n in basis) and isinstance(breakdown, dict):
        names = list(basis) + [k for k in breakdown if k not in basis]
        for name in names:
            components.append({'id': name, 'value': breakdown.get(name),
                'role': 'reward' if name in basis else 'diagnostic',
                'source_reference': base + '/reward_breakdown/' + pointer(name) if name in breakdown else base + '/reward_basis',
                'role_reference': base + '/reward_basis'})
    db = native.get('db_check')
    if isinstance(db, dict):
        checks.append({'id': 'DB', 'component': 'DB', 'met': db.get('db_match'),
                       'description': 'Final database state matches the evaluator target',
                       'source_reference': base + '/db_check/db_match'})
    fields = [('env_assertions', 'ENV_ASSERTION', 'met', 'env_assertion'),
              ('communicate_checks', 'COMMUNICATE', 'met', 'info'),
              ('nl_assertions', 'NL_ASSERTION', 'met', 'nl_assertion'),
              ('action_checks', 'ACTION', 'action_match', 'action')]
    invalid_arrays = []
    for field, component, verdict, description in fields:
        values = native.get(field)
        if values is None:continue
        if not isinstance(values, list):
            invalid_arrays.append(base + '/' + field);continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                invalid_arrays.append(base + '/' + field + '/' + str(index));continue
            text = item.get(description)
            checks.append({'id': field + '/' + str(index), 'component': component, 'met': item.get(verdict),
                'description': text if isinstance(text, str) else dumps(text),
                'source_reference': base + '/' + field + '/' + str(index) + '/' + verdict})
    # A diagnostic check can exist without a numeric diagnostic component score.
    for check in checks:
        component = check['component']
        if not any(c['id'] == component for c in components):
            components.append({'id': component, 'value': None,
                'role': 'reward' if isinstance(basis, list) and component in basis else 'diagnostic',
                'source_reference': check['source_reference'], 'role_reference': base + '/reward_basis'})
    return {'definition': run['metadata'].get('reward_definition', 'tau-bench evaluator version unrecorded'),
            'aggregation': 'product', 'score': native.get('reward'), 'components': components, 'checks': checks}, {
            'base': base, 'basis_valid': isinstance(basis, list) and len(set(map(str, basis))) == len(basis) and all(named(k) for k in basis),
            'breakdown_valid': isinstance(breakdown, dict), 'invalid_arrays': invalid_arrays, 'native': native}


def inspect(run, *, include_criteria=True):
    raw = run['raw']; explicit = raw.get('reward_evaluation')
    native = not (isinstance(explicit, dict) and explicit.get('schema') == CONTRACT)
    if native:
        doc, origin = _tau(run); base = origin['base']
    else:
        doc, origin, base = explicit, None, '/reward_evaluation'
    result = {'schema': VERSION, 'format': CONTRACT, 'run_id': run['id'], 'source_hash': digest(run),
        'available': True, 'protocol': VERSION + ('/tau-bench' if native else '/portable'),
        'definition': doc.get('definition'), 'aggregation': doc.get('aggregation'),
        'logged_score': doc.get('score') if finite(doc.get('score')) else None,
        'components': [], 'criteria': [], 'categories': [], 'issues': [], 'metrics': {}, 'limits': LIMITS}
    def issue(code, ref, note):result['issues'].append({'code': code, 'pointer': ref, 'note': note})
    def metric(key, value=None, numerator=None, denominator=None, evidence=(), reason=None):
        if denominator is not None:
            value = numerator / denominator if denominator else None
        result['metrics'][key] = {'value': value, 'numerator': numerator, 'denominator': denominator,
                                  'evidence': list(evidence), 'reason': reason if value is None else None}
    for key in DEFINITIONS:metric(key, reason='Incomplete or invalid component evaluation record')
    if native:
        if not origin['basis_valid']:issue('invalid_reward_basis', base + '/reward_basis', 'Reward membership must be explicitly recorded as unique nonempty component names.')
        if not origin['breakdown_valid']:issue('missing_reward_breakdown', base + '/reward_breakdown', 'Component scores are not recorded as a mapping.')
        for ref in origin['invalid_arrays']:issue('invalid_check', ref, 'Expected an array of recorded check objects.')
    elif not named(doc.get('definition')):
        issue('missing_definition', base + '/definition', 'Name and version the recorded evaluator definition.')
    components = doc.get('components'); checks = doc.get('checks', [])
    if not isinstance(components, list):
        issue('invalid_components', base + '/components', 'Components must be an array.'); components = []
    if not isinstance(checks, list):
        issue('invalid_checks', base + '/checks', 'Checks must be an array.'); checks = []
    by_id = {}
    for index, component in enumerate(components):
        ref = base + '/components/' + str(index)
        if not isinstance(component, dict) or not named(component.get('id')) or component.get('role') not in ('reward', 'diagnostic'):
            issue('invalid_component', ref, 'Each component needs an ID and explicit reward or diagnostic role.'); continue
        identity = component['id']; value = component.get('value')
        if identity in by_id:
            issue('duplicate_component', ref, 'Component identity must be unique.'); continue
        if value is not None and not finite(value):issue('invalid_score', component['source_reference'] if native else ref + '/value', 'Score must be finite numeric or null.')
        row = {'id': identity, 'role': component['role'], 'value': value if finite(value) else None,
               'source_reference': component['source_reference'] if native else ref + '/value',
               'role_reference': component['role_reference'] if native else ref + '/role'}
        by_id[identity] = row; result['components'].append(row)
    seen = set()
    for index, check in enumerate(checks):
        ref = base + '/checks/' + str(index)
        if not isinstance(check, dict) or not named(check.get('id')) or not named(check.get('component')) or check['component'] not in by_id or not isinstance(check.get('description'), str):
            issue('invalid_check', ref, 'Check needs a unique ID, description and existing component.'); continue
        if check['id'] in seen:
            issue('duplicate_check', ref, 'Check identity must be unique.'); continue
        seen.add(check['id']); met = check.get('met')
        if met is not None and type(met) is not bool:issue('invalid_verdict', check['source_reference'] if native else ref + '/met', 'Check verdict must be boolean or null.')
        result['criteria'].append({'id': check['id'], 'component': check['component'],
            'role': by_id[check['component']]['role'], 'met': met if type(met) is bool else None,
            'description': check['description'], 'source_reference': check['source_reference'] if native else ref + '/met'})
    score_ref = base + ('/reward' if native else '/score')
    if doc.get('score') is not None and not finite(doc['score']):issue('invalid_logged_score', score_ref, 'Logged score must be finite numeric or null.')
    selected = [r for r in result['components'] if r['role'] == 'reward']
    known = [r for r in selected if r['value'] is not None]
    diagnostics = [r for r in result['criteria'] if r['role'] == 'diagnostic']
    result['counts'] = {'reward_components': len(selected), 'known_components': len(known),
                         'diagnostic_checks': len(diagnostics), 'unmet_diagnostic_checks': sum(r['met'] is False for r in diagnostics)}
    if not result['issues']:
        metric('reward_component_coverage', numerator=len(known), denominator=len(selected), evidence=[r['source_reference'] for r in known], reason='No declared reward components')
        zeros = [r for r in known if r['value'] == 0]
        metric('reward_component_zero_observed', int(bool(zeros)) if zeros or selected and len(known) == len(selected) else None,
               evidence=[r['source_reference'] for r in zeros or known], reason='Reward component scores are incomplete or absent')
        failed = [r for r in diagnostics if r['met'] is False]
        metric('reward_diagnostic_failure_observed', int(bool(failed)) if failed or diagnostics and all(r['met'] is not None for r in diagnostics) else None,
               evidence=[r['source_reference'] for r in failed or diagnostics], reason='No complete diagnostic-only check set')
        if selected and len(known) == len(selected) and doc.get('aggregation') in ('product', 'sum'):
            try:
                aggregate = math.prod(r['value'] for r in selected) if doc['aggregation'] == 'product' else math.fsum(r['value'] for r in selected)
                if not finite(aggregate):raise OverflowError
            except (OverflowError, ValueError):issue('aggregate_overflow', base, 'Recorded component aggregation is not finite.')
            else:
                result['aggregate'] = aggregate
                if finite(doc.get('score')):
                    gap = doc['score'] - aggregate
                    if finite(gap):metric('reward_aggregation_gap', gap, evidence=[score_ref] + [r['source_reference'] for r in selected])
                    else:issue('aggregate_overflow', base, 'Score difference is not finite.')
    result['status'] = 'invalid' if result['issues'] else 'complete' if selected and len(known) == len(selected) else 'partial'
    if result['issues']:
        for key in DEFINITIONS:metric(key, reason='Invalid component evaluation record')
    metric('reward_record_invalid', int(bool(result['issues'])), evidence=[r['pointer'] for r in result['issues']])
    if include_criteria:result['source_fields'] = {base: origin['native'] if native else explicit}
    else:result['criteria'] = []
    return result
