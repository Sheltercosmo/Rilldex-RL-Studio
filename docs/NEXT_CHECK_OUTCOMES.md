# First recheck outcomes

`retry-outcomes/1` answers: after a visible failed check, what happens at the **first** later recorded check of the same criterion, and what captured inputs changed before it?

This complements [recovery windows](RECOVERY_WINDOWS.md). That existing measure requires a recorded relevant input change for a positive and can look through three checks. It must not be used to compare changed and unchanged retries: change is already part of its success definition. Its saved definitions and graphs remain intact.

## Independent axes

Each visible failed check is one opportunity. Select the first subsequent check of the same criterion ID in the same actor and trajectory. A changed criterion version still consumes this first position and makes the comparison unknown. Other criterion IDs do not consume it. Never skip a failure or incomparable retry to find a later pass.

| Axis | Categories | Evidence |
|---|---|---|
| Outcome | Passed, failed, unknown | Recorded result; matching criterion version, required-object scope and environment; captured stable inputs and ordered dispatch/result |
| Captured input response | Recorded relevant change | At least one changed required input has a retained recorded edit between failure feedback and retry dispatch |
| Captured input response | Unchanged captured inputs | Required input versions agree between the failed check and first retry |
| Captured input response | Changed inputs, edit unestablished | Input versions differ but no matching retained edit is recorded |
| Captured input response | Unknown | No first retry or comparison is not established |

An unknown result can have a known input category. A comparable pass counts even with unchanged inputs or an unestablished edit. An intervening edit that is reverted before dispatch leaves captured inputs unchanged. Unrelated edits do not establish a relevant change. None of these categories is a semantic revision label.

## Three saved measures

- `next_check_success`: comparable passing first retries / decidable first retries.
- `next_check_success_changed`: the same ratio among recorded relevant input changes.
- `next_check_success_unchanged`: the same ratio among unchanged captured inputs.

The subgroup measures exclude known other input categories. They retain failures with unresolved group membership as unknown; their opportunity counts therefore include possible members. An unknown may appear in both subgroup uncertainty counts. Do not add those subgroup counts as if they were a partition. The four-row outcome table is the disjoint partition of all failure opportunities.

Every saved value includes numerator, denominator, unknown opportunities, group exclusions, the complete outcome table and exact cases. Zero decidable opportunities produces an unavailable value, not zero success. Multiple failed checks in one rollout create correlated, sometimes overlapping opportunities. No independence assumption or causal revision benefit is claimed.

## Engineering and use

In Monitors, choose an analysis measure and one of the three names above. Source evidence is sufficient when the producer supplies versioned check/input records. An observed graph can add existing feedback references; only references before first retry dispatch are retained. Missing links do not mean feedback was ignored.

Data connections includes the question “Does the first retry pass, with or without changed inputs?” It checks the chosen experiment and compatible monitor, then opens the existing monitor view. Saved values open the behavior map with an outcome table and individual failure → first-check cases. Graph edges connect only these selected check pairs; subsequent checks remain available as source context.

The registered dependency chain is `work_state → recovery_windows → retry_outcomes`. The first-check operator reuses captured comparability evidence but ignores the legacy change-conditioned success label. Exact dependency hashes, source identities, definitions and graph bindings are checked when loading receipts. No inference is run by the projection, dashboard or evidence view.

The producer contract is independent of an RL kit or tool name. It requires real criterion identity/version, required inputs, captured versions, stability assertions and source-linked check/edit results. Text-only trajectories without this capture cannot support this measure reliably. Three source encodings passing the replay audit is not native runtime support for those frameworks.

For training curves, the existing monitor uses explicit recorded training coordinates and pools opportunity numerators/denominators per step. Import order is not a training axis. The retained control dataset has no training coordinates and must not be presented as a learning curve.

[Execution replay, browser evidence and limitations](../research/next-check-outcomes-2026-10-11/README.md).
