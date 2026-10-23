# Review the evidence behind a rate monitor

A useful rate needs both a declared denominator and a way to check its cases. The measurement-review workflow freezes a selected rollout cohort, samples its saved opportunity cases, and lets a named reviewer judge source evidence before the monitor's answer appears in that case view. It reuses saved measurements and the existing correction map; it does not run an observer or create semantic reference labels automatically.

## Researcher workflow

1. Open a rate monitor's rollout values, optionally at a training step. Choose **Review sampled cases**. The sample uses all rollouts in that selected cohort, including unresolved cases; the table's positive/available filter does not silently filter the review sample.
2. Enter a reviewer name and declared role. Read the exact case passages, with earlier source context and recorded state available. **Go to latest passage** jumps to the endpoint of a long case.
3. Judge whether the measured opportunity was taken, not taken, unresolved, or not an eligible opportunity. Add a rationale and select supporting source passages.
4. Save to reveal the saved monitor answer. Open the exact measurement in the rollout map to inspect or correct its underlying evidence using the existing workflow.
5. Resume the same frozen sample or export its summary. Later monitor corrections do not rewrite the sample or its judgments. A new sample reflects the latest saved measurements.

Supported routes are analysis monitors with `opportunity_ratio` aggregation, binary code monitors, and built-in diagnostic indicators. Binary reviews use one case per saved rollout result and show the full recorded source. Count and arbitrary scalar monitors are not converted into binary cases. The interface requests up to 20 cases with a fixed seed; the API accepts 1–100.

Choose **Save validation set** to reuse reviewed cases across detector versions. [Detector validation →](DETECTOR_VALIDATION_SETS.md)

## Contract

New samples use `measurement-review-sample/2`. For a work-switch return rate, the frozen sample includes `work-switch-entry-evidence/1`: the exact first contribution of the visit, prior witnesses, source cutoff, recorded order status, and later units excluded from decision evidence. Review stops at that entry. Other analysis rates retain their recorded case scope. This change does not alter the numeric measure or certify that work-identity annotations were inferred without later context.

Older v1 samples retain their full-visit source scope and existing judgments. They are not silently converted. Creating a v2 sample over the same cohort retains the case frame and sampled membership but creates a new sample identity because its review evidence differs. The ordinary saved-measurement map also offers the read-only entry explanation while keeping the whole visit accessible. [Boundary audit](../research/work-switch-entry-2026-10-11/README.md).

- Sample identity covers the exact monitor definition, cohort, latest measurement IDs at creation, full saved case frame, case hashes, requested size, seed, and selected case IDs.
- Deterministic hash ordering samples without replacement across **cases**, not equally across rollouts. A rollout with more opportunities contributes more frame entries. True, false and unresolved predictions all remain eligible.
- Completed zero-case measurements and rollouts without a completed case frame are distinct. No opportunity yields no review sample, not a zero accuracy score.
- Source, graph and measurement receipt identities are checked before sampled cases are published and when opened. Raw source text and exact character offsets support citations.
- Unit spans take precedence over containing-event wrappers. Earlier context stops at the last selected span in each trajectory/context stream. Whole-event witnesses without unit spans retain the complete event. Recorded state is shown only when its source events and referenced snapshots are fully visible.
- This is a retrospective audit. The saved case's construction can depend on later outcomes. Source clipping does **not** prove an online observer used only prior evidence.
- Judgments are append-only. A revision names its predecessor; stale writes are rejected and identical retries are idempotent. The source and saved predictions are not edited by a judgment.
- Reviewer names and roles are self-declared, not authenticated. Prediction hiding is a UI review aid, not a security boundary or proof of independent annotation.

Per-reviewer results keep false positives, false negatives, unresolved references, unresolved predictions with decidable references, and eligibility disputes separate. Agreement uses only jointly decidable judgments. Reviewers are not pooled. The report does not claim population accuracy, causal effects, or recall for opportunities the original case frame missed.

## API

`POST /api/measurement-reviews` takes `monitor_id`, `run_ids`, `size`, and `seed`. `GET /api/measurement-reviews?monitor=<id>` lists saved samples. `GET /api/measurement-reviews/<sample>` returns the summary (`download=1` downloads it).

`GET /api/measurement-reviews/<sample>?case=<case>&reviewer=<name>` returns source passages, context, recorded state, freshness, and that reviewer's latest judgment. The predicted answer is returned in this case view only after that reviewer has a saved judgment.

`POST /api/measurement-reviews/labels` takes `sample_id`, `case_id`, `reviewer`, `reviewer_role`, `label`, `note`, `citations`, and `supersedes`. Each citation supplies `event_id`, `start`, and `end`; stored text is resolved from the frozen source. Labels are `taken`, `not_taken`, `unknown`, or `not_opportunity`. Roles are `independent_reviewer`, `developer_review`, or `not_declared`.

Tables `measurement_review_samples` and `measurement_review_labels` are created lazily in the existing SQLite store. The dashboard advertises the entry point only when the running backend reports the matching capability. A server running older cached code must load the new backend before the feature is offered.

Whole action witnesses and fully visible source action events also expose their recorded tool name and structured arguments. This makes source tools such as `task_tracker` reviewable even when the action's displayed text is only `plan`. Arguments are withheld for partial action text windows. Existing citation fields remain text spans, not JSON-pointer citations; no predicted interpretation is added to the raw arguments.

For initial task-list entries and reported-reopening cases, the case view also returns `source_subject`: the exact raw entry, event ID, event source pointer and argument pointer. The item index and title are validated against a fully visible source action. **Entry being reviewed** displays this subject before judgment so distinct entries from the same list are distinguishable. It adds neither a predicted label nor a new citation format, and does not change stored sample identities.

[Implementation validation and remaining limits](../research/measurement-review-2026-10-11/README.md).
