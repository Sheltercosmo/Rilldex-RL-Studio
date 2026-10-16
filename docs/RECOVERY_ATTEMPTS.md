# Recovery across rollouts

This view follows **explicit failure-triggered chains of complete attempts**, which may each produce several training samples. It complements first-recheck and recovery-window measures inside a rollout. No tool names, adjacent timestamps, similar prompts or positive scalar rewards establish a chain or successful recovery.

In Training health, the automatic view selects **Recovery across rollouts** when the selected population contains attempt declarations. Choose a protocol/verifier, inspect first-attempt success, first-retry success and success within the declared budget, then open a chain and its source/behavior maps. A saved behavior measure can be compared across attempt positions without rerunning extraction. Later attempts are selected by prior failure; this comparison does not isolate the causal effect of feedback.

## Capture through the existing outbox

Supply `data.attempt` in an immutable sample declaration, using either training-record transport version. Version 2 is preferable when one attempt supplies multiple samples. A task ID is required. All samples from one executed attempt repeat the same attempt declaration.

```python
sample_data["attempt"] = {
    "schema": "recovery-attempt/1",
    "producer": "recovery-controller",
    "chain_id": native_chain_id,
    "attempt_id": native_attempt_id,
    "position": 2,                  # one-based; initial attempt is 1
    "budget": 3,                    # fixed maximum for this protocol/chain
    "previous_attempt_id": native_previous_attempt_id,
    "protocol": "feedback-clean-reset/v1",
    "context": "failure_feedback", # initial / fresh_retry / other / unrecorded
    "reset": "original_state",     # continued_state / unrecorded
}
score_data["attempt_outcome"] = {
    "schema": "attempt-outcome/1",
    "attempt_id": native_attempt_id,
    "result": "passed",             # failed / unknown
}
# Attach these fields to your existing sample and score records.
# Preserve native verifier component/definition and source revision.
outbox.log_training(experiment, records, schema="training-records/2")
```

The initial attempt has `context: initial` and `previous_attempt_id: null`. A later attempt must identify its immediate predecessor. Context/reset fields record the controller's assertion, not independently verified environment state or proof that the model used feedback. Version the protocol when context construction, reset policy, verifier access or stopping rules change. Do not insert samples for unused transport padding. Do not infer an explicit outcome from a shaped reward; use the verifier's actual result. Unavailable/error score records can only supply an unknown outcome.

Score revisions already supported by the ledger correct outcomes; immutable sample/attempt identities cannot be overwritten. The same versioned verifier stream must report results across the chain. Missing or conflicting outcomes stay unknown. An attempt ID reused in two chains, duplicate positions, changed task/budget/protocol, a missing predecessor or continuation without an established predecessor failure makes the chain unresolved. An orphan retry does not become a new initial attempt. Chains split by existing experiment/environment/recipe/clock cohorts do not join across those boundaries.

## Measurement definitions

| Measure | Numerator | Denominator and unresolved evidence |
| --- | --- | --- |
| First-attempt success | Initial attempts passing the selected verifier | Decidable initial attempts; unknown results or invalid chains retained separately |
| First-retry success | Passing second attempts after established initial failure | Decidable second attempts after initial failure with budget at least two; missing second attempts/outcomes unresolved; chains with unestablished initial failure excluded from this conditional population |
| Success within budget | Initial-attempt chains passing by the declared budget | Decidable chains: a pass closes a chain; a negative requires all budgeted attempts failed; incomplete chains unresolved |

Each chain counts once, not once per sample, retry or training use. Repeated copies of an explicit attempt result agree or remain conflicting; an absent sample-level copy is not a new failure. The selected verifier is separated by record producer, component and definition. Different protocols and budgets have separate views. Missing source bindings do not erase native outcome records, but prevent source inspection.

The main percentage uses decidable opportunities. When some are unresolved, the interface also shows lower/upper completion ranges across the defined opportunities. These are not confidence intervals and do not cover missing initial chains or failures whose eligibility is unestablished. Success-within-budget is observed cumulative success, not an independent-sampling Pass@k estimator. Reward assignment to the first failed attempt remains untouched when a later attempt passes.

Trends use **the initial attempt's recorded generation coordinate**, keeping a chain together even when retries arrive or execute later. Ambiguous/missing root coordinates remain outside the chart. Neither import order nor retry position is substituted for training step. Saved behavior means count each bound source rollout once within an attempt position, preserve missing measurements and exclude sources outside the selected monitor population. These are whole-source observations, not attribution to trained tokens.

## Compare recent and earlier windows

When at least two distinct initial-generation coordinates are recorded, **Did recovery change, or did the task mix change?** compares recent coordinates with an equally wide immediately preceding window. The default width is up to five observed coordinates per side. Sparse coordinates remain sparse; window width is neither elapsed time nor a count of contiguous optimizer updates. The selected protocol, budget, verifier and existing population boundaries stay fixed.

For each success measure the panel shows the raw, opportunity-weighted change and an equal-weight mean over recorded tasks with opportunities in both windows. Each shared task has weight `1 / number_of_shared_tasks` on both sides. The point estimate is unavailable if any shared task has no decidable outcomes on either side; it is not silently dropped. Missing-outcome ranges average the per-task failure/pass extremes and are not confidence intervals. Unshared/ambiguous task IDs, excluded opportunities and exact contributing chains remain inspectable.

First-retry task matching uses only established initial failures with retry budget. A task whose initial attempts all passed has no retry opportunity in that window. Thus even a shared-task contrast can involve different failure difficulty. Recorded feedback/reset distributions and missing retries are shown separately; different proportions are surfaced beside the comparison. The module makes no causal adjustment claim, does not establish matching task revisions, and does not treat a direction reversal as proof of why training changed.

The window/metric choices persist in the URL. Task inspection and exports retain the frozen dashboard snapshot, exact coordinates, verifier identity and source cases. [Task-mix execution audit](../research/recovery-task-mix-2026-10-12/README.md).

## Validation and remaining gates

[Execution controls and audit](../research/recovery-attempts-2026-10-12/README.md) verify actual local test results, delayed record delivery, source joins and UI cases. Contract tests cover both transports, corrections, duplicate samples, ambiguous lineage, clocks and behavior weighting. No new inference or semantic annotation is performed.

This is a portable producer contract and integrated projection. It is not a native FC-SWE integration, independent semantic validation, a reconstruction of a public training run, or proof of benefit from feedback. Native recovery-controller capture and measurement of task-mix/capture drift remain required.
