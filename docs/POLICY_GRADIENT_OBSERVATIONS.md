# Observed policy-loss derivatives

`policy-gradient-observation/1` records a native loss derivative at generated
target log probabilities. It is an optional `data.policy_gradient` on immutable
`use` records in both training-record schemas. It requires the actual use's
`data.recipe`; generation settings are not inherited. Old use records stay valid.

Required fields: `schema`, `component`, `definition`, `tokenizer_id`, `input_digest`,
`probability_basis`, `normalization`, `target_tokens`, `loss_mask`, `d_loss_d_logp`.
Descriptor strings have the existing 500-character limit. Arrays must align,
contain 1–131072 targets, a binary mask and finite derivatives. If scalar
`model_tokens`/`loss_tokens` counts are supplied, they must agree with the arrays.
Optional [source alignment](TRAINING_UNIT_COVERAGE.md) connects each target to an
exact pinned source span or an explicit gap. Optional `normalization_context` retains up to 24 named finite numbers or bounded
strings. A declared component must resolve before measurements include its uses.

The measured quantity is **∂L/∂log π(target)** at the declared native boundary.
It includes that loss's reduction and backward scaling. It is not a parameter
gradient norm, an optimizer change, causal behavior credit, or an intrinsic
importance weight with advantage/reduction divided out. The sign convention is
for the loss being minimized. A zero derivative alone cannot establish its cause.
Exact zero uses no tolerance. Missing records, unresolved components, no eligible
tokens and zero derivatives are distinct. Off-mask nonzero derivatives are exposed.

Score-centering objectives can additionally involve non-sampled vocabulary
entries at the same prefix. This sampled-target contract does not observe those
paths and must not be presented as the full objective gradient or a drift
measurement. Native scalar correction logs are also not gradient norms. The
[research and capture proposal](../research/verifier-and-score-centering-2026-10-16/README.md#product-decision-observe-the-update-at-its-actual-use-boundary)
specifies separate support, correction and use-boundary evidence; that capture is
not implemented by this contract.

Training health reports zero-derivative token fraction, zero derivative among tokens
with nonzero recorded scalar advantage, and mean absolute derivative. Curves use
the receipt's learner coordinate. Backward and optimizer-confirmed streams remain
separate; optimizer receipts repeat the earlier backward observation, not a second
derivative measurement. Incompatible definition/probability/reduction/tokenizer
semantics suppress pooled values and curves. Raw cases remain exportable.

Saved behavior measures can be compared across uses with some nonzero derivative,
all eligible derivatives zero, no eligible tokens, and unavailable observations.
Each immutable source rollout contributes once per group. Sources present in both
zero and nonzero groups are counted explicitly. This is whole-rollout context, not
token-aligned semantic attribution. It reuses saved annotations without Jev calls.

## Native TRL path

```python
class ObservedTrainer(GRPOTrainingLineageMixin, GRPOTrainer):
    pass

trainer = ObservedTrainer(
    # Existing native trainer arguments and the wrapped reward function...
    training_capture=capture,
    confirm_optimizer_steps=True,
    capture_policy_gradients=True,
)
```

The option defaults to false. The current adapter is version-gated to TRL 1.13.0,
Torch 2.14.1, Transformers 5.19.0 and Accelerate 1.15.0 on the existing single-process
CPU path. It requires the native loss methods, no KL/entropy/router auxiliary loss,
no Liger kernel and no mixed precision. Tool and multimodal mappings are rejected.
Generation-token digests must match the training completion after native shuffle.
Unsupported paths fail setup or follow the existing capture error policy; they do
not acquire guessed gradients.

A read-only PyTorch tensor hook observes the derivative from the existing backward
call and returns `None`, preserving the original gradient. No copied loss, extra
forward or second backward runs. Hooks are removed after the step, including on
failure. Arrays are committed with a use only after native backward returns.
Observations are limited to 131072 positions per backward batch and retained
optimizer window, plus the existing 1000-use window limit. Budget failures omit
confirmation; they do not confirm a partial optimizer population.

Four native CPU configurations (DAPO reduction, CISPO, SAPO and sequence-ratio
clipping) matched an independent `retain_grad()` read and preserved generated
tokens, rewards, backward inputs, optimizer observations and final parameters.
Authored native-loss boundary controls independently check clipping, capping and
smooth derivatives. These are tiny-model controls, not production scaling or
semantic-accuracy validation. See the [audit](../research/policy-gradients-2026-10-12/README.md).

Token arrays and per-use provenance add storage and CPU work. This is an explicit
inspection option, not the default all-rollout capture policy. Materialized bounded
summaries, sampling coverage, and selective raw-token retention are required before
making this the normal large-training path. No production-overhead claim is made.
