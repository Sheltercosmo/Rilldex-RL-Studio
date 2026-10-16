# Repeatable data workflows

Use a workflow when you want capture, saved SQL and exports to run together without
the UI. A workflow is a directory containing `rilldex.json` and `run.py`. A portable
package also includes the local runtime. Python 3.11+ is required; local file
capture and SQL need no extra packages, GPU or model key.

## Start from the app

- **Data & workflows → Setup & deploy**: choose local files, SSH or cloud storage,
  generate the setup, then download a runnable capture workflow.
- **Analyze & export**: choose an experiment, observation set, versions and export
  contents, then download an analysis workflow. This reads the existing database;
  it does not start a second collector.

Unzip on the machine that can access the source/database. Review `rilldex.json`:
relative paths start beside that file, not in the terminal's working directory.
Moving a workflow does not transfer its data or credentials. For remote analysis,
copy a research dataset or restore a workspace and update `database`.

```sh
python run.py --check   # local preflight; no collection or cloud requests
python run.py          # one batch, suitable after a training stage
python run.py --follow # existing + future data; Ctrl+C stops
python run.py status   # last durable capture / export report
```

Choose one run mode at a time. Repeat after restarting to reuse receipts and
completed outputs. `python run.py ui` serves the same workspace in a second
terminal using `ui_port` (the port selected in setup); this does not create a
managed collector for the workflow's source. Override with `python run.py ui
--port 9898`; add `--open` on a local desktop. Remote users forward the selected
loopback port over SSH. No public listener is created by the package.
The collector never starts or modifies training. For a S3/GCS workflow, install
its generated requirements with `python -m pip install -r requirements.txt` and
configure credentials on its host. Docker, notebooks
and offline worker transfer retain their dedicated setup instructions.

## Start entirely from code

After installing Rilldex, create a new directory for a growing JSONL job:

```sh
rilldex workflow init run-a --source ./outputs --mode exports --experiment run-a --producer run-a/worker-0
python run-a/run.py --follow
```

For native Harbor/SWE-agent directories, omit `--mode exports`. For rewritten
JSON snapshots, use `--mode snapshots`. Missing local source directories wait
without being created; they can appear when training begins. Output directories
and the workspace database must be outside the watched source tree.

For a database already maintained by another collector:

```sh
rilldex --db ./workspace/tracker.sqlite workflow init lab-analysis --experiment run-a
python lab-analysis/run.py
rilldex workflow package lab-analysis lab-analysis.zip
```

`workflow init` refuses an existing directory; `workflow package` refuses an
existing ZIP. The ZIP contains config, runner and runtime, not the database,
worker queues, environment secrets or source files. Keep secrets out of config.
The initial command reads a relative `--source`/`--db` from your terminal and saves
an absolute path; `--database` is explicitly relative to the workflow directory.

```python
from tracker.workflows import Workflow

with Workflow("./lab-analysis") as job:
    receipt = job.run()
```

## Define analysis once

Edit `queries` in `rilldex.json`; restart the runner after editing. Queries use
read-only SQL over the frozen `rl_*` tables, with optional positional parameters
and a result-row limit. Default queries summarize saved activity tags and
measurement availability; they do not infer new behavior or diagnosis.

Example query entry for saved relationships:

```json
{
  "name": "relation_counts",
  "sql": "SELECT observer, type, COUNT(*) AS edges FROM rl_edges GROUP BY observer, type ORDER BY observer, edges DESC",
  "parameters": [],
  "limit": 5000
}
```

The configured experiment, observer and version scope applies before queries.
Observer filtering retains rollout/trainer context for that experiment. Counts
describe captured evidence, not prevalence in unannotated data. Use `Research`
for custom Python calculations and resumable row batches; use `FeedMirror` for
each receipt rather than periodic complete snapshots. See
[code-first analysis](CODE_FIRST_ANALYSIS.md) for those APIs.

## Consume complete outputs

Read `results/latest.json` once. Its `generation` names an immutable directory:

| File | Use |
|---|---|
| `data.sqlite` | All scoped research tables, indexed for SQL joins |
| `analysis.json` | Saved query results, table counts and availability |
| `tables.zip` | The configured tables in JSONL or CSV, plus integrity manifest |
| `manifest.json` | Scope, table hashes, query definitions and capture timestamp |

All four files derive from one frozen read snapshot. `tables` selects ZIP contents;
the SQLite dataset retains all scoped research tables. Raw source documents are
omitted unless `sources` is explicitly selected. Missing semantic annotations
stay missing. Dataset capture time is not a training step or generation time.

```python
import json
from pathlib import Path
from tracker.research import Analysis

outputs = Path("lab-analysis/results")
pointer = json.loads((outputs / "latest.json").read_text())
dataset = outputs / pointer["generation"] / "data.sqlite"
rows = Analysis(dataset).table("measurements")["rows"]
```

The runner publishes `latest.json` atomically only after all outputs succeed.
Bad SQL, truncated query results, export limits and failed publication leave the
previous generation intact. Accepted input remains durably collected. A partial
JSONL tail or deferred source file does not block valid records: receipts report
`pending: true`, and the runner retries it on the next pass. A one-off run exits
with code **2** while capture remains pending; code **1** means an error; **0**
means no pending capture. Follow mode retains operation errors in `status.json`
and continues: publication errors retry on the next export cycle, while source
errors retry on the next capture cycle. Bad configuration or competing ownership
fails at startup. Restart after editing configuration. Ctrl+C and SIGTERM unwind
open operations and release ownership; accepted receipts remain durable.

Unchanged live databases skip copying during the same run. After restart, table
hashes reuse an existing generation and its saved calculations. Collector caches
and durable cursors avoid reimporting accepted rows. Keep the producer, database
and source identity stable. Separate workflows must not compete for the same
producer or output directory; OS locks prevent simultaneous writes.

This is a bounded single-host workflow, not a cluster scheduler. Snapshot limits
are 1 million rows per table / 1 GiB; ZIP limits are 100,000 rows per table /
100 MiB. Queries are read-only, time/size limited and refuse truncation. The
default capture polling interval is 10 seconds. Newly generated workflows publish
on startup, then every 5 minutes. `interval` controls polling; `publish_interval`
controls publication. Choose 1 / 5 / 15 minutes when downloading, or set seconds
in the config. `workflow init --publish-every 900` is the code-only equivalent.
Existing configs without `publish_interval` keep their per-cycle publication.
These are delays between operations, not real-time latency guarantees: capture
and publication run serially. A follow cycle drains one bounded capture pass so
backlogs do not starve publication; batches drain up to 100 passes and report
remaining backlog. Use receipt feeds for incremental consumers at larger scale.
Old generations are retained for reproducibility and are not automatically
deleted. Keep these generated files immutable and manage disk retention explicitly.

## Operate unattended

`--check` verifies config boundaries, read access to an existing database, local
source type/access, parent write access and required cloud client installation.
It exits **0** when locally ready, **2** when waiting for a future source, **1**
when blocked. It does not fetch cloud objects, test credentials or execute your
saved SQL. A missing source can also indicate a missing mount; it is never
silently created. Actual capture validates records and exposes deferred errors.

`results/status.json` is updated atomically around each operation. It separates
capture state from publication state; a successful capture cannot erase an
unresolved export error. It includes host, PID, last capture check, last complete
generation and bounded source issues. `python run.py status` adds report age,
config-match and overdue-heartbeat flags. An overdue report can mean a long
operation or an interrupted process; it does not prove the process died.
`latest.json` is a dataset pointer, not a runner-health signal.

For a scheduled CPU job, run the same absolute `run.py --follow` path under your
existing job manager. Hold one owner per producer/database and output directory;
locks remain held between polls. SIGTERM stops without forcing an expensive final
export. Resume with the same command, or run one batch to publish the latest
accepted data. SIGKILL/power loss cannot write a stopped report, so stale status
is expected. No automatic scheduler submission or restart is implied.

Use local disk for live SQLite and cloud caches. Do not point multiple hosts at a
live SQLite file on NFS, Drive or another network filesystem. Send worker packets
through the HTTP/outbox route, or transfer a frozen dataset/workspace backup.
An object-storage prefix is a read-only source; it is not the live database.

These choices follow [verl's trace-volume guidance](https://verl.readthedocs.io/en/latest/advance/rollout_trace.html),
[OpenTelemetry's durable receive/export separation](https://opentelemetry.io/docs/collector/resiliency/),
[SQLite's WAL constraints](https://www.sqlite.org/wal.html), and
[Slurm's termination lifecycle](https://slurm.schedmd.com/sbatch.html).
This package does not inherit those projects' scale or operational guarantees.
