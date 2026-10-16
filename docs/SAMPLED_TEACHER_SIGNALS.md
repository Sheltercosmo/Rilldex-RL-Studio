# Prepared sampled-teacher observations

Implemented 12 October 2026. This is a sampled-token diagnostic for OPD-like preparation, independent of framework and separate from evidence of training use. It does not cover full-vocabulary or top-k distillation, critic values, objective coefficients, or behavior-token alignment. [Pinned source-component audit](../research/tinker-opd-boundary-2026-10-12/README.md).

## Capture and identity

Use the existing `POST /api/training-records` or `Outbox.log_training(experiment, records, schema="training-records/2")`. The new immutable `supervision` record references an independent sample and may arrive before its declaration. Its revision must be zero; replay is idempotent, changed content conflicts. Record every distinct preparation with its own producer-stable ID. Retries reuse that ID; recomputation is a new observation. This is not a score, selection decision or training-use receipt.

The record has the usual `id`, `revision`, `sample`, `evidence`, and `kind: "supervision"`. Its `data` fields are exactly:

| Field | Meaning |
|---|---|
| `recipe` | Exact `{producer, id, revision}` of the preparation recipe; independent of sample-generation and use recipes |
| `component` | Component ID in that declaration |
| `stage` | Currently only `prepared` |
| `boundary` | Producer-described capture boundary |
| `step`, `step_basis` | Nonnegative native preparation coordinate and its meaning; not import order or inferred learner progress |
| `signal` | The `sampled-teacher-signal/1` object below |

The signal requires a teacher `provider: {producer, id, revision}` (revision is a string), `student_policy`, `tokenizer_id`, `probability_basis: {student, teacher}`, and `context: {student_digest, teacher_digest, definition}`. The digests identify producer-recorded inputs; they are not themselves retained teacher context or proof that two renderers are equivalent. Probability bases must describe what the producer actually supplied, including sampling transforms when applicable. The server cannot infer them from an algorithm acronym.

Also required are finite nonnegative `coefficient`, `discount` in [0,1], and equal-length arrays `target_tokens`, `mask`, `student_logprobs`, `teacher_logprobs`, `advantage_delta`. Arrays contain 1–131,072 target positions, with nonnegative integer token IDs and binary integer masks. Log probabilities are finite and nonpositive on selected positions; masked positions may be null. Native advantage deltas are finite at every position, including masked ones. All arrays align with **prediction targets**, not the corresponding preceding input positions. Preserve the actual component delta; do not substitute total advantage or reconstruct it from a guessed loss.

Only a matching component and provider revision establish declaration binding. Missing declarations, wrong component kinds, missing providers and provider conflicts remain explicit. Raw diagnostics are still inspectable; they are not relabeled as reconciled evidence. Schema validation proves structure, not producer truth.

## Measurements and presentation

Learning signal → **Inspect prepared teacher signal** provides:

* Mean sampled log ratio: sum of `student_logprob − teacher_logprob` over selected positions divided by their count. Negative values are possible. This is not full-distribution KL or independent task quality.
* Positive, negative and exact-zero native teacher delta fractions among selected positions. Discounted deltas can differ from local log-ratio signs. These are prepared additions, not final gradient attribution.
* Nonzero deltas outside the selection mask, divided by masked positions. Inspect the native discount and downstream loss before treating this as a defect.
* Selected-token share, observation/sample counts, missing observations in the selected stream, and exact-case drill-down/export.

Curves use the recorded **preparation** coordinate. Streams split by producer, recipe/component, teacher revision, tokenizer, probability definitions, context transformation definition, boundary, coordinate basis, coefficient and discount. Student policy and context digests remain on each observation so they can change over the run. Repeated preparations count again; the denominator is observed tokens, not unique rollouts. Zero eligible tokens yield a missing value. A missing observation does not establish absent supervision or non-use. Preparation does not set backward/optimizer flags. `training-health/3` exports these streams and their exact records.

Teacher-only populations with captured signals open this view by default. Other recipes retain their existing defaults; any population can explicitly inspect teacher records. A source link appears only when its sample has a valid bound source. No Jev or LLM call occurs.

## Experimental Tinker adapter

`tracker.tinker_capture.prepared_record` consumes already-computed native values at cookbook commit `70767c738ba5f523b66210a70e50b0dc14c9fc1a`. It does not install a hook, call a teacher, rewrite tensors or enqueue automatically. It accepts text-only datums and rejects other revisions, mismatched target shifts, changed teacher rendering, nonbinary masks and misaligned teacher responses.

In an explicitly instrumented `incorporate_kl_penalty`, collect after its optional discount and native advantage update, while `kl_advantages`, the teacher response and full input are still available:

```python
from tracker.tinker_capture import prepared_record, UPSTREAM_COMMIT

pending.append(prepared_record(
    record_id=actual_preparation_id, sample=actual_sample_reference,
    datum=datum, teacher_input=full_sequence_inputs_D[i],
    teacher_logprobs=teacher_logprobs_D[i],
    native_advantage_delta=kl_advantages,
    provider=actual_teacher_reference, student_policy=actual_student_policy,
    tokenizer_id=actual_tokenizer_revision,
    probability_basis=actual_probability_definitions,
    recipe=actual_recipe_reference, component=actual_component_id,
    step=actual_preparation_step, step_basis=actual_step_definition,
    coefficient=kl_penalty_coef, discount=kl_discount_factor,
    upstream_commit=UPSTREAM_COMMIT,
))
# Once outside the inner loop, using an existing configured durable outbox:
outbox.log_training(experiment, pending, schema="training-records/2")
```

The caller must retain datum-to-trajectory metadata before `prepare_minibatch` discards it. A rewritten trajectory can produce multiple datums; a datum index alone is not a globally stable sample identity. Declare each sample, preserve episode/source bindings, and pass its actual teacher routing and preparation identity. The adapter removes only the teacher response's leading context-position probability and verifies text target alignment. It records identical full-token context digests for this pinned recipe. This mapping does not support multimodal inputs or independently rendered teacher prompts.

Full arrays require an explicit capture policy, such as bounded diagnostic batches. CPU copies, storage and payload sizes scale with captured tokens. Production overhead is unmeasured. This contract cannot retroactively enrich an immutable observation or reconstruct historical teacher values.

The retained controls execute selected upstream functions with real Tinker SDK and Torch but authored trajectories and teacher responses. They verify arithmetic, masking, splitting and capture noninterference at that boundary. Ordinary cookbook import, Harbor sandbox execution, actual model scoring/backward/optimizer integration, reconnect behavior during training, and production-scale overhead remain unverified. No cloud execution or model credentials were used.
