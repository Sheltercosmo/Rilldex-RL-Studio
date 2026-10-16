"""Deterministic, conservative reading of resolved RL configurations.

No imports from trainers, inference calls, defaults guessed from a framework name,
or execution of Hydra/YAML expressions. Only an allowlist leaves the process.
"""
import math
from argparse import Namespace
from types import SimpleNamespace

from .schema import InputError, digest
from . import nemo_setup, rl_framework_settings, gigpo_setup

VERSION = 'training-setup/5'
SUPPORTED_VERSIONS = {'training-setup/1', 'training-setup/2', 'training-setup/3', 'training-setup/4', VERSION}
PINS = {'trl': '1.13.0', 'verl': '2035f58dcb06d8cad4caee107b30f4045d724367',
        'verl_agent': gigpo_setup.PIN,
        'areal': '3b5ebd550807aa64af8429cff0de7fa6d962afc3', 'nemo_rl': nemo_setup.PIN, **rl_framework_settings.PINS}
SOURCES = {'trl': 'https://huggingface.co/docs/trl/v1.13.0/en/grpo_trainer',
           'verl_agent': gigpo_setup.SOURCE,
           'verl': 'https://github.com/verl-project/verl/blob/' + PINS['verl'] + '/verl/workers/config/actor.py',
           'areal': 'https://github.com/areal-project/AReaL/blob/' + PINS['areal'] + '/areal/api/cli_args.py',
           'nemo_rl': 'https://github.com/NVIDIA-NeMo/RL/blob/' + PINS['nemo_rl'] + '/nemo_rl/algorithms/loss/clipped_pg.py',
           **rl_framework_settings.SOURCES}
TRL_FIELDS = ('loss_type importance_sampling_level scale_rewards multi_objective_aggregation num_generations '
              'num_generations_eval epsilon epsilon_high delta beta num_iterations max_completion_length '
              'mask_truncated_completions use_vllm vllm_importance_sampling_correction '
              'vllm_importance_sampling_mode vllm_importance_sampling_clip_max off_policy_mask_threshold '
              'top_entropy_quantile entropy_coef use_adaptive_entropy sapo_temperature_pos sapo_temperature_neg '
              'vespo_k_pos vespo_lambda_pos vespo_k_neg vespo_lambda_neg reward_weights '
              'temperature top_p top_k min_p repetition_penalty').split()
VERL_FIELDS = ['algorithm.' + x for x in ('adv_estimator', 'norm_adv_by_std_in_grpo', 'gamma', 'lam')] + [
    'actor_rollout_ref.actor.' + x for x in ('policy_loss.loss_mode', 'loss_agg_mode', 'clip_ratio',
    'clip_ratio_low', 'clip_ratio_high', 'ppo_epochs', 'use_kl_loss', 'kl_loss_coef', 'entropy_coeff',
    'tau_pos', 'tau_neg', 'policy_loss.rollout_correction.rollout_is',
    'policy_loss.rollout_correction.rollout_is_threshold')] + ['actor_rollout_ref.rollout.n'] + [
    'algorithm.rollout_correction.' + x for x in ('rollout_is', 'rollout_is_threshold',
        'rollout_rs', 'rollout_rs_threshold', 'bypass_mode', 'loss_type', 'rollout_is_batch_normalize', 'score_centering')]
AREAL_FIELDS = ['actor.' + x for x in ('use_sapo_loss', 'use_cispo_loss', 'importance_sampling_level',
    'use_decoupled_loss', 'eps_clip', 'eps_clip_higher', 'm2_threshold', 'kl_ctl', 'gae_timestep_unit',
    'gae_lambda', 'discount', 'mask_no_eos_with_zero', 'rejection_sampling.metric', 'prox_logp_method',
    'reward_norm.mean_level', 'reward_norm.std_level', 'reward_norm.mean_leave1out', 'reward_norm.std_unbiased',
    'adv_norm.mean_level', 'adv_norm.std_level', 'adv_norm.std_unbiased', 'adv_norm.mean_leave1out',
    'reward_scaling', 'reward_bias', 'reward_clip', 'sapo_tau_pos', 'sapo_tau_neg',
    'rejection_sampling.upper', 'min_usable_group_size', 'token_rewards_as_adv')] + ['gconfig.n_samples', 'rollout.max_head_offpolicyness']
FIELDS = {'trl': TRL_FIELDS, 'verl': VERL_FIELDS, 'areal': AREAL_FIELDS, 'nemo_rl': nemo_setup.FIELDS,
          'verl_agent': gigpo_setup.FIELDS,
          **rl_framework_settings.FIELDS}
MISSING = object()


def at(config, path):
    if isinstance(config, (Namespace, SimpleNamespace)): config = vars(config)
    exact = config.get(path, MISSING) if isinstance(config, dict) else MISSING
    current = config
    for key in path.split('.'):
        if isinstance(current, (Namespace, SimpleNamespace)): current = vars(current)
        if not isinstance(current, dict) or key not in current: return exact
        current = current[key]
    if exact is not MISSING and exact != current:
        raise InputError('Conflicting flat and nested training setting: ' + path)
    return current


def selected_settings(framework, config):
    selected = {}
    for path in FIELDS[framework]:
        value = at(config, path)
        if value is MISSING: continue
        # Only presence affects the supported sampling contract. Never retain
        # a server URL, which may contain credentials or private host details.
        if path == 'rollout_logprob_server_url':
            if value is not None and type(value) not in (str, bool):
                raise InputError('rollout_logprob_server_url must be a URL string, presence flag or null')
            selected[path] = bool(value) if value is not None else None
            continue
        if path.rsplit('.', 1)[-1] in {'reward_weights', 'is_correction_threshold'} and isinstance(value, (list, tuple)):
            if not 1 <= len(value) <= 32 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
                raise InputError(path + ' must be a finite numeric list')
            selected[path] = list(value)
            continue
        if (value is not None and type(value) not in (str, int, float, bool)
                or isinstance(value, str) and len(value) > 200
                or type(value) in (float, int) and not math.isfinite(value)):
            raise InputError('Invalid training setting: ' + path)
        selected[path] = value
    if framework == 'areal' and at(config, 'critic') is not MISSING:
        critic = at(config, 'critic')
        if critic is not None and not isinstance(critic, (dict, Namespace, SimpleNamespace)):
            raise InputError('critic must be an object or null')
        selected['critic.enabled'] = critic is not None
    return selected


def prepare(framework, config, *, version, resolved, trainer=None):
    """Create a safe settings export from an already composed native mapping."""
    if trainer is not None:
        if framework != 'trl' or trainer != 'a2po': raise InputError('Unsupported explicit trainer')
        from .trl_a2po_setup import prepare as prepare_a2po
        return prepare_a2po(config, version=version, resolved=resolved)
    if framework not in FIELDS or not isinstance(config, (dict, Namespace, SimpleNamespace)):
        raise InputError('Supply a supported framework and resolved config mapping')
    selected = selected_settings(framework, config)
    clean = {}
    for path, value in selected.items():
        if path == 'critic.enabled':
            clean['critic'] = {} if value else None
            continue
        parts = path.split('.'); target = clean
        for part in parts[:-1]: target = target.setdefault(part, {})
        target[parts[-1]] = value
    request = {'framework':framework, 'version':version, 'resolved':resolved, 'config':clean}
    inspect(request)  # Validate metadata too; incomplete but inspectable is allowed.
    return request


def inspect(request):
    if not isinstance(request, dict) or not isinstance(request.get('config'), dict):
        raise InputError('Supply a config object with framework, version and resolved metadata')
    if request.get('trainer') is not None:
        if request.get('framework') != 'trl' or request['trainer'] != 'a2po': raise InputError('Unsupported explicit trainer')
        from .trl_a2po_setup import inspect as inspect_a2po
        return inspect_a2po(request)
    cfg = request['config']; framework = request.get('framework', 'auto')
    if not isinstance(framework, str): raise InputError('framework must be a name')
    if framework == 'auto':
        agent = request.get('version') == gigpo_setup.PIN or (
            at(cfg, 'algorithm.adv_estimator') == 'gigpo' and at(cfg, 'env.rollout.n') is not MISSING)
        matches = [name for name, found in [('trl', 'loss_type' in cfg and 'advantage_estimator' not in cfg),
                   ('verl', not agent and ('actor_rollout_ref' in cfg or at(cfg, 'actor_rollout_ref.actor') is not MISSING)),
                   ('verl_agent', agent), ('areal', 'actor' in cfg and 'gconfig' in cfg),
                   ('nemo_rl', 'loss_fn' in cfg and ('grpo' in cfg or 'ppo' in cfg)),
                   ('openrlhf', at(cfg, 'algo.advantage.estimator') is not MISSING),
                   ('slime', 'advantage_estimator' in cfg and 'pg_loss_type' in cfg)] if found]
        if len(matches) != 1: raise InputError('Cannot identify one framework; include its name in the settings export.')
        framework = matches[0]
    if framework not in FIELDS: raise InputError('Config reading supports TRL, verl, verl-agent (GiGPO), AReaL, NeMo RL, OpenRLHF and slime.')
    revision = request.get('version', '')
    if not isinstance(revision, str) or len(revision) > 100: raise InputError('version must be a short string')
    if type(request.get('resolved', False)) is not bool: raise InputError('resolved must be true or false')
    s = selected_settings(framework, cfg); issues = []; missing = []
    def issue(code, message): issues.append({'code': code, 'message': message})
    bool_names = {'mask_truncated_completions', 'use_vllm', 'vllm_importance_sampling_correction',
                  'use_adaptive_entropy', 'norm_adv_by_std_in_grpo', 'use_kl_loss', 'use_sapo_loss',
                  'use_cispo_loss', 'use_decoupled_loss', 'mask_no_eos_with_zero', 'mean_leave1out',
                  'std_unbiased', 'token_rewards_as_adv', 'bypass_mode', 'rollout_is_batch_normalize', 'score_centering'}
    integer_names = {'num_generations', 'num_generations_eval', 'num_iterations', 'max_completion_length',
                     'ppo_epochs', 'n', 'n_samples', 'num_generations_per_prompt', 'max_rollout_turns', 'critic_ppo_epochs'}
    for path, value in s.items():
        name = path.split('.')[-1]
        if name in bool_names and type(value) is not bool:
            issue('invalid_type', path + ' must be a boolean')
        if name in integer_names and value is not None and (type(value) is not int or value < 1):
            issue('invalid_type', path + ' must be a positive integer')
    def read(path, allowed=None):
        value = s.get(path, MISSING)
        if value is MISSING:
            missing.append(path); return 'unknown'
        if allowed is not None and (type(value), value) not in {(type(v), v) for v in allowed}:
            issue('unsupported_setting', path + ' is not supported by this reader'); return 'unknown'
        return value
    unresolved = [k for k, v in s.items() if isinstance(v, str) and ('${' in v or v == '???')]
    if unresolved: issue('unresolved', 'Export the configuration after resolving defaults and overrides: ' + ', '.join(unresolved))
    if not request.get('resolved'): issue('unresolved', 'Configuration is not declared resolved; defaults and overrides may change its meaning.')
    if revision != PINS[framework]: issue('version', 'Field interpretation is checked against ' + framework + ' ' + PINS[framework] + '; this version is unverified.')
    credit = credit_unit = ratio = weighting = reduction = 'unknown'
    estimator = 'Not established'; scheduling = 'unknown'
    label = 'Unrecognized RL objective'; loss = 'unknown'; rules = []
    if framework == 'trl':
        loss = read('loss_type', ['grpo', 'dr_grpo', 'dapo', 'bnpo', 'cispo', 'sapo', 'luspo', 'vespo'])
        ratio = read('importance_sampling_level', ['token', 'sequence'])
        credit, credit_unit = 'group_relative', 'sample'
        estimator = 'Group reward baseline'
        reductions = {'grpo':'mean of sequence token means', 'sapo':'mean of sequence token means',
                      'dr_grpo':'batch size × maximum completion length', 'dapo':'active tokens in accumulated global batch',
                      'cispo':'active tokens in accumulated global batch', 'vespo':'active tokens in accumulated global batch',
                      'bnpo':'active tokens in local batch', 'luspo':'mean of sequence token sums'}
        reduction = reductions.get(loss, 'unknown')
        weighting = 'capped' if loss == 'cispo' else 'smooth' if loss in {'sapo', 'vespo'} else 'hard_gate' if loss in reductions else 'unknown'
        label = {'sapo':'Soft Adaptive Policy Optimization (SAPO)', 'cispo':'CISPO', 'vespo':'VESPO',
                 'luspo':'LUSPO'}.get(loss, 'Clipped RL · ' + loss.replace('_', ' ').upper() + ' reduction' if loss in reductions else label)
        if loss == 'luspo' and ratio != 'sequence': issue('incompatible', 'TRL LUSPO requires sequence-level importance sampling.')
        if loss == 'vespo': ratio = 'sequence'  # native kernel builds sequence weights regardless of ratio option
        read('scale_rewards', ['group', 'batch', 'none', True, False])
        aggregation = read('multi_objective_aggregation', ['sum_then_normalize', 'normalize_then_sum'])
        if aggregation == 'normalize_then_sum':
            estimator = 'Separate reward normalization, then weighted sum and batch normalization'
            rules.append('reward_components')
        elif isinstance(s.get('reward_weights'), list) and len(s['reward_weights']) > 1:
            rules.append('reward_components')
        if s.get('mask_truncated_completions') is True: rules.append('truncation')
        if s.get('use_vllm') is True: rules.append('policy_mismatch')
    elif framework == 'verl':
        adv = read('algorithm.adv_estimator', ['gae', 'grpo', 'grpo_vectorized', 'gdpo', 'rloo',
                    'rloo_vectorized', 'reinforce_plus_plus', 'reinforce_plus_plus_baseline'])
        credit = 'critic' if adv == 'gae' else 'return' if adv == 'reinforce_plus_plus' else 'group_relative' if adv != 'unknown' else 'unknown'
        credit_unit = 'token' if adv in {'gae', 'reinforce_plus_plus'} else 'sample' if adv != 'unknown' else 'unknown'
        estimator = {'gae':'Generalized advantage estimation (GAE)', 'rloo':'Leave-one-out reward baseline',
                     'rloo_vectorized':'Leave-one-out reward baseline', 'gdpo':'Separate reward-component normalization (GDPO)',
                     'reinforce_plus_plus':'REINFORCE++', 'reinforce_plus_plus_baseline':'REINFORCE++ · prompt baseline',
                     'grpo':'Group reward baseline', 'grpo_vectorized':'Group reward baseline'}.get(adv, 'Not established')
        loss = read('actor_rollout_ref.actor.policy_loss.loss_mode', ['vanilla', 'gspo', 'sapo', 'cispo', 'bypass_mode'])
        ratio = 'sequence' if loss == 'gspo' else 'token' if loss != 'unknown' else 'unknown'
        weighting = {'vanilla':'hard_gate', 'gspo':'hard_gate', 'sapo':'smooth', 'cispo':'capped'}.get(loss, 'unknown')
        reduction = read('actor_rollout_ref.actor.loss_agg_mode', ['token-mean', 'seq-mean-token-sum', 'seq-mean-token-mean', 'seq-mean-token-sum-norm'])
        label = {'vanilla':'Clipped policy objective', 'gspo':'GSPO', 'sapo':'Soft Adaptive Policy Optimization (SAPO)', 'cispo':'CISPO'}.get(loss, label)
        correction = 'algorithm.rollout_correction.'
        if any(k.startswith(correction) for k in s):
            bypass = read(correction + 'bypass_mode', [True, False])
            if correction + 'rollout_is' in s: read(correction + 'rollout_is', [None, 'token', 'sequence'])
            if bypass is True:
                bypass_loss = read(correction + 'loss_type', ['reinforce', 'ppo_clip'])
                loss = 'bypass_' + bypass_loss
                weighting = 'none' if bypass_loss == 'reinforce' else 'hard_gate' if bypass_loss == 'ppo_clip' else 'unknown'
                ratio = 'token' if bypass_loss == 'ppo_clip' else 'none' if bypass_loss == 'reinforce' else 'unknown'
                label = 'REINFORCE with rollout correction' if bypass_loss == 'reinforce' else 'Clipped policy objective · rollout-policy baseline'
            elif loss == 'bypass_mode': issue('incompatible', 'Bypass policy loss requires algorithm.rollout_correction.bypass_mode=true.')
            if s.get(correction + 'rollout_is') is not None or bypass is True: rules.append('policy_mismatch')
            if s.get(correction + 'rollout_rs') is not None: rules.append('selection')
            if s.get(correction + 'score_centering') is True and not (
                    bypass is True and s.get(correction + 'loss_type') == 'reinforce'
                    and s.get(correction + 'rollout_is') in (None, 'token')):
                issue('incompatible', 'verl score centering requires bypass REINFORCE with no or token-level importance weights.')
        elif loss == 'bypass_mode': issue('missing', 'Bypass policy loss needs algorithm.rollout_correction settings.')
        if any(k.startswith('actor_rollout_ref.actor.policy_loss.rollout_correction.') for k in s) and not any(k.startswith(correction) for k in s):
            issue('missing', 'Only actor-side correction settings are present. Export algorithm.rollout_correction to establish the trainer-selected policy loss.')
        if adv == 'gdpo': rules.append('reward_components')
    elif framework == 'areal':
        sapo = read('actor.use_sapo_loss', [True, False]); cispo = read('actor.use_cispo_loss', [True, False])
        decoupled = read('actor.use_decoupled_loss', [True, False])
        ratio = read('actor.importance_sampling_level', ['token', 'sequence'])
        if sapo is True and cispo is True: issue('incompatible', 'AReaL SAPO and CISPO are mutually exclusive.')
        if sapo is True and decoupled is True: issue('incompatible', 'AReaL SAPO cannot use decoupled loss.')
        if cispo is True and ratio != 'token': issue('incompatible', 'AReaL CISPO requires token-level ratios.')
        positive = (['actor.eps_clip_higher'] if cispo is True else []) + (['actor.sapo_tau_pos', 'actor.sapo_tau_neg'] if sapo is True else [])
        for path in positive:
            value = read(path)
            if value != 'unknown' and (type(value) not in (int, float) or value <= 0):
                issue('incompatible', path + ' must be positive for the selected objective.')
        loss = 'sapo' if sapo is True else 'cispo' if cispo is True else 'clipped' if sapo is False and cispo is False else 'unknown'
        weighting = {'sapo':'smooth', 'cispo':'capped', 'clipped':'hard_gate'}.get(loss, 'unknown')
        label = {'sapo':'Soft Adaptive Policy Optimization (SAPO)', 'cispo':'CISPO', 'clipped':'Clipped policy objective'}.get(loss, label)
        critic = read('critic.enabled', [True, False])
        if critic is True:
            credit = 'critic'; credit_unit = read('actor.gae_timestep_unit', ['token', 'turn'])
            estimator = 'Generalized advantage estimation (GAE)'
            label += ' · critic / GAE'
        elif critic is False:
            # Group centering is distinct from group variance scaling.
            group = any(s.get('actor.' + n + '.mean_level') == 'group' for n in ('reward_norm', 'adv_norm'))
            credit = 'group_relative' if group else 'return'; credit_unit = 'token'
            estimator = 'Group-centered rewards or advantages' if group else 'Reward returns'
        if decoupled is True: rules.append('policy_mismatch')
        if s.get('actor.rejection_sampling.metric') is not None: rules.append('selection')
        if s.get('actor.mask_no_eos_with_zero') is True: rules.append('truncation')
        if s.get('actor.m2_threshold') is not None: rules.append('moment_constraint')
    elif framework == 'verl_agent':
        native = gigpo_setup.profile(s, read, issue)
        loss, label, credit, credit_unit, weighting, ratio, reduction, rules, estimator, scheduling = (
            native[k] for k in ('loss', 'label', 'credit', 'credit_unit', 'weighting', 'ratio',
                               'reduction', 'rules', 'estimator', 'scheduling'))
    else:
        native = (rl_framework_settings.profile(framework, s, read, issue) if framework in rl_framework_settings.FIELDS
                  else nemo_setup.profile(s, read, issue))
        if native:
            loss, label, credit, credit_unit, weighting, ratio, reduction, rules, estimator, scheduling = (
                native[k] for k in ('loss', 'label', 'credit', 'credit_unit', 'weighting', 'ratio',
                                   'reduction', 'rules', 'estimator', 'scheduling'))
    if missing: issue('missing', 'Settings not recorded: ' + ', '.join(missing))
    if ratio == 'sequence': label += ' · sequence ratios'
    monitors = [monitor('reward', 'Reward and task outcomes', 'Compare recorded reward with independent task results.', 'available_with_records', 'Scores, outcome definitions and generation steps'),
                monitor('use', 'Samples used for training', 'Follow filtering, repeated use and masked tokens.', 'available_with_records', 'Selection and completed backward/update records')]
    if credit == 'group_relative': monitors.append(monitor('group_contrast', 'Groups with identical rewards', 'Find prompt groups with no recorded reward contrast.', 'available_with_records', 'Complete native prompt groups and scored reward components'))
    if credit == 'critic': monitors.append(monitor('critic_credit', 'Value predictions and returns', 'Compare prediction error and variation at the native time unit.', 'available_with_records', 'Aligned native values, return targets, observation masks and token/turn/state positions'))
    if credit == 'return': monitors.append(monitor('return_credit', 'Return-based learning signal', 'Inspect the native return and advantage distributions, including batch normalization or baselines when used.', 'capture_pending', 'Aligned rewards, returns, advantages, masks and normalization membership'))
    if weighting in {'hard_gate', 'capped', 'smooth'}:
        names = {'hard_gate':('Clipped update contribution', 'Clipping depends on ratio and advantage sign; a clipped ratio alone is not zero gradient.'),
                 'capped':('Capped importance weights', 'Capped weights can still contribute gradients; do not count them as discarded tokens.'),
                 'smooth':('Smooth update weights', 'Inspect effective derivative weights; a hard clipping rate is not meaningful here.')}
        title, why = names[weighting]
        monitors.append(monitor('objective_exposure', title, why, 'capture_pending', 'Native effective coefficients, loss masks and exact reduction'))
    if weighting == 'none': monitors.append(monitor('unclipped_update', 'Policy-gradient contribution', 'This objective has no PPO clipping gate. Inspect native derivatives and separate correction terms.', 'capture_pending', 'Native policy-loss derivatives, correction terms, masks and exact reduction'))
    if ratio == 'sequence': monitors.append(monitor('sequence_ratio', 'Sequence ratio distribution', 'Keep sequence weights separate from token-ratio summaries.', 'capture_pending', 'Native sequence weights and their length normalization'))
    extra = {'policy_mismatch':('Sampling and training mismatch', 'Compare sampling and learner probabilities, plus proximal probabilities when the method uses them.'),
             'selection':('Rejected training data', 'Inspect rejection masks and the behavior distribution before and after selection.'),
             'truncation':('Truncated samples excluded', 'Track how much generated work is removed by the completion mask.'),
                 'moment_constraint':('Second-moment constraint', 'Read native M2PO constraint and weights independently of PPO clipping.'),
             'policy_lag':('Policy age at training', 'Compare behavior and training use by generation-to-update policy age; wall-clock arrival is a different measurement.'),
             'policy_segments':('Policy changes within a rollout', 'Retain the policy version for each generated segment when weights change during generation.'),
             'reward_components':('Reward relationships', 'Compare recorded component scores on the same samples and complete groups. Native normalization and weights determine their learning contribution.'),
             'actor_critic_schedule':('Policy and value-model updates', 'Separate critic-only warmup, actor passes and critic passes. A critic update does not establish policy training.'),
             'decoupled_gae':('Policy advantages and value targets', 'Keep the two GAE decay settings and length adaptation separate; value targets may differ from policy advantages.')}
    extra.update({
        'episode_baseline':('Episode baseline and length weighting', 'This pinned GiGPO implementation computes the baseline across turn rows. Retain episode membership to show how longer episodes change its weighting.'),
        'state_groups':('State-group coverage', 'Count singleton groups and groups with no return variation. A zero state-relative signal does not imply zero episode or combined credit. Use native group membership, including similarity grouping when enabled.'),
        'advantage_components':('Episode and state signal agreement', 'Compare the episode term, the weighted state term and their sum: cancellation and sign changes matter more than reward contrast alone.'),
        'turn_continuity':('Episode and turn coverage', 'Keep generated turns, episode boundaries and training iterations separate. Quoted prompt history cannot establish executed actions or missing episode links.'),
        'batch_baseline':('Batch reward baseline', 'Monitor the actual rollout-batch baseline and composition. One rollout per prompt does not create a within-prompt comparison.'),
        'sampling_support':('Sampler probability coverage', 'Score centering depends on the original sampler distribution and support, including top-p truncation or head/tail mass.')})
    requirements = {
        'episode_baseline':'Native episode-group and trajectory IDs, turn inclusion/multiplicity, rewards and actual normalization statistics',
        'state_groups':'Native anchor-group IDs and complete membership, discounted step returns, grouping mode and response masks',
        'advantage_components':'Aligned episode and state advantages, effective state weight, joint advantages and response masks at the learner',
        'turn_continuity':'Native episode ID, ordered turn ID, action/result links, termination/truncation and generation policy identity',
        'policy_mismatch':'Sampling and learner log probabilities, optional proximal probabilities, masks and matching policy identities',
        'selection':'Named acceptance/rejection decisions and the pre-filter sample population',
        'truncation':'Native completion reason and the exact sample/token exclusion mask',
        'moment_constraint':'Native second-moment statistic, threshold, mask and loss normalization',
        'policy_lag':'Generation policy versions and the learner update that consumed each sample',
        'policy_segments':'Token/turn boundaries with the policy version that generated each segment',
        'reward_components':'Component scores, normalization scopes, component weights and exact sample/group membership',
        'actor_critic_schedule':'Separate actor and critic update receipts, warmup state and reused sample identities',
        'decoupled_gae':'Aligned native values, rewards, value returns, policy advantages and effective decay parameters',
        'batch_baseline':'Exact baseline batch membership, raw rewards and the recorded batch mean',
        'sampling_support':'Original sampler probabilities, candidate support, tail mass and effective sampling transformations',
    }
    for rule in dict.fromkeys(rules):
        title, why = extra[rule]
        monitors.append(monitor(rule, title, why, 'capture_pending', requirements[rule]))
    fingerprint = digest({'reader': VERSION, 'framework': framework, 'version': revision, 'settings': s})
    # Recognition never claims a complete objective or validated execution. Extra
    # losses, reward functions and custom callbacks are deliberately not inferred.
    recipe = None
    if not issues and loss != 'unknown':
        recipe = {'id':'setup-' + fingerprint, 'revision':0, 'label':label,
                  'implementation':{'name':framework, 'revision':revision}, 'config_digest':fingerprint,
                  'basis':VERSION + ': selected resolved RL settings; excludes unrecognized fields, auxiliary losses and runtime validation',
                  'setup':{'schema':VERSION, 'framework':framework, 'version':revision, 'settings':s},
                  'components_complete':False, 'context':({'scheduling':scheduling} if scheduling != 'unknown' else {}),
                  'components':[{'id':'rl-policy', 'label':label, 'supervision':'reward',
                      'credit':{'kind':credit, 'unit':credit_unit},
                      'objective':{'definition':framework + '/' + loss, 'unit':ratio,
                                   'weighting':weighting, 'reduction':reduction}}]}
    result = {'schema':VERSION, 'framework':framework, 'version':revision or None, 'label':label,
            'status':'ready' if recipe else 'needs_review', 'settings':s, 'settings_digest':fingerprint,
            'profile':{'credit':credit, 'credit_unit':credit_unit, 'ratio_unit':ratio, 'weighting':weighting, 'reduction':reduction,
                       'estimator':estimator, 'scheduling':scheduling},
            'issues':issues, 'monitors':monitors, 'recipe':recipe,
            'source':{'url':SOURCES[framework], 'revision':PINS[framework]},
            'boundary':'Settings interpretation, not proof of a working trainer integration. TRL 1.13.0 has a separately tested single-process CPU capture path. Other readers still need native record delivery. No thresholds or trainer settings are changed.'}
    from .training_monitoring import recommend
    result['monitoring_plan'] = recommend(result)
    return result


def monitor(identifier, label, reason, state, requires):
    return {'id':identifier, 'label':label, 'reason':reason, 'state':state, 'requires':requires}


def examples():
    """One server-owned set of illustrative settings, never training observations."""
    rows = [
        ('trl-cispo', 'TRL · capped weights (CISPO)', 'trl',
         {'loss_type':'cispo', 'importance_sampling_level':'token', 'scale_rewards':'group',
          'multi_objective_aggregation':'sum_then_normalize', 'num_generations':8}),
        ('trl-sapo', 'TRL · smooth weights (SAPO)', 'trl',
         {'loss_type':'sapo', 'importance_sampling_level':'token', 'scale_rewards':'group',
          'multi_objective_aggregation':'sum_then_normalize', 'num_generations':8}),
        ('verl-ppo', 'verl · PPO with a value model', 'verl',
         {'algorithm':{'adv_estimator':'gae'}, 'actor_rollout_ref':{'actor':{
             'policy_loss':{'loss_mode':'vanilla'}, 'loss_agg_mode':'token-mean'}}}),
        ('verl-reinforce', 'verl · REINFORCE with rollout correction', 'verl',
         {'algorithm':{'adv_estimator':'rloo', 'rollout_correction':{'bypass_mode':True,
             'loss_type':'reinforce', 'rollout_is':'token', 'rollout_is_threshold':2.0}},
          'actor_rollout_ref':{'actor':{'policy_loss':{'loss_mode':'vanilla'}, 'loss_agg_mode':'token-mean'}}}),
        ('areal-sequence', 'AReaL · sequence ratios', 'areal',
         {'actor':{'use_sapo_loss':False, 'use_cispo_loss':False, 'use_decoupled_loss':True,
             'importance_sampling_level':'sequence', 'reward_norm':{'mean_level':'group'}},
          'gconfig':{'n_samples':8}, 'critic':None}),
    ]
    common = {'disable_ppo_ratio':False, 'force_on_policy_ratio':False, 'use_cispo':False,
              'sequence_level_importance_ratios':False, 'token_level_loss':True}
    rows.extend([
        ('nemo-async-ppo', 'NeMo RL · asynchronous PPO', 'nemo_rl',
         {'loss_fn':{**common, 'use_importance_sampling_correction':True},
          'ppo':{'adv_estimator':{'name':'gae'}, 'num_generations_per_prompt':1,
             'ppo_epochs':1, 'critic_ppo_epochs':4, 'policy_training_start_step':4,
             'async_ppo':{'enabled':True, 'in_flight_weight_updates':True}}}),
        ('nemo-gdpo', 'NeMo RL · multiple reward components (GDPO)', 'nemo_rl',
         {'loss_fn':common, 'grpo':{'adv_estimator':{'name':'gdpo', 'normalize_rewards':True,
             'use_leave_one_out_baseline':False}, 'num_generations_per_prompt':8,
             'async_grpo':{'enabled':False}, 'use_dynamic_sampling':True}}),
    ])
    rows.extend(rl_framework_settings.examples())
    rows.extend(gigpo_setup.examples())
    result = {'schema':VERSION, 'examples':[{'id':key, 'label':label,
             'request':{'framework':framework, 'version':PINS[framework], 'resolved':True, 'config':config}}
             for key, label, framework, config in rows]}
    result['examples'].append({'id':'trl-a2po','label':'TRL · cached baseline (A*-PO)',
        'request':{'framework':'trl','trainer':'a2po','version':PINS['trl'],'resolved':True,
            'config':{'num_value_samples':8,'beta1':0.5,'beta2':0.001,'filter_all_incorrect':True}}})
    return result


def record(outbox, experiment, request):
    """Queue a content-addressed declaration and return the reference for facts."""
    result = inspect(request)
    if not result['recipe']:
        raise InputError('Training setup cannot be recorded: ' + '; '.join(i['message'] for i in result['issues']))
    outbox.log_recipes(experiment, [result['recipe']])
    return {'producer':outbox.producer, 'id':result['recipe']['id'], 'revision':0}
