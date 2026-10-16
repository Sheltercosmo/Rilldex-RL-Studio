# Training health

Open Overview → Training health (`/?view=health`). API: `GET /api/training-health?experiment=...&environment=...&monitor=...`.

This read-only view reuses latest retained training records and saved monitor observations. It invokes neither annotation nor training. [Research and rationale](../research/learning-signal-2026-10-12/README.md).

**Scope:** recorded rewards, group variation, training use, policy age, native policy-loss derivatives and sample regression predictions/targets, connected to saved behavior evidence. Positive masks do not account for objective gates or smooth weights. [Recipe declarations](TRAINING_RECIPE_OBSERVATIONS.md) preserve generation/use context separately and identify missing or unsupported evidence. Aligned value/return observations are supported through a generic contract; full native critic hooks and complete objective-weight capture remain pending. Applicability follows producer declarations and versioned readers, not inferred method names or independently verified execution. Existing [teacher observations](SAMPLED_TEACHER_SIGNALS.md) remain accessible when captured; they do not displace RL rewards in Automatic mode.

**Automatic view:** `training-dashboard/4` in the `training-health/14` response chooses from the selected population's evidence. A selected behavior question comes first, followed by explicit recovery lineage, usable policy-gradient/policy-age/regression evidence, learner-specific credit or sampling checks, then recorded rewards and remaining training use. It identifies the exact use stream and explains the choice. It does not infer learner settings from generation settings or use an unverified config to establish a method-specific default. Manual views persist; **Use automatic view** restores the default. [Validation and limits](../research/method-aware-dashboard-2026-10-12/README.md).

**Prediction and target:** compatible sample-regression receipts show mean squared prediction error at each recorded learner step, with cached baseline/reward where present. The exact training-use component and definition control pooling. Chart points open the samples and raw identifiers expand separately. [A*-PO native capture and measurement boundaries](TRL_A2PO_CAPTURE.md).

## Capture and populations

Use the existing [training-record API](TRAINING_LINEAGE.md). Sample declarations optionally accept `group_size`, a positive integer expected membership requiring `group_id`. Emit it from native grouping, not the number of rows observed by the collector. Existing declarations are immutable; do not rewrite historical facts. The pinned TRL mixin emits it for new samples.

Cohorts separate experiment, train/evaluation, environment/version, generation clock, recipe reference and sample identity schema. Components separate scoring producer, component and definition; use streams separate producer, stage and learner recipe reference. Record a new immutable recipe when effective settings change and attach it at the relevant generation/use boundary. Missing references stay unknown. Pinned native-settings readers select monitoring priorities; method identity is never guessed from trajectory text or a framework name alone.

| Measurement | Numerator / statistic | Denominator / exclusions |
|---|---|---|
| Mean component reward | Mean latest scored values | One unambiguous value per sample; missing/unavailable/error/conflicting excluded |
| Groups with no contrast | Complete groups with exactly equal component values | Expected size known and satisfied; ≥2 samples; consistent task/policy/step; complete scores; ambiguous independent producer namespaces excluded |
| Samples in constant groups | Samples in those constant groups | Samples in eligible complete groups |
| Uses with trainable tokens | Receipts with `loss_tokens > 0` | Stage/producer receipts with recorded mask counts |
| Zero recorded advantage | Positive-mask uses with scalar `advantage == 0` | Positive-mask uses with native scalar advantages |
| Tokens included in loss | Sum `loss_tokens` | Sum `model_tokens` over paired counts; reuse counts again; zero denominator unavailable |
| Filter admission | Consistently admitted samples | Consistently admitted/rejected for named filter; unknown/conflicting/batch-varying/missing excluded |
| Behavior by advantage sign | Mean saved monitor value in positive-mask uses of each sign | Each bound source once per sign; expose measurement gaps, unbound samples, monitor scope and sign overlap |

These are observations, not verdicts. Constant components can coexist with contrast elsewhere. Positive masks or nonzero scalar advantages do not prove nonzero gradients. A use receipt is not an optimizer-step count. Whole-source behavior does not describe only trained tokens.

Reward points use `sample.step`/`step_basis`; use points use `use.learner_step`. Generation callback clocks are not relabeled as update clocks. Evaluation samples do not acquire training-use zeros. No policy lag or wall clock is inferred from arrival or checkpoint strings.

## Evidence and updates

Chart points/group rows open evidence dialogs. Source links use immutable run IDs. Population exports retain the selected cohort and definitions; case exports pin the snapshot at dialog open. Ratios expose counts; unavailable points remain absent.

Refresh follows retained training/source/analysis revisions. This reflects received evidence, not proof of producer freshness. Large-run query costs and distributed adapters need further validation; this implementation materializes scoped records.

**Value predictions and returns:** bound observations automatically open position-weighted error, signed bias and explained variance curves. Roles and token/turn/state units form separate selectable series. Within-sample variation is an inspection aid, not an automatic flattening verdict. [Capture, formulas and limits](VALUE_OBSERVATIONS.md).

**Retained batch signals:** supported Slime imports automatically expose native learning-signal arrays at their rollout-batch coordinates. Summaries and case arrays remain separate from confirmed training-use measurements. The reader cannot establish an absent estimator or value-model version. [Import workflow](SLIME_DEBUG_IMPORT.md).

**Reward relationships:** paired component correlations now use the same captured samples, with complete native groups separated from overall task-mix variation. Verified multi-reward settings select this view automatically. The native TRL adapter captures ordered reward-matrix columns under both aggregation modes without extra reward calls. [Definitions, capture and boundaries](REWARD_RELATIONSHIPS.md).
