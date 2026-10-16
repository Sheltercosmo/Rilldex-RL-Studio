# Compare behavior measures on a fixed training population

Implemented 11 October 2026. This extends [saved training investigations](TRAINING_INVESTIGATIONS.md). It compares existing source, graph and analysis monitors without new inference or an environment-specific metric routing list.

## Workflow

Open a saved training investigation and expand **Choose populations and measures**. Select one saved cohort, optionally one recorded coordinate, a focus population, a reference population and up to eight existing monitors. Populations may be named filter decisions or recorded training stages. Use **Preview comparison**, review coverage and matching, then **Save comparison & inspect cases**.

Investigations created from **Reward relationships** also offer saved reward patterns: above/below each raw component's complete-group mean, ties, or unavailable group comparison. These selectors apply only to their original saved reward cohort. Group baselines are frozen before selecting a coordinate or focus/reference subset. Changing to another cohort resets the selectors to recorded stages. The result retains score evidence alongside each case and reuses the same monitor arithmetic and coverage rules. Independent training samples retain their separate identities, while their behavior summaries weight unique bound source rollouts within each population.

The saved population remains fixed. Its original monitor values stay pinned; additional monitors use currently saved observations bound to those same source identities. Adding a monitor does not deliver missing sources, run an observer or update training records. Once saved, those additional values and their absence states are pinned too. A subsequent hypothesis revision retains them. To use new population evidence, explicitly open current training data and start a new investigation.

The table presents several distinct summaries:

| Summary | Calculation | Interpretation limit |
| --- | --- | --- |
| Focus/reference means | Arithmetic mean of available associated rollout values, one weight per declared sample | Different monitors may have different measured samples |
| Difference | Focus mean minus reference mean | Descriptive; task mix and observation coverage can explain it |
| Common samples difference | Same calculation restricted to samples measured by every selected monitor | Comparable coverage, but the retained subset may still be biased |
| Within groups difference | Equal-weight mean of within-recorded-group focus minus reference means | Uses each monitor's available values; missing overlap or context can prevent comparison |
| Pooled opportunities | Sum of retained numerators / sum of decidable denominators for opportunity-ratio monitors | Not the mean sample rate; unknown opportunities remain separate |
| Pairwise association | Spearman correlation on the unique union of focus/reference members with both measurements | At least five pairs; unadjusted, no significance test or causal interpretation |

The detail panel also provides the within-group result restricted to common measured samples. Empty denominators stay unavailable. Unknown opportunities from entirely unresolved samples still contribute to the reported unknown count.

## Identities, scope and groups

The comparison binds declared sample identities using experiment, producer and rollout ID. Repeated training uses do not add sample weight. It reports distinct source rollouts, missing source joins and sources shared by multiple declared samples. Whole-rollout observations describe associated evidence; they do not establish which generated tokens contributed to training.

Filter decisions use the saved producer/filter/definition and explicit record revisions, including unknown, conflicting, batch-varying and absent decisions. Recorded stages can overlap: comparing generated samples with optimizer-recorded samples reports the intersection, rather than treating those populations as disjoint. Absence of an optimizer record is not evidence of non-use.

Matching uses recorded groups inside the selected experiment/cohort. Groups with incompatible recorded task, generation policy or coordinate are excluded. Missing group IDs, groups lacking both populations, and missing observations on a side are counted. Incomplete task/policy/coordinate context is reported even when a descriptive contrast is possible.

This ledger does not yet declare cross-producer group namespaces. Coincident group IDs spanning different sample producers are therefore **excluded as ambiguous**, not automatically joined or split into invented groups. This conservative comparison rule is versioned separately from the older single-monitor filter projection. Neither version establishes expected group completeness or causal control.

## Evidence and API

Each measure retains its definition, observer, receipt identities, coverage states and observation origin. Source hashes must match the saved source binding. Definitions and measurement identities are checked; corrupted values cannot silently enter a result. Case links include unavailable analyzed values, so an incomplete recovery window can be inspected in the existing rollout map and returned to its saved comparison.

- `GET /api/training-comparisons/options` lists existing monitors.
- `POST /api/training-comparisons/preview` takes `parent_id` and `spec`: exact saved `cohort`, optional `step`, `focus`/`reference` selectors `{kind: stage|filter|reward_pattern, value}`, and `monitors`. Reward patterns require the saved reward context and use `both_above`, `x_above_y_below`, `x_below_y_above`, `both_below`, `at_mean`, or `unavailable`.
- `POST /api/training-comparisons` takes the same fields plus `preview_id`. Changed observations require a new preview; client-supplied measurements are not accepted.

Saving creates another document in the existing investigation store, preserving the parent. A saved comparison remains readable if the current monitor catalog is unavailable. No analysis service or database is added. `population_statistics` supplies the unchanged legacy reducers; `population_comparisons` handles explicit members, measures and group context; `training_comparisons` binds that machinery to saved training evidence.

## Validation and limits

[Evidence and reproduction](../research/population-comparison-2026-10-11/README.md) distinguish replayed native TRL data from authored recovery controls. They validate arithmetic, source/measurement binding, censoring, navigation and persistence. They do not validate automatic semantic extraction or provide evidence of a trained model's behavior.

The comparison currently selects one existing cohort and either all its coordinates or one recorded coordinate. Cross-checkpoint matching, explicit group namespaces/completeness, arbitrary episode/segment relationships, observation scheduling, production-scale querying and continuous-ingestion snapshot capture remain work. It performs no causal adjustment, multiple-testing correction or significance testing. A preview is descriptive evidence for choosing a controlled experiment.
