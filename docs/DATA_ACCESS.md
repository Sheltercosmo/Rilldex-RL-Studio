# Input, output and code-based research

The collector, analysis materializer and research consumer have independent
progress. Receiving a rollout does not imply its semantic analysis has finished.
Use **Connections → Export & code** for table previews and exports; use the Python
or CLI interfaces for custom analysis. These readers never schedule inference.

For execution and extension, see [Code-first research](CODE_FIRST_ANALYSIS.md):
`Analyzer` runs built-in projections without a UI, `Research` retains your custom
Python results in a separate SQLite database, `Results` reads/exports/resumes exact
batches without the source workspace, and `analysis database` creates
portable indexed SQL tables for independent tools and DuckDB/Parquet analysis.

Mixed/asynchronous jobs can report execution attempts independently of completed
traces: `Outbox.log_execution`, the `executions` table/feed and
`Analysis.execution_summary`. [Environment, backend and lifecycle contract](DISTRIBUTED_RL.md).

## Choose an input route

| Workflow | Route | Resume identity and practical boundary |
|---|---|---|
| Every emitted in-progress revision matters | `tracker.capture.Outbox.log()` with a background sender, or ordered `POST /api/ingest` envelopes | Producer + logical rollout + sequential revision. Outbox retains unacknowledged data; direct HTTP clients must implement retries and ordering. |
| Training already writes output | Watch native jobs, append-only JSONL, or JSON snapshots | Same producer, relative paths and workspace database retain cursors. Snapshot polling cannot recover overwritten intermediate content. |
| Results arrive per step, worker or evaluation stage | Immutable JSONL shards in one watched directory; `watch --once` between stages or continuous watching | Later shards join the same stream. Commit rows with newlines; publish completed files atomically. A shard is not an atomic multi-file transaction. |
| Workers cannot reach the collector | Export/import offline capture bundles and return receiving-workspace receipts | Uses the same packet identities as HTTP. Exporting a bundle alone does not acknowledge delivery. |
| One completed external artifact | Frozen file import | Identity belongs to exact artifact bytes. Do not repeatedly use this route on growing files that will also be watched. |
| Trainer facts arrive after rollouts | Outbox training records or the training-record HTTP/CLI route | Preserve sample identity/schema, explicit mappings and revisions. Arrival time is not learner step. |

Start with existing data and continue later with the **same** command scope:

```sh
rilldex --db workspace.sqlite watch ./shards --mode exports --producer run-a/worker-0 --experiment run-a --once
rilldex --db workspace.sqlite start --watch ./shards --mode exports --producer run-a/worker-0 --experiment run-a
```

For independent workers, keep separate producer namespaces. No Kafka, OTLP or
Arrow streaming receiver is implemented. Non-Python trainers can emit JSONL or
the HTTP contract without installing a trainer-specific integration.

## Choose an output

| Need | Interface | What it preserves |
|---|---|---|
| Live researcher interaction | Dashboard, rollout maps and investigation views | Latest materialized values and links to saved evidence. UI SSE is refresh notification, not durable history. |
| Pandas / Polars / DuckDB / notebooks | `Analysis.table()` or local read-only SQL | Relational rows, explicit missingness, denominators, source/graph/observer identities. Optional analysis libraries are not package dependencies. |
| Dataset for colleagues or downstream jobs | `analysis export` / UI ZIP download | Consistent database snapshot, JSONL or CSV tables, versioned manifest, counts, columns and hashes. |
| Resumable downstream processing | `Analysis.changes()` or `/api/analysis/changes` | Append receipts and consumer-managed cursors; analysis can arrive after source data. |
| Local background analysis dataset | `analysis sync results.sqlite --follow` | Append receipts and consumer cursors committed together in a separate SQLite database; restart the same command to catch up. |
| Full inspection workspace on another machine | Existing workspace snapshot / restore | Database, saved annotations, reviews, monitors and investigations. Analysis-table exports are not restorable workspace backups. |

## Python and SQL

```python
from tracker.analytics import Analysis

data = Analysis("workspace.sqlite")  # requires an existing database
print(data.catalog())
result = data.table("measurements", experiment="run-a", observer="source")
assert not result["truncated"]  # otherwise narrow scope or use bounded queries
# Optional: pandas.DataFrame(result["rows"])

with data.snapshot() as saved:
    # Both reads see the same committed state while capture continues.
    rollouts = saved.table("rollouts", experiment="run-a")
    edges = saved.table("edges", experiment="run-a")
```

Table names: `rollouts`, `revisions`, `sources`, `graphs`, `nodes`, `edges`,
`measurements`, `monitor_values`, `monitor_definitions`, `training_records`.
SQL views add the `rl_` prefix. Columns ending in `_json` preserve JSON text;
use `json.loads()` or SQLite JSON functions when necessary.

`table()` defaults to latest saved source and artifact versions. `history=True`
retains superseded versions. SQL exposes history by design: explicitly select
`is_latest=1` when estimating current behavior. Historical revisions must not
be counted as independent rollouts. With an experiment scope, monitor definitions
include those referenced by its saved results, including disabled monitors. Without
an experiment scope, definitions include all monitors. Monitor tables expose the
saved monitor name and observer alongside their identifiers.

```python
result = data.query("""
SELECT r.generation_step, m.metric, m.value, m.status,
       m.numerator, m.denominator, m.reason, m.run_id, m.source_hash
FROM rl_measurements m JOIN rl_rollouts r USING (run_id)
WHERE r.is_latest=1 AND m.is_latest=1
  AND r.experiment=? AND m.observer=?
ORDER BY r.generation_step, m.run_id, m.metric
""", ["run-a", "source"])
```

For a saved opportunity-ratio monitor, aggregate its recorded numerator and
denominator only after checking the definition and availability. Averaging
per-rollout ratios answers a different question from pooling opportunities.
`monitor_values` exposes both, its status/reason, `input_id` and `source_hash`.

Graph-based analysis can join exact directed endpoints:

```python
relations = data.query("""
SELECT e.graph_id, e.run_id, e.type,
       a.activity AS from_activity, b.activity AS to_activity,
       e.edge_json
FROM rl_edges e
JOIN rl_nodes a ON a.graph_id=e.graph_id AND a.node_id=e.source
JOIN rl_nodes b ON b.graph_id=e.graph_id AND b.node_id=e.target
JOIN rl_rollouts r ON r.run_id=e.run_id
WHERE r.is_latest=1 AND e.is_latest=1 AND e.observer=?
""", ["your-saved-observer"])
```

Join node identities **within the same graph**. Missing edges do not prove an
activity never happened, and `next_record` describes order rather than causality.
Queries are read-only, have a 10-second SQLite execution budget, a 32 MiB result
budget and a bounded row limit. Duplicate column names are rejected; use aliases.
Custom SQL executes locally through Python/CLI, not through a remote SQL endpoint.
Keep snapshot contexts short: long WAL readers can delay checkpoint reclamation.

CLI equivalents:

```sh
rilldex --db workspace.sqlite analysis catalog
rilldex --db workspace.sqlite analysis options --experiment run-a
rilldex --db workspace.sqlite analysis table measurements --experiment run-a --observer source
rilldex --db workspace.sqlite analysis sql --file analysis.sql --parameters '["run-a", "source"]'
rilldex --db workspace.sqlite analysis export run-a.zip --experiment run-a
rilldex --db workspace.sqlite analysis export measurements.zip --experiment run-a --observer source --profile measurements
```

Use your shell's normal quoting for JSON parameters. `analysis sql --query`
accepts inline SQL; a file is easier for multi-line work. JSONL exports preserve
null and numeric types. CSV retains JSON columns as quoted text and empty numeric
cells for nulls; status/reason remain separate columns. CSV text is not modified
for a particular spreadsheet application. JSONL is preferable for code pipelines.

Exports refuse existing destination filenames, row-limit truncation and byte
overflow. Default limits: 100,000 rows per table and 100 MiB uncompressed output.
The ZIP contains one database snapshot plus a manifest; it is not a live file.
Full normalized sources are opt-in (`--table sources`). Graph properties can
also contain source text; select tables according to the intended recipient.
Exports do not refresh stale measurements or independently validate annotations.

In **Export & code**, recorded experiments and observation sets are suggested from
saved data. Their counts describe saved records, not annotation completeness. An
observation set that has no results in a newly selected experiment stays selected;
the system never silently broadens the filter. **Previewed table only** is the UI
export default. CLI exports retain the all-research-tables default.
Selections are saved in the page URL, so returning from a graph or reopening the
link restores the same experiment, observation set, table and export settings.

Export profiles are `measurements` (values, definitions and rollout context),
`graphs` (nodes, edges, headers and rollout context), and `research` (all research
tables except full sources). `--table` and `--profile` are mutually exclusive.
`--observer` narrows graphs, measurements and monitor tables; rollout, revision,
source and trainer context remain scoped by experiment. The manifest explicitly
lists observer-filtered tables and context tables. Source context can therefore
contain rollouts without results from the chosen observer.

## Continuous output with durable consumer checkpoints

Feeds are independent: `sources` (new immutable source documents), `revisions`
(producer lifecycle receipts), `graphs` (saved headers), `measurements` (whole
measurement records), `monitor_values` (saved results), `training_records`
(schema 1 trainer facts), and `training_samples` (schema 2 facts).

Completion can change without a new source document. Follow `revisions` for
lifecycle and `monitor_values` for later computed results. Fetch graph nodes and
edges by the feed header's graph ID. Feed order is local insertion/receipt order,
never a training step, model checkpoint or causal order.

```python
page = data.changes("monitor_values", cursor=saved_cursor, limit=100)
for row in page["rows"]:
    process_idempotently(row["id"], row["document"])
save_cursor(page["next_cursor"])  # only after processing succeeds
# If has_more, drain the next page. Otherwise wait before polling again.
```

`saved_cursor`, processing and cursor storage belong to the consumer. Replaying
a page after a crash is intentional; deduplicate by receipt ID. Cursors check
their feed, row position and identity anchor; an incompatible or rewritten
workspace fails instead of silently skipping. They are scoped to the workspace
history and are not globally portable watermarks. Mutable review state, monitor
enable/disable switches and deletions are not change events in these feeds.

Read-only HTTP routes mirror table access and feeds:

```text
GET /api/analysis/catalog
GET /api/analysis/tables/measurements?experiment=run-a&limit=1000
GET /api/analysis/changes?feed=revisions&limit=100
GET /api/analysis/export?experiment=run-a&format=jsonl
```

Pass the returned cursor as URL-encoded JSON in the next changes request.
The CLI `analysis changes --feed revisions --cursor-file cursor.json` prints the
next page and next cursor. It deliberately does not advance a cursor file before
the downstream job has processed the rows.

## A local result mirror that resumes automatically

```sh
# Once per downstream batch (repeat while has_more is true):
rilldex --db workspace.sqlite analysis sync results.sqlite --feed revisions --feed monitor_values
# Catch up existing history, then poll for newly saved records:
rilldex --db workspace.sqlite analysis sync results.sqlite --feed revisions --feed monitor_values --follow
# Inspect committed progress; no server or model API is needed:
rilldex --db workspace.sqlite analysis sync results.sqlite --status
```

`--status` requires an existing mirror; a typo does not create a new database.

Omit `--feed` to consume all seven feeds. Each page's receipts and cursor commit in
one transaction. A failed page leaves neither partial receipts nor an advanced
cursor. Restart with the same source and destination; receipt identities prevent
duplicate inserts. Concurrent consumers cannot overwrite a cursor advanced by
another process. Feeds commit independently, so they may be at different positions.

```python
from tracker.analysis_mirror import FeedMirror
mirror = FeedMirror(data, "results.sqlite")
progress = mirror.sync(feeds=["revisions", "monitor_values"], pages=10)
print(mirror.status())

# Optional downstream analysis; use a read-only SQLite connection.
import sqlite3
from pathlib import Path
with sqlite3.connect(Path("results.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as conn:
    for row in conn.execute("SELECT feed, sequence, document_json FROM receipts ORDER BY feed, sequence"):
        print(row)
```

The mirror stores **append history**, not the latest workspace state. Receipt rows
include `feed`, `receipt_id`, `sequence`, `recorded_at`, `document_json` and `sha256`.
It does not execute downstream callbacks, provide exactly-once external side effects,
or capture mutable review edits and deletions. Graph feed records contain headers;
use table exports or the source workspace for their nodes and edges.

The destination is pinned to the source's resolved local path and feed anchors.
Moving the source requires a new mirror. It refuses to initialize over an unrelated
database. Batch sizes are bounded, but total stored history has no automatic quota
or retention policy. Remote HTTP consumers still manage their own checkpoints.

## Validation boundary

Contract tests cover continuous versus staged replay, exact relationships,
same-source lifecycle changes, missing-value fidelity, concurrent ingestion
during a pinned read, SQL write rejection, export integrity and cursor replay.
Installed-package smoke verifies the HTTP/CLI/Python path. These are functional
checks, not a sustained production-scale throughput benchmark. Source detection
and capture cannot manufacture missing token, tool, verifier or semantic evidence.
