# Requested checks, operations and returned evidence

7 October 2026. Development observer, not a validated verification metric. Local units and work records remain unchanged; this layer begins with their selected readable contents. It adds no navigation tab or base activity category.

## Questions kept separate

1. **At dispatch:** Does the actual operation attempt this retained check, prepare for it, have no supported correspondence, or remain unresolved? Later responses and approvals are excluded.
2. **At response:** Does this particular recorded payload supply sufficient, partial, no answering evidence, or unresolved evidence for the same check version? This question is independent of the dispatch-role answer. Incidental evidence is possible.

Candidate checks come from the requested-check clauses retained in the state at dispatch. Requirements and attributed claims are not converted into checking work. Retired clauses are not current candidates. Sources and record/clause versions are retained. A source call identity binds a response to its action; no adjacency heuristic is used.

Sufficiency means evidence available in the recorded response for the requested question. It does not mean that a test passed, an agent communicated the answer, a future shipment was performed, or the environment is truthful. A failing regression test can answer whether the test passes. A failed lookup or another card's balance does not supply the requested card's balance.

## Adjacent methods and adaptation

[ALCE's evaluator](https://github.com/princeton-nlp/ALCE/blob/main/eval.py) checks support using cited passages and separately examines unnecessary citations. This suggests isolating the evidence actually claimed to support an answer, rather than allowing surrounding narrative to substitute for it. Its sentence segmentation, NLI model and metrics are not our unit standard or validated RL measures; none of its models were installed or called. [QASPER](https://aclanthology.org/2021.naacl-main.365/) collects answers and supporting evidence separately, reinforcing that identifying related text and establishing an answer are different tasks. These are methodological adaptations, not transferred accuracy claims.

## What the first real pass exposed

The first `requested-check-evidence/1` pass used prior context and batched the two checks. The identical profile responses at e25 and e31 received different delivery-evidence judgments: sufficient and partial. An authored wrong-card response was also incorrectly selected as sufficient for the requested balance. Both the real pass and its failed control remain saved and replayable.

`requested-check-evidence/2` changes the response question's evidence scope. Each response/check pair gets the specific attributed terms and their source references, the actual dispatch, the linked response and governing instructions. Other conversation and selected interpretations of the action are excluded. Dispatch judgments remain unchanged and reuse their saved decisions. The response definitions distinguish a negative test answer from inability to retrieve a requested value. All selection remains raw argmax; no confidence threshold or model replacement was introduced.

Long responses use bounded readable ranges with explicit omissions. The complete raw response is not smuggled back into the model packet through its subject field. Recorded source remains unchanged and available. This is a text observation; encoded media is not treated as visually inspected evidence.

## Current real-source selections

The existing retail trace has six dispatches; three occur after retained checking requests, producing six action/check pairs. The later profile lookup has no selected check correspondence, but its response is judged separately.

| Recorded operation/response | Balance request | Delivery confirmation |
| --- | --- | --- |
| First profile lookup, e24 | Prepares | Prepares |
| Profile response, e25 | No answering evidence: only the other card's balance | Selected sufficient; scope remains under review |
| Exchange dispatch, e27 | No check correspondence | No check correspondence |
| Payment-method error, e28 | No answering evidence | No answering evidence |
| Repeated profile lookup, e30 | No check correspondence | No check correspondence |
| Repeated profile response, e31 | No answering evidence | Selected sufficient; scope remains under review |

The revised pass is consistent on the identical responses, but consistency does not establish correctness. A profile establishes an address on file, not where a particular future replacement will actually ship. Whether this answers the intended confirmation request requires independent adjudication. The new map displays this review point beside the check results. These judgments must not become counts of verified fulfillment.

The map adds four selected connections: two preparation links and two response-evidence links. It still has 30 local participant contributions, six recorded responses, six dispatches and five action-target groups. The total relation count is 19. These are representation counts, not training metrics. The old observer remains selectable.

## Validation and cost

- All local contribution records and requested-work records exactly match the previous observer. Dependency replay verifies each finite choice against raw argmax.
- Four pre-selection assistant source expectations about missing balance/destination evidence match the returned choices. These are source checks, not independent accuracy.
- Eight authored contrasts exercise matching values, wrong entities, negative tests, retrieval errors, partial scope, prerequisites and incidental evidence. Evidence choices improve from 7/8 to 8/8 expected selections. Dispatch choices remain 7/8: the broad profile retrieval selects preparation where the authored expectation was attempt. Combined exact case agreement remains 7/8. Expectations were not rewritten after the run.
- Five new structural tests cover distinct cutoffs, exact versions, response identity, omitted text, source isolation, raw-argmax replay, missing responses and complete batching. All 477 Python tests and five UI projection tests pass; JavaScript syntax is checked. Software tests do not establish semantic accuracy.
- V1 real selection used six requests, 55,654 input tokens and 831 output tokens. V2 uses nine distinct requests including three reused dispatch decisions: 60,591 input tokens and 843 output tokens across the complete packet set. Its six new response requests account for 33,036 input tokens and 433 output tokens. The authored controls used 16 initial calls and eight new response calls. Upstream candidate authoring and manual review are excluded.

Artifacts: `research/check-evidence-2026-10-07`, `research/check-evidence-isolated-2026-10-07`, and the corresponding `check-evidence-controls*` directories. `tracker/check_correspondence.py` provides replayable file-based execution with explicit harness versions. The existing Jev API is the only model service used.

## Transfer to agent-stated software checks

The real [OpenHands drug-response trajectory](https://github.com/metauto-ai/agent-as-a-judge/blob/43c2fa7b84ef0c1522e8250576e6798bace29dd0/benchmark/trajectories/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML.json) already has 68 selected agent contributions and 33 bound responses. Its agent-stated checking work can occur inside an Orient contribution. It must not be converted into a user request, a new Plan or another base activity.

`tracker/stated_checks.py` accepts externally proposed, source-bound checking contents and selects a complete bundle through Jev. Independently inspectable parts remain contents of the owning unit. The source's expression/action binding retrieves dispatch candidates; Jev then judges each correspondence. Responses are judged independently and bound by source call identity. The pass never assumes a persistent active checklist or replaces a missing source association with adjacency. Other adapters can use the same contract when they supply the required evidence bindings.

Ten real contributions were selected for development inspection: six checking expressions and four construction/next-step contrasts. The six selected checks contain nine parts. The other 25 prose contributions remain explicitly uninspected by this layer. The candidate meanings and pre-selection expectations are implementation-assistant authored, not independent gold or unattended generation. All original units, activities and Plan structures remain unchanged.

The first pass exposed contamination between parts of a check: a directory listing was labeled partial evidence for both PDF presence and PDF contents, and metrics text was treated as partial visualization evidence. The revised `stated-check-evidence/2` packet names one checking target in the actual question and removes the other structured parts from that decision. Exact original source remains available. The failed first pass is preserved and replayable.

| Expressed checking work | Actual operation and evidence | Focused selection |
| --- | --- | --- |
| Inspect generated metrics | Read performance.txt; metrics returned | Attempt; sufficient evidence |
| Inspect visualization, in the same contribution | Same metrics-file read | No correspondence; no answering evidence |
| View visualization to verify results | IPython Image; inline image recorded | Attempt; evidence unresolved because pixels were not inspected |
| Establish working directory | pwd; `/workspace` returned | Attempt; sufficient evidence |
| Check PDF presence | ls results/; PDF listed | Attempt; sufficient evidence |
| Inspect PDF contents | Same directory listing | Preparation; evidence unresolved, versus the authored expectation of no answering evidence |

Five of six frozen source expectations match the focused choices, compared with two of six in the initial pass. These are development comparisons, not measured accuracy. The last disagreement remains visible beside the check in the map. An unspecified content acceptance criterion does not change the source fact that the listing contains no PDF contents. Generic visualization checking, image-path validation and PATH discovery versus package installation remain scope-review cases.

The new observer adds 13 selected connections inside the existing map: 101 unique source units and 125 total relations. Selecting the Orient unit, operation or response opens the same checking contents and evidence. There is no additional peer map or base tag. Missing pixels, uninspected contributions and source-review disagreements remain visible.

Validation: all 482 Python tests and five UI projection tests pass. The new tests cover temporal cutoffs, source-pair identity, candidate provenance, single-part reference scope, omitted text/media and raw-argmax replay. The live map document equals the saved projection. The first pass made 28 calls (101,778 input / 1,454 output tokens). The focused pass reuses ten content decisions and makes 18 new calls (59,017 input / 958 output tokens). Its complete 28-packet set totals 99,992 input / 1,462 output tokens. Candidate authoring and review are excluded. No additional model service was introduced.

Artifacts: `research/software-check-evidence-2026-10-07` preserves the failed pass; `research/software-check-focused-2026-10-07` holds the focused pass, proposals, decisions, source expectations and current map. Reproduce with `python -m research.software_check_evidence --focused`; add `--run` only when new API selection is needed. The API key is prompted without echo and retained only in process memory.

Browser review confirms the 101 unique units, unchanged Orient ownership, scope warning beside the PDF check, operation navigation, uninspected-image status and visible coverage. No page errors or horizontal overflow were observed. Receipt: `research/software-check-focused-2026-10-07/browser-review.json`; screenshot: `combined-evidence.jpg`. A fresh browser export was not tested.

## Applicability before contents; material separate from criteria

Versions 3–5 extend checking inspection to every selected agent prose contribution in the software, airline and retail traces: 35, 7 and 12 contributions respectively. Candidate construction reuses expressed local meanings, retaining the earlier nine software checking parts with their authoring provenance. It does not use a keyword or base-activity eligibility filter. This improves inspection coverage; it does not make the upstream, model-authored meanings complete or independently correct.

Version 3 separates two questions: the basis stated for judging a check, at the expression cutoff; and the material available in the bound response, at the response cutoff. A file can have no stated quality criterion while its contents are absent from a directory listing. Both facts can be observed without declaring a passing or failing check. The distinction is consistent with [Inspect's separate task, submission and criterion inputs](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/scorer/_model.py), but the particular extraction design and evidence choices here are ours. All six previously frozen software material expectations match the v3 selections. An airline permission request was nevertheless wrongly selected as checking work.

Version 4 strengthens the checking definition using the information-seeking versus action-discussion distinction described in [DIT++](https://dit.uvt.nl/). It keeps both real airline approval requests out of checking, and matches 16/17 authored contrasts, but selects five retail reports/assurances as checks. This is a failed generalization result, preserved under `research/checking-intent-2026-10-07`; it is not promoted to the app.

Version 5 makes applicability a separate bounded Jev question before selecting contents. The raw choice records expressed checking work, a report/assurance, a decision request, other contents or unresolved meaning. Only expressed checking work opens the content selection, which can independently reject the proposals. This is an extraction route inside the established contribution, not another base-activity tag. No confidence or margin threshold is used.

| Real source | Applicability inspected | Advanced to contents | Selected checking bundles | Preserved gaps |
| --- | ---: | ---: | ---: | --- |
| Software | 35 | 9 | 8 | One applicability/content disagreement; broad evaluation and image-path scopes need review |
| Airline | 7 | 1 | 0 | ID acquisition versus the mentioned future balance check remains a stage disagreement |
| Retail | 12 | 1 | 0 | One explicit future balance check lacks a faithful candidate; another is missed inside a mixed Report |

The five retail report bundles selected by v4 are no longer treated as new checks. Both airline yes/no approval requests select decision-only. The software pass retains the six earlier checks and additionally selects two requests to run evaluation and see results. These outputs must not be converted into verification rates: evaluation errors are observed feedback even where the selected material target is judged absent, and merely listing an image path does not establish how the converter resolves it.

The two applicability/content disagreements automatically create source-bound review requests. The rejected retail bundle creates a candidate-repair request. Both raw choices are retained; disagreement does not silently become a negative, override or new label. Missing source expression/action bindings remain missing, without a nearest-action fallback.

Twenty-one of 22 authored contrasts match their expected final content outcome. The ambiguous “Please confirm the booking” still selects decision-only instead of the expected unresolved option. One itinerary-choice case has an incorrect checking applicability followed by a correct `none` content selection; final agreement therefore hides a routing error. These are development controls, not independent accuracy. Source review also identifies the missed future check in the longer retail Report. All failures remain visible; no expectation was changed to match the output.

Validation: 490 Python tests passed after the staged implementation; focused tests also passed after adding disagreement queues. Ten map projection tests and JavaScript syntax checks pass. Earlier v2, v3 and v4 saved requests replay unchanged. The three served v5 documents exactly match their saved projections, with all original local units unchanged. The real v5 pass uses 98 requests, 408,435 input tokens and 5,529 output tokens; 35 control requests add 60,895 input and 2,021 output tokens. These figures exclude earlier failed runs, upstream candidate authoring and review. Replaying the completed pass made zero new API calls.

Artifacts: `research/check-material-2026-10-07` (v3), `research/checking-intent-2026-10-07` (v4), and `research/checking-role-2026-10-07` (v5). Prepare a new frozen study with `python -m research.checking_role_review --freeze`; run with `--run`; review saved decisions without inference by omitting flags. After the development run, `python -m research.review_checking_roles` attaches the source-reviewed limitations. Existing frozen inputs must not be overwritten; later revisions need new directories. The generic CLI also accepts `--version stated-check-evidence/5`. The same Jev API is the only model service used.

Live browser review confirms software specification/material separation and the e53 disagreement flag, the airline permission decision, and the retail candidate gap with unchanged Coordinate ownership. All 101 software units remain unique; no visible error, browser error log or horizontal overflow was observed. Receipt: `research/checking-role-2026-10-07/browser-review.json`; screenshot: `material-and-specification.jpg`. A fresh browser export was not tested.

The candidate gap is addressed by the separate revision below. Mixed report/intention coverage and later-operation correspondence remain unfinished.

## Source-validated candidate repairs

`tracker.check_candidate_repairs` accepts a response to a saved `check_candidate_repairs/<hash>.json` request. The response supplies zero to three checking bundles and an attributed producer. It can use exact source quotes or original offsets; quotes resolve to offsets without asking a model to count characters. Every bundle and facet must cite the owning contribution, and every citation must be within the original supplied generation context and cutoff. Changed requests, future or omitted evidence, forced selected answers, and malformed bundles are rejected. Citation validation alone does not establish that a proposed meaning is faithful.

The command prepares a new observation directory after replaying the old local extraction and checking decisions. It preserves the previous candidates, result, request and response with content hashes. Only the repaired row and its provenance change; unrelated content packets and the applicability packet remain reusable. An existing or nested destination is rejected. Running the normal checking CLI on that directory lets Jev independently select or reject the alternatives. No confidence threshold, manual choice override, new base tag or model service is introduced.

Response contract:

```json
{
  "schema": "stated-check-proposal-response/1",
  "request_hash": "<digest of the exact queued request>",
  "producer": "<author or configured generator and version>",
  "citation_format": "source-quotes/1",
  "candidates": [{
    "text": "<readable checking work, with actor/condition scope>",
    "evidence": [{"event_id": "<source event>", "quote": "<exact supplied text>"}],
    "facets": [{
      "id": "<local checking part>", "text": "<readable checking part>",
      "evidence": [{"event_id": "<source event>", "quote": "<exact supplied text>"}]
    }]
  }]
}
```

Repeated quotes require a `source_start` disambiguator. The file protocol accepts external generation but does not configure an unattended generator. Empty candidates remain an explicit gap for Jev to judge, not an inferred absence of checking. Requests caused by applicability/content disagreement have a different review contract and are not silently admitted as candidate rejections.

```text
python -m tracker.check_candidate_repairs SOURCE_DIR RUN_ID --request REQUEST.json --response RESPONSE.json --output NEW_DIR
python -m tracker.stated_checks NEW_DIR RUN_ID --run --version stated-check-evidence/5
python -m tracker.stated_checks NEW_DIR RUN_ID --audit
```

The real retail e19 Coordinate contribution says the user should supply the gift-card ID, after which the agent will verify the balance and finalize the exchange. The prior reused local work target described only obtaining the ID. The revised menu retains that alternative and adds: “Verify the balance of the gift card the user supplies for the $6.32 price difference, once its ID is provided.” It cites only e19 characters 681–831 and contains no later card identifier. Jev selects the new alternative (`c1`). All base units and activities, the other eleven checking observations and all 240 files in the original observer remain unchanged. No source-bound dispatch is available for this contribution, so the revision adds no action or outcome links.

The separate Report contribution still misses its future checking content. Specification chooses `test_defined`, although this Coordinate contribution states no explicit numeric passing threshold; that scope boundary remains visible for review. One correctly selected authored repair is not independent accuracy and does not establish general candidate recall.

Artifacts: `research/checking-candidate-repair-2026-10-07` contains the frozen pre-selection expectation, supplied response, immutable revision, raw decisions and preservation review. The **Checking contents · repaired development** observer uses the same combined map and inspector; its expandable repair history shows the rejected and revised candidates with citations. The prior observer remains available. The real repair made two Jev requests (11,394 input / 108 output tokens); replay made zero new calls. Authoring and review costs are excluded.

Validation: 495 Python tests and ten map-projection tests pass. New protocol tests cover request and source binding, future/omitted evidence, malformed proposals, preservation, row-local cache invalidation, independent rejection, immutable directory preparation, history tampering and zero-call replay. These verify software behavior, not semantic accuracy. Mixed-expression coverage, independent reference review, unattended generation, later-operation links, real RL comparisons and macro validation remain unfinished.

Browser review confirms the unchanged Coordinate activity, old and revised candidate meanings, the raw-selected balance-check target, its citations and the missing-dispatch notice in the existing inspector. The 36 displayed units are unique, and the served document equals the saved projection (14 unchanged relations). No visible error, browser error log or horizontal overflow was observed. Receipt: `research/checking-candidate-repair-2026-10-07/browser-review.json`; screenshot: `candidate-history.jpg`. A fresh browser export was not tested.

## Checking targets across intervening turns

`tracker.check_followthrough` adds a separate relation pass over already selected checking contents. For each check it retrieves all later selected dispatches by the same actor in the same trajectory. Native expression/dispatch pairs already inspected by `stated_checks` are reused, not rescored or duplicated. There is no distance, keyword or probability filter. This gives exhaustive pair coverage for the retained checking targets on these traces; missed upstream checks remain missed.

Each checking part receives two independent bounded Jev questions: whether the actual operation attempts, prepares for, does not correspond to, or cannot be matched to that historical target; and what material the linked response supplies. The first question ends at dispatch. The second uses attributed participant context available at dispatch to resolve the target, and only the exactly bound response as returned material. New terms between dispatch and response cannot rewrite its target. Earlier tool responses are excluded from response-material context. Long text and media remain explicitly unobserved where they were not inspected. Every selected choice is raw argmax, including negative and unresolved outcomes.

Historical target correspondence is distinct from an active-intention record. An operation can match an earlier target even after withdrawal. This pass does not establish current validity, compliance, authorization, causal motivation, success or fulfillment. Multiple earlier expressions can also refer to related work; links to both do not mean that two independent checks occurred.

| Development source | Selected checking bundles | Native pairs reused | Later action/check pairs | Checking-part pairs | Added selected links |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retail | 1 | 0 | 3 | 3 | 2 |
| Software | 8 | 8 | 97 | 115 | 42 |

In retail, the repaired e19 promise now reaches the later e24 and e30 account-profile lookups across user replies. Jev selects preparation for both, versus the pre-run assistant expectation of attempt; that boundary remains disputed. The e27 exchange operation has no selected checking correspondence. All three responses select absent for the requested card balance: the profile responses contain another card, and the exchange returns a payment-method error. A later user claim about a balance is not substituted for returned evidence. No successful charge or completed exchange is inferred.

In software, earlier evaluation checks now reach later script retries and metrics reads, while visualization checks reach the later image-display operation. Across 115 checking-part pairs the dispatch choices are 11 attempts, 25 preparations and 79 none. Response material choices are 6 available, 102 absent and 7 unobserved. These are observer outputs, not accuracy scores or task metrics. Source review identifies concrete weaknesses:

- Agent-authored Markdown returned by a write/edit tool can be selected as evaluation material. Its repeated metrics and GDSC claims are not a new evaluation execution or independent verification. Result-instance scope and attribution still need work.
- Several image-material choices select unobserved for Markdown containing only an image reference. The response contains neither recorded pixels nor omitted text. The inspector flags the missing omission/media basis without overriding the raw choice. Referenced, recorded-but-uninspected and inspected material need reliable separation.
- Broad evaluation targets and repeated expressions can overlap. Summing relation counts would overstate distinct checking work or progress. Active scope and intention history remain separate missing layers.

Eight authored cross-turn controls cover matching and wrong entities, an earlier balance claim followed by an error, a negative existence test, withdrawal, a changed subject and a PDF directory listing. All eight complete expected dispatch/material pairs match. These are implementation-assistant expectations, not independent gold or a transfer accuracy estimate. Real-source disagreements above remain visible and were not relabeled to improve the score.

The pass uses the existing combined map. An earlier contribution can focus its incoming operation links; the same inspector shows expandable later-operation candidates and each response's material choice, including pairs without a selected graph edge. This preserves the original source units and keeps negative evidence inspectable. Long source-review notes are expandable. No new peer map or overlapping activity tag is introduced.

Reproduce the frozen study with `python -m research.check_followthrough_review --prepare` only for a new copy of the original inputs. Use `--run retail`, `--run software` or `--run controls` to execute/resume, or omit flags to review saved selections. Do not rerun preparation over edited review notes. The generic CLI is `python -m tracker.check_followthrough DIRECTORY RUN_ID`; add `--audit` to replay saved evidence. Artifacts, expectations, complete raw requests/decisions and source-preservation manifests are in `research/check-followthrough-2026-10-07`.

The real retail pass uses six requests (38,668 input / 335 output tokens); software uses 230 (1,037,665 input / 12,820 output tokens). Both complete replays made zero new API calls. The sixteen control requests add 36,574 input / 896 output tokens; upstream candidate authoring is excluded. Exhaustive all-prior matching is a development coverage baseline, not yet an efficient training-scale retrieval design; any later pruning needs candidate-recall measurement.

Validation: 501 Python tests and eleven map-projection tests pass. New checks cover delayed retrieval, source order, actor/trajectory boundaries, reuse of native pairs, independent material judgments, dispatch/response cutoffs, exact call binding, long text/media omissions, replay and preservation of upstream observations. These establish software invariants, not independent semantic correctness. Evidence attribution, mixed-content coverage, current-intention histories, scalable retrieval, actual RL comparisons and macro observations remain unfinished.

Live browser review verifies retail's three-unit focus with two incoming preparation links, preserved source gaps and all three candidate operation/material outcomes in the shared inspector. The software returned-report inspector exposes the unsupported-unobserved warning without changing Jev's choice. Both API documents equal their saved projections: retail has 36 unique units/16 relations; software has 101 unique units/168 relations. No visible error, browser error log or horizontal overflow was observed. Evidence: `research/check-followthrough-2026-10-07/browser-review.json`, `retail-connections.jpg` and `software-material-review.jpg`. Fresh browser export was not tested.

## Response material and operation mechanism

The combined map now distinguishes a response's material form from the mechanism of its bound operation. This is a unit property plus target-specific connections, not another map or another base activity tag. The development observer covers all 39 bound responses and all 129 previously selected target/response pairs across the complete software and retail records.

| Question | Input and cutoff | Output and boundary |
| --- | --- | --- |
| What kind of operation produced this response? | Already selected local action contents and its dispatch, before its response | Read/lookup, compute/test, attempted change, statement relay, mixed, unresolved. Operation mechanism does not establish successful execution. |
| What material for this particular check is recorded? | One selected checking facet, scope available at dispatch, and only its bound response | Contents, partial contents, reference only, recorded but uninspected payload, absent, unresolved. This does not establish correctness, a passing check or a fresh evaluation. |

The distinction is informed by [W3C PROV-DM](https://www.w3.org/TR/prov-dm/): use and generation do not alone establish derivation; quotation and attribution are also distinct. We apply that distinction to the data model, without claiming that PROV supplies an extractor. No original author, causal derivation, source independence or result-instance identity is inferred from matching text or a tool-response wrapper.

The first delivery experiment (`response-material/1`) used the operation and response together. It confused an error with a relayed statement and a retrieved metrics record with computation in authored controls. The retained revision (`response-material/2`) follows the layer order: selected action contents → dispatch mechanism → separately inspected returned material. It withholds response text from the mechanism decision. All 129 real-source material decisions are reused exactly; no confidence threshold or post-selection override is added. The old experiment and all upstream checking choices remain replayable.

Concrete source review:

- The performance-file read e57/e58 selects read/lookup. The report creation preview e69/e70 and image-path edit preview e93/e94 select attempted change. Their repeated metrics do not become a new test run or independent validation.
- For three visualization targets, e70/e94 now select reference only in all six pairs. The actual recorded image response e64 remains recorded but uninspected in all three corresponding pairs. A path alone does not invent uninspected pixels.
- The e100 PDF listing supplies information for existence and only a reference for contents. Those two facets remain attached to one checking expression and one response.
- The retail profile/error responses e25/e28/e31 all remain absent for the requested card's balance. The failed exchange is an attempted change; its error does not turn it into a successful change or a test computation.

All fourteen frozen real-source form expectations and five selected delivery expectations match. These were authored by the implementation assistant on already reviewed sources, not independent gold. Broader review also finds eight software delivery changes and one retail change after withholding response output; installation/edit/conversion attempts now select change. The synthetic-data generation operation selects change, although its calculation plus artifact-production scope still warrants review. These counts are not general accuracy claims.

Ten authored controls test reference versus actual media, presence versus contents, written and echoed assertions, a failing test, wrong entities, a preceding claim followed by an error, and partial metrics. The first pass matches seven complete delivery/form pairs; the dispatch revision matches nine. **Unresolved failure:** the minimal `list_files("results") → report.pdf` control is still reference only for an existence target, although the real PDF listing is correctly selected as contents. That choice is preserved; no special-case override or further prompt sweep is applied. Generalization of this boundary needs further testing.

Other open questions matter for macro analysis. Broad requests to run a script and see results include execution/result-instance scope beyond material presence. The two similar evaluation expressions do not always assign the same form to a later report. Incidental cwd metadata and report contents in one response can have different origins despite sharing an operation. Checking candidate completeness, mixed-content coverage, active-intention history, sub-response attribution and independent semantic accuracy remain unproven. Do not aggregate these development links into verification success, progress, exploration or training-shift rates.

`tracker.response_material` validates exact call binding and dependencies, preserves media/text omissions, and replays raw argmax selections. A new observer projection replaces only its inspected material edges, retaining dispatch connections and original units. Earlier raw material choices remain in the inspector's expandable history. Reference and uninspected-material links are named explicitly; neither is displayed as supplied contents. Negative pairs remain inspectable without invented links. No additional model/API was introduced.

Artifacts: `research/response-material-2026-10-07` (first pass), `research/response-material-dispatch-2026-10-07` (revision). Resume/review with `python -m research.response_material_review --dispatch-only --run all`; the complete cached replay makes zero new API calls. The generic CLI is `python -m tracker.response_material DIRECTORY RUN_ID`, with `--audit` for replay. Preparation copies immutable inputs and must not replace an existing revision directory.

Across both versions and controls, 237 distinct new requests used 822,081 input and 16,099 output tokens. This excludes earlier candidate authoring and inspection. Requests are deduplicated by hash across copied study directories. `study-review.json` checks preservation of the complete prior study; both original followthrough sources and all copied upstream dependencies are unchanged. This exhaustive development pass is not yet a training-scale cost design.

Validation: 507 Python tests and twelve map-projection tests pass. Six new Python tests cover response identity, time/visibility and media boundaries, output isolation for dispatch mechanism, exact identity joins, immutable projection changes, source/dependency rejection and raw replay. The API's complete documents equal the saved maps: software has 101 unique units/197 selected relations; retail has 36 unique units/16 relations. The extra relation count includes references and uninspected material, not additional successful checks. Browser evidence and screenshots are saved with the revision. These checks validate software behavior and the reviewed examples, not general semantic accuracy.

Live browser review confirms the report reference and preserved earlier choice, actual uninspected image payload, PDF existence/content distinction and the failed exchange's absent balance. Following the report response keeps six unique connected units and six outgoing relations in the same timeline. The existing tab was reused; no new tab was opened. The browser reported no page errors or horizontal overflow on the software view. **Export remains unverified:** the export button was clicked, but no completed download event or matching file in the default Downloads directory was observed. This is not counted as export validation. Receipts: `browser-review.json`, `api-review.json` and `report-reference.jpg` in the revision directory.
