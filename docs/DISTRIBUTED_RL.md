# Mixed and asynchronous RL execution

Reviewed 15 October 2026. The implemented increment is an execution ledger and
code-first population analysis. It is not a distributed scheduler or a claim that
the current SQLite collector has production cluster capacity.

## What must remain distinct

| Object | Identity / meaning | Common mistake to avoid |
|---|---|---|
| Experiment / resumed branch | Explicit run namespace; a counter reset or fork needs a new policy-clock origin | Joining unrelated policies because both say step 100 |
| Environment episode | Producer + logical rollout ID | Counting every inference call as a rollout |
| Execution attempt / segment | Experiment + producer + record ID; revisions update that attempt | Treating a backend retry as a new training sample |
| Inference service | Backend/version, pool, actual instance, model/role, recorded policy version | Assuming an OpenAI-compatible endpoint establishes backend or weight identity |
| Training sample and use | Existing independent sample ledger, exact source references and repeated use facts | Assuming completed generation was admitted or used by the learner |
| Semantic behavior | Saved source and graph identities | Inferring strategy quality from server latency |

Keep environment, harness, inference backend, policy, and trainer versions
separate. Multi-agent roles may use different models; verifier calls are separate
from actor calls. Multiple inference requests can belong to the same episode.
Partial generation across policy updates needs the existing **token policy
segments**, not one guessed checkpoint label for the entire episode.

## Evidence informing the design

- [verl V1 asynchronous trainer](https://verl.readthedocs.io/en/latest/advance/v1_async_trainer.html)
  distinguishes colocated and separate asynchronous resources; aborted generation
  retains tokens and can resume across model versions. Our capture must retain
  suspended work and segment provenance independently of learner updates.
- [verl Agent Loop](https://verl.readthedocs.io/en/latest/advance/agent_loop.html)
  separates agent orchestration from inference servers and describes request
  balancing/sticky routing. An episode ID and a serving-instance ID are different.
- [AReaL asynchronous RL](https://areal-ai.io/docs/en/algorithms/async.html)
  makes staleness control explicit and supports partial trajectories. We keep
  policy-clock evidence rather than deriving policy age from arrival order.
- [slime customization](https://thudm.github.io/slime/get_started/customization.html)
  separates generation, reward computation, dynamic sampling, buffer filtering
  and training participation, including streaming completed groups to storage.
  These populations must not be collapsed into one completion counter.
- [NeMo Gym 0.7.0 system design](https://docs.nvidia.com/nemo/gym/v0.7.0/infrastructure/engineering-notes/system-design/)
  separates environment, agent, model and resource services, including isolated
  processes and HTTP calls. Observe those boundaries without requiring their
  dependencies to live in the tracker process.
- [Where Does Staleness Accumulate?](https://arxiv.org/abs/2609.36830)
  distinguishes generation staleness from waiting in the completed-trajectory
  pool. This motivates separate generation/queue/use evidence; its reported
  experimental findings have not been reproduced here.

These sources support the design requirements. They do not establish native
adapter compatibility or validate our collector's scaling limits.

## Capture from different environments and serving stacks

Use a local durable outbox per worker/collector producer. The environment or agent
harness supplies native identities; report bounded packets in the background.
No inference request passes through Jev and no semantic model call is scheduled.

```python
from tracker.capture import Outbox

out = Outbox("worker-7.sqlite", producer="job-uuid/worker-7",
             endpoint="http://127.0.0.1:8810")  # local collector or tunnel
context = {
    "split": "train",
    "framework": "your-framework", "framework_version": "recorded-version",
    "environment": "terminal", "environment_version": "task-image-digest",
    "backend": "vllm", "backend_version": "recorded-version",
    "server": "pool-a/replica-3", "pool": "pool-a",
    "model": "actor-model", "model_role": "actor", "policy_version": "native-v12",
}
call = {
    "id": "native-request/segment-0", "revision": 0, "kind": "inference",
    "rollout": {"producer": "job-uuid/orchestrator", "id": "episode-42"},
    "parent": {"producer": "job-uuid/orchestrator", "id": "episode-42/attempt-0"},
    "state": "running", "context": context,
    "evidence": "Native serving completion hook; local monotonic request timer",
}
out.log_execution("job-uuid", [call])
# Execute the actual request. Obtain elapsed_ms from a local monotonic timer.
out.log_execution("job-uuid", [{
    **call, "revision": 1, "state": "completed",
    "metrics": {"duration_ms": elapsed_ms, "output_tokens": native_output_tokens},
}])
out.drain()  # or use the existing background sender; logging itself is local
```

Values above are placeholders; do not claim a backend/version you did not record.
For routed APIs where instance or policy identity is hidden, omit those fields.
Their values remain null in the SQL views. A new request attempt, backend/model
switch or policy segment uses a new ID, optionally with `retry_of: {producer,id}`.
Forward the original rollout reference across services. Parent and retry links
are producer declarations; absent parents remain unresolved and are not invented.

Kinds: `rollout`, `inference`, `environment`, `verification`.
States: `queued`, `running`, `suspended`, `completed`, `failed`, `cancelled`.
Completion describes execution, **not task success**. An exception, cancellation,
unfinished operation, failed verifier outcome and learner rejection are different.
Report actual task outcomes and selection/use through their existing contracts.

The `execution-records/1` packet contains `schema`, `producer`, `experiment` and
1–1,000 `records`. Each record requires `id`, nonnegative `revision`, `kind`,
`rollout`, `state`, `context`, and an `evidence` description. Optional fields:
`parent`, `retry_of`, `source_revision`, `metrics`, timezone-aware `observed_at`,
and a bounded `reason`. `context` accepts the fields in `execution_records.CONTEXT`.
Use opaque resource IDs, not authenticated endpoint URLs or credentials.

Each revision is a self-contained snapshot. Revision gaps and reversed delivery
are accepted; greatest explicit revision wins. Identical retries are idempotent.
Identity/context conflicts reject the whole packet. Known context may be added
but cannot disappear/change in later revisions. Terminal attempts cannot reopen;
give an actual retry a new attempt ID. No timestamps are used to settle conflicts.

Supported metrics: `duration_ms` (terminal only), `queue_ms`, `elapsed_ms` for a
reported unfinished operation, and integer `input_tokens`/`output_tokens`.
Durations must be measured at a defined local boundary. We do not subtract
timestamps from different hosts, infer queue delay from arrival time, or add
nested call durations to claim total wall time. `source_revision`, when supplied,
pins the rollout reference for exact source joins; there is no newest-source fallback.

The same packets support direct `POST /api/execution-records`, durable SDK delivery,
offline capture bundles and returned delivery receipts. Capture files can be kept
on worker-local disks; do not share one SQLite outbox over a network filesystem.
After restart keep producer identities/outbox state; a genuinely new attempt gets
a new ID. A full outbox raises capacity errors rather than silently losing data;
choose a capture failure policy appropriate for the trainer.

## Useful measurements for asymmetric workloads

```python
from tracker.research import Analysis
data = Analysis("workspace.sqlite")
work = data.execution_summary(experiment="job-uuid", kind="inference",
    group_by=["environment", "environment_version", "backend", "model", "model_role"])
rows = data.table("executions", experiment="job-uuid")
feed = data.changes("executions", cursor=saved_cursor)
```

CLI: `rilldex --db workspace.sqlite analysis execution-summary --experiment
job-uuid --kind inference --group-by environment --group-by backend`.
`rl_executions` is available in custom SQL, scoped exports, frozen SQLite datasets
and result mirroring. Old workspaces/datasets expose availability explicitly; a
missing ledger is not a measured zero. Upgrade the collector to enable intake.

| Measure | Implemented meaning | Interpretation boundary |
|---|---|---|
| State counts / unfinished | Latest reported state per execution attempt | Recorded state is not a heartbeat; process death may leave running state |
| p50 / p95 / max completion duration | Nearest-rank quantiles of measured completed durations; measured/eligible counts included | Excludes unfinished, failed and cancelled duration; not an unbiased total latency estimate |
| Queue delay / unfinished elapsed | Reported local values, with coverage counts | No inferred waiting time or automatic timeout label |
| Explicit retry attempts | Attempts carrying a `retry_of` reference | No inference from similar text; unresolved link does not prove predecessor failure |
| Completion mix shift | Share among completed attempts minus share among all observed attempts | Shows selection pressure worth investigating; not evidence of causal reward change |

Use one kind per summary. Compare environment/version, harness, model role,
backend and policy context explicitly; pooling them can explain apparent behavior
changes. Defaults separate split, environment/version, backend, model and model
role, including unknown values. Override grouping deliberately when comparing
other dimensions. Repeated training uses should not add rollout weight. Existing sample,
filter and policy-age analyses answer what was selected/used and under which policy.

The summary refuses truncated populations (100,000 input rows / existing 32 MiB
and 10-second SQL limits). For larger studies, use scoped SQL and exported columns
in DuckDB/Parquet. Persist a manifest with the actual time/step/selection window;
never report an arbitrarily limited prefix as the whole experiment.

## Deployment path and remaining work

1. **Single machine / moderate collector:** worker-local outboxes → HTTP intake →
   SQLite/WAL ledger → code/UI readers. Use SSH/private routing for remote workers.
   Measure delivery backlog, blocked packets and query lag using existing producer
   health; do not place the synchronous collector in the inference critical path.
2. **Large cluster target, not implemented:** partition durable ingestion by stable
   experiment/producer identity; retain at-least-once receipts and replay. Store large
   trace/token artifacts in object storage, operational identities in a transactional
   service, and append-only execution/training facts in a columnar analytical store.
   A shared query layer must deduplicate revisions across shards before aggregation.
3. **Bound analysis independently:** native execution facts on all reported work;
   reusable semantic extraction on an explicit bounded population; targeted deep
   inspection of matched failures, stragglers or shifted cohorts. Preserve sampling
   probabilities and coverage before interpreting sampled behavioral rates.

Do not deploy multiple collector writers against one network-mounted SQLite file.
Automatic sharding, cross-shard query/recovery, distributed semantic scheduling,
production admission control and universal native inference hooks are still work
to validate. This increment tests lifecycle/identity/measurement semantics and
concurrent local HTTP delivery; it does not execute vLLM, SGLang, GPUs or a cluster.
