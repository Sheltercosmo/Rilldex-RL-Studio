# Investigation trials

Open a saved investigation → **Checks & findings → Prepare trial**. Choose a rollout and event boundary, base configuration, variants and seeds. An unchanged reference arm is included. Export `trial.json`.

- **Replay:** pass the captured prefix and appended context to your agent runner.
- **Rescore:** evaluate the complete captured rollout with another grader or configuration.
- **Train from a checkpoint:** branch from a checkpoint your trainer can restore. The selected rollout is diagnostic evidence, not a training dataset.

Run in the environment that owns your model and tools:

```python
from rilldex import TrialStudy
from my_runner import run_trial

study = TrialStudy.load("trial.json")
study.run(run_trial, output="trial-results.json")
```

`run_trial(job)` receives `prefix`, `configuration`, `context_append`, `checkpoint`, `seed`, `budget` and `measure`. Apply these through your trainer/agent API and return:

```python
return {
    "status": "completed",  # or error, blocked, incomplete
    "metrics": {"success": 1.0},
    "applied": {
        "configuration": actual_configuration,
        "context_append": actual_added_context,
        "seed": actual_seed,
        "checkpoint_reference": loaded_checkpoint,  # "" if none
        "restored_state": restored_components,     # [] for text-only replay
        "reset_state": restarted_components,       # [] unless intentionally reset
    },
    "experiment": captured_run_name,  # optional; opens returned telemetry
    "rollout_ids": captured_rollout_ids,  # optional; exact ingestion result IDs
}
```

The adapter owns restoration and step/token limits. For checkpoint branches, choose **Restore** or **Start fresh** for each state component. For example, restore model/optimizer/scheduler and restart RNG, data collection and environments with paired seeds. Undeclared missing state remains visible; a checkpoint label alone cannot restore it. Report actual values, not copies of requested values.

**Import results** on the check to see paired differences, missing trials, execution errors and setting mismatches. Original evidence stays pinned. Add a finding to record your interpretation; the comparison does not automatically claim a cause.

Results save after each callback. Reuse the same output file to skip completed jobs; use `retry_failed=True` to retry other statuses. Use `job["id"]` as an external job idempotency key: an interrupted callback may run again. One process should own each result file. No browser-side trainer execution or universal checkpoint loader is provided.

Without the UI, use `TrialStudy.from_investigation(database, investigation_id, check_id)` and `study.record_results(database, result)` to attach returned receipts as a new saved revision.

Return `rollout_ids` to connect scores to exact maps. **Compare returned behavior** opens saved measures and rollout comparisons for a variant versus Reference. Paired mode requires both jobs and all declared traces; All returned evidence includes partial results. Shared traces, missing annotations and unresolved opportunities remain visible. Use **Refresh rollout evidence** after late traces arrive; earlier comparisons stay pinned. Include `trial_job_id` and `seed` in captured rollout metadata to check the association. Python: `study.refresh_rollouts(database, investigation_id=...)` and `study.compare_behavior(database, investigation_id=..., arm=...)`.
