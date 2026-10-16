# Code monitors with charts and feedback

Use a built-in measure or relationship query for standard questions. Use a Python
monitor when you need domain rules, arbitrary libraries, a native SQL query, or an
external service. Both paths publish to **Monitors**, with per-rollout curves,
coverage, window comparisons, case drilldowns and evidence links.

## Start from an existing workspace

Open **Add monitor → Advanced code** to generate a Python publisher for your
workspace and selected observation protocol. Name it, adapt the callback, and use
**Download .py** or **Copy Python**. The script registers the monitor, backfills
complete rollouts and follows new arrivals. Its values, coverage and feedback
appear in the same monitor registry as built-in measures. Python runs in your
worker environment; the browser supplies the template and displays results.

Install Rilldex in the process that can access your collector's SQLite database.
Run `python examples/live_custom_monitor.py --db workspace.sqlite` to backfill;
add `--follow` to continue as complete rollouts arrive. Restart the same command
after interruption: unchanged inputs are skipped. No UI session is required.

```python
from rilldex import Workspace

workspace = Workspace('workspace.sqlite', experiment='training-a', observer='source')
monitor = workspace.monitor(
    'Agent actions', version='1', unit='value', aggregation='mean',
    description='Recorded non-copied agent actions per complete rollout.')

def measure(ctx):
    actions = [event for event in ctx.run['events']
               if event['kind'] == 'action' and event['actor'] == 'agent'
               and not event.get('copied_context')]
    return {'value': len(actions), 'feedback': {
        'severity': 'info', 'summary': f'{len(actions)} agent actions recorded.'}}

print(monitor.run(measure))
monitor.follow(measure, interval=5)
```

Open **Monitors → Custom Python → View values** for feedback and details; **Show
chart** follows the same experiment and training coordinates as built-in monitors.
Pause/resume works in the UI. Re-registering the same code definition respects
that state. Change definitions in code, rather than disconnecting the publisher
through a UI definition edit.

## Inputs and outputs

The callback receives `ctx.run` (normalized source), `ctx.graph` (exact selected
property graph), `ctx.config`, and `ctx.workspace` (native SQL and analysis
functions). Select an explicit saved semantic observer in `Workspace` to use its
units and relationships. Missing/stale graphs and incomplete captures remain
pending; source-only measures need no semantic model.

| Aggregation | Return | Across a training step |
| --- | --- | --- |
| `mean`, unit `value` or `fraction` | `value` | Mean of measured rollouts |
| `opportunity_ratio`, unit `fraction` | `numerator`, `denominator` | Sum numerators / sum denominators |
| `incidence`, unit `fraction` | `value` of 0 or 1 | Fraction of measured rollouts flagged |

`feedback` accepts `severity` (`info`, `warning`, `critical`), `summary`, and optional
`next_check`. This is researcher-facing feedback; publication does not modify the
training job or send notifications. `details` accepts finite JSON; `evidence_ids`
must belong to the selected graph. Optional `unknown` counts unresolved
opportunities. Return `value=None` with a `reason` when evidence is unavailable.
A zero denominator is unavailable, not a zero rate. Callback exceptions become
durable error cases and do not stop other rollouts.

Results are bounded to 128 KiB each. Put large artifacts in your own storage and
return a reference in `details`. The server accepts result data, never executes
uploaded Python, and does not claim to validate the scientific correctness of a
custom calculation. User code runs with the permissions of its own worker.

## Cache, versions, and changing context

Definitions and results are immutable. Cache identity includes the definition,
source snapshot, selected graph, and explicit dependency revisions. Change
`version` or `config` when your algorithm changes. A new definition appears as a
separate monitor; pause the old version in the registry when appropriate.

If your function reads other rollouts, a reference dataset, or an external model,
include a revision for those inputs:

```python
monitor.run(measure, dependencies={'reference_set': 'evaluation-v3', 'attempt': 2})
```

The worker cannot infer external dependencies. Bump a dependency revision to
retry a recorded callback error. Repeating an identical publication is safe;
publishing a different result for the same basis is rejected. Old receipts stay
readable after later graph revisions. An old result is excluded from current UI
statistics until its new graph is measured. Already published rollouts are not
recomputed just because the browser refreshes.

## Remote compute and code analysis

For a worker that cannot access SQLite, use the authenticated collector API:

1. `POST /api/monitoring/monitors` with `definition` containing `name`,
   `kind: "custom"`, `observer`, optional `population`, and
   `custom: {version, description, unit, aggregation, config}`.
2. Obtain the current source snapshot and selected graph through the existing
   rollout/graph APIs. Retain their `source_hash` and graph `id`.
3. `POST /api/monitoring/custom-values` with `monitor_id`, `run_id`, `source_hash`,
   `graph_id`, optional `dependencies`, and `result`. The background service then
   updates the normal UI. Stale or conflicting publications are rejected.

Keep the server on a trusted/private connection and use the deployment's existing
authentication settings. A local worker needs only access to the database.

No export is required to query published data:

```python
rows = workspace.sql('''
    SELECT run_id, value, status, feedback_severity, feedback_summary,
           feedback_next_check, result_details_json
    FROM monitor_values WHERE monitor_id = ?
''', [monitor.id]).rows
```

`Workspace.table()` and `Workspace.sql()` select current-input monitor values by
default, using the same binding check as the dashboard. Native `measurements`
also defaults to observations matching the current source and declared map input.
A changed source, graph
or recorded monitor input leaves a coverage gap until its result is published.
Queries never run callbacks or request model inference.

Use `Workspace(path, history=True)` to inspect old receipts. In raw
`Analysis.query()` SQL, `rl_monitor_values.is_latest` identifies the published
index; `is_current` also checks applicability to the current inputs. Filter
`is_current = 1` for current measurements. These flags do not establish semantic
accuracy or a non-null value. A paused monitor can retain an applicable receipt;
join `monitor_definitions` and filter `enabled = 1` when only active definitions
are wanted. Join rollouts to measure coverage; an average of available values
alone hides unmeasured cases.

Reads use one committed database snapshot, so a concurrent graph update cannot
mix identities within a query. Portable datasets freeze flags at export time.
Older datasets without freshness flags expose them as unknown and retain their
receipts through `history=True`, rather than asserting that they are current.

Semantic metric records stay bound to their original evidence graph. A new map
with changed observations excludes the earlier value until a matching record
exists. A derived-only rebuild can reuse the value when its explicit semantic
input hash is unchanged. Independent source-based observers do not acquire a
map dependency merely because a graph exists. If an older worker finishes late,
`measurements.is_current` can identify a matching earlier publication while
`is_latest` identifies the late, incompatible one. Prefer `is_current` when
selecting values for a live analysis.

## Why these defaults

Six core starters cover logged reward, explicit success, reported tool errors,
exact repeated dispatches, response-link coverage, and the first comparable
recheck after failure. **Add core monitors** fills gaps in an existing registry
without duplicating an equivalent measure or resuming a paused monitor.
Fourteen recipes also include semantic verification, feedback reference,
work returns, procedure changes, and environment-episode measures. Semantic
starters require a selected observer. Each recipe states the evidence it needs;
missing evidence remains visible in coverage.

The design follows useful established patterns: [MLflow feedback assessments](https://mlflow.org/docs/latest/genai/assessments/feedback/)
keep a value and rationale attached to a trace, and [W&B's metric API](https://docs.wandb.ai/ref/python/experiments/run/)
lets code define/log metrics with explicit step axes. Rilldex binds each result
to its source and graph so those values can share relationship analysis and
rollout-map evidence with built-in measures.
In **Monitor management → Add monitor → Measure**, choose **Advanced code ·
Python**. The editor generates a script for the selected workspace, observer,
experiment and monitor name. Use **Copy Python** or **Download .py**, adapt the
callback, then run it beside the database. Publishing registers the monitor;
its values, feedback, charts and pause control appear in the normal UI. The
editor does not execute Python. **Custom code setup** opens this same flow.

