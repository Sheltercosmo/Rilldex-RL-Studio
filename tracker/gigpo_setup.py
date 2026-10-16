"""Read the pinned verl-agent GiGPO path, without treating it as upstream verl.

This reader establishes settings only. Episode membership, anchor groups and
advantages must come from the trainer; decoded prompt similarity is not a join.
"""

PIN = '20bd331bdbc9026a5668e11362178e10ab7400c8'
SOURCE = 'https://github.com/langfengQ/verl-agent/blob/' + PIN + '/gigpo/core_gigpo.py'
FIELDS = ['algorithm.' + x for x in (
    'adv_estimator', 'gamma', 'use_kl_in_reward', 'use_pf_ppo',
    'gigpo.mode', 'gigpo.step_advantage_w', 'gigpo.enable_similarity',
    'gigpo.similarity_thresh', 'filter_groups.enable', 'filter_groups.max_num_gen_batches')]
FIELDS += ['actor_rollout_ref.actor.' + x for x in (
    'policy_loss.loss_mode', 'loss_agg_mode', 'clip_ratio', 'clip_ratio_low',
    'clip_ratio_high', 'clip_ratio_c', 'ppo_epochs', 'use_kl_loss', 'kl_loss_coef',
    'entropy_coeff', 'use_invalid_action_penalty', 'invalid_action_penalty_coef')]
FIELDS += ['env.rollout.n', 'env.max_steps', 'env.history_length']


def profile(s, read, issue):
    read('algorithm.adv_estimator', ['gigpo'])
    loss = read('actor_rollout_ref.actor.policy_loss.loss_mode', ['vanilla', 'gspo'])
    reduction = read('actor_rollout_ref.actor.loss_agg_mode',
                     ['token-mean', 'seq-mean-token-sum', 'seq-mean-token-mean', 'seq-mean-token-sum-norm'])
    read('algorithm.gigpo.mode', ['mean_norm', 'mean_std_norm'])
    similar = read('algorithm.gigpo.enable_similarity', [True, False])
    dynamic = read('algorithm.filter_groups.enable', [True, False])
    # This native post-advantage transformation is outside this reader's scope.
    if read('algorithm.use_pf_ppo', [True, False]) is True:
        issue('unsupported_setting', 'PF-PPO changes the prepared advantages; capture its native reweighting before interpreting GiGPO credit.')
    for key in ['algorithm.gamma', 'algorithm.gigpo.step_advantage_w']:
        value = read(key)
        if value != 'unknown' and type(value) not in (int, float):
            issue('invalid_type', key + ' must be a finite number')
    for key in ['env.rollout.n', 'env.max_steps']:
        value = read(key)
        if value != 'unknown' and (type(value) is not int or value < 1):
            issue('invalid_type', key + ' must be a positive integer')
    if similar is True:
        threshold = read('algorithm.gigpo.similarity_thresh')
        if threshold != 'unknown' and (type(threshold) not in (int, float) or not 0 < threshold < 1):
            issue('incompatible', 'GiGPO similarity grouping requires a threshold strictly between 0 and 1.')
    if dynamic is True:
        limit = read('algorithm.filter_groups.max_num_gen_batches')
        if limit != 'unknown' and (type(limit) is not int or limit < 1):
            issue('invalid_type', 'Generation retry limit must be a positive integer.')
    if 'env.history_length' in s and (type(s['env.history_length']) is not int or s['env.history_length'] < 0):
        issue('invalid_type', 'History length must be a nonnegative integer.')
    rules = ['episode_baseline', 'turn_continuity']
    if s.get('algorithm.gigpo.step_advantage_w') != 0:
        rules += ['state_groups', 'advantage_components']
    if dynamic is True: rules.append('selection')
    return {'loss': loss, 'label': 'GiGPO', 'credit': 'hierarchical_group_relative',
            'credit_unit': 'turn', 'weighting': 'hard_gate' if loss != 'unknown' else 'unknown',
            'ratio': 'sequence' if loss == 'gspo' else 'token' if loss == 'vanilla' else 'unknown',
            'reduction': reduction, 'rules': rules,
            'estimator': 'Episode and state baselines (GiGPO)' if s.get('algorithm.gigpo.step_advantage_w') != 0
                         else 'Episode baseline (state contribution disabled)',
            'scheduling': 'synchronous'}


def examples():
    return [('verl-agent-gigpo', 'verl-agent · episode and state credit (GiGPO)', 'verl_agent', {
        'algorithm': {'adv_estimator': 'gigpo', 'gamma': 0.95, 'use_pf_ppo': False,
                      'gigpo': {'mode': 'mean_std_norm', 'step_advantage_w': 1.0,
                                'enable_similarity': False, 'similarity_thresh': 0.95},
                      'filter_groups': {'enable': False, 'max_num_gen_batches': 10}},
        'actor_rollout_ref': {'actor': {'policy_loss': {'loss_mode': 'vanilla'}, 'loss_agg_mode': 'token-mean'}},
        'env': {'rollout': {'n': 8}, 'max_steps': 50, 'history_length': 2}})]
