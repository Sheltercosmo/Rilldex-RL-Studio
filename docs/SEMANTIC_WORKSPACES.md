# Reusable semantic extraction workspaces

## Observe a rollout while it is growing

Continuous semantic workers normally wait for completed source records. To inspect
long-running work before completion, initialize a **new** worker with
`semantic watch-init WORKER --experiment EXPERIMENT --label "Live activities" --live-prefixes`.
Supply the same candidate command, versioned producer and explicit lifetime call/byte
allowances as an ordinary semantic worker. Allowances default to zero. Then use
`semantic watch-run WORKER --follow` with that configured command. Source collection
and this observer are independent processes; opening the UI starts neither.

Each latest received prefix is an immutable snapshot. The worker reuses candidates
and Jev decisions only when the entire request matches an earlier revision of the
same producer and rollout under this worker. Changed text, visible context or
protocol creates new requests. Reused candidates still undergo normal stage
validation; Jev decisions still replay their raw maximum-probability choice.
Results, unit identities and source hashes are rebuilt for the new snapshot.
Historical graphs are preserved. Completing an identical source requires no new
inference.

The dashboard's streaming rows link **Open behavior map** only when a published
observation covers that exact current snapshot. Pending, failed and budget-limited
work stays visible. A newer source never inherits an older map's ready status.
Inside the map, the source banner identifies growing or superseded snapshots.
Inspecting a map pins it rather than moving the evidence while you read it.
Incomplete captures remain excluded from completed-rollout monitor values and
training-series bins. Direct graph/code analysis can inspect prefixes, so callers
must retain source lifecycle state when comparing them.

An unresolved failed, interrupted or budget-limited job remains blocked when the
source grows. Inspect `semantic watch-status WORKER`, then explicitly retry the
**current** job with `semantic watch-run WORKER --retry-run RUN_ID`. Raising an
allowance alone does not retry it; restarts do not reset spent reservations. A
newer revision arriving during extraction prevents publication of the obsolete
snapshot, while retaining exact finished requests for subsequent reuse.

This is snapshot observation, not token-by-token inference. One worker runs one
job at a time. Fast source updates can supersede jobs before publication; choose
a collection/observation cadence that leaves enough time to inspect useful
prefixes. Source snapshots, derived graphs and local cache copies still grow with
history; exact reuse saves provider work, not storage. Protocol/code changes require
a new versioned worker. General semantic accuracy and distributed throughput are
not established by the lifecycle controls.

## Rebuild target recurrence and feedback after a revision

Use a separate output workspace to preserve a completed observer while rebuilding its history. The source must contain a complete local extraction. This works over normalized semantic units rather than a framework-specific tool vocabulary.

```powershell
python -m rilldex semantic rebuild-history .tracker/history-v2 --from-directory .tracker/revised-units --run-id YOUR_RUN_ID --reuse-decisions-from .tracker/previous-observer --max-new-calls 0
python -m rilldex semantic rebuild-history .tracker/history-v2 --audit-only
python -m rilldex semantic register .tracker/history-v2 --label "Revised work history"
```

The default `--max-new-calls 0` uses retained decisions only. A missing decision stops with `budget_reached`; resume the same directory after supplying an explicit allowance, for example `--max-new-calls 10 --prompt-key`. Completed work is retained. Both target and feedback stages must finish and replay correctly before this observer can load or register. A source or extraction change requires a new output directory.

Repeat `--reuse-decisions-from` to supply additional cache workspaces at initialization. The complete request, model and raw argmax must match; conflicting selected answers are rejected. The workflow records copied packet fingerprints and provenance, and regenerates derived results. Existing provider costs remain in their original workspaces. Cache reuse establishes reproducibility, not semantic correctness.

The default action-target protocol is `action-target-correspondence/4`; choose `--action-target-version` during initialization if a different supported frozen version is needed. The experimental `action-target-correspondence/5` independently classifies every eligible prior pair in one shared request per action, up to 16 priors. It retains multiple partial-work links, excludes siblings in the same recorded dispatch batch from temporal predecessors, and records unresolved/capacity gaps. Whole-target paths retain the most recent positive identity predecessor; all pair judgments remain saved. This protocol needs independent semantic validation before broad deployment. Source, cache directories and protocol are fixed in `history-rebuild.json`; resume with just the output directory. Method comparison, higher work scopes, goal changes and recovery are separate dependencies and are not generated by this command. See the [three-domain audit and known annotation disagreement](../research/history-reuse-2026-10-11/README.md).

For new histories, `--feedback-linkage adapter-feedback-links/1` also accepts the canonical adapter's unambiguous result associations, including Harbor same-step records without native call IDs. The optional `--feedback-reference-rule assessment-direct-sets/1` selects a single or joint response set in one bounded request. Both settings are frozen at initialization; old observers stay unchanged. The [42-case development comparison](../research/feedback-direct-sets-2026-10-11/README.md) identifies and tests the native-binding gap, reports model usage and distinguishes these checks from independent accuracy. `semantic register` resolves the run from a history/revision manifest when `--run-id` is omitted.

Optional `--feedback-retrieval feedback-recent-plus-lexical/1` retains three recent responses and adds up to two locally retrieved older responses, including exact passages from the middle of long logs. Its version is frozen at initialization. The map's **Feedback considered** disclosure separates offered candidates from selected reference connections and exposes omissions. The [50-case development study](../research/feedback-retrieval-2026-10-11/README.md) found better target availability but one selection regression and 66% more input tokens on the same software situations. It remains opt-in; existing defaults and observers are unchanged. Lexical-only `feedback-lexical-retrieval/1` is retained for comparison and can displace valid recent references. Neither method establishes complete recall or independent semantic accuracy.

## Refine an immediate work target from existing contents

`semantic refine-targets` is an experimental content repair pass. It freezes the
parent units and activities, then offers category-conditioned existing fields as
alternative work-target descriptions. It makes no candidate-generation calls;
Jev selects among the original and at most two alternatives by raw argmax. Other
fields and Plan structure remain unchanged. Rejecting all bundles leaves a repair
gap; exact citations alone do not establish semantic accuracy.

```powershell
python -m rilldex semantic refine-targets NEW_DIRECTORY --from-directory PARENT_DIRECTORY --run-id RUN_ID --prepare-only
python -m rilldex semantic refine-targets NEW_DIRECTORY --prompt-key --max-new-calls 10 --max-input-bytes 350000
python -m rilldex semantic refine-targets NEW_DIRECTORY --audit-only
python -m rilldex semantic register NEW_DIRECTORY --label "Experimental immediate work targets"
```

Use a separate directory; default new-call allowance is zero. Resume with the same
directory and frozen settings. Audits replay both original and refined contents;
collections retain the changed content protocol. Semantic relationships require
rebuilding against the new extraction. To change activities, revise the original
extraction first and then refine its targets; category-conditioned refinements
cannot be carried across a changed activity. The [development trial and retained scope
error](../research/work-target-refinement-2026-10-12/README.md) show both the useful
local-target corrections and the limits of reusing existing candidates.

## Operation observations across rollouts

The `outcomes` commands run the current operation-result observer over any normalized rollout with visible, source-bound dispatch/response pairs. This pass does not require a candidate-generating model. It uses the same finite criteria, Jev model, readable-context policy and raw-argmax rule across rollouts; those settings define a stable protocol ID. Frozen source and annotation hashes remain specific to each rollout. The operation pass does not generate semantic units, Plan stages or target identities.

```powershell
python -m rilldex outcomes run .tracker/operations/v1 --run-id RUN_ID --prompt-key --max-new-calls 300
python -m rilldex outcomes watch .tracker/operations/v1 --prompt-key --max-new-calls 300
python -m rilldex outcomes status .tracker/operations/v1
python -m rilldex outcomes audit .tracker/operations/v1
```

Use the existing source-output watcher in another terminal to import Harbor/SWE-agent files as they arrive. The outcomes watcher follows latest complete producer revisions and explicit imports, excluding still-growing or failed ingestion snapshots. An ingestion state of `complete` means the rollout record is complete, not that its task succeeded. `--all-latest` replaces the run selector for a batch. `--once` makes the observer watcher perform one scan. No watcher is automatically launched by opening the application.

The budget counts new decision requests over the command's lifetime, including across watcher scans; the built-in HTTP transport makes one POST attempt and never retries internally. Cached decisions do not consume this budget. Re-run the command after interruption or budget exhaustion; `--max-new-calls 0` performs cached-only execution. A process-owned lock prevents simultaneous workspace writers. Wire responses are retained before validation, and rejected packets never become published observations. Audit validates source identity and exact decision replay, not semantic accuracy. A changed protocol needs a new workspace; older records are preserved.

Each complete, audited rollout observation and its metrics are committed together. The command returns a direct link to **Rollout metrics**, whose evidence drawer shows outcomes, source dispatches, response excerpts, decision hashes and excluded actions. Failed fraction uses complete consistent terminal calls as its denominator; pending, unknown and calls with no eligible response are not silently counted as successes. Companion coverage and unknown metrics stay available. The same protocol ID can group rollouts over explicit `experiment`/`training_step` coordinates. Missing coordinates never become import-order trends. A new annotation version remains separate; multiple versions for one rollout are excluded from trend points until a consistent selection exists.

On the public Nebius `postlund__pyatv-978` trajectory, this workflow inspected eight responses from nine dispatches: seven completed operations and one rejected edit. The submission has no bound response and remains outside the outcome denominator. The later edit returns changed code, without establishing correctness or task recovery. Execution intentionally stopped after two requests, resumed for 22, and replayed with zero new calls. Artifacts are in `research/operation-workspace-2026-10-08`. This is another real-source execution check and assistant source review, not an independent accuracy benchmark. No real training coordinates are present in that source.

## Full semantic extraction

### Choose a frozen activity definition version

New extraction workspaces can select `--activity-routing work-organization-activity/1` during `semantic prepare --run-id RUN_ID`. This experimental version separates a proposed artifact layout or immediate setup announcement from an organized work plan. It preserves genuine staged plans and continuing strategies. The selection is frozen in the workspace and shared with the candidate worker; audit and map provenance carry it forward. Historical workspaces keep their original definition and cached decisions. Use a new directory to compare versions.

The current evidence is 16 matching development cases across software, browser and business examples, including two public source units. It is not independent accuracy or whole-rollout validation, and existing maps are not silently reannotated. [Exact cases, known legacy error, costs and replay](../research/plan-boundary-2026-10-11/README.md).

To apply a new definition to an existing complete extraction, use `semantic revise NEW_DIRECTORY --from-directory PARENT_DIRECTORY --run-id RUN_ID --activity-routing work-organization-activity/1 --prepare-only`, then `semantic revise NEW_DIRECTORY --prompt-key`. This freezes the old boundaries, reclassifies every unit from its original source context, and queues fresh content only where categories change. Unchanged categories retain their exact content decisions. After supplying pending content candidates, resume with `--plan-links` to rebuild action-to-stage correspondences within the remaining invocation budget. `--audit-only` checks the complete revision; register it with the existing `semantic register` command and explicit `--run-id`.

The first complete public source revision covers 68 units and corrects the scaffold Plan; all twelve report-stage links survive rebuilding. The old observer is preserved. Native mini-SWE-agent and ATIF software tests check source/actor/link preservation; these are not cross-framework semantic accuracy scores. [Whole-rollout evidence, command recipe and measured cost](../research/whole-revision-2026-10-11/README.md).

### Readable declared work after local extraction

The work-item pass operates on an existing complete semantic map. It keeps the same unit boundaries and activities, then selects readable work objects *inside* each agent prose contribution. An Orient can state an earlier achieved result and undertake another operation; these become separate attributed work items without turning the contribution into several activities. Missing candidates remain pending, and selecting an empty bundle is a distinct recorded judgment.

```powershell
python -m rilldex work-items prepare .tracker/work-items/my-pass --run-id RUN_ID --observer OBSERVER_ID
python -m rilldex work-items run .tracker/work-items/my-pass --prompt-key
python -m rilldex work-items history .tracker/work-items/my-pass --prompt-key
python -m rilldex work-items actions .tracker/work-items/my-pass --prompt-key
python -m rilldex work-items audit .tracker/work-items/my-pass
python -m rilldex work-items register .tracker/work-items/my-pass --label "Stated work and histories"
```

`prepare` freezes the exact parent map and queues file-based candidate requests. The response contract is in each request. Supply the candidate response files before `run`; no new generative service is configured or invoked. This pass records explicit undertaking, proposal, postponement, withdrawal, reported achievement and reported blockage, each attached to a natural-language work item and source evidence. Code or claims inside a drafted artifact remain distinct from the author's outer undertaking.

Only after every eligible prose unit has a selected bundle can `history` compare the items. Its version 2 asks bounded whole-work identity questions separately for each earlier record, using the selected local work meaning and citations. Conflicting or unresolved identity choices stay unresolved; they do not create novelty or merge records. This is a history of statements, not an active-goal state machine. The most recent `reports_finished` statement does not establish successful execution.

`actions` then compares each dispatch with earlier selected work records in the same actor/trajectory. It preserves the statement available at dispatch time and withholds later responses. Each bounded question selects attempts, prepares, checks, none or unresolved by raw argmax. Version 2 names both endpoints and the direction in each option, and retrieves past recorded dispatch context to clarify references such as “the required packages.” Exact decisions resume from cache; rejected responses remain in the wire archive. Registration optionally binds this complete pass and its source review without changing previously registered observers.

The same history focus now includes matched dispatches, their bound responses, and intervening activities. Plan-stage links are shown when those particular dispatches already have separately selected stage correspondences; no direct statement-to-stage identity is inferred transitively. Source outcome, claimed achievement and stage completion remain distinct. On the reused software trace, 382 pairs over all 33 dispatches selected 64 links; an earlier 91-link pass made backward dependencies and wrong package-instance matches and is preserved unpromoted. Eleven of twelve authored controls match. A runtime-installation versus code-writing scope failure remains, along with three reviewed output-to-implementation links. These observations are a development view, not validated deviation/completion measurements or independent accuracy. [Review](../research/declared-actions-2026-10-08/source-review.md).

Registration binds the exact local pass and optional history into an additive observer. It audits them before showing them in the existing map, preserves earlier observers and adds no separate destination. The inspector exposes each work item; a stated-work history focuses its original contribution units and intervening work in the card map. Changed registered results are rejected until a new audited observer is registered.

The design borrows the distinction between conditional offers and commitments from [DAMSL](https://www.cs.rochester.edu/research/speech/damsl/RevisedManual/node10.html), without adopting its overlapping dialogue-act tags as our unit activities. [LangChain's TodoListMiddleware](https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/agents/middleware/todo.py) writes agent-supplied task descriptions/statuses into state; those recorded declarations are useful inspection inputs, but the tool's state write does not independently verify task achievement. Our inference from these practices is to preserve attributed declarations separately from operations and result evidence.

The same staged extractor can now process any normalized imported run without a trajectory-specific research script. A workspace freezes its source and observer configuration. Completed, audited passes register in the existing Behavior map through the selected SQLite store; no Python catalog edit is required. The existing development observers remain available.

## File-based workflow

Import a supported source with `python -m rilldex import trajectory.json`. Use its returned run ID:

```powershell
python -m rilldex semantic prepare .tracker/semantic/my-pass --run-id RUN_ID
python -m rilldex semantic run .tracker/semantic/my-pass --prompt-key
python -m rilldex semantic status .tracker/semantic/my-pass
python -m rilldex semantic audit .tracker/semantic/my-pass
python -m rilldex semantic register .tracker/semantic/my-pass --label "My observer version"
```

`prepare` makes no model calls. It queues coherent-boundary proposals for prose/user regions and activity readings for recorded dispatches. It does not split prose by sentences or guess missing meanings. User contributions are included by default and retain their authorship; use `--agent-only` at initialization to exclude their annotation while preserving them as context. An explicit `--context-policy FILE` overrides the default readable context of complete governing instructions plus eight recent events, up to 4,000 characters per ordinary event. The existing context contract records omitted ranges and unobserved media. This is a supplied-context policy, not proof that the selected context is sufficient.

Each JSON in `candidates/requests` supplies the exact source, visible prefix, instructions, response contract and content-derived identity. A candidate provider writes the corresponding `candidates/responses/HASH.json`, including that request hash and its producer name/version. The next `run` selects boundaries, then one base activity, then readable category-specific content. Newly enabled dependent requests appear in the same queue. Rejected or unresolved choices remain review work; response-file presence is not a selected annotation.

Jev chooses the maximum-probability supplied option. No confidence gate is added. The key prompt is hidden, occurs only when a new call is needed, and retains the credential in process memory. Saved exact requests/decisions are reused on resumption. All eligible regions must finish before a complete result replaces the workspace's previous complete result.

Each invocation defaults to at most 50 new Jev requests, 50 candidate process calls and 1,000,000 combined request bytes. Use `--max-new-calls`, `--max-candidate-calls` and `--max-input-bytes` to set an allowance; all three zero means cache-only. A stop returns `budget_reached`, persists current partial coverage and preserves the completed map. Resume grants a fresh allowance. These are invocation/byte limits, not billed-token limits; older/custom transport retries and generator API calls require their own metering. See [budget receipts, token-report coverage and replay evidence](SEMANTIC_EXTRACTION_WORKFLOW.md#bounded-execution-and-honest-coverage).

## Optional generator process

A configured generator can handle the same queue without manual file handoff:

```powershell
python -m rilldex semantic run .tracker/semantic/my-pass --prompt-key --candidate-producer "generator-name/version" --candidate-command python my_generator.py
```

Place `--candidate-command` last. It receives a JSON envelope containing `request_hash` and `request` on stdin and returns a JSON candidate response on stdout. There is no shell command interpolation. The process may implement a user-configured generative endpoint; the application does not install or call an extra model by default. It does not receive `JEV_API_KEY`. The worker validates boundaries, citations and response structure before storing candidates. Producer attribution remains separate from source facts, Jev selections and independent reference labels. The current development environment has no real generative endpoint configured.

For usage accounting, the generator process can attach numeric `usage.input_tokens`, `usage.output_tokens` and `usage.total_tokens` from its actual API receipts. Do not obtain these values by asking the model to estimate its usage. The tracker records these reported counters and their reporting coverage; it does not independently verify provider billing. Failed or interrupted calls may have unknown consumption.

The process runner enforces the existing two-million-character stdout limit while
reading UTF-8, rather than after buffering the complete output. It separately
counts and discards stderr, stopping at two million bytes. Its default 120-second
deadline includes request delivery, both output pipes and process exit. OS process
creation itself may not be interruptible; termination cleanup has a separate
five-second allowance. Invalid UTF-8, excessive output, nonzero exit and timeout
remain failed attempts and never publish candidate responses. There is no retry
inside the runner.

On Windows a gated launcher joins a kill-on-close Job Object before starting the
configured command. Normal completion, timeout and output failure clean up its
descendants, including children whose immediate parent exited. POSIX uses a new
process group and kills that group on cleanup. Commands must not detach into a new
session or launch untracked remote jobs; this is not a sandbox. Abrupt termination
of the POSIX worker itself is not covered by process-group cleanup. Linux and
macOS execution of this increment remains unverified.

Each invocation records `receipts/attempts/<attempt-id>.json`; the existing
`receipts/<request-hash>.json` is the latest-attempt view. Retries retain earlier
failures, including a pre-existing legacy receipt. Records contain safe failure
categories, byte counts and timing, not raw stderr or command arguments. Observed
byte counts can exceed a limit by one read chunk; they are not token counts or
proof that a remote API cancelled work. Exact candidate cache hits still avoid
the process entirely. See the [process and retained-data audit](../research/2026-10-15-candidate-process.md).

### Citing the current contribution without copying its text

For a generator configured to return subject identifiers and exact source references, set `--candidate-citation-format source-references/1` before `--candidate-command`. The harness supplies the selected format, current request hash and configured producer; the generator can return just the candidate payload. A conflicting format is rejected. Omitting this option preserves the existing response contract. This avoids spending generator effort on transport metadata; it does not repair evidence strings or establish that generated meanings follow from their citations.

A generator can opt into the `source-references/1` response format. Use `{"subject": true}` when the **whole current source unit** supports the proposed reading or content field. The tracker resolves it to the request's exact original event, pointer, offsets and text. This avoids copying errors in equations and code; it does not certify the proposed meaning.

```json
{
  "citation_format": "source-references/1",
  "reading_protocol": "contribution-readings/2",
  "readings": [{
    "activity": "orient",
    "text": "Announces the immediate next step without performing it.",
    "evidence": [{"subject": true}]
  }]
}
```

This is a response shape, not a suggested label for every source. The configured command harness supplies `request_hash` and `producer`; a provider writing files directly must include both. Content bundles use the same evidence item inside `candidates[].fields.FIELD.evidence`, including Plan structure evidence. All existing required fields still apply.

For a narrower claim or earlier context, use an exact `{event_id, quote}` citation, with `source_start` to disambiguate repeated text. These can be mixed with the current-unit reference. The whole unit must be visible in the supplied context; a span containing omitted text or uninspected encoded media is rejected. A malformed quote is still rejected rather than repaired. Responses using this opt-in format do not change historical request hashes, Jev options, argmax selection or extraction order.

The [six-case development trial](../research/scoped-reading-trial-2026-10-12/README.md) retains one failed quote response and a fresh format variant. Its actual file-provider handoff is validated; general semantic accuracy and complete path recovery remain unmeasured.

## Audit and registration

### Continuous file handoffs

The semantic watcher records a fingerprint of candidate responses when a job
waits for proposals. A later worker poll resumes that job when a new or changed
JSON response is bound to its exact request hash. Write each response to a
temporary file and rename it atomically into `candidates/responses/`; partial
JSON and responses for another request remain pending. Stage validators still
check the complete content before selection. The automatic handoff does not
accept a response merely because it is parseable.

Unchanged rejected candidates are not sent again. Failures, interruptions and
exhausted budgets still require explicit retry, including when a newer source
prefix arrives. Older waiting jobs without a saved handoff fingerprint also
require an explicit retry. The public worker status exposes pending counts and
annotation coverage, not local candidate files. These counts measure annotation
readiness, not task progress, semantic accuracy or tool-result coverage.

Worker configurations retain their extractor fingerprint. Keep the original
runtime to finish an existing paid observation; initialize a new worker for a
changed extraction implementation. See the [long-trace semantic exercise](../research/longtrace-semantic-2026-10-15/README.md)
for the distinction between frozen real inference and installed-package tests
of this handoff change.

The workspace stores its frozen source, configuration, pending checkpoint, last complete extraction, stage decisions, candidate provenance, wire responses and execution receipts. A completed Jev response is saved before answer validation, so a model/shape mismatch remains inspectable. A process-owned lock prevents two writers; a leftover lock file does not prevent resumption after the process exits. Provider failures and interrupts leave saved decisions available for replay.

Registration replays the extraction and all present derived modules. Its identity binds the run, source, selected extraction and full derived map, including reviews. Changing any registered observation requires registering the new audited version. A stale registration is omitted from selectable maps and reported as unavailable; it never silently becomes a different observation. Existing research passes can also be registered with `--run-id`, and explicit `--action-target-version` / `--method-directory` when those extra observations are part of the intended pass.

Registration adds an observer choice, not another map screen. The resulting URL, inspector, focus controls and export use the same underlying unit identities. A complete local extraction does not automatically create unselected goal histories, semantic relations, strategy labels or training comparisons.

## Development evidence and limits

### Requested conditions in the continuous worker

Configure a **new** worker with `--requested-conditions` to preserve user requirements,
requested checks and attributed claims as separate source-backed clauses. It can be
combined with `--feedback-references` and `--live-prefixes`. The workspace option is
`"requested_profile": "requested-conditions/1"`; it pins `requested-work-records/2`
and requires user contributions. Existing observers keep their original configuration.

```sh
rilldex --db study.sqlite semantic watch-init observations --experiment training-run --label "Activities, feedback and requirements" --live-prefixes --feedback-references --requested-conditions
```

Initialization authorizes **zero** new calls. Set explicit lifetime limits with
`semantic watch-budget` before running a paid worker. The existing candidate-command
contract now also receives `stage: requested_work_candidates`. A proposer must support
its supplied response contract; a unit-only proposer is insufficient. Alternatively,
return request-bound files in each run workspace's `work_candidates/responses` queue.
Valid new or edited responses resume a waiting worker once. Partial files do not wake
it; unchanged rejected proposals do not repeatedly spend. Failed or budget-limited
jobs retain the existing explicit retry policy.

Base extraction, feedback selection and requested terms share the same durable budget,
decision cache and publication transaction. The observer is not published until its
configured layers pass replay audit. A pending conditions layer does not invalidate
the saved base extraction or consume calls to recreate it. Exact requested proposals
can be reused; a changed full extraction currently creates a new request identity for
this layer. This does not promise constant cost for growing prefixes.

In the existing Behavior map, open **Task requirements** above any map level and select a version
to inspect its clauses and source quotations. The same records are graph nodes of kind
`requested_work_version` and `requested_clause_version`, accessible through
`Workspace.table('nodes', kind='requested_clause_version')` and SQL without export.
Scope revisions, explicit clause retirements and original source units remain linked.
These are requested terms, not fulfillment, correctness, an active-goal inference or
a reward-hacking judgment. A later check must be tied to the actual requirement and
artifact version before it can support completion or recovery.

The [long-trace exercise](../research/longtrace-semantic-2026-10-15/README.md) documents
the motivation: two acceptance conditions were absent from the compact task summary.
The summary is not the authoritative requirements list.

On 8 October, the public SWE RL `apache__druid-15402_0` source already imported as `7755e31c48a23b251f6954c6` was passed through this new workflow. Its full run has 137 eligible regions: 69 prose/user regions and 68 recorded actions. No candidate generator was supplied, so all 137 first-stage requests remain pending, zero semantic selections are claimed, and zero Jev calls were made. This is a complete-source queue/resumption check, not a new annotated map or an independent transfer test. The source was previously inspected for adapter/macro development; it is not an untouched holdout. Its public release has no reliable per-trajectory checkpoint mapping, so sample filenames are not treated as training steps.

The command-process end-to-end tests use a clearly identified test generator and synthetic Jev responses. They verify dependency ordering, source/configuration preservation, failed-response retention, exact cache reuse, audit, registration and detection of changed review evidence. They do not measure semantic accuracy. A configured real generator, independently reviewed fresh traces and supported goal/Plan/result histories remain necessary for the broader product goal.

The real-source integration uses a separate SQLite database and registers the existing 101-unit software observation without catalog code changes. Its derived map remains identical, including the method comparisons and source reviews; API and native browser exports match the audited export digest. This check found and fixed a real clean-database failure: the bundled catalog caught the test store's `InputError`, but the actual store reports absent runs with `KeyError`. Reproduce with `python -m research.semantic_workspace_review`; evidence and screenshot are under `research/semantic-workspace-2026-10-08`. All 577 Python tests and seventeen map projection checks pass. The temporary review server is separate from the updated main application.
# Work results attached to the same units — 8 October 2026

## Optional local adjustment pass

After a complete work-item pass, reuse its readable items with a bounded additional observer:

```powershell
python -m rilldex work-items adjustments WORKSPACE --adjustment-directory ADJUSTMENTS --max-calls 50 --prompt-key
python -m rilldex work-items adjustments WORKSPACE --adjustment-directory ADJUSTMENTS --max-calls 0 --audit-only
```

Use a separate output directory. The first command saves each exact raw-maximum decision before proceeding. Exhausting `--max-calls` stops new transport requests and preserves completed decisions; rerunning resumes them. The budget counts new requests in that invocation, not token spend. `--audit-only` validates saved choices without inference. Changed source, items or harness require a new snapshot workspace. Prefix-local request identity remains stable when unrelated future events are appended, but this command does not yet provide streaming append ingestion.

The experimental graph composer subsequently joins these observations with audited work identity, action correspondences and outcomes. That step makes no inference calls. The bundled `software-local-adjustments` observer exposes the graph in the existing map; its optional monitors are disabled pending broader evaluation. [Known errors, token receipts and limitations](../research/local-adjustments-v2-2026-10-08/README.md) are part of the observer's review, not independent validation.

## Preserve declarations when adding correction content

### Distinguish a correction from use of corrected input

The experimental `--protocol effect` retains those same declarations and asks whether each work item makes a correction, uses a separate correction, or describes other content. It does not change base units or activities. A follow-up reference pass can retrieve earlier corrective-work candidates from saved work/action relationships and select their referents:

```powershell
python -m rilldex work-items adjustments WORKSPACE --adjustment-directory EFFECTS --protocol effect --max-calls 50 --prompt-key
python -m rilldex work-items adjustment-references WORKSPACE --adjustment-directory EFFECTS --reference-directory REFERENCES --max-calls 20 --prompt-key
python -m rilldex work-items adjustment-references WORKSPACE --adjustment-directory EFFECTS --reference-directory REFERENCES --max-calls 0 --audit-only
python -m rilldex work-items register-adjustments WORKSPACE --adjustment-directory EFFECTS --reference-directory REFERENCES --label "Corrections and return to work"
```

Use separate effect and reference directories. References require protocol 4. Registration audits saved evidence and adds an immutable observer without enabling a monitor or calling a model. Missing candidates, unresolved identities and budget-limited questions stay explicit; the selector does not force a nearest match. See [evidence, token receipts and retained errors](../research/adjustment-effects-2026-10-08/README.md).

Use `--protocol facet` with `work-items adjustments` to add a correction-content observation without reclassifying the selected work declaration. The output preserves `reports_finished`, `commits`, `proposes`, `defers`, `withdraws` or `reports_blocked`; completion claims cannot be turned into prospective changes by this additional facet. The previous protocol remains replayable and is the compatibility default.

```powershell
python -m rilldex work-items adjustments WORKSPACE --adjustment-directory FACETS --protocol facet --max-calls 50 --prompt-key
python -m rilldex work-items adjustments WORKSPACE --adjustment-directory FACETS --protocol facet --max-calls 0 --audit-only
python -m rilldex work-items register-adjustments WORKSPACE --adjustment-directory FACETS --label "Work declarations and correction content"
```

Graph registration requires the frozen parent to include operation outcomes, plus completed work history and action correspondences in the work-item workspace. It audits every dependency without new inference, retains the saved work-history/action links and their review notes, binds the exact combined observation, and returns a URL in the existing Behavior map. Changed source, observations or notes require a new registration. This pass remains experimental: [development results and known scope errors](../research/adjustment-facets-2026-10-08/README.md).

## Response-time results

`python -m rilldex work-items results WORKSPACE --prompt-key` adds result evidence after the local declarations, work histories and action correspondences have passed exact replay. It inspects only selected attempts, using each earlier natural-language scope, dispatch and bound responses through that response's cutoff. Preparations and checks are not automatically attempts at the broader goal.

`work-result-evidence/3` selects a result (fulfilled, partial, failed, pending or not established) and, separately, whether the named scope has a reported unmet condition. Running a test and making its tests pass are different scopes. Partial component support does not itself mean the remaining component failed. Jev uses raw argmax; there are no confidence gates. Version 1 and 2 requests remain replayable.

The optional `work-result-review.json` pins review notes to the exact observation hash and result IDs. Registration binds both artifacts. Notes remain separate from raw selections, appear on cards and in the evidence inspector, and do not serve as independent labels.

The Behavior map now links response cards back to their stated work or Plan stage. Focusing one work scope displays its result on the existing response card. Plan cards show their latest response-time reading; stage-change lines expose the preceding stage's result available **before that entry**. Results are not persistent current-goal state or accepted task completion. No completion, deviation or recovery rate is enabled by this extension.

The public DevAI development trace has 39 selected scope/response observations across 23 scopes: 33 declared-work observations and 6 Plan-stage observations. Four rows retain source-review flags: two echo-only scaffold judgments, one uninspected-image judgment, and one check-versus-purpose scope ambiguity. The older observer's exported payload remains byte-equivalent under canonical serialization. See `research/work-results-2026-10-08/software-review.json` and the retained raw decisions in `research/work-items-complete-2026-10-08/software`.
