# Revision flow review

26 October 2026. Select **Plans & attempts → Structure & flow**, then an **R** event. Trigger, target, follow-through and observed consequence appear beside source evidence and before/after results. Measures and alerts are available from that selection; there is no separate revision navigation page.

Comparison shares branch positions only for identical saved identities or user-confirmed pairs. Hatched work is **unmatched**, not necessarily absent. Depth and original parentage remain intact. Columns retain each rollout's event order. Shared-parent graphs keep independent layouts.

Branch pairs and selected revision evidence survive view changes and reloads. Selecting unmatched work leaves the reference scope empty. Changing the rollout or observer clears stale comparison selections.

## Evidence

The saved public-trace replay exposed two projection defects: older implementation relation names were ignored, and prerequisite edits lost their explicitly linked retries. Both are fixed. All **10 reviewed implementation/retry chains** now survive the projection. Failed implementation attempts remain distinct from later retry results.

The UI also counted `not_established` outcomes as measured. Coverage now counts only explicit completion or failure; unknown outcomes remain separate.

Check comparisons now keep distinct input objects separate and count a shared evidence pair once across revision scopes. Partial follow-up shows both observed changes and unresolved checks. Versioned receipts retain their original population; new projections use the corrected counting.

Source review covered **46 nonempty agent prose records** from OpenHands software, airline and retail trajectories; one ambiguous diagnostic proposal was excluded. The saved detector identified **9/12 reviewed revision decisions**, with **0 false positives** in this set. Misses: installing a missing dependency before the first conversion; proposing separate reservations after user correction; adopting a reduced exchange scope.

These are development sources reviewed by the implementation assistant after inspecting outputs, not independent labels or a holdout. They contain no versioned task-quality checks. They do not validate automatic assumption/context-change classification, reversion detection, or general accuracy. The four fields expose the evidence available, including unknowns.

Reproduce against the pinned local exports:

```sh
python scripts/audit_revision_flow.py --output .tracker/revision-flow-audit.json
```

[Review labels](../tests/fixtures/revision_flow_review.json) pin source hashes. Separate authored controls verify mixed gain/regression, partial follow-up, evaluator changes and temporal cutoffs; they are not accuracy results.
