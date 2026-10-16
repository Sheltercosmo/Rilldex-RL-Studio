# TRL GRPO capture

For the separate opt-in adapter that follows native grouping, masks, shuffle and backward reuse, see [training sample lineage](TRAINING_LINEAGE.md#optional-native-trl-adapter). Its private hooks have narrower compatibility than this public reward wrapper. Reward-only capture still does not establish optimizer use.

This optional bridge wraps a public custom reward function. It uses the ordinary durable outbox and source contracts; the tracker package does not depend on TRL, Torch or a trainer subclass. **TRL 1.13.0 was executed end to end on a Windows CPU**, using an authored tiny random model. TRL 1.15.0 was source-inspected and attempted, but its unconditional Triton-dependent GRPO path failed on this machine before capture. No upstream code was patched. See the [runtime audit](../research/trl-runtime-2026-10-11/README.md) for exact pins, source hashes and the retained failure. Inspect and revalidate against your installed version before an upgrade.

The public reward callback receives generated prompts, completions, completion token IDs, dataset columns and `trainer_state`. In the inspected release, the callback occurs when a generation batch is scored. A batch can subsequently be reused for several optimizer steps. Capture at this hook therefore counts generated/scored completions; it must not count every optimizer use as a newly sampled rollout. The original reward function is evaluated once and its return object is passed back unchanged.

## Connect a reward function

```python
import trl
from tracker.capture import Outbox
from tracker.trl_capture import GRPOCapture

outbox = Outbox(
    'worker-0-component-a.sqlite',
    producer='experiment-a/rank-0/component-a',
).start(report_status=True)

# Define trainer before the first callback executes. Read the actual sampler's
# policy identifier here when available; leave it absent when unknown.
def capture_context():
    return {
        'split': 'train' if trainer.model.training else 'evaluation',
        'worker_rank': trainer.accelerator.process_index,
        'environment': 'my-task-family',
        'environment_version': 'task-set-v1',
        # 'policy_version': actual_generating_policy_identifier,
    }

capture = GRPOCapture(
    outbox,
    experiment='experiment-a',
    reward_definition='my-reward-component/v1',
    trainer_version=trl.__version__,
    context=capture_context,
    on_error='warn',  # explicitly choose 'warn' or 'raise'
)

trainer = trl.GRPOTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    processing_class=tokenizer,
    reward_funcs=capture.wrap_reward(my_reward_function),
)
trainer.train()
print(capture.status())
outbox.close()  # pending delivery survives; close does not flush it
```

Use a distinct outbox and producer for each worker and separately captured reward component. Put stable `tracking_task_id` and `tracking_sample_id` columns into the dataset when available. The bridge preserves their repeated values across completions, while batch UUID + local completion index identifies each generated sample. It does not infer global GRPO repeat indices from a local rank's row order or deduplicate identical completions. New callback invocations get new sample identities, including after a process restart; queued revisions retain their IDs across transport retries.

`on_error='warn'` keeps the original reward output, emits an explicit warning and increments failed-batch counters. That batch is missing from capture. The trainer must retain its own data if capture completeness is required. `on_error='raise'` stops the callback on capture failure. A reward-function exception is always re-raised; the bridge first attempts to preserve its source with lifecycle `failed`, missing score and a separate raw scorer error. That is a scoring failure, not an agent task-failure label. If enqueueing also fails, the original reward exception gains a note and remains the exception raised. Check both in-process capture counts and durable outbox status; in-process counters reset at restart.

The generation batch is validated and enqueued in one local SQLite transaction. Backpressure or an invalid last row does not leave earlier rows queued. Delivery remains per rollout revision, so server visibility can advance gradually. `Outbox.log_many` accepts up to 1,000 snapshots; the existing 20 MiB request and 256 MiB default pending limits still apply. Enqueue is synchronous disk work; delivery runs separately.

## What the captured fields mean

| Field | Meaning / boundary |
|---|---|
| `training_step` | `TrainerState.global_step` at reward callback, with basis `trainer_global_step_at_reward_callback`. A skipped optimizer update can still advance this native coordinate; it is not a count of confirmed optimizer updates. Older captures retain their original basis and are not silently merged. |
| `batch_id` / `local_completion_index` | Capture-batch identity and local row; not a global generation clock or group repeat index |
| `policy_version` | Only an explicitly supplied sampler identity; never inferred from `global_step` |
| `split` | Explicit train/evaluation context; these populations remain separate |
| `training_inclusion` | `reward_scored_optimizer_use_unconfirmed`; capture does not prove loss inclusion, nonzero advantage or a parameter update |
| `outcome.reward` | One named reward function's returned component; `None` remains missing. It is not an inferred weighted total or normalized advantage |
| `capture_provenance` | Callback's original prompt/completion and exact returned completion token IDs |

Plain-text completions use `generation/1`; structured conversations use `chat-messages/1`. A raw text completion cannot reconstruct missing tool execution. Native tool IDs are used where present; absent IDs stay unlinked. The inspected TRL tool loop can emit tool response messages without call IDs, so source-linked response coverage is not guaranteed from this callback alone. Supply explicit tool schemas through `tools=` if they are available.

The prompt at this hook is the reward callback's prompt; this alone does not establish the exact tokenized/sampler input after any external truncation or custom rollout transformation. Capture inside the rollout backend when that distinction matters. Only selected task/sample columns enter metadata. Ground truths, user simulators and arbitrary reward kwargs are not placed in agent context. External async/vLLM sampling policy and learner clocks require explicit producer evidence.

## Validation

The opt-in native lineage adapter now also supports two to 32 reward columns with shared generated-sample identity. Use the [ordered multi-reward configuration](REWARD_RELATIONSHIPS.md#native-trl-multi-reward-capture), wrapping only the first function. The standalone reward hook above still captures one component; independently wrapping multiple functions does not establish a common sample join. Actual native DAPO and SAPO CPU controls exercise both reward aggregation modes with missing cells and unchanged capture-on/off training.

The contract suite covers synchronous/asynchronous reward functions, unchanged outputs, repeated samples, private-field exclusion, missing tool IDs, malformed rows, queue backpressure and restart identity. The actual runtime audit completes six optimizer steps and evaluation: 12 train and four evaluation completions, with identical tokens, rewards and final model parameters with capture enabled/disabled. All 16 travel through the actual HTTP collector; a lost acknowledgment and queue reopen produce no duplicate revisions. Automatic monitor means and all source receipts match native reward output. Train/evaluation labels, step-bin counts, source navigation and mobile layout are browser-checked.

Capture took 33.7 ms total across five callbacks / 16 tiny completions (about 2.1 ms per completion, including the audit's policy fingerprint). This is one small warm CPU control, **not** a production throughput estimate. Network delivery was deliberately offline during that training audit and resumed afterward. The subsequent [concurrent audit](../research/concurrent-training-2026-10-11/README.md) tests two independent native CPU trainers with live delivery, 328 completions, retry faults, worker queue reports and browser updates. These are separate models, not distributed gradient training. GPU jobs, vLLM synchronization, live tool environments, actual optimizer-use joins and semantic generalization require separate acceptance tests.
