# Record the state that an operation actually used

`tracker.state_capture.WorkStateRecorder` connects producer observations to the existing state graph and monitors. It supports any single-rollout adapter whose source events resolve unambiguously. Runtime encoding checks cover SWE-agent, Harbor/ATIF and portable chat records; these are adapter checks, not execution of those agent frameworks.

This enables two different questions: did a comparable check pass after a recorded relevant change, and does a passing check still apply to the delivered state? A repaired attempt may pass while a later edit leaves the final delivery unverified. These are recorded-criterion observations, not semantic judgments of strategy or whole-task success.

## Capture beside the tool loop

Use source JSON pointers, optionally qualified by event kind and trajectory. Pointers refer to the actual exported document. `call_ref(...)` also accepts an exact normalized call identity; ATIF namespaces calls, so source pointers are often easier there. Missing, ambiguous, wrong-kind, cross-trajectory, future and unlinked references are rejected. For tools returning several feedback records, use the exact result pointer rather than an ambiguous call reference.

```python
from tracker.state_capture import WorkStateRecorder, source_ref, file_versions

state = WorkStateRecorder(environment="actual-container-image-and-config-id")
action = source_ref("/trajectory/0/action", kind="action")
result = source_ref("/trajectory/0/observation", kind="feedback")

# Record at dispatch, using the input versions actually supplied to the tool.
inputs = file_versions(workspace, ["app.py", "test_app.py"])
snapshot = state.snapshot(action, inputs)

# After receiving the real result, attach the producer's recorded facts.
state.check(
    action, result, snapshot=snapshot,
    criterion_id="acceptance-tests",
    criterion_version=actual_test_definition_version,
    required_objects=["app.py", "test_app.py"],
    outcome=recorded_check_outcome,  # passed, failed, or unknown
    state_stable=None,
)

enriched = state.attach(native_trajectory, format="swe-agent")
outbox.log(rollout_id, enriched, format="swe-agent", state="complete")
```

No source text is rewritten, and the original dictionary is unchanged. The enriched document has its own source identity. Existing work-state evidence cannot be overwritten. Attach only records whose referenced events are present in the emitted snapshot; pending tool results must wait for their source records. The recorder is in memory; persistence begins when the enriched source is committed to the outbox or imported.

`file_versions(root, paths)` hashes named files as exact bytes and records missing files as `absent`; it does not export contents or absolute paths. It rejects paths outside the root, duplicate paths, non-files and reads above its byte allowance (100 MB by default). These sequential reads are not an atomic snapshot or proof of input stability. Preserve artifact contents separately when a researcher needs to inspect a diff or reproduce a check.

For business or browser state, use `object_version(json_value)` and meaningful object identities, for example `{"order:123": object_version(recorded_order)}`. Include rule/data/environment versions required by the criterion. Do not substitute a current object for the historical object supplied to the check.

## State stability and scope

The recorder does **not** infer `state_stable=True`. Matching hashes before and after execution cannot rule out a transient change or establish what the checker read. Supply true only when the producer establishes that the scoped inputs were held fixed, for example by running the check over the captured immutable inputs. Otherwise leave it unknown. Checks remain bound to their snapshots, but recovery and final applicability remain unknown.

Likewise, `required_objects` is an explicit producer-supplied dependency scope, not automatic program analysis. The recorder does not discover imports, database dependencies, nondeterminism or external services. Outcome and criterion version must come from the tool/evaluator contract. A process exit status alone is not a universal acceptance criterion. The tracker rejects contradictions with recognized test summaries, but that limited check is not independent verification of all producer assertions.

## Edits and deliveries

Capture a before snapshot at or before dispatch, and the resulting state at its source-native result:

```python
before = state.snapshot(edit_action_ref, before_versions)
after = state.snapshot(edit_result_ref, after_versions)
state.edit(edit_action_ref, edit_result_ref, before=before, after=after)

final = state.snapshot(delivery_ref, delivered_versions)
state.deliver(delivery_ref, snapshot=final, requirements=[{
    "criterion_id": "acceptance-tests",
    "criterion_version": actual_test_definition_version,
    "basis": "task",  # or research_policy; retain the distinction
}])
```

The backend computes changed objects from versions; an edit request with unchanged recorded state does not establish a relevant change. Changed criterion versions cannot silently become recovery of the original criterion. Agent checks and edits must bind to agent actions and their actual results. User-simulator actions are excluded by `work-state/6`; older saved measurements retain their version. Existing version-pinned monitors require a new definition to use this revision; no old values are rewritten.

## Researcher workflow

In **Monitors → Add monitor → Analysis**, select the source observer and one of:

- **Checks bound to recorded input state** — capture coverage, not passing-check frequency.
- **Recovery of the recorded criterion** — comparable recovery within the next three same-criterion checks, with a recorded relevant change; unknown opportunities remain explicit.
- **Verification applicable at delivery** — required checks whose recorded results apply to the delivered input versions.

Open a per-rollout value to inspect its immutable measurement, source events, snapshots and graph links. Supply real training coordinates if available. Sources without them remain individual inspectable values and never receive invented training curves. State observations complement semantic units and work identities; they do not label exploration, exploitation, intention or deviation.

See the [executed cross-domain audit](../research/state-capture-2026-10-11/README.md). It contains controlled tool executions with known input handling, not agent performance or independent semantic-accuracy results.
