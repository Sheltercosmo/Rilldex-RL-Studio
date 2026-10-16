# Interpreting a moving RL curve

Implemented 15 October 2026. This is evidence interpretation shared by every
monitor, not a detector for an early-training dip.

## Research basis

- [verl fully asynchronous training](https://verl.readthedocs.io/en/latest/advance/fully_async.html)
  separates production and consumption, exposes sample staleness and supports
  partial rollouts. Streaming collection size and distribution order can affect
  training, so arrival bias and learner-consumption bias are distinct questions.
- [slime rollout modes](https://thudm.github.io/slime/rollout/index.html) include
  synchronous, partial and distributed asynchronous operation. Asynchronous
  inference alone does not establish asynchronous optimizer updates.
- [verl dynamic scheduling](https://verl.readthedocs.io/en/latest/advance/dynamic_schedule.html)
  describes mixed inference pools, request redistribution and partial-rollout
  retries. Infrastructure attempts must not be counted as independent task
  failures or successful policy samples.

These sources motivate the measurement boundaries. They do not verify the
community anecdote or show that an early reward drop will recover. Short outputs
are not necessarily easy tasks, and completion selection can move a metric in
either direction. No stop/continue recommendation follows from these checks.

## A general investigation workflow

1. Identify the changed outcome or behavior and its recorded clock. A generation
   step, learner update and evaluation batch are not interchangeable.
2. Examine evidence availability at those same coordinates. Separate unfinished
   source capture, capture failure and an arrived source without this monitor's
   measurement. Missing evidence stays missing on outcome/behavior charts.
3. Examine selection: measured versus observed task/policy proportions; baseline
   versus current task mix; and recorded configuration differences. Environment
   reweighting controls only recorded environment strata, not task difficulty.
4. Inspect scheduler execution reports, durations, output tokens and states.
   This panel covers the whole selected experiment/environment, not comparison
   step ranges: execution records do not currently declare those coordinates.
5. Inspect generated, selected and actually used samples and policy age in the
   existing training views. A biased dashboard and a changed optimizer input
   population require different responses.
6. Save the comparison, repeat the identical windows after evidence arrives,
   inspect exact cases and use a fixed-task evaluation to test persistent
   regression. A frozen result never changes underneath the researcher.

The same workflow applies to delayed verifiers, missing semantic observations,
capture outages, task-mix changes, reward/correctness disagreement and differing
generation/learner policies. It exposes competing explanations rather than
automatically declaring a cause.

## Product and code contracts

- Overview exposes reported execution context and a **Show measurement
  coverage** chart mode for each monitor. Coverage is measured / observed source
  captures, not completed / scheduled jobs. Outcome zero is measured; missing
  outcome is not zero. The chart retains original source and receipt IDs.
- `monitor-comparison/3` retains declared cohort evidence and its alignment with
  chart clocks alongside per-window `readiness`, structured `review` checks
  and frozen `execution_context`. Versions 1 and 2 remain readable without
  inventing their missing capture history.
- `readiness.selection` compares measured and observed task/policy proportions
  using total variation distance; unknown metadata is retained explicitly.
  This is descriptive, not a significance test or causal estimate.
- `population_closed` is always null for these summaries. Neither all observed
  executions ending nor all received sources being measured proves scheduler
  closure. No instrumentation means unknown workload, not zero in-flight jobs.
- Execution summaries count attempts and retain retries. They are latest
  reported states, not heartbeats. Durations and tokens require producer values;
  no cross-host timestamp subtraction or character-to-token conversion occurs.
- Execution-only revisions refresh the overview independently of source arrival
  or semantic measurement materialization. This does not invoke Jev or Luna.

## Declare workload before traces arrive

The scheduler, not the observer, knows which work was admitted. `log_cohorts`
uses the existing durable outbox: local enqueue, background HTTP delivery,
restart/replay, or offline capture bundles. No UI or model calls are required.
Frameworks can emit this contract from their scheduler or an exporter; this is
not a claim that every trainer already emits it automatically.

```python
from rilldex import Outbox

out = Outbox("scheduler-outbox.sqlite", producer="scheduler",
             endpoint="http://127.0.0.1:8810")
cohort = {
    "id": "generation-12", "revision": 0, "label": "Generation batch 12",
    "coordinate": {"clock": "run-a/generation", "basis": "generation batch", "index": 12},
    "context": {"split": "train", "environment": "terminal"},
    "sealed": True,  # scheduler knows this membership is fixed
    "members": [
        {"producer": "worker-1", "rollout_id": "sample-12-0",
         "generation_state": "admitted", "context": {"task_id": "task-a"}}
    ],
    "evidence": "Scheduler admission ledger",
}
out.log_cohorts("run-a", [cohort])
out.drain()  # or use the existing background outbox sender

# After the same logical rollout finishes, update its generation declaration.
# The worker sends the trace using that exact producer / rollout_id pair.
cohort["revision"] = 1
cohort["members"][0]["generation_state"] = "completed"
out.log_cohorts("run-a", [cohort])
out.drain()
```

Before sealing, revisions can append members. After sealing, membership cannot
change; admitted members can still become completed, failed or cancelled.
Generation termination is not verified task success. Retain a separate
execution attempt ID for each retry; retries do not add logical cohort members.
Never reuse an experiment identity for a new training job.

Full snapshots accept 1–100 cohorts and at most 10,000 member entries per packet.
This is a bounded manifest protocol, not a high-throughput per-token stream.
Use bounded scheduler batches and coalesce state changes; huge repeatedly copied
manifests need a future membership-delta protocol. Do not split one immutable
logical population across invented identities to hide incomplete membership.

The server accepts `POST /api/generation-cohorts` with
`{"schema":"generation-cohorts/1","producer":...,"experiment":...,"cohorts":[...]}`.
`GET /api/generation-cohorts?experiment=run-a&members=1` reads current evidence.
Optional `cohort`, `producer`, `clock`, `basis`, `environment` and `limit` narrow
the read. `Analysis(...).changes("generation_cohorts")` follows immutable
declarations using the same restartable feed cursors as other analysis data.

```python
from rilldex import Workspace

ws = Workspace("study.sqlite", experiment="run-a")
evidence = ws.cohort_readiness(
    clock="run-a/generation", basis="generation batch",
    windows={"baseline": [0, 9], "current": [10, 19]},
    include_members=True,
    # monitor=monitor_id,  # include current saved semantic/metric receipts
)
rows = ws.sql("SELECT label, coordinate, sealed FROM generation_cohorts")
```

Each cohort separates declared members, pending generation, delivered sources,
complete captures, available rewards/success labels, saved monitor coverage and
reported execution attempts. Available outcome means are **partial-population
means**, not estimates for unseen members. Task-delivery mix is descriptive;
task identity alone is not a difficulty measure.

Reads use one transaction. Defaults return at most 100 cohorts (highest declared
coordinates) and 100,000 members, with `truncated` when more are omitted. The
maximum `limit` is 1,000; filter by clock and named windows for bounded studies.
Overlapping cohort membership is explicit and must not be summed as independent
samples. Environment subsets retain the whole cohort's pending count.

Source identities join independently of clock alignment. A different source
clock is valid but cannot be overlaid with the declared generation coordinate.
A different index on the same recorded clock and basis is a conflict and its
outcomes/measurements are excluded. Missing coordinates remain unrecorded.
Saved comparisons explicitly label declaration clocks that cannot be matched
to their source charts; similarly numbered learner and generation steps are
not assumed equivalent.

Native workspace SQL, JSONL exports, research SQLite datasets and capture
bundles retain the declaration table. Frozen research datasets support SQL over
that table; `cohort_readiness` needs the full live/restored workspace to join
source and monitor state. Old exports expose this table as unavailable rather
than inventing scheduled membership.

Declared membership still does not establish scorer closure, future training
non-use, representative task sampling, or a causal explanation. Use the existing
training-sample view to inspect recorded selections and learner use; it has a
different grain and is not collapsed into cohort rollout counts.

Native access requires no export:

```python
from rilldex import Workspace
from tracker.analytics import Analysis

workspace = Workspace("study.sqlite", experiment="my-run", observer="source")
comparison = workspace.compare_monitor(
    monitor_id, baseline=[20, 29], current=[30, 39], save=True
)
for cohort in comparison["cohorts"]:
    print(cohort["current"]["readiness"])

data = Analysis("study.sqlite")
lifecycle = data.execution_summary(
    experiment="my-run", kind="rollout",
    group_by=["environment", "backend", "policy_version"]
)
```

## Validation and remaining boundaries

Counterfactual controls cover early apparent improvement and deterioration with
the same final outcomes, a persistent regression, missing outcomes after capture,
capture failure, completed-only imports, lifecycle-only refresh, late revisions,
frozen comparisons and backward compatibility. A repeated 64-step/1,024-rollout
installed-package simulation checks the existing ingestion, restart, measurement,
comparison and restore path. These validate deterministic behavior on synthetic
inputs; they do not establish real-job causal diagnosis or semantic accuracy.

Still needed for stronger operational conclusions: a scheduler-declared batch or
population closure contract, complete request admission instrumentation, and
explicit bindings from execution attempts to generation windows and training
uses. Current charts cannot infer unreported requests from completed trace files.
