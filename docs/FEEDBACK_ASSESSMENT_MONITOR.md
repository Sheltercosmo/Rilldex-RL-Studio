# Direct feedback-assessment monitor

This experimental source-based monitor asks whether the agent expresses an assessment of a bound tool response before its next recorded dispatch. It needs no hand-authored semantic units, targets or candidate paraphrases. Jev classifies supplied agent expressions using finite choices and raw argmax. No confidence threshold or other model/API is used.

It supplements **Inspection feedback assessed**, the existing graph query starting from selected Inspect units and searching eight later units. This new monitor covers **all tool purposes**, ending at the next dispatch or user interruption. Their denominators and windows differ and must not be substituted or merged.

## Observation contract

One opportunity is one agent call with source-bound, visible environment responses. Multiple response chunks form one group. Every group retains its action, responses, following expressions, boundary, selected assessment, decision identity and coverage. Result-specific success/progress claims count even if wrong. Bare acknowledgements and next-step intentions do not establish assessment.

- **Assessment fraction:** selected positive groups / decidable groups.
- **Unknown fraction:** unknown groups / all response groups.
- Calls without bound visible responses remain separately counted, not negative assessments.

Recorded absence requires a complete readable window closed by another dispatch. Trace endings without a next dispatch, user interruptions, unread media, ambiguous batches, interleaved chunks and oversized windows cannot establish absence. An empty prose window before a recorded next action establishes only the absence of *expressed* assessment in that window, not hidden comprehension.

Immutable measurements bind to immutable graph versions. `assesses_response_group` edges connect existing source events. This observer does not invent semantic units or label them Assess. The full rollout remains visible; measurement drilldown lists every positive, absent and unknown group.

The worker runs explicitly, has a call budget, preserves interrupted executions and reuses validated decisions. Dashboard reads never initiate inference. The existing service detects newly saved observations within its five-second polling cycle. Continuously connecting this worker to ingestion is not implemented.

```powershell
python -m rilldex feedback-monitor research/feedback-assessment-v2-2026-10-08 --run-id 00a05d9a7ebf17ee7760cc18 --run-id 7046d56e989fdc4a4e7714d1 --run-id b81df2948f5135fbf5f283be --run-id 23a6f4b7c76c919e74ae6d50 --max-new-calls 60 --prompt-key
```

Repeat to resume. `--audit-only` replays complete results without provider calls. Credentials are prompted into process memory, never workspace files.

## Failed development pass

V1 completed four public traces across Nebius, Agent Process Bench and DevAI adapters. Its 41 response groups contained 15 selected positives, 25 recorded absences and one media-limited unknown. One trace had no eligible agent tool-response groups and no rate. These are **rejected development predictions**, not validated statistics or training trends.

Source review found missed explicit success/progress assessments in the software trace:

| Call | Agent expression | V1 problem |
| --- | --- | --- |
| e54 | The script executed successfully | Missed assessment |
| e57 | The performance metrics have been saved | Missed assessment |
| e60 | The visualization file has been generated | Missed assessment |
| e75 / e81 | Now that pandoc / pdflatex is installed | Missed result assertion |
| e96 | The PDF report has been generated | Missed assessment |
| e30 | Let's correct the syntax error and update the file | Questionable positive: intended correction alone is insufficient |

These paraphrased review cases are implementation-assistant judgments, not independent labels. Exact source passages and predictions remain in the audit artifact. V1 stays replayable, but new monitor creation rejects it, observer choices exclude it, and retained maps display its rejected status. It was never enabled on the main overview. Historical identities remain unchanged.

V2 resumed after provider recovery and completed six public traces: 53 response groups, 28 selected positives, 24 recorded absences and one unknown. One additional trace contributes zero eligible groups. SQL graph edges and saved numerators/denominators reconcile exactly; raw argmax replay passes. These are experimental predictions, not validated population statistics.

Source expectations were frozen before V2 predictions, although four development traces had already informed the harness; two additional transfer traces had not. Against those implementation-assistant expectations, 51 of 53 opportunities agree. Two result assertions remain missed: software call e24 (the sample dataset is now available) and transfer Nebius call e13 (the end of protocol.py has been reached without locating the failure handler). These judgments are not independent gold. V2 is registered as an experimental observer but remains **disabled as a main-dashboard monitor**. The previous service outage is resolved; semantic errors and independent evaluation are the remaining blockers.

V2's saved successful decisions report 105,387 input and 2,136 output tokens. See `research/feedback-assessment-v2-2026-10-08/audit.json` and `research/feedback-assessment-review-2026-10-08/comparison.json` for every opportunity and the two disagreements.

V1's 39 successful requests reported 83,021 input and 1,705 output tokens. V2 partial requests and service probes are additional usage; failed-request usage is unavailable. Review effort and discarded passes must count toward practical cost.

## Verification and remaining work

`scripts/audit_feedback_assessment.py` replays raw maxima, independently sums opportunities and reconciles physical SQL graph edges, response groups and source ordering. The V1 report is `research/feedback-assessment-2026-10-08/audit.json`. This verifies computation, not semantic accuracy.

Browser QA uses explicitly simulated selections in an isolated database on port 8766, never the real workspace. Positive, absent and unknown drilldowns retain all 12 cards; the positive case highlights its three source records. No browser errors occurred. Software and browser results are recorded in `research/feedback-assessment-v2-2026-10-08/validation.json`.

Next: resolve or explicitly adjudicate the two remaining source-review disagreements and obtain independent transfer evaluation before enabling a population monitor. Independent semantic evaluation, general semantic-unit/content extraction, continuous worker ingestion and genuine semantic training curves remain unfinished. The 3,072 public training generations still have source/reward metrics rather than these tool-feedback observations.
