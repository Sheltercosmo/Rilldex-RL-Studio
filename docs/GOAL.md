# Active product goal

**Mixed asynchronous execution — 15 October:** Added an independent, versioned
execution ledger for environment/rollout/inference/verifier attempts. Queued,
running and suspended work stays in the reported population; reversed revisions
and duplicate delivery cannot reset latest state. Environment, backend, model
role and policy labels remain separate from semantic observations and training
use. SDK/HTTP/offline bundles, SQL/CLI summaries, exports and durable feeds share
the contract. Default summaries separate training/evaluation, environment/version,
backend, model and role; measured latency coverage and completion-mix shifts are
explicit. 115 tests and three final-wheel workflows passed, including 16 local
concurrent clients, 16,000 authored attempts, 32,000 unique revisions and 16,000
duplicate reports. No model calls or synthetic records in the main workspace.
[Design and limits](DISTRIBUTED_RL.md) · [Evidence](../research/mixed-async-execution-2026-10-15/README.md).
This validates capture mechanics, not native inference engines or cluster
capacity. Sharded intake, cross-shard analytics, distributed observation scheduling
and production-scale validation remain open. The broader goal stays active.

**Exact recovery and offline research results — 14 October:** Custom analyses can
resume the original saved batch after source revisions or source unavailability.
`Results` exposes read-only SQL, progress, paged membership and consistent JSONL
batch exports without the original workspace; CLI access never initializes a
missing source. Continuous checks can reuse the latest unchanged complete batch,
preventing duplicate polling history. Database initialization publishes atomically,
and successful output/item completion now commit together. 84 focused tests and
two installed-package workflows passed, including a forced process stop followed
by source change and offline recovery. Existing v1 results passed unchanged
read/export; the UI download matches the bundled example. No model calls.
[Evidence and limits](../research/research-workflow-refinement-2026-10-14/README.md).
The broader goal remains active; distributed scheduling, automatic custom-result
dashboard publication and production-scale validation remain open.

**Code-first research foundation — 14 October:** Built-in dependency analyses now
have a public headless API/CLI, and custom Python can select source evidence with
SQL and persist versioned outputs in a separate SQLite database. Exact input
batches, failures, interruption recovery and content-based reuse are retained.
Portable indexed SQL datasets support independent database/graph analysis, with
a tested optional DuckDB/Parquet route. The installed app includes downloadable
code guidance and a runnable analysis example. 75 tests and three final-wheel
workflows passed; retained public observations and CPU-control data were read
without new inference. [Evidence and limits](../research/code-first-analysis-2026-10-14/README.md).
Distributed execution, production-scale performance, and automatic custom-result
publication into native dashboard metrics remain outside this implementation.
The broader product goal stays active.

**Reusable setup and restart boundaries — 14 October:** Start here now downloads
a launch file for local, remote-host and cloud capture. One file supports checks,
staged replay and live catch-up; paths resolve beside the file across terminal
directories. Remote/workstation shells are separate, raw snapshot completion is
explicit, and local automatic ports are supported. Startup rejects invalid
database paths; a known source's missing mount is not recreated as empty output.
Mirror status no longer creates a database for a mistyped path. 153 tests ran
(152 passed, one POSIX-only skip) and five installed-package workflows passed.
The actual UI download also passed a no-write launch check. No model calls.
[Evidence and limits](../research/quick-setup-2026-10-14/README.md). Real Docker,
Linux/macOS, managed notebook/cloud and production-scale deployment validation
remain open; the broader goal stays active.

**Scoped exports and durable consumers — 14 October:** Added recorded experiment
and observation-set discovery, measurement/graph export profiles, readable monitor
names and exact saved-graph links. Export settings survive evidence navigation in
the URL. A separate SQLite result mirror commits receipts and consumer cursors
together; once/follow/status CLI supports staged analysis and continuous catch-up.
64 focused tests, installed-wheel live/forced-stop/restart smoke, and browser
scope/download checks pass on Windows. No model calls or new research-workspace
test records. [Evidence and limits](../research/scoped-analysis-2026-10-14/README.md).
Cross-platform runtime and production-scale validation remain open; the broader
goal is active.

**Research input/output — 14 October:** Added a read-only Python/SQL interface,
CLI and HTTP access, ten saved-data tables, consistent JSONL/CSV exports, and
seven independent resumable receipt feeds. Lifecycle receipts retain completion
even when source text is unchanged. Connections → Export & code exposes scoped
previews, actual downloads and code examples. Continuous/staged replay parity,
read isolation, provenance, nulls and cursor boundaries are tested. 55 tests and
installed-package smoke passed; a browser download's manifest hashes matched.
No model calls. [Evidence and limits](../research/data-access-2026-10-14/README.md).
The broader deployment and semantic-quality goal remains active.

**Source discovery — 14 October:** Added bounded, read-only source detection to
setup and Watch a job, plus a database-free `discover` CLI. Detected layouts and
filename rules carry through generated commands and actual collectors; explicit
producer identities remain visible. Mixed, partial and unsupported samples are
reported. Seventy focused tests pass. Browser catch-up, new rollout delivery and
restart retained three receipts without duplication. Saved public SWE-agent
traces decode; mixed SWE-RL grading folders and the saved PRM evaluation schema
still need more specific integration work. No model calls. See
[evidence](../research/source-discovery-2026-10-14/README.md). The broader goal remains active.

**Use-case deployment — 14 October:** Connections now starts with six deployment
paths and generates location/stage/shell-specific instructions, restart guidance
and first-analysis links. Offline workers can export consistent packet bundles,
merge them through existing receipt identities, and return verified receipts to
free delivered queue space. This also supports artifact-based cluster/CI handoff.
97 distinct tests passed, plus installed-wheel and browser import/replay/receipt
checks. [Evidence and remaining environment gaps](../research/use-case-deployment-2026-10-14/README.md).
No model calls or new test records in the research workspace. Universal native
integration, real distributed deployment and the full product goal remain open.

**Real S3-client recovery — 14 October:** Actual s3fs HTTP calls to a local Moto
service exposed cloud failures blocking already-downloaded backlog. Cached
records now continue while remote freshness remains explicitly unknown; one-off
replay still fails if cloud access is unresolved. Connection/notebook totals use
database receipts so earlier capture and other delivery routes remain visible.
Thirteen installed S3-client scenarios, seventeen installed lifecycle scenarios,
68 passing tests (one POSIX skip) and a browser permission-failure/recovery check
pass. [Evidence](../research/s3-client-recovery-2026-10-14/README.md). No model calls.
This is real client/HTTP evidence against authored storage, not real AWS IAM,
GCS, Docker, Linux/macOS or production throughput validation. The goal stays active.

**Collector recovery — 14 October:** Reproduced a slow-read shutdown race that
reported stopped while allowing a second reader. Local producer ownership now
coordinates managed collectors and CLI replay; pending readers remain visible,
pause/resume and relocation wait for actual exit, and notebooks retain stopping
sessions. Other sources continue. Sixty-four tests pass on Windows; one POSIX
fork test is skipped. Installed-wheel handoff/restart and browser recovery checks
pass without model calls. [Evidence and runtime limits](../research/collector-recovery-2026-10-14/README.md).
Real Docker/cloud/Colab/Linux/macOS validation and the full product goal remain open.

**Controlling usability correction — 14 October:** The current request is deployment
and lifecycle usability: Ubuntu/Windows/macOS, Docker, remote jobs, cloud output,
notebooks, attachment mid-training, historical plus future input, and stop/restart.
Do not substitute more metrics for this work. Implement concrete launch and
recovery paths, preserve the same source/analysis contracts, and distinguish
tested environments from supplied configurations and unvalidated provider runtimes.

Deployment implementation now includes Docker persistence/health/lifecycle configuration,
managed S3/GCS prefix capture, notebook-owned capture/export, environment-specific
setup navigation and a stop/restart contract. Fifty-eight focused tests and a
Windows installed-wheel/listener smoke pass. Docker and multi-OS CI are supplied
but unrun here; real cloud/Colab/cluster validation remains open. No provider calls.
[Evidence and remaining gaps](../research/deployment-lifecycle-2026-10-14/README.md).

**Work maps into rollout monitoring — 14 October:** Existing Plan attempts,
native goal visits/requests and reviewed stop/defer/resume decisions now feed
seven separate count measures. Branch summaries expose effort and depth, open
prefilled monitors, and link saved value cases back to exact work scopes. Public
native source counts reconcile at 45 requests; the software review retains 12
linked dispatches without counting shared parent scopes repeatedly. Direct,
JSONL, snapshot and batch lifecycle controls agree and preserve historical
receipts. No provider calls. See [validation and limits](../research/work-structure-measures-2026-10-14/README.md).
This improves reuse of captured evidence; it does not establish exploration
quality, independent semantic accuracy or support for every native trainer. The
broad product goal remains active.

**Repeated-work inspection — 13 October:** Work path now lists recurring targets,
focuses their complete first-to-last recorded windows, and opens exact procedure
pairs with source/Unit-map drilldown. Collapsed repetitions remain individually
inspectable; full-route restoration and frozen links preserve context. Four
retained graphs, 50 JavaScript tests and desktop/narrow browser checks establish
presentation and evidence retention, not independent semantic accuracy. No model
calls. [Evidence and limitations](../research/work-focus-2026-10-13/README.md).
The full product goal remains active.

**Controlling scope correction — 13 October 2026:** The sparse-success blog is an
example of a researcher investigation, not a standalone implementation goal for
its proposed RL method. Prioritize notice/scope → retrieve/compare → distinguish
explanations → choose a useful check → incorporate results → decide, in the
existing investigation workspace. Reuse the maps, sample ledger, measurements
and saved evidence. Linking checks to returned evidence and revised findings is
now implemented in the existing Investigations workspace; automatic diagnostic
assistance and demonstrated researcher benefit remain open. Continuation comparisons are optional evidence for a
check, not the product's organizing concept. Native branching, automatic window
judges and optimizer/credit interventions are deferred unless broader validated
workflows justify them. See the [scope decision and current capability audit](RL_ENGINEERING_FRAMEWORK.md#scope-correction-learn-an-investigation-from-a-method--13-october).
The broad product goal remains active; linked evidence does not establish
automatic diagnosis, independent semantic accuracy or training benefit.

**Case retrieval in the investigation workflow — 13 October:** Checks & findings
now retrieves recurrence and comparable-recovery cases from frozen comparisons.
Researchers filter by work target/criterion, focus/reference, recorded outcome
and feedback reference; inspect the connected evidence; and attach the whole
case with its exact graph, source, projection, review notes and comparison.
Case counts and distinct rollout counts stay separate. Conflicting annotation
versions are withheld; missing links and incomplete recovery windows remain
unestablished. Validation: 130 focused Python tests, HTTP contracts, 17 retained
public cases across software/airline/retail, desktop/mobile and exported-bundle
checks. No model calls. These are retrieval and workflow checks, not a new
independent semantic evaluation. [Evidence and limits](../research/investigation-cases-2026-10-13/README.md).

**Source-reviewed procedure comparisons — 13 October:** Recurrence cases now
offer an exact-pair review of dispatched procedure, with source context, explicit
definitions and named provenance. Reviews produce immutable graphs and feed the
existing adaptation matrix and procedure-change monitor; unknown pairs and
original snapshots remain intact. A public software case distinguishes one
explicit setting change from two identical invocations across other work.
Seven other recurrences stay unreviewed. New graphs publish immediately to the
existing observer inventory. No model calls. [Implementation, verification and
limits](../research/procedure-reviews-2026-10-13/README.md). Automatic, independently
validated procedure observation and the broad product goal remain open.

**Reviewed work outline — 13 October:** Added a framework-neutral, source-linked objective/subgoal/approach/hypothesis outline inside Plans & attempts, with typed relationships, explicit scoped decisions and a correction editor. It preserves immutable graph versions, stable work identities and base units; unchanged reviews reuse the saved version. A public software development review demonstrates ten work items, nine parent links and one PDF-completion claim, connected to the existing attempt path and exact source/units. Full regression: 1,988 Python tests; final affected checks: 48 Python and 98 JavaScript. Desktop/mobile navigation and cutoff checks passed; no model calls. [Evidence and limits](../research/work-outline-2026-10-13/README.md). General automatic construction, independently evaluated semantic accuracy and training measures from these relationships remain unfinished. The broad product goal stays active.

**Nested goal map — 13 October:** Extended Plans & attempts with explicit source-captured goal/control trees, sibling effort comparisons, failure shortcuts, complete scoped history, record cutoffs and source-map round trips. A public ReAcTree evaluation example preserves 10 goals, four controls and 45 native operation requests, with two failed alternatives and later completion reports. The source Unit map retains 166 records without turning structural metadata into fake units. Full Python suite: 1,940 passed; subsequent affected checks: 34 Python and 31 JavaScript. No model calls. [Evidence and limitations](../research/nested-plan-map-2026-10-13/README.md). This is validated representation and explicit capture, not general free-text subplan extraction or a training-performance result; the broad goal remains active.

**Measured plan-case workflow — 13 October:** Connected existing native task-list monitors to the plan hierarchy with exact item identity, frozen graph/cutoff, switchable cases, highlighted history witnesses and return to the receipt. Fixed monitor navigation inheriting an unrelated experiment filter. Four public cases reconcile to 0/4 initial completed entries despite later completion reports; 21 Python checks, 11 JavaScript checks and desktop/mobile walkthroughs pass. One deterministic measurement was added, 694 cached results reused, and no model calls made. [Evidence](../research/plan-case-workflow-2026-10-13/README.md). General semantic Plan measures, nested branch extraction, independent semantic validity and the broader goal remain open.

**Plans & attempts — 13 October:** Added the first supported mind-map hierarchy inside Behavior map: saved Plan steps, linked preparation/attempt/check actions, feedback and traversable evidence connections; native task-list identity and reported state history; record cutoff and exact Unit-map drilldown. Reused software evidence has 13 linked actions across three stages, and a public OpenHands case has four native items across five declarations. Twenty-six focused Python tests, eleven related JavaScript tests and desktop/mobile checks passed, with zero model calls. [Evidence](../research/work-hierarchy-2026-10-13/README.md). This improves representation and inspection, not extraction accuracy. General nested objectives, subplans, variant identity, lifecycle validation and the broader product goal remain open.

**RL method adaptation: value observations — 12 October:** A framework-neutral value/return contract closes the critic measurement gap with automatic compatible series, native positions/masks, per-learner-step views and readable case drilldown. Five framework settings families, 16 native OpenRLHF CPU kernel backward steps with capture invariance, 1,878 tests and desktop/mobile checks passed. New model calls: zero. [Evidence](../research/value-observations-2026-10-12/README.md). Full native distributed integration and independent semantic/macro accuracy remain open; the product goal stays active.

**Return inspection workflow — 12 October:** The existing work map now opens a saved return as previous visit, intervening work and returned visit, with exact reference/source drilldown and stable episode/visit URLs. A public retrieval walkthrough exposed target-scope comparisons being presented as references; the final view separates them and its replay uses the actual optional comparison projection. Four retained-source projections, 22 focused JavaScript checks, 29 existing Python checks and desktop/mobile walkthroughs pass without model calls or changed measurements. [Evidence](../research/return-context-2026-10-12/README.md). This improves inspection, not extraction accuracy. Independent semantic validation, scalable work identity and native training populations for macro comparisons remain open; the full goal stays active.

**Activity versus target, with saved graph evidence — 12 October:** A six-call bounded experiment replaced broad task membership with explicit pair scope comparisons. V1 fixed both retrieval overmerges but confused a final answer with a different target from its reasoning question (8/9 development matches); the planned transfer calls were skipped. An opt-in v2 separates activity from the immediate question/outcome and matched all four targeted comparisons in the remaining two calls. Four v2 decisions now appear as source-inspectable relations in an isolated existing map; the incomplete layer does not create work groups or training measurements. Unit corrections invalidate its receipts and edges. Total new usage was 32,032 input / 963 output tokens, zero Luna; all old outputs remain. 81 Python and 38 JavaScript checks pass, and the browser inspector was verified. [Evidence and limits](../research/contribution-target-pairs-2026-10-12/README.md). Next validate announced/compound work and cross-domain target identity before deriving complete memberships or claiming macro accuracy. The broad goal stays active.

**Jev spending clarification — 12 October:** The user permits new Jev tests when a substantive change makes them useful; this supersedes the preceding blanket stop on calls. Do not cancel useful work solely to avoid all model use. Reuse exact saved requests, replay and validate offline first, then bound new calls to affected distinctions. A UI refresh, graph projection, audit, or unchanged experiment is not a reason to pay for recalculation. A changed harness is not automatically worth rerunning a whole dataset: state the expected improvement and freeze a small informative comparison first. Preserve failed experiments and report actual provider usage, including unknown billing after errors. No new numerical spending allowance was specified by the user.

**Work-membership replay and cost control — 12 October:** The generic membership experiment is not promoted: the corrected retrieval pass merges partial-scope searches; the airline pass stops at an unanswered request after 17 completed decisions. A read-only preflight now identifies the first uncached request, and `bind-work --cache-from` reuses exact validated decisions across workspaces. Tests establish that editing only the final contribution reuses the earlier prefix and requires only one new decision. The two real experiments replay without changing their saved artifacts or making model calls. Next isolate the membership/scope distinction using the existing local units and saved scope decisions; do not restart the unchanged broad experiment. [Audit, historical usage, and next test](../research/contribution-work-replay-2026-10-12/README.md). The full product goal remains active.

**Independent process-reference groundwork — 12 October:** The full AgentProcessBench corpus exposed 250 rejected BFCL imports. A source-preserving BFCL schema path and unlinked-result handling now admit all 1,000 trajectories while keeping 8,509 whole-message judgments separate from semantic units. The reproducible audit checks every message/call/schema binding; earlier corpus exposure constrains the final task-group split to 600 development / 400 reserved trajectories. Native quality transitions are not mislabeled as recovery, and no training clock or model prediction is fabricated. [Evidence](../research/agentprocess-reference-2026-10-12/README.md). Automatic work identity, complete semantic paths, independent diagnostic accuracy and the broader training gates remain open; the full goal stays active.

**Contribution-scoped candidates — 12 October:** Six fixed development units distinguish next-step announcements, recalled knowledge and performed derivation at the proposal stage. Five initial responses pass source validation; one malformed quote remains rejected. A fresh explicit whole-unit reference variant resolves that case through exact source binding. All six now load and replay through the production file provider, with zero selected activities or new monitoring labels. The runtime citation change passed the 1,526-test suite; 27 focused tests cover the subsequent handoff and retained-output checks. Historical replay covers 19 runs / 54 units without changing requests or files. Five Luna turns, zero Jev calls; billed tokens are unavailable. [Evidence and limits](../research/scoped-reading-trial-2026-10-12/README.md). Selector agreement, useful targets, full paths and independent validation remain open; the full goal stays active.

**Public native-plan transfer — 11 October:** Real OpenHands captures exposed a legacy importer that discarded message text and tool calls. A dedicated native adapter now preserves all 1,211 calls and 1,191 returned responses across twenty frozen public rows, with evaluation fields kept outside agent-visible evidence. Schema-declared task IDs extend task-list history to v2; first-list completion rates distinguish prospective-looking lists from lists already reporting work done. Exact source-entry review resolves ambiguous cases sharing one call. Full 1,515 tests passed before the last review repair, followed by 24 affected tests, eleven map tests and four browser groups. Old v1 receipts remain readable. No model calls or inferred training clock; main 8765 remains untouched. [Evidence](../research/declared-plan-transfer-2026-10-11/README.md). Only four captures contain native lists, so these are optional evidence. General activity/target extraction and independently reviewed attempt/check paths remain the next gate; the broader goal stays active.

**Structured task-list history — 11 October:** A source-only operator now reads documented LangChain/OpenHands task-list calls through canonical events, stores list/item/previous-declaration relations and supplies declaration-count and reported-reopening monitors. Existing maps show readable lists and their changes without fake semantic units; reviews retain raw structured arguments. Renames, duplicates, removal, invalid gaps and parallel ambiguity remain unknown. Sixteen authored captures agree across two profiles and two encodings; three extracted upstream schema classes, 1,509 backend tests, eleven map tests and three browser groups pass. No model calls, real RL validation or verified-completion claim. [Contract](DECLARED_PLANS.md) · [Evidence](../research/declared-plans-2026-10-11/README.md). The isolated 8794 preview runs the new backend; main 8765 and its in-memory credentials remain untouched. Free-text extraction, actual plan/attempt/check correspondence and independently reviewed training traces remain open; the broader goal stays active.

**Work-switch evidence boundary — 11 October:** Saved return measurements now expose an exact visit-entry explanation in the existing map, highlight only decision witnesses and scroll to the measured contribution. New v2 review samples freeze that entry scope; old reviews retain their original full-visit scope. All four retained public reasoning cases previously included later same-visit units; those are excluded from new entry reviews without changing the 2/4 return rate, source graphs or historical measurements. All 1,502 backend tests and four browser groups pass. No model calls or independent semantic-accuracy claim. [Evidence](../research/work-switch-entry-2026-10-11/README.md). Complete target/path validity and broader native training validation remain open; the full goal stays active.

**Saved measurement review — 11 October:** Rate monitors now freeze a cohort and sample saved opportunity cases, including unresolved outcomes, for source-cited named review before revealing the saved answer in that case view. Append-only judgments separate classification disagreements, unknowns and eligibility disputes; cases open the existing exact-measurement correction map. Four public reasoning cases remain unreviewed; the software source has no eligible switches. The full regression run passed 1,495 tests before final source/UI repairs; 29 affected tests and seven browser groups passed afterward. No new model calls or semantic-accuracy claim. [Contract](MEASUREMENT_REVIEWS.md) · [Evidence and limits](../research/measurement-review-2026-10-11/README.md). Independent measurement validity remains the next gate; the full goal stays active.

**Candidate/selector contract alignment — 11 October:** Added opt-in `contribution-readings/2`, binding every activity route to identical generator/selector definitions and explicitly distinguishing current contribution from described work. The retained audit identifies 49 mismatched work-phase units among 54 compared reading units; all new requests align while preserving source prefixes. No new model predictions, activity labels or confidence gates. Historical workspaces remain v1, and mixed reading protocols cannot be pooled. Next, evaluate unit activity, readable work target and complete relation paths together on independent prefix-safe cases before promoting this protocol. [Evidence](../research/contribution-scope-2026-10-11/README.md). General automatic extraction and semantic accuracy remain unresolved; the full goal stays active.

**Work evidence reaches the macro map — 11 October:** Restored saved stated-work attempt/preparation/check links in both existing action navigation and generic contribution navigation. The inspector distinguishes prose, recorded dispatch and native textual implementation; Orient announcements remain Orient and reported completion remains a claim. Retained software replay preserves 64 links and 28 work visits; native reasoning preserves 53 references and six visits. No new model calls or semantic accuracy claim. [Evidence and limits](../research/work-evidence-2026-10-11/README.md). Independent announcement/performance and complete-path validation remains the next semantic gate; the full product goal stays active.

**Bounded Luna proposal result — 11 October:** Operation/target decomposition supplied readable work descriptions but still mislabeled a next-step announcement as performed reasoning; neither variant recovered the one native checking path. Four of six subjects had later same-trace context exposed by batching, so this is retrospective exploratory evidence only. A separate audited planner now prevents differing source cutoffs sharing a future fresh context; no extra model turns were run. Resolve announcement/performance and native textual-implementation meanings before repeating or promoting the proposal workflow. Two Luna turns, no Jev calls, billed tokens unavailable; 22 affected tests passed. [Evidence](../research/luna-purpose-target-2026-10-11/README.md). The complete product goal remains active.

**Whole-path semantic audit — 11 October:** Replayed saved experimental native-relation selections against raw paired human annotations. The original 43-case study selects two checking paths that both disagree with native references, and misses its one fully inspected reference path despite having both candidates. Added an executable path-level audit and inspectable source-card report; no classifier accuracy fix or current-observer certification is claimed. The next semantic experiment must validate expressed purpose, exact target and complete paths together; candidate recall and negative-dominated pair agreement are insufficient. [Evidence and next gate](../research/path-selection-audit-2026-10-11/README.md). Independent product-specific semantic validation remains required; the broader goal stays active.

**Independent next-check outcomes — 11 October:** Added a versioned first-recheck outcome measure with separate captured-input groups, correcting the circularity of comparing changes using a success definition that already requires a change. The eleven retained executed controls produce five passing, five failing and six unknown opportunities; all three source encodings agree and legacy recovery graph identities remain intact. Existing monitors, question checks and case maps expose the new measures. [Contract and limits](NEXT_CHECK_OUTCOMES.md). Captured input changes are not semantic revision labels; independent semantic validity and the broader product goal remain open.

**Question evidence checks — 11 October:** Implemented experiment/question/measure checks inside Data connections, using existing training records and monitor receipts. Missing sources, observations, stale calculations, unresolved recovery and unavailable validation remain distinct; named filters, cohort splits and sample/source counts carry into existing investigations. The main 3,072-rollout corpus exposed and verified read-only compatibility with an older database lacking training tables. [Evidence and limits](../research/question-readiness-2026-10-11/README.md). This improves the connected researcher workflow; independent semantic accuracy and the broader product goal remain open.

**Engineer workflow consolidation — 11 October:** Rechecked primary community reports on incomplete training joins, scorer errors hidden as reward zero and incomplete callback context. The controlling direction now makes question-specific readiness and shared investigation context the next acceptance demonstration, followed by cross-domain recovery/selection validity and correction-effort measurement. This turn updates the plan and evidence; it adds no runtime integration or semantic-accuracy claim. [Review](../research/universal-rl-review-2026-10-11/README.md#follow-up-engineer-workflow-before-another-integration). The full goal remains active.

**Generation/export token evidence — 11 October:** Added optional exact token contexts and logical episode references in v2 samples, with visible sequence differences, mask counts and mixed policy versions. An experimental AReaL bridge passes pinned source-component controls, grouped-rollout guards and delivery/UI checks. The ordinary runtime probe did not pass; this does not close native trainer coverage or semantic accuracy. [Contract](TRAINING_TOKEN_CONTEXT.md) · [Evidence](../research/areal-export-2026-10-11/README.md). The full goal remains active.

**Independent training samples — 11 October:** Added an opt-in v2 identity contract and episode/span mappings through the existing intake, training populations, frozen investigations and behavior comparisons. Stage counts use samples; behavior and opportunity counts weight distinct source rollouts. [Contract](INDEPENDENT_TRAINING_SAMPLES.md) · [Evidence](../research/independent-samples-2026-10-11/README.md). Native multi-sample capture, context alignment, expected groups, mixed-policy generation and independent semantic validity remain open. The full goal stays active.

**Unit correction inside recovery — 11 October:** Added complete-window boundary/activity/content review in the existing rollout map, explicit dependency impact, immutable graph composition and continuation of the same graph/analysis measurement. Saved recovery cases open their original semantic input; recorded outcomes and semantic references remain distinct. [Contract](UNIT_REVIEWS.md) · [Evidence](../research/unit-correction-2026-10-11/README.md). This is an initial integrated correction workflow. Independent semantic validation, automatic extraction quality, finer dependency invalidation and native multi-sample training mappings remain required; the full goal stays active.

**RL engineering workflow review — 11 October:** Sharpened the framework around linked execution, per-call context, agent work and training evidence. New contract probes confirm that separate sample declarations for one rollout currently conflict; explicit episode/interaction/sample mapping is required before a broader multi-turn native integration. The near-term order remains complete selection/recovery investigations, compatible identity expansion, a second native trainer and independent validity/cost testing. This is a direction review and reproducible architecture audit, not a new runtime feature. [Evidence, useful recipes and acceptance](../research/rl-engineer-workflows-2026-10-11/README.md). The full goal stays active.

**Population measures — 11 October:** Existing monitors now compare over one frozen declared-sample cohort, retaining per-measure missingness, common support, group context, shared sources and exact receipts. An authored recovery control verifies that censored retries remain unknown through comparison and case review. [Contract and evidence](POPULATION_COMPARISONS.md). Unit correction inside recovery, independent semantic validation, async lifecycle capture and another native trainer remain required; the full goal stays active.

**Preserved training investigations — 11 October:** Completed an initial training-population → pinned comparison → exact case → return → hypothesis revision loop using existing storage and views. All 1,357 backend tests and eight browser groups pass; retained native CPU packets reconcile. [Contract](TRAINING_INVESTIGATIONS.md). This does not finish the portable investigation gate: cross-metric population matching, unit correction in recovery, independent semantic validation and another native trainer remain required. The full goal stays active.

**Shared analysis execution — 11 October:** Migrated all 18 deterministic operations to common registered contracts, including source and composed recovery paths. Generic plan validation/execution and monitor dependency expansion no longer branch on operation names. All 1,351 tests, 90 exact legacy output comparisons and five browser checks pass. [Evidence](../research/operation-registry-2026-10-11/README.md). The next product slice is a preserved investigation context across training selection, behavior comparison and rollout evidence. Independent semantics, broader lifecycle capture and native trainer validation remain required; the full goal stays active.

**Direction review — 11 October:** Preserve the macro behavior goal while prioritizing complete, portable investigations over additional isolated labels or editors. The next slices share operation/dependency declarations and investigation context across behavior-before/after-selection and failure/recovery workflows. Explicit lifecycle identity, independent semantic validation and a second materially different native trainer remain delivery gates. [Controlling framework](RL_ENGINEERING_FRAMEWORK.md) · [Community and code evidence](../research/universal-rl-review-2026-10-11/README.md). The goal remains active.

**Relationship correction — 11 October:** Exact source-bound feedback/evidence/revision reviews now compose with work-target annotations, update existing graph measurements and preserve original receipts. A public airline development review records two explicit references with sixteen unknown responses; it does not validate report correctness. Full 1,339-test regression, an additional recovery-composition check and five browser checks pass. [Evidence and limits](../research/relationship-correction-2026-10-11/README.md). Independent semantic validation and the broader product goal remain unfinished.

**Framework consolidation — 11 October:** The controlling plan now separates training evidence, agent work and saved investigations, with extension contracts for capture, observation, measurement and domain profiles. Community examples about partial batches, task routing and all/effective populations inform the engineering questions. A shared contract now drives monitor observer routing and backend validation without preferring a software observer. All 1,329 backend tests and five browser checks pass. These verify mechanics; independent semantic accuracy and researcher benefit remain open. [Revised direction](RL_ENGINEERING_FRAMEWORK.md) · [Evidence](../research/engineering-consolidation-2026-10-11/README.md). The full goal remains active.

**Native optimizer membership — 11 October:** The existing portable sample ledger and comparison view now receive confirmed accumulated sample-use receipts from opt-in, pinned TRL CPU AdamW execution. Six native updates and all 24 sample uses reconcile with an independent Torch post-step oracle; capture leaves tokens, rewards, prepared tensors and parameters unchanged. New source captures correctly label the trainer's global step separately from optimizer completion. Population curves, evidence export and stage-specific counts use the existing workflow. This closes one training integration gap; independent semantics, a second native trainer, async lineage and deployment scale remain open. [Evidence](../research/optimizer-use-2026-10-11/README.md). The full product goal remains active.

**Connected work evidence — 11 October:** The generic work map now projects saved request/Plan references, exact stage roles, feedback-response paths, revisions and native reasoning references onto existing visits. It preserves work membership and population metrics, keeps within-visit relations distinct from transitions, and opens original evidence from grouped lines. Replay covers 18 retained traces / 1,421 saved relationships; 1,305 tests and five browser groups pass, with zero new model calls. These are projection/interaction results, not independent semantic accuracy or validated exploration/deviation diagnosis. [Evidence and remaining gates](../research/framework-core-2026-10-11/work-connections/README.md). The full product goal remains active.

**Work population measures — 11 October:** Shared immediate-work profiles now pool compatible rollouts while retaining immutable local review revisions. The existing dashboard shows visit distributions and recorded-step curves; a new monitor measures supported returns among decidable work switches with unknowns explicit. Exact cases open the same work/unit map. Six browser groups verify live correction and preserved prior evidence; 1,293 Python tests pass. The public reasoning case has no training coordinates; authored controls test the training axis. No model calls were made. Independent semantic accuracy and native sample-use joins remain open. [Contract and evidence](../research/framework-core-2026-10-11/work-subjects/population-README.md). The full goal remains active.

**Contribution-work foundation — 11 October:** The existing map and analysis engine now support explicit work-subject bindings for reasoning contributions and actions. The unit inspector supports named target review, earlier-target assignment and immutable corrections; stale edits are rejected. Structural replay spans 18 saved traces. These reviews provide a common representation and correction path; automatic extraction, independent semantic accuracy and engineering benefit remain open. [Contract and evidence](../research/framework-core-2026-10-11/work-subjects/README.md). The broader product goal remains active.

## Controlling scope — 11 October 2026

Build an accurate, adaptable RL behavior investigation and monitoring system that connects what models express and do with how their samples are generated, scored, selected and used in training. A useful result is an evidence-backed population measurement and a concrete next experiment, with rollout-level drill-down. Coherent units, one primary activity per unit, readable category-conditioned contents and supported relations remain the semantic foundation; richer macro behavior is built from that evidence. Jev remains supplied-option raw-argmax selection.

Follow the [consolidated framework and delivery gates](RL_ENGINEERING_FRAMEWORK.md#delivery-gates). Complete one portable feedback/recovery investigation through setup, comparison, correction and a saved monitor using the existing work and training foundations. Validate its measurements independently, compare direct scanning with graph reuse, and then close a second native training loop including delivery failures and sample selection. Capture/population health applies throughout. This replaces narrower historical priorities without declaring unfinished accuracy work complete. The full product goal remains active.

**Engineering direction review — 11 October:** The common core is versioned evidence, sample lineage, scoped observations and reusable measurements. Domain meanings remain explicit profiles. Support is assessed separately for format fidelity, native runtime, semantics, measurement validity and operating scale. Consolidate existing components around feedback use, recovery and sample selection; avoid another broad tag/proposal experiment before identifying the blocking error in a selected question. [Community evidence, implementation audit and decisions](../research/framework-core-2026-10-11/engineering-review.md).

**Practical framework revision — 11 October:** Separate environment, agent harness, inference service, trainer and observer contracts. Prioritize reusable engineering questions, capture/population context and comparable training investigations over more individual tags or detectors. The existing analysis engine now exposes per-operation contracts and a read-only whole-plan preflight, with structural evidence counts and explicit accuracy limits. [Decision and next gates](RL_ENGINEERING_FRAMEWORK.md#delivery-gates) · [Implementation and evidence](../research/framework-core-2026-10-11/README.md). This does not establish semantic accuracy, broad trainer support or completion of the product goal.

**Cross-activity feedback foundation — 11 October:** An opt-in contribution scope, free preflight, source-defined feedback opportunities and a saved monitor now share the existing graph/analysis engine. Retained software reports 19 reference witnesses / 33 responses with 14 unknowns; airline and retail remain unavailable under their old observers. Expanded public questions are prepared, not executed or accuracy-validated. [Contract](FEEDBACK_REFERENCE.md) · [Evidence](../research/feedback-contributions-2026-10-11/README.md). This partially delivers Slice 2; the full goal stays active.

## Historical progress and requirements

**Question setup — 11 October:** The existing monitor editor now checks a question's current source/observer evidence and saves exact experiment/environment/split scope. Materialization, chart denominators, cases, receipts and training behavior comparisons retain the scope; native training-stage counts remain separate. Four read-only public/control checks, 1,269 Python tests and six browser check groups pass. This is practical progress on Slice 1; automatic semantic accuracy, general work identity and the complete correction/training gates remain unfinished. [Implementation and evidence](../research/framework-core-2026-10-11/question-setup/README.md).

**Reasoning without tool actions — 11 October:** Recorded relationship-path queries now use the same typed DAG, cache, monitor and source-map workflow. A retained paired-human reference corpus reconciles 19 native paths across 15 traces with zero actions and no fabricated training clock. Native labels, disputes and limits are explicit. Automatic semantic accuracy and reasoning work-identity navigation remain open. [Audit and preview](../research/reasoning-paths-2026-10-11/README.md). The full goal remains active.

**Macro distribution workflow — 11 October:** Same-work recurrence and exact-pair procedure observations now appear in population distributions, with native action coverage, unknown comparisons, recorded-step curves, cached analysis receipts and exact episode/unit drill-down. Three retained public domains reconcile 57 actions; authored controls verify missing annotations and automatic late updates. All 1,241 Python tests pass; no model calls. This improves usability without establishing exploration/deviation labels or semantic accuracy. [Evidence and remaining gate](../research/work-distributions-2026-10-11/README.md). The full goal stays active.

**Macro-path retrieval evidence — 11 October:** Frozen candidate retrieval was evaluated on fifteen previously reserved, paired-human ReasoningFlow traces after exact task/source deduplication against the six declared development traces. A separate checker reconciles 301 native consensus links and nineteen verification-intention chains. Hybrid-12 finds 277 links but only twelve complete chains; hybrid-24 finds 296 links and eighteen chains. Added an opt-in bounded retrieval API while preserving existing defaults and Jev argmax. Full suite: 1,233 tests; zero model calls. Human segmentation, native labels, limited domains and unmeasured selector accuracy prevent a product semantic-accuracy claim. [Evidence and next gate](../research/relation-retrieval-reserved-2026-10-11/README.md). The full goal remains active.

**Training-selection investigation — 11 October:** Added a reusable named-filter comparison over existing monitors and training facts, including decision conflicts/unknowns, per-step behavior curves, within-recorded-group contrasts, exact sample drill-down and linkable selections. Replayed native TRL records reconcile four admitted/eight rejected training samples with independent source arithmetic; fourteen browser checks verify live late facts and observations. Full suite: 1,231 tests. No new model calls; semantic accuracy and broader native integrations remain unfinished. [Contract](TRAINING_SELECTION.md) · [Evidence](../research/training-selection-2026-10-11/README.md). The full goal stays active.

**Recovery investigation implementation — 11 October:** A versioned three-check recovery operation now distinguishes supported recovery, fully observed failed windows and unknown follow-up. It reuses state capture and the analysis DAG, retains optional feedback references in the unified evidence map, and saves an investigation as a monitor. Eleven executed authored software/business/SQLite controls, 33 encoding checks, 1,223 Python tests and 14 browser checks pass. This is mechanics validation; independent semantic accuracy, real-workload capture and the complete training investigation gate remain unfinished. [Contract](RECOVERY_WINDOWS.md) · [Evidence](../research/recovery-windows-2026-10-11/README.md). The full goal stays active.

**Training-context implementation — 11 October:** The first revised-plan slice now has immutable training facts, exact source/monitor joins and a Training samples overview. Actual TRL 1.13.0 CPU capture-on/off controls preserve tokens, rewards, backward inputs and final weights. Twelve training samples produce 24 backward-use records, but only four samples have positive native completion masks. Real HTTP retry recovery and pushed late-score browser updates are verified. This is a partial engineering foundation; optimizer confirmation, broader native trainer validation, reusable semantic operations and independent accuracy remain unfinished. [Contract](TRAINING_LINEAGE.md) · [Evidence](../research/training-lineage-2026-10-11/README.md). The full goal stays active.

Progress entries below retain dated evidence and original wording. Earlier “next” and “current priority” statements do not override the controlling scope above. Existing accuracy requirements still apply.

**Progress — reference accuracy and Harbor follow-through, 11 October:** Added opt-in direct response-set selection and canonical adapter feedback bindings. The former resolves the software e50 disagreement under an explicit direct-reference convention; the latter fixes lost Harbor evidence after successful import. The revised method matches 42 frozen development expectations (18 software, 20 authored contrasts, four public framework fixtures), versus 38 for the old combination. This is not independent accuracy. The new software map retains all base units and ten recurrences, with 19 assessment links and preserved older observers. Full 1,177-test suite plus the new CLI registration regression pass. Fifty-seven successful Jev calls used 213,930 input / 4,453 output tokens; one HTTP 451 attempt has unknown usage, and no Luna was used. [Evidence and limits](../research/feedback-direct-sets-2026-10-11/README.md). Next expand distant/multiple response retrieval and independent source review before promoting macro recovery or exploration measures. The full product goal remains active.

**Progress — reusable history after revision, 11 October:** Added `semantic rebuild-history`: regenerate target and feedback requests from a complete extraction, reuse only identical validated decisions, enforce frozen configuration, budget new calls and prevent partial publication. The corrected software observer recovers ten recurrences and five returns through 64 exact saved decisions; 33 actions remain reachable in 28 live work cards. Airline and retail replay checks bring represented actions to 57 across three retained traces. Zero new Jev/Luna calls. All 1,172 Python tests pass; nine live browser checks preserve the 3,091-source population. The known feedback-reference disagreement remains flagged, and neither replay nor cross-domain coverage establishes accuracy. Method/scope dependencies remain unrecomputed. Next validate target identity and feedback referents on source-reviewed held-out cases before rebuilding higher interpretations. [Evidence and limits](../research/history-reuse-2026-10-11/README.md). The full product goal remains active.

**Progress — complete source revision and Plan rebuilding, 11 October:** Added a reusable `semantic revise` workflow with frozen boundaries, versioned activity decisions, exact unchanged-content reuse, fresh changed-category candidates, call/byte budgets and lineage checks at map loading. The full 68-unit public software trace changes only its false scaffold Plan to Orient; one replacement content bundle is Jev-selected and all twelve report-stage correspondences are rebuilt. The older observer remains available. Source review notes and a new registered map expose the revision; overlapping edge labels were replaced by hover/inspector names with keyboard access. Full suite: 1,162 passing tests plus a native mini-SWE-agent revision check; eight live browser checks preserve all 3,091 sources. Ninety-three Jev calls used 489,260 input / 10,311 output tokens; exact complete replay uses zero calls and no Luna was used. This preserves old boundaries and 67 content selections, so it is not independent fresh-extraction accuracy. Recurrence/method/outcome sidecars remain unrecomputed in this observer. Next prioritize dependency-scoped reuse and smaller evidence packets, followed by complete cross-domain trace/relationship validation before promoting exploration or recovery measures. [Evidence and limitations](../research/whole-revision-2026-10-11/README.md). The full product goal remains active.

**Progress — semantic foundation regression, 11 October:** Source review found an immediate file-scaffold announcement classified as a Plan, contaminating its stage interpretation. The optional `work-organization-activity/1` distinguishes intended product structure from organization of work; sixteen development cases match frozen expectations across software, browser and business examples. This is not independent or whole-rollout accuracy. Candidate workers, source-bound workspaces, audit and map provenance now preserve the selected definition, with legacy replay intact. Full suite: 1,154 tests passed; one additional criteria-integrity regression also passed. Twenty-four Jev responses used 68,442 input / 3,096 output tokens and no Luna. Existing maps are unchanged: next apply the new version to complete reviewed rollouts and rebuild dependent content/relations before promoting macro measures. [Audit, source proof and limitations](../research/plan-boundary-2026-10-11/README.md). The full goal remains active.

**Semantic execution practice — 11 October:** General extraction now has separate per-execution Jev/candidate invocation and input-byte allowances, durable attempt receipts, explicit missing token reports and current partial coverage. Budget stops preserve the prior completed map; cached work resumes without calls. Replay validates 429 retained decisions over 19 public software, airline, retail and flat-generation rollouts through 77 budget stops, with no new inference. Connections links to the practical setup recipe. These controls do not establish semantic accuracy or supply an automatic proposer. [Evidence, operating limits and remaining gates](../research/semantic-budget-2026-10-11/README.md). The full product goal remains active.

**Concurrent capture practice — 11 October:** Two independent native TRL 1.13.0 CPU trainers each complete 80 optimizer steps and evaluation with live delivery. All 328 completions, four cohort aggregates and exact reward receipts match native output; capture-on/off tokens and parameters are unchanged. Throttling and malformed acknowledgments recover without duplicates; the browser updates without reload. Optional worker reports distinguish local queues from confirmed collector receipts and protect freshness with durable report sequences. Successful batches no longer idle with pending work, while new capture cannot defeat transient backoff. This is a verified concurrent ingestion path, not DDP, large-job throughput or semantic accuracy. [Audit and actual latency](../research/concurrent-training-2026-10-11/README.md). Next scope remains distributed/async policy-use provenance, sustained-load controls, and budgeted, independently validated semantic extraction over tool trajectories. The full goal remains active.

**Native trainer gate — 11 October:** Actual unmodified TRL 1.13.0 CPU GRPO now completes six optimizer steps and evaluation through the public reward capture bridge. Two fresh-directory controls each preserve all 16 completions, exact tokens/rewards/policy hashes and final model parameters against capture-disabled training. Lost HTTP acknowledgment plus reopened local queue yields no duplicate revisions; automatic monitor bins and all exact reward receipts match native output. The dashboard distinguishes train/evaluation and labels clock/display-order semantics. All 1,115 Python tests, seven new browser checks and four existing saved-history checks pass. Current TRL 1.15.0 failed on this Windows CPU at its mandatory Triton path; the failure is retained, not hidden by an upstream patch. Next: distributed/asynchronous producer identity, concurrent delivery/backpressure under useful load, richer live tool traces, and independent semantic review. No claim of production throughput or universal framework compatibility. [Audit and pins](../research/trl-runtime-2026-10-11/README.md). The broader goal remains active.

**Broader practice validation — 11 October:** Added a native text τ-bench reader and made JSONL/native-bundle imports usable through one shared browser/HTTP/CLI path. Replayed 656 published airline/telecom simulations, retaining 4,572 assistant calls, 4,569 linked results and 5,587 separate user-side calls. Whole-file validation, bounded previews, stable repeated-sample identity, graph persistence and source-linked monitors are verified in an isolated database. All 1,105 Python tests and eight browser checks passed with zero inference calls. This strengthens evidence capture and practical usability; the next trainer gate remains a pinned live callback run with interrupted-delivery recovery, correct policy/clocks, counted capture completeness and measured overhead. Held-out unit/relation accuracy is independently required. [Audit and limits](../research/native-adapters-2026-10-11/README.md). The product goal remains active.

**Portability delivery — 9 October:** Common source contracts now cover recorded chat/tool messages, environment episodes and flat generations, alongside native ATIF/Harbor and existing adapters. New no-write UI/API/CLI preflight separates connectivity, source evidence, deterministic measurements and semantic readiness. Environment metrics flow through the same revision database, graphs, monitors, investigations and immutable evidence receipts. A real Gymnasium 1.4.0 terminal/truncation audit, 121 focused regression tests and browser checks ground these claims. Framework hook research is explicitly not end-to-end trainer validation. The next integration gate is a pinned small trainer run with capture completeness, correct async identities, recovery and measured overhead; domain-specific semantic accuracy remains required independently. [Evidence, setup and limitations](INTEGRATION_COVERAGE.md). The full product goal remains active.

**Current engineering delivery — 9 October:** Running-job intake is now managed in the application: persistent directory connections, partial-write recovery, late-result revisions, durable producer delivery and pushed source/analysis updates. A public Harbor replay verifies the end-to-end path, including a corrected reward mapping. This supports the existing semantic foundation; it does not complete automatic extraction or establish training-scale performance. [Integration and next practical requirements](LIVE_INGESTION.md).

**Implementation — configurable history monitors, 9 October:** History queries now integrate with the existing monitor editor, cached background materialization, per-rollout/step plots and immutable measurement receipts. Query edits preserve earlier values; selected-but-unknown opportunities remain separate from rollouts with no selected dispatches. The deployed public monitor materialized all 3,091 imports: one airline rollout contributes 3/6 matches, while 3,090 zero-opportunity values reuse source graphs. No public training coordinates were invented. All 85 affected Python tests and isolated/live browser workflows pass; zero model calls. [Definition, audit, UI and limits](../research/history-monitor-2026-10-09/README.md). Next priority returns to validated macro work/approach transitions and broader semantic coverage. The full product goal remains active.

**Implementation — structured history evidence, 9 October:** Completed an explicit query primitive joining native dispatch arguments to the latest matching prior lookup and returned attributes, with three-valued results, action-time scope, cache reuse and persisted graph witnesses. Public replay finds 3/6 airline bookings selecting a recorded Mastercard, 1/1 retail exchange using an order recorded as delivered, one ambiguous duplicate-item identity, and 33 software actions without native arguments. The existing map exposes these facts without adding activity cards; the batch CLI retains separate per-rollout denominators. All 67 affected Python tests, 17 layout tests and live browser checks pass. Zero model calls. These observations do not establish policy compliance, successful effects, macro strategy or independent accuracy. Configurable dashboard registration, richer history semantics and general macro validation remain open. [Contract, public replay and command](../research/history-evidence-2026-10-09/README.md). The full goal remains active.

**Implementation and evaluation — compact condition evidence and reusable execution, 9 October:** Lossless tool-contract interning reduces the previously blocked airline packet from 77,623 to 68,079 characters with all 31 events preserved. The version-4 observer matches 18/19 frozen development expectations, including ten prior-case comparisons and nine new public pairs; software requirements were manually seeded exact source sentences. The remaining software case exposes artifact-versus-runtime scope ambiguity. Two explicit authored contrasts pass without changing the observer; the original disagreement remains recorded. Added a cache-first CLI with frozen input bindings, cumulative HTTP budgets, pending-request receipts and raw-argmax replay; a real airline result reproduces with zero calls. All 49 affected tests and both offline audits pass. This study used 32 Jev calls, 227,860 input / 5,031 output tokens, zero Luna. No direct monitor is enabled. Scope interpretation, evidence sets, automatic transfer extraction, independent validation and population coverage remain unfinished. [Implementation, command and evidence](../research/condition-compaction-2026-10-09/README.md). The full goal remains active.

**Research progress — grounded condition observations, 9 October:** Added a reusable operation → governed instance → positive evidence observer, with exact source witnesses, subset coverage and raw-argmax replay. The 16-case first pilot corrected the six sampled public scope failures and missing-verification failure but exposed request-as-evidence and stage errors. A retained failed revision revealed an unconditional witness-selection instruction. The evidence-only repair matches nine of ten selected development expectations; one airline packet remains context-limited. These are assistant-authored, reused cases, not independent accuracy or prevalence. All 36 results replay, 39 affected tests pass, and 67 metered HTTP attempts total 307,088 input / 7,188 output tokens, with zero Luna calls. Prior decisions and errors are retained. No direct monitor or alert is enabled. Next work is bounded evidence packets, evidence sets, broader real-trace evaluation and reviewed monitoring denominators. [Implementation, failures, costs and limits](../research/condition-grounding-2026-10-09/README.md). The full goal remains active.

**Research result — action-condition observer withheld, 9 October:** A staged, argmax-only observer was implemented and tested on frozen authored controls plus the complete retail/airline inputs. Real source review found that workflow context contaminated operation applicability and that missing verification was sometimes called a conflict. A nine-request focused-packet comparison corrected five of six sampled scope errors but left the calculation and missing-evidence failures. This version is deliberately not promoted to direct monitoring or live graphs. All raw decisions and 90 total Jev calls (1,049,582 input / 13,035 output tokens; zero Luna) are retained and replayable. The next design must ground operation, subject and decisive evidence separately, then test fresh cases. The source-linked condition graph remains intact. [Experiment, counterexamples, costs and next requirements](../research/condition-dispatch-2026-10-09/README.md). The full goal remains active.

**Implementation — typed conditions in historical action context, 9 October:** The graph now retains requirements, requested checks and attributed claims as distinct source-linked objects inside condition versions. Normal graph creation includes complete requested histories, with unchanged clause identity, explicit revision/removal edges and action-time snapshots. This repairs the recent retail integration's use of an older record that omitted the waiting restriction, reusing the already audited version 2 extraction. Retail/airline source replay preserves all 24 actions, 20 clause versions and the original 37/50 visible cards, without new inference. Clause integrity is checked by replaying edits rather than trusting enclosing hashes. The inspector exposes exact sources and retirements without claiming satisfaction. Condition applicability, attempt versus effect, independent accuracy and general training coverage remain unfinished. [Contract and evidence](../research/request-conditions-2026-10-09/README.md). The full goal remains active.

**Implementation — request context at dispatch, 9 October:** The property graph and existing unit inspector now expose the exact historical request/condition snapshot for an action and its inherited work-role judgments. All 24 public retail/airline actions are represented, with 38 existing positive links, five distinct snapshots and 96 prior pair judgments replayed without new inference. Retail e27 retains GC7381924 and excludes the later replacement-card instruction. State/version objects do not create activity units; native coverage gaps and uninspected condition satisfaction remain explicit. Live desktop/mobile source navigation passes. This closes a graph/inspection gap; condition applicability, current purpose, violation/effect distinction and independent accuracy remain unfinished. [Contract and evidence](../research/request-dispatch-2026-10-09/README.md). The full goal remains active.

**Implementation — requested terms and historical versions, 9 October:** The existing rollout map now exposes source-linked request/condition histories without adding fake activity units. A staged argmax-only Jev observer distinguishes record support, undertaking identity and term changes; the CLI defaults to cached replay and validates historical state and version integrity. Airline and retail exports retain 9/12 changes and 50/37 original cards. The two earlier trials are replayable; integration adds no model calls. One likely retail false rejection remains explicit, and the observer is experimental rather than a direct drift metric. The full Python run passed 982 tests, subsequent targeted integrity checks passed, and live desktop/mobile navigation passed. Active-goal identity, independent semantic accuracy, approach discovery and training-wide semantic coverage remain unfinished. [Contract, known failure, cost and evidence](../research/request-changes-v2-2026-10-09/README.md). The full goal remains active.

**Implementation — adaptation at recurrence, 9 October:** The investigation page now cross-tabulates exact-pair procedure comparisons with the location of linked correction attempts. Pooled counts and equal-weight rollout shares preserve unknowns and source drilldowns. Two persistent software monitors track same-procedure resumption after separate preparation and the fraction of compared recurrences with changed procedure. Seventeen public episodes and sixteen saved authored controls replay without new inference; the actual `alternative_procedure` option is no longer lost to a consumer naming mismatch. Nine new tests and the full 971-test suite pass. These are recorded adaptation patterns, not validated exploration, goal drift or recovery; broader approach identity, independent accuracy and semantic training coverage remain unfinished. [Contract, audit and limitations](../research/adaptation-patterns-2026-10-09/README.md). The full goal remains active.

**Implementation — work-level navigation, 9 October:** The same rollout page now switches between named work visits and the complete unit map. Positive identity links support consecutive-attempt grouping; separate visits, recorded order, scope/Plan membership, returns and correction attempts remain distinct. All 57 actions across software/airline/retail examples remain reachable, with 28/18/6 visits, source witnesses and original graph identities. Cached projections add no inference. Browser testing repaired inspector overlap and misleading lines through unrelated cards; geometric path checks, existing scope navigation, eight layout tests and all 962 Python tests pass. This exposes recorded work structure; approach novelty, goal drift and semantic accuracy remain unproven. [Audit, contract and remaining requirements](../research/work-navigation-2026-10-09/README.md). The full goal remains active.

**Implementation — separate repair-phase baseline, 8 October:** Added an explicitly scoped, deterministic action/history phase observer, independent of base semantic activities. Three released Graphectory examples contain 103 action events; 100 are classified, three stay visible as gaps, and 95 comparable labels agree with the generated release graphs. This is compatibility evidence, not independent accuracy. Investigations retain versioned cached projections, equal-weight rollout shares, complete phase-block paths and exact source links. The report-generation example cannot activate this repair-specific profile. All 954 Python tests and the new browser workflow pass, with no model calls. General semantic phases, validated diagnosis and training-wide coverage remain unfinished. [Contract, audit and limitations](../research/task-phases-2026-10-08/README.md).

**Implementation — persistent expressed work scopes, 8 October:** Saved request/Plan memberships now survive as explicit scope nodes and source/membership edges in the rollout graph, with unresolved status and decision evidence retained. The existing map adds a Requests & plans sequence above the complete unit canvas; a scope opens its source and contributing cards, and each unit links back. New scope nodes do not become fake activities or source-order steps. Software, airline and retail examples retain 3/4/5 scopes with 68/24/17 assigned contributions and no new inference. The 944-test suite, eight layout checks and live browser checks pass. These are expressed scopes, not validated task phases, goal drift or strategic preferences. The full goal stays active. [Architecture and limits](ARCHITECTURE.md#expressed-work-scopes-in-the-graph--implemented-8-october).

**Correction — activity sequences, 8 October:** Replaced the reported single-rollout alluvial chart with a labeled complete-sequence navigator. The projection now preserves base activities instead of merging Orient/Plan and Construct/Report; original unit/graph identities remain attached to every card. Population flows expose counts and complete sequences, stop padding after observation end, and limit transition tables to observed activities. Fifty targeted Python tests and both live process-browser checks pass, including reachability of all 68 units in the reported rollout. This is a presentation/aggregation correction, not a validated strategy or task-phase observer. [Findings and validation](MONITORING_WORKSPACE.md#activity-sequence-correction). The full goal remains active.

**Implementation — persistent analysis monitors, 8 October:** Episode and recorded-state projections now feed the ongoing monitor service. Eleven version-pinned measures cover recurrence patterns, exact-pair procedure changes, linked assessments/corrections, criterion recovery, delivery verification and input binding. Researchers can promote an investigation pattern with one click or configure a monitor; future saved observations materialize automatically. Every chart value retains its original projection, plan, graph and contributing cases. Ratios pool decidable opportunities and expose unknowns. Historical values remain inspectable after reannotation; new rollouts cannot silently use a retired extraction version. Live examples show five returns and eight correction-attempt recurrences sharing one cached projection, with no new model calls. Both stay outside training curves because their source lacks training coordinates. Also fixed unresolved check results entering delivery-verification denominators and refresh reads overlapping materialization. The 936-test suite and live browser workflow pass. Actual training annotation coverage, independent semantic accuracy, producer state capture, discovery and evaluated guidance remain unfinished; the full goal stays active. [Implementation contract and receipt](MONITORING_WORKSPACE.md#persistent-analysis-measures).

**Implementation — connected work episodes, 8 October:** Investigations now group positively linked recurrences and retain intervening operations, feedback, assessments, attempted corrections and named plan stages. Independent method judgments apply only to their inspected pair. Gaps remain gaps; later identity disputes cannot rewrite earlier episodes. Focus/reference charts, evidence cards with directed links, five selectable recurrence metrics, exact full-rollout drilldowns and plan replay share one immutable projection. Source-reviewed examples cover software (10 recurrences; seven with recorded assessments, eight with attempted corrections) and airline workflows (six recurrences). These are inherited semantic observations, not independent accuracy or recovery measurements. Two plans replay 12 cached nodes with no computation or inference. The broader goal remains active: actual state capture, reviewed task-purpose/strategy abstractions, held-out accuracy, recurring training integration, discovery and feedback evaluation remain required. [Implementation and validation](../research/strategy-profiles-2026-10-08/README.md#connected-work-episodes-and-integration).

**Implementation — ordered investigations and recorded work state, 8 October:** Investigations now include count-preserving focus/reference activity flows, intersectable ribbon witnesses, transition comparisons and complete-rollout links. Source gaps and ambiguous batches break paths; observation end is not termination. A separate recorded-work-state graph stores file views, producer snapshots, check-input/result bindings and edit effects. Recovery and delivery-verification opportunities preserve unknowns and reject changed criteria, future evidence, unlinked edits and contradicted check stability. A bounded typed analysis DAG caches each projection/comparison, with inspectable plans and repeatable API execution. Four real investigations replay 30 nodes with zero recomputation or model calls. The public-source audit finds 45 complete numbered file views and two supported pytest checks across 16 convenience samples, but **zero captured test-input snapshots**; their version-aware recovery remains unknown. Authored capture-contract tests establish software behavior, not independent annotation accuracy. The renderer is activity flow; a reviewed task-purpose observer, general semantic revision/assessment lifecycles, discovery and intervention evaluation remain unfinished. [Implementation scope, evidence, API and validation](../research/strategy-profiles-2026-10-08/README.md#implemented-process-investigation-foundation). The broader goal remains active.

**Integrated priority — evidence-grounded investigations, 8 October:** Adopt the referenced architecture plan by completing one useful investigation before expanding the chart catalog: **failure → relevant edit → recheck → result → submitted artifact**. Preserve the coherent semantic units and work relationships; add versioned domain objects and execution evidence so a repeated command can be distinguished from a retry after a relevant change, and a historical pass from a check applicable to the submitted state. The current verification projection explicitly records artifact versions as unrecorded, so these conclusions are not available yet. Implement the associated episode/phase views inside the existing Investigation workspace. Then generalize the working recipe into composable, cached analysis plans over existing jobs; add discovery/review and promotion to monitors; evaluate feedback in shadow mode before intervention trials. Learned strategy models follow only where task-family evidence supports them. This supersedes the chart-first order below without removing sequence or opportunity analysis. [Integrated build order, contracts and acceptance criteria](../research/strategy-profiles-2026-10-08/README.md#integrated-implementation-decision). This update changes the plan and architecture documentation only; the new capabilities are not implemented or validated. The full goal remains active.

**Priority correction — sequence and opportunity analysis, 8 October:** The latest paper/code review identifies a missing layer between saved unit graphs and population metrics. Prioritize ordered, gap-preserving behavior projections, contextual task phases, and explicit opportunity lifecycles. Activity composition alone is not strategy; whole-rollout correlation does not localize a failure. Add count-preserving focus/reference phase flows and transition differences within the existing investigation, then feedback uptake, verified same-goal recovery and outstanding required verification with exact witnesses. Keep base activities, phase purposes and evidence relationships separate; retain Jev raw argmax and deterministic reuse. The read-only audit finds orderable units in 18 selected saved graphs, with one incomplete record-coverage case; it does not validate semantics or establish representative training behavior. [Method correction, contracts and implementation order](../research/strategy-profiles-2026-10-08/README.md#method-correction-after-the-two-paper-review). This is a research/specification update; the new renderer and general lifecycle engine are not implemented. The full goal remains active.

**Current progress — first strategy-profile layer, 8 October:** Prioritize the strategy-profile design; Jev workflow-correction repos are supporting references. Overview now includes versioned failure/adjustment/retry and closed-window feedback profiles, with cohort/observer separation, per-rollout values, real-step aggregation, unresolved coverage and exact-graph episode drill-down. Raw-source review caught false identical-dispatch labels caused by unavailable `{}` arguments; version-14 measurements append the correction without rewriting prior evidence. The software example has eight linked adjustment/retry episodes, 2/6 known operation outcomes completed and two unknown outcomes; native dispatch comparison is unavailable. No new inference calls. 861 Python and seven map-layout tests pass; semantic accuracy is not thereby established. Approach identity/search breadth, independently reviewed recovery and matched training trends remain unfinished. [Implementation, evidence and next steps](../research/strategy-profiles-2026-10-08/README.md#first-implemented-slice). The full goal remains active.

**Direction update — strategy profiles, 8 October:** Add a higher analysis layer for recurring, context-conditioned working styles: failure response, search breadth/persistence and feedback-to-action patterns first, with verified effectiveness measured separately. Profiles aggregate evidence-linked episodes; they do not add personality labels to base units or relax the coherent-unit standard. OEB is close prior art for graphs, opportunity metrics and persona profiles, so these are not uniqueness claims. Its implementation was inspected at a pinned commit; its scored runs have not been reproduced. The [design and implementation order](../research/strategy-profiles-2026-10-08/README.md) specify per-rollout/training aggregation, unknown coverage, Jev raw argmax and inference-cost constraints. This is a direction update, not an implemented or validated profile feature. The full goal remains active.

**Current progress — first matched-task semantic training pilot, 8 October:** Sixteen real CHERRL generations at logged steps 50 and 140 now have 49 selected units and readable contents under one registered experimental observer. Non-generative and Luna whole-task boundary failures are retained. The optional within-task boundary/activity contract removes three false Plan labels, with 8/8 authored contrast controls matching; real final creation-versus-delivery ambiguity and missing work/version relationships remain explicit. A deterministic control finds 18/20 quoted word-count claims wrong despite all 16 final notes meeting the length limit, demonstrating why checking frequency, check correctness and final outcomes must be separate. No new frequency monitor is enabled. Collection registration freezes compatible protocols and all source/map bindings; the map selector distinguishes repeated tasks and hides unused lane columns. The full-suite check exposed and repaired a frozen-clock metric-ordering failure. [Pilot, costs, retained failures and next work](../research/training-semantic-pilot-2026-10-08/README.md). The broader goal remains active; independent accuracy, complete relations and production-scale inspection remain unfinished.

**Live-monitor reliability follow-up, 8 October:** Restart verification caught schema-13 filtering of older saved metric records: the compatible migration was only reached by the legacy report. The main monitor refresh now appends compatible extensions directly, preserving original records, source bindings, graph identities and observation ordering. The live dashboard again shows 3,072 rewards and its saved behavioral examples. Both startup-migration and newer-observation-precedence regressions pass; the full suite is now 831 tests. No model calls were needed. [Receipt and verification](../research/adjustment-effects-2026-10-08/README.md#dashboard-upgrade-regression-found-during-live-verification). The goal remains active.

**Current progress — correction effects and return references, 8 October:** The new local effect observation separates an operation that makes a correction from one that describes using a separately corrected input. It preserves all units/declarations and removes the two reviewed e86/e95 scope errors, including the false e96 correction-attempt edge. A separate reference selection over saved work/action candidates links resumed conversions to Pandoc installation, TeX installation and the image-path edit; it rejects the unrelated earlier repair for a future prerequisite. These are source-attributed references, not verified repair or task recovery. 27/28 authored controls match, with a quoted/denied attribution failure retained. The real effect/reference extension used 143,121 input and 4,318 output Jev tokens, excluding upstream costs; zero Luna calls. Eight existing retry episodes and their 2/6 known-outcome completion ratio remain unchanged; no monitor is enabled. All 829 Python tests and five map-layout checks pass. [Evidence and next work](../research/adjustment-effects-2026-10-08/README.md). General extraction, independent semantic accuracy, useful training curves and product maturity remain unfinished; the goal is active.

**Current progress — preserve meaning between layers, 8 October:** The correction-content protocol now retains each selected work declaration instead of competing with its temporal/report status. All 60 software items replay, including ten unchanged completion claims in the final summary. Two earlier attribution controls pass; new authored contrasts match 17/18, with a missed upstream contradiction. Two real scope errors remain and are flagged; one adds an erroneous local-action link but neither changes this sample's eight metric episodes. Added a generic audited registry command and separate declaration/content labels in the existing map; no new monitor is enabled. Software usage is 114,155 input / 3,250 output Jev tokens, excluding upstream costs; no Luna calls. [Review, receipts and next decision](../research/adjustment-facets-2026-10-08/README.md). The full goal remains active and semantic accuracy remains unproven.

The same observer now retains all 30 audited work-history relations and 64 action/work relations. Four final-report claims connect back to prior work, with their natural-language scopes visible in connection buttons; unlinked claims remain unlinked. Old snapshots keep their earlier projection. All 823 Python tests, five layout checks and zero-call replay pass; live navigation from a final claim to earlier construction and back was verified.

**Current progress — reusable local adjustments, 8 October:** Reused 60 extracted work items in 35 software contributions, classified their adjustment status once with Jev raw argmax, and composed existing work/action/result connections without further inference. The incremental pass used 119,915 input tokens versus 484,707 for the earlier pairwise pass (75.26% less; upstream costs excluded). The optional observer finds 2/6 completed retries with known outcomes plus 2/8 unknown outcomes; this is a changed observer on the same trace, not a training gain or verified task recovery. Three scope errors improved, two final-report labels regressed, and an external-actor control still fails. Raw choices and review notes remain visible, monitors start disabled, and general semantic accuracy is unproven. Added a reusable budgeted/resumable CLI and zero-call audit; no Luna calls. [Review and evidence](../research/local-adjustments-v2-2026-10-08/README.md). Next work should remove redundant temporal/status classification and evaluate independent held-out cases before production promotion. The full goal remains active.

**Current progress — behavior monitor usefulness and operating cost, 8 October:** Fixed 18 empty tool-message wrappers in the airline map's projection, retaining all source data. Added conditional same-work retry measurements with explicit changed/unchanged payloads, known/unknown outcomes, evidence and opportunity-weighted aggregation; enabled changed-retry completion, direct feedback assessment, and Plan-stage attempt monitors. Current examples show 3/3 changed retries completed and 28/52 decidable feedback assessments, not validated training trends. A reproducible Luna payload budget estimates about $20k per million similar 19-agent-unit rollouts before reasoning, retries and Jev; actual subagent billing remains unavailable. Prefer deterministic extraction, bounded Jev selections and selective metered proposals. Docent/Scout feature parity and superiority are not established; the differentiated direction is reusable relational behavior monitoring. [Research, evidence, cost and next work](../research/behavior-monitoring-review-2026-10-08/README.md). The full goal remains active.

**Current progress — source groupings and complete transfer extraction, 8 October:** A bounded non-generative candidate builder offers complete adjacent paragraph groupings while protecting code payloads. Jev agrees with 47/59 existing development partitions (11/16 challenging cases); these assistant-authored references do not establish accuracy. On a new public Nebius software trace, the authorized Luna proposer and Jev now select all 21 local units and readable contents, including all nine agent dispatches, after retained citation/content repairs. The experimental map displays 30 cards, 18 source-identity links and four visible source-review notes. Invalid candidate responses remain in the active repair queue; no confidence threshold is used. 786 Python tests, 24 map tests and zero-call raw-maximum replay pass. Boundary/activity adjudication, independent semantic accuracy, complete work relationships and semantic training curves remain unfinished. No new population monitor is enabled. [Evaluation, map and next work](../research/global-source-partitions-2026-10-08/README.md). The full goal remains active.

**Current progress — non-generative candidates evaluated before Luna, 8 October:** Deterministic boundary-site candidates cover all 59 prose regions in three development maps, but a source-only Jev endpoint selector matches only 8 of 16 frozen challenging partitions. A subsequently authorized Luna subagent supplies global alternatives; Jev matches 10 of 16, with or without generated descriptions. Misbound descriptions remain accepted in two concrete cases, so neither partition trial is promoted. Seven isolated local-content proposals pass source checks and are selected, supporting a narrow role for generation after units/activities are established, not full extraction accuracy. Exact replay and 35 relevant tests pass. Coherent grouping, independent review, complete relationships and training-stream semantic observations remain unfinished. [Evaluation and source evidence](../research/nongenerative-candidates-2026-10-08/README.md).

**Current progress — direct feedback observations with full denominator, 8 October:** A budgeted source-based worker measures expressed tool-feedback assessment without generated semantic candidates, retaining positive, absent and unknown opportunities and source-event relationships. Drilldown lists every group while retaining the full rollout. The first 41-group public pass failed source review by missing success assessments; it is retained for audit and rejected for new monitors. The revised finite-choice harness has now completed six public traces after provider recovery: 53 response groups with two disagreements against frozen implementation-assistant expectations. It remains experimental and disabled as a main-dashboard monitor; independent accuracy is not established. Independent SQL reconciliation and isolated browser QA pass. General extraction and reliable population behavior curves remain unfinished; the goal is active. [Contract and remaining work](FEEDBACK_ASSESSMENT_MONITOR.md).

**Current progress — measurement-to-evidence integrity, 8 October:** Chart and case links now pin immutable measurement values and their original graph/source versions. The full map explains numerator membership, inspection windows and stored witness paths while retaining every card. Five of the software example's nine inspection anchors have no recorded match and remain unestablished, not behavioral negatives; an independent SQL join reconciles the four recorded matches. New semantic metric records preserve exact graph bindings without duplicating unchanged observations when only derived display metadata changes. 759 Python tests and browser checks pass. This closes a measurement drilldown defect; general automated extraction, independent semantic accuracy, relation opportunity coverage and genuine semantic training curves remain unfinished. [Evidence and architecture](MONITORING_WORKSPACE.md#saved-measurements-linked-to-exact-evidence). The full goal remains active.

**Product correction — population monitoring first, 8 October:** The main workspace is now Overview → Monitors → Rollouts. Persistent monitor definitions produce versioned values for every current rollout, with numerator, denominator, source/observer identity and missingness retained in SQLite. The application service checks for saved input changes every five seconds without a browser request or a paid model call. Overview displays multiple charts together; researchers save explicit relationship questions as recurring measures and open contributing rollout cases from figures. The default rollout map retains the whole trace when a card is selected, combining units, named plan stages, actions, feedback and recorded connections with zoom, search and a trace navigator. Legacy point-focused maps and query tools are under Data & tools. This is a monitoring workspace implementation; it does not establish semantic accuracy or fabricate relationship curves for the 3,072 training generations that lack semantic observations. The full goal remains active and incomplete. [Implementation and verification](MONITORING_WORKSPACE.md).

**Current progress — connected graph requirements, 8 October:** Persistent rollout graphs now support researcher-defined evidence paths of up to three directed relationship hops, with exact witness cards and saved versioned definitions. On the unchanged software source, requiring an assessment to reference its inspection's returned feedback reduces fifteen temporal matches over six inspection anchors to four connected matches over four anchors (nine eligible anchors). This is a query-definition distinction, not a model improvement or semantic accuracy claim. Source-order and cutoff checks exclude future/unresolved objects, and search exhaustion cannot become a negative measurement. New-direction evidence, complete revision coverage, independent annotation accuracy and a real relation-aware training comparison remain unfinished. [Source pairs and reproducible query review](../research/graph-evidence-paths-2026-10-08/README.md). The full goal remains active and incomplete.

**Current progress — operation evidence for named work, 8 October:** Four result-reader variants were evaluated on 26 frozen authored contrasts and all 39 result rows in the software map. Reusing the existing operation observer resolves the stored-log/read distinction; selectively inspecting unestablished responses corrects one command-echo result, while missing media prevents an unsupported absence claim. The final experimental observer retains four source-review flags and a failed relay/refund control. Repeated identical API packets also changed the raw winner on that control, so exact cached replay must not be confused with fresh-call semantic stability. Separate result workspaces preserve older maps; the inspector now exposes operation evidence and caveats on the same cards. The default protocol remains unchanged, no new macro rates are promoted, and independent accuracy remains unmeasured. 705 software tests pass. [Experiments, counterexamples and next work](../research/work-material-2026-10-08/README.md). The full goal remains active and incomplete.

**Current progress — budgeted diagnostic stream monitoring, 8 October:** `monitor-rollouts run/watch/status/audit` now follows latest completed imports with immutable source/protocol identity, resumable decision budgets, failure isolation, explicit retries and atomic measurement publication. The dashboard separates complete, pending, failed, waiting and ineligible populations. A real four-source run stopped after one request, resumed to three completed inspections plus one retained HTTP 400 failure, then reused results with zero new calls. A zero-call population scan reused three existing observations and excluded 3,072 flattened generations plus four oversized sources instead of recording false negatives. This is operational monitoring infrastructure, not independent diagnostic accuracy or complete automatic macro annotation. Long-source processing, semantic extraction quality and validated macro behavior remain unfinished. [Workflow and evidence](../research/diagnostic-stream-2026-10-08/README.md). Full goal remains active and incomplete.

**Current progress — diagnostic evidence roles and source order, 8 October:** An optional versioned source diagnostic now selects lookup/target, returned-material/incorporation, access/boundary and manipulation/mechanism evidence separately, then validates the relationship. It repairs a source-label splitter that merged returns with later actions, identifies and resolves a tested provider token-limit failure without dropping source text, and fixes JSON round-trip replay while preserving prior hashes. All 16 original controls and seven of eight new authored contrasts match; one temporal/source-type case remains unresolved or incorrect. Targeted real-source review removes one speculative history-search flag and locates two precise patch-to-edit pairs. These are development results, not independent accuracy. A new observer is available in the existing rollout dashboard; no new base activity tags or invented training coordinates were introduced. [Evidence and remaining work](../research/diagnostic-monitors-2026-10-08/chains-review.md). Full goal remains active and incomplete.

**Current direction — direct diagnostic monitoring, 8 October:** Add versioned rollout-level diagnostics over raw trace evidence and, where reliable, the neutral unit/target/result map. Separate answer acquisition, reuse, evaluation interference, task-contract violations and demonstrated reward exploitation. Six experimental source-only Jev monitors now produce numeric values or explicit unknowns with exact raw-maximum replay; two imported SWE-agent runs are visible in the existing rollout dashboard. Sixteen authored contrast cases and twelve public heuristic-selected traces expose unresolved boundary errors, so these are not validated cheating metrics. Base-layer accuracy remains unfinished, and map-dependent diagnoses must wait for their required correspondences. Next: independent contrast evaluation, explicit evaluator/task boundaries, precise retrieval-to-use links and reward/validity evidence, then ingestion-worker integration. [Research, implementation and retained failures](../research/diagnostic-monitors-2026-10-08/README.md). The full product goal remains active and incomplete.

**Current progress — actual per-rollout training coordinates, 8 October:** The application now contains 3,072 public Qwen3-4B completions across six complete training batches, with each record's source-logged iteration, score, immutable file hash and line identity. A reusable verl-generation adapter keeps evaluator material outside behavior events and does not invent tool structure or generating-policy IDs. The training chart exposes every rollout, preserves missing iteration ranges, opens exact source text and paginates the list. Source scores and character counts reconcile against every downloaded record; existing semantic/operation measurements migrate additively to the new metric schema. This is sparse source-level coverage, not automatic semantic annotation of the training stream or independent accuracy. Stable semantic protocols across rollouts, validated current Plan/accepted-result relationships, general candidate generation and independent transfer evaluation remain incomplete. The full product goal remains active. [Evidence](../research/training-rollouts-2026-10-08/source-review.md).

**Current progress — statements connected to dispatches and results, 8 October:** An additive observer now connects the software trace's 30 selected work histories to concrete actions, their bound responses and independently selected Plan-stage links. All 33 dispatches were inspected against 382 prior work instances. The retained first pass made backward-dependency and wrong-package matches; explicit ordered-pair options plus source-bound earlier dispatch context reduce its 91 links to 64 in the reviewed version. Eleven of twelve authored probes match; one preparation-scope error and three real output/implementation scope reviews remain visible. This is not independent accuracy. The same map focus includes later actions/results without changing the 101 unit cards. 660 Python tests and 25 map checks pass. Active intention, accepted completion, general candidate automation, independently validated transfer and genuine rollout training coordinates remain incomplete. No strategy or completion rates are added from these development links. The full goal remains active. [Evidence](../research/declared-actions-2026-10-08/source-review.md).

**Current progress — complete local work statements and selected histories, 8 October:** An additive observer retains the software trace's 101 original unit cards and inspects all 35 agent prose units, selecting 60 readable work items before resolving their histories. The revised identity pass produces 30 records and 30 temporal links. It separates Pandoc installation, PDF conversion and image-path repair; the earlier pass that merged these remains saved and is not published. Four remaining scope questions are visible review notes. Both local and history passes replay with zero new requests. The browser focuses the same cards and intervening work, distinguishes multiple work relations between the same units, and exports the exact audited observation. 654 Python tests passed before final targeted catalog/review checks, which also pass; four blueprint checks pass. Candidate proposals and source reviews are authored development material, not independent accuracy. Current pursuit, correspondence to action instances and Plan stages, accepted completion, unattended candidate generation and actual training-coordinate rollouts remain unfinished. The full goal remains active. [Evidence](../research/work-items-complete-2026-10-08/source-review.md).

**Current progress — reusable per-rollout operation monitoring, 8 October:** A shared observation protocol now runs across normalized imports through `outcomes run` and follows newly completed imports through `outcomes watch`. Source/configuration identity, raw argmax replay, interrupted execution, process-wide request budgets, rejected wire responses and atomic observation/metric registration are covered by six workspace tests. A new public SWE-agent trajectory produced eight inspected response pairs (seven completed operations, one rejected edit); its ninth dispatch has no linked response and is displayed outside the outcome denominator. The run stopped after two requests, resumed for 22 and replayed with zero new calls. The existing Behavior maps and ten semantic measurement versions remain available. No complete semantic map or recovery relationship is invented for this operation-only pass. The full suite passed 644 tests before the final watcher test, which also passes. Next connect reusable complete semantic extraction and selected histories to a stable cross-rollout observation protocol, establish supported active Plan/outcome relationships, and obtain genuine per-rollout training coordinates. Independent accuracy and real training trends remain unmeasured; the full goal remains active. [Workflow and evidence](SEMANTIC_WORKSPACES.md#operation-observations-across-rollouts).

**Current progress — scoped outcomes across repeated work, 8 October:** Three additive observers now inspect all 57 source-bound responses in the software, airline and retail maps. They connect five later completed operations to already-observed failed operations on the same selected target: two software transitions and three airline bookings. The original units and previous observer exports are unchanged. Silent conversion, warning-only output and uninspected image evidence do not become successful execution or Plan completion. Four rollout metrics retain terminal-call denominators and unknown coverage. Early generic outcome classifiers repeatedly mistook stored error text for a failed read; the retained final pipeline first selects operation mechanism and current executor-error attribution, then chooses raw argmax among compatible outcome options. Sixteen reused development probes pass; independent accuracy remains unmeasured. 639 Python tests and 22 Node checks pass. Active Plan adoption, stage acceptance, general extraction automation and actual rollout-by-rollout training evidence remain required. The goal remains active and incomplete. [Evidence and boundaries](BEHAVIOR_MAP_INTERFACE.md#scoped-operation-outcomes-and-repeated-work).

**Current progress — Plan stages connected to observed work, 8 October:** The same Behavior map now shows stage cards, declared ordering, observed stage changes and the original actions/results beneath them. A new additive software observer inspects seven stage-product responses across two Plans and three stages. The report Plan has twelve linked dispatches and one observed Markdown→PDF stage change; its earlier Markdown response is visible at the transition cutoff. The PDF filename remains a reference, not inspected PDF contents or verified completion. Four new per-rollout metrics retain coverage and unavailable outcomes. Twelve authored development controls pass after a preserved scope-boundary failure; independent accuracy remains unmeasured. The full Python suite passed 632 tests, with one additional targeted Plan test and all 22 Node checks passing. Browser navigation and the native export agree with the saved source projection. Next establish supported stage outcome and active-Plan history before completion, deviation or recovery measures; continue obtaining real training-coordinate rollouts and automating complete semantic passes. The full goal remains active and incomplete. [Contract and evidence](BEHAVIOR_MAP_INTERFACE.md#plan-stages-and-observed-work).

**Current progress — executor reports connected to returns, 8 October:** An additive observer now annotates 57 source-bound responses across the real software, airline and retail traces and adds 11 temporal target-return connections after error reports. The same cards, source evidence and original activities remain intact. Per-rollout measurements include report coverage, error/warning report fractions, unknown evidence and return counts. Handled component errors, warning-only conversion output and informational notices remain distinct; no whole-action failure or recovery is inferred. Earlier failed harness versions and the unchanged original map exports are retained. The final development pass matches 18 authored probes and the implementation assistant's source review; independent accuracy is still unmeasured. 627 Python tests and 21 projection checks passed. Next connect scoped outcome evidence to work/Plan stages, then establish supported completion/next-stage transitions and obtain real rollout training coordinates. Unattended general semantic extraction and the full product goal remain incomplete. [Evidence and contract](BEHAVIOR_MAP_INTERFACE.md#executor-reports-on-the-same-cards-and-connections).

**Current user direction — visual blueprint and every-rollout statistics, 8 October:** A card-and-line layout now exposes original activity units, Plan contents, typed connections and response evidence within the existing map. The rollout metric layer records each imported snapshot and adds saved semantic-map measurements, with individual rollout points and training-step distributions. It does not require checkpoint snapshots. All 16 current rollouts are measured at source level; three have semantic metrics, and none has explicit training coordinates. Macro exploration/deviation/recovery/completion labels, a real training stream, consistent batch observer protocols and unattended semantic extraction remain unfinished. 622 Python and 21 projection tests pass, with browser checks and an isolated chart fixture. The product goal remains active. [Measurement contract](DIRECTION.md#rollout-first-measurement-contract).

**Current extraction finding — local work objects before histories, 8 October:** Two experiments that reuse a contribution's generic target as a work-history object fail on real sources: communicative targets become completion claims, and whole tasks merge with narrower stages. They are not promoted. A replacement local candidate contract keeps one unit/activity while naming several source-attributed work items when needed. Its described-candidate pilot selects the authored choices on eight reused examples; an earlier retail expectation was itself incomplete. This is not independent accuracy or whole-trace coverage. All live maps remain unchanged. Next complete local work-item extraction and candidate generation before work identity, history updates or active-goal metrics. The product goal remains active and incomplete. [Results and limits](SEMANTIC_EXTRACTION_WORKFLOW.md#local-work-objects-before-history).

**Current progress — returning sequences in one map, 8 October:** The macro layer now connects earlier and later multi-target sequences across intervening work, with original units, request changes and exact-pair procedure evidence in the shared inspector. The real airline searches at positions 3–4 return at 8–9 under changed requested terms; 21 original units remain visible. Prior projections/exports remain identical, the new browser export is reconciled, and 601 Python plus nineteen UI checks pass. Source consistency is not independent semantic accuracy. Reliable active-goal/Plan/result histories, unattended candidate generation, independent transfer evaluation and semantic checkpoint/strategy analysis remain unfinished. The full goal remains active. [Evidence](BEHAVIOR_MAP_INTERFACE.md#sequences-that-return-after-intervening-work).

**Current progress — repeated-work macro projection, 8 October:** The single Behavior map now summarizes consecutive repeated target sequences and opens their unchanged units, reasoning and feedback. A shared exact-sequence kernel detects the real ALFWorld four-command/six-copy example missed by adjacent recurrence, in a separate versioned checkpoint study. Missing observations and disputed identity remain explicit; no exploration, exploitation, deviation or failure cause is inferred. Original maps, registered observers and prior studies remain preserved. Independent semantic accuracy, spaced patterns, active goal/Plan/result histories, candidate automation and strategy-level RL comparisons remain unfinished. The full goal remains active. [Evidence](BEHAVIOR_MAP_INTERFACE.md#repeated-work-sequences).

**Current progress — reproducible checkpoint investigations, 8 October:** The main application now contains the pinned three-policy ALFWorld study (384 episodes, 91 matched games, 12,592 recorded steps). Saved investigations preserve an exact comparison, selected raw episodes, filters and note with content identities; reopening uses that frozen evidence. The browser attachment failure is repaired with a server download. Source-only comparisons and semantic Behavior maps remain distinct research scales. Missing native observations prevent feedback-sensitive explanations; no new semantic accuracy or training-causality claim is made. Independent fresh-source annotation, candidate automation and reliable goal/Plan/result histories remain required. The full goal remains active and incomplete.

**Current progress — reusable extraction and map registration, 8 October:** The staged extractor now has public prepare/run/status/audit/register commands, source-bound settings, process-owned locking, response retention and database-backed registration of complete maps. A clean-database integration exposed and fixed a bundled-source assumption. The existing real software observation survives registration and native export exactly; a complete SWE RL source queues 137 regions without inventing candidates or labels. 577 Python tests and seventeen map checks pass. A callable generative endpoint is not configured, so fresh semantic output and independent accuracy remain unproven. The original macro/product goal and its goal/Plan/result-history, transfer and matched-checkpoint requirements remain active and incomplete. [Workflow](SEMANTIC_WORKSPACES.md).

**Current progress — procedure versus context, 8 October:** Seventeen recurring-work pairs now have source-bound method/configuration comparisons and separately attributed agent explanations in the combined map. Three versioned trials preserve failures and refinements; original units, targets and work histories remain unchanged. Live source/export checks pass, with 571 Python and seventeen Node checks. Independent semantic accuracy, real alternative-method coverage, reliable goal/Plan lifecycle, candidate automation, practical scale and matched RL comparisons remain incomplete. [Evidence](BEHAVIOR_MAP_INTERFACE.md#procedure-comparisons-within-recurring-work). The full goal remains active.

**Current progress — shared work history, 8 October:** The single Behavior map now includes source-bound histories of requested work and conditions, linked to previously selected dispatch roles. Retail and airline preserve per-item identity and earlier terms; software history is explicitly unavailable until requested-work records are selected. No new model calls or semantic claims arise from the projection. Browser/export and 558 Python/sixteen Node checks pass; independent accuracy, reliable goal/Plan lifecycle, method changes, unattended generation and matched RL comparisons remain required. [Evidence](BEHAVIOR_MAP_INTERFACE.md#persistent-work-inside-the-combined-map). The full goal remains active and incomplete.

**Current progress — 8 October:** The airline map retains all 25 agent contributions and adds five coherent user contributions, eight request/condition records and nine version changes. E27’s feasibility proposal remains distinct from e29’s three-booking authorization; e24’s dispatch snapshot excludes later terms. Recurrence comparisons now expose changed requested versions in three lookup/search intervals and unchanged versions in three booking intervals. Six historical prerequisite links remain disputed and cannot establish active intention. The source protocol marker is explicitly outside semantic scope. Native export now downloads the complete audited observation and rejects stale bindings. [Evidence and limits](BEHAVIOR_MAP_INTERFACE.md#requested-scope-across-recurrence). Independent semantic accuracy, active goal/Plan histories, result-instance scope, unattended generation, scalable retrieval and actual RL comparisons remain unfinished. The full goal remains active.

**Interface constraint:** Treat semantic contents, action characteristics, relationships and derived work groups as levels of one connected representation. The user supplied possible inspection needs, not a requirement for five peer maps. Present a single map with useful focus, history and evidence drill-down; add separate destinations only when a distinct research task justifies them. The current unit focus brings both directions of selected connections into the timeline, preserves the anchor and marks omitted units. [Current implementation](BEHAVIOR_MAP_INTERFACE.md). This presentation consolidation leaves the accuracy and RL research goal active and incomplete.

**Current foundation progress:** The development condition observer now preserves restrictions, requested checks and attributed claims inside readable versioned records. The missing e20 waiting restriction survives later updates with its original source; all 30 local contributions remain unchanged. Browser and exported map agree. Eight authored contrasts and 472 software tests pass, without establishing independent semantic accuracy. The next layer is specific requested-check-to-action/result correspondence, followed by real software/Plan transfer. Unattended candidate generation and actual RL comparisons remain incomplete. [Evidence](SEMANTIC_EXTRACTION_WORKFLOW.md#retained-conditions-requested-checks-and-attributed-claims). The full goal remains active. Earlier progress entries below are historical.

**Current action connection:** The retail requested-work map now has seven selected dispatch-to-work-version links. The source state at each dispatch is inspectable; later approval and action feedback are excluded from the correspondence decision. Existing base contributions are unchanged. Condition-specific connections, retained-condition accuracy, real software/Plan transfer, independent semantic evaluation, unattended candidate generation and actual RL comparisons remain incomplete. [Evidence](SEMANTIC_EXTRACTION_WORKFLOW.md#work-versions-connected-to-dispatches). The full goal remains active.

**Current foundation progress:** Local participant contents now precede versioned requested-work updates. One retail trace has 30 attributed contributions, four readable scope/condition records and 12 selected version changes; the app exposes state at each contribution and its exact evidence. The failed all-prior comparison graph is not promoted. User scope is distinct from model activity, attempted action and fulfillment. Condition completeness and action/version correspondence remain next, followed by software/Plan transfer. Authored candidates, independent accuracy and actual training comparisons remain unresolved. [Evidence](SEMANTIC_EXTRACTION_WORKFLOW.md#participant-contributions-and-versioned-requested-work). The full product goal remains active and incomplete.

**Method selection:** When a layer remains unsolved, inspect primary papers, public code and concrete examples from adjacent fields before another ad hoc prompt sweep or new model/API. [Current research](ADJACENT_METHODS.md) specifies which ideas transfer and which assumptions do not. Complete local contents before history relations; evaluate content, update choice and error propagation separately. Discuss any additional model/API before using it. This is part of the existing active goal, not a completed accuracy milestone.

**Latest complete-source progress:** The fresh retail source now has 18 selected coherent contributions with readable local contents and targets, six dispatch/result bindings and one repeated-work relation. Candidate readings preserve the source distinction between asking for authorization and reporting status; all old decisions remain available. The generic opt-in worker interface requests partition descriptions, then source-bound activity readings, then category-conditioned contents. The app marks old overlapping-tag/mention extraction views as historical and opens the current map for the selected rollout. Independent accuracy and unattended generation remain unproven. Next are supported user-request/authorization relationships and real plan transfer, before macro measures. [Evidence](SEMANTIC_EXTRACTION_WORKFLOW.md#complete-retail-contributions-with-candidate-readings). Full goal remains active and incomplete.

**Latest fresh-source correction:** The foundation remains incomplete. A new public retail record exposes fragmented units and request/Report confusion. Semantic boundary proposals now precede activity classification in the default extraction CLI; syntax-only candidate menus are retained only for legacy replay. One region remains unresolved, and the revised wording probe is not promoted after mixed results. Readable source-review targets show the intended useful history, including two distinct kettle occurrences with one item ID, withdrawn work, a failed attempt and approval without execution. Complete accurate local records before adding their relations or macro metrics. [Current evidence](SEMANTIC_EXTRACTION_WORKFLOW.md#fresh-source-boundary-failure-and-candidate-ordering). Full product goal remains active and incomplete.

**Latest connected-path progress:** The complete OpenHands record now has 23 source-ordered work paths covering all 33 dispatches once, with associated prose, responses, existing assessments and plan-stage references. The unchanged target observer first exposed a false merge between figures-only inspection and a broader directory/figures check; an explicit partial-scope relationship now preserves that distinction. The two known missing-identity pair controls also select unresolved under the revised contract. All eighteen authored scope contrasts match their development expectations; this is not independent accuracy. The airline replay retains its existing semantic relations. Browser navigation, plan-stage drill-down and downloaded path JSON are verified. [Evidence and remaining gates](SEMANTIC_EXTRACTION_WORKFLOW.md#connected-work-paths-and-scope-coverage). Full goal remains active and incomplete.

**Latest task-instance repair:** On the unchanged 25-contribution airline extraction, a separate pair-relation stage now retains six same-work links while distinguishing two calculation/booking pairs as different work on the same subject. Aarav and Evelyn's identical formulas no longer create a shared target. The failed intermediate observer is preserved. One missing-identity pair control still fails; candidate generation and reference expectations remain assistant-authored. The live map and downloaded JSON expose the observer version and source-bound meanings. Next priorities are missing-scope reliability and useful target/plan/review histories on another complete source, before macro metrics. [Evidence and limits](SEMANTIC_EXTRACTION_WORKFLOW.md#task-instance-identity-and-different-work). Full goal remains active and incomplete.

**Latest foundation repair:** Versioned context retention now supplies complete recorded system/developer instructions. On the airline source, all 24 local meanings remain unchanged under this context-only repair. A separately tested boundary observer recovers a distinct authorization request, yielding 25 contributions and eighteen action/result pairs. It preserves the user's whole Orient reference and other coherent controls, but the exact itinerary/request attachment differs from the frozen reviewer preference. All three observer passes are selectable in the same UI. No semantic target links are silently inherited by revised units; task-instance correspondence remains next. [Evidence and limits](SEMANTIC_EXTRACTION_WORKFLOW.md#retained-instructions-and-contribution-boundaries). Full goal remains active and incomplete.

**Latest cross-domain source review:** A complete public airline execution now has 24 readable agent contributions and 18 separate dispatch/result bindings under the same base activity definitions. Action-target paths show passenger-specific booking attempts and exact payment changes. The pass also reveals a wrong same-formula/different-passenger link, a Report/authorization boundary disagreement, and omitted initial policy context. These issues are visible in the map; no validated recurrence or compliance metric is claimed. Candidate generation and review expectations remain assistant-authored. See [airline target paths and source review](SEMANTIC_EXTRACTION_WORKFLOW.md#airline-target-paths-and-source-review). The next priority is those local scope/context errors, not additional macro labels. Full goal remains active and incomplete.

**Latest relation repair:** Response text now appears beside Jev's feedback-reference options, and joint reference is distinguished from an ambiguous single referent. On the frozen development set, exact matches against assistant-authored expectations move from 15/18 to 17/18 real cases and 11/12 to 12/12 controls. The real recurrence link is recovered; e50 now includes an older same-error response beyond the reference expectation and remains a disagreement. The current development map adds 34 source-record associations between contributions and dispatches, without claiming intent compliance. There are 18 assessment groups with 20 evidence edges. These are development results, not independently measured accuracy. See [feedback-reference repair](SEMANTIC_EXTRACTION_WORKFLOW.md#feedback-reference-evidence-and-source-pairing). Full goal remains active; the earlier whole-trace entries below retain historical results.

**Latest whole-trajectory progress:** The public DevAI/OpenHands record now has complete eligible-source coverage: 67 windows, 68 selected agent contributions, 33 separate dispatch/result bindings and readable category-conditioned contents. Whole-trace review exposes synthetic test data versus later GDSC claims, a PDF-content check announced but only a directory listing dispatched, and a stable installation target with changing methods. Search and connected-evidence views support inspection. Thirteen plan-stage links and sixteen feedback assessments are selected, but two obvious feedback references are missed and recurrence linking remains unstable. These are development predictions, not validated metrics. Candidate generation remains assistant-authored. See [whole-trajectory review](SEMANTIC_EXTRACTION_WORKFLOW.md#whole-trajectory-source-review). The full goal remains active; older progress entries below are historical.

**Current continuous-episode progress:** The public OpenHands reporting episode e65–e101 now has complete eligible-window coverage: 26 selected agent units across 25 windows, twelve source responses, twelve plan-stage links and nine feedback assessments (ten evidence edges, including a joint recurrence assessment). Draft framing and the final delivery summary are retained as coherent contributions. Explicit episode coverage is audited; narrow-panel unit inspection now opens directly. This remains one episode, assistant-authored candidates and unvalidated semantic judgments. See [workflow](SEMANTIC_EXTRACTION_WORKFLOW.md#continuous-reporting-episode). The full goal remains active.

**Current relation development:** The selected OpenHands sample now has ten local agent units, seven dispatch/result bindings and six Jev-selected links to specific Plan stages. Preparation, direct attempt and result checking are separate. The first pass mislabeled empty-file creation as attempting report writing; a narrower stage-scope contract selects preparation. Both versions remain saved. Eight authored role controls yield seven expected selections and one review-versus-preparation error. This is a nine-window development sample, not whole-trajectory coverage or proven semantic accuracy. See [the workflow](SEMANTIC_EXTRACTION_WORKFLOW.md#plan-stage-correspondence). The full goal remains active.

**Current foundation update:** Source-preserving readable context and exact quote citations now run through Jev. The same four-unit OpenHands development sample retained its selected meanings while reported input tokens fell 80.33% across eleven decisions. A configurable candidate process is implemented and tested, but a real generative service remains unconfigured. Context omissions are visible; incomplete reruns preserve the last complete map. 418 tests pass; no independent semantic-accuracy claim. See [workflow](SEMANTIC_EXTRACTION_WORKFLOW.md#readable-context-and-candidate-worker). The full goal remains active.

**Latest development evidence:** A real public OpenHands sample now has a selected mixed-message split, an organized two-stage Plan with readable targets and citations, a separate Orient correction, and a Construct dispatch linked to recorded feedback. Selected windows only; model-authored candidates and explicitly limited context; 407 tests pass, no independent semantic-accuracy claim. See [SEMANTIC_EXTRACTION_WORKFLOW.md](SEMANTIC_EXTRACTION_WORKFLOW.md#organized-plan-development-pass). Full product goal remains active.

**Current progress — executable local extraction:** [SEMANTIC_EXTRACTION_WORKFLOW.md](SEMANTIC_EXTRACTION_WORKFLOW.md) records the real telecom pass: 22 sentence fragments become five selected contributions with readable contents, preserving customer/agent attribution and visibility. Jev selects concrete partitions, one activity and coherent content bundles using raw argmax. Candidate handoff and resumption work; the candidate batch is model-authored, not unattended generation or independent ground truth. Relations, positive organized plans, broad transfer and RL comparison accuracy remain incomplete.

Revised by the user's instructions on 6 October 2026. This is the controlling interpretation of the active thread goal and supersedes narrower milestone priorities elsewhere in this repository.

**Build a highly accurate, adaptable foundation for observing model behavior in RL trajectories, so researchers can reliably develop higher-level understanding, tags, flags and practical training investigations from it. Deliver a mature, useful tracking tool grounded in real RL evidence and workflows.**

The eventual product should make macro behavior understandable first, with supporting detail available beneath it. The implementation must establish reliable local observations and relationships before claiming those macro interpretations. A working graph, a successful API call or a fixed taxonomy does not satisfy this goal.

## Required foundation

1. Cover model-authored messages and available reasoning text as well as tool/action dispatches. Preserve environment feedback, user instructions, context changes, artifacts and outcomes in their distinct roles. Missing reasoning is unobserved, not absent behavior.
2. Define useful annotation units with exact source references, boundaries, attribution, actor and temporal scope. Preserve mixed content and expose segmentation uncertainty. A tool call must not stand in for the full behavior expressed in its parent message.
3. Support multiple dimensions and levels without stacking competing labels for the same question on the same behavioral unit. Establish the meaningful unit of task work first; do not equate clauses, verbs or grammatical predicates with separate behavioral units. The user's latest reference classifies the entire decorator passage as one Orient unit, not a premise/proposal split and not Plan. Assess belongs to the relationship layer after units and local contents are established. The assistant's six-function replacement is withdrawn. Category-specific natural-language targets/content follow the base classification directly; grammatical attachment, canonical entity identity and relationships are not prerequisites. A parent category and its subtype count once. The proposed activities remain revisable, guided by concrete reference cases and useful distinctions rather than another invented ontology. See [ACTIVITY_STRUCTURE.md](ACTIVITY_STRUCTURE.md) for the controlling correction and attribution of the user reference.
4. Separate semantic activity, expression form, action type, objective/plan relationships and outcome evidence. Plans, hypotheses, attempts, assertions, reported success and independently recorded results must remain distinguishable. A next-step announcement is intended work, not sufficient evidence of plan organization or high-level planning. Observe organization and scope separately; build evidence-linked plan objects across expressions before measuring plan following or revision. Do not use the existing broad Plan count as a high-level planning metric. See [PLANNING_OBSERVATIONS.md](PLANNING_OBSERVATIONS.md).
5. Make core tagging semantics and harness contracts independent of any one RL framework. Harbor/SWE-agent are useful starting integrations, not the scope of the taxonomy or a programming-only behavioral model. Adapters translate source records and supply environment/tool evidence; they must not redefine the same activity label per framework. Environment families, source formats and action types are separate dimensions. Missing capabilities remain explicit.
6. Use Jev for bounded decisions among supplied alternatives, selecting the maximum-probability option for each question. Do not use confidence statistics, probability floors or winner-margin thresholds to accept, reject, retry or route the choice. Competing values of one dimension belong in one bounded choice, rather than independent present/absent questions. Independent questions are appropriate for distinct dimensions or distinct source-bound moves. Do not compare probabilities across the old independent questions to invent a primary tag. Unresolved, not-applicable and no-suitable-candidate remain explicit alternatives when appropriate and take effect when they win. Build and optimize segmentation, retrieval, entity/link candidates, tool context, definitions and question structure outside this selection rule. Evaluate those changes against reference annotations and downstream inspection usefulness; threshold tuning is not the optimization mechanism. Evidence completeness and link validity checks remain separate from selection and preserve the raw winning option; a missing input must not be disguised as a low-confidence decision.
7. Preserve versioned measurements, evidence packets, distributions, uncertainty and original source data. A unit's activity or role must use evidence available at that unit's cutoff. Later relationship questions can use their later cutoff, but must not silently reclassify the earlier unit using future evidence. Retrospective interpretations remain separate measurements. Taxonomy changes must be traceable; reprocess or bridge frozen data before comparing versions. Unknown labels must not silently become negatives.

## Accuracy and usefulness gates

**11 October retrieval validation:** Local feedback search now offers exact older source passages without a proposer model. The optional combined policy retains recent-three candidates, adds at most two older lexical matches, and exposes candidate coverage in the unit inspector. The 50-case development comparison improves complete target availability from 36/45 to 43/45 but retains three selection disagreements, including one regression; the same software questions use 66% more input tokens. It is not promoted to a default. All 1,185 Python tests and nine browser checks pass; old observers and 3,091 source rollouts remain intact. Airline/retail eligibility gaps must be addressed through the unit/content layer before claiming transfer. Continue broader semantic reference review and cost/representation tests; this is progress, not goal completion. See [the complete audit](../research/feedback-retrieval-2026-10-11/README.md).

- Audit extraction, attribution, segmentation, candidate availability, context sufficiency, classification and relationships separately, then evaluate the complete pipeline.
- Establish independent reference annotations with disagreement retained and adjudicated; keep model proposals distinct from human reference labels. Use grouped held-out data across tasks, producers and relevant environments.
- Demonstrate transfer of the same core definitions across reasoning-only, tool-use and interactive trajectories, including non-programming tasks. Evaluate at least a second producer and domain on held-out evidence before claiming generalization. Parser compatibility and relabeled copies of the same fixture do not establish semantic transfer. Specialized extensions may add evidence or tags without silently changing core meanings. Do not claim universal support for untested frameworks or modalities.
- Measure per-tag precision/recall, explicit unresolved choices, missing-evidence exclusions, coverage, relation accuracy and error in downstream aggregates. Report rare-tag support and relevant slices. Evaluate returned probabilities diagnostically if useful, without confidence-based filtering. Decide whether a measurement is fit for an investigation from independent validation and the consequences of its errors; do not claim high accuracy before measuring it.
- Validate macro patterns against complete trajectories and matched policy checkpoints. Test whether local errors, missing evidence, task mix or inspector changes can reverse a purported behavior shift. Frequency alone does not establish exploration, exploitation, deviation, adaptation, progress or failure.
- Demonstrate practical usefulness through trace-to-finding workflows, evidence and counterexample drill-down, reproducibility, correction burden, latency and cost. Compare the same investigations with manual/notebook, Scout and accessible Docent workflows.

## How to change the tag framework

The user clarified that tags may change whenever the current framework is inadequate for inspection or upper-layer analysis. This authorizes revising the design itself. It does not require a user-facing taxonomy editor, or adding labels simply to increase detail.

For each proposed change, identify the research distinction it enables and the evidence needed to observe it. Check whether the problem is actually a bad unit boundary, missing context or a missing relationship before adding a category. Keep distinctions that can be annotated reliably and used downstream; merge or remove distinctions that cannot. Represent coexisting work with distinct moves and separate dimensions. Unexplained same-dimension overlap is an annotation problem, not a useful structural representation. Separate expression form, action type and outcome evidence instead of forcing these into one label.

Evaluate changes on frozen development cases and then independent held-out cases across producers and domains. Preserve the previous definitions, units, evidence and predictions. Never interpret a difference caused by changing the taxonomy, segmentation or harness as a policy's behavior changing across training. Comparisons need a common reprocessed version or an explicitly validated bridge.

## Current priority: useful semantic content and maps

### Failure investigation workflow — 8 October 2026

Researchers can enter `/investigate` from Rollouts or a monitor's rollout values. A monitor entry retains its exact signal metric/protocol and selected value; a direct rollout entry uses an explicit source-failure boolean when available, otherwise a labeled reward threshold. A threshold is a research signal, not a verified failure or model-confidence cutoff.

Select a focal rollout or a set of recent matching rollouts; compare against other rollouts or known signal-negative rollouts. Default to the same task/configuration and recorded training step; widen recorded-step coverage or task scope explicitly. The UI compares metrics with measured/missing counts, plots paired metrics, retains source/graph IDs, and saves an immutable investigation with a researcher hypothesis. New observations prompt an explicit refresh instead of moving the active comparison.

Correlations are exploratory. Whole-rollout features can include reactions after failure, so this feature does not identify causes or establish temporal precedence. Missing annotations are not zero measurements. Next accuracy work should validate pre-failure windows and mechanism evidence, then evaluate whether the investigation reduces researcher diagnosis time. The broader goal remains active.

### Distribution analysis slice — 8 October 2026

The higher layer now also supports a compact distribution view at `/?view=strategies`. This projects saved unit activities into exclusive, versioned analysis groupings and presents separate relation-based lenses for feedback response, failure response and retry outcomes. Grouping changes do not relabel units, change Jev selection or establish strategy preferences. The detailed episode view remains at `/?view=strategies&detail=episodes`.

Compare two recorded training windows within one observer and task/configuration cohort. Show category shares and percentage-point differences together, per-rollout values, sample coverage and exact graph drill-down. Equal-rollout weighting and pooled opportunities answer different questions and are selectable. Unknown observations remain in the distribution; unobserved rollouts are coverage gaps. Missing coordinates cannot become a training curve. Configured groups cover the complete base vocabulary; unsupported labels remain explicitly unmapped.

This release demonstrates the workflow on 16 experimental annotated generations at two logged steps. It does not establish semantic accuracy, training improvement, a general personality or representative policy behavior. Continue the independent semantic/relationship validation and matched-task sampling work before enabling diagnostic alerts or claims about preferences. Goal remains active.

The latest source review finds that source-substring targets, sentence splitting and predicate-first extraction do not supply the requested semantic foundation. Follow [SEMANTIC_MAP_REVIEW.md](SEMANTIC_MAP_REVIEW.md): meaningful units → one activity → readable natural-language target/content with exact evidence → action/result bindings → typed relations. Preserve the difference between local work-target changes, answer revisions and root-objective changes. The two source-bound authored maps now show the required output and every recorded agent contribution; they are not automatic extraction output or semantic accuracy evidence. Implement general candidate generation and actual boundary repair next. Jev remains bounded raw-argmax selection.

## Historical priority notes (superseded where inconsistent)

## Immediate priority after the user's correction

The user's subsequent correction requires the **entire** semantic activity layer to have clear same-level boundaries, not only Orient. The working contract is [BASE_ACTIVITY_STANDARD.md](BASE_ACTIVITY_STANDARD.md): thirteen substantive categories spanning orientation, knowledge, planning, hypotheses, reasoning, choice, information acquisition, construction, checking, coordination, delivery, refusal and social interaction. One category is selected for an established unit; Assess and Revise belong to relationships. This is a full coverage contract to test, not a claim that all real cases or boundaries are already solved. Unit repair states stop category/content inference, and Other/Unresolved expose coverage and definition gaps.

Implement and validate the missing semantic activity foundation before expanding coarse macro inferences, diagnostic categories, environment imports or source-only checkpoint dashboards. The current tool-purpose heuristics are a legacy projection and must not be presented as the planned semantic layer. The source-only ALFWorld investigation developed before this correction remains a research branch of the local code, not proof of completion.

The current delivery priority is a layered whole-trajectory workflow: (1) represent and classify every eligible agent unit, (2) decide which fields each selected activity needs and extract those fields with exact evidence, (3) resolve entity references across units, (4) construct typed relationships using those entities and references, and only then (5) derive macro observations. A unit may have several activity routes or need no entity extraction. Literal word recurrence is not the semantic entity layer. Do not skip category-specific extraction by asking generic all-pairs relationship questions over raw units. Independent validation must accompany the workflow rather than displace its implementation.

The current category-conditioned extractor remains version 0.6, with 53 development units and 220 fields. Local occurrence version 0.2 now refines locally present mention roles: membership is judged per supplied candidate, followed by a separate choice among overlapping boundaries. Several local occurrences may survive for one field. It preserves all previous single-span decisions, supports checkpoint/resume and does not merge entity identity. Twenty-four units / 34 fields yield 45 selected occurrences. The planned reproduce.py mention and its local pronoun are now extracted, and the later create-file target links to the planned file.

This is a capacity and workflow improvement, not proven semantic accuracy. Thirteen authored controls match eleven expected sets after a first design matched seven. Target/payload/purpose, tool/target and feedback-reference mistakes remain in real traces. Only software and telecom have complete base annotation among these small examples. Category selection still limits which fields enter later extraction, and missing source boundaries cannot be repaired by choosing an arbitrary candidate.

Reference version 0.4 completes 45 target and 23 relationship decisions over the occurrences. Actual wire requests and exact decoded evidence are preserved. Shared evidence values solve the observed large-request availability problem, but 18 of 35 comparable field results change relative to the earlier partial inline pass; there is no repeated-run control or independent semantic label set for that representation comparison. Do not claim that encoding preserves model interpretation. A matching object is not plan following or successful execution.

The latest local-layer implementation exposes dependencies for every mention role, with source-bound governing expressions, contrast fields and repair status. An eight-unit / ten-field experiment compares an exact baseline repeat with a dependent local-role request. The candidate helps some target distinctions but damages a feedback-reference result and does not separate compound-edit roles; it is not promoted. The next step is still local: isolate operation/claim instances and define each category's argument relationships, especially target versus payload/purpose and assessed input versus conclusion. Complete those local bindings before expanding reference transport experiments, same-unit identity links, typed action relationships or macro interpretations. See DELIVERY.md and `research/local-role-context-2026-10-07` for the complete mixed evidence.

The subsequent local-frame implementation separates predicate-head proposals and per-head argument attachments, with persistent per-call resumption and source-visible review. The ten-unit pass reveals both useful separation and basic head/attachment errors. An optional parser comparison supplies better candidates in some cases, with its own errors preserved. Next, use a source-bound candidate-provider contract and inspect each predicate occurrence once before sharing it across activity routes. Do not interpret the current nineteen head proposals as nineteen verified actions, entities or behavior events. Accurate local scope, complements, semantic roles and independent validation remain required by the full goal.

The initial H0/H1 implementation is available in the local app; its validation is in progress. Its existence, tests or demonstration annotations do not by themselves meet the accuracy gates above. See [DELIVERY.md](DELIVERY.md) for the current evidence. The broader product goal remains active and incomplete.

## Goal-tool limitation

The available app goal tools can read the active objective, create a new objective when none is unfinished, and update status. They cannot edit an active objective's text. The original app goal remains active; this document and the latest user instruction control the revised scope. Do not falsely complete or pause the goal to replace its text.
# Current delivery direction — 8 October 2026

Use one connected Behavior map: source units are cards, activities and readable work are characteristics, and selected relationships are inspectable lines. Organized Plan stages are a summary of those same units, not another independent annotation map. Keep recorded order, preparation, attempt, result, check, return and expressed revision distinguishable. A move to another stage is not automatically a deviation; a later successful operation is not automatically recovery of the task.

Training monitoring is per rollout, with explicit experiment, logged iteration and rollout identity. Checkpoints are optional provenance. The current public training sample contains 3,072 completions from six complete logged batches; its flattened text supports length and logged reward, but not internal action paths. Do not transfer semantic-map observations from unrelated demonstration traces onto this training series.

Near work: improve source-scope boundaries and echo/media handling against retained failures; test the same result layer on additional interactive domains; obtain independent reference review before reporting semantic accuracy; connect complete semantic passes to genuinely step-indexed action rollouts; and reduce map-loading audit latency while preserving version checks. Candidate proposals still require supplied files or a configured provider. Keep the broader goal active until reliable general extraction and useful macro comparisons are demonstrated.

## Latest relation/measurement progress — 8 October 2026

The experimental stated-change layer now joins prior operation failure, an agent's expressed change, a matching dispatch and the next selected same-work outcome. It retains base activities and distinguishes procedure changes, prerequisite repairs, prerequisite-state reports and attempted enactment. The software development trace measures 1 completed retry / 5 retries with known outcomes, with 2 further unknown outcomes. Airline/retail have no eligible expressed-change denominator. No training coordinates or task recovery are inferred.

The long-context experiment uncovered nested-scope and temporal correspondence errors despite passing short controls. The focused protocol repairs the reviewed false links but still omits some intermediate prerequisite declarations; notes accompany raw choices in the map. Do not claim independently established accuracy. See `research/attempt-revisions-v4-2026-10-08/README.md`.

The next priority is local change extraction and incremental relationship reuse, followed by held-out source review, before enabling expensive semantic inspection for every rollout. This relation pass alone used 484,707 Jev input tokens for one software trace, with no Luna calls. Dashboard refresh and graph aggregation use saved observations only. Keep the product goal active.

## Practical evidence capture — 11 October 2026

`WorkStateRecorder` now lets producers supply versioned check inputs, changed objects and delivery requirements using source references. Eight controlled software/business tool executions agree across three source encodings and produce 24 source-linked live measurements. Unknown stability and changed criteria remain unknown for recovery; an edit after a pass invalidates that pass for changed delivery inputs. These are recorded-state facts, not new semantic labels or proof of whole-task success. State objects remain in the graph but are attached to actual step cards in the map; empty parent reasoning wrappers fold without deleting source records.

The next gates remain native producer integration, independent semantic review and real step-indexed action training data. The source-state increment supplies useful evidence for those layers; it does not complete exploration, deviation, recurrence interpretation or framework-general accuracy. See [audit](../research/state-capture-2026-10-11/README.md).

The subsequent [mini-SWE-agent native audit](../research/mini-runtime-2026-10-11/README.md) executes the source-state path in actual upstream 2.4.6 agent/environment loops, across text/tool/Responses modes and interruption paths. Capture-on/off messages and outcomes match across seven authored cases. This closes one native integration gate, not framework-general support or semantic accuracy. Correctly recorded limits remain measurable completed traces; unexpected exception traces remain partial. Next prioritize independent source review of the semantic/macro layer and real interactive training data, while retaining untested container/distributed boundaries.

## Diagnostic validation and network correction — 12 October 2026

The [first-error pilot](../research/process-error-pilot-2026-10-12/README.md) compares a limited tool-error rule over 600 development traces with four source-hash-selected, fresh-context Luna reviews. Exact first-error agreement is 284/600 for the rule and 1/4 for the small Luna pilot; these are different populations and not a performance ranking. The pilot misses earlier visible tool constraints and includes a source-grounding problem even in its matching case. No diagnostic is promoted. Next test generic tool-contract validation and scoped semantic constraint checks, keeping operation failure, agent error, reporting claims and task success distinct. Preserve the 400 reserved tasks for evaluation after definitions freeze. Four Luna turns, zero Jev calls; billing telemetry unavailable.

The [proxy check](../research/jev-route-2026-10-12/README.md) corrects an earlier connectivity inference: approved host inspection discovers the user's enabled local proxy, while the sandbox exposes no proxy. The historical failed request's route is unverified. A different Jev endpoint has not been established as necessary. This check made no authenticated request and did not change or restart the running service. The broader product goal remains active.

Subsequently, [six actual Jev selections](../research/scoped-selector-2026-10-12/README.md) succeeded using a dedicated standard opener with the host's automatically discovered proxy. Raw argmax selects two Orient, one Knowledge and three Reason, matching all six frozen development expectations. Usage is 21,390 input / 774 output tokens across six HTTP attempts, with no new Luna calls. This is fixed-unit development agreement, not independent accuracy or complete extraction. Six category-conditioned content requests are prepared but have no generated outputs or selected contents yet. The next semantic step remains useful local work targets and typed relationships. No server restart or endpoint change was required.

**Subsequent content-stage progress:** The [category-conditioned trial](../research/scoped-content-2026-10-12/README.md) now retains four fresh Luna outputs, five actual Jev-selected content bundles and one rejected exact quote. The strict original result is 3/6 structurally ready; two missing transport headers are recovered by separately supplying the caller-owned metadata without altering fields/evidence. The reusable candidate worker exposes this explicit contract and budgets its actual extended stdin envelope. Jev uses 12,078 input / 235 output tokens in five calls; Luna billing remains unavailable. Source review finds readable immediate targets, preserved intention/performance and arithmetic, plus a contextual-assumption citation concern. This closes a bounded content execution step, not independent semantic accuracy or complete relationships. Next require complete coherent contributions and source-linked targets/conditions before testing target → attempt/check → feedback/revision paths; do not turn sparse development snippets into macro metrics. The broad product goal stays active.

The [parameter-schema observer](../research/tool-contracts-2026-10-12/README.md) now checks source-bound native calls without inference and exposes evidence through current dashboard monitors. Across 600 development traces it records 56 conflicts in 3,018 calls; 169 calls lack declarations. Fifteen flagged whole messages carry nonnegative process labels, including tools that accepted arguments inconsistent with their declarations. These are interface observations, not a general first-error detector. The GAIA pilot's earlier malformed call is localized, while BFCL's prose path constraint remains outside this check. The broader semantic/macro goal stays open. Next validate scoped natural-language preconditions and provenance of accepted tool arguments before combining these observations into a general diagnostic; preserve the 400 reserved tasks. Automatic invocation on ingestion and deployment into the existing keyed server remain unfinished.

The [complete retrieval case](../research/retrieval-rollout-2026-10-12/README.md) now covers all five eligible agent units in one public development rollout, with selected readable contents, three source call/result links and one prose/dispatch association. All twelve Jev calls succeed through the configured host proxy. The source retains a malformed two-query call, tool error, two same-batch follow-up searches and final answer; no empty semantic card or invented assessment/revision is added. This closes a bounded whole-rollout execution check, not semantic accuracy. Review finds overly broad work-target descriptions and a whole-identity candidate gate that can omit partial work overlap. Address those local scope/retrieval issues before inferring recurrence or strategy change. The research coordinator now requires explicit producer completion and sealed output snapshots; historical premature-import and receipt-namespace failures remain documented. Twelve Luna jobs have no billing telemetry; Jev uses 43,391 input / 974 output tokens. Preserve the reserved evaluation tasks and keep the full goal active.

The [related-work scope trial](../research/scope-pairs-2026-10-12/README.md) adds opt-in correspondence/5: independent comparisons with all eligible prior actions, multiple partial-work links and exclusion of same-batch temporal predecessors. The map exposes these links and their source evidence. Actual Jev results match 17/20 authored control requests and 2/2 reviewed real-source comparisons, with three retained failures around changed means and missing task-instance evidence. No independent accuracy claim or default promotion follows. The final integration fix keeps unresolved identity visible in rollout metrics. The full Python suite passed 1,589 tests before that fix, the final relevant suite passed 45 tests, and 11 browser layout tests passed. All 22 Jev requests succeeded through the user's proxy: 56,901 input / 1,791 output tokens and zero new Luna calls. Next prioritize grounded immediate work versus broader objectives, task-instance identity versus means, and complete-source review before expanding macro claims. The 16-candidate cap is explicit; scalable retrieval and training-scale cost remain open. The broad product goal stays active.

The [immediate-target refinement](../research/work-target-refinement-2026-10-12/README.md) now offers existing category-conditioned content fields as alternative work targets, without new generative proposals. The ordinary CLI preserves units/activities and Plan structure, audits parent decisions, versions collection protocols, supports resumable budgets and rebuilds dependent history separately. Actual Jev selections match 9/10 frozen development acceptability sets: three retrieval operations and two Orient next-work descriptions improve, while a Reason unit still wrongly targets its future check. Field reuse cannot supply the absent correct candidate, and Jev failed to reject the offered bundle. The preview retains that failure as a visible review note. No default promotion or independent accuracy claim follows. Ten successful responses use 40,596 input / 590 output tokens, zero new Luna calls; a local trial credential-variable bug caused one extra 401 attempt, was regression-tested and repaired, and is explicitly unrelated to proxy availability. Full-suite evidence is 1,595 tests before final checks, followed by 40 final relevant tests. Next generate and evaluate a fresh coherent candidate for the remaining contributed-reasoning versus described-next-action distinction, then validate broader transfer and downstream metric impact. The broad product goal remains active.

The [targeted content repair](../research/content-repair-2026-10-12/README.md) now adds a reusable fixed-unit content queue: original versus up to two fresh bundles, raw-argmax selection, explicit rejection/gaps, preserved source/parent decisions, separate relation rebuilding and versioned collection scope. One Luna fallback turn supplied the absent Reason candidate. Its original citations failed strict format validation; a separately recorded deterministic binding removed only matching redundant subject identifiers, leaving generated meanings unchanged and the strict production parser intact. Jev selected the repaired chronology target and two rebuilt partial-work links in three successful requests through the existing proxy (12,789 input / 205 output tokens). Luna billing remains unavailable. Activity counts are unchanged; neither partial overlap nor a final answer establishes recovery, and missing training coordinates remain missing. The original failure is retained and the repaired map is a separate experimental observer. Full-suite validation passed 1,604 tests, followed by 48 focused checks including the final history/registration integration test. Next validate category/domain transfer and relation effects before promoting the repair or claiming general macro accuracy; the broader goal stays active.

## Automatic native RL signals — 12 October 2026

Supported existing Slime imports now expose retained advantages, values and returns without re-importing or changing capture. Automatic view selection, response-mask-aware pooled statistics and exact source drilldown reduce per-user setup. The native writer runs after actor training, but its retained critic values originate earlier; no optimizer-use receipt, estimator definition or model version is inferred. Four previously executed native-writer CPU controls reconcile over seven eligible positions with unchanged source/fact hashes and zero new model calls. Full regression passed 1,892 tests, followed by 30 final focused checks and responsive browser/export verification. See research/retained-rl-signals-2026-10-12/README.md. Continue RL-method adaptation and full native producer validation; independent semantic accuracy, distributed execution and production-scale costs remain open. The broad product goal stays active.


## Multi-reward RL integration — 12 October 2026

Reward relationships now compares exact shared sample scores across native generation steps and separately pools complete-group deviations, with explicit missing coverage and paired source drilldown. The native TRL adapter captures multiple reward-matrix columns on one generated identity; DAPO/sum-then-normalize and SAPO/normalize-then-sum each passed six-step CPU training/evaluation comparisons with capture enabled/disabled. Actual tokens, reward matrices, advantages and final parameters match. Versioned settings readers now prioritize the comparison for supported multi-reward settings. Full regression: 1,904 tests, followed by 96 final focused checks and responsive browser/export verification. No Jev/Luna calls. See research/reward-relationships-2026-10-12/README.md. Continue framework-native validation, scalable projections and independent semantic/strategy accuracy; this descriptive score relationship is not a diagnosis of gradient conflict or reward hacking. The broad goal stays active.


## Reward patterns and fixed behavior comparisons — 13 October 2026

Reward relationships now saves exact pair evidence and original complete-group baselines into the existing training investigation. Saved pattern populations compose with existing behavior monitors, source weighting and immutable case links. Native DAPO/SAPO retained-data replay reconciles four populations; corrections leave saved membership intact and reject stale new saves. Ten new authored controls include shared-source independent samples and exact group-mean direction under extreme-scale cancellation. Full regression passed 1,917 tests, followed by 62 final focused checks. Saved browser exports now retain server numeric representation and independently verify their original hashes. No new training or model calls. See research/reward-behavior-2026-10-12/README.md. Continue full native framework coverage, production-scale querying and independent semantic/strategy validation; score patterns do not establish reward preference, gradient conflict or reward hacking. The broad goal stays active.

## Behavior map prominence and objective hierarchy — 13 October 2026

User direction makes the detailed unit map a highlighted primary feature and asks for a mind-map-like objective/plan/branch view. Behavior map is restored to primary navigation and workspace search; rollout/observation selectors are visible, and the existing levels are named Unit map and Work path. The objective/plan hierarchy is designed in OBJECTIVES_AND_PLANS_MAP.md but is not implemented. Prioritize enduring work identity, evidenced parentage, alternative approaches and scoped lifecycle before branch-level metrics; reuse existing source-bound units and plans. Do not substitute the temporal work route for this hierarchy or infer ignored/completed branches from missing events. The broad goal stays active.

## Readable plan attempt comparison — 13 October 2026

The hierarchy now supports native nested control flow and semantic Plan stages. This increment replaces the semantic plan's flat action expansion with a branch-specific attempt path: dispatch, response, agent assessment, explicit return links and compact intervening work. A public software replay retains four conversion attempts and their distinct evidence without turning a directory listing into verified report completion. Exact source cutoffs, stage URLs, graph exports, in-place evidence and Unit-map roundtrips are preserved. No new provider calls. Regression passed 1,952 Python tests; focused Python and browser-model checks also passed. See PLAN_ATTEMPT_PATH.md and research/plan-attempt-path-2026-10-13/README.md. Next validate general work identity, hierarchical parentage and branch lifecycle across independent sources before making strategy/recovery quality claims. The broad product goal remains active.

## Consistent work measurements — 13 October 2026

Current work-return monitors and Work focus distributions now qualify saved memberships against compatible contradictory pair observations. Disputed switches stay unknown, affected counts are withheld, and the map shows the disagreeing claims and their source excerpts. Unaffected returns remain usable. Historical monitor definitions and projections are retained explicitly, with dashboard interpretation notices. The public retrieval replay changes a misleading zero to unavailable; a separate pair-derived grouping retains its one return and 1/2 decidable switch fraction. This is consistency evidence, not independent annotation accuracy. Validation passed 1,962 Python and 91 JavaScript tests, with desktop/mobile workflow checks and no new provider calls. See research/work-consistency-metrics-2026-10-13/README.md. Continue independent work-identity, hierarchy and lifecycle validation before interpreting movement as exploration, deviation or successful recovery. The broad goal remains active.

## What changed between attempts — 13 October 2026

Plans & attempts now compares exact saved return pairs in place: recorded tool/input differences or explicit text-only comparison, intermediate actions with their actual plan assignments, source cutoffs and direct unit links. A retained software case separates an added PDF-engine option from an unchanged command after an image-path edit. Two real Harbor exports and authored SWE-agent/portable chat controls exercise common captured inputs. No variant, causal repair or completion is inferred from field equality. The reusable comparator and versioned projection preserve the source graph and existing measurements. Validation passed 1,976 Python and 94 JavaScript tests, with final focused checks and responsive browser workflow verification. No new provider calls. See research/attempt-input-comparison-2026-10-13/README.md. Independent semantic accuracy, free-prose hierarchy/branch lifecycle and production-scale comparison remain open; the broad goal stays active.

## Full work outline and tested proposal boundary — 13 October 2026

Plans & attempts now shows a nested full outline, focused subtrees, explicit shared-work references and a source-ordered decision history. Source drilldown preserves the selected branch and view. A named manual software review has twelve work items, eleven parent links and six decisions/reports, including a synthetic-data test kept distinct from the requested GDSC evaluation. Original units and prior graph versions are retained. Full regression passed 2,000 Python tests before the final row-diagnostic change, followed by 46 affected Python tests and all 100 JavaScript tests. Desktop/narrow-screen, cutoff, collapse, attempt-path and source-roundtrip checks passed. See research/work-outline-overview-2026-10-13/README.md.

The automatic-outline trial did not yield an accepted map. The non-LLM saved-plan baseline lacked objectives and decisions; a Luna proposal failed exact citation binding. Its feedback-assisted repair bound structurally but was rejected by one raw-argmax Jev selection. No automatic graph was installed. Cost was 8,869 Jev input / 50 output tokens and two Luna turns with unavailable billing metadata. The rejection and original candidates are retained in research/outline-proposer-2026-10-13. The framework has a replayable bounded candidate contract, not proven automatic extraction.

Next establish source-local work targets and scope before identity/parentage and decision attachment, include conditional reporting in the representation, and evaluate independent traces. Do not rerun an unchanged rejected bundle. General extraction, strategy accuracy, training-scale costs and reliable cross-prefix work identity remain open; the broad product goal is active.

## Work timeline and local scope boundary — 13 October 2026

The same behavior-map workspace now includes a Work timeline beside the nested outline and focused branch view. It shows source-record positions of declarations and explicit decisions, initially filters to work items with decisions, preserves a visible shown/total count, and provides an all-items switch. Exact evidence appears in a dismissible panel; source-record drilldown returns to the same timeline. Nearby observations are grouped without dropping conflicts, and an identical quote that introduces and chooses work is not duplicated. No durations, abandonment, causal recovery or parent completion are inferred. The public twelve-item manual outline, cutoff and source links remain unchanged. Full validation passed 2,010 Python tests and 103 JavaScript tests, with desktop/mobile, cutoff, filtering, source-roundtrip and keyboard checks. See research/work-timeline-2026-10-13/README.md.

A new local scope experiment reused all eight existing work/purpose pairs without Luna. The single Jev batch used 7,721 input and 541 output tokens; an unchanged replay used zero new HTTP requests. Three of seven prewritten development expectations disagreed with selection, including checking Pandoc availability versus converting the report; one case remained unadjudicated. This is not an independent accuracy benchmark. The experimental graph was retained as evidence but not installed, and its local edges were not used to construct the displayed hierarchy. See research/work-scope-frames-2026-10-13/README.md. Clarify the distinction between included operations, required outcomes and downstream undertakings before another paid trial. General work identity, reliable automatic parentage and independently validated strategy metrics remain open; the broad goal remains active.

## Bounded earlier-work search — 13 October 2026

The Unit map now retrieves earlier contributions using a non-LLM text index plus recent context, shows exact candidate text, supports navigation back to the comparison, and exports bounded pair requests. Existing compatible observations, including unresolved selections, are not recomputed. Missing targets and budget deferrals stay explicit; no identity, group or novelty conclusion is inferred from ranking. The complete-pair grouping contract remains unchanged. Refresh now restores the selected unit, and inspector/zoom changes keep its card visible.

Three retained public development sources shortlist 681 of 2,587 eligible pairs and retrieve 20/20 existing reference links versus 15/20 for recent-only selection. Software prepared input falls from 9,086,208 to 2,305,930 serialized bytes; these are request-size measurements, not token costs or independent accuracy. All nine compatible retrieval-source pairs are reused with no new requests. Full regression passed 2,020 Python and 103 JavaScript tests, with final syntax, HTTP/download and desktop/narrow-screen verification. No Jev or Luna calls. See research/work-retrieval-2026-10-13/README.md.

Next validate missed-link risk on independent and paraphrased work, clarify local scope semantics, and establish reliable identity/parentage before automatic high-level branch maps. Persistent incremental indexing and training-scale load checks are still required: the comparison budget is bounded, but local whole-rollout scanning can remain quadratic. The broader product goal remains active.

## Purpose attachment is not hierarchy — 13 October 2026

AMR, RST and UMR design distinctions motivated a separate `work-purpose-roles/1` selector: the intentional role of a purpose is no longer conflated with whether its words or result fall inside a complete work description. Existing content and source are reused, and raw argmax is retained. Local purpose edges cannot establish separate work identity, parentage or completion. Legacy scope graphs continue to replay.

Two bounded Jev requests matched eight authored controls and four of five adjudicated real-source expectations; three compound cases remain unadjudicated, and all eight real pairs selected whole-work purpose. This is a new question, not an independently measured accuracy improvement over the prior scope test. Neither experimental graph was installed. Actual cost was 8,767 input / 1,322 output tokens, zero Luna calls; unchanged replay used zero HTTP requests. A local parser probe exposed candidate heads but problematic clausal attachments and contraction spans. All 267 work-related tests passed. See research/work-purpose-roles-2026-10-13/README.md.

The next semantic bottleneck is now concrete: establish local work mentions within an unchanged contribution and bind purpose, sequence and conditions to the correct mention. Avoid another whole-outline regeneration or more overlapping activity tags. General automatic identity, hierarchical parentage, strategy measurements, independent evaluation and production-scale operation remain incomplete; the full product goal stays active.

## Local work descriptions and a failed whole-reading selector — 13 October 2026

Implemented a bounded local-content layer within unchanged units, with exact source quotes, operation/state modality, purpose/order/condition/response links, immutable replay, and a read-only inspector shared by Unit map and Plans & attempts. Source-reviewed descriptions stay inside their unit and do not create extra activity cards. Narrow-screen inspection uses page scrolling; verbose activity fields are grouped under a disclosure.

The higher-level outline opens with the objective and main branches, expands one branch or the whole hierarchy, and adapts its columns to available space. Timeline folding is independent. Browser checks confirmed eight overview cards versus twelve fully expanded items, six decision-history rows retained after overview collapse, subgoal-to-unit navigation, withheld-reading visibility, and desktop/narrow-screen layout. This changes presentation without inferring new parentage or lifecycle states.

The first generator artifact was an incompatible whole-outline response and was rejected before a paid selection. The corrected local proposal passed source binding but had semantic defects. Jev selected all eight bundles, including a purpose link aimed at the absence of the required tool. Assistant development source review withheld four readings; only four reviewed contributions, ten descriptions and three links were installed in a separate preview graph. Raw selection remains unchanged. This is a useful inspection increment and a negative automatic-selection result, not validated automatic extraction. All 101 original units and the reviewed outline remain unchanged.

Actual new Jev cost: 4,779 input and 363 output tokens, one request; unchanged replay made no new HTTP call. Luna usage was not available; one proposal task had two corrective follow-ups. 279 work-related Python and 103 JavaScript checks passed; source/API receipts are retained under research/work-mentions-2026-10-13. Next isolate mention completeness, modality and per-link support, keep these rejection failures as tests, and establish stable cross-unit work identity before adding higher-level branch metrics. The broad product goal remains active and incomplete.

## Spatial work canvas and retry counts — 13 October 2026

Replaced the reviewed outline's scrolling card grid with a bounded mind map: two-sided branches, pan/zoom, minimap, folding, scope up/down and source-evidence pop-ups. Explicitly stopped/deferred work is gray; absent decisions stay distinct. The decision timeline and original Unit map remain available. Removed the obsolete outline grid renderer/styles and side-panel evidence styling.

Added read-only `work-hierarchy/6` retry summaries over existing attempt and return relationships. Counts distinguish repeated attempt dispatches from explicit returns after an error report, exclude standalone checks/preparation, deduplicate parallel witnesses and stage membership, and respect source cutoffs. Unique plan-to-approach citations let reviewed ancestors display nested counts without assigning guessed step identities or propagating outcome states.

The public PDF conversion has four attempts, three repeated attempts and one explicit error-linked retry; the other repeats retain unknown error-return linkage. The modal exposes earlier feedback, exact input differences and intervening work. No model call was made. 284 work-related Python tests, 22 plan/comparison tests and 112 JavaScript tests passed. Browser checks cover desktop/narrow layouts, cutoff changes, retry highlights, modal/Escape, folding, scope, timeline and unit navigation. Evidence and limitations: research/work-canvas-2026-10-13/README.md.

Automatic hierarchy extraction, verified answer attribution, reliable abandonment and exploration/exploitation measurements remain unfinished. These presentation and deterministic counting changes do not establish them. The broad product goal remains active.

## Continuation experiment evidence — 13 October 2026

The preceding goal turn produced evidence that changed the next action: the GRPO
case audit distinguished semantic work branches from actual sampler forks and
identified missing prefix-experiment lineage, plus concrete long-context capture
limits. It was progress through a verified capability audit, not implementation
of the experiment or proof of the full product goal.

Added immutable `continuation-studies/1` designs, independent child-sample
membership, exact master/child token-prefix checks, sampling/context consistency,
late and revised binary outcomes, and explicit discovery/confirmation identity
checks. The existing durable outbox, HTTP collector and CLI accept these records.
Training health now includes a continuation comparison with coverage, conditional
intervals, probe-generation cost, sampling branch tiles, source unit-map links and
pinned evidence export. Existing live revision events update late outcomes.
Experiment/environment filters include fact/design-only scopes before sources arrive.

Generation-only token declarations allow untrained probes to provide exact prefix
evidence without invented learner inputs or masks. Known optional observations
are retained when generation and export records coexist.

Validation includes 150 targeted tests and one additional precedence regression
(151 distinct targeted tests), HTTP replay/conflict/filter controls, and desktop/
narrow-browser checks for live outcome arrival, pop-ups, source navigation and
export. All controls are explicitly authored in an isolated database. No new Jev
or Luna call was made. Main owned preview on 8810 was refreshed without loading
the authored studies into its database. Details: docs/CONTINUATION_STUDIES.md and
research/continuation-studies-2026-10-13/README.md.

Real native continuation experiments, long-context/distributed capture, arbitrary
sampling genealogy, cross-study training curves, selection-aware inference and
span-to-training-weight audits remain incomplete. These are limitations of the
adapter, not commitments to implement the blog's method; the controlling scope
correction above takes priority. These additions do not establish
causal token credit, an effective optimizer intervention, independently accurate
semantic extraction or completion of the broad product goal.

## Connected investigation checks — 13 October 2026

Implemented the shared workflow increment in existing Investigations: immutable
check designs, independent or related checks, appended findings, linked saved
comparisons, exact annotated units and optional continuation results. Supports or
contradicts requires evidence; inconclusive and not-run outcomes stay explicit.
Original case scope survives findings, corrected scores and note revisions.
Comparison and unit-map inspection return to the originating investigation, and
exports preserve exact direct evidence documents. Continuation viewing is now
supporting evidence in Training health rather than an always-visible main action.

120 focused Python tests, actual HTTP controls and desktop/narrow browser flows
pass. A downloaded workflow export independently verifies both retained document
identities. Selection, reward-review and recovery cases are authored controls in
an isolated database; the main preview on 8810 has the feature but no added test
investigations. Zero new provider calls or training runs. See
[the contract](TRAINING_INVESTIGATIONS.md#follow-up-checks-and-returned-evidence)
and [verification](../research/investigation-followups-2026-10-13/README.md).

This provides researcher-driven workflow assistance, not automatic diagnostic
reasoning or experiment execution. Next evaluate actual investigation effort,
retrieval and candidate localization, evidence comparability and semantic
accuracy across real cases. Production-scale storage and native experiment
handoffs remain open. The broad product goal stays active.

## Component audit experiment — 13 October 2026

Implemented optional, replayable checks of existing local descriptions,
relationships and coverage inside unchanged base units, plus an in-place audit
disclosure. Source review overrides publication without rewriting the model's
choice. A controlled option-identifier evaluation helper preserves raw argmax.

The extraction experiment failed to establish better semantic reliability.
27/36 first-trial decisions matched Assistant development expectations; important
purpose, bundling and omission errors remained. Two small follow-ups did not
establish a remedy. These are neither independent accuracy measurements nor
evidence of a production improvement. No experimental graph was installed into
the main database. The initial shared-state prompt also did not enforce per-unit
context isolation; its limitation is recorded with the frozen experiment.

90 focused tests and desktop/narrow UI checks verify the mechanics. Three new
Jev calls used 13,576 input and 2,812 output tokens through the configured proxy;
zero Luna calls. Unchanged proposals and original selections were reused; all
replays made zero HTTP calls. See the
[experiment record](../research/work-mention-checks-2026-10-13/README.md).

Next improve separately referable operations and intended states at candidate
construction, then independently evaluate omissions and source-bound relations.
Do not infer reliable macro structure from this failed selector. The broad goal
remains active; existing researcher-driven investigation and procedure-review
workflows remain the usable path while automatic extraction is unresolved.


## Procedure monitor consistency — 13 October 2026

Aligned new same/reconfigured-procedure counters with the strict exact-pair
eligibility used by the procedure distribution. Partial and unresolved judgments
no longer enter these new witness counts. Historical definitions and receipts
remain unchanged and carry a visible notice. Cards expose compared/unresolved
coverage, and editing a focused historical monitor follows its replacement.

61 focused Python tests, 51 map/navigation tests, public-source replay and
normal/narrow browser checks passed. The retained public trace has 3 compared
of 10 recurrences: 2 same, 1 reconfigured and 7 unresolved; change fraction 1/3.
Zero provider calls and no test data added to the main preview. See
[verification](../research/procedure-coverage-2026-10-13/README.md).

This establishes measurement consistency, not semantic accuracy or population
prevalence. The broad goal remains active. Continue independent source review
and evaluation of candidate omissions before relying on automatic macro claims.


## Window-bound distribution evidence — 13 October 2026

Connected macro distribution bars to complete evidence retrieval in the selected
earlier/later window, including shared-task restrictions. All cases are reachable;
search, exact source comparison, frozen-map round trips and selection exports
retain context without changing measured shares. A retained public installation
trace exposes two virtualenv-error recurrence pairs directly in this view while
its seven unresolved procedure comparisons remain unresolved.

11 JavaScript tests, 32 Python tests, 21 public cases and browser checks of an
isolated 27-case paginated selection passed. Main preview updated; no model calls
or test data added to its database. See
[verification](../research/distribution-cases-2026-10-13/README.md).

This improves researcher investigation, not automatic semantic accuracy or
causal diagnosis. The broad product goal remains active; independent semantic
validation and demonstrated research benefit remain open.

## Unit evidence reading — 13 October 2026

Replaced repeated target-only action text with discriminating dispatch/operation
details. A selected unit now defaults to one relationship; its inspector groups
returned feedback, recorded assessment, repeated work and plan links with source
excerpts. Exact two-edge response/assessment paths are readable without inferring
causality or filling missing annotations. All unit links remain available.

32 focused tests, 152 cards across three retained public graphs, and desktop,
narrow-screen and actual mouse-scroll checks passed. The software rollout's
final card is reachable; zero provider calls or annotation changes. See
[verification](../research/unit-reading-2026-10-13/README.md).

The broad goal stays active. This resolves a concrete map-reading weakness;
it does not establish automatic semantic accuracy or complete the wider audit
of page content and researcher workflows.

## Evidence-dense story cards — 13 October 2026

The story now places an operation, its bound response and the exact linked
follow-up together. It displays source text for standalone contributions and
preserves unknown or unpaired feedback. Search, review filters and a compact
moment navigator replace the duplicate horizontal strip. A frozen graph link
retains filter and position across Unit-map navigation and reload.

38 focused tests, four public graph projections and desktop/narrow browser
checks passed. The software example exposes 20 saved two-edge paths across
19 of 33 responses; source-only data generates no semantic links. These are
presentation and binding checks, not independent annotation accuracy. UI work
used zero model calls. See the
[verification record](../research/story-evidence-2026-10-13/README.md).

A separately prepared source-inventory proposal contract passed 33 mechanical
tests. Its one bounded Luna trial and delivery-only recovery follow-up failed
to deliver response files. No Jev calls, semantic result, accepted annotation or
accuracy improvement came from that experiment. Preserve this failed execution
and avoid an unchanged repeat; see the
[construction trial](../research/work-mention-construction-2026-10-13/README.md).

The broad goal remains active. The next semantic work needs a delivery mechanism
that produces attributable candidates before any selection or quality claim;
the broader UI audit remains distinct from that unresolved extraction problem.


## Saved feedback assessment timing — 13 October 2026

Added a deterministic per-rollout measure for whether a response’s earliest
eligible saved assessment follows additional recorded dispatches. The retained
software trace has 1/19 such comparable responses, with 14/33 opportunities
unknown. Missing links and incomparable ordering remain unknown; no claim of
ignored feedback, actual first assessment or causal use is made.

The existing monitor-to-map workflow now groups timing cases with command and
response excerpts, shows the exact intervening actions, resolves native event
references to displayed unit cards, and restores the case after reload. A scoped
monitor is available in the main preview; no training coordinates were invented.

103 focused Python tests, 29 story/unit-reading JavaScript tests, four public
graph replays and desktop/narrow browser checks passed. Zero provider calls.
See [verification](../research/feedback-timing-2026-10-13/README.md).

The broad goal remains active. This adds an inspectable observation, not an
automatic diagnosis or independent semantic validation. Continue evaluating
upstream extraction and researcher workflows before expanding aggregate claims.

## Connection reader and information density — 13 October 2026

The unit map now opens with an expanded canvas. A focused connection presents
both endpoint excerpts, a concrete research question and its exact predicate;
source expressions retain uncertainty. Navigation across a unit's links and
graph-bound reload were checked. Feedback details now lead with returned output.

Dashboard cards expose missing-measurement reasons and direct case retrieval,
remove fixed blank space, and avoid redundant one-bar charts for single rollouts.
59 JavaScript tests and live desktop/narrow viewport checks passed. All 105
cards in the software example are reachable with actual mouse scrolling.
No provider calls or annotation changes. See the
[verification record](../research/connection-reader-2026-10-13/README.md).

The broader product goal remains active. This improves evidence reading;
independent semantic validation and the wider page audit remain separate work.

## Staged local content candidates — 13 October 2026

Preserved and reviewed all four isolated proposal outputs: two failed structural
binding, and one of the two that bound misattached a mathematical method. A
changed contract now constructs readable work contents before relationships,
assigns IDs locally, and freezes source/content identity between stages.

Three bounded fresh Luna responses all bind; two meet the frozen development
criteria and one loses the source hedge in its label. No response was repaired,
no relationships were generated, and no Jev calls or live annotations resulted.
47 contract tests passed. Exact token usage remains unavailable. See the
[trial and retained failure](../research/work-content-stages-2026-10-13/README.md).

The broad goal stays active. Layering removes a demonstrated contract failure,
but independent semantic accuracy and cost at training scale remain unproven.
Preserve source expressions in maps and investigate qualification/omission errors
before using these candidates for automatic macro claims.

## Connection routing and responsive evidence — 13 October 2026

Shortened nearby cross-column links through row gaps, moved labels onto their
routes and highlighted both endpoints. A focused connection now fits desktop
columns without persisting a zoom preference that makes narrow-screen text
unreadable. Removed the disabled connection-reader navigation footer.

40 map/reading tests, geometric card-intersection checks, desktop/narrow browser
checks and actual full-trace mouse scrolling passed. All 105 example cards remain
reachable, and saved connection evidence restores on reload. No provider calls
or annotation changes for the UI pass. See
[verification](../research/connection-routing-2026-10-13/README.md).

The broad goal remains active. The map now explains a selected relationship more
clearly; wider UI consolidation and validated macro extraction remain open.

## Whole-rollout work timeline — 13 October 2026

Added a compact occurrence timeline to the existing Work path. Repeated targets
have their own rows; Other recorded work expands into separate identities. Every
recorded occurrence remains inspectable. Selecting a return opens its prior work,
intervening visits and source units. The detailed route and saved graph remain
unchanged. Missing procedure comparisons no longer displace the observed work
sequence at the top of the reader.

28 JavaScript and 21 Python tests passed. Three retained public-source graph
projections reconcile 33 actions, 34 reasoning contributions and 5 search
contributions. Desktop/narrow browser checks covered expansion, focused windows,
reload, evidence-to-unit navigation and internal horizontal scrolling. No model
calls or new semantic observations. See
[verification and interpretation boundaries](../research/work-timeline-2026-10-13/README.md).

The previous turn was verified progress, and this increment further improves
whole-rollout inspection. The broad goal remains active: recorded recurrence is
now easier to inspect, but validated automatic exploration, deviation, productive
adaptation and training-population comparisons remain unproven.

## Procedure lens over recorded recurrence — 13 October 2026

The previous turn was verified progress. The existing Work timeline now exposes
saved procedure comparisons beside work returns, retaining every action and the
intervening work. Known comparisons lead with the saved review and exact dispatch
text; missing comparisons stay unknown. Graph, source and pair identities must
match, and reasoning contributions do not acquire action-procedure metrics.

38 JavaScript and 44 Python tests passed. Read-only replay reconciled the reviewed
software graph (1 changed, 2 same, 7 unknown), its unreviewed graph (10 unknown),
and 34 reasoning contributions. Browser checks verified source-unit navigation,
reload, narrowed windows and mobile layout. No model calls or annotation writes.
See [verification and limits](../research/procedure-lens-2026-10-13/README.md).

The broad goal remains active. This improves inspection of an existing observation
layer; automatic procedure extraction, independently validated macro semantics,
and useful comparisons across training populations remain unproven.

## Content adequacy before relationship generation — 13 October 2026

The previous turn was verified progress. Added an experimental finite-choice
assessment of each frozen local content plus whole-inventory coverage before
relationship acceptance in the staged file workflow. A named source review can
resolve a disagreement while keeping raw Jev choices and all original contents.
Omissions, unresolved items and material defects block advancement; no confidence
threshold or automatic rewriting is introduced.

Three bounded new Jev requests reused the earlier Luna proposals through the
configured proxy: 8,419 input and 923 output tokens. The assessor caught the known
dropped hedge but disagreed with prior source review on two other contents.
Named development reviews retain eleven contents and withhold one. These are
known examples, not independent accuracy evidence. Replay made zero new calls.
49 focused tests passed. No live annotations, relations or dashboard data changed.
See [trial, cost and interpretation limits](../research/work-content-audit-2026-10-13/README.md).

The broad goal remains active. This stage is not enabled for all training data;
the observed overhead and disagreements require evaluation before broad use.
Reliable automatic content extraction and macro interpretation remain incomplete.

## Execution evidence on work branches — 13 October 2026

The previous turn was verified progress. Work-map cards now distinguish their
reported decision state from linked attempts, checks and repeats. Branch details
expose distinct actions, returned feedback and assessments, with exact source
drilldown. Unbound work stays visibly unmeasured; subplan totals are explicitly
inherited and deduplicated across shared memberships.

46 Python and 20 JavaScript tests passed. Read-only replay of the saved software
example reconciled twelve linked actions across five temporal cutoffs. Live
browser checks covered action/feedback/unit navigation, coverage highlighting,
reload and a 390px viewport. No provider calls or annotation writes. See
[evidence and limitations](../research/outline-execution-2026-10-13/README.md).

The broad goal remains active. Only one of this example's twelve work items has
a direct plan binding; two ancestors inherit it and nine remain unmapped.
Automatic general work/action correspondence and verified work-result linkage
are still incomplete. This projection does not establish which branch solved
the task or label unbound branches as ignored.

## Explicit execution-scope correspondence — 13 October 2026

The previous goal turn was verified progress. Inspection showed that two unmapped
subgoals already had plan-step action evidence, but no way to associate it with
their outline scope. Version 2 reviewed outlines now store exact work-to-plan or
work-to-step bindings with citations and rationale. The existing review UI edits
them, and the hierarchy uses them without lexical matching or reclassification.
Version 1 observations remain unchanged; explicit mode never falls back silently.

A named development review binds the report approach and its two named steps.
Drafting now exposes one attempt and conversion four attempts with three repeats;
the parent union remains twelve distinct actions. Seven work items stay unmapped.
The original graph, units and action annotations remain unchanged. 66 Python and
20 JavaScript tests passed; live UI checks covered scope details, quote reuse,
unchanged revision saves and a narrow viewport. No provider calls. See
[review, contract and limitations](../research/outline-bindings-2026-10-13/README.md).

The broad goal remains active. This adds a practical reviewed correspondence
path, not validated automatic general scope matching. The existing action-role
judgments and three new bindings remain development observations; independently
validated automatic extraction and verified work-result interpretation are still
required for the full objective.

## Finite scope-link candidate experiment — 13 October 2026

The previous goal turn was verified progress. Added deterministic candidate
enumeration over existing work and plan scopes, grouped by context and source
cutoff. Jev selects among bounded scope relationships using raw argmax; only
same-scope choices become unpublished binding candidates. No generative proposer
is needed. The file workflow retains raw responses and creates an incomplete
named-review draft, while unchanged semantic inputs reuse identical requests.

Two bounded calls recovered the three prior software bindings and two authored
instance-control matches without extra same-scope choices in eighteen development
comparisons. Four nonmatch-category disagreements remain; those choices are not
promoted to hierarchy or dependency measurements. Usage was 13,407 input and
1,690 output tokens; executed replay made zero new calls. 44 tests passed. No
live graph edits or observation recomputation. See
[trial, workflow and cost limits](../research/outline-scope-match-2026-10-13/README.md).

The full goal remains active. This is not independent accuracy evidence or a
training-wide default. It cannot supply missing work contents, connect arbitrary
unplanned actions or verify outcomes. Those parts of the general correspondence
and macro-observation foundation remain unfinished.


## 14 October 2026 — Evidence-led map reading

Improved unit-card meaning, question-to-case navigation, unavailable-observation
handling, direct unit navigation, narrow canvas space and dashboard information
order. The retained software graph has 105 reachable cards; source-only examples
retain all cases without presenting missing semantic observations as zero.
66 JavaScript checks passed and desktop/narrow browser interactions were exercised.
No provider calls or saved-data recalculation. See
[implementation and verification](../research/map-reading-2026-10-14/README.md).

This addresses the user’s current UI reading/navigation request. The broader goal
remains active; independently validated semantic extraction and general work/action
correspondence are still unfinished.


## 14 October: start, attach and replay across training stages

The usability foundation now includes `start`, `doctor`, managed append-only JSONL collection, and a shared batch/live replay path. Stable producer identities and durable cursors preserve accepted records through partial writes, outages, restart and delayed revisions. UI setup supports experiment, format and filename selection; collection status distinguishes waiting, backlog and invalid records. Capture does not schedule paid inference.

The installed wheel was tested outside the checkout without optional dependencies on Windows/Python 3.12. Fifty focused ingestion/startup tests pass, alongside the portable-contract suite and a desktop/mobile browser audit. Linux/macOS/Python 3.11–3.13 CI was added but has not run remotely here. See [setup and boundaries](GETTING_STARTED.md) and [validation](../research/portable-intake-2026-10-14/README.md).

The next engineering gates remain self-contained relocation of legacy review workspaces, large-scale collection throughput and native cluster/runtime validation. The broader accuracy and RL-research goal remains active.


## 14 October: portable inspection snapshots and output relocation

Added online workspace snapshots and non-overwriting restore, preserving source/graph/measurement identities, reviews, investigations and frozen legacy observer results. Restored copies pause source collectors and queued inference. Paused connections can change output location while retaining producer identity and JSONL cursors. Full original extraction/candidate workspaces remain external; preserved structural audit receipts do not establish independent semantic accuracy.

Verified 191 live-workspace sources, 210 graphs, 400 training records and six investigations; all 42 original tables and all graph documents match the restored copy. One applicable legacy observer was archived without an unavailable result. Fifty-five focused tests passed in both the normal and dependency-minimal environments; installed-wheel HTTP download/CLI restore and browser relocation checks passed. No provider calls. See [audit](../research/workspace-transfer-2026-10-14/README.md). The full product goal remains active.


## Intake lifecycle adaptation — 14 October 2026

Extend the existing startup/export/transfer work with structured JSON snapshot collection and a real source preflight. One collector configuration can attach before output exists, observe running snapshots, recover after restart and replay completed files. Source normalization is shared with HTTP ingestion; explicit envelopes retain transport-independent identities. Raw files use stable relative-path identity and never infer completion from inactivity. Preview is bounded and separates usable source evidence from semantic analysis prerequisites. No model provider is called by capture or preflight. This improves the common intake contract; it does not establish native runtime support for every trainer or all operating systems.
