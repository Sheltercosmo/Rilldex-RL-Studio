# Recovery after a recorded change

Implemented 11 October 2026 within the [RL engineering framework](RL_ENGINEERING_FRAMEWORK.md). This delivers a deterministic recovery operation and one investigation-to-monitor path. It does not establish general semantic accuracy or complete the broader feedback/recovery research gate.

## Research question and required evidence

Did an agent recover from a failed check, after a relevant recorded input change, within a declared follow-up window?

The source can describe code, an order, a document or another versioned object. The producer supplies criterion identity/version, required objects, environment identity, input versions, stability during the check, check outcome and action/result references through the existing [state capture contract](STATE_CAPTURE.md). The observation does not guess these from tool names or success claims. Missing capture makes the measure unavailable rather than zero.

An optional selected semantic observer adds already-recorded [feedback references](FEEDBACK_REFERENCE.md). Their presence before the successful retry is inspectable; a missing edge remains unestablished. A reference does not prove that the feedback caused the change. No model calls or additional activity labels are needed by this operation.

## Versioned definition

The operation is `recovery-windows/1`; the saved measure is `criterion_recovery_window`. The definition is pinned with its work-state and feedback-opportunity dependencies.

| Item | Rule |
| --- | --- |
| Opportunity | One recorded failed check with a visible result. Multiple failures in a rollout create separate, potentially overlapping opportunities. |
| Follow-up window | The next three recorded checks with the same criterion ID, after the failure result, by the same actor in the same trajectory. Checks with changed versions or scopes consume a slot but may be incomparable. Other criterion IDs do not consume slots. |
| Comparable check | Same criterion version, required-object set and environment, with captured input versions, result after dispatch, recorded stable inputs and no recorded relevant change during the check. Both original and follow-up checks must have the necessary evidence. |
| Relevant change | A recorded edit between failure result and retry changes a required object; the changed version differs from the failed input and remains present at retry. This witnesses at least one retained relevant change, not a complete causal explanation. |
| Recovered | A comparable passing check after a supported relevant change occurs within the window. This positive witness can close the window early. An earlier incomparable pass does not hide a later valid one. |
| Not recovered in window | All three follow-up checks are comparable and failed. This does not establish whole-task failure or absence of later recovery. |
| Unknown | Short window without a positive witness; missing criterion/state/stability; incomparable checks; unknown outcomes; or a pass without supported relevant change. End of the captured trace does not convert unknown to failure. |
| No opportunity | No eligible recorded failed check; no rate is reported. Hidden/missing failed-result exclusions are counted separately. |

The displayed rate is recovered opportunities / decidable opportunities. Always show unknown and total opportunity counts. The cohort comparison pools opportunity numerators and denominators; mean per-rollout rate is a separately named value. Opportunities overlap, so their count is not a count of independent samples or unique repair episodes. Task success conditioned on recovery is another measure, not this one.

The three-check horizon is an explicit initial convention, not a universal optimal horizon. A different horizon or negative rule requires a new definition and validation. Do not infer training order from these controls' import order.

## Researcher workflow

1. Open an investigation and choose focus/reference rollouts with suitable task and configuration context.
2. Under **Recovery & verification**, compare rates together with decidable, unknown and opportunity counts.
3. Open a failed-check window. Inspect each retry, criterion comparability, retained input changes and unknown reasons.
4. Open its rollout evidence. The existing map retains semantic units and native actions, with a **Rechecks** relationship filter. Check/state facts remain evidence records rather than empty activity cards.
5. Select **Monitor criterion recovery** to save the pinned definition using that observer. The monitor covers current/future captured rollouts; the temporary investigation cohort is not silently frozen into its population. Use overview filters to select a cohort.

Native recorded facts and semantic contributions share one evidence graph. A `recorded_recheck_of` edge connects stored check records; the map projects the endpoints onto their existing visible occurrences. The relationship alone does not assert comparability, recovery or causation. Its inspector states comparability and retains the stored check identities.

## Reuse and compatibility

The existing typed analysis engine runs `work_state → recovery_windows`, caches both dependencies and saves source/version/output/graph receipts. It also supplies per-rollout monitor values, cases and cohort comparisons. There is no separate recovery service or new graph store.

The older `work-state/6` recovery calculation and `criterion_recovery` monitor remain frozen for historical receipts. That calculation could mark a short failed retry as negative, or select an incomparable pass before considering a later valid pass. New investigations use the explicit-window measure. Older saved investigations display their earlier definition and require reanalysis to obtain the new result; the monitor editor labels the old option accordingly.

## Validation boundary and next work

[Executed controls and browser evidence](../research/recovery-windows-2026-10-11/README.md) cover software checks, business-state checks and SQLite workflow checks. SWE-agent, Harbor and chat encodings test source normalization; they are not native agent-framework executions or policy behavior evaluations.

Producer-supplied criteria, scope and stability still need auditing in real integrations. Semantic feedback/reference accuracy remains unmeasured independently. Next compare direct-source and graph-derived answers on the same held-out questions, quantify coverage and errors, then join validated recovery observations to actual training sample populations. Causal claims require intervention evidence beyond this trace relation.
