# Population monitoring workspace

## Compare training windows

Use **Compare windows** on the overview or a measure card. Select one experiment
and two disjoint, inclusive recorded-step ranges. The result saves the selected
source revisions, monitor definition and exact measurement receipts. Open
**Baseline cases / Current cases** to follow a receipt into the rollout map;
Back to Overview restores the saved comparison. Download evidence exports the
same frozen result. Reopening it never refreshes its population implicitly.

The comparison works for recorded metrics, graph requirements and saved analysis
operators. Thus source success and action cost use the same workflow as feedback
assessment, work returns or recovery, without adding labels or model calls.
Annotation accuracy remains a property of the selected observation protocol.

- Cohorts retain environment/version, adapter, split, sampling, task revision,
  reward definition, generation/use clock and declared source/selection context.
- Opportunity rates pool numerators and decidable denominators. Other measures
  give each measured rollout equal weight. Missing and pending rollouts, unknown
  opportunities and coverage changes remain visible beside the values.
- When all other configuration fields agree and every environment stratum has
  measurements in both windows, the summary also applies baseline weights to the
  current values. Observed change = within-cohort change at baseline weights +
  composition component. This is descriptive standardization, not causal or
  statistical inference. Changes in missingness can still bias either figure.
- Recorded task-ID distribution changes are called out inside each cohort.
  Unknown metadata does not establish matched task difficulty or configurations.
- A changed annotation invalidates the current display until its measurement is
  reconciled. Old receipts remain readable. One WAL read snapshot binds dashboard,
  case and comparison reads; a slower worker changing the latest-result index
  triggers reconciliation even without a new source arrival.

Python requires no UI or export:

```python
from rilldex import Workspace

ws = Workspace("workspace.sqlite", experiment="my-training-run")
monitor_id = ws.table("monitor_definitions").rows[0]["monitor_id"]
comparison = ws.compare_monitor(
    monitor_id, baseline=(40, 47), current=(48, 55), save=True
)
for cohort in comparison["cohorts"]:
    print(cohort["cohort"], cohort["delta"], cohort["current"]["coverage"])
same_result = ws.monitor_comparison(comparison["id"])
recent = ws.saved_monitor_comparisons()
```

`save=False` (the default) is read-only. `save=True` and
`POST /api/monitoring/comparisons` persist the same schema in SQLite;
`GET /api/monitoring/comparisons/{id}` reopens it. Full workspace backup/restore
preserves these comparisons. The independent custom-Python results sidecar is
still separate; a full workspace archive does not yet bundle that sidecar.
Comparisons refuse more than 100,000 selected rollouts rather than silently
truncating. Select smaller windows or an environment at that boundary.

### Engineering basis, reviewed 15 October 2026

The [previous workflow review](../research/rl-engineer-workflows-2026-10-11/README.md)
and [community review](../research/universal-rl-review-2026-10-11/README.md) prioritize
population identity, conditional behavior measures, missing evidence and exact
case navigation. This increment connects those existing pieces.

[AReaL's performance guide](https://github.com/areal-project/AReaL/blob/main/docs/en/best_practices/algo_perf.md)
distinguishes generated, evaluation and training-consumed reward and warns about
distribution changes. That supports explicit population/clock separation rather
than one unexplained reward curve. These window comparisons concern source
rollouts; the existing Training samples/Training health views retain consumed
sample populations. No consumption is inferred from a source monitor.

[verl rollout correction](https://verl.readthedocs.io/en/latest/algo/rollout_corr.html)
separates importance weighting, rejection masks and policy mismatch diagnostics.
Those meanings should remain native evidence in Training health, not be renamed
as generic behavior quality. The comparison workflow consumes declared measures
without assuming GRPO, a fixed group size or one inference server.

[Slime's producer-failure report](https://github.com/THUDM/slime/issues/2399)
describes errors that can leave a consumer waiting or silently skip groups. This
is an upstream issue report, not a reproduced defect in our collector. It
reinforces keeping failed/pending states and coverage in the population, testing
restart recovery, and avoiding the claim that unavailable follow-up is failure.

## Work distributions above activity counts

Added 11 October 2026. **Overview → Behavior distributions** now includes **Work recurrence** and **Procedure changes**, alongside existing activity, feedback and failure views. These consume the existing versioned `work_episodes` and `adaptation_patterns` analysis operations, with cached receipts and zero new model calls.

| View | Population and exclusive categories | Interpretation |
| --- | --- | --- |
| Work recurrence | Every native recorded agent action: consecutive recurrence, return after intervening work, recurrence across an observation gap, or recurrence not established. | Same-work identity requires positive stored evidence. The last category includes first occurrences and missing/unresolved observations; it is not a novelty measure. Missing action units retain their source positions and denominator weight. |
| Procedure changes | Recorded same-work recurrences: same procedure, changed settings/inputs, different procedure, or unresolved comparison. | Uses the exact-pair version-3 procedure observation and its work-instance check, not dispatch-string differences. Unknowns remain in these distribution shares; the existing conditional procedure-change monitor has a different denominator. |

Compare recorded training windows with equal-rollout or pooled-opportunity weighting. Missing annotations break the trend rather than becoming zeros; absent training coordinates produce a static distribution. Reviewed rollouts without recurrence opportunities remain distinguishable from unobserved rollouts and have no procedure share. Existing task/configuration and observer separation apply.

Choose a category, open its contributing rollout, then inspect the exact recurrence in **Work overview**. The link pins the graph, episode and source unit. The selected work card and relationship inspector retain every witness; a witness opens the original **All units** card. **Back to behavior distributions** restores the comparison. The map now uses the same validated procedure projection as the chart, preventing a legacy or unresolved raw comparison from acquiring a stronger display label.

Source identities, analysis plans, category memberships, coverage and unknowns are included in the snapshot export. New source or semantic graph arrivals use the existing monitoring refresh stream. A local authored late-annotation test updated the open view in about 5.5 seconds; this is one observed update, not a production latency guarantee.

[Public three-domain replay, authored chart controls, browser evidence and limits](../research/work-distributions-2026-10-11/README.md). This connects existing semantic evidence to useful population views. It does not independently validate that evidence, classify exploration/exploitation/deviation, or establish behavior changes through real training.

## Requests and plans above the rollout units

The existing rollout map now shows a **Requests & plans** sequence when its saved
observer includes expressed-scope memberships. Select a block to read the actual
request or organized Plan and open any contributing card in the complete map.
An individual unit also links back to its scope. Earlier/Later controls traverse
long sequences. Unresolved and no-work observations remain separate; multiple
scopes attached to one contribution appear together without duplicating it.

Scope nodes and membership/source edges are persisted graph data, so export and
subsequent analyses retain the same evidence. Historical graphs are unchanged.
This describes expressed scope: request edits, Plan changes and repeated scopes
are not automatically inferred objectives, task phases, deviation or success.

[Three-source audit](../research/strategy-profiles-2026-10-08/work-scope-graph-audit.json)
and [software view](../research/strategy-profiles-2026-10-08/work-scopes-software-local-adjustments.png).
The 944-test Python suite and live browser checks pass. No model calls were added;
membership semantic accuracy is inherited and remains independently unvalidated.

## Work overview and unit map

Open a rollout and select **Work overview** to follow named work targets, grouped consecutive attempts, returns, expressed scopes and correction links. Select a card to inspect its constituent attempts, or a relationship to open its source witnesses. A witness switches to **All units** at the original contribution while retaining the full trace. Direct unit/evidence links still open the unit map by default. `level=work` opens the overview directly. Missing work observations stay explicit, and separate cards do not imply exploration or a changed goal. [Source audit and interpretation boundaries](../research/work-navigation-2026-10-09/README.md).

## Software repair phases

Investigations of imports explicitly marked `task_family: software_repair` now include **Software repair workflow**, separate from base activities. It compares phase shares with equal rollout weight and shows every action through labeled phase-block cards. Select a block to inspect its commands and exact source graph. Unknown dispatches remain visible and stay in denominators. No phase profile is inferred merely because a rollout contains programming tools. This is an experimental command/history baseline, not a validated strategy detector or a passing-test measure. [Rules, public examples, audit and remaining work](../research/task-phases-2026-10-08/README.md).

## Activity-sequence correction

The prior investigation chart applied an aggregate alluvial renderer to a single
rollout, combined Orient/Plan and Construct/Report into distribution groups, and
showed only ten blocks before a generic tail. Its ribbon counts were consistent,
but the view did not support an interpretation of task phases or work relations.
The reported software trace contains 68 agent units: 27 Orient, 2 Plan, 28
Construct, 9 Inspect and 2 Report. Its activity preview was not a strategy map.

`activity-sequence/4` preserves the individual activity labels, exact unit IDs,
source spans and source excerpts. A single observed rollout now uses an overview
of all blocks and paginated labeled cards. Every unit links to its original graph
and selected card. Multiple observed rollouts can use count-scaled aggregate
flows with visible labels, explicit preview length and complete-sequence
drilldown. Padding stops after all observed sequences end. Transition tables
show activities actually present in the selection. Gaps are preserved and
observation end is not task completion. Legacy saved analyses keep their original
data with a grouping warning and an explicit reanalysis link.

Validation: 25 process tests, 13 analysis-monitor tests and 12 investigation tests
pass. Both the existing process-browser workflow and the new
`activity-sequence-browser.cjs` pass on the live app. The latter reaches all 68
units across all 63 blocks of the reported trace, verifies exact graph/unit
navigation, population drilldowns and narrow layout. No inference was performed.
This corrects aggregation and presentation; task-purpose classifications and
independent annotation accuracy remain separate unfinished work.

[Corrected single-rollout view](../research/strategy-profiles-2026-10-08/activity-sequence-corrected.png).

## Persistent analysis measures

The investigation projections now participate in the same background service as recorded metrics and graph requirements. Choose **Add monitor → Work episodes & verification**, or select a supported pattern bar in an investigation and use **Monitor this behavior**. That creates a persistent definition for current and future saved observations using the selected protocol. It does not annotate missing trajectories or call a model.

Supported measures:

- Counts of consecutive recurrences, returns after intervening operations, and recurrences spanning observation gaps.
- Counts of recurrences with recorded assessments or attempted corrections.
- Counts of exact-pair same, reconfigured or different procedure observations.
- Recorded-criterion recovery, applicable verification at delivery, and check-input binding rates.

Counts describe positively recorded witnesses; absent relationships do not establish behavioral absence. Procedure comparisons apply to the exact inspected pair. Recovery remains scoped to a recorded criterion and the existing next-three-check window. It requires comparable captured state and relevant recorded change, and does not establish whole-task success or causal benefit. Verification requires a captured delivery requirement. Missing state or unresolved results remain unknown.

Rates retain numerator, decidable denominator, total opportunities and unknown opportunities. Logged-step summaries pool the numerator and denominator; they also retain unknown opportunities from entirely unmeasured rollouts. Every-rollout views retain individual values. Missing training coordinates never become synthetic iterations.

### Definition and execution contract

For example, `POST /api/monitoring/monitors` accepts:

```json
{"definition":{"name":"Returns to earlier work","kind":"analysis","observer":"software-local-adjustments","group":"Behavior","analysis":{"measure":"returns"}}}
```

The response pins the current extraction/measure version and includes the full measure definition. Options come from `/api/monitoring/options` under `analysis_measures`. Recorded-state measures use `observer: source`; work-episode measures require a semantic observer. Editing creates a new immutable monitor and pauses the replaced definition. Retired extraction versions cannot silently classify new inputs; their historical values and evidence remain readable.

The background service uses the existing content-addressed investigation plans. Two measures over the same graph reuse the same extraction node. Measurements preserve their input graph, source hash, output, plan, definition, complete opportunity/case set and exact evidence IDs. `/api/monitoring/values/{id}` reconciles these bindings and the arithmetic before serving a drilldown. Selecting a case highlights its original nodes/edges while preserving the whole rollout. Values are also selectable as investigation signals and correlations.

### Validation and limits

The [live receipt](../research/strategy-profiles-2026-10-08/analysis-monitor-audit.json) records two persistent measures over the existing public software trace: **five returns** and **eight recurrences with attempted corrections**. They share one cached projection; replay uses zero computation and zero inference. The trace has no training coordinate, so these appear as inspectable values rather than a training curve. Other rollouts lacking this observer remain waiting. No new Luna or Jev calls were made.

The 936-test Python suite passes. Thirteen new tests cover source/version contracts, shared cache reuse, automatic background updates, annotation revisions, historical receipts, absent observations, pooled opportunities, missing coordinates, value/projection reconciliation and overlapping refresh reads. Recorded-state controls establish arithmetic and binding behavior; they are authored fixtures, not observed training improvement. An unresolved result now stays outside the decidable delivery-verification denominator. Derived work-state graphs no longer inflate semantic-map coverage.

The [browser check](../tests/analysis-monitor-browser.cjs) covers one-click promotion, editor configuration, automatic materialization, receipt-to-case navigation, whole-map highlighting, missing-coordinate disclosure and a narrow viewport. [Monitor card](../research/strategy-profiles-2026-10-08/analysis-monitor-card.png), [evidence view](../research/strategy-profiles-2026-10-08/monitor-episode-evidence.png).

Independent semantic accuracy, sufficient annotated training populations, real producer state capture and controlled feedback evaluation remain unestablished. The service refreshes saved observations; automatic general semantic extraction is a separate unfinished requirement.

The experimental [direct feedback-assessment worker](FEEDBACK_ASSESSMENT_MONITOR.md) now retains complete opportunity denominators and source-event links, with case drilldown in the same whole-rollout map. Its initial selector failed source review; the revised pass has completed six public traces after provider recovery, with two disagreements against frozen source expectations. Neither is enabled as a dependable live measure; independent semantic accuracy remains unestablished.

The main workflow is a population of rollouts → saved monitors → per-rollout charts → contributing cases → whole-rollout evidence. A point-neighborhood graph is not the product's starting screen.

## Persistent backend

SQLite already retains immutable rollout property graphs with typed nodes, directed relationships, adjacency indexes, source spans and observer identity. `tracker/monitoring.py` adds:

- `monitors`: immutable measurement definitions, enabled/paused state and creation time. Editing creates a new definition and pauses the prior one.
- `monitor_values`: append-only values keyed by monitor, rollout and exact input identity. A graph or source revision creates a new value and preserves the old evidence.
- `monitor_latest`: rebuildable current-value pointers. Superseded producer snapshots remain historical and do not enter current population charts.
- `monitor_service`: last completed synchronization receipt.

The server checks saved input identities every five seconds, independent of browser visits. New rollouts and saved observer results enter enabled monitors automatically. Restarting the app resumes from the database. This is an application process, not a scheduled Codex automation. It computes from saved observations; it does not start semantic extraction or spend model API credits.

Each value retains its source hash, observer or graph identity, numeric value, numerator/denominator where applicable, status, reason and evidence IDs. Graph queries also retain exact witness paths. Unknowns, incomplete imports and missing training coordinates are not converted to zero.

## Research workflow

- **Overview `/`**: simultaneous metric cards, every-rollout lines and a trailing mean of up to 32 records; optionally show means at logged training steps. Missing values and missing iteration ranges break lines. The within-batch order is the recorded source-file order, not wall-clock generation time. Each compatible experiment/environment/split/reward definition remains a separate series.
- **Monitors `/monitors`**: add recorded metrics or explicit relationship patterns; choose the observation protocol, starting activity, later relation, window and evidence connection. The written question names the executable rule; arbitrary natural language is not silently treated as a query compiler. Definitions apply to current and future saved rollouts. Pause/enable and immutable edits retain history.
- **Rollouts `/runs`**: search and paginate the scoped population; distinguish semantic maps from source-only traces. Chart and monitor case tables use the same scope. Case exports include the monitor definition, scope and contributing measurements.
- **Rollout `/semantic-map?run=…`**: all semantic units, unannotated source records and saved plan stages in one connected canvas. Selection highlights neighbors without removing other cards. Stage-specific edges use their recorded stage identity; stage order and precedence come from stored plan content. Search, zoom, pan, a whole-trace navigator and recorded-moment jumps support long traces. Lines open their source evidence; cards open natural-language contributions, targets and source excerpts.

Graph ratios are **recorded-match fractions**, not independently validated behavior rates. Binned graph values pool matching anchors and eligible anchors, rather than averaging unequal rollout ratios. The UI names partial relationship coverage. Experimental tampering and answer-search detectors remain labeled experimental; rubric penalties are not evidence of reward hacking.

## Current real-data verification

The workspace has 3,088 imported rollouts, including 3,072 public training generations in six logged batches. Those batches support reward, response length and rubric metrics but have no saved semantic-unit graphs. Three other rollouts have semantic maps, without training coordinates. One selected software observer records assessment paths for 4 of 9 inspection anchors. The saved revision-from-inspection-feedback monitor has 0 recorded matches over those 9 anchors; partial annotations do not establish absence of the behavior.

The software map displays 105 cards: 101 semantic units, one uncovered source instruction and three plan stages. Selecting a card retains all 105. Recorded returns after executor error reports are visible as connections; they do not establish whole-task failure or successful recovery.

Verification: 749 Python tests pass, including nine new monitor tests for incremental updates, service operation without a browser request, graph revisions, input mismatches, immutable edits, scope, missing coordinates, weighted ratios and incomplete snapshots. Three new JavaScript map checks cover source/semantic coverage, declared stage order and exact stage link routing. Browser verification covers chart-to-rollout navigation, custom monitor creation and automatic materialization, scoped cases, and whole-map selection. These are implementation checks, not independent semantic accuracy measurements.

Remaining research work: general and independently evaluated base extraction; complete relation opportunity coverage; stable observers on actual training streams; validated diagnostic boundaries and appropriate task/evaluator context. The workspace now exposes these gaps instead of inventing monitoring curves from unrelated examples.

## Saved measurements linked to exact evidence

Chart points, unplaced values and case-table links now carry their immutable `value_id`. `/api/monitoring/values/<id>` resolves that value's source, definition, input record and graph, checks content identities and reconciles the numerator/denominator against its contributing cases. The map opens that saved graph, including after a later annotation or producer revision. It never borrows an unrelated latest semantic graph for an unbound legacy or diagnostic measurement. New semantic metric records retain their exact graph binding; rebuilding derived display metadata reuses the first binding when the semantic measurement itself is unchanged.

**Explain value** lists all contributing starting units, the recorded matches, the unestablished remainder, the inspected window and each stored witness path. Selecting a witness highlights its original cards and lines without removing any other cards. The saved source, graph, metric definition, input record and limitations can be downloaded together. This export establishes computational lineage, not semantic accuracy.

The architectural reference is OpenTelemetry's [metric exemplars](https://opentelemetry.io/docs/specs/otel/metrics/data-model/#exemplars), which associate recorded metric values with trace context. Here the analogous identity is a versioned rollout measurement linked to its graph and source evidence; this is not an OTLP implementation.

Verification on the unchanged software example: an independent SQL join over stored inspection, feedback and assessment edges returns the same four matched anchors and nine starting units. The five remaining anchors stay **not established**, with no behavioral-negative count. The arithmetic check and four source excerpts are in [measurement-audit.json](../research/monitoring-workspace-2026-10-08/measurement-audit.json); reproduce with `python scripts/audit_monitor_evidence.py VALUE_ID`. The revision monitor's zero recorded matches likewise does not establish behavioral absence. Source review confirms the four snippets express assessments; it does not adjudicate the correctness of those assessments or recall across unlinked cases.

759 Python tests and three map-layout checks pass. New tests cover graph replacement, historical producer sources, wrong rollout IDs, corrupt receipts, zero versus unknown, exact witness membership, bound semantic metrics, unbound legacy fallback and links from chart points. Browser checks retain all 105 cards, highlight the three units/two edges of a witness and show the five unresolved cases. The downloadable API response matches the stored receipt; a mismatched rollout request is rejected.
## Adaptation at recurrence

Investigations include **What changes when work is retried?**: procedure comparisons crossed with separately linked preparation or correction in the retry. Select an episode count to inspect its source relationships. Switch to mean within-rollout shares to compare populations without weighting long trajectories more heavily. Every recorded recurrence remains in one cell, including unknown comparisons and missing correction links.

Save **Same procedure after preparation**, **Procedure change fraction**, or **Different procedures** as persistent monitors. Their exact definitions and source receipts are retained; unknown comparisons stay outside the change-rate denominator. Training plots use only recorded training coordinates. This layer reuses saved observations with no new model calls. [Evidence contract and current limits](../research/adaptation-patterns-2026-10-09/README.md).


## From behavior distributions to exact cases

Selecting an earlier/later category bar opens every contributing case in that
window. Fixed-task comparisons keep the shared-task restriction. Evidence can
also be scoped to both windows, the whole cohort, outside-window cases or
unplaced observations. Overlapping windows do not duplicate cases.

Find target, source text or rollout searches saved descriptions and exact
recurrence source text. It filters evidence only; chart weights and denominators
stay unchanged. All matching cases are paginated. Exact recurrence rows show
source action positions, earlier response excerpts and expandable earlier/later
dispatches. The case link opens the frozen map; returning restores the category,
window, task scope, search and page.

Export matching cases includes all matching pages, the original distribution
snapshot identity, definitions, points and analysis receipts. Unknown procedure
judgments stay unknown even when displayed commands differ. See
[replay and browser validation](../research/distribution-cases-2026-10-13/README.md).
