# Choose where the tracker runs

Start in **Connections → Start here**. The setup planner generates commands for
your job location, training stage and shell, with separate collector/workstation
steps, restart instructions and the first checks to open. It does not execute
commands, change training, or invoke a model. CLI equivalent:

```sh
python -m rilldex setup --case remote --host training-host --root /jobs/run-a/outputs --mode exports --experiment run-a
```

Use `--shell powershell` for Windows commands. Cases are `local`, `remote`,
`docker`, `cloud`, `notebook`, and `offline`. `--stage after` generates one-off
replay followed by opening the saved workspace; `before` and `during` generate
catch-up plus continuous collection. Output must already be in a supported
format; selecting a deployment does not create a trainer integration.

## One launch file across training stages

The simplest repeatable route is **Start here → Download launch file**. Save it
beside the job, review the source and database paths, and keep that file for
checks, batches and live capture. It is configuration data, not an executable
shell script. It does not install packages or start the trainer.

```json
{
  "schema": "rilldex-launch/1",
  "database": "./inspection/workspace.sqlite",
  "port": 0,
  "create_output": true,
  "source": {
    "root": "./outputs",
    "producer": "run-a/worker-0",
    "mode": "exports",
    "metadata": {"experiment": "run-a"}
  }
}
```

```sh
rilldex launch /jobs/run-a/job.rilldex.json --check
rilldex launch /jobs/run-a/job.rilldex.json --once
rilldex launch /jobs/run-a/job.rilldex.json
```

Choose one command for the current need. `--check` uses a temporary inspection
store, reads a bounded source sample, and leaves the workspace and output alone.
It also works while the configured UI port is occupied. `--once` drains existing
records and exits; incomplete JSONL tails or failed records produce a nonzero
exit code without discarding accepted records. Live launch catches up first and
then follows new output. Stop with Ctrl-C and rerun the same command to resume.
Add `--open` only for a local live UI. No mode invokes a model provider.

All relative filesystem paths resolve against the **launch file's directory**,
not the terminal's current directory. Cloud prefixes stay unchanged. Moving the
file changes the meaning of relative paths; keep it beside its job or use absolute
paths. Absolute paths belong to the machine where launch runs. A Windows absolute
path is rejected on a POSIX host instead of being treated as a relative filename.
Source access and persistent local disk are still prerequisites.

`create_output: true` prepares a missing local output directory when launched;
it does not create it during `--check`. Setup enables this only for local/remote
**before training** plans. Do not use it to hide an incorrect path for an active
job. Cloud directories are never created. The database should stay on local disk.
After a producer has a saved connection or receipts, a missing output directory
is an error even if `create_output` is true. Restore the mount or relocate the
paused connection; restart must not hide lost access behind a new empty folder.

Producer identity, source-relative filenames and decoding settings must remain
stable. Live and one-off collection share the same lock: pause/stop the existing
collector before running a batch against it. Editing a connected source's settings
does not silently replace its saved connection. Use the existing pause/relocate
workflow for moving its output directory.

Launch files accept one source and the existing native, JSONL and JSON snapshot
readers, metadata, filename pattern, interval and explicit snapshot state. Saved
additional connections in the same workspace resume through the normal service.
Unknown keys and files larger than 128 KiB are rejected. Docker, notebook and
offline-worker setups retain their dedicated routes rather than pretending the
same launcher installs or manages those environments.

CLI generation is available without a UI:

```sh
rilldex setup --case local --mode exports --stage before --save-launch job.rilldex.json
rilldex setup --case remote --shell powershell --collector-shell posix --root /jobs/run-a/outputs
```

The first command refuses to overwrite an existing launch file. Its source and
database paths are interpreted beside the saved file. The second generates Linux
host commands independently from the Windows workstation's SSH command. POSIX
instructions use `python3`; Windows instructions use `python`. Select/install a
Python 3.11+ interpreter in a separate environment. Python documents that an
environment can be used through its executable path without activation:
[venv usage](https://docs.python.org/3/library/venv.html#how-venvs-work).

For raw JSON snapshots, choose **Work in progress** or **Completed rollouts**
explicitly (`--snapshot-state complete` when generating a setup). Finishing or
stopping training alone does not establish every rollout's completion. Explicit
envelopes always retain their own state; completion is not success.

Port `0` chooses an available local port and prints its address. Remote SSH and
Docker setup require a fixed port; generated SSH commands stop if forwarding
cannot be established. After launch, setup's links point to the selected workspace
port rather than the workspace that generated the instructions.

### Identify existing output before connecting

Use **Detect output** in Start here (local/cloud) or Watch a job. It reads a
bounded sample with the existing source decoders, shows candidate layouts,
recorded producer IDs, unresolved files and suggested filename rules, then lets
you apply a layout. **Check source** still checks the chosen reader and evidence
coverage before connection. Nothing is imported or inferred by detection.

```sh
python -m rilldex discover /jobs/run-a/outputs
python -m rilldex discover s3://my-bucket/run-a/outputs
```

Run remote discovery on the machine that can read those paths. Cloud discovery
uses temporary downloads and the normal host credentials, and excludes model
weight files. It does not create a workspace or durable cursor. Limits: 5,000
directory entries, 6 files per layout, 32 MiB, and the first two committed JSONL
records within 20 lines. Sampled matches do not prove the rest of a job is valid.

Suggested filename rules separate **observed** trajectory files from unrelated
settings/log files when possible. An exact filename follows only that name in
subdirectories; other filenames need another rule. Mixed layouts stay separate
to avoid automatically double-counting the same trajectory. Multiple producer
IDs in one file require separate connections or worker bundles, not renaming to
one producer. Empty folders cannot identify an unwritten format. A saved
connection keeps its selected reader; detection never changes it automatically.

| Situation | Lowest-friction route | First useful result |
|---|---|---|
| Existing evaluation / failed job | Import files or replay a directory | Inspect the failed rollout and recorded action/feedback map |
| Active job writing trajectories or JSONL | Independent directory collector | Catch up existing records, then follow new receipts without restarting training |
| Remote GPU / SSH access | CPU collector near outputs; tunnel browser port | Same workspace and maps without copying each new file |
| Shared cluster / many workers | One local outbox per worker; live delivery or bundles | Preserve worker/sample/revision identities when joining evidence |
| Restricted compute | Offline bundles and returned receipts | Transfer rollout and trainer facts without a server in the job |
| Containerized collector | Read-only output mount and persistent workspace volume | Isolated installation; retain observations across restart |
| Cloud object output | S3/GCS reader and local cache | Observe changing output while retaining accepted local evidence |
| Ephemeral notebook | Headless workspace; export before VM deletion | Capture now, inspect the same saved data on a workstation later |
| Research handoff / CI artifact | Capture bundle for new records; workspace archive for saved analysis | Repeatable review without re-running unchanged semantic observations |

The deployment boundary is data accessibility and persistence, not the RL loss
function. Native adapters still determine which algorithm-specific facts exist.
Scheduler job logs alone cannot reconstruct agent trajectories. All routes use
the same store; source coverage governs which maps and measures are useful.

## Offline workers and artifact handoff

Use `Outbox` without calling `.start()` to record without network delivery. Each
worker needs its own local SQLite file and stable producer ID. Supply stable
sample IDs, explicit state, native source documents and training coordinates
where available. Export makes a consistent read snapshot while the worker may
continue recording; do not copy a live SQLite main file alone.

```sh
# Worker machine: use a NEW bundle filename for each handoff.
python -m rilldex capture export worker-0.sqlite worker-0.rilldex-capture.zip
# Inspection machine: imports need no running server.
python -m rilldex capture inspect worker-0.rilldex-capture.zip
python -m rilldex --db review/tracker.sqlite capture import worker-0.rilldex-capture.zip --receipt worker-0.receipts.json
# Copy the receipt back to the original worker to free delivered queue space.
python -m rilldex capture acknowledge worker-0.sqlite worker-0.receipts.json
```

Bundles preserve rollout envelopes, training records, recipe declarations and
continuation studies. Every packet is checksum/schema checked before importing;
receipts commit separately. Conflicts block later revisions of that rollout,
while independent records can continue. Retrying reuses accepted identities.
CLI returns nonzero for partial failure and can still write receipts for the
accepted portion. No executable serialization or archive path extraction is used.

**Connections → Start here → Receive an offline worker bundle** accepts bundles
up to 14 MiB and offers a receipt download. CLI supports 50,000 packets / 2 GiB
uncompressed, at most 20 MiB per packet. `capture import a.zip b.zip` combines
workers; request `--receipt` separately for each bundle when acknowledging.

Export does not clear the worker queue. Acknowledge verifies the original outbox
identity, queue IDs, payload hashes and receiver IDs before clearing any matching
payloads. New packets remain queued. Retain the receiving workspace or its backup
after acknowledgment. Backpressure applies until then (256 MiB pending by
default); choose handoff cadence and storage capacity accordingly. Receipt files
are explicit local handoffs, not remote authentication. Already HTTP-delivered
packets were pruned from the outbox; import later revisions into their original
receiving workspace or its restored backup. Transfer prior analyses with a
**workspace snapshot**, not a capture bundle.

## Collector placement

The tracker is a separate collector and research workspace. It does not need to
run inside the trainer's Python environment or use its GPU. Attach one saved
connection to the job output: it reads existing records, then follows new ones.
Starting halfway through training does not require restarting the trainer.

| Your situation | Recommended start | State that must survive |
|---|---|---|
| Ubuntu, Windows or macOS workstation | Install the wheel in a separate Python 3.11+ environment; `rilldex start --open` | Workspace database and any worker outboxes |
| Docker available | `docker compose up --build -d --wait` | The `jev-data` volume; output directory is mounted read-only |
| Remote GPU VM / SSH-accessible cluster | Collector beside the output, browser through SSH port forwarding | Workspace on local persistent disk; job outputs |
| Job output in S3 or GCS | Watch the cloud prefix with the normal route; optional storage package uses host credentials | Workspace and its adjacent cloud cache; source objects |
| Colab / managed notebook | Notebook-owned capture, inline status and a portable workspace export | Save/download the archive and source output before the runtime is deleted |
| Training already finished | Replay the same connection with `watch ... --once`, or import frozen files | Workspace archive for later inspection |

This is a local/single-user deployment, not an authenticated public SaaS service.
The supplied Docker port mapping stays on host loopback. Remote browsers use SSH;
the app's Host/Origin checks remain active. No deployment path automatically
schedules paid semantic extraction. Saved maps/annotations/measurements transfer
in workspace snapshots. Missing captured facts remain unavailable on every path.

## Ubuntu, Windows and macOS

From this checkout, using Python 3.11+:

```sh
python -m venv .venv
# Ubuntu/macOS:
.venv/bin/python -m pip install .
.venv/bin/rilldex --db ./workspace/tracker.sqlite start --open
```

PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\rilldex.exe --db ./workspace/tracker.sqlite start --open
```

On Ubuntu, install the distribution's `python3-venv` package if venv support is
missing, and use `python3` to create the environment. An older trainer Python is
fine: the collector is separate. Offline machines can install a built wheel with
`python -m pip install --no-index --no-deps /path/to/rilldex-0.1.0-py3-none-any.whl`.
Do not assume this development package is published on PyPI.

Keep the installation separate from the trainer. To run a downloaded launch file
without activating an environment, use `.venv/bin/rilldex launch job.rilldex.json`
on Linux/macOS or `.venv\Scripts\rilldex.exe launch job.rilldex.json` on Windows.
On a restricted host, install the supplied wheel with `--no-index --no-deps`;
cloud readers additionally require their storage dependencies to be provisioned.

Pin `--db` to an absolute path when starting from different directories.
`rilldex doctor --port 0` checks installation/storage, and `start --port 0`
chooses an available port. Omit `--open` on a headless machine.

## Docker: persistent workspace, existing and future output

Create `outputs/` beside `compose.yaml`, or set `RILLDEX_OUTPUT_DIR` to your existing
absolute output path. The defaults expect JSONL; set `RILLDEX_INPUT_MODE=native` for
Harbor/SWE-agent jobs or `snapshots` for one JSON document per rollout. Put these
values in a `.env` file beside Compose (do not put provider/API keys there):

```dotenv
RILLDEX_OUTPUT_DIR=/absolute/path/to/training/outputs
RILLDEX_INPUT_MODE=exports
RILLDEX_EXPERIMENT=run-a
RILLDEX_PRODUCER=run-a/exports
RILLDEX_PORT=8765
```

Use a Windows absolute directory on Docker Desktop when appropriate. Then:

```sh
docker compose up --build -d --wait
docker compose logs --tail 50 tracker
# Open http://127.0.0.1:8765
docker compose stop
docker compose start
```

The image runs as a non-root user, reads `/outputs`, and keeps the database and
cached inspection in the named `jev-data` volume. Mounted output must be readable by container UID 10001;
if your site uses restricted job-directory permissions, grant the intended read
access or run the Python collector as the job user instead. Output written while stopped
is collected on restart. `docker compose down` removes the container but keeps
the volume; another `up` resumes. `down --volumes` deletes that workspace volume,
so it is not a normal stop command. Preserve the Compose project name/directory
or use a workspace export when moving projects. Keep the same port inside and
outside the container; Compose does this automatically.

Snapshots default to in-progress capture. Explicit envelopes declare completion;
for already-completed raw snapshots, select **Completed rollout snapshots** in
the UI or use the documented `--snapshot-state complete` CLI route. Do not mark
a running job complete based on file inactivity.

The Docker image contains base capture, not cloud SDKs. Use cloud collection in
a Python environment with the storage extra, or mirror cloud output to the
read-only mounted directory with your existing cloud CLI. No trainer dependency
is installed into the image.

## Remote Ubuntu / GPU host / cluster

Run the collector in a persistent CPU session on a host that can read the job's
outputs. It does not attach to or interrupt the training process:

```sh
rilldex --db /local-disk/rilldex/workspace.sqlite start --watch /jobs/run-a/outputs --mode exports --experiment run-a --producer run-a/exports
```

From your workstation:

```sh
ssh -N -L 8765:127.0.0.1:8765 training-host
```

Open `http://127.0.0.1:8765`. Use the same selected port at both ends. Closing the
tunnel disconnects the browser; it does not stop a collector running in a
persistent job/service/session. If the collector stops too, restart with the
same database and connection. A sample systemd user service is in
`deploy/rilldex.service`; edit its absolute paths before installing it.
Cluster job scheduling and shared-filesystem permissions remain site-specific.
Keep SQLite on local storage with reliable locking, not NFS or an object mount.

## S3 and Google Cloud Storage

Install the appropriate optional storage backend into the collector environment:

```sh
python -m pip install '.[s3]'   # from this checkout; use .[gcs] for GCS
rilldex --db ./workspace/tracker.sqlite start --watch s3://my-bucket/run-a/outputs --mode exports --experiment run-a --producer run-a/cloud-exports
```

Use `gs://my-bucket/run-a/outputs` for GCS. In **Connections → Watch a job**, the
same **Output directory or cloud prefix** field accepts these URIs. Credentials
come from the storage SDK's normal environment/profile/workload identity on the
collector host. The product has no credential-entry form and does not persist
keys in a connection. Bucket/list/read permission is needed; no object writes
or deletes are performed. Signed URLs and credentials embedded in URLs are rejected.

The collector mirrors changed objects into `cloud-cache/` beside its database,
then uses the ordinary native/JSONL/JSON readers. Downloads are written to
temporary files, checked against object metadata and atomically published.
Interrupted downloads retain the previous accepted copy. Unchanged objects with
version/etag/time metadata skip download. Deleted cloud objects do not delete
local evidence. An outage retains accepted data and shows a retryable connection
error. Already downloaded records continue through the ordinary reader during an
outage, including after restart. Connections shows **Cloud unavailable · using
cached output** and the last complete cloud sync separately from local receipt
activity. This does not establish whether new remote output exists. `watch --once`
drains the available cache but exits unsuccessfully while cloud access is still
failing; a partial replay is never reported as complete. Restart resumes from the
saved local source and cursors.

S3-compatible storage can use the storage client's standard endpoint setting,
configured before starting the collector:

```sh
export FSSPEC_S3_ENDPOINT_URL=https://your-object-storage.example
rilldex --db ./workspace/tracker.sqlite start --watch s3://bucket/run-a --mode exports --experiment run-a --producer run-a/cloud
```

PowerShell uses `$env:FSSPEC_S3_ENDPOINT_URL='https://your-object-storage.example'`.
Keep credentials in the SDK environment/profile/workload identity, not in the
source URI. The endpoint setting selects the service; the source still uses
`s3://bucket/prefix`. See [s3fs compatible-storage configuration](https://s3fs.readthedocs.io/en/latest/#s3-compatible-storage).
Restart the collector after changing environment configuration. This path has
been exercised with the real s3fs client and a local Moto HTTP service, not a
production MinIO/Ceph endpoint or real AWS IAM credentials.

When training forks worker processes, keep the cloud collector in its own process.
If combining them, s3fs requires `spawn` or `forkserver`; its sockets/background
thread are not safe under `fork`. See [s3fs multiprocessing guidance](https://s3fs.readthedocs.io/en/latest/#multiprocessing).

`watch CLOUD_URI ... --once` drains existing objects without a UI; `--check`
downloads a temporary preview of up to five objects, bounded to 32 MiB, without
importing records or advancing cursors. It may list the selected prefix; use a
narrow job prefix. Collection permits up to 1 GiB per object and 100 changed
objects per pass, with the configured file limit. This is polling, not a cloud
event subscription. Prefer bounded immutable shards; changed growing objects
must be downloaded again. Cloud costs and throughput have not been benchmarked.
Snapshots overwritten between polls cannot be recovered; use append-only shards
or explicit retained revision envelopes if every intermediate state matters.

An AWS/GCS CLI mirror, Azure Blob sync, or SSH copy can also feed a local watched
directory. Retain relative paths, atomically publish finished copies, and never
delete/rewrite accepted JSONL prefixes. Native Azure/authenticated HTTP artifact
connectors are not implemented in this increment.

## Colab and other notebooks

Install the wheel into the runtime, then keep the working database on the
runtime's local disk. The helper uses the same collection and measurement
services without a web server, public tunnel, subprocess or paid inference:

```python
from pathlib import Path
from tracker.notebook import open_workspace

Path('/content/outputs').mkdir(parents=True, exist_ok=True)
inspection = open_workspace('/content/rilldex/workspace.sqlite')
connection = inspection.watch('/content/outputs', producer='run-a/exports',
                              experiment='run-a', mode='exports')
inspection.start()
inspection.status()       # received count, source errors, backlog and connection state
inspection.rollouts(10)    # inspect captured rollout summaries in the notebook
```

Rerunning `open_workspace(...).start()` reuses this kernel's session. Calling
`inspection.stop()` requests shutdown and waits up to ten seconds. It returns
`{"state": "stopped"}` once the readers and analysis have exited. A slow storage
read can return `{"state": "stopping"}` instead; check `inspection.status()['state']`
or call `inspection.stop(timeout=30)` to wait longer. Starting while that previous
session is still stopping is rejected, so rerunning cells cannot duplicate a
reader. Once stopped, `inspection.start()` catches up on output written while
stopped. Use `pause(connection['id'])` / `resume(...)` to
persist a per-connection pause. A new kernel reopens the same database and
resumes enabled connections on `start()`.

For the full map/investigation UI, export the workspace and open it on your
workstation. Choose a new archive filename each time:

```python
inspection.snapshot('/content/inspection-001.rilldex.zip')
from google.colab import files
files.download('/content/inspection-001.rilldex.zip')
```

Alternatively copy that completed archive to your mounted Drive or managed
artifact storage. Keep the active SQLite file on local disk; copy the completed
archive, not an active database/WAL pair. Download/copy source output too if you
need to continue capture after runtime deletion. On your workstation:

```sh
rilldex --db ./recovered.sqlite workspace restore inspection-001.rilldex.zip
rilldex --db ./recovered.sqlite start --open
```

Restored collectors are paused. Use **Change output location** for relocated
local output, then resume. A deleted Colab runtime cannot be recovered without
an archive or replayable source outside that runtime. The helper does not keep
Colab alive, bypass its restrictions or provide a hosted web UI. Full notebook
UI proxy integration is separate work.

## Stop/restart contract

| Event | What happens | What you do |
|---|---|---|
| Browser closes | Collector continues | Reopen the same URL |
| Collector stops or machine reboots | Received revisions/cursors remain in the workspace | Start the same workspace; enabled connections catch up |
| Connection paused | New output is not consumed by that connection | Resume it; existing backlog then new output is read |
| Training stops and resumes | Stable producer/path identities preserve continuity | Use new rollout IDs/files for new samples; retain old accepted bytes |
| Network/cloud outage | Last accepted source remains; cloud/download errors are visible | Restore access; retries resume |
| New host/container | Paths and ephemeral files may be gone | Retain Docker volume or restore an archive; reconnect source paths |
| Notebook runtime deleted | Unsaved runtime disk is lost | Restore an externally saved archive or replay retained outputs |

Backlog ingestion and live collection share one receipt path. Do not separately
upload growing files and then watch them: frozen uploads intentionally have
artifact identities. Use the watched directory/prefix for both historical and
future records. Explicit envelopes can travel over HTTP or files with the same
producer, rollout and revision identity.

Pause is a request: an in-flight filesystem or storage SDK call may still be
finishing. Connections shows **Pausing · finishing current read** until that
reader exits. Other sources continue while it finishes. Relocation is allowed
only after the reader has stopped; a quick Resume waits for the old reader rather
than starting an overlapping one. A current read may finish accepting a revision
before the pause completes.

There is one file collector per workspace/producer at a time, enforced by a local
OS lock. If another server/notebook owns it, the connection shows **Another
collector is active** and waits for ownership. CLI `watch` instead exits with a
message so scripts do not silently start a competing reader; `watch --check`
remains available. Different producers and HTTP deliveries can continue.
Closing or crashing the owning process releases ownership automatically.
`.jev-capture-locks` contains persistent marker files: their existence does not
mean a process is running, and deleting them is not a recovery operation.
Keep the workspace on a local filesystem with working OS locks. This is not a
distributed lock for collectors sharing SQLite over NFS or different hosts.

## Evidence and current validation boundary

The implementation follows [Docker's localhost port-publishing guidance](https://docs.docker.com/engine/network/port-publishing/)
and [Compose readiness checks](https://docs.docker.com/compose/how-tos/startup-order/).
Object readers use the [fsspec filesystem interface](https://filesystem-spec.readthedocs.io/en/latest/usage.html).
[Colab documents ephemeral VMs and managed-runtime restrictions](https://research.google.com/colaboratory/faq.html);
the notebook workflow therefore retains capture locally and exports durable
inspection archives instead of promising a persistent hosted service.

Windows integration checks exercise installed packages, listener behavior,
batch/live revisions, restarts, cloud protocol failure controls and notebook
capture/export. A real s3fs client over localhost HTTP to Moto also covers
preflight, historical/future data, cached backlog during HTTP permission failure,
restart, equal live/batch identities, snapshot revisions and late native verifier
files. These are authored S3 service controls, not real account validation.
Docker and Linux/macOS jobs are provided in CI. This host has no
Docker engine or usable WSL distribution, so those jobs have not run locally.
Real S3/GCS credentials, managed Colab execution and GPU-cluster deployments were
not exercised. The storage control tests establish transport/recovery logic,
not provider authentication or production throughput.
