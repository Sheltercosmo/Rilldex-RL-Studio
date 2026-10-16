"""Sample-level native predictions and targets at a confirmed training use."""
import math
from .schema import InputError
from . import training_recipes

VERSION = 'sample-regression/1'


def validate(value):
    training_recipes.fields(value, {'schema','component','definition','prediction','target'},
                            {'baseline','reward'})
    if value['schema'] != VERSION: raise InputError('Use sample-regression/1')
    for key in ('component','definition'): training_recipes.text(value[key],key)
    if ('baseline' in value) != ('reward' in value): raise InputError('Supply baseline and reward together')
    for key in ('prediction','target','baseline','reward'):
        if key in value and (type(value[key]) not in (int,float) or not math.isfinite(value[key])):
            raise InputError('Regression '+key+' must be finite')
    return value


def bound(value, context):
    return any(c['id'] == value['component'] and c['objective']['weighting'] == 'regression'
               for c in (context.get('manifest') or {}).get('components', []))


def summarize(receipts, context):
    observed = [r['data']['regression'] for r in receipts if 'regression' in r['data']]
    valid = [v for v in observed if bound(v, context)]
    definitions = sorted({(v['component'],v['definition']) for v in valid})
    compatible = len(definitions) <= 1
    values = valid if compatible else []
    residuals = [v['prediction']-v['target'] for v in values]
    def mean(xs):
        if not xs: return None
        try: value = math.fsum(x/len(xs) for x in xs)
        except (OverflowError,ValueError): return None
        return value if math.isfinite(value) else None
    baseline = [v for v in values if 'baseline' in v]
    return {'observed_uses':len(observed),'missing_uses':len(receipts)-len(observed),
        'unbound_uses':len(observed)-len(valid),'compatible_definitions':compatible,'eligible_uses':len(values),
        'definitions':[{'component':c,'definition':d} for c,d in definitions],
        'mean_squared_error':mean([r*r for r in residuals]),'mean_error':mean(residuals),
        'mean_prediction':mean([v['prediction'] for v in values]),'mean_target':mean([v['target'] for v in values]),
        'baseline_uses':len(baseline),'mean_baseline':mean([v['baseline'] for v in baseline]),
        'mean_reward':mean([v['reward'] for v in baseline]),
        'interpretation':'Each confirmed sample use counts once within its stage and definition. Squared prediction error is an observation, not the scaled total trainer loss, critic accuracy, PPO clipping or causal behavior credit. Baselines stay separate from live prompt-group means.'}
