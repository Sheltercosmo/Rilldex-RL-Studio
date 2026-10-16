# Running-job integration

**14 October update:** [`start`, installation checks and managed JSONL collection](GETTING_STARTED.md) now cover empty-directory setup, attachment during training and replay after training. Native Harbor/SWE-agent collection remains available. JSONL accepts any supported single-rollout adapter or explicit revision envelopes; it uses durable append cursors rather than repeated frozen-file imports. No inference is launched by collection.

Implemented 9 October 2026. Open [Data connections](http://127.0.0.1:8765/connections). This is a local, continuous ingestion path with durable revisions and visible collector health. It does not start training or automatically run semantic inference.

## What changed and why

The previous UI periodically reloaded saved measurements. A separate `watch` command could collect files, but the application neither managed that collector nor showed its health. Manual imports often omitted the result files that contained rewards. Refreshing a historical dataset was therefore easy to mistake for monitoring a running job.

The practical workflow is now: connect the producer → save source revisions → materialize measurements → push a change notification → inspect the updated rollout or chart. Capture, receipt and analysis status are shown separately. The collector resumes after the server restarts; pause/resume is available in the UI. An empty directory can be connected before the job starts.

## Practices examined

| Project and primary source | Relevant practice | Implementation decision here |
|---|---|---|
| [Harbor job outputs](https://github.com/harbor-framework/harbor/blob/main/docs/content/docs/run-jobs/run-evals.mdx) | Job directories contain trial configuration, agent trajectories and separate verifier/result artifacts. | Connect the job directory. Collect late result changes under the same rollout identity. Preserve the existing continuation and retry handling. |
| [SWE-agent trajectory persistence](https://swe-agent.com/latest/reference/agent/) | The agent saves its trajectory/history/state as a JSON `.traj` document. | Tolerate partially written snapshots and retry. An invalid replacement must not erase the preceding valid revision. |
| [verl rollout tracing](https://verl.readthedocs.io/en/latest/advance/rollout_trace.html) | Trace context includes training step, sample identity, rollout repeat and evaluation context. Trace sampling is configurable per worker and retains rollout groups. | Keep these coordinates producer-supplied. The outbox accepts explicit metadata, independently of its delivery order. Do not equate an import timestamp with a training step or silently claim sampled data covers all rollouts. |
| [ART metric logging](https://art.openpipe.ai/features/tracking-metrics/) | Rollout metrics and group metrics have different granularity; logging writes step-level history. | Keep per-rollout evidence and revisions separate from chart aggregation and training updates. Capture is cheap and independent of semantic inference. |

These are engineering patterns, not claims that we implement native ART/verl tracing backends or have feature parity with them. Harbor and SWE-agent directories are the managed connectors in this delivery. Other existing trajectory adapters can be used through the outbox or snapshot import.

## Harbor and SWE-agent: connect existing output

1. Start the tracker with `python -m rilldex serve --port 8765`.
2. In **Data connections**, enter the output directory on the tracker host and a producer name unique to that job/worker.
3. **Check directory** previews discovered paths without importing. **Connect & watch** starts collection. The default interval is two seconds.
4. Follow received rollouts, deferred files and last successful receipts. Open a rollout from the receipt table. The Rollouts page updates automatically and shows lifecycle state.

For Harbor, choose a directory containing `trial/agent/trajectory.json` and `trial/result.json`. For SWE-agent, choose the directory containing `.traj` files. The collector reads source files; it does not write to the job directory. Pause takes effect between files; an in-flight ingestion may finish.

Supply stable experiment defaults in the connection form. Supply changing coordinates per rollout:

```json
{
  "experiment": "my-training-run",
  "training_step": 42,
  "checkpoint": "policy-42",
  "sample_id": "task-17",
  "rollout_n": 2,
  "split": "train"
}
```

Save this as `trial/tracking.json` for Harbor, or beside `sample.traj` as `sample.tracking.json` for SWE-agent. Per-rollout values override connection defaults. Do not put a fixed training step in connection defaults for a directory spanning multiple steps. The producer owns task, policy and training-coordinate correctness.

The `recorded_reward` monitor now reads Harbor's explicit `verifier_result.rewards.reward`. If the reward has a different name, specify `reward_key` in metadata. It does not sum or arbitrarily choose among reward fields. The exact result-source ID and JSON pointer are retained in the measurement and shown in its evidence view. Existing sources are upgraded through new metric records; older receipts are preserved. A reward is not automatically a task-success label.

## Python producers: durable delivery

Install the local package with `pip install -e .` in the producer environment. Use one persistent outbox and one producer identity per worker. The producer supplies a supported native trajectory document; this client is not a universal trace converter.

```python
from tracker.capture import Outbox

client = Outbox(
    "worker-0.sqlite",
    producer="run-a/worker-0",
    endpoint="http://127.0.0.1:8765",
).start(report_status=True)

# Inside the rollout loop, after a snapshot is available:
client.log(
    rollout_id=f"{training_step}/{sample_id}/{rollout_n}",
    document=native_trajectory,
    format="swe-agent",  # or harbor / another supported adapter
    state="in_progress",
    metadata={"experiment": "run-a", "training_step": training_step,
              "sample_id": sample_id, "rollout_n": rollout_n, "split": "train"},
)
# Emit a final snapshot with state="complete" or "failed".
# Neither lifecycle value asserts task correctness.
print(client.status())
client.close()  # Stops delivery; it does not discard or guarantee a flush.
```

`log()` serializes and commits locally without HTTP or model calls. It is synchronous disk work, not zero-cost instrumentation. The background sender retries network errors, HTTP 429 and server errors. It preserves per-rollout order. A lost acknowledgment replays the same immutable revision; the server deduplicates it. Identical successive snapshots reuse their queued revision.

HTTP client/schema conflicts are marked **blocked** and do not block other rollout streams. Inspect and resume after fixing the receiving configuration:

```sh
python -m rilldex outbox worker-0.sqlite --producer run-a/worker-0
python -m rilldex outbox worker-0.sqlite --producer run-a/worker-0 --send
python -m rilldex outbox worker-0.sqlite --producer run-a/worker-0 --retry-blocked --send
```

`--send` drains at most 100 eligible snapshots by default (`--limit` changes this). Blocked retries use unchanged payloads. An invalid payload cannot be repaired by repeatedly resending it: preserve the failed outbox for inspection and re-export corrected data under a new producer namespace. Do not discard an outbox and reuse its producer identity against the same server; revisions would restart at zero.

The default pending-data limit is 256 MiB; one request is limited to 20 MiB. A full outbox raises `BufferError` instead of silently dropping observations. The training integration must decide whether to pause collection, retain native outputs for later ingestion, or increase the explicit limit. Acknowledged payload bodies are released locally; revision hashes and receipts remain. Raw source is retained by the tracker.

## Meaning of live

- Directory capture is polling, normally every two seconds. Unchanged source and sidecar signatures avoid reparsing. Missing sidecars are tracked so their later arrival invalidates the cache. In-place modifications that preserve both size and modification time are outside this cache contract.
- A directory snapshot may skip intermediate versions written between scans. Use the outbox when each submitted revision must be retained. Neither path exposes tokens or steps that the producer has not emitted.
- Ingestion wakes the monitor materializer. A five-second reconciliation scan still catches external writes and completed annotations. Saved observations are the only semantic input; no paid inference is launched by collection.
- A shared server-sent event stream sends current source/analysis state to open pages. Reconnect sends the latest state. The stream is a notification channel; immutable database revisions are the event history.
- Receipt visibility and finished analysis are separate. Ongoing/failed snapshots remain visible; monitors requiring a completed rollout report them as incomplete. Unknown semantic measurements remain unavailable.

The server remains loopback-only. On a training machine, run the tracker next to its output directory and forward its port to your workstation, for example `ssh -L 8765:127.0.0.1:8765 training-host`. For a producer sending to a tracker on another machine, use an appropriate SSH tunnel or an authenticated HTTPS deployment supplied separately. This delivery does not add a shared cloud service or remote authentication.

## Validation and next engineering work

See [replay evidence](../research/live-intake-2026-10-09/browser-audit.json) and the desktop/mobile screenshots in that directory. A pinned public Harbor trace was replayed with clearly authored training metadata in an isolated database. The test covered empty-directory setup, partial JSON, late reward, pushed dashboard refresh, pause/resume, reconnect and mobile layout. The measured delays are local test observations, not an SLA or distributed training benchmark.

The [11 October concurrent native audit](../research/concurrent-training-2026-10-11/README.md) now covers two independent TRL CPU trainers, live delivery, 328 exact source/reward checks, throttling and malformed-acknowledgment recovery, queue reports and pushed browser updates. It does not establish distributed gradient training or sustained production-scale throughput. Native verl/ART callbacks, large-job concurrency, bounded semantic-observer scheduling and per-observer coverage/latency budgets remain separate work.

## Worker delivery reports — 11 October

Opt in with `Outbox(...).start(report_status=True, report_interval=5)`. Reports run on a separate background thread, even while ingestion waits. The **Worker delivery** section distinguishes worker-reported queue counters from server-confirmed revision/rollout counts. The two snapshots need not coincide, especially after a lost acknowledgment. Counts are revisions/snapshots, not expected training samples; they cannot establish capture coverage.

The report sends only producer identity, persistent random outbox identity, durable sequence, sender phase, interval and queue counters/capacity/oldest age. It sends no source text, arbitrary errors or filesystem path. The server records receipt time itself. Reports become overdue after `max(15, 3 * interval_seconds)`; overdue means stale information, not a diagnosis of worker death. A graceful `close()` attempts a final sender-stopped report. Failure of that request cannot erase queued data and may leave the previous report overdue. Check `status()['delivery_report_error']` locally when reports are missing.

`POST /api/producers/report` accepts the strict `producer-delivery/1` shape defined in `tracker/producer_health.py`; `/api/connections` and the existing SSE stream include the latest reports. Equal retries and lower sequences do not refresh receipt time. Equal sequence with altered content or a different outbox under the same producer returns a conflict. Restarting the producer with its original queue continues the sequence. CLI inspection/recovery does not send health automatically; after a manual recovery, restart the original reporting sender or explicitly call `report_status(phase='stopped')` when that sender remains stopped.

Delivery scheduling now drains successful batches immediately while eligible data remains. New capture cannot cancel transient-error backoff, and a permanently blocked rollout does not introduce increasing retry delays for unrelated streams. A malformed JSON acknowledgment is a recoverable delivery failure; the exact queued revision remains intact. This improves queue behavior without claiming a production latency target.
