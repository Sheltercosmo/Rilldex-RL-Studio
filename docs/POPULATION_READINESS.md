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
- `monitor-comparison/2` adds per-window `readiness`, structured `review` checks
  and frozen `execution_context`. Version 1 comparisons remain readable without
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
