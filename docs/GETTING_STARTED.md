# Start and resume RL inspection

**Choose your input and output:** [continuous capture, staged batches, exports,
Python/SQL analysis and resumable result feeds](DATA_ACCESS.md). In the app, open
**Data & workflows → Analyze** to query, preview and export saved research tables.

**Choose your environment first:** [Ubuntu/Windows/macOS, Docker, remote GPU hosts, S3/GCS and Colab/notebooks](DEPLOYMENT.md). That guide covers existing + future output, stop/restart, persistent storage and recovery after runtime loss. The in-app **Connections** page links directly to each setup.

Use a separate collector environment with Python 3.11+. The package has no mandatory trainer, GPU, Node, model-provider or external-database dependency. Install this checkout with `python -m pip install .`, or build a wheel with `python -m pip wheel --no-deps --wheel-dir dist .` and install that wheel on the collector machine. An already-built wheel can be installed with `pip install --no-index --no-deps path/to/rilldex-0.1.0-py3-none-any.whl` in an offline environment.

The same CLI is intended for Windows, Linux and macOS. The current installed-wheel audit ran on Windows/Python 3.12; the added CI matrix covers all three operating systems and Python 3.11–3.13, but is not evidence of a completed remote CI run.

## First launch

After launching, use **Data & workflows → Setup** to generate commands for your
environment and training stage. For a headless machine, `python -m rilldex setup
--case remote` prints a plan without starting anything. Restricted jobs can use
[offline capture bundles with returned receipts](DEPLOYMENT.md#offline-workers-and-artifact-handoff).

For existing output, use **Detect output**, apply a suggested layout, then
**Check source**. CLI: `python -m rilldex discover /path/to/outputs`. Discovery
does not import records or start model inference; unresolved formats remain
visible instead of being treated as ready.

**Check source** also shows the decoded rollout: source text, actions and their
recorded responses. Select a sampled rollout; use **Result for…** to locate the
corresponding action. The preview shows up to 12 events per rollout and 700
characters per event, with omitted content counted explicitly. For repeated
rollout identities it uses the highest revision found in the bounded sample.
Checking does not save data, advance collection or call a model.

Choose **Connect & watch** to follow existing and new output. The connected-source
panel updates with received rollouts and links to their source maps and recorded
experiments. Its URL retains the source selection across refreshes; **Check this
source** reloads its saved settings for another preview. Each connection has its
own recent receipts, so other busy workers do not displace its links. Semantic
maps and behavior measures still require saved observations.

```sh
rilldex doctor --port 0
rilldex start --open
```

The application is at `http://127.0.0.1:8765`. `--port 0` selects a free port and prints its URL. `--open` is optional; omit it on a headless host. Launching collection does not schedule semantic inference. Existing observation caches and graphs remain available.

The database defaults to `.tracker/tracker.sqlite` relative to the working directory. Pin it when launching from different directories:

```sh
rilldex --db /local-disk/rilldex/tracker.sqlite start
```

Quote paths containing spaces. Keep the database and outbox on a local disk with working SQLite locking, not an object-store or network mount. A source output directory may be mounted read-only. Stop the foreground process with Ctrl+C; saved directory connections restart with the next `start` or `serve` invocation. To stop collection while keeping the UI running, use **Connections → Watch a job → Pause**.

## Choose by available evidence, not RL algorithm

| Existing evidence | Capture route | Available immediately | Needs more evidence |
|---|---|---|---|
| Harbor / SWE-agent job directory | Native managed connection | Saved actions/results, late results, lifecycle revisions, source map | Semantic activity/relationship observers and valid task outcomes |
| Decoded prompt/completion/reward export | JSONL exports or frozen file import | Score/text distributions and supplied training coordinates | Internal actions and reasoning structure cannot be recovered from a flat completion |
| Structured model messages and tool results | Portable conversation through JSONL, Outbox or HTTP | Recorded call/result links, source review | Saved semantic observations for intent/strategy measures |
| Environment reset and transitions | Portable episode through JSONL, Outbox or HTTP | Actions, states, explicit rewards and ending flags | Domain-specific interpretation, visual observation where needed |
| Trainer optimizer facts | Existing training-record/recipe capture | Supported method-specific measures when fields are supplied | A trajectory alone does not establish optimizer inclusion or policy age |

PPO, GRPO, async/off-policy and other methods use the same intake contracts. They do not share all metric prerequisites. Keep generating-policy version, generation/learner step, sample/group identity, split, reward components and masks where the framework exposes them. The existing settings and evidence checks choose relevant measures; missing facts remain unavailable. See the [framework evidence matrix](INTEGRATION_COVERAGE.md) for actual native validation levels.

## Before, during and after training

**Before:** create the output directory, then use **Connections → Watch a job**. The directory may be empty. Set a stable experiment and a unique producer per worker/export stream.

**During:** point the same form at existing outputs. No trainer restart is needed for file collection. Native Harbor/SWE-agent readers follow saved snapshots and result sidecars. For newline-terminated JSONL, choose **JSONL exports**, an experiment and an optional filename pattern. Records already present replay before newly appended records.

```sh
rilldex start --watch ./outputs --mode exports --experiment run-a --producer run-a/worker-0
```

Omit `--mode exports` for native Harbor/SWE-agent output. CLI startup saves the connection in the same database as the UI.

For any supported single-rollout JSON document, choose **JSON — one file per rollout**. This includes portable conversations, environment episodes, prompt/completion records and supported native snapshots. Detection uses the document structure. Narrow the filename pattern if the directory also contains configs or unrelated JSON. Use the native job route for Harbor/SWE-agent when result sidecars, continuations or retry bundles are needed.

```sh
rilldex watch ./outputs --mode snapshots --experiment run-a --producer run-a/worker-0 --check
rilldex start --watch ./outputs --mode snapshots --experiment run-a --producer run-a/worker-0
```

**Check directory** now decodes a bounded sample through the collector's normalization contract. It reports source maps, action/feedback evidence, reward coverage, training coordinates, incomplete files and validation errors. It reads up to five files, two JSONL records per file (within 20 physical lines), and 32 MiB total. It imports no sources and makes no model calls. The check is not a proof of exporter completeness or revision continuity; collection validates every received record.

Raw JSON files default to `in_progress`; the collector never guesses completion from file inactivity. Use `--snapshot-state complete` for completed snapshots, or put `state` in an explicit ingestion envelope when a producer supplies it. An unchanged snapshot that was already explicitly marked complete retains that state when a collector restarts with its old in-progress default. Changed content uses the configured default again. Each raw filename is a distinct rollout; updates to the same relative filename create revisions. Use a new filename for a new rollout, even if the task repeats. A stable filename must not be reused for unrelated samples.

Write each snapshot to a temporary file and atomically replace its destination where the filesystem supports this. A reader tolerates incomplete JSON and retains the last accepted revision, but polling cannot recover snapshots overwritten between checks. For every intermediate revision, use the durable outbox or append-only JSONL. Explicit envelopes keep strict sequential revision semantics across HTTP, JSONL and JSON files; a missing revision blocks that rollout until supplied. Raw JSON collection numbers the snapshots it actually observes.

**After:** frozen JSON/native bundles use **Import files**, with an evidence preview before import. For the same exports used by a live connection, replay with:

```sh
rilldex watch ./outputs --mode exports --experiment run-a --producer run-a/worker-0 --once
```

Use `--mode snapshots --once --snapshot-state complete` for a directory of completed JSON snapshots. Keep this same mode, producer and relative paths when resuming collection. A one-off run exits nonzero if a source is invalid or an export tail is incomplete. Frozen **Import files** has a separate artifact identity; use directory replay for files that will later be followed live.

This drains existing rows in bounded passes without requiring a server. A subsequent live connection uses the same receipts and cursors. Preserve producer, experiment, relative filenames and database. If you copy output to another machine, preserve the relative tree and move the stopped collector database too, or replay into a fresh database. Use SQLite's backup tooling for an online database; copying just the active `.sqlite` file can omit WAL data.

For portable inspection, use a workspace snapshot instead of copying an active SQLite file. **Connections → Import files → Move or back up this workspace** downloads one, or use:

```sh
rilldex --db ./current.sqlite workspace snapshot experiment.rilldex.zip
rilldex workspace inspect experiment.rilldex.zip
rilldex --db ./restored.sqlite workspace restore experiment.rilldex.zip
rilldex --db ./restored.sqlite start --open
```

The snapshot retains the database, immutable graph/measurement identities, reviews and investigations. Available older observer results are frozen with their structural audit receipts so inspection no longer needs their original workspace paths. The manifest lists unavailable observer results explicitly. This preserves earlier audit evidence; it does not rerun or independently validate an extraction.

Restoration requires a **new** destination file and leaves collection and pending inference paused. For a moved output mount, open **Watch a job → paused connection → Change output location**, supply the new directory, save, then resume. Producer identity, receipts and export cursors remain attached. Relative filenames must stay the same; accepted-prefix checks detect incompatible data.

External worker outboxes, training output directories and original candidate-generation/audit workspace files are not included. Keep those workspaces if continuing extraction development or rerunning the full original audit. Do not rerun paid extraction merely to inspect a relocated result. Snapshots currently support databases up to 8 GiB and local filesystems with hard-link support for atomic, non-overwriting publication; larger deployments need a separate backup strategy.

**Do not repeatedly import a growing JSONL file through frozen-file import.** Frozen imports intentionally identify the exact artifact bytes. Live exports identify producer + relative path + physical line, so appending data does not change earlier identities. Explicit envelopes use producer + rollout + revision and can also be replayed over HTTP with identical metadata.

## JSONL contract

Each physical line is one UTF-8 JSON object followed by a newline. UTF-8 BOM at the beginning and CRLF are accepted. Each raw object must normalize to exactly one rollout; multi-rollout bundles belong in frozen-file import. Select an explicit adapter if automatic detection is insufficient.

Example native verl generation row:

```json
{"input":"Question","output":"Answer","step":42,"score":0.5}
```

A raw row declares a complete exported record. It does not imply task success. The recorded `step` is retained as the source's logged iteration, not a guessed policy checkpoint. Identical completions on separate lines remain separate samples.

For in-progress work and later corrections, use the same envelope as `/api/ingest`:

```json
{"rollout_id":"42/task-3/0","revision":0,"state":"in_progress","format":"generation","metadata":{"experiment":"run-a","generation_step":42,"policy_version":"p42"},"document":{"trajectory_format":"generation/1","prompt":"Question","completion":"Partial response"}}
```

The connection supplies `producer`. The next envelope uses the same rollout ID, revision `1`, updated document and explicit lifecycle state. Envelope metadata overrides connection defaults. Neither `complete` nor `failed` proves a verifier outcome. Use one producer namespace for a given ordered revision stream; do not have independent writers allocate revisions for it.

Accepted rows are immutable. Add new shards with new filenames; never truncate and reuse a filename. The reader verifies the accepted byte prefix whenever the file changes, retains per-file offsets in SQLite and advances them only after ingestion succeeds. A crash between receipt and cursor commit causes an idempotent replay. It checks bounded rows per file per poll (default 100); unchanged files are skipped. Records have a 20 MiB limit. Prefix verification costs I/O proportional to the accepted prefix of a changed file, so prefer bounded per-step/worker shards over indefinitely growing logs. This is not a measured large-cluster throughput guarantee.

## Offline workers, remote jobs and recovery

Use the existing [durable Python outbox](LIVE_INGESTION.md#python-producers-durable-delivery) when instrumenting a worker. `log()` writes locally; `.start(report_status=True)` enables background delivery and queue reporting. Network failure retains pending data. Closing an outbox stops its sender; it does not guarantee all data was delivered. Inspect its pending/blocked counts and resume delivery later:

```sh
rilldex outbox worker-0.sqlite --producer run-a/worker-0
rilldex outbox worker-0.sqlite --producer run-a/worker-0 --send --limit 1000
```

Older-Python/non-Python trainers can emit the JSONL or HTTP contract without importing this package. For a remote job, run the collector next to its outputs and forward its loopback port:

```sh
ssh -L 8765:127.0.0.1:8765 training-host
```

The supplied Docker Compose setup mounts output read-only and retains a named workspace volume. Its explicit container listener works with Docker port publishing to host loopback; the default local listener and Host/Origin checks remain. See [Docker startup and restart](DEPLOYMENT.md#docker-persistent-workspace-existing-and-future-output). An authenticated public/multi-tenant service is not implemented.

| Visible condition | Meaning | Recovery |
|---|---|---|
| Waiting for output files | Directory exists but matching output has not arrived | Check root/pattern or wait for the job |
| Waiting for the last newline | Last row is not committed | Let the writer finish and append its newline |
| Catching up | More rows remain than the per-poll budget | Collection continues automatically; inspect scan duration |
| Deferred file + line number | Invalid row, unavailable source, or revision conflict | Fix the unaccepted row or restore the correct revision order; other files continue |
| Accepted bytes changed/truncated | Previously imported evidence was overwritten | Restore accepted bytes; export new/corrected samples under a new filename or explicit revision stream |
| Delivery pending | Outbox has unacknowledged records | Restore connectivity and drain the same outbox |
| Blocked delivery | Non-retryable schema/identity error | Inspect the saved error; repeating unchanged invalid data will not repair it |
| Semantic measure unavailable | Required observations or source evidence are missing | Open Data coverage; provide/review the needed observer data within an explicit budget |

## Practices informing this design

[W&B offline synchronization](https://github.com/wandb/wandb/blob/main/wandb/cli/cli.py) supports saving work locally and synchronizing later. [OpenTelemetry Collector resiliency](https://opentelemetry.io/docs/collector/resiliency/) documents persistent queues, retry and queue-capacity monitoring. Those informed the separation of durable capture from delivery and analysis. This implementation uses the existing Outbox and immutable receipt machinery; it is not an OTLP receiver or a W&B backend.

Verified locally: installed wheel outside the checkout with no optional dependencies; loopback HTTP, automatic port selection, packaged UI routes, empty-directory attachment, partial writes, live collection, frozen file upload, revision replay and restart. Lifecycle regression tests also compare batch/live source, analysis and stored graphs across verl, generations, conversations, environment episodes and Harbor. Native distributed GPU training, all OS versions, object stores, visual modality analysis and automatic semantic generalization remain separate validation work.


## Inspect while new output arrives

A behavior map is pinned to a saved source. Its revision strip shows whether that source is still the latest received snapshot. New input produces a notice and **Open latest source** link without moving cards or changing evidence under an active review. The link opens the current source map; semantic observations remain attached to the snapshots they actually inspected. A disconnected collector is shown explicitly, and revision checks resume after reconnection.

For sources with a declared goal tree or saved work/Plan observations, **Plans & attempts → Track across rollouts** creates a monitor from the same evidence basis. Inspect branch effort and depth, then follow values back to their exact cases. This reuses saved data without model calls. [Available measures and lifecycle behavior](WORK_STRUCTURE_MEASURES.md).
