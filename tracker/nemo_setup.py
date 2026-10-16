"""Read selected NeMo RL settings without importing or running the trainer.

Interpretation follows the pinned native config, estimator and loss implementations.
Callers supply effective settings after native validation/default composition.
"""

PIN = 'a5fba40266a2d696d4fb63c8b6e1278104840f90'
LOSS_FIELDS = ('disable_ppo_ratio force_on_policy_ratio sequence_level_importance_ratios '
               'token_level_loss use_cispo ratio_clip_min ratio_clip_max ratio_clip_c '
               'use_importance_sampling_correction truncated_importance_sampling_type '
               'truncated_importance_sampling_ratio truncated_importance_sampling_ratio_min '
               'reference_policy_kl_penalty reference_policy_kl_type use_kl_in_reward '
               'positive_example_nll_weight seq_logprob_error_in_loss').split()
COMMON_FIELDS = ('num_generations_per_prompt max_rollout_turns overlong_filtering '
                 'use_dynamic_sampling dynamic_sampling_max_gen_batches seq_logprob_error_threshold '
                 'adv_estimator.name adv_estimator.normalize_rewards '
                 'adv_estimator.use_leave_one_out_baseline adv_estimator.minus_baseline '
                 'adv_estimator.reward_weights').split()
FIELDS = (['loss_fn.' + f for f in LOSS_FIELDS]
          + [p + '.' + f for p in ('grpo', 'ppo') for f in COMMON_FIELDS]
          + [p + '.async_' + p + '.' + f for p in ('grpo', 'ppo') for f in
             ('enabled', 'max_trajectory_age_steps', 'in_flight_weight_updates')]
          + ['ppo.' + f for f in ('ppo_epochs', 'critic_ppo_epochs', 'policy_training_start_step',
             'adv_estimator.gae_lambda', 'adv_estimator.gae_gamma', 'adv_estimator.normalize_advantages',
             'adv_estimator.gae_lambda_value', 'adv_estimator.gae_lambda_policy', 'adv_estimator.length_adaptive_alpha')])
BOOL_FIELDS = {f for f in FIELDS if f.rsplit('.', 1)[-1] in {
    'disable_ppo_ratio', 'force_on_policy_ratio', 'sequence_level_importance_ratios',
    'token_level_loss', 'use_cispo', 'use_importance_sampling_correction', 'use_kl_in_reward',
    'overlong_filtering', 'use_dynamic_sampling', 'normalize_rewards', 'normalize_advantages',
    'use_leave_one_out_baseline', 'minus_baseline', 'enabled', 'in_flight_weight_updates',
    'seq_logprob_error_in_loss'}}


def profile(s, read, issue):
    families = [p for p in ('grpo', 'ppo') if any(k.startswith(p + '.') for k in s)]
    if len(families) != 1:
        issue('ambiguous', 'Supply one effective NeMo RL trainer configuration: grpo or ppo.')
        return None
    p = families[0]
    for path in BOOL_FIELDS & s.keys():
        if type(s[path]) is not bool: issue('invalid_type', path + ' must be a boolean')
    adv = read(p + '.adv_estimator.name', ['gae', 'raw_reward'] if p == 'ppo' else ['grpo', 'gdpo', 'reinforce_plus_plus'])
    credit = 'critic' if adv == 'gae' else 'group_relative' if adv in {'grpo', 'gdpo'} else 'return' if adv in {'raw_reward', 'reinforce_plus_plus'} else 'unknown'
    credit_unit = 'sample' if adv in {'grpo', 'gdpo', 'raw_reward'} else 'token' if adv in {'gae', 'reinforce_plus_plus'} else 'unknown'
    estimator = {'gae':'Generalized advantage estimation (GAE)', 'raw_reward':'Raw reward',
                 'grpo':'Group reward baseline', 'gdpo':'Separate reward-component normalization (GDPO)',
                 'reinforce_plus_plus':'REINFORCE++'}.get(adv, 'Not established')
    if adv in {'grpo', 'gdpo'}:
        leave_one_out = read(p + '.adv_estimator.use_leave_one_out_baseline', [True, False])
        normalize = read(p + '.adv_estimator.normalize_rewards', [True, False])
        if adv == 'grpo' and leave_one_out is True:
            estimator = 'Leave-one-out reward baseline' + (' · group scaling' if normalize is True else '')
    if adv == 'reinforce_plus_plus':
        baseline = read(p + '.adv_estimator.minus_baseline', [True, False])
        if baseline is True:
            credit = 'group_relative'; estimator += ' · prompt baseline'
        elif baseline == 'unknown': credit = 'unknown'
    flags = {k:read('loss_fn.' + k, [True, False]) for k in
             ('disable_ppo_ratio', 'force_on_policy_ratio', 'use_cispo', 'sequence_level_importance_ratios', 'token_level_loss')}
    disabled, forced, capped, sequence, token_loss = (flags[k] for k in flags)
    if capped is True and (disabled is True or forced is True or sequence is True or token_loss is False):
        issue('incompatible', 'NeMo RL CISPO requires token ratios and token loss; disabled or forced ratios are incompatible.')
    if capped is True and s.get('loss_fn.ratio_clip_c') is not None:
        issue('incompatible', 'NeMo RL CISPO cannot use dual clipping (ratio_clip_c).')
    if sequence is True and token_loss is True:
        issue('incompatible', 'NeMo RL sequence ratios require sequence-averaged loss.')
    if disabled is True and forced is True:
        issue('incompatible', 'Both disabled and forced ratios are set. Native forced-ratio precedence needs review.')
    weighting = 'unknown' if 'unknown' in flags.values() else 'capped' if capped else 'none' if disabled or forced else 'hard_gate'
    loss = 'unknown' if weighting == 'unknown' else 'cispo' if capped else 'reinforce' if disabled else 'on_policy' if forced else 'gspo' if sequence else 'clipped'
    ratio = 'unknown' if weighting == 'unknown' else 'none' if disabled else 'token' if forced else 'sequence' if sequence else 'token'
    objective = {'cispo':'Capped importance weights (CISPO)', 'reinforce':'Unclipped policy gradient',
                 'on_policy':'On-policy gradient · ratio fixed at one', 'gspo':'Sequence-clipped policy objective',
                 'clipped':'Clipped policy objective'}.get(loss, 'Unrecognized RL objective')
    reduction = 'active tokens in global batch' if token_loss is True else 'mean of sequence token means' if token_loss is False else 'unknown'
    rules = []
    async_path = p + '.async_' + p
    async_enabled = s.get(async_path + '.enabled')
    scheduling = 'asynchronous' if async_enabled is True else 'synchronous' if async_enabled is False else 'unknown'
    if async_enabled is True: rules.append('policy_lag')
    if s.get(async_path + '.in_flight_weight_updates') is True: rules.append('policy_segments')
    if s.get('loss_fn.use_importance_sampling_correction') is True: rules.append('policy_mismatch')
    if async_enabled is True and s.get('loss_fn.use_importance_sampling_correction') is not True:
        issue('incompatible', 'NeMo RL asynchronous training requires importance-sampling correction.')
    if s.get('loss_fn.truncated_importance_sampling_type') is not None and s.get('loss_fn.use_importance_sampling_correction') is not True:
        issue('incompatible', 'Truncated importance correction requires use_importance_sampling_correction.')
    if s.get(p + '.use_dynamic_sampling') is True: rules.append('selection')
    if s.get(p + '.overlong_filtering') is True: rules.append('truncation')
    if adv == 'gdpo': rules.append('reward_components')
    if adv == 'gae' and any(s.get('ppo.' + k) not in (None, 0) for k in
                         ('critic_ppo_epochs', 'policy_training_start_step')): rules.append('actor_critic_schedule')
    if adv == 'gae' and (s.get('ppo.adv_estimator.gae_lambda_value') is not None
            or s.get('ppo.adv_estimator.gae_lambda_policy') is not None
            or s.get('ppo.adv_estimator.length_adaptive_alpha', 0) != 0): rules.append('decoupled_gae')
    return dict(loss=loss, label=objective, credit=credit, credit_unit=credit_unit, weighting=weighting,
                ratio=ratio, reduction=reduction, rules=rules, estimator=estimator, scheduling=scheduling)
