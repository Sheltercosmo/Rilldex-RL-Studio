# Execution errors and evaluator evidence

Rilldex keeps three different questions separate:

1. Did the tool explicitly report an execution error?
2. Which recorded checks contributed to the reward, and which were diagnostic only?
3. Is the task independently known to be solved?

The first two do not establish the third. No-error flags, successful termination,
reference-action matching and positive reward are not interchangeable labels.

## Monitoring and inspection

The metric selector includes **Tool responses flagged as errors**, **Tool error
flag coverage**, **Reward component coverage**, **Zero-valued reward component**,
**Unmet checks outside the reward** and **Logged reward minus component aggregate**.
Open a reward/error metric's rollout values, then **Evaluator evidence**. The same
inspection is available inside an investigation's rollout evidence dialog.

Component membership and scores appear together; checks show their recorded
verdict and whether they count toward reward. Unknown results remain unknown.
The inspector preserves source references and exposes the full evaluator record.
It does not call a model or recompute a benchmark verdict.

Native tau-bench `reward_info` is supported, alongside existing weighted rubric
records. `reward_basis` determines membership; `reward_breakdown` supplies scores.
An ACTION or NL_ASSERTION check outside the basis is diagnostic only. In particular,
reference actions often construct an expected state rather than prescribing the
agent's plan. See the [upstream evaluation contract](https://github.com/sierra-research/tau2-bench/blob/4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699/docs/evaluation.md).

## Portable producer contract

Attach this to a supported trajectory's raw document, outside its agent-visible
messages. A producer must record the evaluator definition and actual membership;
Rilldex does not guess them from check names or failed assertions.

```json
{
  "reward_evaluation": {
    "schema": "component-evaluation/1",
    "definition": "task-state-checks/2",
    "aggregation": "product",
    "score": 1,
    "components": [
      {"id": "final_state", "role": "reward", "value": 1},
      {"id": "preferred_method", "role": "diagnostic", "value": 0}
    ],
    "checks": [
      {"id": "method_check", "component": "preferred_method",
       "description": "Recorded preferred-method check", "met": false}
    ]
  }
}
```

The example's reward is 1 despite an unmet diagnostic check. It does not prove
reward hacking or a policy violation. `sum` and `product` permit an arithmetic
consistency check when every reward component and the logged score are finite.
Other transformations leave that measure unavailable. Null scores and verdicts
represent missing evidence; boolean scores, duplicate IDs and invalid references
invalidate derived measures. A missing check is never silently treated as passing.

Native agent tool responses with an explicit boolean error flag contribute to
the error fraction. A separate coverage denominator includes all source-linked
agent responses. User-side actions, copied history and ambiguous links are excluded.

## Code access without export

```python
from rilldex import Workspace

w = Workspace("study.sqlite", experiment="my-experiment", observer="source")
rows = w.sql("""
    SELECT run_id, metric, value, numerator, denominator, status
    FROM measurements
    WHERE metric IN ('environment_tool_error_fraction',
                     'environment_tool_error_coverage',
                     'reward_component_zero_observed',
                     'reward_diagnostic_failure_observed')
""").rows
```

`GET /api/reward-records/<run_id>` returns the versioned inspection with source
pointers, component roles, checks, issues and calculations. Metric schema 18
extends existing saved measurements from retained source data, preserving semantic
annotation and graph identities. This migration makes no paid inference calls.

## Independent checks in an investigation

**Checks & findings → Record finding → Verifier / independent check** attaches
reports produced by your evaluation worker. Inspect and attach both the original
reward evaluation and the independent check to see their verdicts side by side.
Existing investigation revisions and original rewards stay unchanged when a
later check or evaluator repair arrives. The comparison is saved in the finding
and included in its investigation bundle.

Each report is a producer statement, not a Rilldex-certified evaluation. Rilldex
does not execute the report, fetch artifacts, authenticate the producer, or prove
that the declared hashes were actually used. Hidden checks and later evaluations
remain outside the agent-visible source and cannot enter earlier-evidence search.
The `independent_check` purpose is the producer's declared role; it does not prove
statistical independence or a different implementation.

The comparison distinguishes:

- **Verdicts agree / disagree:** both checks completed with known verdicts and
  the same declared task, criterion, artifact, environment and output boundary. Evaluator
  definitions may differ; the comparison shows whether they do.
- **Different source / inputs:** the pair does not isolate an evaluator change.
- **Input revisions missing:** insufficient declared identity to establish the
  controlled comparison, even if both reports say “passed.”
- **Execution error / unresolved:** an errored, unfinished or unknown check is
  not a failed task. Missing input information is retained alongside the status.

Disagreement can result from invalid work accepted by the original grader,
valid work rejected by an overrestrictive grader, or a faulty independent check.
It is not automatically reward hacking. Investigate the requirements, artifacts
and reported evidence before recording your conclusion.

### Send a worker report

Use `Workspace.record_evaluation(receipt)` locally or `POST /api/evaluations`
remotely. The following fields are required for `evaluation-receipt/1`:

| Field | Meaning |
|---|---|
| `schema` | `evaluation-receipt/1` |
| `label`, `producer` | Readable check name and producing worker/version |
| `performed_at` | Producer-reported ISO timestamp with timezone; arrival time is stored separately |
| `run_id`, `source_hash` | Exact existing rollout and its canonical source digest |
| `purpose` | `reward`, `independent_check`, or `repair_check` |
| `inputs` | Keys `task`, `criterion`, `artifact`, `evaluator`, `environment`, `output_boundary`; each is `{label, sha256}` or `null` |
| `execution` | `completed`, `error`, `incomplete`, or `not_run` |
| `verdict` | `passed`, `failed`, or `unknown` |
| `score` | Finite reported number or `null`; no success threshold is inferred |
| `summary` | What was checked and any relevant limitations |
| `evidence` | Up to 16 `{label, text}` excerpts; bounded report text, not executable commands |

Use actual SHA-256 digests, in lowercase. For a multi-file submission, hash a
canonical manifest that names every submitted file and its content digest. Pin
the effective evaluator configuration with its implementation, not a mutable
branch name. Unknown input identities must be `null`, never guessed from a
filename. Hashing a manifest establishes its identity, not its completeness.
`criterion` identifies the normative property being assessed, independently of
the implementation used to test it. A diagnostic method check and a task-success
check are not equivalent just because they share a task. Older reports without
criterion identity stay readable, but comparison version 2 marks that input
missing; older saved comparisons retain their historical values and are labeled
as not having checked criterion scope in the UI.
For noncompleted checks, `verdict` must be `unknown` and `score` must be `null`.

Find the exact source digest with
`w.graphs(run_id=run_id, observer="source").rows`; select the graph matching the
source snapshot being evaluated. Do not attach an older evaluation to the newest
rollout just because its logical training sample has the same name.

```python
import json
from pathlib import Path
from rilldex import Workspace

w = Workspace("study.sqlite", experiment="my-experiment")
receipt = json.loads(Path("evaluation.json").read_text(encoding="utf-8"))
saved = w.record_evaluation(receipt)
# Retrying exactly the same report returns exactly the same identity.
assert w.record_evaluation(receipt)["id"] == saved["id"]

page = w.evaluations(receipt["run_id"], limit=50, offset=0)
# Choose explicit report IDs; do not silently substitute the latest verifier.
comparison = w.compare_evaluations([original_report_id, independent_report_id])
print(comparison["pairs"][0]["status"])
```

HTTP also provides `GET /api/evaluations?run_id=...&limit=50&offset=0`,
`GET /api/evaluations/<id>`, and `POST /api/evaluations/compare` with
`{"ids": [original_report_id, independent_report_id]}`. Follow-up results attach
`{"kind": "evaluation", "id": saved_id}` through the existing follow-up API.
Receipt IDs are content identities; corrections create new receipts. Worker
authentication and transport deployment follow the existing server configuration.

### Query with your own code

The native `evaluations` table is available to `Workspace.sql()` and
`Workspace.table()`, and included in new research exports and full workspace
snapshots. Experiment and source-history scoping apply. Existing frozen exports
without the table report it unavailable instead of inventing zero observations.

```python
rows = w.sql("""
    SELECT evaluation_id, run_id, purpose, execution, verdict, score,
           performed_at, received_at, receipt_json
    FROM evaluations
    WHERE run_id = ?
""", [run_id]).rows
```

There may be several checks, repetitions and revisions per rollout. Counting
report rows as distinct rollout outcomes would overcount. Select explicit report
identities and define your audited population before computing a rate. These
reports do not yet provide a new remote incremental change-feed channel; use the
worker POST endpoint, paginated reads or the existing workspace snapshot path.

The [executable workflow controls](../research/evaluation-followups-2026-10-16/README.md)
exercise both directions of disagreement, incomplete evidence and infrastructure
failure. They validate the workflow; they do not estimate real-world hack prevalence.

## Follow a reviewed rollout into training

In a report inspector, choose **Look up selection & training use**. In **Record
finding**, select **Selection & training use**, inspect the bound samples, and
attach the snapshot. An evaluation report and a training snapshot can coexist in
the same finding. Original rewards and previous findings are not changed.

The lookup uses exact producer / rollout / revision declarations. It never joins
by matching task text, file names or the newest available source. Independent
training samples retain their separate identities and explicit span bindings.
Conflicting declarations, invalid spans and experiment conflicts are excluded
from membership counts and remain inspectable.

```python
from rilldex import Workspace
from tracker.training_exposure import reference

w = Workspace("study.sqlite", experiment="my-experiment", history=True)
exposure = w.training_exposure(run_id, source_hash=reviewed_source_hash)
for cohort in exposure["cohorts"]:
    print(cohort["split"], cohort["bound_samples"],
          cohort["backward_receipts"], cohort["optimizer_receipts"])
evidence_reference = reference(exposure)  # existing follow-up result evidence
```

HTTP: `GET /api/training-exposure?run_id=…&source_hash=…&experiment=…`.
The experiment is optional; supplied workspace scope always applies in Python.
Use `history=True` to inspect a superseded source revision with the SDK.
Saving rechecks the snapshot identity. If relevant records arrived since preview,
review the new snapshot before attaching. A saved finding retains its old view.

Results distinguish named filters and batches, backward and optimizer stages,
positive / zero / unrecorded backward masks, sample counts and receipt counts.
Training and evaluation samples, experiments and identity schemas retain separate
denominators. Missing records mean unknown, not rejection or non-use. A source
binding alone does not prove the evaluated behavior or artifact entered the loss;
a positive mask does not prove a nonzero gradient or causal parameter effect.

The targeted lookup reads up to 200 candidate samples, 2,000 projected records
and two million projected characters across the lookup. Incomplete samples are
excluded from totals, with limit reasons; sample truncation is explicit. Tensor
payloads are omitted with field names retained. Use the existing native analysis
tables for larger or token-level queries. This is not a complete search of
unmapped or orphan training records and does not estimate exploit prevalence.

[Validation and retained native replay](../research/training-exposure-2026-10-16/README.md).
