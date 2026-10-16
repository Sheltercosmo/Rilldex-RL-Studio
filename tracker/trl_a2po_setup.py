"""Pinned A*-PO settings: cached baseline and sequence regression are separate."""
import math
from .schema import InputError, digest

PIN = '1.13.0'
VERSION = 'trl-a2po-setup/1'
FIELDS = ('num_value_samples', 'beta1', 'beta2', 'filter_all_incorrect', 'reward_weights',
          'max_prompt_length', 'max_completion_length', 'temperature', 'top_p', 'top_k')
SOURCE = 'https://github.com/huggingface/trl/blob/v1.13.0/trl/experimental/a2po/a2po_trainer.py'


def inspect(request):
    from .training_setup import at, MISSING, monitor
    from .training_monitoring import recommend
    cfg = request.get('config')
    if not isinstance(cfg, dict): raise InputError('A*-PO needs a resolved config mapping')
    revision = request.get('version', '')
    if not isinstance(revision, str) or len(revision) > 100: raise InputError('version must be a short string')
    if type(request.get('resolved', False)) is not bool: raise InputError('resolved must be true or false')
    s = {}; issues = []
    def issue(code, text): issues.append({'code':code, 'message':text})
    for key in FIELDS:
        value = at(cfg, key)
        if value is MISSING: continue
        if key == 'reward_weights' and isinstance(value, (list, tuple)):
            if not 1 <= len(value) <= 32 or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):
                raise InputError('reward_weights must be a bounded finite numeric list')
            value = list(value)
        elif value is not None and (type(value) not in (str,int,float,bool) or
                isinstance(value,str) and len(value)>200 or type(value) in (int,float) and not math.isfinite(value)):
            raise InputError('Invalid A*-PO setting: '+key)
        s[key] = value
    for key in ('num_value_samples', 'beta1', 'beta2', 'filter_all_incorrect'):
        if key not in s: issue('missing', 'Setting not recorded: '+key)
    for key in ('beta1','beta2','temperature'):
        if key in s and (type(s[key]) not in (int,float) or s[key] <= 0): issue('invalid_type', key+' must be positive')
    if 'num_value_samples' in s and (type(s['num_value_samples']) is not int or s['num_value_samples']<1): issue('invalid_type','num_value_samples must be a positive integer')
    if 'filter_all_incorrect' in s and type(s['filter_all_incorrect']) is not bool: issue('invalid_type','filter_all_incorrect must be boolean')
    if revision != PIN: issue('version','A*-PO settings are checked against TRL '+PIN+'; this version is unverified.')
    if not request.get('resolved'): issue('unresolved','Export effective A*-PO settings after defaults and overrides are resolved.')
    label = 'A*-PO · advantage regression'
    profile = {'credit':'cached_baseline','credit_unit':'sample','ratio_unit':'sequence','weighting':'regression',
               'reduction':'mean squared sequence regression residual','estimator':'Cached reference-policy reward baseline',
               'scheduling':'synchronous'}
    checks = [
        monitor('reward','Reward and task outcomes','Compare scored outcomes under consistent reward definitions.','available_with_records','Scores and generation coordinates'),
        monitor('use','Samples used for training','Baseline-estimation samples are separate from on-policy training samples.','available_with_records','Exact sample identities and completed training-use records'),
        monitor('cached_baseline','Cached reward baseline','Inspect the baseline used for each prompt and any reference-stage filtering. Online prompt-group contrast is not its learning signal.','capture_pending','Native cached values, prompt identity and reference-stage membership'),
        monitor('regression','Advantage prediction error','Compare the sequence log-ratio prediction with reward minus the cached baseline. This objective has no PPO clipping gate.','available_with_records','Prediction and target at each recorded training use, with objective identity')]
    fingerprint = digest({'reader':VERSION,'version':revision,'settings':s})
    recipe = None
    if not issues:
        recipe = {'id':'setup-'+fingerprint,'revision':0,'label':label,
            'implementation':{'name':'trl/A2POTrainer','revision':revision},'config_digest':fingerprint,
            'basis':VERSION+': selected effective A*-PO settings; excludes custom rewards and independent native execution validation',
            'setup':{'schema':VERSION,'framework':'trl','trainer':'a2po','version':revision,'settings':s},
            'components_complete':False,'context':{'scheduling':'synchronous'},
            'components':[{'id':'rl-policy','label':'A*-PO sequence regression','supervision':'reward',
                'credit':{'kind':'cached_baseline','unit':'sample'},
                'objective':{'definition':'trl/a2po','unit':'sequence','weighting':'regression','reduction':profile['reduction']}}]}
    result = {'schema':VERSION,'framework':'trl','trainer':'a2po','version':revision or None,'label':label,
        'status':'ready' if recipe else 'needs_review','settings':s,'settings_digest':fingerprint,'profile':profile,
        'issues':issues,'monitors':checks,'recipe':recipe,'source':{'url':SOURCE,'revision':PIN},
        'boundary':'A*-PO has a reference-sampling stage and on-policy regression. Configuration recognition is separate from validated native capture.'}
    result['monitoring_plan'] = recommend(result)
    return result


def prepare(config, *, version, resolved):
    from argparse import Namespace
    from types import SimpleNamespace
    from dataclasses import is_dataclass
    if isinstance(config,(Namespace,SimpleNamespace)) or is_dataclass(config) and not isinstance(config,type): config=vars(config)
    report = inspect({'config':config,'version':version,'resolved':resolved})
    return {'framework':'trl','trainer':'a2po','version':version,'resolved':resolved,'config':report['settings']}
