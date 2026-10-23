# Stable-Baselines3

Capture native metrics, logs, configuration and hardware in the same run. Add the optional environment wrapper for action, reward and observation traces. Install Rilldex alongside your existing `stable-baselines3` environment.

```python
from rilldex import Run
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env

with Run("cartpole", project="control", workspace="study.sqlite") as run:
    capture = run.stable_baselines()
    env = capture.wrap_env(make_vec_env("CartPole-v1", n_envs=4))
    try:
        model = PPO("MlpPolicy", env)
        model.learn(4096, callback=capture.callback())
    finally:
        env.close()
```

Run `rilldex --db study.sqlite start --open`. Select **control / cartpole**: **Training signals** shows native curves; **Run details** contains configuration, logs and hardware; **Rollouts** opens captured episodes. For metrics only, omit `capture.wrap_env(...)`. Other callbacks can share a list with `capture.callback()`; existing logger outputs remain attached.

Training signals defaults to the latest received session across all charts. Use **Session** or **Browse sessions** to review an earlier capture; its selection survives reload. Native JSONL export follows the selected worker, session, clock and step interval.

- **Remote/offline:** pass `target=outbox` to `Run`. Start its background sender for live delivery, or transfer the saved outbox later. [Delivery and file capture](RUN_CAPTURE.md).
- **Resume:** reuse the project/name and load your checkpoint normally. Each `Run` and `learn` call retains a separate session, including counter resets. `run.add_file(path)` snapshots files up to 2 MiB.
- **Vector environments:** preserve each slot's episodes, terminal observations and truncation. On Windows, start `SubprocVecEnv` inside `if __name__ == "__main__":`.
- **Large observations:** supply `observation_projection=lambda obs: ...` and optional `info_projection` to return compact JSON. The default supports JSON/NumPy state up to 64 KiB per observation. Callbacks receive copies.

Episode return is not inferred success. Success requires an explicit `is_success` flag. Capture records the wrapped VecEnv boundary; place it outside `VecNormalize` to retain normalized values, or inside for pre-normalized values. Metrics retain native reductions: PPO entropy loss is negative entropy; PPO KL is distinct from trainer/inference mismatch; DQN epsilon is a configured probability. Environment timesteps are not learner updates or tokens.

Capture errors raise; store the outbox on reliable local storage. Incomplete episodes stay incomplete. Source traces do not establish exact replay-buffer or optimizer use, and state/action records alone do not contain a language model's plans. Native CPU validation covers SB3 2.9.0 PPO/DQN, vector resets, normalization, evaluation, checkpoint resume and Windows spawned workers. GPU/distributed algorithms and other SB3 releases need separate validation.
