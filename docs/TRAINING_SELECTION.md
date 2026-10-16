# Investigate what a training filter removes

**Saved investigations:** Use **Investigate this comparison** or **Investigate selected cases** to preserve the displayed evidence and return to it after rollout inspection. [Workflow, identities and limits](TRAINING_INVESTIGATIONS.md). Ordinary training URLs still reopen live data.

Implemented 11 October 2026. This extends the [training sample ledger](TRAINING_LINEAGE.md) and the [RL engineering framework](RL_ENGINEERING_FRAMEWORK.md). It compares existing observations with recorded selection decisions; it performs no new semantic inference.

## Engineering question

Does a particular training filter admit and reject samples with different observed behavior? Does that difference persist inside recorded prompt groups, or could the overall population mix explain it?

This needs the actual filter definition and decisions. For example, [verl's DAPO recipe](https://verl.readthedocs.io/en/latest/algo/dapo.html) documents removing groups with constant values of a selected metric and sampling additional groups. Consequently, generated and admitted populations can differ intentionally. That source motivates the question; it is not evidence that this tracker has executed or validated native verl filtering.

The earlier **Filter admitted** stage remains an observed union of admissions. It cannot answer what one specific filter removed. The new comparison selects exactly one producer, filter name and definition. Equal-looking names from different producers or definition versions are not silently combined.

## Use it

1. Open **Overview → Training samples** and select an experiment/environment.
2. Choose an existing behavior or source monitor, then a recorded filter.
3. Read admitted/rejected counts and measured coverage, the behavior curve on recorded sample coordinates, and the within-group comparison.
4. Click a decision count or chart point to inspect the exact samples. Open the pinned rollout measurement and the original training records.
5. Copy the page URL to reopen the live selection, or **Export evidence** to retain the current facts, monitor identities and comparison outputs. The URL follows latest records; it is not an immutable snapshot.

Any existing monitor can be selected, including recovery, feedback reference and recurrence measures. If the chosen observer has not processed a sample, its measurement remains missing. Training records do not synthesize a semantic graph or authorize inference. The retained native example currently measures response length; no semantic-quality conclusion is claimed from it.

## Grain, decisions and missingness

The unit is one declared sample. A reused sample or repeated agreeing filter decision is counted once. The source joins and monitor values are pinned through the existing ledger. Different split, environment/version and coordinate basis remain separate cohorts.

| State | Meaning for the selected producer/filter/definition |
| --- | --- |
| Admitted / Rejected | All latest recorded decisions agree on this value. This does not establish that every possible batch decision was captured. |
| Decision unknown | An explicit unknown remains among recorded batches, without contradictory known decisions. |
| Conflicting within batch | Different latest record identities disagree within one batch. Arrival order does not resolve the conflict. |
| Varies across batches | Known decisions include both admitted and rejected across different batches. Neither is chosen as the sample's single decision. |
| No decision recorded | No matching record exists. This is not rejection. |

Revisions of the same identity are resolved by greatest explicit revision, never arrival order. Conflict takes precedence over variation/unknown; variation takes precedence over unknown. Every underlying batch and record revision remains in the exported comparison inputs and sample evidence.

An admission does not establish actual backward or optimizer use. Evaluation samples can have a recorded filter decision while remaining evaluation samples. The existing training-stage counts stay available below the comparison.

## Aggregation and interpretation

The primary curve is the arithmetic mean of available per-sample rollout measurements, separated into admitted and rejected samples. Missing values do not become zero. Each point exposes measured/sample coverage and opens its contributing cases. No recorded coordinate means no invented training curve. A recorded bin with no available values breaks the line.

For opportunity-ratio monitors, the table additionally pools retained integer numerators/denominators and reports unknown opportunities. All-unknown rollouts still contribute their unknown count. Samples without a complete count contract are counted separately. Pooled opportunity rates and mean rollout rates are different quantities; the within-group comparison uses the latter.

The within-group result is the equal-weight mean of **admitted rollout mean minus rejected rollout mean** inside each recorded prompt group. A group contributes only when both sides have available measurements. Explicitly conflicting task/policy/step context excludes the group. Missing group IDs, groups without decision overlap, missing observations on one side and unrecorded context are reported.

Whole-group filters may have no admitted/rejected overlap inside any group. The matched result then remains unavailable, not zero. This feature does not manufacture matching groups or substitute different tasks. Missing task/policy context and incomplete group capture limit interpretation even when a contrast can be calculated. No expected group-size completeness or causal claim is implied.

The aggregate difference can disagree in sign with the within-group result. Neither should be read as behavior-specific training credit or an intervention effect. Examine coverage, group/task mix, budgets and the actual filter before proposing a training change.

## API and implementation

`GET /api/training-populations` now returns `selection_options`. Pass one option's exact `id` as `selection`, with the existing `experiment`, `environment` and `monitor` parameters. Unknown filter IDs fail explicitly. Each cohort receives a `selection_comparison`; samples retain `filter_decision` evidence. Existing requests without `selection` preserve their original stage meanings.

`training-selection-comparison/1` declares the current grouping and aggregation rules. Its content-derived ID covers results and contributing sample/monitor/decision identities. This is a pure projection of the existing ledger and monitor values, not another storage or inference engine. `view_revision` changes when late source joins or monitor materialization change even if the training-record revision stays constant.

Browser updates reuse the existing source, analysis and training event stream. Tests verify late decisions and late source/measurement arrivals without page reload or loss of the selected filter. Earlier collectors still display ordinary training stages and monitor comparisons; they do not gain filter comparison support merely by loading the updated static files.

## Evidence and limits

[Audit and retained outputs](../research/training-selection-2026-10-11/README.md) reconcile this projection against actual previously captured native TRL 1.13.0 CPU records. Additional authored controls cover conflicting/missing decisions, unequal group mix, pooling, source arrival and revision ordering. No new training run or model calls were performed.

Remaining work includes independent semantic validation, another native trainer's filter capture, group-level selection provenance/completeness, explicit configuration identities and production-scale querying. Filter identities are currently scoped to a record producer; cross-producer equivalence needs an explicit contract rather than name matching.
