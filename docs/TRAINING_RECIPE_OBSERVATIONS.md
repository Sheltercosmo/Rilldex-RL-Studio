# Training recipe observations

Implemented 12 October 2026: immutable recipe declarations, independent generation/use references, cohort and stream separation, and declaration-based measurement applicability. A subsequent [sampled-teacher increment](SAMPLED_TEACHER_SIGNALS.md) records prepared token signals. [Native policy-loss derivative observations](POLICY_GRADIENT_OBSERVATIONS.md) now add exact backward evidence and whole-rollout associations. Full-distribution teacher/critic tensors, intrinsic objective weights and semantic-token alignment remain pending. [Evidence and priorities](../research/modern-rl-recipes-2026-10-12/README.md) · [Conformance and transport controls](../research/recipe-context-2026-10-12/README.md).

## Capture contract

Use `POST /api/training-recipes`, `Outbox.log_recipes(experiment, recipes)`, or `training-recipes import file.json`. The packet has exactly `schema: "training-recipes/1"`, `producer`, `experiment`, and `recipes` (1–100 declarations). Read retained revisions with `GET /api/training-recipes?experiment=...` or `training-recipes view --experiment ...`.

Each declaration requires `id`, nonnegative integer `revision`, `label`, `implementation: {name, revision}`, `config_digest`, `basis`, `components_complete`, `components`, and `context`. The digest is the producer's recorded configuration identifier; the server does not reconstruct a native configuration from it. Each object is immutable at its producer/experiment/id/revision key. Replaying identical bytes after JSON normalization is idempotent; a conflicting value is rejected atomically. New revisions do not silently replace references to old revisions.

Each of 1–32 components requires a unique `id`, `label`, `supervision`, `credit: {kind, unit}`, and `objective: {definition, unit, weighting, reduction}`. An objective may additionally declare `probability_basis`. A component may identify a supervision provider using `provider: {producer, id, revision}`; provider revision is a string, such as a model version. Context may declare `phase`, `domain`, `effort`, `budget_definition`, `scheduling` and `trajectory_policy`. All descriptor strings are limited to 500 characters. Custom descriptor values are retained; they do not acquire interpretations from an acronym.

Optional `data.recipe: {producer, id, revision}` is accepted on both sample and use records in `training-records/1` and `/2`. References resolve within the record's experiment and can arrive before the declaration. Generation context is **never inherited** by a use. Old immutable samples/uses cannot be rewritten to attach guessed context. Generation cohorts split by reference; use streams additionally split by their own reference, producer and evidence stage.

```python
outbox.log_recipes(experiment, [native_manifest])
generation_ref = {"producer": outbox.producer,
                  "id": native_manifest["id"], "revision": native_manifest["revision"]}
# Use generation_ref in the new sample record's data.recipe.
# Independently record the actual update recipe in each use's data.recipe.
outbox.start()
```

The existing outbox bounds, retry, acknowledgment checks and restart identity apply. The training revision includes declaration arrivals, enabling existing live refresh. Saved training snapshots and exports retain exact referenced declarations, not a moving latest manifest. Missing references are explicitly `not_recorded` or `not_delivered`.

## Implemented applicability

The resolver recognizes supervision `reward`, `teacher`, `self_teacher`, `supervised`; credit kinds `group_relative`, `hierarchical_group_relative`, `cached_baseline`, `critic`, `return`, `token_distribution`, `direct`, `none`; credit units `sample`, `sequence`, `token`, `turn`, `vocabulary`; and weighting `hard_gate`, `capped`, `smooth`, `regression`, `none`. These are interpretation vocabularies, not the only accepted strings. Custom or partial declarations retain uncertainty.

Sample regression receipts can now capture predictions and targets against an exact regression component/definition. The scalar contract includes optional paired reward/baseline fields and preserves unavailable or incompatible coverage. [A*-PO producer and metric meanings](TRL_A2PO_CAPTURE.md). This does not supply token-level critic values or returns.

Each capability has independent `applicability` (`applicable`, `not_applicable`, `unknown`) and `state` (`captured`, `missing`, `not_applicable`, `unsupported`, `unknown`). An observed component can establish applicability even in a partial list. Absence establishes not-applicable only when the list is complete and the relevant component meanings are recognized.

Group contrast can be captured for complete scored group/component pairs. Scalar-advantage context can be captured for positive-mask use receipts when a declared credit estimator uses a sample/sequence scalar; it remains unattributed to individual objective components. Distributional teacher, critic and objective-exposure capabilities identify needed evidence but remain unsupported measurement operators. Prepared sampled-teacher streams have their own exact recipe/component/provider binding; they do not satisfy full-distribution coverage. No state means independently verified execution or confirmed learning.

Training health defaults to recorded use evidence for recipes without group-relative credit. It hides inapplicable group/advantage charts while preserving raw records in exports and explicit reward inspection. When both boundaries pin the same recipe, one combined card shows their context. Distinct or missing references stay separate. Existing records with unknown recipes retain descriptive views rather than inferred applicability.

## Purpose and evidence

Bind measurements to supervision and update mechanisms independently of framework names. Reuse the sample ledger, source snapshots, operators and investigations. Recipe components describe training machinery, not semantic activities.

The following broader model remains the architectural target; only the contract above is accepted by ingestion today.

| Object | Meanings to preserve |
|---|---|
| Recipe revision | Immutable producer/ID, native config hash, implementation revision, parent phase/branch; method name is descriptive |
| Objective component | Supervision provider, formula/version, coefficient schedule, credit estimator, ratio semantics, token/sequence/turn/vocabulary unit, reduction and gates; several components can coexist |
| Supervision reference | Reward definition or teacher/critic identity/revision; feedback source and teacher-visible context; fixed/EMA/other update schedule when captured |
| Generation segment | Behavior policy, sampler, time/step semantics, visible context and source mapping; several segments can belong to one episode |
| Training-use binding | Actual use/learner coordinate, component revision, tensors or bounded summaries with provenance, masks and transformed-input mapping; reuse has a distinct identity |
| Comparison context | Task/environment/evaluator/harness revisions, domain, effort, budget definition, modality, evaluation protocol and policy |

Unknown stays explicit. Producer-qualified definitions prevent acronym collisions. Scalar advantages and vocabulary-level supervision cannot share an untyped field. Preserve probability semantics: raw versus sampling-transformed distribution, actual behavior versus recomputed trainer, tokenizer, temperature/support and precision where relevant.

## Admission rules

1. The producer declares component semantics and implementation version. An operator checks retained evidence against its requirements. Presets suggest capture; they do not prove applicability.
2. Distinguish captured, missing, not-applicable and unsupported. Conflicting declarations are rejected; unresolved references remain unknown, never zero.
3. Combine components only under the native combination rule. Do not sum separately normalized losses or average incompatible KL estimators.
4. Measurements retain grain, population, coordinate, weighting, numerator/denominator, component version, unknown coverage and exact evidence. Split at material recipe changes unless intentionally comparing them.
5. A positive loss mask establishes eligibility only. Gates, capped weights, smooth coefficients, signed credit, accumulation and optimizer application are separate facts. None alone proves causal parameter influence.
6. Token-weighted semantic metrics require alignment. Packing, reuse, rewritten context, observations and unmapped spans stay explicit. Sequence weights may cover many units; prevent overlap double counting. Unknown annotations remain in coverage accounting.
7. Generated-token statistics cannot stand in for full-vocabulary or top-k distillation. Label partial diagnostics and retain support/tail semantics.

## Conformance cases

| Case | Required result |
|---|---|
| Teacher-only multi-turn OPD with zero reward and multiple samples per prompt | Teacher requirements apply; constant reward cannot establish absent supervision |
| Single-rollout actor-critic | Critic/actor clocks and token credit apply; no inferred group baseline |
| Group-relative scalar objective | Require native group membership/completeness; constant component does not prove constant combined objective |
| Detached capped, hard-gated and soft weights | Distinguish capped, zeroed and attenuated contributions; reconcile native coefficients |
| RL plus OPD in one update | Preserve both components and combination semantics |
| Partial rollout, rewritten/packed context | Retain segment/source/use mappings and policy/token identity |
| Changed teacher, effort, verifier or phase | Versioned changes visible; older measurements reproducible |
| Missing tensors, sampled-only ratios, unsupported modality | Limited scope and missing prerequisites visible; no full-gradient or full-KL claim |

## Delivery

Provenance and capability selection now have authored controls and HTTP/outbox validation. RL has priority over further distillation. Validate critic and async segments separately; native policy derivative controls are now available. Native tensor reconciliation, capture noninterference and independently checked semantic alignment precede behavior-specific update-exposure claims.

Training health now includes group/scalar-use diagnostics and prepared sampled-teacher streams. The latter have source-component validation, not a complete native OPD training run. The method guide does not enable critic, full-distribution teacher or behavior-aligned objective-weight measurements.
