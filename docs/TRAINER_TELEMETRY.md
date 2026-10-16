# Trainer metrics

Loss, entropy, KL, clipping, tokens and throughput appear in **Training overview → Trainer metrics**, next to rollout behavior. Pick a series to choose its trainer, objective, split, writer and session. Open **Definition & source** for the native key, unit and reduction. Click a point for its exact saved log identity. **Export values** downloads the current bounded view.

## Connect a running trainer

Start the collector with `rilldex start`. In your training process, create one persistent outbox for the process that owns the reduced logger output:

```python
from rilldex import Outbox, TrainerTelemetry

outbox = Outbox("trainer-outbox.sqlite", producer="run-a/learner",
                endpoint="http://127.0.0.1:8765")
outbox.start()
metrics = TrainerTelemetry(
    outbox, experiment="run-a", framework="verl",
    framework_version="your-installed-version", objective="gspo/config-v1",
    session="training-start-1",
)

# At the existing native logger call, after its distributed reduction:
# logger.log(data=native_metrics, step=global_steps)
metrics.log(native_metrics, step=global_steps)
```

The call only enqueues scalars locally. Delivery retries through the existing outbox. Keep the same outbox, producer and session when resuming the same training clock. Use a new session if the clock or cumulative token counter restarts. Use separate producers for independent learners or unreduced ranks; Rilldex does not average them. A logging failure raises to the caller, so applications can explicitly choose fail-fast or their own warning/retry policy.

### TRL GRPO and PPO

Use `framework="trl-grpo"` or `framework="trl-ppo"`, with the installed TRL version and actual objective/configuration identifier. Attach to the public Transformers logging callback:

```python
trainer.add_callback(metrics.transformers_callback())
trainer.train()
```

Create `metrics` with the matching TRL profile first. The callback captures only world rank zero and separates `eval_` keys from training logs. It does not request extra forward passes, enable entropy/KL computation, or change the trainer's logging frequency. A metric the trainer does not emit remains unavailable. TRL must already be installed in the training environment; the collector has no TRL dependency.

### Other trainers and inference servers

Use `framework="custom"` and supply definitions for your logger's exact keys:

```python
definitions = {
    "server/output_tokens_per_s": {
        "label": "Generated token throughput", "group": "throughput",
        "unit": "tokens / second", "reduction": "server interval rate",
        "definition": "Output tokens emitted by this server / interval seconds; prompt tokens excluded.",
    }
}
metrics = TrainerTelemetry(
    outbox, experiment="run-a", framework="custom", framework_version="server-v1",
    objective="generation/config-v1", session="server-start-1",
    clock="server_interval", population="this inference server",
    definitions=definitions,
)
metrics.log({"server/output_tokens_per_s": 1250.0}, step=42)
```

Groups: `loss`, `entropy`, `kl`, `clipping`, `tokens`, `throughput`, `other`. Unknown numeric keys are retained as unmapped native scalars and available in Python/exports. No guessed aliases or derived throughput are applied. Pass `environment=` only when the entire logged population belongs to that environment; mixed-environment batches should retain `unspecified` or an explicit mixture name.

## Link a trainer log to rollout evidence

When your trainer records individual training uses, attach their exact IDs to the log:

```python
metrics.log(native_metrics, step=global_steps, training_uses={
    "records": [{"producer": "learner-0", "id": "use-0042", "revision": 0}],
    "coverage": "partial",  # or complete when the producer records all log-context uses
    "basis": "Uses recorded by the learner for this logger emission",
})
```

The IDs refer to existing `kind="use"` records in the same experiment, through
either training-records version. Use receipts and sources may arrive later.
Click a trainer-curve point to open its linked rollout maps. A saved interval
investigation automatically retains logs referencing its selected use receipts,
including the native definitions, log identity and exact source links.

Source generation steps and learner steps do not need to match. A mixed batch
appears once with both interval labels; its aggregate is never split into invented
per-rollout losses. Link coverage is producer-declared log context, not validation
of a metric's denominator or individual sample influence. Unreferenced logs remain
available in Training overview. Stock TRL callbacks do not invent sample/use IDs.

```python
from rilldex import Workspace

ws = Workspace("study.sqlite", experiment="run-a")
context = ws.telemetry_evidence(producer="run-a/learner", record_id="saved-log-id")
print(context["run_ids"], context["unmatched_uses"])
```

For JSONL import, supply `step`, `split`, `metrics` and `training_uses` in each
linked row. An explicit split prevents applying a train batch's references to a
separate evaluation log. Unlinked version-1 packets remain supported; linked logs
use `trainer-telemetry/2` and require an updated collector. Reads and interval
capture use one database snapshot. New receipts only affect a newly captured
comparison; previous saved investigations stay unchanged.

## Existing logs and staged batches

Import a TRL `trainer_state.json` or JSONL objects with `step` and native keys. A JSONL object can also contain `{"step": 1, "metrics": {...}}`.

```sh
rilldex --db study.sqlite telemetry import trainer_state.json --framework trl-grpo --framework-version 1.15.0 --objective dapo-config-v1 --session training-start-1 --experiment run-a --producer run-a/learner
rilldex --db study.sqlite telemetry show --experiment run-a
```

Repeat the same import after another batch is written; unchanged log records are idempotent. An incomplete final JSONL line is left for the next import. Malformed completed lines raise an error. For continuous delivery use the SDK/outbox above. `--definitions metrics.json` adds or overrides native definitions; a changed definition becomes a separate series.

Offline workers can use the existing `rilldex capture export` / `capture import` bundle route. Local analysis without a server can pass `tracker.store.Store("study.sqlite")` as the telemetry target, together with an explicit `producer=`.

## Analyze with Python and SQL

```python
from rilldex import Workspace

ws = Workspace("study.sqlite", experiment="run-a")
logs = ws.telemetry(limit=10000)  # rows include decoded `record.metrics`
loss = ws.sql("""
    SELECT step, session, json_extract(record_json, '$.metrics.loss.value') AS loss
    FROM trainer_telemetry
    WHERE framework = 'trl-grpo' AND split = 'train'
    ORDER BY session, step
""", limit=10000)
```

`GET /api/trainer-telemetry?experiment=run-a` returns the chart series. `POST /api/trainer-telemetry` accepts the versioned packet produced by `tracker.trainer_telemetry.packet()`. SQL and standard analysis exports expose the complete retained logs; the dashboard reads the latest 1,000 logs and up to 64 distinct series, displaying any truncation.

## Definitions and coverage

| Profile | Native families | Distinctions preserved |
| --- | --- | --- |
| TRL GRPO | Loss, token entropy, reference KL, clipping region/bounds, cumulative tokens, completion length, trainer-reported rates | Objective clipping versus completion truncation; cumulative count versus rate |
| TRL PPO | Policy/value loss, sampled sequence entropy, policy entropy, reference/update KL, policy/value clipping, episode rate | Sequence sum versus token mean; reference KL versus update KL; actor versus critic |
| verl | Actor/critic loss, actor entropy, reference KL loss/update KL, policy clipping, batch token count, response length, step duration, throughput | Objective-specific reductions; tokens per second **per GPU** versus total throughput |
| Custom | Explicit key definitions, any declared clock/population | Server, worker, learner, objective and restart boundaries |

Definitions are based on [TRL logging](https://huggingface.co/docs/trl/main/logging), [TRL GRPO source](https://github.com/huggingface/trl/blob/main/trl/trainer/grpo_trainer.py), [verl metric computation](https://github.com/verl-project/verl/blob/main/verl/trainer/ppo/metric_utils.py) and [verl objective implementations](https://github.com/verl-project/verl/blob/main/verl/trainer/ppo/core_algos.py). Pin the version and actual objective in each stream; override a definition if your fork changes it.

Missing, non-finite and conflicting points stay gaps. Each curve shows finite values / observed log coordinates, not expected logging coverage or rollout coverage. No generic clipping or entropy health threshold is imposed. These aggregate logs do not establish which individual samples or units contributed to an update; use training-use receipts for that join.
