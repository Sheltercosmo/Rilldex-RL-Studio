# Executable semantic extraction

## Optional contribution reading protocol v2

11 October 2026: new workspaces can select `--reading-protocol contribution-readings/2`. It binds the candidate generator to the same activity definitions as Jev for every activity route. It also asks both stages to distinguish what a unit contributes now from an operation mentioned in a request, intention, offer, report, quotation or artifact payload. Substantive reasoning and artifact creation can happen in text; evidence of an external operation requires a recorded dispatch. Source `actor` and `kind` are supplied as recorded form, without asserting effect or success. This adds no activity labels or confidence thresholds.

For example, prepare a **new** directory using `python -m rilldex --db <database> semantic prepare <new-directory> --run-id <recorded-run-id> --activity-routing work-phase-activity/1 --reading-protocol contribution-readings/2`. The workspace freezes the setting; the ordinary `run`, `status`, `audit` and collection commands then use it. It still needs a supplied candidate response or explicitly configured candidate command. No provider is installed or invoked by `prepare`.

V1 remains the default so existing workspaces, request hashes and decisions retain their original meaning. Old responses cannot satisfy v2 requests; publication audits check the v2 definitions, contribution rule and source binding, and collections reject mixed reading protocols. The partition-description contract remains v1 because this change addresses activity readings after boundaries have been selected.

The offline audit replays 19 retained rollouts and compares 54 units with readings (49 flat-generation units, five airline units). The 49 work-phase units had mismatched candidate/selection definitions; v2 construction removes those mismatches while retaining exact source and context. **This is protocol validation, not improved semantic accuracy.** V2 has no live model outputs yet, and the general automatic proposer and independent review remain required. The compared generation payloads grow from 551,408 to 673,361 UTF-8 bytes; those are neither billed tokens nor a full-pipeline cost estimate. [Evidence and evaluation gate](../research/contribution-scope-2026-10-11/README.md).

## Bounded execution and honest coverage

11 October 2026: `semantic run` now defaults to 50 new Jev request invocations, 50 new candidate subprocess invocations and 1,000,000 combined UTF-8 request payload bytes **per execution**. Override these with `--max-new-calls`, `--max-candidate-calls` and `--max-input-bytes`, before the final `--candidate-command` option. Set all three to zero for cache-only replay. Resume starts a new allowance; this is not a lifetime workspace or training-job budget. No confidence threshold or semantic protocol change is introduced.

The gate reserves an attempt and writes its receipt before invoking external code. Provider failures count; a process crash can leave a `started` record with unknown completion/billing. Completed raw Jev responses survive answer-validation failures. Previously validated decisions and supplied candidate files do not consume the allowance. The current partial checkpoint is saved at interruption and cannot replace a completed published map. `semantic status` distinguishes a budget stop from successful extraction and exposes eligible/visited/unvisited windows, selected source-byte coverage, per-stage attempts, and per-counter token-report coverage. A previous complete result remains explicitly separate.

These limits measure invocations and payload bytes, **not billed tokens or currency**. The built-in Jev transport makes one POST attempt without automatic retry; older/custom transports may differ, and a candidate subprocess may call a model multiple times. A generator may return numeric `usage.input_tokens`, `usage.output_tokens` and/or `usage.total_tokens` alongside its response; missing counters remain unknown. Aggregate reported usage covers journaled attempts only; older workspaces retain their separate validated-decision usage audit. Bytes are never converted into asserted token counts. General automatic proposal generation still needs an explicitly configured process or supplied responses.

Use [the application setup recipe](http://127.0.0.1:8765/integration-guide#inspection-budgets) and the [cross-domain replay audit](../research/semantic-budget-2026-10-11/README.md). Keep semantic coverage and sampling policy beside behavior rates. For comparison, [verl documents per-worker/per-step trace sampling](https://verl.readthedocs.io/en/latest/advance/rollout_trace.html); its trace-volume setting is not a semantic-inference budget. Selecting failures or shorter traces does not yield unbiased whole-training prevalence. None of these execution controls establishes independent semantic accuracy.

## One extraction protocol across rollouts

`python -m rilldex semantic register-collection DIRECTORY --run-ids ID1 ID2 --label "Matched-task pilot"` registers complete passes from a shared extraction directory under one observer. It audits every member before registration, freezes source/extraction/map hashes, and requires compatible context, activity/boundary protocols and candidate producer versions. A changed member becomes unavailable without hiding unchanged members. Original observations remain stored.

This lets the existing graph store and rollout measurements compare one protocol across real training coordinates. It does not certify annotation accuracy, establish representativeness, infer training steps or enable a monitor automatically. The first real matched-task development pilot and its retained failures are documented in [the training pilot](../research/training-semantic-pilot-2026-10-08/README.md).

The optional `contribution-boundaries/4` and `work-phase-activity/1` experiments preserve within-task checking and delivery, and distinguish an outline of answer content from a broader work plan. They are explicitly versioned; existing workspaces retain their earlier protocols.

## Local work objects before history

8 October 2026. A contribution's existing generic `content.target` cannot safely serve as its work-history object. On the frozen software source, “communicate visualization status” differs from the generation/display outcomes actually claimed; Markdown drafting is one stage of the PDF report work. On the airline source, obtaining confirmation differs from the reservation update being proposed. Reusing these targets creates misleading histories even when the base activity is unchanged.

The retained `expressed-work-declarations/1` trial matches 12/12 authored control sequences but fails these real-source boundaries. Version 2 adds a target-suitability stage and whole/partial-scope checks; it matches 16/18 authored controls, misses several explicit undertakings on the software source, and still accepts a communicative completion target. Both are **not promoted**. They do not supply active-goal or completed-work measures.

`tracker/declared_work_items.py` instead requests local work-object bundles before any cross-unit identity. Each item has readable work/scope, an attributed declaration and exact evidence. Several items may belong to one unchanged unit: “Pandoc is installed; let's convert the report” can retain an installation outcome claim and a conversion undertaking while remaining Orient. Claims embedded in a drafted artifact are not silently attributed as the outer agent's completed work. Conditions remain part of the work description.

The finite declaration roles are `commits`, `proposes`, `defers`, `withdraws`, `reports_finished` and `reports_blocked`. These are content attributes, not additional activities. They record what the speaker expresses, not actual commitment, internal goals, verified completion or environmental state. IDs are local to the unit. No automatic history update follows. The contract is developmental, not a frozen universal taxonomy.

Candidate generation happens outside Jev. The file handoff binds one to three bundles to a source/map/request hash. Jev selects a whole bundle, `no_suitable_candidate` or `unresolved` using raw argmax; there is no confidence threshold. Missing candidates differ from a selected empty bundle. Version 2 adds a concise interpretation to every option, including empty bundles, so Jev compares meaningful readings. Exact references, current-contribution evidence, visible-prefix boundaries and supported fields are validated before selection; validation does not prove semantic correctness.

The first eight-example pilot matches five authored choices. Source review finds its retail empty expectation was incomplete: the source states proceeding with the first exchange and not proceeding with the second. Rejecting those supplied candidates is not an established model error. The described pilot corrects that candidate and adds readings to all options; it selects all eight authored choices. These are reused examples, assistant-authored candidates and assistant review. They do not estimate held-out accuracy, isolate the effect of readings, demonstrate automatic generation or establish whole-trace coverage.

Both ledgers and both local pilots retain requests, responses, raw choices, sources and replay audits under `research/work-declarations-2026-10-08`, `research/work-declarations-staged-2026-10-08`, `research/local-work-items-2026-10-08` and `research/local-work-items-described-2026-10-08`. Run `python -m research.work_declarations_review` to replay all decisions and confirm registered maps remain identical. Consolidated results: `research/work-declarations-review-2026-10-08/review.json`. This increment adds no live map layer and uses no additional model service. Next complete local-object coverage and candidate generation, then connect supported whole/partial work scopes and history changes.

Verification: all 616 Python tests pass, including source/cutoff binding, missing versus empty candidates, versioned reading validation and declaration replay. The consolidated audit replays 318 retained selections across the four experiments and verifies unchanged registered maps. These are software and provenance checks, not 318 independent semantic labels. The interface was not changed in this increment.

## Retained conditions, requested checks and attributed claims

The **Retained conditions · development** observer repairs a concrete loss in the previous retail work history: the e20 instruction not to charge before the user supplies the gift-card ID was present in the local Orient contribution but missing from its persistent condition record. The new pass retains that restriction with the exact same source and clause version through e22 and e33. All 30 local user/agent contributions are unchanged. This is a repair to the contents of a record, not another activity tag or evidence of a new objective.

`requested-work-records/2` gives condition records three content roles:

| Content role | What it preserves | What it does not establish |
| --- | --- | --- |
| Requirement | A requested term, restriction or prerequisite | Whether it was satisfied or followed |
| Requested check | Something the participant asks to verify or confirm | An attempted check or passing result |
| Attributed claim | What an identified speaker asserts | Independent truth or environment verification |

For e22, the payment record contains the requested card/payment terms, the retained waiting restriction, the request to verify the card balance, and the user's claim that its balance is $15. These remain contents of one condition record. When the user later chooses another card, the earlier card-specific check and claim leave current scope with explicit source-backed retirement reasons. Their history remains inspectable. Retirement does not mean a check passed or that the claim was false. The waiting restriction remains recorded without inferring whether its prerequisite has already been met.

This adapts the selective-update idea from SOM-DST and the preservation of alternatives/references from Frames, as documented in [the adjacent-method review](ADJACENT_METHODS.md). Neither supplies our coherent-unit definitions, readable targets or semantic accuracy. The earlier condition-compressing observer remains selectable for comparison.

### Selection, evidence and interface

Jev still selects among finite supplied bundles using raw argmax; no confidence gate was added. The new version requires source-bound condition clauses and explicit reasons for retiring previously retained clauses. Unchanged clauses preserve their original version and evidence. Validators reject silent loss, future evidence, unsupported role mutation and new/revised clauses that fail to cite the current contribution. Candidate contents and retirement reasons in this development pass are implementation-assistant authored, not an unattended extractor or independent gold annotations.

The live Requested work view shows these contents at each contribution, their history, and their exact source citations. Search includes condition contents and opens a matching section. Action snapshots retain the conditions available at dispatch time. Browser inspection verified the original e20 source, final retained restriction, explicit retirement history and search. The downloaded JSON exactly matches the saved projection and retains all 30 unchanged local contributions. Evidence is in `research/condition-records-2026-10-07/browser-review.json` and `condition-contents.jpg`.

### Development results and limits

- The 12-contribution pass selects 13 record-version changes and two unchanged decisions across four records. There are 11 distinct condition-clause versions, five explicit retirements and three current clauses at the end. These are representation counts, not objective-change or RL-progress metrics.
- Re-running the existing dispatch correspondence selector against the richer records yields eight relations from twelve candidate pairs. The first profile lookup, e24, now selects preparation for the first exchange; it previously had no specific exchange relation. The later lookup e30 remains unmatched. This is a changed prediction to review, not demonstrated accuracy improvement.
- The combined map contains six source feedback bindings, one repeated-action-target relation and eight work correspondences, totaling 15 relations. Direct requested-check-to-action/result connections remain unimplemented.
- All eight authored clause-selection contrasts match their expectations, including rejection of invented verification, request/claim confusion and unsupported retirement. They isolate this layer and do not establish general extraction accuracy. All 472 software tests pass.
- The real condition pass used 12 calls, 143,728 input tokens and 644 output tokens; the correspondence re-run used six calls, 46,610 input tokens and 894 output tokens. Eight additional calls evaluated the authored controls. Candidate authoring and manual review are excluded from these usage totals.

Artifacts: `research/condition-records-2026-10-07/{condition-record-audit,delivery-review,selected-map,browser-review}.json`, frozen proposals and decisions; `research/condition-clause-controls-2026-10-07/review.json`. V1 remains replayable. No additional model/API was used.

**Next:** derive correspondence candidates from retained requested-check clauses at each action's source cutoff, keeping attempted checks and outcome evidence separate. Transfer the work-history interface to real software targets and organized Plans before adding macro metrics. Independent semantic evaluation, unattended candidate generation and actual RL checkpoint comparisons remain unfinished.

## Work versions connected to dispatches

The current retail observer now connects selected requested-work versions to recorded dispatches. Candidates are **derived from the latest prior work-state snapshot**, not newly authored for each action. Each candidate receives one raw-argmax correspondence: preparation, attempt, result/progress check, none or unresolved. Multiple work items can share a prerequisite without requiring overlapping base activity tags. Withdrawn work remains a candidate, with its previous requested terms, so attempting withdrawn work is representable without assuming authorization or success.

The real six-dispatch pass produces seven links from twelve candidate pairs: the initial identity, order and product lookups each prepare both exchange requests; the exchange dispatch attempts only the retained first item. The two later profile lookups receive no specific exchange-work correspondence. The e24 lookup concerns payment/address checks currently held in condition content; the e30 dispatch does not express its purpose. **Condition-specific correspondence remains missing**, and the unmatched results are not evidence of useless work or deviation.

The Requested work view exposes each item's linked dispatches through the selected contribution. Its default End of recorded trace option also includes actions after the last user contribution, which matters for traces with only an initial task request. Action cards and their inspector expose the requested scope and conditions available at dispatch time. For e27, the snapshot includes the GC7381924 payment request and its user-claimed balance, alongside the recorded attempt and payment-method error. The final gift_card_7245904 approval is not substituted into that earlier state. Exact source call/result links remain separate from model-selected work links. Live history cutoffs, linked-dispatch navigation, action-state contents, error display and downloaded JSON are checked; `work-correspondence-browser-review.json` and `work-action-version.jpg` retain the evidence.

`tracker/work_correspondence.py` is independent of framework tool names and retail IDs. It batches up to twelve work records per request without dropping overflow candidates. Every selected edge records the work/version identity, state hash, source evidence and decision hash. Replay rejects changed dependencies or links. Source cutoffs reject future evidence and cross-trajectory state. `Pipeline.decide` now exposes the existing validated multi-question answers while `choose` preserves the single-choice API and old request/cache behavior.

```powershell
python -m tracker.work_correspondence research/participant-contributions-2026-10-07 9f5b00fa0c3418a66d561730 --audit-only
python -m tracker.work_correspondence research/participant-contributions-2026-10-07 9f5b00fa0c3418a66d561730
```

Validation: 469 software tests passed; eight authored contrasts match all expected correspondence sets, covering shared prerequisites, separate work, withdrawn work, requested checks, checking a product, unrelated work, changed terms and distinct people. These contrasts isolate this layer using authored local records; they do not establish upstream extraction quality or independent accuracy. The real pass used six calls, 43,787 input tokens and 893 output tokens. The controls used nine calls. No additional model/API or generative provider was introduced for this layer.

The combined map has 30 participant contributions, six separate source responses and fourteen relations: six response bindings, one repeated-action-target relation and seven work correspondences. Fourteen relations are not fourteen successes or macro behaviors. Work-state changes, conditions and execution outcomes remain distinct.

Artifacts: `research/participant-contributions-2026-10-07/work-correspondence-audit.json`, dependency-bound `work_correspondence` results, decision packets and the combined `selected-map.json`; authored controls and outcomes under `research/work-correspondence-controls-2026-10-07`. Next: retain and connect condition/check requests without promoting every conversational question into persistent work, then transfer work histories and action correspondence to real software/Plan sources. Independent review, generative candidate automation and RL checkpoint comparisons remain required.

## Participant contributions and versioned requested work

The retail development trace now includes **18 unchanged agent contributions and 12 selected user contributions**, with **six source dispatch/result pairs**. The new **User scope and agent work · development** observer adds a Requested work view. It preserves four readable records (two work items and two conditions), 12 version changes, and three carry-forward decisions across the 12 user contributions. Users can select a contribution, inspect the state at that point, expand each record's history, and open the exact source. User contributions remain separate from model-activity counts. The initial objective is now the actual first user request, not the system policy.

This is the first implementation of the selective-update/frame-history ideas in [the adjacent-method review](ADJACENT_METHODS.md). It is **requested scope**, not a complete model-goal or completion tracker. Agent proposals, adopted plans, authorization-to-attempt correspondence and environmental fulfillment still require separately supported records/relations.

| Source sequence | Selected representation |
| --- | --- |
| Initial request | Two separately addressable exchanges; second replacement material initially unspecified |
| Clarification | Tentative ceramic preference, then a firm ceramic requirement; old versions preserved |
| First-only decision | Second work item withdrawn once; first item retained |
| Reconfirmation | Existing state carried forward, without another withdrawal |
| Card supplied | User-reported balance distinguished from verified balance |
| Final authorization | Different payment card and confirmed address; no completed-exchange status invented |

### Why the first history experiment was rejected

`request_history` compared every later user contribution against earlier ones. It selected 31 edges, including repeated withdrawals when later statements merely reconfirmed current scope. Structural replay passed, but source review showed the resulting graph was misleading. These artifacts remain saved for diagnosis and are **not projected into the live relation map or its counts**.

The replacement `requested-work-records/1` operates on the current records. A candidate bundle can introduce, revise, withdraw or restore specific records; Jev can select the bundle, retain the state, request candidate repair or mark the evidence unresolved. Selection remains raw argmax. Code validates references, immutable previous versions, source cutoffs and state transitions. Missing or rejected candidates stop dependent history rather than manufacturing updates. One coherent contribution can affect several work items without receiving several base activity tags.

### General interface and practical use

`--include-user` in the semantic extraction CLI is opt-in. It preserves old agent windows and selects local user boundaries, one activity and readable attributed content before the history layer runs. User statements of a need addressed to an assistant can be Coordinate; statements about their own pending work can remain Orient. The eight authored routing controls all match their expected categories, including the user's Orient example, but are not independent accuracy evidence.

The core requested-work module has no retail tool names, event IDs or framework-specific tags. Its file queue exports a source-bound request with the current contribution, local content, visible source and previous records. A candidate provider returns zero to three complete edit bundles. The development provider in `research/run_requested_work.py` is explicitly assistant-authored and source-specific; it must not be mistaken for the generic extractor or an unattended model worker.

```powershell
python -m tracker.requested_work research/participant-contributions-2026-10-07 9f5b00fa0c3418a66d561730 --audit-only
# For a new pass, use a completed participant extraction and explicit context policy.
# Missing proposals are written to work_candidates/requests; supply responses and resume.
python -m tracker.requested_work research/participant-contributions-2026-10-07 9f5b00fa0c3418a66d561730 --context-policy research/participant-contributions-2026-10-07/work-context-policy.json
```

The app exports the selected local extraction, observer identity, work records, snapshots, changes and source evidence together. Existing Action map, five Work paths and seven source/target relations remain available. The new request histories are not disguised as action-compliance judgments.

### Review, cost and remaining accuracy work

- All original 18 agent contribution records are exactly unchanged. Complete source coverage and saved raw-argmax choices replay.
- The requested-work pass made 12 new Jev calls: 131,169 input tokens and 644 output tokens. Candidate authoring, the failed history experiment and manual review are excluded; this is not end-to-end cost.
- The final state has one requested work item, one withdrawn work item and two conditions. Twelve version changes include introductions and term revisions; they are not 12 objective changes or an RL metric.
- The e20 contribution remains a review point: Jev chooses Orient and retains prior state. Its explicit no-charge-before-card confirmation is present in local meaning/source but compressed in the carried-forward payment record. Condition completeness is not established by a valid state transition.
- 466 software tests passed. Source-bound map replay, CLI audit, JavaScript syntax, browser state navigation, version/source drill-down, search and exported JSON are checked. These are software/trace checks, not semantic accuracy.

Artifacts: `research/participant-contributions-2026-10-07/{delivery-review,selected-map,requested-work-audit}.json`, local/candidate/decision receipts, rejected `request_history`, current `requested_work`, and `requested-work.jpg`. All candidate and source-review authorship remains explicit.

**Next:** assess retained conditions and changed-scope completeness; connect actions to the appropriate work/authorization version; transfer the same update interface to software targets and explicit Plan revisions. An actual generative candidate provider, independent semantic review and real checkpoint comparisons remain unfinished. No additional model/API was introduced.

## Complete retail contributions with candidate readings

The same fresh retail source now has **18 selected agent contributions across all 13 eligible source regions**, plus **six source-linked environment responses**. Exact source coverage and every raw-argmax decision replay. The live **Contribution readings · development** observer exposes the complete map, its readable contents and six source-review notes. Earlier failed passes remain separate.

The substantive change is how candidates describe a unit. A partition proposal now explains each contribution and why its supporting text belongs together. Selected source units can then receive candidate activity readings such as “asks the customer to authorize this payment.” Jev judges those interpretations against the source with the complete original activity vocabulary still available. These descriptions are proposals, not source facts or guaranteed labels. No probability threshold was introduced.

| Previously unresolved or misleading output | Current selected output |
|---|---|
| Two-exchange proposal rejected as an unsplit region | One Coordinate contribution requesting authorization, with variants and prices as its contents |
| Availability explanation and replacement-choice request merged | A Decline contribution for the unavailable ceramic replacement, a separate Coordinate choice, then the identity/payment Report |
| Payment authorization labeled Report | Coordinate with the readable target “Obtain authorization for a usable payment method after the attempted exchange’s payment error” |
| Shipping answer treated as part of the payment question | A separate Report, including the expressed address and a repeated closing reminder |
| Targets reduced to identifiers | Natural-language work, requested decision, attempted change, withheld work and reported status, with exact source citations |

The explicit “cannot fulfill” contribution selects **Decline**, rather than the earlier reviewer preference for Report. This is retained as a review point; it was not relabeled to match an expected answer. The profile lookup after a verification request still selects Inspect, and its inspection/verification purpose is also flagged for review. An account retrieval does not by itself verify the supplied card’s claimed balance.

The action map has six dispatch/result pairs. The unchanged scope-aware target observer links the repeated account lookup (e30→e24) and keeps the other operations separate, yielding five action work paths. No exchange retry is invented after final user approval. User-request scope changes and approval-to-action relationships are currently source-review findings, not automatically selected edges.

### General worker integration

The opt-in `--contribution-readings` mode in `research.run_semantic_extraction` implements this workflow without retail event IDs. `tracker/contribution_readings.py` defines source-bound reading requests and validation. `FileCandidates` and `CommandCandidates` support the following sequence:

1. Propose coherent partitions with contribution descriptions and boundary rationales; select the partition.
2. Propose activity readings from **each selected unit's own visible prefix and cutoff**; select one base activity from the original vocabulary.
3. Propose readable, category-conditioned content; select the content bundle.
4. Build separately justified relationships using those selected records.

Missing activity readings produce `needs_activity_readings` before classification or content extraction. Validators reject future/omitted evidence, unknown activity names, duplicate labels, stale request bindings, and readings that fail to cite the current unit. Candidate workers receive no Jev credential. Generation and selection resume independently from their source-bound receipts. The inspector now shows supplied candidate readings and their evidence under **Inspector context and unobserved evidence**.

The real retail pass uses the frozen prototype request layout in `research/run_contribution_readings.py`; the general worker integration is exercised by end-to-end software tests. Those are distinct verification scopes. The actual external generative endpoint remains unconfigured. Retail candidates are implementation-assistant authored, not unattended output.

### Validation and cost

- **43 selected local decisions:** 7 boundaries, 18 activities and 18 content bundles; 362,264 input tokens and 3,538 output tokens. Thirty-five calls were new; eight unchanged activities reused exact prior decisions. Candidate generation and manual review are excluded from these costs.
- **Six target decisions** select one repeated-work link after the local extraction completes.
- Eight short authored controls cover Orient, Plan, Hypothesize, Reason, Report, Coordinate, Verify and Construct. All eight retain their expected label in baseline, faithful-reading and misleading-reading conditions. The user’s decorator passage remains Orient. These controls are not independent accuracy or broad robustness evidence.
- **458 software tests pass**. JavaScript syntax, live main-inspector navigation, current-versus-historical labeling, readable map contents and source/action navigation are checked. The earlier overlapping-tag guidance is explicitly historical and links to the current map for the selected rollout.

Artifacts: `research/contribution-readings-2026-10-07/{manifest,proposals,readings,authored-content,review,target-review,selected-map}.json`, source-bound requests/decisions, and `research/contribution-reading-controls-2026-10-07`. All source review notes identify their assistant authorship. Complete local coverage is demonstrated; independent semantic accuracy, automatic candidate generation, cross-unit requested-scope/authorization links and RL checkpoint comparisons remain unfinished.

**Next:** use these complete readable records to establish requested-scope and authorization relationships with exact user-message evidence, keeping intended, approved, attempted and returned states distinct. Transfer the described-candidate observer to further real sources, including actual organized plans, before promoting it as the default semantic observer or using its counts as RL behavior metrics.

## Fresh-source boundary failure and candidate ordering

The next complete public record exposes an unresolved foundation failure. AgentProcessBench retail record **840 / query 18 / sample 0** has 27 source messages, 33 normalized events and 13 eligible agent source regions. It was selected as the first sample of the next retail task after previously inspected query 17, without using grader labels. Its complete messages have now been inspected; it is development material, not an independent holdout. The pinned dataset revision and hashes are in `research/retail-transfer-2026-10-07/manifest.json`.

The unchanged boundary harness produced **24 units**, including “Let me clarify…” and “Let me address…” as isolated Orient units, and repeated closing requests as separate contributions. Reading these outputs confirms the user's complaint: exact offsets and one label per fragment do not make a useful unit. The automatic menu contained whole-message, paragraph and legacy sentence partitions before any semantic boundary candidates existed. A raw-argmax selector can choose a poor offered partition even when an abstention option exists.

### Implemented ordering repair

`semantic-boundary-candidates/1` requires externally supplied coherent partitions **before any prose activity classification**. Until they exist, the source region remains `needs_partition_candidates`; there is no synthetic fragment activity. The candidate menu retains the whole-source alternative and supplied semantic partitions, and excludes automatic paragraph/sentence partitions. Recorded action dispatches retain their source boundary. A configured candidate command now runs boundary generation first. No probability threshold or confidence rule was added.

New runs through `research.run_semantic_extraction` use this mode and contribution-boundaries/3 by default. `--legacy-syntax-boundaries` retains the historical candidate behavior for replay. The low-level provider's legacy default preserves existing callers and saved observations. Earlier complete maps remain separately stored; an incomplete pass is not published over them.

The fresh comparison, with explicitly assistant-authored boundary proposals, yields **16 classified units and one unresolved source region**. The exchange proposal in e13 has no accepted partition. This is not a claim that 24→16 means better accuracy: coverage is unfinished, readable content has not been selected, and actual semantic errors remain.

| Source | Remaining issue | Consequence |
|---|---|---|
| e13 | The unsplit proposed exchange/authorization message is rejected | Repair boundaries before extracting its target or relations |
| e15, first selected unit | Availability answer and substantive choice request remain combined | One Report label loses the requested decision |
| e32, first selected unit | Payment authorization request is labeled Report | A target history can confuse a proposed payment change with delivered status |
| e15, closing reminder | A prompt revision overreacts to a repeated request after an identity answer | Do not promote a wording change just because it fixes the obvious positive cases |

An eight-case request/answer wording probe repairs the e13/e32 activity choices but misses the mixed-unit and closing-reminder expectations (6/8 assistant-authored expectations). It is **not promoted**. The fixed implementation change is candidate ordering; semantic boundaries and activities still need repair. There are no selected content bundles or semantic relations for this fresh record, and no completed map is advertised.

### What a useful map must recover from this source

The source review extracts readable work targets directly, without noun-role parsing. These are assistant-reviewed expectations with exact citations, not automatic predictions:

| Recorded point | Readable work target and status |
|---|---|
| Initial request | Exchange two kettle occurrences in order #W4316152: first to ceramic/gas, second to 1.5-liter/gas. The initial request does not specify the second replacement's material. |
| Order response | Both original kettles share item ID 7292993796. Preserve two occurrences; an item ID is not sufficient instance identity. |
| Later user clarification | The user says the second replacement should be ceramic. Preserve this later statement without rewriting the initial request. |
| User narrows the request | Exchange only the first kettle; keep the second. Pay the $6.32 difference with another gift card whose ID is pending. |
| Actual action and response | The agent attempts the first exchange using GC7381924; the tool returns “Payment method not found.” |
| Agent asks for another payment choice | It proposes gift_card_7245904, whose recorded account balance is $17. This is a request, not another exchange execution. |
| Final user approval | The user approves that card and the address. No subsequent exchange dispatch or completion evidence is recorded. |

This is the required analytical result: distinguish changed requested scope, repeated product identity, payment choice, attempted mutation, failure and approval without execution. None requires labeling an option list Plan or inventing an exploration/recovery diagnosis. The exact review history and citations are in `research/retail-semantic-boundaries-2026-10-07/source-review.json`.

### Evidence and next work

- Baseline: 31 selected boundary/activity decisions; 256,402 input tokens and 3,530 output tokens.
- Semantic-candidate pass: 23 selected decisions; 191,348 input tokens and 2,436 output tokens. Fifteen calls were new; unchanged activity decisions were reused. These costs exclude generation, readable content and relations, and the incomplete passes are not an efficiency benchmark.
- Both passes replay raw argmax and bind exact source ranges. **454 software tests pass**, including pending-boundary behavior, exclusion of automatic syntax candidates, generator-before-selector ordering and resumability. These tests do not establish semantic accuracy.
- Reproduce with `research.run_retail_transfer`, `research.prepare_retail_boundaries`, `research.probe_retail_activity` and `research.review_retail_transfer`. Separate directories preserve all failed and revised predictions.

Immediate priority is the rejected/mixed units and the authorization-versus-answer boundary on this complete source. Then select readable category-conditioned contents, preserving occurrence scope and claimed versus recorded status. Only then construct target-change, assessment and realization relations. Candidate generation remains a configured external interface with assistant-authored development batches; a real generative service and independent annotation are still missing. No macro behavior metric should be built from these unfinished outputs.

7 October 2026. This follows the authored maps in [SEMANTIC_MAP_REVIEW.md](SEMANTIC_MAP_REVIEW.md). The general product goal remains active: local extraction, relation reliability, broader transfer, organized-plan reliability and useful RL checkpoint comparisons are not all solved.

## Connected work paths and scope coverage

The existing target observer was transferred unchanged to the complete DevAI/OpenHands source with 68 selected agent contributions and 33 dispatches. Ten expected whole-target links were recovered: two syntax-repair attempts, three training/evaluation runs, five package-installation attempts and four report-conversion attempts. It also made one wrong whole-target match: `pwd` plus `ls results/figures/` was joined to the earlier figures-only listing. Both dispatches remain coherent recorded operations, but their complete scopes differ. Splitting the composite command or erasing its extra purpose would hide the problem.

`action-target-correspondence/4` keeps the established anchor question and explicitly distinguishes **partial work overlap** in the subsequent pair question. Whole identity requires the entire immediate scope; different methods or argument choices can still implement that same scope. Unknown beneficiaries or requested instances remain unresolved unless actual source evidence resolves them. Choices remain raw argmax. Every old request and selected relation is retained under its original version.

On eighteen frozen, assistant-authored pair contrasts, the new contract matches all eighteen expectations, including both previously failing missing-identity cases. The older version matches thirteen, but three of those differences concern the newly expressible partial-overlap option; this is a schema-coverage and development comparison, not an independent accuracy improvement estimate. On the software source, the broad directory/figures check now receives `overlapping_work_scope`, while all ten expected identity links remain. The airline replay retains its six identity links and two different-work/same-subject links. No local activity, boundary, content or source hash changes in either replay.

`tracker/work_paths.py` is a deterministic projection over these selected relationships and the previously audited plan/assessment layers. It groups only whole-target identity links. Each dispatch appears in exactly one path. A path then includes source-paired prose, recorded responses and selected assessments of those responses, in source order, with each unit appearing once in that path. A contribution that assesses an earlier response and accompanies a later dispatch keeps both relationships on one unit. Context may legitimately recur in another path; global aggregates must deduplicate by original unit ID. Related plan stages are references, not newly inferred or completed plans.

The software map has **23 paths covering all 33 dispatches**, 33 source response links, 34 source expression associations, thirteen prior plan-stage links and twenty prior assessment edges. The installation path contains five dispatches, five responses and six prose contributions. The PDF conversion path contains four dispatches, four responses and eight prose contributions, with four attempt links to the declared conversion stage. The original plan inspector separately exposes preparation, content writing, conversion and checking correspondences. The two local plans concern scaffold setup and report production; their succession does not establish plan replacement.

The live **Work paths** view replaces the former action-only target grouping. Paths collapse to readable targets and counts, expand to their connected evidence, and can be searched by selected meanings. Clicking a related plan stage opens its source-backed structure. Inspector connection buttons allow navigation from an assessment to its recorded dispatch or feedback, including work outside the current path. Long responses use readable head/tail previews; terminal color escapes and encoded media are omitted from previews only, with original source unchanged. Review labels are deduplicated. Existing assessment-reference and verification-coverage disagreements remain visible in source-bound review notes.

Verification: 451 Python tests pass, including single-count path coverage, actor/trajectory/time validity, partial-scope non-merging, immutable local content and argmax replay. JavaScript syntax passes. Live browser checks cover all 23 path summaries, the sixteen unique timeline units in the installation path, the PDF path's four plan-stage attempts, contribution inspection, navigation to TeX installation, and the actual downloaded map. The export is 1,712,102 bytes and matches the selected extraction, source and observer version. No browser console errors were recorded. These are software/usability checks, not semantic-accuracy measurements.

Target inference for this software trace uses 44 selected decisions, 560,512 input tokens, 6,952 output tokens and 105.813 summed observed API-call seconds. These figures exclude local candidate generation, earlier plan/assessment selection and human review. Candidate generation remains an assistant-authored development batch; unattended generative service configuration is still missing.

Evidence: `research/work-paths-2026-10-07/{manifest,target-review,review,target-usage,scope-aware-map}.json`, exact source/decisions and browser receipt; contrasts and paired replays under `research/work-scope-2026-10-07`. Reproduce with `research.run_work_paths`, `research.compare_work_scope` and `research.review_work_paths`. The first script preserves the unchanged version-3 transfer as the baseline; the latter scripts produce the scope-aware version-4 view. Neither record is a matched RL checkpoint comparison or an independently annotated holdout.

## Task-instance identity and different work

The concrete failure was in relation selection: local meanings already said “Calculate the remaining payment for Aarav's separate reservation” and “Calculate the remaining payment for Evelyn's separate reservation,” but the original observer joined their identical `1449 - 250` dispatches. No new entity parser or activity label was needed to express the difference.

`action-target-correspondence/2` foregrounds the selected natural-language meanings, retains recorded governing instructions, and shares repeated tool definitions losslessly. It fixes that passenger merge but introduces two wrong identities: calculating a passenger's unpaid amount is joined to creating that passenger's booking. On the same real source and unchanged local meanings, the original has 16/17 reference matches and this intermediate candidate has 15/17. Both remain saved. The twelve authored input contrasts match 11/12 and 12/12 respectively. These are development comparisons, not independent accuracy.

`action-target-correspondence/3` preserves the first-stage candidate selection and asks a separate bounded question about that pair. Options distinguish same immediate work target, different work on the same subject, similar operation for different instances, unrelated, and unresolved. Only the raw winning identity option creates a `same_action_target` edge. Different-work and different-instance relationships remain typed connections, not merged target groups. Rejecting a selected candidate's identity does not establish that no other earlier match exists. No confidence/margin gate or semantic rewrite is used.

On the full revised airline record, this produces the six expected identity links and two expected different-work/same-subject links. The calculations for Mohamed, Aarav and Evelyn stay separate. Each passenger's first and later booking attempts are grouped, with exact payment argument differences. Two calculation-to-booking links preserve their shared subject without asserting a prerequisite, causal response, successful recovery or plan following. This is a partial relation graph, not a complete subtask graph.

The isolated pair contrast set matches 10/11 assistant-authored expectations. The remaining failure is important: an unspecified beneficiary can still be treated as the earlier passenger. The first stage chooses unresolved for that end-to-end contrast and therefore creates no pair, but that does not repair the pair classifier's weakness. No held-out or independently adjudicated quality claim follows from these results.

The observer costs 25 decisions and 342,680 input tokens on this trace, versus 17 decisions and 283,257 input tokens for the baseline; summed observed API call durations were 52.768 and 37.171 seconds. The extra pair stage improves the known distinctions at additional cost. These figures exclude local candidate generation and human review, and are not production latency/cost estimates.

The live selector's **Task-instance relations** pass presents the same 25 agent contributions, eighteen actions and eighteen recorded responses. Source hashes and local extraction are unchanged from the boundary-revised pass. Search for `remaining payment` shows three separate target paths. The relation view exposes the distinct-work links; source drill-down opens the original calculation and its supporting contextual citations. Exports now include the observer ID and extraction hash, and use the observer in the filename. The actual downloaded JSON was checked against the saved extraction. A browser download-event wait timed out despite successful file creation; verification used the resulting file rather than treating the timeout as success.

Evidence and replay live in `research/scoped-targets-2026-10-07`: `controls.json`, `control-comparison.json`, `real-comparison.json`, `pair-controls.json`, `pair-comparison.json`, `review.json`, `characterized-map.json`, exact decisions, and frozen source. Scripts: `research.compare_scoped_targets`, `research.characterize_target_pairs`, `research.review_scoped_targets`. Candidate meanings and reference expectations are assistant-authored development material. 445 software tests pass; these check replay, cutoffs and data integrity rather than semantic accuracy.

Next: establish missing task scope explicitly and test the relation decision on unseen complete sources; connect stable targets to plan stages and explicit reviews only where the local content supports it. A general candidate worker, independent references, reliable plan/revision histories and matched RL checkpoint comparisons remain unfinished.

## What now runs

`tracker/semantic_extraction.py` implements source regions → selected concrete partitions → one activity per selected unit → coherent natural-language content bundles. Jev uses raw argmax throughout. A repaired partition creates actual source spans rather than leaving a “needs merge” label on the old sentence fragments. All non-whitespace content within a region must be accounted for exactly once.

The baseline offers complete regions, paragraph boundaries and the previous sentence proposals as alternatives. A source-bound file queue accepts additional partitions from a model or reviewer when these are inadequate. The same queue asks for readable content **after** the unit and activity are established. Candidate contents remain distinct from selected outputs and from human reference labels. One coherent bundle is selected, avoiding incompatible fields picked independently from different interpretations.

Each decision is cached by its exact request. New candidates or a changed activity request create a different decision identity. Intermediate checkpoints and immutable content-addressed snapshots support resumption; only a completed pass is published as the latest result. The app replays the saved argmax choices and checks source coverage, activity/content dependencies, attribution and evidence cutoffs before showing a result. These checks establish provenance and integrity, not semantic accuracy.

## Actual telecom result

The public `tau2_telecom:query-34` record previously had 22 eligible sentence-level fragments. The executed pipeline selects five coherent agent contributions:

| Source | Selected activity | Readable work |
|---|---|---|
| e2 | Social | Greet the customer and invite their problem description |
| e4 | Coordinate | Ask for status-bar icons to investigate the service problem |
| e9 | Coordinate | Ask the customer to disable Airplane Mode; reconnection remains an expectation |
| e14 | Coordinate | Ask for SIM status to investigate the continuing service problem |
| e19 | Coordinate | Ask the customer to reseat the SIM, recheck signal/data and report results; further diagnostics are conditional |

All five contributions have selected readable contents and source citations. There are **zero agent tool dispatches** in this record. Four customer-side dispatches remain separate source events, with visibility to the inspected agent unestablished. They are excluded from the model-facing annotation prefix. Later customer reports remain observable dialogue evidence, and are not silently replaced by those private tool results.

The first pass classified e9 as Orient. The recorded `interaction-boundary/1` rule clarifies the existing distinction: instructing another actor to do the work is Coordinate, including an imperative preceded by an explanation. Re-running the five activity decisions changes e9 to Coordinate and leaves the other four labels unchanged. The original requests and predictions remain available. This is a development correction on one known trace, not a held-out improvement estimate.

The live pass used 20 Jev calls including the five superseded activity decisions: 147,485 reported input tokens and 1,800 output tokens. Content selection had one model-authored bundle per unit plus rejection alternatives. It therefore tests whether Jev selects or rejects the supplied meaning; it does not demonstrate ranking among independently generated competing meanings. No confidence threshold was used.

The observed local contents are available under **Telecom · Jev local extraction** in `/semantic-map`. The two earlier authored maps retain their provenance. The telecom map does not invent target-identity links, customer execution by the agent, plan objects or cross-unit diagnoses.

## Candidate handoff and reproduction

The general queue protocol is implemented. No unattended generative API service is configured in this workspace. The current candidate responses were authored by the assistant in this chat and saved as an explicit generation batch. This is not an automatic natural-language generator, nor a set of independent ground-truth labels.

Run from the repository root with Python:

```text
python -m research.run_semantic_extraction freeze --run-id <recorded-run-id>
python -m research.run_semantic_extraction run --run-id <recorded-run-id>
python -m research.run_semantic_extraction audit
```

The default run is the telecom record. A first uncached Jev call asks for its key without echo and keeps it only in process memory. A fully cached pass needs no key. Candidate requests are written under `research/semantic-extraction-2026-10-07/candidates/requests`. A provider writes responses under `responses`, using the same request-hash filename and retaining its producer/version. Each request contains only the relevant source prefix, field contract and response contract. A changed unit or category requires a matching new response; mismatched, future, cross-trajectory or unobserved evidence is rejected.

`research/propose_telecom_content.py` reproduces this one model-authored response batch. It is deliberately labeled as such and must not be mistaken for a domain-general extraction algorithm. `tracker/semantic_extraction.py` is the reusable execution path.

## Remaining work

The organized-plan and mixed-message development example below now exercises this path. Next test an actual generation worker through the existing queue, with proper media descriptors and context retrieval, including proposals rejected by Jev, repaired candidates and disagreements in independent review. Keep positive Plan structure distinct from instructions issued to another actor: requested sequencing can exist inside Coordinate content without becoming another same-level tag.

Before automating relations, test whether local target descriptions preserve the distinction among a work goal, an artifact and requested information across these cases. Then bind references and add typed links with their own evidence and cutoff. Macro patterns such as deviation or recurrent work still require those relations and matched training metadata; five readable local records do not establish the larger product goal.


## Organized-plan development pass

A second actual source is now imported from the [Agent-as-a-Judge repository's public OpenHands trajectory](https://github.com/metauto-ai/agent-as-a-judge/blob/43c2fa7b84ef0c1522e8250576e6798bace29dd0/benchmark/trajectories/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML.json). The original array, repository revision and hash are retained under `research/semantic-plan-2026-10-07`. The DevAI adapter imports thoughts, recorded action descriptions and their paired environment responses without executing source content or inventing native tool arguments, exit status or task success. This is an agent execution example, not evidence from RL checkpoints.

Selected source windows from steps 9 and 21 test three practical boundaries. They are a purposive development sample, not a whole-run or held-out evaluation:

- The apparent syntax error and required string-formatting correction stay one **Orient** contribution.
- The visualization completion statement becomes **Report**, separate from the subsequent **Plan**. This classification remains a model judgment; the Report/Orient boundary on internal status statements still needs independent review.
- The complete report-production Plan remains one unit, with two subordinate stages: create report content in Markdown, then convert it to PDF. The immediate announcement to start creating the Markdown file stays within that plan instead of becoming another Plan unit.
- The recorded `create_file` dispatch becomes **Construct**, with its exact filename and intended work target. Its paired response is shown as source evidence, not a Jev success judgment.

Nine legacy fragments become four selected agent units. Jev chooses the supplied merged/split partition, one activity per unit and a coherent content bundle. Each selected Plan bundle now has `local-plan-content/1`: readable stage targets, stable local stage identifiers, exact citations, and explicit ordering/prerequisite links. Order is not automatically a prerequisite. Completion criteria remain missing when unstated. Validators reject completed-status fields, invented endpoints, cyclic order and future evidence. Cross-unit execution links and plan progress remain unselected.

The candidate batch is reproducible via `python -m research.propose_devai_content`; it is explicitly assistant-authored and contains one bundle per unit plus rejection alternatives. It is not the unattended generation service still needed by the product.

Re-run the selected-window pass with:

```text
python -m research.run_semantic_extraction run --run-id 23a6f4b7c76c919e74ae6d50 --window-event e29 --window-event e65 --window-event e66 --recent-events 6
```

The full prefix exceeded the provider limit (`max_tokens_exceeded`, HTTP 400). The explicit `instructions-and-recent/1` policy keeps instructions plus six recent visible events, listing every omitted older event. It creates distinct request identities and never alters source data or silently turns omitted activity into absent behavior. Missing history may still matter; no equivalence to full-context judgments is established. A future provider must retrieve additional evidence where needed. Raw embedded image data in this source also makes the text context expensive; passing its encoded bytes does not constitute visual inspection. Proper media descriptors/visibility and evidence retrieval are still needed.

The pass added 13 successful Jev calls (including two earlier full-prefix decisions), with 215,909 provider-reported input tokens and 1,080 output tokens. Two failed oversized requests were observed, one in the runner and one confirming the provider error. Their billable usage is unavailable. These costs are a development finding, not acceptable production efficiency.

The replay audit exposed an exact-tie serialization bug: sorted JSON keys discarded criterion order. New decisions retain the original order explicitly. One saved decision was repaired with the known order from the single-action partition builder; its original receipt is preserved under `reviews`. Its raw response and selected maximum are unchanged. No confidence threshold was introduced.

The app's **OpenHands · Jev plan development sample** displays the partial coverage and context limitation, the two cited Plan stages, and action-to-response binding. All 407 tests pass. This demonstrates addressable local plan structure; it does not establish semantic accuracy, plan following, completion, generalization, or a macro behavior metric.

The final local API and live browser show the plan and source response binding. A browser download-event check timed out, so export delivery through the browser is unverified. `research/semantic-plan-2026-10-07/selected-map.json` contains the selected extraction, rendered map data and validation from the verified local API.


## Readable context and candidate worker

The next development pass uses `readable-context/1`. Inline base64 media is replaced only in the inspector's request view with a declared media type, source interval and explicit unobserved status. Original events remain unchanged. Structured media and media carried in auxiliary tool fields are also marked unobserved. This is a text view, not image interpretation. A required subject containing binary media stops with an explicit unsupported-input error instead of pretending to inspect it.

Long prior events can retain their beginning and end, with every omitted interval recorded. Instructions and the current subject stay complete as text. An explicit `extra_ranges` list can retrieve omitted source intervals, including older visible events. Future content, other trajectories and private actor results are rejected. The limits bound optional context per event; they are not a guarantee that every possible task prompt fits the provider's total context window. Retrieval is supported, but a model-driven retrieval policy is not yet implemented.

Projected text has a source-offset map. Candidate citations must fit entirely inside supplied source ranges; synthetic omission/media descriptors cannot be cited as task evidence. The optional `source-quotes/1` response format lets a generator supply `{event_id, quote}`. Exact original offsets are resolved outside the model; repeated quotes require a disambiguating `source_start`. Missing/fuzzy quotes fail rather than being silently repaired. The same checks apply to plan stages and their ordering evidence.

The `CommandCandidates` worker connects a configured JSON-generating process to the existing pipeline. It receives a request on stdin and returns candidates on stdout. The harness supplies request identity and producer metadata, resolves quote citations, validates content, and then asks Jev to select among the candidates and rejection alternatives. A command can likewise propose repaired partitions using complete quoted units. It is invoked as an argument list with no shell, and its environment excludes `JEV_API_KEY`. Process errors do not publish candidate output or persist stderr. Completed candidates and Jev decisions are reusable across resumes. A rejected partition generated by the worker is available on the next pipeline pass; there is no unbounded repair loop.

For a configured generator script:

```text
python -m research.run_semantic_extraction run --run-id <run-id> --readable-context --candidate-producer <model-and-generator-version> --candidate-command python <generator-script.py>
```

The generator command must be last. It receives `{request_hash, request}` and emits a JSON object with `candidates` and optionally `citation_format: "source-quotes/1"`, or `partitions` for a partition-repair request. Content candidates still follow the selected activity's field contract; Plan candidates also carry `plan_structure`. The tracker does not generate free text with Jev. The worker was executed in tests using local deterministic fixtures; no real generative API has yet been configured. Its existence is not evidence of unattended semantic extraction accuracy.

The same OpenHands sample was rerun with unchanged candidate meanings and partition alternatives. All four selected units, activities, natural-language contents and the two-stage Plan stayed unchanged. The eleven decisions used **39,408 reported input tokens versus 200,335 previously**, a reduction of **80.33%**. This is a single development comparison with no repeated-run control, not a general accuracy-equivalence or latency claim. Encoded plot data accounted for most of the removed payload. The new context and quote representation change request identity, and original observations remain retained.

Evidence is in `research/readable-context-2026-10-07/{before,after,comparison,context-size-audit}.json`. The quote responses are explicitly reused assistant-authored meanings; no new candidate-generation model call is claimed. All 418 Python tests pass, covering media exclusion, Unicode/source-offset preservation, omitted-range retrieval, future/private evidence rejection, quote ambiguity, worker execution/resumption and publication behavior.

An unfinished pass now writes checkpoints/snapshots while leaving the last complete map published. The review panel exposes each unit's context scope and unobserved media. Cross-unit semantic relationships, plan following, matched RL checkpoint comparisons and independent accuracy remain unfinished.
# Plan-stage correspondence

7 October 2026. `tracker/plan_relations.py` implements a dependent relation layer over audited, completed local extraction. It retrieves prior selected stages from the same actor and trajectory, supplies their original source and readable meanings, asks Jev to select a stage, then asks for the dispatch's role relative to that specific stage. Raw argmax remains the only selection rule. The pool is bounded at 24 candidates; larger pools require retrieval, and multiple applicable stages have an explicit repair state. Neither case is silently called no match.

The three roles are **prepares**, **attempts** and **checks**. Preparation establishes tools, prerequisites or containers. A direct attempt performs the operation actually named by the stage on some required content/state. A check examines the stage's product or progress. If checking is itself the stated stage operation, dispatching that check attempts the stage. These relationships do not establish success, completion, active-plan identity, causal motivation or compliance.

The real public DevAI/OpenHands development slice was expanded from four to ten selected agent units across nine of 67 eligible source windows. Seven source-linked feedback records remain separate. The six plan-stage links are:

| Source | Selected local meaning | Stage | Relationship |
|---|---|---|---|
| e66 | Create the empty Markdown file | Write report content | Prepares |
| e69 | Insert report content | Write report content | Attempts |
| e72 | Locate Pandoc | Convert report to PDF | Prepares |
| e78 | Dispatch conversion | Convert report to PDF | Attempts |
| e90 | Dispatch conversion using pdflatex | Convert report to PDF | Attempts |
| e99 | List results directory entries | Convert report to PDF | Checks |

The earlier e30 code edit has no prior **selected** plan in this sample. This is not a claim that there was no plan in the complete source, nor a deviation judgment. e79 records a missing PDF engine after e78; no success flag is manufactured. e99 lists a directory; the preceding expression's claim to inspect PDF contents is not promoted into the command's actual scope.

Version 1 selected **attempts** for empty-file creation. Version 2 makes the reference scope the named stage operation, rather than all setup mentioned by the enclosing plan; it selects **prepares**. Original decisions and baseline document are retained. Version 1 and 2 each made twelve relation calls, reporting 89,611 and 90,088 input tokens respectively. No repeated-baseline control was run, so the observed difference cannot be attributed solely to the prompt change.

Eight assistant-authored, role-only controls cover table creation/population/counting and explanation creation/writing/review. Seven match their authored expectations. **Reviewing an existing explanation for a missing base case is still selected as preparation, where the authored expectation is checking.** These supplied-local-content controls are not an end-to-end extraction evaluation, independent labels or transfer evidence. Do not derive a semantic accuracy claim from their match count.

Every relation bundle binds the exact extraction digest and harness version. Replays rebuild the original request, verify source cutoffs and reapply raw argmax. Changed local extraction cannot silently reuse old links. Citation drill-down includes endpoints and the recorded parent expression; these are source context, not an automatically extracted minimal proof. The original request packet remains stored by hash. Snapshots preserve complete published relation bundles.

The semantic, action and relation views share these records. The Plan inspector lists linked actions under each stage. The action view shows intended stage → relation role → dispatch → recorded feedback. The relation view exposes citations. Exported map JSON carries the links and their decision hashes.

Implementation checks cover dependency order, source cutoffs, source-result binding, raw-argmax replay, changed-extraction invalidation, other actors, oversized pools and unresolved/multiple choices. Full suite: 423 passing tests; targeted checks also pass after adding parent-expression citations. These are software checks, not semantic labels.

Reproduce with `python -m research.run_plan_relations --run-id 23a6f4b7c76c919e74ae6d50`. A cached rerun makes zero provider calls. `research/plan-relations-2026-10-07/review.json` records costs, predictions, the preserved error and limitations; `selected-map.json` contains the inspectable map. Candidate text remains explicitly assistant-authored for this development slice; a production generative worker is still unconfigured.

**Next:** finish one continuous episode's local units and readable contents before adding more relation families; then relate feedback assessments, local target changes and method revisions to their specific prior units. Establish independent review for the disputed boundaries before using aggregate behavior metrics. Whole trajectories, multiple producers and matched RL checkpoints remain required.
## Continuous reporting episode

The next pass covers **every eligible source window from e65 through e101** in the public DevAI/OpenHands run. This is the report-writing/conversion episode, not the whole 101-event trajectory. `episode_scope` records ordered event boundaries, trajectory and the expected window IDs; the auditor rejects a published episode that drops any eligible window. CLI supports `--from-event` and `--through-event` as an alternative to individual `--window-event` arguments.

There are 25 episode windows, 26 selected agent units and twelve separate source responses. Activities selected by Jev are two Report, one Plan, ten Construct, ten Orient and three Inspect. These counts describe predictions; they are not validated behavioral metrics. Every selected unit has readable category-conditioned contents. The candidate batch in `research/propose_reporting_episode.py` is explicitly assistant-authored development material, not an unattended generator.

The first boundary pass split the drafted report and final delivery into three units each. `contribution-boundaries/2` asks for the coarsest adequate partition and explicitly keeps an artifact's framing or a delivery's closing language with its contribution. Both now select one unit. The independent visualization status and new report Plan remain two units. Previous predictions and the reviewed partition alternative are preserved; this is not a controlled accuracy experiment.

`feedback_assessments.py` consumes the already selected **Orient situation field**. It retrieves up to three prior visible responses bound to selected actions by the same actor, with original evidence and explicit omissions. Jev selects the response being described/interpreted. A mistaken interpretation can still have an assessment relationship: claim support, correctness and causal motivation are not judged here. None-of-these, unresolved and missing candidates do not become negative behavior metrics.

If Jev selects multiple responses, a dependent bounded set question offers the available pairs/triple, plus repair/unresolved options. In the actual episode, “the image-path issue persists” selects the two conversion responses e85 and e91 jointly. The observation is one assessment group with two evidence edges; those edges must not be counted as two assessments or treated as independently sufficient evidence. The original single-choice outcome is retained.

Current map: **12 source bindings + 12 Plan-stage links + 10 assessment evidence edges = 34 edges**, representing nine assessment groups. Four dispatches attempt the selected PDF-conversion stage; five prepare it and one checks it. These are observed dispatch-role counts, not completion or progress percentages. Repeated command text alone does not establish a repeated state: the source includes an intervening Markdown image-reference edit.

The action view presents the intended stage, dispatch, source response and agent interpretation. The interpretation retains its stated next work. Semantic and relation views use the same units and links. Source drill-down opens in a drawer within narrow app panels, with a Back to map control, instead of requiring scrolling past the entire trajectory.

Software validation: full 427-test suite passed before adding the joint-set branch; sixteen targeted relation/extraction tests pass after that addition, including a new joint-group test. Browser verification confirms 38 semantic cards, twelve action groups, 34 relation cards, joint-source links, source drill-down, drawer opening/closing and no observed page errors. These are implementation checks, not semantic accuracy evidence.

Current selected decisions total 111 calls with 556,812 reported input tokens and 8,100 output tokens, including reused decisions and excluding superseded development calls. Cached relation replay makes zero provider calls. Cost and correction burden remain product concerns; a complete working episode is not proof of commercial practicality.

Reproduce local extraction with `python -m research.run_semantic_extraction run --run-id 23a6f4b7c76c919e74ae6d50 --from-event e65 --through-event e101 --recent-events 6 --readable-context`; the explicit candidate queue must already be populated or supplied by a configured generator. Run relationships with `python -m research.run_episode_relations`. `research/reporting-episode-2026-10-07/review.json` and `selected-map.json` preserve the selected contents, boundaries, relationship groups, counts and limits.

**Next work:** continuous coverage before this episode; align semantic target and method changes across units; distinguish the agent's assessment from evidence supporting it; evaluate the disputed Inspect/Verify and review/preparation boundaries independently. A configured generative service, multiple producers, whole trajectories, practical investigation workflows and matched RL checkpoints remain unfinished. The original product goal remains active.

## Whole-trajectory source review

The same public DevAI/OpenHands record now covers all **67 eligible source regions** in its 101 canonical events. There are **68 selected agent contributions**, including 33 dispatches, and 33 separate source responses. The selected activity distribution is two Plan, 28 Construct, 27 Orient, nine Inspect and two Report. These are predictions on one recorded execution, not activity accuracy measurements or RL checkpoint comparisons. `research/propose_openhands_prefix.py` supplies explicitly assistant-authored, source-bound development candidates; a generative service is still unconfigured.

The first whole pass rejected boundaries for an `open_file` dispatch and a recorded edit. `source-dispatch-boundary/1` now preserves the adapter's recorded dispatch as one unit; program internals remain its payload. Prose still uses the semantic partition selector. Activity and useful contents follow in both cases. The audit verifies both boundary origins, exact source coverage and downstream bindings, including rejecting a removed unit-origin marker. Previous partition decisions remain saved.

Reading the selected contents against the source yields three practical investigations:

| Investigation | Preserved evidence | What the map does not yet infer |
|---|---|---|
| Dataset provenance versus delivery claims | e23 calls for synthetic test data; e24 writes random data to `path_to_gdsc_dataset.csv`; e34 shows training using that path; e68/e101 claim GDSC loading | Intent, deception, root-objective change, or independently verified final artifact contents |
| Announced versus performed verification | e98 proposes checking PDF existence and contents; e99 only lists `results/`; e101 reports completion | Whether report contents are correct, or automatic verification-coverage scoring |
| Method changes under one work target | Package-installation attempts retain the installation target while changing `--user`, interpreter and `sudo`; source responses and interpretations stay separate | Canonical method identity, causal recovery, exploration or objective change |

No real-GDSC replacement is visible in this recorded trace. That is a source-review observation, not a claim about unrecorded execution. `review-packets.json` saves these three **assistant-authored review packets**, with exact source evidence and selected local contents for later LLM/human inspection. They are not automated diagnoses or independent references.

The current map contains **33 source bindings + 13 plan-stage links + 16 feedback-assessment edges = 62 edges**. The scaffold dispatch adds one Plan-stage attempt to the earlier report episode's twelve stage links. Those report-stage links retain the preparation/attempt/check distinction. Eighteen Orient situations are considered for feedback references; sixteen receive a link.

The feedback pass still fails on simple cases. e80 receives no link despite e79 saying `pdflatex not found`; e86 receives no link despite e85's missing-image warning. e92's persistence claim selects only e91, whereas the earlier episode selected e85 and e91 jointly. These failures are listed in the review artifact. They prevent treating feedback-link or recurrence counts as reliable behavioral metrics.

The episode/full-run e92 requests had the same visible source and offered responses but different extraction digests and counts of omitted older responses. This is an observed selection discrepancy; no controlled experiment identifies which difference, or fresh-call variation, caused it. `local-assessment-dependencies/1` removes that unrelated aggregate bookkeeping from the model-visible request. The result still binds the exact extraction digest, and omission counts remain in its audit rows. Identical local input now reuses the same stored raw-argmax decision even when unrelated extraction bookkeeping changes. Changed local situation/evidence still changes the request. Legacy metadata-bound results remain replayable. This does **not** establish fresh-call determinism or improve semantic accuracy: the new pass additionally misses e86 and still selects only one recurrence response. The unchanged earlier results are preserved.

The UI now searches selected meanings, targets and plan-stage text, with matching field excerpts and optional directly connected evidence. Search is literal text matching, not inferred entity identity. Action groups retain their linked evidence; relation search retains edges touching matching units. Empty results and clearing the filter are explicit. An unlinked feedback selection is visible in the unit inspector. The whole trace is an inspectable development map, not a claim of completed high-level diagnosis.

Artifacts: `research/whole-openhands-2026-10-07/{review,review-packets,selected-map,relation-audit,feedback-before-local-dependencies}.json`. Rebuild review with `python -m research.review_whole_openhands`. Current selection dependencies contain 236 calls, including reused decisions, reporting 1,111,416 input tokens and 18,159 output tokens. Superseded/rejected development calls are excluded. This volume is a practical efficiency problem to address, not a commercial-cost claim.

Software validation: **430 Python tests pass**, JavaScript syntax checks pass, and cached relationship replay uses zero new provider calls. Browser checks confirm 101 total cards, 33 action groups and 62 relationships; synthetic-data search returns three direct matches plus one connected interpretation. Turning connected evidence off, empty-result handling, clearing search and the unlinked-feedback notice work. No browser console errors were observed. `browser-check.json` and `semantic-search.png` preserve that verification. These checks establish implementation behavior, not semantic accuracy.

**Next:** put each candidate response's readable evidence directly beside its choice and test direct matches, unrelated responses, misleading interpretations and joint recurrence. Preserve old predictions and evaluate the complete fixed set, rather than rerunning only failures until they change. Then connect persistent targets and explicit method changes. Independent boundary/content references, actual generator integration, another producer/domain and matched RL checkpoints remain required before broader accuracy or training-progress claims.

## Feedback-reference evidence and source pairing

The next development comparison freezes all eighteen eligible Orient situations in the whole OpenHands record, plus twelve authored relation controls, before inference. Controls cover paraphrase, unrelated content, mistaken interpretations, a non-adjacent reference, joint recurrence, change across responses, ambiguity and a referent outside the offered pool. Local labels are supplied in the controls: this tests the relation harness, not end-to-end extraction or independent transfer.

`inline-feedback-options/1` places each response's readable excerpt beside its selectable option. It uses only response text already present in the source-preserving context, limits the option excerpt, and leaves additional visible text in the context. It neither generates a response summary nor changes the raw-argmax policy. The dependent set-selection options also retain response evidence. Baseline and candidate have the same questions and local inputs apart from evidence layout.

The second candidate adds `assessment-reference-boundaries/2`: a comparison or expressed recurrence can jointly refer to several responses; ambiguity about which single response was meant stays unresolved. Both variants preserve historical requests/results, and the audit reconstructs the appropriate version.

| Development variant | Real cases matching authored expectations | Authored controls matching expectations | Reported input tokens over this set |
|---|---:|---:|---:|
| Baseline | 15/18 | 11/12 | 125,625 |
| Response evidence beside options | 17/18 | 11/12 | 138,121 |
| Response evidence plus reference boundary | 17/18 | 12/12 | 152,027 |

These are development matches, **not semantic accuracy estimates**. There is no repeated uncached baseline or independent held-out reference set. The second candidate was designed after inspecting the first result, so this is an iterative development comparison, not a preregistered confirmatory experiment. Input use increased; the change trades additional context for clearer reference selection. The variants use 33, 33 and 34 decisions respectively, including dependent set questions.

The current development map uses the last variant. It recovers e80→e79 (missing PDF engine), e86→e85 (missing image), and e92→{e85,e91} (the agent's expressed persistence claim). The ambiguous control selects unresolved rather than linking both possible referents. One disagreement remains: e50's current-environment installation assessment selects both e43 and e49, where the authored reference expected only e49. Both responses contain the same installation restriction. Whether the statement actually refers to both needs adjudication; extra supporting evidence must not automatically be treated as an extra referent. The raw selection remains visible.

The map now has eighteen assessment groups and twenty evidence edges: e50 and e92 each have two linked responses. Counts of edges must not become counts of assessment acts. Claim validity remains unjudged, including interpretations of empty output and assertions stronger than a directory listing.

`source-expression-association/1` adds a separate, deterministic relationship: **recorded with**. A dispatch is associated with selected prose belonging to its recorded parent message, or prose with the same source parent, within the same actor/trajectory and cutoff. No adjacency fallback is used. This source association does not mean the dispatch fulfills the stated intent. It recovers 34 contribution/dispatch associations across the 33 dispatches; one source expression contains two selected contributions. The action view displays the contribution before the actual operation, with source association and semantic correspondence explicitly distinguished.

This makes the e98/e99 inspection useful: the first contribution calls for verifying the PDF's existence and contents, while the paired dispatch only lists a directory. The source relationship connects them without inventing a successful content check or an automatic failure diagnosis. The resulting map has 101 cards and 100 evidence edges: 34 source expression associations, 33 source responses, thirteen plan-stage links and twenty assessment edges.

Evidence is in `research/feedback-inline-2026-10-07`: frozen `expectations.json`, both comparison files, every variant's real/control predictions, `promotion-review.json`, `promoted-audit.json` and `selected-map.json`. Reproduce the full comparison with `python -m research.compare_feedback_options --reference-boundaries`; it reuses saved decisions. `python -m research.review_feedback_promotion` records the current map and remaining disagreement. The former whole-trace and episode artifacts remain historical evidence.

Software checks: 432 tests pass, including source-parent/actor binding, absence of an adjacency fallback, source-only option excerpts, separate variant storage and replay. These checks do not validate semantic judgments. Next, test additional complete traces and connect persistent work targets and explicit method changes; do not keep adjusting this same small set and call the result generalization. The generator integration, independent references, broader activity coverage and matched RL checkpoint analysis remain incomplete.

Browser verification confirms 101 semantic cards, 33 action groups and 100 relation cards. The joint recurrence inspector links both e85 and e91. Searching `which entries` shows e98's requested PDF-content check beside e99's narrower directory listing. No console errors were observed. `browser-check.json` and `source-pairing.png` preserve this verification. An additional passing ATIF adapter check confirms that a message and its separately recorded reasoning text can share the dispatch's source parent; this is structural compatibility, not semantic transfer evidence.
# Retained instructions and contribution boundaries

7 October 2026. Three saved observers now expose the same airline source without replacing earlier predictions. `Local extraction` has 24 contributions with the original context policy; `Retained instructions` has the same 24 local meanings while retaining all recorded policy text; `Contribution boundaries v3` has 25 contributions, separating the e21 Report from the explicit Coordinate request. All three retain eighteen dispatch/response bindings. They are different observers on an identical source hash, not model training checkpoints.

`readable-context/2` preserves all visible preceding user instructions and system/developer-role records, including text beyond the usual event character limit. Role metadata comes from source adapters. Tool output containing the words “system policy” is not promoted into that role. Future, other-trajectory and private records remain excluded. Media remains explicitly uninspected. The inspector displays retained instruction event IDs. The full 54-decision context-only pass leaves all local meanings and boundaries unchanged. This verifies supplied context and observed stability on this source, not compliance or general semantic accuracy. Version 1 requests still replay exactly.

`contribution-boundaries/3` prioritizes independently contributed work before minimizing unit count. A completed answer followed by a substantive request for authorization can need two records; a current gap and immediate correction stay together, as do a plan's intended stages and a draft with supporting framing. It is an explicit experimental option. The default version 2 remains available; no activity vocabulary changes in this experiment.

The frozen contrast set contains seven real passages and six authored controls, including the user's whole-unit decorator reference. Only the airline mixed-message choice changes. Both versions retain the decorator Orient, the organized plan, the artifact draft, the final summary/courtesy and the prerequisite-status passage as coherent units. Exact option agreement is 10/13 for both versions; two apparent misses differ only by attached whitespace. Comparing non-whitespace boundaries gives 12/13 for both. Version 3 changes the remaining case from one Report to Report + Coordinate, but splits immediately before the authorization question rather than the reviewer's preferred boundary before the itinerary section. That attachment difference remains a visible review note. The frozen expectations were not changed to count the new choice as a pass.

The revised complete pass selects both new units' readable contents. The Report communicates the balance result and proposed itinerary. The Coordinate unit targets obtaining confirmation, records the requested update and cites the preceding itinerary as context. It does not claim that confirmation has already occurred. Candidates remain assistant-authored; no unattended generative capability or independent annotation accuracy is claimed.

The app's saved-pass selector is populated from complete, source-bound results. The selected observer is recorded in the URL; changing it preserves historical observations and loads that observer's own evidence. New local passes do not inherit earlier semantic target links. The earlier flagged calculation-instance error therefore remains inspectable in its original pass, while the revised pass explicitly has no newly selected target correspondences. Source action/result bindings remain available in every pass.

Verification: 442 software tests pass, including role-based retention, original-offset citations, visibility/cutoff exclusions, exact legacy request compatibility, complete-result catalog filtering and source binding. Browser review confirms 43 cards (25 contributions + 18 responses), the new Coordinate target, retained events e1/e3/e5 at its cutoff, and switching between the old one-unit and revised two-unit view. Software checks do not establish semantic accuracy.

Artifacts: `research/governing-context-2026-10-07/`, `research/contribution-boundaries-2026-10-07/` and `research/partition-revision-2026-10-07/`. The latter's `review.json` compares all three observers and retains the disagreement. The live revised view is `/semantic-map?run=d8c0e38f633a068fbc7aed74&observer=partition-revision`. The CLI exposes `--governing-context` and `--partition-standard contribution-boundaries/3` for explicit new passes; saved historical requests retain their original settings.

Next: establish task-instance correspondence from the selected natural-language work targets and their source context, then rerun relation inference on the revised units. The unresolved same-formula/different-passenger case must be addressed before recurrence metrics. Broader domain/producer coverage, independent review, candidate automation and matched RL checkpoint evidence remain required by the full product goal.

# Airline target paths and source review

7 October 2026. The fixed base-activity contract was applied to a complete public airline execution from [AgentProcessBench](https://github.com/RUCBM/AgentProcessBench/blob/0a42606b178a8c69d40c5765dc05c342f921e578/data/AgentProcessBench/tau2.jsonl), record 750. This is agent execution in a simulator, with no recorded training checkpoint. The source appeared in older project experiments; this pass is not an unseen-source holdout.

The pass accounts for 24 agent contributions and 18 separately bound action responses. The readable contents identify each passenger, reservation scope, calculation target, proposed update, confirmation request and reported outcome. The source has no recorded reasoning between many dispatches; no Orient explanation or causal reaction is fabricated for those gaps. Candidates are an explicitly assistant-authored development batch, selected by Jev raw argmax. This does not yet demonstrate unattended generative extraction or independent semantic accuracy.

`action-target-correspondence/1` operates only after complete local selection. It offers all earlier selected actions by the same actor in the same trajectory, without filtering by tool name, and selects the most recent counterpart with the same immediate work target. None, multiple targets and unresolved remain distinct choices. Oversized pools request retrieval rather than silently returning a negative. The selected edge is **same action target**, not successful retry, deliberate recovery, exploration or plan following. Exact JSON argument differences are a separate deterministic source comparison, with missing fields distinct from null and lists compared as complete ordered values.

The actual pass selects seven links: repeated account/flight retrievals, three booking pairs, and one erroneous calculation pair. Six links agree with the frozen assistant expectations; Evelyn's calculation is wrongly joined to Aarav's because their formulas are identical despite different selected work targets. Sixteen of seventeen selector decisions match those development expectations; the first action has no prior candidate and is excluded from that decision denominator. This small, authored comparison is not a product accuracy estimate. The wrong link remains visible and flagged in the semantic, target and relation views. It must not support validated recurrence metrics.

The source review also exposes a useful claim/evidence discrepancy: after the existing-reservation update, the agent reports a $122 credit-card charge, while returned payment history records $3,780 on that card. The map keeps the invocation, response and subsequent claim separately inspectable. Later user requests explicitly change the requested work from updating one reservation to creating three; the UI now exposes that instruction history instead of implying a model deviation.

Two foundation issues remain. First, a message answers the balance question and requests authorization for the booking update. Jev retains one Report unit even after receiving two coherent split alternatives. Both meanings survive in content, but its activity count hides the request. Second, the current readable-context policy retains user instructions but drops the initial airline policy once that system/context event leaves the recent window. These results cannot establish policy compliance. Both issues are flagged without rewriting saved predictions.

The first target-relation layout repeatedly embedded source quotations inside fields and received HTTP 400 at e55. The prior request used 32,350 input tokens; an input limit is suspected, not confirmed by a provider error body. `source-once/1` retains source text in the prefix and citations as original event offsets. It completes all seventeen choices, retains all thirteen comparable earlier selections, and reduces their reported input tokens from 212,423 to 168,141. The largest completed request still uses 32,040 input tokens: candidate retrieval and context size remain practical limits for longer traces. This representation comparison has no repeated-run control.

The UI has an **Action targets** projection over the same observations, preserving all 18 dispatches and responses across eleven raw selected paths. Searching `Aarav business` isolates the booking pair. The argument inspector shows the added $1,199 card payment. Reviewer annotations are bound to the exact source and extraction hashes and cannot change the model's raw selections. They are retrospective implementation-assistant findings, not automatic diagnoses or independent labels.

Evidence: `research/airline-semantic-2026-10-07/` contains the frozen contract and source provenance, baseline extraction, boundary alternatives, target expectations, actual predictions, source review, packet comparison, selected map and browser check. The live view is `/semantic-map?run=d8c0e38f633a068fbc7aed74`. Next: repair the mixed-work boundary and governing-context retention, then test task-instance correspondence on fresh contrast cases before expanding this relation to longer trajectories or macro metrics.
