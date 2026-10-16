"""Framework-neutral, position-aligned value observations at training use.

Targets are the producer's return estimates, never independent ground truth.
The declared role separates a policy baseline from a value-loss input. Masks
belong to this observation and are not borrowed from the actor's loss mask.
"""
import math

from .schema import InputError, digest
from . import training_recipes

VERSION = 'value-observation/1'
MAX_POSITIONS = 131072
KEYS = ('component', 'definition', 'unit', 'role', 'target_kind', 'value_model')


def validate(value):
    training_recipes.fields(value, {'schema', *KEYS, 'value_version', 'input_digest',
                                   'positions', 'mask', 'values', 'returns'})
    if value['schema'] != VERSION:
        raise InputError('Use value-observation/1')
    for key in (*KEYS, 'value_version', 'input_digest'):
        training_recipes.text(value[key], key)
    if value['unit'] not in {'token', 'turn', 'state'}:
        raise InputError('Value positions must use token, turn or state units')
    if value['role'] not in {'advantage_baseline', 'value_fit'}:
        raise InputError('Declare advantage_baseline or value_fit')
    if value['target_kind'] not in {'lambda_return', 'discounted_return', 'monte_carlo_return', 'custom'}:
        raise InputError('Declare the native return target kind')
    positions = value['positions']
    if (not isinstance(positions, list) or not 1 <= len(positions) <= MAX_POSITIONS
            or any(type(p) is not int or not 0 <= p < 2**63 for p in positions)
            or any(b <= a for a, b in zip(positions, positions[1:]))):
        raise InputError('Supply 1–131072 increasing native position indexes')
    mask = value['mask']
    if (not isinstance(mask, list) or len(mask) != len(positions)
            or any(type(m) is not int or m not in {0, 1} for m in mask)):
        raise InputError('Value mask must be binary and position-aligned')
    for key in ('values', 'returns'):
        xs = value[key]
        if (not isinstance(xs, list) or len(xs) != len(positions)
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in xs)):
            raise InputError(key + ' must be finite and position-aligned')
    return value


def observation(*, component, definition, unit, role, target_kind, value_model,
                value_version, input_digest, positions, mask, values, returns):
    """Build from detached native arrays. Does not compute GAE or run a model."""
    return validate(dict(schema=VERSION, component=component, definition=definition,
        unit=unit, role=role, target_kind=target_kind, value_model=value_model,
        value_version=value_version, input_digest=input_digest,
        positions=list(positions), mask=list(mask), values=list(values), returns=list(returns)))


def bound(value, context):
    # A component binds the learning context, not a claim that its actor loss
    # trained the value head. Role and producer/stage stay explicit downstream.
    return any(c['id'] == value['component'] and c['credit']['kind'] == 'critic'
               for c in (context.get('manifest') or {}).get('components', []))


def mean(xs):
    if not xs:
        return None
    try:
        value = math.fsum(x / len(xs) for x in xs)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def variance(xs):
    avg = mean(xs)
    return mean([(x - avg) * (x - avg) for x in xs]) if avg is not None else None


def finite(value):
    return value if math.isfinite(value) else None


def summarize(receipts, context, *, split=True):
    observed = [r['data']['value_observation'] for r in receipts if 'value_observation' in r['data']]
    valid = [v for v in observed if bound(v, context)]
    definitions = sorted({tuple(v[k] for k in KEYS) for v in valid})
    compatible = len(definitions) <= 1
    rows = valid if compatible else []
    groups = [[(v, t) for v, t, m in zip(r['values'], r['returns'], r['mask']) if m] for r in rows]
    result = {'schema': VERSION, 'observed_uses': len(observed), 'missing_uses': len(receipts) - len(observed),
        'unbound_uses': len(observed) - len(valid), 'compatible_definitions': compatible,
        'definitions': [dict(zip(KEYS, key)) for key in definitions],
        'eligible_uses': sum(bool(g) for g in groups), 'masked_out_uses': sum(not g for g in groups),
        **paired_moments(groups), 'recorded_positions': sum(len(r['positions']) for r in rows),
        'interpretation': 'Each eligible native position counts once per recorded use in this stage. '
            'Repeated uses count again. Explained variance is 1 − Var(return − value) / Var(return), '
            'with population variances and no stabilizing epsilon; constant returns are undefined. '
            'MSE and signed bias expose errors that variance alone misses. Within-sample variation is '
            'within-use value variance divided by pooled value variance. These are descriptive checks '
            'against recorded return targets, not true state-value accuracy, total trainer loss, '
            'proof of value flattening or causal policy credit.'}
    if split:
        result['series'] = []
        for key in definitions:
            selected = [r for r in receipts if 'value_observation' in r['data']
                        and tuple(r['data']['value_observation'][k] for k in KEYS) == key]
            result['series'].append({'id': 'values-' + digest(key),
                **summarize(selected, context, split=False)})
    return result


def paired_moments(groups):
    """Position-weighted moments for aligned, already selected value/target pairs."""
    values = [v for g in groups for v, _ in g]
    targets = [t for g in groups for _, t in g]
    errors = [v - t for v, t in zip(values, targets)]
    target_var, error_var, value_var = variance(targets), variance(errors), variance(values)
    mse, bias = mean([e * e for e in errors]), mean(errors)
    ev = finite(1 - error_var / target_var) if target_var and error_var is not None else None
    within = []
    for group in groups:
        center = mean([v for v, _ in group])
        if center is not None:
            within.extend((v - center) * (v - center) for v, _ in group)
    within_var = mean(within)
    fraction = finite(within_var / value_var) if value_var and within_var is not None else None
    return {
        'eligible_positions': len(values), 
        'mean_value': mean(values), 'mean_return': mean(targets),
        'mean_squared_error': mse, 'mean_error': bias,
        'return_variance': target_var, 'value_variance': value_var, 'error_variance': error_var,
        'explained_variance': ev, 'within_sample_value_variance': within_var,
        'within_sample_variation_fraction': fraction,
        'explained_variance_status': ('available' if ev is not None else 'no_eligible_positions' if not values
            else 'constant_returns' if target_var == 0 else 'numeric_range'),
        'variation_status': ('available' if fraction is not None else 'no_eligible_positions' if not values
            else 'constant_values' if value_var == 0 else 'numeric_range')}
