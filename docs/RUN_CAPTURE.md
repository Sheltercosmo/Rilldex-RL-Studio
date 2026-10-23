# Run capture

Wrap any command to capture stdout/stderr, session exit status, Python/Git context and hardware:

```sh
python -m pip install "rilldex[system] @ git+https://github.com/Sheltercosmo/Rilldex-RL-Studio.git"
rilldex --db study.sqlite record --project reasoning --name trial-1 -- python -u train.py
rilldex --db study.sqlite start --open
```

Use `--experiment existing-id` to attach to an imported run. Repeat the same project/name on restart; each process gets a separate session. `--producer worker-0` distinguishes distributed workers. `--no-hardware` disables sampling; `--interval 10` sets seconds between samples. Child exit codes are preserved. The wrapper captures command output; it does not parse arbitrary console text into trainer metrics.

For Python, `Run(..., config={...})` captures console inside its context manager. `run.log(metrics, step=n)` retains native scalar names. Supply a supported `framework`, `framework_version`, `objective` and optional `definitions` for interpreted trainer signals; `run.telemetry.transformers_callback()` exposes the existing TRL callback. [Stable-Baselines3](STABLE_BASELINES.md) uses `run.stable_baselines()` for native logs and optional vector-episode capture. Use `capture_console=False` in applications that manage their own output.

## Remote and offline

```sh
rilldex record --project reasoning --name trial-1 --producer worker-0 --endpoint http://127.0.0.1:8765 --outbox worker.sqlite -- python -u train.py
```

Use an SSH tunnel for a remote collector, or the configured HTTPS endpoint. Outbox records survive interrupted delivery. Resume delivery with the same outbox, or use `rilldex capture export` and `rilldex capture import` for offline transfer. Python accepts `Run(..., target=outbox)`; run `outbox.start()` / `outbox.close()` around it. Mount the workspace and outbox on persistent storage in containers.

For disconnected workers, replace `--endpoint ...` with `--offline`; no delivery is attempted. `--encoding` selects the child console encoding (UTF-8 by default).

## Browse and analyze

- **Experiments:** filter projects, search run names/tags, pin/archive, edit notes, save up to three runs for comparison. Archive hides a run without deleting its data.
- **Run details:** Config & runtime, Logs, Hardware, Files, Settings, Trainer streams, Run history and Sessions. Logs support worker/session filters, search, pagination and Follow. Follow shows the latest 100 matching chunks; older chunks remain available with From beginning.
- **Session details:** open from Training signals or an inspected point. Worker/process selection carries across capture tabs. Config & runtime compares recorded snapshots; `run.log_config({...})` saves a new snapshot. For a separate trainer session, pass `trainer_session="..."` to link it to this process. SB3 links each learn call automatically. Process capture can span several training calls; native trainer-step intervals do not filter these records.
- **Hardware:** browse full history by host and process, select a UTC interval, or inspect a peak to open nearby logs. CPU/RAM, GPU utilization, memory, temperature and power retain missing samples. Statistics use all captured samples; reduced plots retain extrema. Refresh includes late arrivals; Follow updates automatically.
- **Files:** `run.add_file(path)` stores snapshots up to 2 MiB. `run.add_reference(path_or_uri, role="checkpoint")` tracks large files or local directories in their current storage. **Link stored file** adds references from the browser. [Large files](RUN_FILES.md).
- **Workspaces:** click the sidebar workspace name to open, create or switch studies. Each database and capture endpoint stays independent. Download workspace preserves run capture, project organization and saved comparisons. [Switching and restore](WORKSPACES.md).

```python
from rilldex import Workspace
ws = Workspace("study.sqlite", experiment="reasoning/trial-1")
logs = ws.run_records(kind="console", q="error", limit=100)
next_page = ws.run_records(kind="console", after=logs["next_cursor"])
samples = ws.table("run_capture")  # also available as rl_run_capture in SQL
ws.organize(tags=["baseline"], pinned=True)
context = ws.trainer_context(producer="worker-0", session="trainer-session")
hardware = ws.hardware_history(producer="worker-0", points=160)
logs = ws.run_records(kind="console", producer="worker-0", session="process-session",
                     observed_from="2026-10-23T10:00:00Z", observed_to="2026-10-23T10:05:00Z",
                     as_of=hardware["as_of"])
```

Collection needs no LLM or GPU. CPU/RAM requires psutil (`system` extra); NVIDIA GPU sampling requires `nvidia-smi`. AMD/Apple GPU utilization is not implemented. Samples describe the machine visible to the collector, not per-job resource attribution or all nodes of a cluster. Run a collector on each relevant worker. This is a local workspace, without shared accounts, permissions or a general checkpoint registry.
