# General behavior measurements and independent reference protocol

Version: `general-measurements/1` and `reference-benchmark/1`, 6 October 2026.

The machine-readable definitions live in `tracker/contracts.py`; `python -m rilldex contracts` prints them. They are definitions of intended measurements, not claims of validated accuracy. Specialized failure diagnoses remain outside this layer.

## Three investigation contracts

| Investigation | Observable | Denominator and unavailable cases | Research use |
| --- | --- | --- | --- |
| Work allocation and sequence | Action purpose and consecutive within-agent purpose pairs | All non-copied actions; all eligible adjacent pairs. Unknown purposes remain explicit. Pairs touching multi-action expressions are excluded without bridging. | Locate a changed way of working and inspect task-matched examples. |
| Response after feedback | Repeat, parameter change, method change, information gathering or continuation | Actions with feedback for the immediately preceding same-agent action, recorded before the current action. Unknown is separate from no opportunity. | Investigate persistence or updates following comparable feedback. |
| Verification and closure | Verify-purpose actions, linked results and the recorded action sequence following checks | Verify share uses all actions. Whole-sequence closure needs every action's purpose and unambiguous ordering; otherwise unresolved. | Inspect checking and stopping practice alongside separate verifier/outcome records. |

Purpose share is not time share or token share. A transition share divides by all eligible pairs, not only outgoing pairs of the row purpose. Repetition is not automatically wasted work. Method changes are not necessarily effective adaptation. Verification share is the same underlying measurement as the verify component of purpose share, not independent corroboration. Completion claims, task success and reward remain distinct.

For checkpoint comparisons, compute rollout rates first, average within each task, then weight matched tasks equally. Show actual opportunity counts, missingness and measurement provenance. An unavailable rate is not zero. The reference evaluator currently returns per-rollout purpose and transition errors, not a validated checkpoint-shift detector or automatic intervention policy.

## Runtime evidence requirements

`measurement-evidence/1` records source capabilities and support for each investigation. `macro/0.7.0` uses the same action/result linkage and opportunity rules as `macro-semantics/0.4.0`, which gates Jev questions before submission. `verification-evidence/2` leaves the post-check sequence unresolved when action purposes or order are unresolved. These versions supersede earlier packet/derivation behavior without rewriting original source records or stored answers.

| Source condition | Measurement treatment |
| --- | --- |
| Unique same-agent call ID, result after the prior action and before the current action | Eligible feedback correspondence; linkage basis and environment/harness origin remain visible. |
| First action, no preceding result, or a pair touching an unordered multi-action expression | No established preceding-feedback opportunity. Report the reason and do not ask Jev to invent a relationship. |
| Linked result with blank text or uninterpreted media/subagent context | Keep the established opportunity in the denominator, with an unresolved answer and no semantic request for that field. |
| Missing textual objective, local expression, action, or selectable goal candidate | Gate only the question requiring the missing evidence. Other supported questions can proceed. |
| Unknown action purpose or ambiguous ordering after a check | Preserve observed checks/results; keep the recorded post-check sequence unresolved. Artifact freshness remains unestablished. |
| Final producer grade or reward | Retain as outcome evidence; never include it in prefix-only behavioral judgments. |

Availability is not accuracy: a fully linked export can still produce poor semantic labels. Deterministic gate records are identified as `evidence_gate`, not Jev predictions, and carry no option probabilities. If an older stored answer violates current evidence requirements, preserve it underneath the withheld observation. Exact semantic cache reuse still requires an identical versioned packet.

The native SWE RL probe reconciles two downloaded trajectories, 150 structured actions, 148 source-linked results and two initial objectives. Two results are explicitly harness-generated. Later synthetic reminders do not create objectives. Optional grading is joined by a caller-supplied matching basename, then bound to source content and task identity; this does not independently authenticate the producer's verdict. The audit is `research/public-rl-2026-10-06/swe-rl-import-audit.json`. Neither trace records a policy checkpoint, and no new semantic inference or accuracy validation was performed for this import.

## What reference preparation produces

```sh
python -m rilldex contracts
python -m rilldex --db .tracker/tracker.sqlite reference prepare research/my-reference --per-run 12
```

Use `--run-id ID` repeatedly to choose runs. `--per-run 0` includes every action and is needed if the goal is to validate whole-rollout rates. The output must be a new directory so earlier labels and evidence cannot be overwritten.

| File | Audience and purpose |
| --- | --- |
| `review.html` | Local, self-contained reference UI. Open in a browser, read prefixes, enter judgments, download labels and resume later. No network request or inference is made. |
| `cases.jsonl` | Prediction-blind cases with the full recorded actor prefix and the exact bounded inspector state. Final metadata scores and policy names are omitted; raw source text can still reveal identity. |
| `labels.jsonl` | Empty reference template. No fabricated human annotations. |
| `predictions.jsonl` | Frozen unreviewed baseline results. Keep away from the independent reference reviewer. Existing retrospective overlays are not used. |
| `manifest.json` | Contract versions, grouping, declared exposure, sampling, opportunity inventory, source scope and content identities. |

The page shows the current action first, lets the reviewer expand source events and the bounded packet, and offers two questions per case. Predictions are never embedded in it. Downloads are explicit; browser memory is not durable storage. Keep independent reviewers' files separate. Importing another reviewer's file is for inspection/adjudication, not independent labeling.

The packet preserves source event IDs and JSON pointers. Normalized data alone cannot prove the adapter captured all source events. Source-extraction audits must compare with the immutable original producer records. The review form's extraction assessment means the supplied representation is valid for the particular judgment; an unexamined raw-source correspondence must not be described as audited.

## Grouping, exposure and sampling

Default preparation is **development-only**. Current public examples and producer fixtures have already been inspected. They cannot become a clean holdout by changing a random seed.

For a new unseen corpus, supply `--group-map groups.json` with entries such as:

```json
{
  "actual-run-id": {
    "group": "repository-or-task-family",
    "split": "holdout",
    "exposure": "unseen",
    "reference_scope": "Real producer rollout from the named evaluation corpus"
  }
}
```

Define groups before tuning. All rollouts of a task must use one group; related task variants should normally share a repository/family group. The preparer rejects groups crossing splits, same-task group conflicts and identical raw content crossing splits. It cannot infer every semantic relationship between tasks or independently authenticate an unseen-exposure declaration.

Selection uses a fixed seed to hash-rank actions within each rollout. The manifest records inclusion probability and whether each rollout is completely sampled. This balances review workload across rollouts; it does not make a convenience corpus a random sample of a training population. The reference scores describe selected cases, not population prevalence. Keep enriched challenge cases separate from a prevalence sample and use appropriate sampling weights for population estimates.

## Annotation instructions

Read the full available prefix to decide the reference value. Then inspect the bounded state to assess whether the model was given enough information. Do not use later action results, final reward or inspector predictions to decide a prefix judgment.

For **purpose**, select the best supported immediate observable purpose: explore, apply, verify, coordinate or report. Use unresolved for mixed or unsupported alternatives, or when the prefix cannot establish intent. Tool spelling alone is not sufficient when context changes its purpose. A command may execute work technically while its observable purpose is checking a hypothesis.

For **feedback response**, examine the previous action, its linked feedback and the current action. Use not-applicable when no such feedback opportunity exists. Choose unresolved when the relationship or operation is ambiguous. Distinguish changed arguments from a changed approach; do not infer a response merely because two actions are adjacent. Do not label an ordinary continuation as an improvement or failure.

For every entered judgment, supply:

- A value and one or more supporting prefix event IDs.
- An extraction assessment: valid, invalid or uncertain.
- Bounded-context sufficiency: sufficient, insufficient or uncertain.
- A note for ambiguity, missing evidence or disagreement when needed.
- A reviewer identifier and explicit provenance: human or model proposal.

A stronger LLM may propose labels, but `model_proposal` rows are excluded from human-reference accuracy. Human provenance is declared, not cryptographically authenticated. Do not copy inspector answers into a file labeled as independent human truth. The browser asks reviewers to confirm their own human judgments; it does not certify expertise or independence.

For subjective boundaries, obtain overlapping independent labels, retain disagreement and adjudicate with evidence. The initial evaluator accepts one resolved reference per case; it deliberately rejects duplicate rows. Multi-reviewer agreement and adjudication tooling are still to be added. Keep original reviewer files and a separate adjudicated file rather than overwriting disagreements.

## Evaluation and interpretation

```sh
python -m rilldex reference evaluate research/my-reference --labels reference-labels.jsonl --split development --output research/development-evaluation.json
```

The default evaluation split is holdout. Use development explicitly for the current pilot. Output files must be new. An unlabeled or absent holdout produces no accuracy claim. Use `--predictions alternate-predictions.jsonl` to evaluate another method against the same frozen cases, retaining case and manifest hashes and a declared `profile.external` identity.

Evaluation separates:

| Output | Meaning |
| --- | --- |
| Selective accuracy | Correct decisions / decided cases with concrete, valid reference labels. |
| Decision coverage | Decided cases / concrete valid reference cases, including missing predictions in the base. |
| Overall correct share | Correct decisions / concrete valid reference cases; abstentions and missing predictions are not successes. |
| Per-class precision/recall and confusion | Distinguish false positives, misses and class support. Unresolved/not-applicable reference cases are reported separately. |
| Extraction exclusions | Invalid and uncertain extraction are counted separately; classification results are conditional on valid extraction. |
| Context and adapter slices | Show whether errors cluster in insufficient context or a source format. |
| Predictor-profile slices | Avoid attributing a mixed heuristic/Jev baseline to Jev alone. |
| Whole-rollout macro errors | Purpose and transition share differences relative to complete references. Sparse references produce an incomplete status, not a rate estimate. |
| Closure sequence | Derived independently from reference and prediction action purposes. Unknown purposes or ambiguous ordering produce unresolved; no claim about artifact freshness or justified stopping. |

Every prediction/reference is checked against the frozen case and manifest identity. Missing predictions remain visible. Model-proposed references do not contribute to human-reference accuracy. No action-IID confidence interval is reported because actions within a rollout are correlated. Repeated action types can still dominate within a selected rollout; inspect task/adapter slices and use an independent challenge set for rare cases.

This evaluator does not yet estimate feedback-rate error over fully reviewed eligibility sets, inter-reviewer agreement, calibrated thresholds, uncertainty from annotation disagreements, or false/missed checkpoint shifts. These remain required before promoting the corresponding monitoring claims.

## Current prepared pilot

`research/reference-pilot-2026-10-06/` contains 98 action cases from eight existing public SWE-agent dataset trajectories plus three normalized runs from pinned Harbor repository examples/golden fixtures. The Harbor continuation is assembled once, with copied context excluded from action counts. There are four adapter encodings: Nebius, Harbor, Harbor bundle and native mini-SWE.

The 98 cases are **development material**, not a new representative 20-30-rollout RL cohort. Producer golden fixtures establish format/workflow coverage, not real model behavioral generalization. Five of the eleven records have complete action samples. No human labels or held-out accuracy results have been created.

The existing packet remains frozen under its original harness versions. Evaluate it without rebuilding:

```sh
python -m rilldex reference evaluate research/reference-pilot-2026-10-06 --split development
```

Its unlabeled evaluation report explicitly returns `no_reference_labels`. The historical preparation script reads the tracker database in read-only mode and checks pinned fixture hashes. After the harness change, re-preparing with the six old Jev answers correctly fails the stale-packet guard. A new packet needs current-version predictions or an explicitly separate heuristic-only baseline; do not relabel old answers as current or overwrite the original pilot. Neither preparation nor evaluation submits inference.

## Promotion gates

Before a metric becomes a default training monitor, set acceptable error and review burden for its intended decision, evaluate grouped held-out traces, inspect candidate/context/extraction failures, and test macro differences on actual matched checkpoints. A 0.9 option probability, a successful API call or a passing workflow test is not a substitute.

Practical evaluation should record setup time, time to a reviewed finding, correction burden, missed findings, unsupported conclusions and cost. Compare the same questions and evidence with a manual workflow and a Scout scanner; assess Docent when access is available. A well-supported null finding can be useful. The objective is research decisions, not a high count of diagnoses.

Design references: [AISI transcript-analysis workflow](https://www.aisi.gov.uk/blog/a-pipeline-for-transcript-analysis-using-inspect-scout), [Scout validation](https://meridianlabs-ai.github.io/inspect_scout/validation.html), [TypeSafe primitives](https://docs.typesafe.ai/primitives). These informed the protocol; they do not establish our measurement quality.
