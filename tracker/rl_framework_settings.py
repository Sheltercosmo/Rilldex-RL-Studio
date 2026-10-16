"""Pinned RL config readers. No trainer imports, callback execution or model calls.

Credit estimation, the policy objective and sampling correction are independent.
These readers describe selected settings; they do not validate native execution.
"""

PINS = {'openrlhf': 'dc2a7ad326f619fc5a47737ea47d1920ce2c0b53',
        'slime': '05e3b017fed9e02de418c2fbac9d75602a534be5'}
SOURCES = {
    'openrlhf': 'https://github.com/OpenRLHF/OpenRLHF/blob/' + PINS['openrlhf'] + '/openrlhf/models/loss.py',
    'slime': 'https://github.com/THUDM/slime/blob/' + PINS['slime'] + '/slime/backends/megatron_utils/loss.py',
}
FIELDS = {
    'openrlhf': ['algo.advantage.' + x for x in (
        'estimator', 'gamma', 'lambd', 'no_std_norm', 'is_correction_level',
        'is_correction_mode', 'is_correction_gating', 'is_correction_threshold')]
        + ['actor.policy_loss_type', 'actor.loss_agg_mode', 'critic.freezing_steps',
           'rollout.n_samples_per_prompt', 'train.async_enable', 'train.async_queue_size',
           'train.partial_rollout_enable', 'train.max_epochs', 'algo.dynamic_filtering_enable',
           'algo.kl.use_loss', 'algo.kl.init_coef'],
    'slime': ('advantage_estimator pg_loss_type use_score_centering loss_type train_backend '
        'calculate_per_token_loss rewards_normalization grpo_std_normalization normalize_advantages '
        'n_samples_per_prompt num_steps_per_rollout use_rollout_logprobs use_tis get_mismatch_metrics '
        'tis_clip tis_clip_low use_opsm opsm_delta use_unbiased_kl '
        'partial_rollout mask_offpolicy_in_partial_rollout rollout_function_path flush_cache_interval '
        'custom_advantage_function_path custom_reward_post_process_path '
        'custom_convert_samples_to_train_data_path custom_pg_loss_reducer_function_path '
        'custom_tis_function_path dynamic_sampling_filter_path rollout_sample_filter_path '
        'custom_generate_function_path rollout_logprob_server_url '
        'use_opd score_centering_top_k rollout_temperature rollout_top_p rollout_top_k '
        'gamma lambd kl_coef kl_loss_coef').split(),
}
BOOLS = {'no_std_norm', 'async_enable', 'partial_rollout_enable', 'dynamic_filtering_enable',
         'use_score_centering', 'calculate_per_token_loss', 'rewards_normalization',
         'grpo_std_normalization', 'normalize_advantages', 'use_rollout_logprobs', 'use_tis',
         'get_mismatch_metrics', 'use_opsm', 'partial_rollout', 'mask_offpolicy_in_partial_rollout',
         'use_opd', 'use_unbiased_kl', 'use_loss'}


def profile(framework, s, read, issue):
    for path, value in s.items():
        if path.split('.')[-1] in BOOLS and type(value) is not bool:
            issue('invalid_type', path + ' must be a boolean')
    return openrlhf(s, read, issue) if framework == 'openrlhf' else slime(s, read, issue)


def openrlhf(s, read, issue):
    prefix = 'algo.advantage.'
    adv = read(prefix + 'estimator', ['gae', 'reinforce', 'reinforce_baseline', 'rloo',
                                    'group_norm', 'dr_grpo', 'flash_reinforce'])
    grouped = adv in {'reinforce_baseline', 'rloo', 'group_norm', 'dr_grpo'}
    credit = 'critic' if adv == 'gae' else 'group_relative' if grouped else 'return' if adv != 'unknown' else 'unknown'
    estimator = {'gae': 'GAE with a value model', 'reinforce': 'REINFORCE++',
        'reinforce_baseline': 'REINFORCE++ with a prompt baseline', 'rloo': 'Leave-one-out baseline (RLOO)',
        'group_norm': 'Group reward baseline (GRPO)', 'dr_grpo': 'Group mean baseline (Dr. GRPO)',
        'flash_reinforce': 'Rollout-batch reward baseline (FlashREINFORCE)'}.get(adv, 'Not established')
    n = read('rollout.n_samples_per_prompt')
    if n != 'unknown' and (type(n) is not int or n < (2 if grouped else 1)):
        issue('incompatible', 'This OpenRLHF baseline requires ' + ('at least two' if grouped else 'at least one') + ' rollouts per prompt.')
    loss = read('actor.policy_loss_type', ['ppo', 'gspo'])
    reduction = read('actor.loss_agg_mode', ['token-mean', 'seq-mean-token-mean'])
    # Native PolicyLoss overrides token_level_loss for GSPO.
    if loss == 'gspo': reduction = 'seq-mean-token-mean'
    ratio = 'sequence' if loss == 'gspo' else 'token' if loss == 'ppo' else 'unknown'
    rules = []
    level = read(prefix + 'is_correction_level', ['off', 'token', 'seq'])
    if level not in {'off', 'unknown'}:
        rules.append('policy_mismatch')
        mode = read(prefix + 'is_correction_mode', ['mask', 'clip'])
        gate = read(prefix + 'is_correction_gating', ['ratio', 'binary_kl', 'tv'])
        bounds = read(prefix + 'is_correction_threshold')
        if not isinstance(bounds, list) or len(bounds) != 2 or not 0 <= bounds[0] <= bounds[1] or bounds[1] <= 0:
            issue('incompatible', 'Export the resolved two-element correction threshold: nonnegative lower bound and positive upper bound.')
        elif gate not in {'ratio', 'unknown'} and bounds[0] > 0:
            issue('incompatible', 'A divergence gate requires a zero lower bound.')
        if mode == 'clip' and (level != 'token' or gate != 'ratio'):
            issue('incompatible', 'Capped correction requires token-level ratio weights; sequence/divergence gates must mask.')
        # For GSPO, the correction switch changes the ratio denominator; the
        # separate PPO mask/clip branch does NOT run (native loss.py).
        if loss == 'ppo' and mode == 'mask': rules.append('selection')
    async_ = read('train.async_enable', [True, False])
    partial = read('train.partial_rollout_enable', [True, False])
    if partial is True and async_ is False:
        issue('incompatible', 'OpenRLHF partial rollouts require asynchronous training.')
    if async_ is True: rules.append('policy_lag')
    if partial is True: rules.append('policy_segments')
    if s.get('algo.dynamic_filtering_enable') is True: rules.append('selection')
    if adv == 'gae': rules.append('actor_critic_schedule')
    if adv == 'flash_reinforce': rules.append('batch_baseline')
    return dict(loss=loss, label=('GSPO' if loss == 'gspo' else 'PPO-style policy update') + ' · ' + estimator,
        credit=credit, credit_unit='token', weighting='hard_gate' if loss != 'unknown' else 'unknown',
        ratio=ratio, reduction=reduction, rules=rules, estimator=estimator,
        scheduling='asynchronous' if async_ is True else 'synchronous' if async_ is False else 'unknown')


def slime(s, read, issue):
    adv = read('advantage_estimator', ['grpo', 'gspo', 'cispo', 'ppo', 'reinforce_plus_plus', 'reinforce_plus_plus_baseline'])
    configured = read('pg_loss_type', [None, 'ppo', 'cispo', 'reinforce'])
    sc = read('use_score_centering', [True, False])
    loss = configured if configured is not None else 'reinforce' if sc is True else 'cispo' if adv == 'cispo' else 'ppo'
    if sc is True and loss != 'reinforce': issue('incompatible', 'Score centering requires the REINFORCE policy objective.')
    if adv in {'gspo', 'cispo'} and (sc is True or configured not in (None, 'ppo' if adv == 'gspo' else 'cispo')):
        issue('incompatible', 'slime GSPO/CISPO selects a specific policy objective and cannot be combined with score centering.')
    read('loss_type', ['policy_loss'])
    normalized = read('rewards_normalization', [True, False])
    group = normalized is True and adv in {'grpo', 'gspo', 'cispo', 'reinforce_plus_plus_baseline'}
    credit = 'critic' if adv == 'ppo' else 'group_relative' if group else 'return' if adv != 'unknown' and normalized != 'unknown' else 'unknown'
    estimator = 'GAE with a value model' if adv == 'ppo' else 'Prompt reward baseline' if group else 'Reward returns' if credit == 'return' else 'Not established'
    for hook in ('custom_advantage_function_path', 'custom_reward_post_process_path', 'custom_convert_samples_to_train_data_path'):
        value = read(hook)
        if value not in (None, 'unknown'):
            issue('custom', 'Custom reward/credit processing needs an explicit measurement declaration: ' + hook)
            credit = 'unknown'; estimator = 'Custom credit assignment'
    custom_reducer = read('custom_pg_loss_reducer_function_path')
    per_token = read('calculate_per_token_loss', [True, False])
    reduction = 'active tokens in training batch' if per_token is True else 'mean of sequence token means' if per_token is False else 'unknown'
    if custom_reducer not in (None, 'unknown'):
        reduction = 'unknown'; issue('custom', 'A custom policy-loss reducer needs its own reduction definition.')
    if adv in {'reinforce_plus_plus', 'reinforce_plus_plus_baseline'} and read('normalize_advantages', [True, False]) is not True:
        issue('incompatible', 'slime REINFORCE++ estimators require advantage normalization.')
    use_rollout = read('use_rollout_logprobs', [True, False]); tis = read('use_tis', [True, False])
    callback = read('custom_tis_function_path')
    if use_rollout is True and tis is True and loss != 'reinforce':
        issue('incompatible', 'Using rollout log probabilities with TIS requires the REINFORCE objective.')
    rules = []
    known_tis = (None, 'slime.backends.megatron_utils.loss.vanilla_tis_function', 'slime.backends.megatron_utils.loss.icepop_function')
    if tis is True:
        rules.append('policy_mismatch')
        if callback not in (*known_tis, 'unknown'):
            issue('custom', 'Custom correction weights and masks need an explicit measurement declaration.')
        if callback == known_tis[2]: rules.append('selection')
    if s.get('get_mismatch_metrics') is True:
        rules.append('policy_mismatch')
        if callback is None: issue('incompatible', 'slime mismatch metrics require a correction callback.')
    if s.get('use_opsm') is True or any(s.get(k) for k in ('dynamic_sampling_filter_path', 'rollout_sample_filter_path')):
        rules.append('selection')
    if s.get('partial_rollout') is True: rules.append('policy_segments')
    if s.get('mask_offpolicy_in_partial_rollout') is True: rules.append('selection')
    rollout = s.get('rollout_function_path')
    scheduling = 'asynchronous' if rollout == 'slime.rollout.fully_async_rollout.generate_rollout_fully_async' else 'unknown'
    if scheduling == 'asynchronous': rules.append('policy_lag')
    if sc is True:
        rules.append('sampling_support')
        if read('train_backend', ['megatron', 'fsdp']) != 'megatron': issue('incompatible', 'slime score centering requires the Megatron backend.')
        for field in ('use_opd', 'use_opsm', 'get_mismatch_metrics', 'use_unbiased_kl'):
            if read(field, [True, False]) is True: issue('incompatible', 'Score centering cannot combine with ' + field)
        if s.get('custom_generate_function_path') == 'slime.rollout.sglang_streaming_rollout.generate_streaming':
            issue('incompatible', 'Score centering does not support streaming rollout.')
        if s.get('rollout_logprob_server_url'):
            issue('incompatible', 'Score centering requires original sampler probabilities, not server-recomputed probabilities.')
        if tis is True:
            low, high = read('tis_clip_low'), read('tis_clip')
            if type(low) not in (int, float) or type(high) not in (int, float) or not 0 <= low <= high or high <= 0:
                issue('incompatible', 'Score-centering correction requires finite 0 <= lower <= upper and upper > 0.')
    # Orthogonal extra components stay explicit without diverting RL setup to a
    # distillation workflow or silently declaring the component list complete.
    if s.get('use_opd') is True: issue('custom', 'An additional teacher objective is enabled; declare that component separately.')
    ratio = 'none' if loss == 'reinforce' else 'sequence' if adv == 'gspo' else 'token'
    label = 'Score-centered REINFORCE' if sc is True else 'GSPO' if adv == 'gspo' else {'ppo':'PPO-style policy update', 'cispo':'CISPO', 'reinforce':'REINFORCE policy update'}.get(loss, 'Unknown policy update')
    return dict(loss=loss, label=label, credit=credit, credit_unit='token', ratio=ratio,
        weighting={'ppo':'hard_gate', 'cispo':'capped', 'reinforce':'none'}.get(loss, 'unknown'),
        reduction=reduction, rules=rules, estimator=estimator, scheduling=scheduling)


def examples():
    """Illustrative resolved settings, not observations or training prescriptions."""
    openrlhf_config = {
        'algo': {'advantage': {'estimator':'flash_reinforce', 'is_correction_level':'seq',
            'is_correction_mode':'mask', 'is_correction_gating':'binary_kl', 'is_correction_threshold':[0.0, 0.01]}},
        'actor': {'policy_loss_type':'ppo', 'loss_agg_mode':'token-mean'},
        'rollout': {'n_samples_per_prompt':1},
        'train': {'async_enable':True, 'partial_rollout_enable':True},
    }
    slime_config = {
        'advantage_estimator':'grpo', 'pg_loss_type':'reinforce', 'use_score_centering':True,
        'loss_type':'policy_loss', 'train_backend':'megatron', 'rewards_normalization':True,
        'calculate_per_token_loss':True, 'use_rollout_logprobs':True, 'use_tis':True,
        'tis_clip_low':0.0, 'tis_clip':2.0, 'custom_tis_function_path':None,
        'custom_advantage_function_path':None, 'custom_reward_post_process_path':None,
        'custom_convert_samples_to_train_data_path':None, 'custom_pg_loss_reducer_function_path':None,
        'use_opd':False, 'use_opsm':False, 'get_mismatch_metrics':False, 'use_unbiased_kl':False,
        'rollout_function_path':'slime.rollout.fully_async_rollout.generate_rollout_fully_async',
        'partial_rollout':True,
    }
    return [('openrlhf-flash', 'OpenRLHF · single-rollout batch baseline', 'openrlhf', openrlhf_config),
            ('slime-score', 'slime · score-centered REINFORCE', 'slime', slime_config)]
