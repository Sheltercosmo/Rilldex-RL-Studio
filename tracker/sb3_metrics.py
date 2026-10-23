"""Native SB3 logger definitions. Coordinates are environment timesteps."""

def definitions(metric):
    return {
        'rollout/ep_rew_mean': metric('Episode return · rolling mean','reward','return','native episode window mean','Mean return in SB3 ep_info_buffer, with stats_window_size in configuration. Monitor and wrapper placement determine the reward stream; this is not a success rate.'),
        'rollout/ep_len_mean': metric('Episode length · rolling mean','other','environment steps / episode','native episode window mean','Mean episode length in SB3 ep_info_buffer, not tokens or learner updates.'),
        'rollout/success_rate': metric('Reported episode success','reward','fraction','native success window mean','Mean explicitly supplied is_success flags. Missing flags are not failures.'),
        'eval/mean_reward': metric('Evaluation episode return','reward','return','evaluation episode mean','Mean return from the native EvalCallback evaluation episodes. Evaluation environment and protocol must be recorded separately.'),
        'eval/mean_ep_length': metric('Evaluation episode length','other','environment steps / episode','evaluation episode mean','Mean episode length from the native EvalCallback.'),
        'eval/success_rate': metric('Evaluation reported success','reward','fraction','evaluation episode mean','Mean explicitly supplied evaluation is_success flags.'),
        'time/fps': metric('Environment throughput','throughput','environment transitions / second','elapsed training rate','SB3 environment timesteps since this learn call divided by elapsed time. Includes training and collection; not model tokens per second.'),
        'time/total_timesteps': metric('Environment timesteps','other','environment transitions','trainer counter','Native num_timesteps across all vector slots. reset_num_timesteps can reset this counter between learn calls.'),
        'train/n_updates': metric('Native update counter','other','native updates','algorithm counter','Algorithm-defined update counter; PPO counts epochs and DQN counts gradient steps. Compare only within the same objective.'),
        'train/loss': metric('Native training loss','loss','objective units','algorithm logger reduction','Native train/loss. PPO logs its last minibatch total loss; DQN logs the mean Huber loss across gradient steps. Objective and framework version identify the definition.'),
        'train/policy_gradient_loss': metric('Policy gradient loss','loss','objective units','native optimization mean','Native mean policy loss across the completed optimization phase; not a rollout reward.'),
        'train/value_loss': metric('Value loss','loss','squared return units','native optimization mean','Native value-function loss, averaged as implemented by the recorded algorithm.'),
        'train/entropy_loss': metric('Negative policy entropy','entropy','negative nats','native optimization mean','Native entropy loss: negative entropy, or its sampled estimate when analytic entropy is unavailable. Values are not positive policy entropy.'),
        'train/approx_kl': metric('PPO approximate KL','kl','nats','native final optimization epoch','PPO mean of exp(log_ratio)-1-log_ratio for the final executed epoch. Not KL to a reference model or trainer/inference mismatch.'),
        'train/clip_fraction': metric('PPO clipping fraction','clipping','fraction','native optimization mean','PPO fraction with abs(ratio-1) above clip_range, averaged over recorded minibatches. Not clipped gradients, truncated episodes or discarded tokens.'),
        'train/explained_variance': metric('Value explained variance','other','fraction','native rollout-buffer statistic','Variance explained by value predictions against recorded returns. May be negative; unavailable when target variance is zero.'),
        'train/learning_rate': metric('Learning rate','other','learning rate','native optimizer value','Learning rate reported by the native algorithm after schedule evaluation.'),
        'rollout/exploration_rate': metric('DQN epsilon','other','probability','current exploration schedule','Native epsilon-greedy exploration probability. Not measured behavioral exploration or policy entropy.'),
        'train/actor_loss': metric('Actor loss','loss','objective units','native optimization mean','Native continuous-control actor objective; not interchangeable with PPO surrogate loss.'),
        'train/critic_loss': metric('Critic loss','loss','objective units','native optimization mean','Native critic objective across completed gradient steps.'),
    }
