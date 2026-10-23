# Continuous semantic observation

The collector receives rollouts; the monitor service refreshes saved measurements.
The opt-in **semantic worker** connects those two stages by extracting and
publishing activities, plan links, work-target links, executor feedback and approach comparisons as
completed rollouts arrive. An optional feedback-reference pass connects agent
prose to prior tool responses. All run without the UI.

This first worker is local and serialized. It accepts the common normalized
source contract, rather than a Harbor/SWE-specific format. It does not schedule
every experimental relationship or reward detector. It does not establish general semantic accuracy or production
throughput.

## Continue from a pilot

```sh
python -m rilldex.models watch observations --db study.sqlite --experiment trial --from-pilot pilot --follow
```

The installed command reuses exact pilot decisions, pins its models and analysis
stages, and handles saved and arriving rollouts. Set `--candidate-calls`,
`--decision-calls` and `--input-bytes` for new work; defaults are zero for a new
worker and retain saved limits on restart. These are additional worker lifetime
ceilings, separate from the pilot's recorded usage. Reported-error, target-return
and feedback-coverage monitors use the same observer and appear in Behavior measures.
Work-target observation also adds **Changed inputs on work revisits** and
**Repeated inputs and feedback**. Open a measured case to compare both attempts,
intervening operations and captured feedback. These use saved evidence with no
additional model calls; incomplete comparisons remain unknown.
New workers also add **Changed approaches in repeated work**. Its saved pair
comparisons distinguish unchanged procedures, changed inputs/settings and
alternative procedures; opportunities and unknown comparisons accompany the rate.
**Errors on repeated work** joins those attempts to saved executor inspections,
keeping repeated errors, inspected absence and unresolved follow-up distinct.
Existing pauses are preserved. Omit `--from-pilot` to use the current installed
protocol. The UI generates this command under **Models → Observe an experiment continuously**.

Use `watch-status` below for per-stage coverage and blocked jobs. After raising a
limit, add `--retry-run RUN_ID` on restart. All requested stages must finish before
a rollout is published under the observer; pending rollouts are not negative results.
For a custom proposer, `watch-init --behavior-links` enables the same stages.
Old workers retain their original protocol and publications.

## Start without model calls

Use the same database and experiment name as your collector:

```sh
rilldex --db study.sqlite semantic watch-init observations --experiment trial --label "Base activities"
rilldex --db study.sqlite semantic watch-run observations
rilldex --db study.sqlite semantic watch-status observations
```

Defaults allow **zero** new provider invocations. The worker creates source-bound
candidate request files in `observations/runs/<run-id>/candidates/requests`.
Supply responses using the existing [candidate process contract](../tracker/candidate_worker.py),
or configure a candidate command when creating the worker. File-based requests
and responses remain compatible with `semantic prepare/run/status/audit`.
Use `watch-run --retry-run RUN_ID` to resume after supplying or repairing proposals;
blocked jobs are not retried on each poll.

## Connect your candidate proposer

Pass an executable argument list after `--candidate-command`; no shell expansion
is performed. The proposer reads one JSON packet on stdin and returns one JSON
object on stdout. It receives stage-specific definitions and source evidence;
Jev performs the finite-choice argmax selection. Version the producer name when
changing the candidate model or prompt. Keep credentials in the process environment,
not command arguments. The Jev key is excluded from the candidate child's environment.

```sh
rilldex --db study.sqlite semantic watch-init observations --experiment trial --label "Base activities" --candidate-producer proposer-v1 --candidate-command python proposer.py
rilldex --db study.sqlite semantic watch-budget observations --max-new-calls 100 --max-candidate-calls 100 --max-input-bytes 2000000
rilldex --db study.sqlite semantic watch-run observations --follow --candidate-command python proposer.py
```

These are example **lifetime ceilings**, not estimates for a rollout. The first
command requires a fresh worker directory if a different configuration already
exists. The executable name must be available on that machine; an absolute
Python/interpreter path works on Windows, Linux and macOS. Only Windows execution
has been validated for this increment.

The `JEV_API_KEY` and the existing proxy configuration are read by the normal Jev
client. The same candidate argument list is required on resume; raw arguments are
not stored in the worker configuration. A custom command implements the supplied
JSON contract; the installed `python -m rilldex.candidate` adapter is also available.

Use `--workspace-options options.json` at initialization to pin existing options:

```json
{
  "include_user": true,
  "partition_standard": "contribution-boundaries/4",
  "activity_routing": "work-phase-activity/1",
  "reading_protocol": "contribution-readings/1",
  "context_policy": {
    "schema": "readable-context/2",
    "recent_events": 8,
    "max_event_chars": 4000,
    "extra_ranges": []
  }
}
```

These select a versioned extraction protocol; they are not universally validated
defaults. Source, options and extractor implementation are frozen. Changed
protocols require a new worker identity; old observations remain inspectable.

After a package update, run `rilldex --db study.sqlite semantic watch-refresh observations`,
or add `--refresh-worker` to `python -m rilldex.models watch`. Refresh replays
saved work offline and requires every published map to remain identical. It
keeps the observer, protocols, measurements, blocked jobs and lifetime usage.
If replay changes a map or the pinned protocol is unsupported, keep the original
worker and create a new observer. `watch-status` reports whether refresh is needed.

## Add explicit feedback references

Enable this layer when initializing a **new** worker:

```sh
rilldex --db study.sqlite semantic watch-init feedback-observations --experiment trial --label "Activities and feedback" --feedback-references --candidate-producer proposer-v1 --candidate-command python proposer.py
```

Set the lifetime allowance and start it as above, using `feedback-observations`
as the worker directory. The flag adds the pinned `feedback-references/1` profile;
the equivalent workspace option is `"feedback_profile": "feedback-references/1"`.
It does not grant any provider allowance. This profile is opt-in because it adds
Jev questions and a new observation scope.

After base units and content are complete, the worker asks which prior visible
tool responses each eligible agent prose contribution explicitly describes or
interprets. Primary activity labels stay unchanged: an Orient or Coordinate unit
can refer to feedback without gaining a second activity label. Source-native
action/response bindings, same actor/trajectory constraints and prefix-only
candidate retrieval determine the offered responses. Jev selects the raw argmax
option. Retrieval and context omissions remain recorded; no confidence threshold
is applied. This layer needs no additional generative candidate calls.

Base and feedback requests share one durable budget and exact-decision cache.
Stopping between stages retains the base and any completed feedback decisions.
After raising the ceiling, explicit retry resumes the missing questions. Nothing
is published under this new observer until all requested stages audit successfully.
A source revision during inference also prevents stale publication.
`semantic status WORKER/runs/RUN_ID` includes `layers.feedback`; worker job details
include the audited layer scope or the pending layer status when blocked.

The existing `feedback_reference` analysis counts **tool-response opportunities**,
not relation edges. Two references to one response count once. It uses the next
three nonempty agent text events from the same recipient and trajectory. A selected
reference can establish a positive; a negative needs the complete window,
segmentation, reviewed contributions and visible candidate evidence. Missing or
incomplete evidence remains unknown and outside the rate denominator. This
measures explicit reference, not correct interpretation, silent use or recovery.

For a code-only monitor, use the observer ID returned by `watch-status`:

```python
from rilldex import Workspace
from tracker.store import Store
from tracker import monitoring

observer = "<observer ID from watch-status>"
store = Store("study.sqlite")
monitor = monitoring.create(store, {
    "name": "Explicit feedback reference",
    "kind": "analysis", "observer": observer,
    "analysis": {"measure": "feedback_reference"},
})
monitoring.sync(store)  # Uses saved observations; no model calls.
data = Workspace("study.sqlite", observer=observer)
print(data.table("monitor_values", monitor_id=monitor["id"]).rows)
print(data.relations(relation="assesses").rows)
```

The same monitor and evidence cases are available in the dashboard. These reads
do not rerun extraction. Adding this layer to a previously published base worker
requires a new identity; it must not overwrite the old observer's meaning. Exact
base decisions can be reused through `tracker.decision_cache`, with receipts.
Implementation refresh does not add analysis layers or change protocols. The retained
[live trial](../research/2026-10-15-continuous-feedback-trial.md) demonstrates reuse
without spending again on the base extraction.

## Arrival, failures and restart

- `watch-run` handles at most eight rollouts; `--follow` polls every five seconds.
  `--max-rollouts` and `--max-pending` bound each batch and queued backlog. This
  does not make the full experiment inventory scan constant-cost.
- In-progress/failed producer revisions wait. Ordinary imported snapshots are
  eligible as recorded snapshots; this does not imply their original run finished.
- A current completed revision gets one durable job. Superseded sources are
  checked before extraction and again inside the publication transaction. If a
  revision changes during a remote call, that call may still consume budget;
  its stale result is retained but not published as current.
- The OS lock prevents overlapping owners on one local filesystem. A crashed
  owner releases that lock. Its job becomes interrupted, not silently retried.
- Provider/configuration failure or exhausted budget pauses further execution.
  Fix the issue, then explicitly use `--retry-run RUN_ID`. Existing exact cached
  decisions and proposals are reused. A failed publication can retry without
  redoing successful extraction.
- `watch-budget` raises absolute lifetime ceilings. Restart, reinitialization
  and retry never refill them. A reservation is recorded before external work;
  failed and unfinished attempts remain counted. Unknown completion/billing is
  never represented as zero usage.
- Limits count provider invocations and UTF-8 request bytes, **not tokens or
  money**. The built-in Jev client sends one POST attempt per invocation and never
  retries automatically, including after a timeout or HTTP 429. An explicit retry
  makes a new reservation. Older clients and custom transports may differ; multiple
  model calls inside a candidate command are not separately capped. Provider
  account limits are needed for a hard financial ceiling.
- `watch-status` also returns `provider_usage.providers`: reported input/output/
  total token counters, the number of attempts reporting each counter, stage
  counts, and attempts with no usage report. These totals survive restart and
  include failed/unfinished reservations. A missing counter is unknown, not zero;
  explicit reported zero is retained. File-based candidate handoffs are outside
  this ledger, so `candidate_requests: 0` does not mean a separately run proposer
  consumed no tokens. Usage reporting does not impose a token or currency cap.
- Failed attempts retain safe operational facts: HTTP status, a numeric
  Retry-After hint when supplied, and whether the remote outcome is unknown or
  nothing was sent. Provider response bodies and credentials are excluded.
  An unknown outcome is not zero cost or evidence that the provider did no work.

Keep the database **and** worker directory on durable storage. A path or database
move is not an automatic worker migration. Do not run this SQLite/OS-lock worker
as a distributed shared-filesystem scheduler. The dashboard server never starts
this worker or spends inference budget implicitly.

## Results and code access

Candidate subprocess failures also appear in `provider_failure` on the job and
its budget attempt: timeout, UTF-8/pipe error, excessive stdout/stderr, exit code
or startup failure. The [runner contract](SEMANTIC_WORKSPACES.md#optional-generator-process)
defines output limits, descendant cleanup and per-attempt receipts. A failed
process does not imply that its remote API call was cancelled or unbilled.

The observer ID stays stable as new rollouts arrive. Complete audited results are
archived in the database. The archive, graph, rollout measurements and published
job state commit together. Existing maps, monitors and code analysis can select
that observer. Incomplete extraction does not produce a zero-valued behavior
measurement. Relation-dependent measures remain unavailable when this base pass
has not selected their required relationships.

```python
from tracker.store import Store
from tracker.semantic_watch import status

progress = status(Store("study.sqlite"), "observations")
print(progress["current_published"], progress["current_sources"])
print(progress["job_counts"], progress["remaining"])
```

Job states distinguish queued, running, published, superseded, ineligible,
needs_candidates, budget_reached, failed and interrupted. The journal tables are
`semantic_watchers`, `semantic_watch_jobs` and `semantic_watch_attempts`.
`watch-status` is an inspection snapshot, not proof that a daemon is currently alive.

## Validation and limits

`scripts/audit_semantic_watch_replay.py --output FRESH_DIRECTORY` runs 16 retained
real training outputs through the worker and normal Jev HTTP client, using a
strictly matched local replay endpoint. It injects an HTTP 429, confirms that
polling/restart cannot resend it, explicitly retries with a new reservation, and publishes 49
historical selected units under one observer, reopens the database between source
batches and verifies no duplicate extraction. Activity metrics cover all 16
rollouts; unextracted feedback relationships cover zero.

To validate an installed wheel, invoke the same script with `python -X utf8 -I`
and absolute source/output paths from outside the checkout. Isolated mode checks
that Rilldex resolves to `site-packages`. The audited run uses 115 HTTP attempts
and 115 reservations, including the explicit retry. The
[provider attempt audit](../research/2026-10-15-provider-attempt-accounting.md)
also covers late responses and unknown completion.

Separate lifecycle tests kill a real worker process after request reservation,
inject provider/validation/publication failures, and change source revisions
while queued and during extraction. These validate architecture invariants.
The replay makes **zero fresh external model calls**. Historical candidates and
responses do not measure fresh generation, held-out semantic accuracy, a live
optimizer or distributed training behavior. See [validation strategy](VALIDATION_STRATEGY.md).
