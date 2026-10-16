# A*-PO training capture

This opt-in adapter follows the native **TRL A2POTrainer**. It records the reference-sampling stage separately from on-policy sample regression. A*-PO is an RL objective using a cached reward baseline; its frozen reference policy is not treated as a distillation teacher.

**Validated boundary:** TRL 1.13.0, Transformers 5.19.0, Accelerate 1.15.0, Torch 2.14.1; single-process FP32 CPU, native AdamW, plain-text prompts. Other package versions, accelerator modes and optimizers are rejected. GPU/distributed execution, checkpoint resume, conversational inputs, custom trainer overrides and production-scale overhead are unvalidated. This is a second native TRL trainer, not a second training framework. [Native execution audit](../research/a2po-native-2026-10-12/README.md).

## Connect

```python
from trl.experimental.a2po import A2POTrainer
from tracker.capture import Outbox
from tracker.trl_a2po_capture import A2POCaptureMixin

class ObservedA2PO(A2POCaptureMixin, A2POTrainer):
    pass

outbox = Outbox(
    "a2po-worker.sqlite",
    producer="my-a2po-run/worker-0",
    endpoint="http://127.0.0.1:8810",
).start(report_status=True)

trainer = ObservedA2PO(
    training_outbox=outbox,
    experiment="my-a2po-run",
    reward_definition="my-combined-reward/v1",
    model=model,
    args=training_args,  # Native effective A2POConfig, with use_cpu=True
    train_dataset=dataset,
    processing_class=tokenizer,
    reward_funcs=reward_function,
)
trainer.train()
print(trainer.capture_counts)
print(outbox.status())
outbox.close()  # Stops delivery; pending durable records are retained.
```

Use your tracker's actual loopback endpoint. The capture contract is strict: capture failure stops this opt-in run rather than silently dropping a training-use record. It invokes no extra model, reward or generation calls. It observes native loss inputs and completed backward calls; a separate native optimizer callback confirms non-skipped AdamW application. That confirmation establishes batch membership, not a causal per-sample parameter effect.

The adapter registers effective settings automatically. To inspect settings without attaching capture:

```python
from tracker.training_setup import prepare, inspect
request = prepare("trl", training_args, trainer="a2po",
                  version="1.13.0", resolved=True)
report = inspect(request)
```

The allowlist excludes private or unrelated arguments. Unknown versions and incomplete settings require review. This reader describes selected settings, not complete native configuration validation. Changing these settings inside a captured trainer is rejected: a new reference cache needs a new trainer context.

## Read the dashboard

Select the experiment in **Overview → Training health**, leaving **View → Automatic**. Compatible recorded predictions and targets select **Training use**. The chart shows **Prediction error over training** and opens exact sample receipts. The training-record selector separates **backward completed** from **optimizer step completed**. Settings and raw identifiers expand in place; manual view choices remain available.

For the pinned native implementation:

- Prediction: `beta2 * (policy sequence log-probability - reference sequence log-probability)`.
- Target: `native combined reward - cached V*`.
- Displayed MSE: mean squared prediction-minus-target over eligible recorded sample uses in that evidence stage. Reused samples count again. Different component/definition identities are not pooled.
- Baseline and reward remain separate recorded fields. This mean is not automatically the trainer's accumulated, scaled or total loss.
- The horizontal coordinate is the recorded learner step. Source generation retains its own trainer-step-at-generation basis; arrival order is not a training clock.

Reference sampling traverses both native training and evaluation datasets without a split argument at the captured reward hook. Those completions are retained as raw reference rollouts, without invented train/evaluation declarations or optimizer uses. The final native cache is exposed in `trainer.capture_baseline`; per-use baseline values are durable. Complete reference-sample-to-cache membership and native filter-decision records are still pending. Cache keys follow native rendered prompt text, including duplicate-key overwrites.

The standard sample/use/recipe contracts remain reusable by other producers. The optional `data.regression` field uses `sample-regression/1`, requiring `component`, versioned `definition`, finite `prediction` and `target`. Optional `baseline` and `reward` must be supplied together. Bind it to an exact recipe component with `objective.weighting="regression"`; missing or incompatible bindings remain unavailable. This scalar contract does not stand in for token-level critic values and returns.

Primary references: [A*-PO paper](https://arxiv.org/abs/2505.20686), [pinned TRL documentation](https://huggingface.co/docs/trl/v1.13.0/en/a2po_trainer), [native trainer source](https://github.com/huggingface/trl/blob/v1.13.0/trl/experimental/a2po/a2po_trainer.py).
