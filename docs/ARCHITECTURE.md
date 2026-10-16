# Behavior observation architecture

## Structured plan declarations — 11 October 2026

`declared_plans` is a source-only registered operator over native task-list arguments, covering documented LangChain and OpenHands profiles through the canonical event layer. Version 2 supports schema-declared native task IDs and an initial-reported-completion measure; ID-less profiles retain exact-text matching. It persists declaration/item nodes and status relationships, then reuses the monitor engine and evidence map. The native `nebius-openhands` adapter preserves structured chat messages, tool schemas and call/result links before these operators run. Neither layer adds semantic units or treats reported completion as verified work. [Capture, metrics and validity boundary](DECLARED_PLANS.md).

## Source-bound unit correction — 11 October 2026

`unit_reviews` reuses source windows, semantic content/Plan contracts, named work binding and relationship review. It forks immutable observation graphs, previews dependencies invalidated by unit replacement and composes the reviewed observer in units → work → relationships order. Saved measurement receipts expose their original observation input, including recovery's separate semantic graph. The existing map hosts editing and continuation of the same graph/analysis monitor. Unknown legacy dependency scope clears observation coverage conservatively. [Contract](UNIT_REVIEWS.md) · [Evidence and limits](../research/unit-correction-2026-10-11/README.md).

## Architecture direction — 11 October 2026

The [RL engineering framework](RL_ENGINEERING_FRAMEWORK.md) separates existing implementation from the next contracts. Extend the current source/graph store with joinable training provenance; extend the existing typed investigation engine with declared capabilities, eligibility, evidence and validation; retain versioned metric definitions with explicit populations and denominators. Trainer adapters, environment adapters and observation operations are independent extension points. Source scanners and graph-derived measures share the same result contract. No replacement graph service or second analysis engine is required.

Following the [11 October direction audit](../research/universal-rl-review-2026-10-11/README.md), all 18 deterministic analysis operations now use shared execution/dependency descriptors. The generic engine validates parameters and source bindings, executes registered callbacks, and preserves existing cache and receipt identities. Monitor plans expand declared dependencies. [Operator responsibilities and limits](ANALYSIS_OPERATORS.md). An initial [saved training context](TRAINING_INVESTIGATIONS.md) now carries the same population, chart evidence and case selection through rollout inspection and immutable hypothesis revisions. An initial [population comparison](POPULATION_COMPARISONS.md) joins existing monitor receipts to those frozen samples, using shared statistical reducers and explicit coverage/group context. Cross-checkpoint matching and the full recovery correction workflow remain to be connected. The four-kind training ledger still needs compatible lifecycle extensions for episode attempts, generation segments, learning groups and resumed training/checkpoint lineage. Automatic semantic scheduling remains separate; immutable existing sources and results stay authoritative.

Behavior remains source → coherent unit → base activity → readable content → supported relations → work episodes → measurements. Training provenance and analysis dependencies have different meanings from behavior relationships even when stored in the same system. The overview, investigation and rollout map are connected views of that evidence. An initial lifecycle ledger is now implemented as described below; generic operation declarations and the remaining lifecycle contracts still require work. Dated implementation notes remain a historical record.

### Initial reusable feedback operation — 11 October

`agent-contribution-feedback/1` is an opt-in scope on the existing feedback selector, with frozen history configuration and no-call preflight. `feedback-reference-opportunities/2` projects source-bound responses and existing reference edges into positive/negative/unknown opportunities in the recipient's recorded context. It shares necessary relationship evidence checks with maps, graph queries, timing and work paths. It is registered in the existing typed plan registry and monitor catalog. New observer graphs retain candidate and inspection coverage; older graph identities remain unchanged. No new analysis service or activity taxonomy is introduced. See [contract and validation limits](FEEDBACK_REFERENCE.md).

### Recovery composition — 11 October

`work_state → recovery_windows` runs in the existing typed plan registry. The new operation freezes explicit window/censoring semantics independently of historical `work-state/6` outputs. Its evidence graph unions the selected source/semantic graph with state facts, adds recorded recheck relationships, and preserves existing activity cards. The monitor receipt validates both dependency outputs and source/graph versions. Investigation cohort pooling and saving use this same definition. [Recovery contract](RECOVERY_WINDOWS.md) · [Execution audit](../research/recovery-windows-2026-10-11/README.md).

### Initial training ledger — 11 October


`training_lineage` persists immutable producer records with explicit sample references and score/selection revisions. `Outbox.log_training` uses the existing durable queue, with separate HTTP routing and exact packet acknowledgments. Source documents are not rewritten. The population projection pins source revisions, separates stage availability from observed counts, and joins saved monitor values with measured coverage. A separate live-stream revision refreshes the new overview tab when late facts arrive. `GRPOTrainingLineageMixin` is a narrowly gated TRL 1.13.0 CPU adapter preserving sample identities through native shuffle/reuse; it records native backward completion and mask evidence, not optimizer effects. [Contract](TRAINING_LINEAGE.md) · [Native and transport evidence](../research/training-lineage-2026-10-11/README.md).

## Configurable history monitoring — 9 October

### Named-filter projection — 11 October

`training_selection` projects latest ledger decisions and existing monitor values, preserving one weight per declared sample and separate conflict/unknown/absent states. It adds no storage or inference service. Filter identity includes record producer, name and definition; content-derived comparison IDs bind decision revisions and monitor value IDs. Cohort-local group contrasts exclude incompatible recorded context and retain no-overlap/missing-observation counts. The existing event stream refreshes late joins/materialization. [Contract](TRAINING_SELECTION.md).

`analysis_metrics` now accepts a `history_query` selector with an explicit validated query. The complete definition and extraction/linking/graph versions are pinned in the immutable monitor. Execution reuses the typed investigation DAG; source-only queries require the source observer. The metric reducer reconciles each true/false/unknown action case with the recorded numerator, denominator and opportunity count. Receipt verification binds query, source, plan, output and graph identities without reinterpreting historical observations.

The existing `monitoring.Service` materializes current and future imported rollouts. The editor configures the query; the same chart/case/receipt workflow reaches `appendHistoryEvidence` in the full rollout map. Query selection coverage is exposed separately from unknown opportunity counts. Zero selected dispatches has no rate and reuses the source graph (`history-evidence-graph/2`), avoiding graph copies for unrelated rollouts. Chart placement still requires logged experiment/step metadata. [Live audit and validation](../research/history-monitor-2026-10-09/README.md).

## Structured history queries — 9 October

`history_evidence.py` provides an explicit native-argument → prior lookup → returned-record → attribute query. Configuration pins tool names, JSON-pointer scope/identity bindings, equality checks, quantifier and invalidating calls. Latest pending/failed/unknown-scope lookups cannot fall back to old facts; missing, ambiguous and unavailable evidence remain unknown. It emits per-rollout opportunities, numerator, decidable denominator and exact source witnesses. It makes no natural-language applicability or successful-effect claim.

`investigation_plans` executes and caches this operation using query, source hash and capability-linking version. Graph materialization replays the result before storing query/observation/fact nodes and their relationship edges. `history_query` exposes the same path as a batch CLI. The map excludes evidence objects from activity layout and resolves them from the selected action or its grounded unit into one inspector. Source chronology and all original cards remain intact.

The public audit reconciles four query cases, persisted graphs, cache hits and source values. It exposes a real duplicate-item grain limitation and missing native arguments in the software export. This is configured evidence retrieval, not an automatically interpreted requirement or a live monitor. The next integration should reuse persistent monitor definitions and receipts, without interpreting zero opportunities as a negative behavior rate. [Contract, sources, tests and limitations](../research/history-evidence-2026-10-09/README.md).

## Compact packets and reusable observer execution — 9 October

`packet_interning` losslessly shares identical tool contracts across prefix events, validating content-addressed references on expansion. `condition-grounding/4` uses this representation for evidence packets while reusing unchanged prior-stage requests; source events and readable ranges are retained. `condition_observer` exposes frozen source/document/protocol/selection bindings, cache-only defaults, explicit pending work and complete-result raw replay. `metered_jev.BoundedTransport` supplies cumulative pre-recorded HTTP-attempt budgets and no hidden retry loop; research trials reuse it. The observer remains experimental and separate from direct monitoring because artifact-versus-runtime requirements can be ambiguous and independent accuracy is unmeasured. [Contract, transfer cases and runnable command](../research/condition-compaction-2026-10-09/README.md).

## Experimental grounded conditions — 9 October

`condition_grounding` consumes validated historical request snapshots and existing immediate action contents. Operation type and governed instance gate independent positive support/contradiction witness selections; exact source ranges and raw-argmax request identities are retained. Version 3 reuses unchanged version-2 operation/subject requests while correcting its evidence polarity contract. Unknown scope, missing proof, several-record requirements, context limits and partial pair coverage remain distinct. The observer is not materialized into live graphs or direct metrics: development evidence still includes a context-limited public case and lacks independent accuracy validation. `research.condition_grounding_trial` provides immutable case manifests, resumable exact caches and cumulative pre-recorded HTTP budgets; `research.condition_grounding_audit` replays and reconciles all trials without inference. [Evidence and remaining work](../research/condition-grounding-2026-10-09/README.md).

## Typed condition objects — implemented 9 October

`requested_graph` materializes validated requested histories and shared clause versions. Ordered membership, source attribution, content revisions and explicit retirements are persistent edges. `graph_store.build` includes them automatically for complete requested-work inputs and binds the existing historical dispatch projection; source-only or incomplete inputs retain their missing coverage. The request-change observer reuses this materializer while attaching only its own replayed semantic comparisons. `request_changes.changes` now reconstructs every edit, including clause version and retirement contents, before accepting the chain. The map's condition inspector reads the persisted membership and original source links. Clauses never enter activity layout or chronological transitions. [Contract, public replay and limits](../research/request-conditions-2026-10-09/README.md).

## Historical request context at dispatch — implemented 9 October

`request_dispatch.build` validates the source-bound request chain and reconciles each existing correspondence row with the latest prior state in the action's trajectory. Its materializer adds shared `requested_state` nodes, action-to-context edges, state-to-version membership and exact version endpoints for inherited positive work roles. Availability and semantic correspondence remain separate. The existing action inspector reads those persisted edges, displays the historical record order and links to request-version/source inspection. Neither state objects nor requested versions participate in activity-card layout or temporal transitions. [Data contract, replay audit and limits](../research/request-dispatch-2026-10-09/README.md).

## Requested terms and version history — implemented 9 October

`request_changes` consumes complete requested-work records, validates their per-trajectory source/state/version chain, and compares only historical revisions through support → undertaking → terms selections. Jev raw argmax is preserved and dependent questions stop on unresolved or unsupported premises. Graph export replays decisions, retains all source units, and adds typed historical requested-object nodes with explicit source and previous-version edges. The existing rollout map projects these objects into a request history, separate from unit chronology. It opens before/after contents, exact source units and saved judgments. The layer is experimental: a known public false rejection is retained, no goal-drift assertion or production metric is derived, and independent accuracy remains unmeasured. [Contract and reproducible evidence](../research/request-changes-v2-2026-10-09/README.md).

## Adaptation patterns — implemented 9 October

`adaptation_patterns.project(graph)` composes exact-pair dispatch-scoped method observations with correction/preparation relationships. It leaves the source graph and base activities unchanged. The typed `adaptation_patterns` and `compare_adaptation` operations cache against exact source/graph identity and a version that includes the work-episode dependency. Each recurrence occupies one procedure × correction-location cell, with raw request IDs and source episode witnesses retained. Comparison outputs distinguish pooled counts from equally weighted within-rollout shares; unknowns remain explicit. Three monitor definitions reuse the same projection and evidence receipts. Earlier method protocols are excluded because their treatment of changed referenced inputs differs. [Data contract, source audit and limits](../research/adaptation-patterns-2026-10-09/README.md).

## Work-level navigation — implemented 9 October

`work_navigation.project(graph)` builds a complete action route over the existing `work_episodes` projection. The typed `work_navigation` plan operation persists a source/graph/version-bound result. Visits retain every native action and its selected units; only positively linked consecutive same-work occurrences with unchanged expressed scopes and plan stages can share a visit. Return and correction links retain their original episode and graph-edge IDs. UI compression therefore cannot generate new semantic relations or replace unknowns with novelty. The existing rollout page switches between this work overview and the full unit map, sharing source drilldown and scope context. [Evidence, invariants and limits](../research/work-navigation-2026-10-09/README.md).

## Domain phase projections — implemented 8 October

`repair_phases.py` supplies a separate, experimental action/history baseline for explicit `metadata.task_family=software_repair` imports. It does not alter semantic units or their activity tags. `repair_phases` and `compare_repair_phases` are typed cached investigation-plan operations, bound to exact source graph/hash and rule version. Each classified or unknown action keeps its original event/pointer, rule and prior patch-attempt reference. Concurrent actions and unsupported commands remain gaps; paths never join across trajectories. The existing investigation UI displays equal-weight rollout shares and complete phase blocks with source drilldown. Neither phases nor phase adjacency imply correctness, actual changes, successful tests or completion. See the [release comparison and scope](../research/task-phases-2026-10-08/README.md).

## Expressed work scopes in the graph — implemented 8 October

Saved `expressed-work-context/1` observations previously survived only in their
semantic exports and legacy views. `work_scopes.materialize` now persists selected
requests and organized Plans as `work_scope` nodes, exact origins as `scope_source`
edges, and selected unit membership as `in_work_scope` edges. Selection status,
decision identities, source/cutoff and unresolved memberships remain in the graph
snapshot. Future, cross-trajectory, invisible, source-mismatched and inconsistent
memberships are rejected. Partial membership is not promoted to a selected edge.

These nodes provide a higher-level navigation layer above the unchanged unit
canvas. They do not become artificial units or insert extra source-order steps.
The Requests & plans sequence combines only consecutive equal membership sets,
keeps unresolved/no-work records distinct, and separates trajectories. Shared
membership displays together and contributes once to this sequence. Its arrows
mean source order, not causality, active-goal change, authorization or completion.
Clicking a scope opens the actual request/plan and the exact contributing cards;
unit inspectors link back to the same scope nodes. Older graphs remain immutable.

The implementation reuses saved predictions without model calls. Three public
development traces retain 3/4/5 selected scopes and 68/24/17 assigned contributions
respectively (software/airline/retail). Two conversational traces also contain one
no-work contribution each. The 944-test Python suite, eight layout checks and a
live three-trace browser workflow pass. Independent membership accuracy and
task-phase/strategy inference remain unestablished.

## Continuous analysis materialization — implemented 8 October

`analysis_metrics` defines version-pinned measures over the existing `work_episodes` and `work_state` plan operations. Monitor definitions retain the measure specification and extraction version. The background service keys values by source, graph, lifecycle and pinned version, reuses the analysis-node cache, and publishes immutable measurement receipts. Several measures can share one extraction. No model work is scheduled by these definitions.

An analysis receipt resolves the original graph, source, plan and output; checks their hashes and version bindings; and reconciles values with the complete case set. Whole-rollout evidence selection highlights the contributing nodes and edges. Work-state graph nodes are not counted as semantic annotation coverage. A retired extraction version can still explain its stored values but cannot classify a new input without a newly versioned monitor definition.

The live snapshot endpoint checks service generation before and after reading values. A read overlapping materialization carries `snapshot_stale`, causing the client to fetch again even if its observed service revision already matches. This prevents acknowledging a new service revision with an older data read.

## Work-episode projection — implemented 8 October

`work_episodes.project` derives prefix-grounded recurrence episodes from an immutable semantic graph. Snapshots retain target-identity review coverage and independent method observations. The projection validates source spans, reference order and trajectory, preserves ambiguous/missing action positions, and prevents future disputes from altering prior episodes. Same-target chains establish correspondence, not strategy identity. Method judgments are exact-pair observations. Unresolved identity or method information does not become novelty, exploration or failure.

`adjustment_before_retry` connects a declaration to the earlier attempt; `retry_unit_id` identifies the later action and `via_action` identifies the attempted adjustment. That attempt may occur in the retry itself or before it. Consumers must not invert these roles or infer successful effects from the relationship.

`work_episodes` and `compare_episodes` extend the existing typed investigation DAG. Charts, selectable recurrence metrics and card/relationship drilldowns reuse cached outputs. Source, protocol, graph and extraction version participate in cache identity. Historical investigations remain frozen. Missing review coverage stays unavailable; positive counts describe recorded witnesses, not validated prevalence. This layer makes no model calls or training interventions.

The main research question is: **What changed in the model's way of working, and what evidence supports that observation?** Macro behavior is the entry point; detailed tags and relationships support explanations underneath it.

## Adopted extension order — 8 October

The [integrated implementation decision](../research/strategy-profiles-2026-10-08/README.md#integrated-implementation-decision) controls the next architecture work. These are planned extensions, not claims about the current schema:

1. Extend the evidence/work graph with domain object versions and separate requested operations, execution evidence and observed effects. Complete one failure → relevant edit → recheck → delivery investigation. Bind check results to the recorded artifact/environment scope; unknown bindings remain unknown. Preserve immutable historical graphs and the coherent semantic-unit contract.
2. Compose the working investigation into a typed analysis dependency graph over the existing storage, jobs and exact-request cache. Source/observer versions, context selection, prefix cutoff, code/rubric and input hashes are part of node identity. Expose partial status and evidence through the existing Investigation workspace.
3. Add exploratory discovery with review and detector promotion; then evaluate prefix-only feedback. A learned task-family behavioral model is a later derived representation, separate from historical evidence and from the analysis execution graph.

The common domain interface is object → version → operation → result, connected to work targets and evidence. Harbor/SWE-agent coding data is the first adapter, not the core ontology. Phase flows and opportunity metrics are views and computations over these records. They must retain unknown coverage, exact episode membership and per-rollout contributions. No additional top-level map products are required.

The legacy verification records in `evidence.py` still mark artifact versions as unrecorded. The additive `work_state.py` projection now supports validated producer captures and complete numbered file views; `investigation_plans.py` persists its typed state graph and a bounded cached analysis DAG. `behavior_sequences.py` supplies gap-preserving activity projections. These do not establish a general semantic task-purpose observer or independent accuracy. The implemented scope and capture contract are documented in the [implementation receipt](../research/strategy-profiles-2026-10-08/README.md#implemented-process-investigation-foundation).

## Evidence and observations

`adapters.py` converts source-specific data into typed events with source pointers. `watch.py` collects stable producer-file snapshots and explicit continuation/retry relationships. `context.py` projects source configuration and outcomes without adding them to prefix-only Jev packets. `store.py` preserves source documents and normalized events in immutable run snapshots. `observe.py` derives conservative features and groups actions for presentation; `sequence.py` preserves eligible adjacent-action relationships and `evidence.py` preserves check/output/resource scopes. `jev.py` supplies contextual semantic judgments. `jobs.py` runs those requests outside ingestion. `compare.py` computes matched-cohort comparisons; `comparison_evidence.py` resolves a displayed change to its contributing tasks, rollouts and actions. `web/` presents maps, sequences and evidence.

The legacy action map has four views. Work targets reveal where the agent directs operations and revisits earlier work. Behavior flow reveals transitions between information seeking, execution, checking, coordination, reporting, and unresolved purpose. Task relation maps the selected fine relationship to a coarser label; probability sums never override the selected option. Goal focus links actions to recorded objectives and literal expressed plan blocks. These are complementary views of the same evidence. None is a causal graph or a representation of hidden reasoning. The separate semantic activity foundation covers model-authored text and dispatches; its validation status and priority are controlled by GOAL.md and DIRECTION.md.

Macro observations are not exclusively aggregates of sentence labels. Jev sees a bounded packet containing the relevant objective, current action, model expression and previous attempts. Each question has a separate rubric. The application combines typed answers; one answer in a shared request is not treated as hidden input to another.

The experimental `expression_scope.py` module illustrates a separate measurement request over the same source evidence. Candidate scopes are exact subdivisions of one complete model-text unit, each with its own supplied-choice form question. A scope is not a new event: all scopes inherit the parent's cutoff, and parent-unit counts must not be replaced with scope counts. Missing candidate coverage and unresolved/mixed content remain explicit. This module is not yet connected to live activity metrics; its expression definitions and candidate boundaries remain under validation. No experimental observation silently overwrites an activity record or changes the selected argmax option.

## Contracts from existing systems

| Source inspected | Implementation consequence |
| --- | --- |
| [Harbor ATIF RFC](https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md) and [trajectory models](https://github.com/harbor-framework/harbor/tree/main/src/harbor/models/trajectories) | Link tool observations by `source_call_id`; preserve copied context, media references, per-document subagent identity and source metrics. Do not conflate session identity with a unique trajectory document. |
| [SWE-agent agent implementation](https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/agent/agents.py) | Import explicit action/observation trajectories; preserve history separately as source evidence. A submission is an agent lifecycle event, not proof of task success. |
| [verl rollout tracing implementation](https://github.com/verl-project/verl/blob/main/verl/utils/rollout_trace.py) | Preserve sample, rollout and policy provenance; distinguish inspection sample coverage from the full training population. Avoid synchronous semantic inspection in the training loop. A direct verl adapter is deferred behind Harbor/SWE-agent. |
| [TypeSafe primitives](https://docs.typesafe.ai/primitives), [state](https://docs.typesafe.ai/concepts/state), [models](https://docs.typesafe.ai/models) and [confidence](https://docs.typesafe.ai/confidence) | Batch independent questions against shared text state, pin the returned model version, retain full distributions, separate uncertain outputs from negatives, and retrieve evidence outside the model. |

These sources were inspected on 6 October 2026. The implementation uses their published interfaces and design constraints; it does not incorporate their implementation code. Adapter contract fixtures are not a substitute for testing a pinned producer release.

### Pinned producer contracts

The inspected source copies, URLs and SHA-256 hashes are in `research/producers/sources.json`; Harbor fixture source and license are in `tests/fixtures/harbor/`. The watcher is based on these explicit contracts:

| Pinned source | Observation and implementation consequence |
| --- | --- |
| [Harbor trial paths](https://github.com/harbor-framework/harbor/blob/c803185a8b7c88c163abe48a22e9cea0bbd95e90/src/harbor/models/trial/paths.py) and [trial results](https://github.com/harbor-framework/harbor/blob/c803185a8b7c88c163abe48a22e9cea0bbd95e90/src/harbor/models/trial/result.py) | The actual result path is `result.json`; a layout docstring says `results.json`. Follow executable path definitions. `finished_at` indicates recorded terminal lifecycle; exceptions and arbitrary numeric verifier rewards are distinct from task success. Multi-step results need association with the named step. |
| [Harbor task configuration](https://github.com/harbor-framework/harbor/blob/c803185a8b7c88c163abe48a22e9cea0bbd95e90/src/harbor/models/task/config.py) and [trajectory metrics](https://github.com/harbor-framework/harbor/blob/c803185a8b7c88c163abe48a22e9cea0bbd95e90/src/harbor/models/trajectories/metrics.py) | Preserve selected declared timeout/environment/verifier constraints. Task checksums do not establish full environment identity. Cached tokens are included in input totals. Reports from different document/trial scopes must not be summed. |
| [SWE-agent lifecycle and retry implementation](https://github.com/SWE-agent/SWE-agent/blob/3ea751c087f32b16e039a2233dd6eefecef325d5/sweagent/agent/agents.py) | `.traj` is written during execution. A nonempty `info.exit_status` records termination, not verified success. Retry wrappers copy a chosen attempt into their root; the watcher imports each actual/embedded attempt once instead of recounting the selected copy. |
| [SWE-agent trajectory types](https://github.com/SWE-agent/SWE-agent/blob/3ea751c087f32b16e039a2233dd6eefecef325d5/sweagent/types.py) and [model statistics](https://github.com/SWE-agent/SWE-agent/blob/3ea751c087f32b16e039a2233dd6eefecef325d5/sweagent/agent/models.py) | Preserve explicit step execution duration and recorded state; absent duration is unknown. Retain scoped tokens/cost/API-call counts. Demonstration history does not become the actual task instruction. Replay configuration is projected through recognized fields. |

Configuration projections omit unrestricted environment variables and credential fields. Their original file hash and projected content hash are distinct. They are evidence sources, not commands to execute. Local references are bounded to explicitly selected roots, and changing/partial files are retried. A read-set stat check reduces torn collections but does not claim a transaction across producer files; a producer-supplied manifest would be needed for that guarantee.

## Storage and versioning

SQLite in WAL mode stores immutable snapshots, semantic observation records, observer jobs, review history and producer revisions. Import IDs include source content, metadata and adapter version. Identical imports are idempotent. Metadata correction creates a new snapshot instead of silently rewriting evidence.

Revision ingestion requires explicit producer/rollout IDs and consecutive revision numbers. Registration and source insertion are atomic. Duplicate identical requests are retries; conflicting content or skipped revisions are rejected. Logical identity is included in snapshot metadata so separate attempts with identical content remain separate rollouts. Lists select the latest revision; comparisons reject incomplete snapshots. Old revisions are addressable and never rewritten. Semantic results can transfer only when the current model, harness, selection policy and complete request hash match; reviews are not silently transferred.

Observation records preserve model, rubric version, packet hash, returned distributions, selection policy, source cutoffs, evidence truncation, token usage and request duration. Current selection is argmax/1 without a confidence or probability cutoff. Historical threshold provenance remains in old records; exact saved distributions may be reselected offline with both old and new provenance preserved. Evidence completeness gates are recorded separately from the winning choice. A material rubric or adapter change requires a new version. Recomputing a materialized analysis does not alter source evidence.

Jobs pin the model, harness and selection policy at submission; activity jobs also pin boundary-algorithm version. Queue capacity, duplicate detection and claims are serialized with SQLite write transactions. A worker renews a 60-second lease during inference. Result insertion and progress updates check ownership and lease validity in the same transaction, so an expired/stopped worker cannot commit a late response. Fresh workers leave existing live owners alone. Expired jobs become interrupted and require resubmission; saved exact-request results are reused. Already-authorized queued jobs with matching profiles survive restarts. This does not guarantee exactly-once remote inference across a crash.

`goals.py` constructs candidate IDs outside Jev and bounds eligibility by the action's source position. Candidate extraction and each request's candidate-set hash are versioned. Candidate existence, observable pursuit, and attainment are separate. Unknown focus intervals break temporal edges; observing the same focus after a gap does not prove a return. Goal selection remains independent from the action's purpose and task relation.

`reviews.py` overlays retrospective annotations while preserving original model distributions. SQLite appends a review record and uses an expected revision to reject stale edits. A clear event removes the overlay without deleting history. Review records carry evidence IDs and reviewer labels but no fabricated confidence. Grouped queues prioritize repeated unresolved observations and missing evidence links; they are not a diagnostic taxonomy.

Independent activity-reference evaluation is separate from those retrospective overlays. `activity_reference.py` derives per-case inspection findings from frozen predictions and eligible reviews, with quality votes, adjudications and unresolved references retained. The optional HTML report embeds the same JSON result and supports local source navigation; it makes no model calls and changes no stored observations. Selected options remain separate from scored availability, case-level concerns may overlap, and observer profiles cannot silently pool their metrics. The report intentionally exposes predictions, unlike the separate blind `review.html`.

`activity_context.py` separately audits source-span coverage for supported exact activity packets. It shares the reference workflow's visible-prefix construction, validates packet/source bindings and observation cutoffs, unions overlapping code-point ranges and reports partial or omitted normalized text. Live analysis supplies only current saved packets; frozen reference reports identify their packet basis explicitly. Unsupported packets are unavailable rather than reconstructed as if sent. Coverage is descriptive, does not establish relevance or sufficiency, and never mutates requests, selected options, scored availability or stored observations. Raw-source extraction, media and serialized tool-contract completeness require separate audits.

The live H1 result still comes from one multi-question request. Experiments in `activity_verification.py` and `research/activity_verification_probe.py` retain broad, question-scoped and independent Verify candidates without promoting them. `activity_components.py` now imports their source-bound frozen journals into append-only `activity_component_collections` and `activity_component_records` tables. Each record owns its question fields, original request, selected options, evidence status, model, selection rule and usage. Validation precedes the write transaction; differing replacement content is rejected. Production `get`/H1 observations do not read or merge these components.

The read-only `/components` view uses catalog, comparison and individual-record API endpoints. Comparisons join on both run ID and source-unit ID, distinguish identical-request repeats/reuse from changed requests, exclude changed option definitions from comparable-choice counts, and preserve “not requested” separately from negative observations. Evidence inspection returns the validated source prefix and exact saved packet. A registered packet-layout audit permits explicit experimental harness versions without relabeling a saved request as a production harness. The first importer supports current eligible source segmentation and registered development formats only. Provider identity/reuse declarations are not authenticated. Isolation prevents replacing unrelated saved fields, not semantic errors, and independent calls can add context cost.

## Scope of the initial harnesses

| Observation | Current measurement | Remaining validation |
| --- | --- | --- |
| Work strategy | Tool/command purpose and contextual Jev purpose; contiguous episodes and transitions | Human-reviewed boundaries; multi-purpose actions and task-conditioned strategy tests |
| Objective pursuit | Recorded instructions, literal plan registry, contextual action/task relation and goal selection; observed switches/returns | Semantic paraphrase identity, authorized amendments, hierarchical goals and completion states |
| Feedback response | Exact recurrence and Jev comparison of adjacent attempts | Longer-range recovery, action opportunities, state-sensitive repetition and reviewer agreement |
| Plan correspondence | Local expressed step versus current action | Multi-step commitments, deferred work and whole-plan coverage |
| Verification | Check attempts and result links; narrowly parsed pytest summary spans as reported output; structured completion claims and subsequent application-purpose actions | Claim-to-check support, artifact versions and task-wide verification coverage |
| Progress and stopping | Separate numeric rewards, dataset task outcome, terminal lifecycle, scoped producer usage and recorded-duration coverage | Environment milestones, resources between milestones and environment-grounded stopping semantics |

## Comparison policy

Comparisons intersect stable task IDs across selected checkpoints and average rollout rates within a task before giving each task equal weight. They refuse incompatible experiments, environment versions, splits, inspector configurations or explicit sampling settings. Unknown observations remain in denominators. Missing checkpoint identity does not become a synthetic training axis. Selective retrospective annotations cannot become a trend without a matched annotation protocol.

Paired task-cluster bootstrap intervals use 2,000 deterministic draws and a five-task display minimum. Within-task rollout variability and inspector uncertainty are not covered. Feedback-response contrasts use the subset of paired tasks with recorded opportunities on both sides. The first action and parallel actions issued before any prior result do not create response opportunities. Intervals are pointwise and do not drive automatic significance alerts.

The temporal macro layer uses a fixed six-by-six purpose transition map, not a growing vocabulary of fine tags. A single rollout retains exact adjacent event pairs. Pairs touching a multi-action parent expression are excluded, including its entry/exit boundaries, because choosing an arbitrary first/last action would create an unsupported temporal edge. Excluded pairs are not skipped over, and unresolved purposes remain explicit nodes. Edges describe recorded order, not causation, execution chronology or responses to feedback.

Transition counts are divided by each rollout's eligible pair count. Eligible rollout rates are averaged within each task. A paired contrast then averages task differences over tasks with sequence opportunities at both checkpoints. This is a share of all eligible pairs, not a row-normalized Markov transition probability. The same paired-task bootstrap supplies pointwise intervals. No-opportunity rollouts/tasks remain visible in coverage rather than becoming zero-valued observations.

The evidence endpoint recomputes the cohort identity, verifies that the chosen task/rollout belongs to it, and reconciles metric numerators against exact action matches. It exposes all task contributions and a complete rollout selector; action previews are the first 12 matches in recorded order and are not claimed to be representative. Individual rollouts are not treated as seed-paired. A stale cohort, changed observations or inconsistent materialized counts prevents the drill-down from being presented as evidence for the old aggregate.

Run lists read source, materialized counts, revision lineage and review versions from one SQLite read snapshot. A committed review whose derived view has not yet refreshed triggers a refresh before the list can enter a comparison. This prevents the interruption window between review commit and refresh from passing as an unreviewed cohort.

Task revision, projected context hash and adapter version must also match for the same task across checkpoints. The context hash covers only recognized recorded fields and cannot replace explicit environment versioning.

The UI selects runs by recorded context, profile, sampling setup and explicit checkpoint subset. It does not yet reconstruct previous inspector versions within a run or establish full-population sampling coverage. Next requirements include those historical profile views, controlled sampling coverage, claim/artifact association and real checkpoint-indexed integration. Changes in behavior frequencies must not be presented as causal effects of an RL update.
