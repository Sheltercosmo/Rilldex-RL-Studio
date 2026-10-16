# Capture mini-SWE-agent while it runs

The tracker now supports mini-SWE-agent v2 native parsed actions, text/tool/Responses output records, explicit interruptions and final exits. The live hook was executed with upstream **2.4.6**, its `DefaultAgent`, `LocalEnvironment` and deterministic test models. The core tracker needs no mini-SWE-agent dependency; install/use it in the producer's existing environment.

```python
from minisweagent.agents.default import DefaultAgent
from tracker.capture import Outbox
from tracker.mini_capture import MiniCapture, CaptureMixin

class ObservedAgent(CaptureMixin, DefaultAgent):
    pass

outbox = Outbox("worker-0.sqlite", producer="experiment-a/worker-0").start(
    report_status=True
)
capture = MiniCapture(
    outbox,
    rollout_id=actual_rollout_id,   # stable across retries, new for another run
    context=lambda: actual_rollout_metadata,
    on_error="warn",              # preserve native execution; inspect failures
)
agent = ObservedAgent(model, environment, capture=capture, **agent_config)
try:
    result = agent.run(task)
finally:
    print(capture.counts, capture.last_error, outbox.status())
    outbox.close()
```

The mixin calls the upstream save method first, returns its original value, and enqueues the resulting full snapshot locally. Background delivery handles HTTP separately. `close()` stops delivery; it is not a guarantee that every pending revision has arrived. Keep the outbox and replay pending records with the existing outbox CLI. Native files remain usable even if tracker capture fails. Choose `on_error="raise"` when a capture failure should stop the job; `warn` continues and counts the failure. Monitor both capture failures and outbox backlog.

Create a new capture object/rollout identity for each `agent.run(...)`; reusing an identity for a new trajectory conflates attempts. Supply actual task, sample, experiment, split, rollout and policy coordinates when known. The hook does not derive training steps from model-call counts or infer checkpoint identity. Per-rollout context should identify the same attempt across its revisions.

## Recorded completion is separate from task success

`Submitted`, `LimitsExceeded`, `TimeExceeded`, `RepeatedFormatError` and `UserInterruption` are recorded terminal traces (`complete` ingestion state). Their original termination status remains in the source. A limit or format-error ending is not success. Unexpected exception exits use `failed`, which keeps the partial source visible and withholds completed-rollout measures. An ongoing save uses `in_progress`.

This distinction matters: excluding normally ended limit cases as failed capture would bias the population toward successful tasks. Source and behavioral metrics still require their own evidence and denominators. Submission alone supplies no verified-success label.

## Optional state-aware measures

Supply `enrich=lambda doc: state.attach(doc, format="mini-swe-agent", metadata=actual_rollout_metadata)` to `MiniCapture`, where `state` is a [WorkStateRecorder](STATE_CAPTURE.md). Capture the actual input versions in your environment's execution hook, before dispatch, and bind outputs after return. The saved source references are:

- Parsed action: `/messages/I/extra/actions/J`.
- Text or tool output: `/messages/K/content`.
- Responses API output: `/messages/K/output`.
- Submission content: the recorded exit message's `/messages/K/content`.

Use actual recorded indexes or exact adapter call IDs; do not guess which output belongs to which action. Our normalized IDs are `mini:I:J`, with native tool IDs preserved separately. Several actions can be batched, output order can differ by format, and an early submission can prevent later actions from executing. Raw parsed actions alone do not prove execution.

State enrichment is optional and may only add/replace the `work_state` sidecar; the entire native trajectory must remain equal. `WorkStateRecorder.attach` itself refuses to overwrite existing evidence. Correct scope, outcome and input-stability assertions remain the producer's responsibility. The [executed example](../research/mini-runtime-2026-10-11/audit.py) captures immutable verifier inputs and real edits; it is an audit, not a general automatic dependency detector.

## Compatibility and cost

V2 imports use `mini-swe-agent/2`. Existing legacy text-fence imports retain their old version and identities. Missing parsed actions are not guessed from display text. Format-error feedback cannot become a user goal change, and framework limit exits cannot become agent completion claims. Duplicate call identities/results fail instead of creating ambiguous links. Referenced media remains unobserved by text analysis.

Capture enqueues one full snapshot per upstream save. Long trajectories have growing serialization, storage and network costs; this is not delta ingestion. The outbox has explicit capacity limits and fails visibly when full. These source operations use no external model tokens. Optional semantic inspection has [separate budgets](SEMANTIC_EXTRACTION_WORKFLOW.md).

Pin your producer version and rerun preflight after upgrades. The audit covers actual native control flow with authored deterministic outputs, not learned-policy behavior, container environments, distributed RL or semantic accuracy. See [evidence and reproduction](../research/mini-runtime-2026-10-11/README.md).
