"""Observed loss derivatives at target log probabilities, never causal credit."""
import math
from .schema import InputError
from . import training_recipes

VERSION = 'policy-gradient-observation/1'
MAX_TOKENS = 131072


def validate(value):
    training_recipes.fields(value, {'schema', 'component', 'definition', 'tokenizer_id',
        'input_digest', 'probability_basis', 'normalization', 'target_tokens', 'loss_mask', 'd_loss_d_logp'}, {'normalization_context', 'source_alignment'})
    if value['schema'] != VERSION: raise InputError('Use policy-gradient-observation/1')
    for key in ('component', 'definition', 'tokenizer_id', 'input_digest', 'probability_basis', 'normalization'):
        training_recipes.text(value[key], key)
    context = value.get('normalization_context', {})
    if not isinstance(context, dict) or len(context) > 24: raise InputError('Bound normalization context to 24 fields')
    for k,v in context.items():
        training_recipes.text(k, 'normalization field')
        if isinstance(v, str): training_recipes.text(v, 'normalization value')
        elif type(v) not in {int,float} or not math.isfinite(v): raise InputError('Normalization values must be text or finite numbers')
    ids = value['target_tokens']
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_TOKENS or any(type(t) is not int or t < 0 for t in ids):
        raise InputError('Policy gradient needs 1–131072 nonnegative target token IDs')
    mask, gradient = value['loss_mask'], value['d_loss_d_logp']
    if not isinstance(mask, list) or len(mask) != len(ids) or any(type(m) is not int or m not in {0, 1} for m in mask):
        raise InputError('Policy gradient mask must be binary and target-aligned')
    if not isinstance(gradient, list) or len(gradient) != len(ids) or any(type(g) not in {int, float} or not math.isfinite(g) for g in gradient):
        raise InputError('Policy gradient must be finite and target-aligned')
    if 'source_alignment' in value:
        from .training_spans import validate as validate_source
        validate_source(value['source_alignment'], len(ids))
    return value


def ratio(n, d):
    return {'value':n/d if d and n is not None else None, 'numerator':n, 'denominator':d}


def binding(signal, recipe_context):
    manifest = recipe_context['manifest']
    if not manifest: return recipe_context['status']
    component = next((c for c in manifest['components'] if c['id'] == signal['component']), None)
    if component is None: return 'component_missing'
    return 'bound'


def summarize(receipts, recipe_context):
    observed = [r for r in receipts if 'policy_gradient' in r['data']]
    valid = [r for r in observed if binding(r['data']['policy_gradient'], recipe_context) == 'bound']
    keys = {(s['definition'], s['probability_basis'], s['normalization'], s['component'], s['tokenizer_id'])
            for r in valid for s in [r['data']['policy_gradient']]}
    # Same recipe can still carry different boundaries/normalizations. Refuse a
    # pooled curve unless the observation definitions agree; raw cases survive.
    compatible = len(keys) <= 1
    rows = valid if compatible else []
    gradients = [g for r in rows for g, m in zip(r['data']['policy_gradient']['d_loss_d_logp'], r['data']['policy_gradient']['loss_mask']) if m]
    nonzero_credit = [g for r in rows if r['data'].get('advantage', 0) != 0
                     for g, m in zip(r['data']['policy_gradient']['d_loss_d_logp'], r['data']['policy_gradient']['loss_mask']) if m]
    try: absolute_sum = math.fsum(abs(g) for g in gradients)
    except OverflowError: absolute_sum = None
    return {'observed_uses':len(observed), 'missing_uses':len(receipts)-len(observed),
        'unbound_uses':len(observed)-len(valid), 'compatible_definitions':compatible,
        'definitions':[{'definition':k[0], 'probability_basis':k[1], 'normalization':k[2], 'component':k[3], 'tokenizer_id':k[4]} for k in sorted(keys)],
        'eligible_tokens':len(gradients),
        'zero_gradient':ratio(sum(g == 0 for g in gradients), len(gradients)),
        'zero_gradient_nonzero_advantage':ratio(sum(g == 0 for g in nonzero_credit), len(nonzero_credit)),
        'mean_absolute_gradient':ratio(absolute_sum, len(gradients)), 'magnitude_overflow':absolute_sum is None,
        'negative_gradient':ratio(sum(g < 0 for g in gradients), len(gradients)),
        'off_mask_nonzero':sum(g != 0 and not m for r in rows for g,m in zip(r['data']['policy_gradient']['d_loss_d_logp'],r['data']['policy_gradient']['loss_mask'])),
        'interpretation':'Derivative of the declared loss at target log probabilities, including native reduction/backward scaling. Exact zeros use no threshold. This is not parameter-gradient magnitude, optimizer change, causal behavior credit or proof that clipping caused a zero.'}


def sample_state(record, recipe_context):
    s = record['data'].get('policy_gradient')
    if s is None or binding(s, recipe_context) != 'bound': return 'unavailable'
    gradients = [g for g,m in zip(s['d_loss_d_logp'],s['loss_mask']) if m]
    if not gradients: return 'masked_out'
    return 'zero' if all(g == 0 for g in gradients) else 'nonzero'
