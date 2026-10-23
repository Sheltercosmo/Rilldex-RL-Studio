# Code-first research

Use saved observations as data, run built-in analyses without a server, and add
your own Python analyses. Nothing in this workflow requires opening the UI or
calling a model. A custom callback runs in your Python process with your normal
environment and dependencies.

## Start with the live workspace

No export, server or browser is needed. After installing Rilldex, point Python at
the same local database used by capture:

```python
from rilldex import Workspace

ws = Workspace("study.sqlite", experiment="run-a", observer="reviewed")
result = ws.activity_counts()
result.rows                         # dictionaries + coverage metadata on result
frame = result.to_pandas()           # optional pandas; refuses truncated results
links = ws.relations(target_activity="revise")
series = ws.metric_series("recorded_reward")
```

The observation-set name must match saved data. `ws.options()` lists experiments
and saved sets; `ws.catalog()` describes SQL tables, columns and row meanings.
Source-only traces have no
semantic unit tags; an empty activity result is not evidence of absent behavior.
Every call reads fresh committed data. Joins and coverage counts within a call
share one short SQLite read snapshot. Training can continue writing to WAL.

`ws.rollouts()`, `ws.units()`, `ws.graphs()` and `ws.metrics()` return records;
`ws.table("training_records")` and `ws.table("executions")` expose trainer and
serving context. Scalar keyword filters are parameterized equality conditions.
JSON fields such as `metadata_json`, `node_json` and `details_json` become
`metadata`, `node` and `details` dictionaries in returned records. Scalars,
nulls, statuses, reasons, versions and evidence IDs retain their meanings.

```python
rows = ws.sql("""SELECT activity, COUNT(*) AS units
                 FROM nodes WHERE kind='unit'
                 GROUP BY activity""").rows
graph = ws.graph(ws.graphs().rows[0]["graph_id"])
edges = graph.connections(graph.nodes[0]["id"], direction="both")
network = graph.to_networkx()  # optional networkx.MultiDiGraph
```

SQL's named relations (`rollouts`, `nodes`, `edges`, `measurements`, etc.) use
the Workspace scope. Low-level `rl_*` views remain unscoped escape hatches;
filter them explicitly. Nodes join on **graph_id AND node_id**; multiple typed
edges between the same endpoints are preserved. `graph()` requires an explicit
saved version and refuses partial/dangling graphs. Temporal links are not causes.
Use `history=True` when intentionally querying superseded source or graph versions.

For branch effort and decision-to-action evidence, use the same projection as
**Plans & attempts**, directly on an exact saved graph:

```python
work = ws.work_structure(graph.graph_id, cutoff_event_id=None)
windows = work["decision_windows"]
resumes = [w for w in windows if "resume" in w["decision_types"]]
for window in resumes:
    print(window["label"], window["status"], window["counts"])
```

Each window retains its decision, scope bindings, action roles and feedback
witnesses. Unmapped or conflicting evidence has `counts=None`; zero linked
actions does not establish an ignored decision. The optional cutoff is a source
event ID. See [definitions and limits](WORK_STRUCTURE_MEASURES.md#decisions-and-recorded-follow-through).

For request-to-evidence inspection, use the same data as **Rollout story →
Requested checks & evidence**:

```python
review = ws.request_evidence(graph.graph_id)
for row in review["rows"]:
    if row["clause"]["kind"] == "requested_check":
        print(row["clause"]["text"], row["state"], row["coverage"])
        print(row["counts"]["response_choices"])
        # Exact source links, action identity and request-version identity:
        print(row["responses"])

followups = ws.feedback_followthrough(graph.graph_id)
```

These functions read saved judgments, never invoke a model, and do not require
an export. A sufficient response supplies answering evidence; it need not be a
passing result. `no_answer`, `unresolved`, missing review, and an operation with
no recorded response remain different states. Superseded clauses keep their own
evidence. Requirements and attributed claims are outside this check observer.
Older graphs may retain only positive links; their negative-review coverage is
unknown. The optional `cutoff_event_id` limits source evidence, not the time at
which annotations were produced. Partial graphs are rejected.

The local HTTP equivalents are `/api/request-evidence?graph=GRAPH_ID` and
`/api/feedback-followthrough?graph=GRAPH_ID`; append `through=EVENT_ID` for a
source cutoff or `download=1` for an optional JSON download. The source and
observer versions remain pinned to the supplied graph ID.

To retrieve earlier source passages for a particular claim before annotating a
relationship, use `ws.search_evidence(run_id, anchor={"event_id": event_id},
text="a focused evidence question")`. Results retain source offsets, native
call/response context, omissions and a continuation cursor. Set an explicit page
budget; see [bounded evidence retrieval](SOURCE_EVIDENCE.md#continue-with-an-explicit-budget).
This is candidate retrieval, not an automatic semantic judgment.

Built-in functions are discoverable through `Workspace.functions()`:
`activity_counts`, `relation_counts`, `metric_availability`, `recorded_outcomes`.
The Analyze page and `rilldex --db study.sqlite analysis compute activity_counts`
call these same functions. The UI provides a bounded snapshot, not a streaming
materialized view. Export is an optional transfer/reproducibility operation.

## Save your own function without managing another path

```python
def my_measure(row, config):
    return {"verified": row["verified_success"]}

batch = ws.evaluate("my_measure", my_measure, version="1")
rows = ws.results().results(batch["id"])
```

`evaluate` captures scoped inputs, releases the read transaction, then runs your
Python callback. It uses the existing versioned Research cache and retained batch
provenance, reusing unchanged inputs. Pass `sql`, `parameters`, `key_columns`,
`config` and `limit` for a different row grain. Duplicate/null keys and truncated
inputs are rejected. Version your callback and external dependencies explicitly.
Callbacks run only in your own Python process; the HTTP UI never executes code.

Results are managed in `study.analysis.sqlite` beside `study.sqlite`. The app
lists these under **Analyze → Write your own Python analysis**. That list covers
the whole workspace, not only the active UI scope. The sidecar separates custom
writes from immutable source evidence. The existing workspace backup does not include this sidecar. Retain it separately;
after moving paths, read old batches with `Results(sidecar_path)` below. Workspace
refuses to attach results whose recorded source path differs from its database.
Advanced callers can still choose another result path with `Research` below.

For code-only collection, the essential command is:

```sh
rilldex --db study.sqlite watch ./outputs --mode exports --experiment run-a --producer run-a/files
```

This reads existing and future JSONL records into the live database, without
publishing dataset copies. Keep the same producer/database to resume. The output
directory must exist; use the workflow runner when waiting for a future directory
is needed. Omit `--mode exports` for native Harbor/SWE-agent folders; use `--once`
for a batch. The UI is optional: `rilldex --db study.sqlite serve`.

## Storage choice and interoperability

The live implementation remains SQLite/WAL with indexed relational graph tables
and versioned JSON evidence. It fits transactional capture plus concurrent local
readers; it does not claim multi-host write scaling. Keep active databases off
network filesystems. Remote workers use the existing HTTP/outbox route.
For analytical transforms use ordinary SQL or optional pandas/Polars; for graph
algorithms use NetworkX. These adapters work on bounded in-memory results without
requiring a dataset export. Heavy historical jobs can still use the existing
DuckDB/frozen-dataset path. We have not replaced the database or added a new query DSL.

Design references: [SQLite WAL](https://www.sqlite.org/wal.html),
[DuckDB concurrency guidance](https://duckdb.org/docs/lts/connect/concurrency),
[Ibis's separation of query expressions and execution](https://ibis-project.org/tutorials/basics),
and [NetworkX directed multigraphs](https://networkx.org/documentation/stable/reference/classes/multidigraph.html).

## Code interfaces

| Interface | Purpose | Storage |
|---|---|---|
| `rilldex.Workspace` | Start here: scoped functions, decoded records, graphs and custom Python results | Live workspace; managed result sidecar for custom functions |
| `Analysis` | Query sources, units, directed relations, measurements and trainer facts | Read-only live workspace or frozen research dataset |
| `Analyzer` | Execute the same deterministic, dependency-aware projections as investigations | Existing workspace; versioned cached outputs and saved plans |
| `Research` | Run arbitrary custom Python on SQL-selected evidence, retain results and resume | Separate researcher-owned SQLite database |
| `Results` | Inspect, page, export or finish a retained batch without the source workspace | Existing researcher-owned result database |

The live workspace keeps transactional ingestion in SQLite/WAL. Its graph is
represented by indexed nodes and edges, keyed by **graph ID + node/edge ID**.
Relationships, JSON properties, observer versions and source hashes remain data.
Recursive SQL and graph libraries can use them without reading a visualization.
No graph server or second service is required. Heavy analysis can use a frozen
SQL dataset, or transfer selected typed columns to DuckDB/Parquet.

## Run built-in analysis

To check whether a correction or changed observer alters a conclusion, use
`workspace.annotation_changes(baseline_graph_id, current_graph_id,
requirements=[...])`. It compares source-aligned units and reruns your explicit
graph requirements, retaining changed denominators and evidence cases. This is
read-only analysis over saved versions, with no export or inference.
[Example and interpretation](ANNOTATION_CHANGES.md).

```python
from tracker.research import Analysis, Analyzer

data = Analysis("workspace.sqlite")
analyzer = Analyzer("workspace.sqlite")
operations = analyzer.operations()  # definitions, grain, required evidence, limits
graphs = data.table("graphs", experiment="run-a", observer="my-observer")
assert not graphs["truncated"]
g = graphs["rows"][0]  # select a graph with the evidence your operation requires

check = analyzer.run("retry_outcomes", g["run_id"], graph_id=g["graph_id"], check=True)
result = analyzer.run("retry_outcomes", g["run_id"], graph_id=g["graph_id"])
print(result["outputs"]["observation"])
print(result["execution"])  # computed / cache_hits / inference_calls
retained = analyzer.saved(result["id"])  # exact outputs, no execution
print(analyzer.saved_plans())
```

Preflight checks source identities and required evidence presence; it does not
certify annotation accuracy or measurement readiness. `retry_outcomes` expands
its state/recovery dependencies automatically. Missing outcomes stay unknown.
Graph-consuming operations require an explicit saved graph; the SDK never
silently substitutes source events for semantic observations. Source-only
operations such as `declared_plans` do not require a graph argument.

```sh
rilldex analysis operations
rilldex --db workspace.sqlite analysis run retry_outcomes --run-id RUN_ID --graph-id GRAPH_ID --check
rilldex --db workspace.sqlite analysis run retry_outcomes --run-id RUN_ID --graph-id GRAPH_ID
rilldex --db workspace.sqlite analysis saved-plans
rilldex --db workspace.sqlite analysis saved PLAN_ID
rilldex --db workspace.sqlite analysis plan analysis-plan.json --check
```

Use `analyzer.plan(...)` to obtain the dependency-plan JSON, add explicit
comparison nodes if needed, and pass it to `analyzer.execute(plan)`. CLI JSON
plans select registered operations; they do not load executable plugins. Advanced
local developers can also use the existing `analysis_registry.Registry` and
`investigation_plans.execute(..., registry=...)` for typed custom DAG operators.

Semantic extraction remains a separate explicit workflow (`rilldex semantic
prepare/run/register`). These APIs only use saved evidence. They do not enable
paid extraction, invent missing semantic tags, or bypass its budgets.

## Add your own analysis layer

This example applies a researcher-defined threshold to a **saved ratio monitor**.
Select its monitor ID through `data.table("monitor_definitions")` and inspect its
definition before choosing a threshold. This rule is an example, not a built-in
claim about recovery quality.

```python
from tracker.research import Research

lab = Research("workspace.sqlite", "my-analysis.sqlite")
sql = """
SELECT v.value_id, v.run_id, v.monitor_id, v.source_hash, v.input_hash,
       v.value, v.status, v.reason, v.numerator, v.denominator
FROM rl_monitor_values v JOIN rl_rollouts r USING (run_id)
WHERE r.is_latest=1 AND v.is_latest=1 AND v.monitor_id=?
ORDER BY v.run_id
"""

def my_rule(row, config):
    if row["status"] != "available" or row["value"] is None:
        return {"flag": None, "status": "unavailable", "reason": row["reason"]}
    if row["denominator"] is None or row["denominator"] < config["minimum"]:
        return {"flag": None, "status": "insufficient_support"}
    return {"flag": row["value"] < config["threshold"], "status": "available"}

batch = lab.evaluate(
    "my-recovery-rule", "1", sql, my_rule,
    parameters=["YOUR_MONITOR_ID"], config={"minimum": 5, "threshold": .5},
    key_columns=["run_id", "monitor_id"], limit=100000,
)
assert batch["status"] == "complete", batch
rows = lab.results(batch["id"])
assert not rows["truncated"]
```

Callbacks return a JSON object: scalar measurements, structured findings, arrays
of cases, custom node/edge records, or a combination. These remain **your layer**;
they do not overwrite verified observations or acquire their semantic authority.
Keep evidence IDs, status, missing-value reasons and relevant denominators in
your inputs/outputs. Unknown should remain null, not an inferred negative.

The runner records the complete selected input row before calling your function.
Its cache includes the name/version, SQL/parameters, configuration, and exact
input content. A changed row, query, config or version causes new computation.
Successful unchanged rows are reused, including after restart. Failures remain
visible and are retried on the next call. A truncated selection or duplicate/null
input identity fails **before any callback**, so an accidentally incomplete
population cannot be presented as a complete batch.

Include **all dependencies** in the SQL row or versioned config. For example,
selecting only `run_id` will not detect a new annotation of the same source;
select `graph_id`, `annotation_hash`, and relevant properties/results as well.
Change the version when changing callback logic or external dependencies. The
runner does not discover hidden closure state, files, endpoints or model versions.
Do not include credentials in persisted configuration.

One evaluator owns a result database at a time, using an OS lock released by
process exit. Readers can continue. Successful rows commit independently; a
crash between callback completion and commit may repeat that callback. Use pure
functions or make external side effects idempotent. Output and item completion
commit together. Interrupted batch membership is retained. Choose explicitly
between finishing its original population and evaluating the current population.
This is not a distributed scheduler or an exactly-once external execution system.

## Resume the exact batch, even offline

```python
from tracker.research import Results

saved = Results("my-analysis.sqlite")  # original workspace may be offline or moved
recent = saved.batches(limit=20)
batch_id = recent["rows"][0]["id"]
status = saved.batch(batch_id)
print(status["definition"], status["counts"])

# Only when you intend to execute your callback again:
finished = saved.resume(batch_id, my_rule, version="1")
```

`resume` uses the **same batch ID, exact saved inputs and original configuration**.
It does not rerun SQL, add newer rollouts or drop an older source revision.
Successful rows reuse their results; failed and pending rows retry. Input,
definition and cache identities are checked. A different supplied version is
rejected: changed logic belongs in a new `Research.evaluate` definition.
The version is your assertion about the callback; it is not a code fingerprint.
Resume updates the batch's current failure/error state; it is not an attempt log.

`evaluate` captures a **new current population**. This distinction matters when
training advances while a batch is interrupted. `Research(...).resume(...)` works
too; `Results(...)` avoids any dependency on the original source path.

Progress counts distinguish pending, failed, computed and reused items. The
`running` status is the last saved state, not a process heartbeat; an abrupt kill
can leave it recorded until recovery. Resume and evaluate share one evaluator
lock, while readers remain available. Opening results or listing status never
starts computation.

## Follow without duplicate unchanged batches

```python
batch = lab.evaluate(
    "my-recovery-rule", "1", sql, my_rule,
    parameters=["YOUR_MONITOR_ID"], config={"minimum": 5, "threshold": .5},
    key_columns=["run_id", "monitor_id"], limit=100000, skip_unchanged=True,
)
if not batch["unchanged"]:
    print(batch)  # process the new batch
```

With `skip_unchanged=True`, identical ordered membership and input content reuse
the latest **complete** batch for that definition. Its ID and `captured_at` stay
unchanged; `checked_at` records this check. The runner still queries current data
and checks saved results, but writes no duplicate batch and runs no callback.
Changes to input content, order, membership or definition create a new batch.
Incomplete batches are never skipped. Use `resume` to retry one in place.
Without this option, each `evaluate` records a new selection, even when all row
results are cached. Use a deterministic `ORDER BY` in polling queries.

## Query custom results with existing evidence

```python
answer = lab.query("""
SELECT r.experiment, r.generation_step, i.input_key_json,
       i.status execution_status,
       json_extract(o.output_json, '$.flag') flag,
       json_extract(o.output_json, '$.status') finding_status
FROM custom.research_batch_items i
LEFT JOIN custom.research_results o ON o.id=i.result_id
LEFT JOIN rl_rollouts r ON r.run_id=json_extract(i.input_json,'$.run_id')
WHERE i.batch_id=? ORDER BY i.ordinal
""", [batch["id"]])
```

`research_definitions` retains definitions/configuration. `research_batches`
retains selection timestamps and completion status. `research_batch_items`
retains exact membership, input rows, failures and result links.
`research_results` retains successful outputs and hashes. These are ordinary
SQLite tables, readable with `sqlite3`, R, database clients or your own service.
`custom.` is their attached schema name inside `lab.query()`; omit it when
opening `my-analysis.sqlite` directly. You can create your own additional tables
there using SQLite; reserved `research_*` tables belong to this runner.

Always select a batch when computing a population statistic. Summing every
historical cached result double-counts revised inputs. A live join can show newer
source context than the selected batch: use the saved `input_json` for exact
historical input. Source and result databases have independent commit clocks.

## Inspect and share results without the source

```python
saved = Results("my-analysis.sqlite")
page = saved.results(batch_id, limit=500)
while True:
    consume(page["rows"])  # includes failed/pending rows with null outputs
    if not page["truncated"]:
        break
    page = saved.results(batch_id, limit=500, after=page["next_after"])

own_rows = saved.query("""
SELECT i.ordinal, i.status, json_extract(r.output_json,'$.flag') flag
FROM research_batch_items i
LEFT JOIN research_results r ON r.id=i.result_id
WHERE i.batch_id=? ORDER BY i.ordinal
""", [batch_id])
saved.export(batch_id, "my-findings.zip")
```

Paging uses stable item ordinals; `batches` uses `next_before` to page older
selections. Individual pages are separate read snapshots and can reflect a resume
in progress. Export uses one consistent snapshot: `manifest.json` records the
definition, source path, capture/completion state and counts; `results.jsonl`
contains input objects, outputs, IDs, hashes and execution errors. Failed/pending
cases remain in the population. The file hash covers the JSONL bytes. Exports
refuse overwrites and partial publication, with a default 100 MiB row-data budget.
Source text and custom configuration in the inputs are included; this is not a
redaction or anonymization step.

```sh
rilldex analysis results my-analysis.sqlite batches --limit 20
rilldex analysis results my-analysis.sqlite batch BATCH_ID
rilldex analysis results my-analysis.sqlite rows BATCH_ID --limit 500
rilldex analysis results my-analysis.sqlite rows BATCH_ID --after 499 --limit 500
rilldex analysis results my-analysis.sqlite sql --query "SELECT name,version FROM research_definitions"
rilldex analysis results my-analysis.sqlite export BATCH_ID my-findings.zip
```

These commands need no `--db`, UI or original workspace. SQL is read-only and
has the same row, byte and time bounds as the evidence query interface. An unknown
batch or missing result database is an error; reading never creates an empty one.
ZIP exports are for downstream analysis, not executable/resumable databases. To
move the complete result database while a writer is active, use SQLite's backup
API; copying only the `.sqlite` file may omit committed WAL data:

```python
import sqlite3
from contextlib import closing
from pathlib import Path

source_uri = Path("my-analysis.sqlite").resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(source_uri, uri=True)) as source:
    with closing(sqlite3.connect("shared-results.sqlite")) as destination:
        source.backup(destination)
```

Open the copy with `Results` for offline reading/resume. Source joins and new SQL
selections through `Research` still require the originally bound workspace path;
moving a result database does not implicitly rebind it to unrelated evidence.

The runnable `examples/custom_monitor_policy.py` supports one-shot and `--follow`
analysis. Run the same script after staged imports, in a notebook, or alongside
the collector. Follow prints the initial state and subsequent changed batches;
unchanged polls do not grow the result history. Resume uses the saved configuration:

```sh
python custom_monitor_policy.py run workspace.sqlite my-analysis.sqlite MONITOR_ID --follow
python custom_monitor_policy.py resume my-analysis.sqlite BATCH_ID
```

Bound the population by experiment/step/window for large jobs.
`Research` selects up to 100,000 rows / 32 MiB per batch and has the existing
10-second SQL budget. It closes its read snapshot before running callbacks.
Changed batch records accumulate; there is no automatic retention policy. Use
separate result files per study/window when that fits your workflow.

## Portable database, no application required

```sh
rilldex --db workspace.sqlite analysis database run-a.sqlite --experiment run-a --observer my-observer
```

Or `data.database("run-a.sqlite", experiment="run-a", observer="my-observer")`.
The file contains physical indexed `rl_*` tables and a `research_snapshot`
manifest with scope, capture time, row counts, column names, grain and content
hashes. All tables come from one committed source snapshot. No server, extension,
SQL-view installation or Jev package is needed to read it:

```python
import sqlite3
from contextlib import closing

with closing(sqlite3.connect("run-a.sqlite")) as connection:
    rows = connection.execute("""
      SELECT e.graph_id,e.type,a.activity,b.activity
      FROM rl_edges e
      JOIN rl_nodes a ON a.graph_id=e.graph_id AND a.node_id=e.source
      JOIN rl_nodes b ON b.graph_id=e.graph_id AND b.node_id=e.target
    """).fetchall()
    # Optional: pandas.read_sql_query(sql, connection)
```

Defaults: latest versions, all observers unless selected, no full source documents.
Use `--history` and `--include-sources` explicitly. Omitted `rl_sources` exists as
an empty table and is marked `included: false`; graph properties can still contain
source text. Frozen datasets work with `Analysis` and `Research` but cannot run
the original built-in execution engine or supply live change feeds. They contain
research tables, **not all application internals or a restorable workspace**.
Read full saved built-in outputs with `Analyzer.saved()` or use a workspace archive.

Exports stream in batches, refuse replacement/partial publication and default to
1,000,000 rows per table, 1 GiB serialized data and a 120-second source-read budget.
Narrow scope for large workspaces. The existing JSONL/CSV export and resumable
change feeds remain available. A snapshot of a snapshot cannot recover omitted
data; the parent manifest is retained.

## DuckDB, Parquet and graph tools

DuckDB can read the frozen SQLite file and write typed Parquet for larger scans.
Its optional SQLite extension may need an initial network download. The base
package does not install or depend on DuckDB. SQLite preserves heterogeneous
scalar values; import as strings and explicitly cast the columns you analyze:

```sql
INSTALL sqlite;
LOAD sqlite;
SET sqlite_all_varchar=true;
ATTACH 'run-a.sqlite' AS evidence (TYPE SQLITE, READ_ONLY);
COPY (
  SELECT run_id,metric,CAST(value AS DOUBLE) AS "value",status,source_hash
  FROM evidence.rl_measurements
  WHERE metric='recorded_reward'
) TO 'reward.parquet' (FORMAT PARQUET);
```

Use strict `CAST` so malformed fields fail visibly. The optional executable
`scripts/research_duckdb_smoke.py` checks numeric round-trip and graph endpoints.
For NetworkX, use `(graph_id,node_id)` as the node key and a `MultiDiGraph` to
retain parallel typed edges. For bounded graph paths, use `WITH RECURSIVE` over
`rl_edges` with explicit relation types, graph ID, a depth limit and cycle control.
Temporal `next_record` edges do not establish causality.

The built-in UI continues to inspect the same workspace and its saved graphs.
Custom result files are not automatically rendered as dashboard monitors or
merged into semantic graphs. Use the IDs in your results to open existing maps,
or build a dedicated visualization in your notebook. That publication boundary
prevents an arbitrary custom score from silently becoming a product metric.

## Behavior comparisons

Compare saved observations directly, with no model calls or export:

```python
ws = Workspace("study.sqlite", experiment="training-run", observer="my-observer")
capture = ws.compare_behavior(lens="procedure", a_start=0, a_end=9,
                              b_start=10, b_end=19, save=True)
original = ws.compare_behavior(saved=capture["id"])
followup = ws.compare_behavior(parent_id=capture["id"], save=True)
```

Omit `save=True` for a live snapshot. Saved captures retain counts, coverage and
graph links; follow-ups use the original task, annotation version and windows.

## Practices borrowed and choices made

For interpreting changing curves, [Population readiness](POPULATION_READINESS.md)
documents the monitor comparison's source states, measurement gaps, task/policy
selection checks and execution context. `Workspace.compare_monitor(...)` returns
the same frozen evidence used by the UI. `Analysis.execution_summary(...)` reads
reported attempts, duration and output-token coverage directly from the database.
Neither method infers a closed population from completed-only imports.

- [Phoenix's client](https://arize-phoenix.readthedocs.io/projects/client/index.html)
  exposes traces and annotations programmatically, including custom results.
  We adopt evidence-linked results and separate read/compute/persist steps.
- [Inspect Scout results](https://meridianlabs-ai.github.io/inspect_scout/results.html)
  retain scan configuration, membership, errors and result data, with explicit row
  grain. We apply those ideas to exact SQL input batches and resumable results.
- [MLflow's saved-trace evaluations](https://www.mlflow.org/docs/latest/genai/eval-monitor/running-evaluation/traces/)
  reuse captured traces with built-in and custom scorers. Our built-in operations
  likewise reuse saved evidence; custom code is independent of collection.
- [DuckDB's SQLite extension](https://duckdb.org/docs/current/core_extensions/sqlite)
  and [Parquet support](https://duckdb.org/docs/current/data/parquet/overview)
  provide an optional path from portable operational data to columnar analysis.

These are adapted design practices, not copied implementations or claims of
feature parity. SQLite is the practical default for transactional receipts,
indexed adjacency and local deployment. A managed graph service, distributed
catalog or automatic lakehouse would add operational requirements not justified
by the tested workload. Large-scale throughput and cloud/multi-host scheduling
remain unvalidated; the open tables allow those consumers without changing the
trace and graph identities.
