# Reward relationships

Open **Training health → Reward relationships**. The view reads existing named score records on the same declared samples. It works independently of a particular RL objective and makes no model calls. Native capture support is still adapter-specific.

Choose two reward components. Definition and scoring producer remain part of each identity. The default prefers a component with broad score coverage and a peer with overlap; it never selects by a favorable correlation. Verified multi-reward settings prioritize this view automatically when at least two matched scores exist. Other available native learning signals keep their own priorities. Changing the population refreshes the pair; a saved unavailable pair is reported rather than silently substituted.

## Measurements

**Overall correlation** is Pearson correlation over samples with exactly one latest scored record for each selected component. A conflicting duplicate is excluded even if its value matches. Failed, unavailable or absent scores are not zeros. Each declared sample counts once; repeated optimizer uses do not duplicate it.

**Within-group correlation** is

`sum_g sum_i [(x_i - mean_g(x)) (y_i - mean_g(y))] / sqrt(sum_g sum_i (x_i - mean_g(x))² × sum_g sum_i (y_i - mean_g(y))²)`.

Groups must have recorded expected size, exact membership, at least two samples, consistent task/policy/step context, unambiguous producer namespace and both scores for every member. One missing component excludes that whole group from this statistic. Neither a partial group mean nor an average of group correlations is substituted. Subtracting means does not reproduce GDPO variance normalization or native advantages. Group sizes and residual magnitudes determine weighting.

Both correlations stay undefined for insufficient samples or zero variance. There are no alert thresholds or significance claims. Positive and negative numbers describe the recorded score relationship; they do not establish objective agreement, gradient conflict, reward hacking or a causal learning effect. Reward directions and weights require their own explicit interpretation.

Curves use each sample's recorded generation coordinate, never an inferred checkpoint or optimizer clock. Train/evaluation, environments, settings and identity schemas remain separated by the existing population contract. A group inconsistent across steps stays excluded even inside a step slice. Missing coordinates remain available in the overall evidence but do not acquire chart points.

Click a point or **Inspect paired scores** for both scores, missing states, group eligibility and source/behavior-map links. **Export paired evidence** preserves the opened snapshot, exact component definitions, score record IDs/revisions, sample identities and all rows. The table pages 50 rows at a time without reducing the export.

API: `GET /api/training-health?experiment=...&reward_x=<reward-id>&reward_y=<reward-id>`. IDs come from the response's `reward_relationships.components`. Only the selected pair is materialized; unrelated pairs are not expanded into full row sets.

## From reward patterns to behavior

In paired evidence, **Investigate behavior** saves the displayed pair and training population in the existing Investigations workspace. It retains the full cohort even when started from one chart point. The case list initially follows that point; later case selection does not change the group baselines.

**Saved reward patterns** displays each recorded generation coordinate as a stacked distribution: both raw scores above their own complete native group means, one above and the other below, both below, at least one at its mean, or unavailable. Direction compares the exact represented score with its group mean, with no tolerance threshold; rounded display values do not determine ties. Counts include unavailable samples. A missing score or incomplete group does not become a below-mean observation. These are explicit sample-selection rules, not new semantic tags or inferred diagnoses. Higher scores do not automatically mean preferred behavior. This comparison requires native groups; methods without complete group evidence retain unavailable results rather than receiving fabricated groups.

The two most populated available patterns initialize the focus/reference selectors when two exist. This ordering uses membership counts, never measured behavior differences. Researchers can compare up to eight existing behavior/source monitors, save their exact measurements, open a pinned rollout and return to the comparison. The grouped bars describe the entire saved reward cohort; a behavior contrast describes its explicitly selected populations and monitor coverage. Both remain inspectable after later score corrections.

`POST /api/investigations/rewards` accepts `scope` (experiment/environment/monitor), `snapshot_id`, `cohort_id`, `reward_x`, `reward_y`, optional `step`, `title` and `hypothesis`. It derives evidence server-side and rejects stale displayed snapshots. No new extraction or model calls occur. See [saved investigations](TRAINING_INVESTIGATIONS.md), [population comparisons](POPULATION_COMPARISONS.md), and the [native-data replay audit](../research/reward-behavior-2026-10-12/README.md).

## Native TRL multi-reward capture

The opt-in `GRPOTrainingLineageMixin` now accepts ordered component identities for TRL 1.13.0's native reward matrix. Wrap the first reward once; the remaining rewards stay unchanged. Their columns join to that same generated batch before native weighting and aggregation. NaN cells remain unavailable. The original matrix object is returned unchanged.

```python
class CapturedTrainer(GRPOTrainingLineageMixin, GRPOTrainer):
    pass

trainer = CapturedTrainer(
    # Usual native trainer arguments ...
    training_capture=capture,
    confirm_optimizer_steps=True,
    reward_funcs=[capture.wrap_reward(accuracy_reward), format_reward],
    reward_components=[
        {"component": "Accuracy", "definition": capture.reward_definition},
        {"component": "Format", "definition": "format-verifier/1"},
    ],
)
```

The producer supplies names and versioned scoring definitions, not monitoring thresholds. Component order must match `reward_funcs`; names must be unique. Two to 32 columns are supported. Single-reward capture is unchanged. The existing CPU/single-process/text-only/version gates remain; this does not establish a distributed, GPU, custom-rollout or second-framework capture adapter. Independently wrapped reward callbacks have separate generation identities and cannot replace this native matrix join.

[Native execution audit and limitations](../research/reward-relationships-2026-10-12/README.md).
