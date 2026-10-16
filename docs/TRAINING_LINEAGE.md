# Training sample records and population comparison

Implemented 11 October 2026. This is the first part of the [RL engineering framework](RL_ENGINEERING_FRAMEWORK.md), with a generic fact contract and a narrowly tested native TRL adapter. It does not complete the framework's optimizer, distributed-training or semantic-accuracy gates.

## Research workflow

**Named-filter investigation is now available:** select one producer/filter/definition to compare admitted, rejected and unresolved samples, behavior curves, and within-recorded-group differences. This supplements the union-of-admissions stage below. [Definitions, live updates and limits](TRAINING_SELECTION.md).

Open **Overview → Training samples** in an updated collector. Select an experiment and an existing monitor. The view compares the monitor's measured rollout values across recorded generation, scoring, filter admission and training-use populations. Select a count or a chart point to inspect the contributing samples, source rollout and training evidence.

Native facts are stored separately from the source trajectory and its behavior graph. Late scores and repeated uses therefore do not create new rollouts or require rewriting/re-annotating a source. Monitor joins use the explicitly pinned source revision. An unavailable semantic monitor remains unavailable; the training adapter does not generate semantic observations.

Counts are observed membership, not a funnel or conversion rate:

- **Generated:** an explicit sample declaration exists.
- **Scored:** at least one latest component-score record has a numeric value. This is not a verified weighted total.
- **Filter admitted:** at least one latest named selection record admits the sample. The underlying filter, definition, batch and reason remain inspectable. This is not “passed every filter.”
- **Backward visited:** a producer records a completed backward use. A sample is counted once even if reused.
- **Backward · positive mask:** at least one completed backward use reports a positive token-mask count. In the native TRL adapter this is the completion mask, not a proof of nonzero final loss, gradient or parameter effect.
- **Optimizer recorded:** a producer explicitly records an optimizer-stage use. The TRL adapter can now emit this with the additional opt-in and runtime gate below. This establishes sample membership in a completed update, not a nonzero gradient or per-sample parameter effect.

No record means unknown. Unsupported stages display a dash and do not produce a zero-valued curve. A recorded zero mask is distinguishable from an absent mask record. Counts expose missing groups, source joins, selection records and use records. Different experiment, split, environment/version and clock bases stay in separate cohorts. Chart positions use the sample's recorded coordinate, including later evidence about its use; they are not the time of that later use.

Stage comparisons use an arithmetic mean of available per-rollout monitor values. Named-filter and cross-metric comparisons additionally show pooled opportunity counts when the monitor supports them. Repeated training uses do not add sample weight. V2 comparisons deduplicate source-rollout behavior weight separately from sample membership. Each population shows measured/eligible counts, with missing values excluded and visible. Task mix, filtering and missing observations can explain differences; this view does not infer causal behavior credit.

## Portable record contract

The following example describes the legacy one-sample-per-rollout v1 contract. For multiple samples per episode, use [training-records/2](INDEPENDENT_TRAINING_SAMPLES.md); it preserves independent identities and deduplicates whole-source behavior weight. Existing v1 receipts and producers are unchanged.

Use `Outbox.log_training(experiment, records)` for durable delivery, `POST /api/training-records` for direct delivery, or `training-records import` for retained JSON. Existing outbox retry, capacity, error reporting and replay apply. Queue counters now count queued messages, which can be source snapshots or training fact packets.

Samples and uses optionally pin an independent `data.recipe` reference in either schema. [Recipe declarations](TRAINING_RECIPE_OBSERVATIONS.md) arrive through the same durable outbox. Generation cohorts split by recipe reference; the Learning signal view also separates use recipes. Saved snapshots retain the declarations available at save time. Existing records remain valid with unknown recipe context.

```python
from tracker.capture import Outbox

outbox = Outbox("worker.sqlite", producer="experiment-a/worker-0")
sample = {"producer": "experiment-a/worker-0", "rollout_id": "generation-42/sample-3"}
outbox.log_training("experiment-a", [{
    "id": "sample/generation-42/sample-3",
    "revision": 0,
    "kind": "sample",
    "sample": sample,
    "evidence": {
        "basis": "native generator record",
        "source_revision": 0,
    },
    "data": {
        "split": "train",
        "task_id": "task-7",
        "group_id": "generation-42/prompt-group-2",
        "policy_version": "producer-recorded-policy-version",
        "step": 42,
        "step_basis": "producer's explicitly defined generation coordinate",
    },
}])
```

The values above illustrate the contract; obtain actual identities and clocks from the producer. A group ID identifies a particular group within an experiment, including across workers. Do not construct it from task text, fixed assumed group width, or a worker-local integer reused for different groups. Group counts report observed groups, not completeness against an expected group size.

Sources are delivered separately with the referenced producer/rollout identity and revision. A missing revision remains unresolved; it does not fall back to the newest source. Explicitly conflicting source/record experiment metadata prevents the join. Source metadata may omit experiment identity when the training declaration supplies it. Changing rollout text later does not move an existing pinned measurement.

Every record requires `id`, `revision`, `kind`, `sample`, `evidence` and `data`. Identity is scoped by packet producer and experiment. Producer record identities must remain stable across transport retries. Packet schema is:

```json
{"schema":"training-records/1","producer":"worker-0","experiment":"experiment-a","records":[]}
```

Replace the illustrative empty list with 1–1,000 records. Packets are validated and committed atomically; transport retries return the exact packet identity. Conflicting record identity fails the packet. Score/selection revisions may arrive out of order; the greatest explicit revision wins, while older records remain stored. A record's sample, kind and component/filter definition cannot change across its revisions. Use a new identity for a new definition.

| Kind | Required data | Optional data / interpretation |
| --- | --- | --- |
| `sample` | `split`: `train` or `evaluation` | `task_id`, `group_id`, `policy_version`, `environment`, `environment_version`; `step` and `step_basis` must appear together. Immutable revision zero. |
| `score` | `component`, `definition`, `status`, `value` | Status is `scored`, `unavailable` or `error`. Only scored records have finite numeric values; the other statuses require null. Component scores remain separate. |
| `selection` | `filter`, `definition`, `batch_id`, `decision` | Decision is `admitted`, `rejected` or `unknown`; optional `reason`. Different filters/batches remain different records. |
| `use` | `batch_id`, `learner_step`, `stage` | Stage is `backward_completed` or `optimizer_step_completed`; optional native `advantage`, `model_tokens`, `loss_tokens`. The evidence basis must state what mask the token count represents. Immutable revision zero. |

`use` records are stage-specific evidence events, not automatically counts of optimizer updates. In particular, a backward record and an optimizer record must not be added together as two optimizer uses. The UI counts unique samples and separately exposes the number of evidence records.

The `evidence.basis` describes the producer hook/meaning. Optional `source_revision` enables the exact source join on a sample declaration. Records are producer assertions; the collector's schema validation does not independently certify that a model call or optimizer update occurred. Multiple sample declarations for the same identity are reported as conflicting rather than resolved by arrival order.

```powershell
python -m rilldex --db .tracker/tracker.sqlite training-records import retained-packet.json
python -m rilldex --db .tracker/tracker.sqlite training-records view --experiment experiment-a
python -m rilldex outbox worker.sqlite --producer experiment-a/worker-0 --send
```

`GET /api/training-populations` accepts `experiment`, `environment` and an existing `monitor` ID. It returns cohorts, step bins, measured coverage, samples and retained latest-record evidence. The UI's export preserves these joins and monitor identity. Historical record revisions remain in SQLite; the population endpoint selects their latest versions.

## Optional native TRL adapter

The ordinary [GRPO reward capture](TRL_CAPTURE.md) stays dependency-free and retains no additional batch after capture by default. To observe downstream use, opt into the version-gated mixin:

```python
from trl import GRPOTrainer
from tracker.trl_lineage import GRPOTrainingLineageMixin

class ObservedTrainer(GRPOTrainingLineageMixin, GRPOTrainer):
    pass

trainer = ObservedTrainer(
    training_capture=capture,  # the GRPOCapture instance
    confirm_optimizer_steps=True,  # optional; requires the additional pinned runtime below
    reward_funcs=capture.wrap_reward(my_reward_function),
    model=model, args=training_args,
    train_dataset=dataset, processing_class=tokenizer,
)
trainer.train()
```

Compatibility is intentionally narrow: TRL **1.13.0**, single-process CPU, one wrapped reward function, no tools, custom rollout or vLLM, at most 256 local completions. It uses private trainer boundaries. Other versions/modes must be inspected and validated before changing the gate. Existing reward-only integration does not gain these claims automatically.

The mixin records actual single-process grouping before the native shuffle. Sample identities move through TRL's shuffle/split/reuse alongside the tensors. Tracker-only fields are removed before loss computation without mutating the reusable buffer. The adapter emits a use record only after native `training_step` returns from backward. This handles identical completions without text-based matching.

Native truncation masking is captured as a named selection, separate from the reward. In adapter `/2`, `learner_step` is the trainer update index **before** increment; the native trainer can increment this coordinate even when an optimizer update is skipped. Gradient accumulation can create several backward records at one coordinate. Backward-only capture remains the default and does not confirm a subsequent optimizer update. Group normalization, returned advantages, token order and training results are not recomputed by the tracker.

### Confirm optimizer membership

`confirm_optimizer_steps=True` additionally requires Transformers **5.19.0**, Accelerate **1.15.0**, Torch **2.14.1**, and native `adamw_torch`, within the same TRL/CPU constraints. The callback accepts only native AcceleratedOptimizer wrapping Torch AdamW. Custom optimizers and untested dependency versions fail setup or capture explicitly; inspect and validate their execution before widening the gate.

The adapter retains scalar backward receipts through gradient accumulation, then emits matching `optimizer_step_completed` records only after `on_optimizer_step` and a non-skipped, synchronized optimizer call. Each optimizer receipt keeps the original sample, batch, learner coordinate, advantage and completion-mask count. Its ID is the backward receipt ID plus `/optimizer`; its evidence names that receipt. Evaluation emits neither stage. Reused samples keep their identities; each use remains a separate event. No nonzero loss or parameter contribution is inferred from a positive completion mask.

The pending window is capped at 1,000 sample uses; exceeding it invalidates confirmation for the whole window and follows the configured error policy. Missing identities, failed backward capture and mismatched update coordinates cannot create a partial window that looks complete. A skipped step clears its pending window. Interrupted training and later `train()` calls cannot reuse old pending receipts; each call uses a fresh capture session. These receipts are not persisted as pending optimizer facts before completion. A crash between an optimizer update and durable capture can leave missing confirmation, which stays unknown.

Capture status exposes optimizer callback, skipped-update and recorded sample-use counters. The population view separates backward and optimizer evidence counts; do not add them as independent uses. Curves continue to group unique samples by their recorded generation coordinate, including later use evidence. They are not learner-update-weighted curves.

Capture errors follow the supplied `warn`/`raise` policy; missing facts stay visible. The source queue can succeed before a later fact packet fails, so partial capture must not be treated as complete negative evidence. Mixin lineage work is additional to the public reward hook's `capture_seconds` counter; whole-run timings in the audit are the available end-to-end control, not a production overhead estimate.

## Learning-signal diagnostics

The [Learning signal view](TRAINING_HEALTH.md) derives component/group contrast and native-use measurements from these records. New sample declarations may include `group_size` (positive expected membership, requiring `group_id`). The pinned TRL adapter records its native group size. Historical immutable samples without this field remain unclassified for complete-group ratios.

## Evidence and next gates

The [native and transport audit](../research/training-lineage-2026-10-11/README.md) includes capture-on/off equality, repeated use, native truncation masking, an independent read of prepared tensors, lost-ack HTTP recovery and live browser updates. It uses an authored tiny task/model and makes no semantic-quality claim.

[Optimizer-use audit](../research/optimizer-use-2026-10-11/README.md) verifies six actual AdamW calls against an independent Torch post-step hook, all 24 sample-use joins, capture-on/off parameter/token equality, HTTP retry and the population UI. Authored controls cover skipped/failed/incomplete windows; they do not claim native GPU overflow validation.

Remaining gates: another structurally different native trainer adapter, GPU/distributed runs, generation segments spanning policy versions, configuration/reward aggregation lineage, expected group completeness outside the pinned TRL adapter, producer event-time/staleness and deployment-scale queries. Independent semantic accuracy and reusable cross-domain feedback/recovery operations remain separate work. These are the unfinished parts of the broader plan, not implied by successful transport or one native integration.

## Prepared supervision

Independent records also accept immutable `kind: supervision` at `stage: prepared` for [sampled teacher signals](SAMPLED_TEACHER_SIGNALS.md). These observations join by exact sample identity and recipe/component/provider, use their own preparation coordinate, and never set backward/optimizer membership. Source mappings and training-use receipts remain independent.
