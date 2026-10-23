# Find and compare experiments

Open **Overview**, with **All experiments** selected. Search the experiment list,
then open Training, Behavior, Execution or Rollouts from its row. Filter by
project, pin or archive runs, and edit names, tags and notes with **Organize**.
Experiments with trainer logs or process capture appear even without rollouts.

Select rows or **Select this page**, then move, tag, pin, archive or restore up to
500 runs together. Selection survives filtering, paging and browser reloads;
the toolbar counts selected runs outside the current page. **Review selection**
lets you remove individual runs. Organization preserves captured data and run IDs.

For curves, select two or three runs with trainer logs and choose **Compare runs**.
Use **Save selection** to keep a named comparison in the workspace. Runs without
trainer logs can still be organized. Selections are separate for each workspace
and environment; browser selection is local, named comparisons are stored in the database.

Choose **Recorded settings** beside search to find runs by captured configuration
keys or values. Select two or three runs → **Compare settings**, also available
beside training curves. Pick a worker/session snapshot per run, search fields or
show only differences, and download the selected snapshots. Settings can be
compared without trainer logs. Snapshots stay fixed until **Refresh sources**;
operation settings are compared separately, never merged into a run configuration.

Trainer details show recorded framework versions and objective identifiers.
**Run details** adds captured configuration, Python/Git context, searchable
console logs, hardware samples and files. Enable collection with
[`rilldex record` or `Run`](RUN_CAPTURE.md). Previously imported runs retain
only their available records. Last received denotes data arrival.

**Run details** also opens operation settings, trainer sessions and run history.
Search each section; open an operation to inspect its execution. Settings remain
attached to their recorded operations. Partial settings are not merged into a
complete run configuration. Chart-point inspection shows settings only through
explicit trainer-log references.

The same records are available without the UI:

```python
from rilldex import Workspace
run = Workspace("workspace.sqlite", experiment="run-a")
settings = run.experiment_details(section="settings", q="temperature")
streams = run.experiment_details(section="trainers")
history = run.experiment_details(section="history", limit=20, offset=0)

Workspace("workspace.sqlite").organize_experiments(
    ["run-a", "run-b"], project="Review", add_tags=["baseline"], pinned=True
)
comparison = Workspace("workspace.sqlite").compare_settings(["run-a", "run-b"])
```

Bulk edits add or remove tags without replacing other tags. Use `project=""`
to unassign a project, `remove_tags=[...]`, or `archived=True` / `False`.

[Connect trainer metrics](TRAINER_TELEMETRY.md) · [Integration coverage](INTEGRATION_COVERAGE.md)

Use the sidebar [workspace picker](WORKSPACES.md) to open another study. Projects
and saved selections remain in their original workspace.
