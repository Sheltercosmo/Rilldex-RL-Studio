# Verification: the operation, its target and its evidence

Development decision, 6 October 2026. This refines the observation contract for review; it does not activate a new harness or add a failure taxonomy. Jev continues to choose the maximum-probability supplied option. Live H1 remains `semantic-activity/1.4`.

## What the researcher needs to distinguish

The useful question is whether the model actually attempts to test something, what it tests, and what happens afterward. Counting the word “check”, a verification plan, a generic lookup, or a passing-test claim cannot answer that question.

Keep the existing multi-label activities. Inspect describes information acquisition; Verify describes an attempted check. They can coexist when retrieval itself carries out or initiates a particular evidenced check. A text-only substitution or comparison can also be a check. The method, the purpose and the result are different observations.

Use a linked record beneath those activities, rather than expanding the headline tag list:

| Element | Required evidence | Boundary |
| --- | --- | --- |
| Target | Source span identifying the claim, artifact, state or condition under consideration | A generic task objective is not automatically the target of every later lookup |
| Criterion | An expressed expectation, comparison, acceptance condition or applicable environment rule | A rule must be tied to this operation and task instance; its presence in a long policy is insufficient |
| Proposed operation | The exact plan, offer, request or proposed checking code, if present | This does not establish execution; it may be absent for an actual check |
| Attempted operation | The current performed textual comparison/calculation, or recorded dispatch that initiates the check | An attempt need not pass, produce feedback or be correct |
| Recorded feedback | A later result bound to the dispatched operation, including explicit missingness | This is retrospective evidence and must not enter the earlier activity packet |
| Assessment or report | The model's own interpretation of the feedback or claim about completion | A report is not an independently established result |

These are evidence roles, not six mandatory stages. A check can occur without an expressed plan. A plan can remain unexecuted, and a dispatch can have missing feedback. Do not display them as a conversion funnel or force every trajectory through a fixed sequence.

## Concrete review cases already in the app

The observations below are implementation-assistant proposals based on preserved prefixes. They are not independent reference annotations. Each source unit retains its original Jev results in the comparison view.

| Case | Evidence available at the unit cutoff | Review question and proposed distinction |
| --- | --- | --- |
| [Retail offer](http://127.0.0.1:8765/#run=03a8e09d51e348a01eeccea3&activity_unit=u1b74ac0b162a8d52672e) | An offer to help with identity verification and a request for identifying details | The subject describes assistance. The later lookup cannot be attributed backward to this offer. Proposed checking is separate from an attempted check. |
| [Retail identifying lookup](http://127.0.0.1:8765/#run=03a8e09d51e348a01eeccea3&activity_unit=u6ab5a3765357334a9251) | The benchmark policy explicitly requires locating an ID using supplied identity details; the prefix contains those details; the dispatched tool performs that lookup | A lookup can initiate the policy-defined check. Inspect and Verify need not be exclusive. This is a claim about the benchmark's recorded procedure, not the security of real-world authentication. |
| [Retail user-details lookup](http://127.0.0.1:8765/#run=03a8e09d51e348a01eeccea3&activity_unit=u715b845b32544fbd2fc0) | The previous identifying lookup has returned an ID. The next tool contract retrieves profile/order details. No new specific comparison is expressed in the intervening message | Do not carry the previous authentication check forward automatically. A checking target/criterion for this dispatch remains unestablished. The isolated Verify result changes to present, which still needs independent review. |
| [SWE reproduction dispatch](http://127.0.0.1:8765/#run=00a05d9a7ebf17ee7760cc18&activity_unit=u0159ca8126159f470423) | Prior code and file feedback identify the reproduction script; the parent expression proposes comparing its output with the issue; the script is dispatched | This initiates a specific check. The script's subsequent output and whether it reproduces the issue are separate evidence. Its filename alone would not establish the purpose. |
| [Search answer comparison](http://127.0.0.1:8765/#run=7046d56e989fdc4a4e7714d1&activity_unit=ua7c21e7f6dab66f1e765) | Retrieved school descriptions and the question precede a textual comparison of a candidate against the task criteria | A check may be expressed in text alongside reasoning, assessment and revision. Observing a comparison does not establish that its facts or conclusion are correct. |

All five cases are in `research/activity-verification-isolated-2026-10-06/cases.json`. Run plus unit identity is required: local unit IDs alone are not globally unique. `research/verification-boundary-review-2026-10-06.json` records exact case IDs, source hashes, cutoffs and review proposals for these links.

## External evidence and the mapping decision

[ReasoningFlow](https://arxiv.org/html/2606.05402v1) provides manual node/relation annotations alongside a larger automatic set. Its `plan:verify` relation connects a target to a verification plan; `reason:execute` links a plan with textual implementation. These provide useful target and operation distinctions. They are not our multi-label activity references.

The pinned [analysis code](https://github.com/jinulee-v/reasoningflow/blob/d839f008d6db25efaa2ca0f949ed517f8262a1d9/localverify_analysis.py) counts certain source nodes with outgoing verification-plan or validation relations. That unit is a targeted proposition, not a performed checking operation. The [relation guide](https://github.com/jinulee-v/reasoningflow/blob/d839f008d6db25efaa2ca0f949ed517f8262a1d9/schema/edge_labels.yaml) also links consistent or conflicting conclusions. Such links do not by themselves establish an expressed check, a correction or a real error. No automatic relabeling into Verify is justified.

Our audit used six traces selected before label inspection, two per domain: math, physics and chemistry. The pinned GitHub tree has 31 first-annotation files and 21 second-annotation files. This differs from assuming two accessible annotation files for every trace; no equivalence with the Hugging Face distribution is claimed. The remaining 25 traces were not downloaded. They are reserved, but require source/task deduplication before being called a held-out evaluation set.

The current audit is `research/reasoningflow-reference-2026-10-06/audit-v3/audit.json`:

- All 426 native spans match raw text exactly: 415 response spans and 11 question spans. Both annotators assign the same label to 389 matched spans; 37 disagreements remain. This does not evaluate our tags or segmentation accuracy.
- Two self-links violate the source-before-destination rule, and two edges have blank labels. They remain in the original files and audit, with no fabricated repair. Invalid annotations are separated from ordinary annotation disagreements.
- Of 149 candidate endpoint pairs involving the four inspected relation types, 94 have matching relation sets and endpoint node labels with valid source evidence. The remaining 55 remain inspectable but are not consensus references. These are native-schema references only.

The source validity issues are localized, but become material if these files are treated as an exact graph reference. Use the validated subset and retain excluded rows for review. Annotation disagreement is evidence about the task, not a data defect to erase. This is a single pinned snapshot; it supplies no time trend or training-checkpoint comparison.

Reproduce without network or inference:

```powershell
python -m research.inspect_reasoningflow research/reasoningflow-reference-2026-10-06 --output research/new-reasoningflow-audit
```

`audit-v1` and `audit-v2` are retained preliminary outputs. Use `audit-v3`, generated by `reasoningflow-reference-audit/1.1`: it distinguishes an invalid counterpart annotation from an unannotated relation and records question/response counts. Original sources never changed. Only local audit code ran; no upstream scripts were executed.

## How to test the contract with Jev

1. Build source-bound target and criterion candidates outside Jev. Include explicit no-suitable-candidate and unresolved alternatives. Candidate recall needs its own assessment; a correct choice from an incomplete list can still miss the real target.
2. Keep the activity decision independent from the target/link questions. Each bounded question uses argmax. Preserve disagreeing answers; do not silently change one winner to make it consistent with another.
3. Distinguish a proposal from a current textual operation, a recorded dispatch, and a retrospective report using exact spans. A source unit may carry multiple activities, but described future work must not become current execution.
4. Keep prefix eligibility and result linkage separate. Missing or invalid evidence is a recorded limitation, not a low-probability decision. Never retrieve a later answer, reward or feedback as evidence for the earlier membership decision.
5. Evaluate native relationships on their own labels and our Verify membership on independently reviewed product references. Test positive cases and contrasts: a lookup used for an explicit check versus one retrieving an unknown detail, a plan versus its execution, and a comparison versus a bare assertion.

This requires validation before promotion. No new field is added to the production harness by this document. Useful eventual measures include planned-but-unobserved checks, target coverage of attempted checks, recorded results per dispatched check and claim-to-check support. Each needs its own opportunity denominator, missingness and relation validation; none is yet a validated training monitor.

## Relationship experiment: what is useful and what failed

The first development experiment is complete in `research/native-relations-probe-2026-10-06`. It uses the six previously audited traces, their human-provided boundaries, and only the prefix available at each subject. Source and subject identities, raw spans and actor boundaries are checked before a request can be built. Native annotation labels, edges and future text are absent from Jev's inputs. `tracker/relation_candidates.py` is a reusable experimental retriever over framework-independent source units, not a new production adapter or tagger.

Candidate availability and classification must remain separate. Across all 84 strict native positive links in these six traces, retrieving the 12 most recent units retains 10/10 verification-target links and 72/74 plan-implementation links. Keeping six recent units plus six lexical matches retains 9/10 and 73/74 respectively. Both retain 82/84, but the aggregate hides a tradeoff: lexical retrieval recovers a distant implementation link while displacing a relevant verification target. Neither policy is established as generally better. These are native-positive coverage counts, not recall of all semantically valid relationships.

The initial harness asked independent present/absent/unresolved questions for each candidate, plus a candidate-list question with explicit no-suitable and not-applicable alternatives. All winners use `argmax/1`; no confidence filter, probability floor or consistency repair was applied. Its 43 completed requests contain 487 pair questions, of which 47 have unresolved native references and are excluded from scoring. The negative-heavy match total is not a useful headline:

| Relationship | Retrieved native positives recovered | Positive choices matching native edges / scored positive choices |
| --- | --- | --- |
| Target to verification plan | 1 / 6 | 1 / 11 |
| Plan to textual implementation | 8 / 12 | 8 / 51 |

Seventeen requests contain contradictory pair/list choices. This is an observable consistency failure, not a reason to silently change a selected option. The experiment is not ready for production use.

### Controlled question-binding follow-up

`research/native-relations-binding-2026-10-06` freezes 12 cases covering three domains and five distinct traces. Cases were chosen by identity hash within domain/relation/sampling-stratum groups, without inspecting outputs. Each retains its original result, a fresh exact-request repeat, and a variant that repeats the actual source/subject text and relation definition inside every pair question. Candidate lists, model, prefix evidence, candidate-list question and argmax rule remain fixed. Wording and local text binding change together, so their effects cannot be separated by this experiment.

| Variant | Verification targets recovered | Plan implementations recovered | Positive choices disagreeing with native graph | Pair/list inconsistencies |
| --- | --- | --- | --- | --- |
| Original saved results | 0 / 2 | 2 / 3 | 14 | 5 / 12 |
| Fresh identical-request repeat | 0 / 2 | 3 / 3 | 14 | 4 / 12 |
| Explicit text-pair questions | 1 / 2 | 3 / 3 | 11 | 5 / 12 |

There are 142 pair decisions, with 132 scorable native references and 10 unresolved references, plus 12 list decisions. The exact repeat changes 4/154 winners. Explicit text-pair questions change 13/154 winners relative to the original; eight scorable decisions become matching and three cease matching, with two changes on unresolved references. The small, dependent development sample supports investigating the wording change, not claiming an accuracy improvement or stability. Use `comparison-v2.json`; the preliminary `comparison.json` incorrectly described the follow-up as covering six distinct traces. Requests and results are unchanged.

### The more important finding: relation scope must be explicit

Inspection of disagreements and the pinned relation guide revealed a harness-definition mismatch. Our experimental `reason:execute` question allows any later textual step carrying out an earlier plan. The native guide includes a convention linking a plan to the first nodes of parallel reasoning chains. Its sparse graph therefore does not represent every broader plan-to-operation relationship. Neither human annotator recording a particular edge is not proof that the broader semantic relationship is absent. The reported numbers measure disagreement with that graph; calling all of these disagreements product-classification errors would be misleading. No references or predictions have been rewritten.

Three concrete cases explain the implications:

- In the math calculation case `90d46afa1f8b…`, both native annotators link multiplication to the immediate numerator-computation plan. Jev also links it to the earlier full-expression calculation and verification plans. Those additional choices may represent broader plan implementation; they require a different reference contract.
- In verification case `5eb7f0fde653…`, explicit binding recovers the native target stating the smallest candidate value, and also selects an earlier list item containing that value. This exposes the distinction between exact source occurrence and a claim's semantic identity. A dashboard must not count repeated mentions as separate checked claims without a validated identity rule.
- In physics case `1252efe2d8b7…`, Jev still selects factual formula/substitution statements as implemented plans. This remains a concrete plan-versus-premise concern under the supplied question, independently of graph sparsity. The wording change removes another factual-premise link but does not solve this boundary.

These are development interpretations by the implementation assistant, not new independent human labels. Exact pairs, choices, references and changes are preserved in the comparison files.

The next design step is to specify two separate evaluation contracts: reproduction of the publisher's direct graph annotations, and our product's broader plan/target relationships. Keep exact source occurrences separate from semantic target identity and nested-plan membership. Do not add headline activity tags to compensate for unclear relationships. Before another model sweep, make each relationship's inclusion, exclusion and scope rules concrete on these inspected cases. Then test the fixed contract on independently annotated product cases and reserved, deduplicated sources. Current role extraction, candidate completeness, plan-versus-premise discrimination and cross-question consistency each need their own validation.

This slice made 67 new provider calls: 43 initial calls and 24 controlled follow-up calls. The 12 reused originals are not counted again. Reported usage totals 711,902 input tokens and 36,411 output tokens. The deliberately duplicated full-prefix packets are expensive development instruments, not a production cost target; context packaging and question decomposition are valid optimization sites outside argmax. This experiment adds no production observations and measures no RL checkpoint change.

Recompute the controlled comparison without network or inference:

```powershell
python -m research.reasoningflow_relations compare-binding research/native-relations-binding-2026-10-06 --output research/new-binding-comparison.json
```

## Source-time roles and later relationships — 7 October 2026

The next experiment made the scope distinction executable in `tracker/relation_contracts.py`: a source-plan property, broader plan implementation, and a separate ReasoningFlow direct-edge question. Broader implementation admits a first or later concretely evidenced step of a plan. Direct graph reproduction follows the publisher's first-node convention for parallel reasoning chains. Neither implies correct reasoning, task success or a completed plan. An actual request is a coordination operation; it does not establish that the recipient performed the requested check.

`research/relation-scope-2026-10-06` contains 16 deliberately selected development contrasts across seven traces: eight reasoning pairs, five SWE pairs, two retail pairs and one telecom pair. The shared source contract is independent of the producer. Native text and normalized rollout projections both bind the exact earlier/current spans to recorded prefixes, with trace/actor separation and unique event order. Unread media is unsupported and rejected explicitly. Native labels, final rewards and later evidence are absent from requests. The normalized rollout projection relies on the existing adapters; this experiment does not independently validate raw extraction.

The 16 requests completed. Jev selected present for every native direct-edge question: all three native positives and all five native negatives. That does not solve direct graph recovery. Its broader answer was absent for the post-run SWE report, present for the four SWE dispatch cases, and mixed across the other domains. These are observations, not accuracy results. One chemistry case selected a direct implementation while denying broader implementation. The original choices and this inconsistency remain visible.

More significantly, the identical earlier retail offer received a present Plan choice when paired with its first lookup, and an absent choice when paired with a later detail lookup. We cannot isolate context sensitivity from response variation with these two requests, but both supplied evidence after the source expression. That packet cannot establish the role as it was observable at the original source cutoff.

### The temporal contract now enforced

1. Observe an expression's own role at its source cutoff. Its input contains only that source and its preceding recorded prefix. It contains no later subject or relationship result.
2. Observe a later relationship at the current operation's cutoff. Identify both source occurrences exactly. If earlier role observations are used in a downstream composition, bind their source, cutoff, observer version and packet identity.
3. Reuse an identical source-role packet across later pairs. This establishes consistent provenance and avoids repeated source classification. It does not prove the model's answer is correct or stable on a fresh call.
4. Preserve each raw argmax winner. Conflicting role/link choices are explicit inspection findings; they are not repaired by thresholds, majority votes or overwriting a field. A compatible set of choices is not automatically a validated link.
5. Keep retrospective interpretation separate from source-time activity. A later result can clarify what happened; it cannot silently become evidence for what was observable earlier. This rule applies beyond Plan to hypotheses, reported completion, verification and other activities.

The source-time projection deduplicates the 16 pairs into 13 exact source packets in `research/source-plan-time-2026-10-07`. All 13 calls completed. Their selections differ from the earlier pair-time Plan selections on three of the 16 pairs: two formula statements change to absent, while the second retail pairing now uses the same present source choice as the first. Wording was shortened and criteria made explicit at the same time, so this is not a causal estimate of cutoff isolation's effect. Independent product references remain absent.

The revised source choices expose two implementation-without-plan inconsistencies in the old link results; the chemistry direct/broader inconsistency also remains. Nothing changes those original link choices. The next inference work should address these concrete role/operation/link failures with separately inspectable inputs and fixed definitions, rather than expanding the failure taxonomy or deriving a macro score from them.

The current [TypeSafe primitives guide](https://docs.typesafe.ai/primitives) specifies that question IDs are not model inputs and recommends explicit field references. Its [workflow guidance](https://docs.typesafe.ai/concepts/how-to-build-with-system-one) favors narrow questions and separates content from evaluation logic; the [Choice guide](https://docs.typesafe.ai/primitives/choice) allows contrasting option descriptions. The source-time question follows those conventions. We retain the user's argmax-only selection rule; none of the documentation's optional confidence-routing examples are adopted.

### Review and reproducibility

- `research/source-plan-time-2026-10-07/review.html` collects source-time Plan judgments with no later evidence or model predictions.
- `research/relation-scope-2026-10-06/review-v2.html` shows both exact endpoints and the later prefix for relationship review. It explicitly describes its original source-role question as retrospective. Native references and predictions are excluded. Opaque case IDs replace the descriptive experiment IDs that could suggest answers. The original `review.html` is retained as a preliminary export and must not be distributed as blind review material.
- Both use the existing review component, begin with all fields unfilled, retain independent-review/adjudication declarations, support source citations, export committed annotations and resume without replacing them. Give a reviewer only the relevant HTML file; the other experiment files expose labels or predictions. The later milestone below connects these packs to standalone scoring with the shared activity-review rules; no exported model proposal counts as a human reference.

This slice made 29 new calls: 16 relationship packets and 13 source-time packets. Reported usage is 112,401 input tokens and 2,221 output tokens. There are no provider calls during review export or reproduction. All 245 Python tests and both the new relationship review browser suite and existing activity review suite pass. Tests establish packet isolation, binding, missing-media handling, raw-winner preservation and review mechanics; they do not establish semantic accuracy. The live H1 harness and historical observations remain unchanged. See `research/relation-scope-delivery-2026-10-07.json` for preservation hashes.

```powershell
python -m research.relation_scope summarize research/relation-scope-2026-10-06 --output research/new-scope-results.json
python -m research.relation_scope summarize-roles research/relation-scope-2026-10-06 research/source-plan-time-2026-10-07 --output research/new-source-time-results.json
```

## Wider source-time sample and reference scoring — 7 October 2026

`research/source-plan-corpus-2026-10-07` inventories every one of the 415 response spans in the six previously allocated development traces. It freezes eight spans per trace using a fixed identity hash before consulting labels or outputs. All 48 requests use the unchanged source-time Plan question, full preceding question/response text and the exact source cutoff. The general packet builder no longer requires a later pair to observe a source. The previous 13 source packets reconstruct exactly as the original saved requests. No reserved traces were opened, and no held-out claim follows from this development sample.

All 48 new calls completed: 17 present, 31 absent, with no unresolved winner. Native annotators agree on the role of 40 sampled spans and disagree on eight. Jev matches the native planning/non-planning mapping on 35 of those 40, selects present for all ten agreed native planning spans, and also selects present for five agreed native reasoning spans. Counts are descriptive. Equal sampling per trace does not estimate prevalence across all 415 units, and the common producer is QwQ-32B-Preview rather than multiple RL checkpoints.

The [pinned publisher node guide](https://github.com/jinulee-v/reasoningflow/blob/d839f008d6db25efaa2ca0f949ed517f8262a1d9/schema/node_labels.yaml) explicitly allows subsequent verification steps to help distinguish planning from reflection. It assigns a single native role to a node. Our prospective, overlapping property therefore has a different information boundary and definition. Native agreement is useful evidence for inspecting discrepancies; it is not independent product accuracy.

The five discrepancies warrant different follow-ups. These are implementation-assistant interpretations, not new reference labels:

| Source case | Observed content | Boundary to investigate |
| --- | --- | --- |
| `e0c167734e6c…`, math 12 | An unfinished premise beginning “But since” beneath an earlier divisibility plan | The source span stops before the sentence's next-step clause. Determine whether it is a usable local unit; a surrounding plan must not automatically confer Plan on its premises. |
| `cbe51cdc099e…`, math 12 | A derivation of a divisibility requirement, expressed with “I need it to be” | Distinguish a desired mathematical condition from a proposed operation. Wording alone is insufficient. |
| `663c11b0becc…`, physics 3 | An asserted equivalence between two forms of an exponent | It may implement an earlier calculation plan without itself expressing a new plan. |
| `f9f54f43f6d1…`, physics 3 | A calculation introduced by “Calculating that” | Classify the operation expressed now separately from the intended work it serves. |
| `bd936d7e3600…`, physics 4 | A supplied velocity followed by “so I can calculate gamma” | A mixed fact and prospective step can legitimately overlap roles; decide whether ability is adopted as a next step using the preceding context. |

The practical optimization target is the definition and unit/context construction outside argmax. First specify local role versus plan membership with these contrasts, retain mixed activities where evidence supports them, and flag unusable span boundaries independently. Then compare a fixed candidate harness against the frozen baseline on the same development cases and separately sourced software/dialogue cases. Do not patch individual case IDs, choose cutoffs from observed probabilities, add failure categories, or convert all five native discrepancies into assumed errors. Independent review and reserved, deduplicated evaluation remain necessary before promotion.

### Reviews can now be scored

`research/relation_review.py` reconstructs and validates frozen requests and blind exports, checks saved argmax results, and consumes the existing review JSONL format. It shares review collection, provenance, consensus and adjudication logic with the activity evaluator. Invalid units exclude references; context concerns stay visible without erasing an otherwise known reference. Missing/unresolved predictions remain in applicable recall denominators. Missing/disputed reference labels do not become negatives. Native publisher metadata never enters product-reference resolution.

The three `inspection.html` reports cover 48 corpus sources, 13 earlier source-time cases and 16 relationship pairs. They expose exact source/current spans, citations, per-field definitions, preserved distributions, submitted reviews and a separate publisher-annotation panel. All 77 cases currently lack independent product references and show no accuracy values. Give a blind reviewer only `review.html` (source packs) or `review-v2.html` (pair pack); inspection pages disclose predictions and labels.

```powershell
python -m research.plan_corpus summarize research/source-plan-corpus-2026-10-07 --output research/new-plan-native-comparison.json
python -m research.relation_review research/source-plan-corpus-2026-10-07 --annotations reviewer-a.jsonl --annotations reviewer-b.jsonl --output research/new-plan-review.json --html research/new-plan-inspection.html
```

Use the same scoring command with either earlier collection directory. Omit `--annotations` to inspect the collection's local annotations if present, otherwise receive an unscored report. Use new output paths to preserve earlier results. These experiments remain outside live H1 ingestion and do not measure training progress.

This slice used 48 new provider calls and zero reused results, reporting 84,422 input and 2,095 output tokens. All 256 Python tests and four browser suites pass. Tests cover label-independent sampling, source cutoffs, final-unit support, preserved old requests, reference eligibility, adjudication, raw argmax, all 77 real display cases, source citations and desktop/mobile layout. Synthetic test reviews never enter real datasets. See `research/source-plan-corpus-delivery-2026-10-07.json` for source, report and production-preservation checks.

## Local expression versus plan membership — controlled follow-up

The new candidate in `local_plan_packet` changes only the question wording, option definitions and harness identifier to `source-plan-role/0.2-experimental`. It requires the exact span to specify intended work, while allowing preceding context to resolve references and attribution. A surrounding plan does not automatically make its premises, calculations and results planning expressions. A required mathematical condition differs from a proposed operation for achieving it. Mixed content can retain Plan alongside another activity. No probability/confidence threshold is used, and no later text is added.

`research/source-plan-locality-2026-10-07` freezes all 61 source units from the two existing source collections, across nine traces. The original 61 results are reused as baseline. One fresh exact repeat and one candidate request were made for each source. All 122 new requests completed in provider session 44202, reporting 263,896 input and 5,316 output tokens. The baseline repeat preserves all 61 winners. The candidate selects 24 present and 37 absent, changing six baseline choices. One repeat is a control observation, not proof of general stability or the cause of a particular difference.

| Source expression | Baseline / repeat | Candidate | Inspection implication |
| --- | --- | --- | --- |
| Incomplete divisibility premise, math 12 | present / present | absent | Consistent with classifying local content, but the incomplete source boundary still needs a usability reference. |
| Derivation of a required divisibility condition, math 12 | present / present | absent | Separates a required state from intended work. |
| A numbered divisibility condition, math 12 | present / present | absent | Native annotators disagree between reasoning and assumption; no native score is assigned. |
| Exponent equivalence, physics 3 | present / present | absent | A computation serving a plan need not itself specify intended work. |
| Computation introduced by “Calculating that”, physics 3 | present / present | absent | Performed reasoning and proposed work remain separate properties. |
| Doppler formula introduced by “Now, for…”, physics 4 | absent / absent | present | Unresolved intended-work versus discourse-transition boundary; this must not disappear behind improved subset metrics. |

These implications are implementation-assistant interpretations, not independent annotations. The final formula is labeled fact by both publisher annotators in the pinned source, but it belongs to the earlier-source collection without native-reference scoring metadata. Its local expression combines a transition with a formula, so the appropriate overlapping product activity needs a product reference, not an automatic native mapping.

On the 48-unit corpus subset, the same 40 units have agreed native roles and eight remain unscored. The candidate matches 39/40 mapped roles versus 35/40 for both baseline runs. It retains all ten native planning positives and selects present on one native non-planning case, the mixed velocity/next-calculation expression. This is a schema comparison on development data, not an accuracy gain. The formula concern outside that scored subset illustrates why coverage and inspectable counterexamples must accompany aggregate metrics.

The five non-reasoning sources comprise three software planning expressions, a retail offer and a telecom request plan. All three variants select present on all five. This preserves those particular observations but does not test adequate negative, ambiguous, mixed or quoted cases in those domains. It is not evidence of cross-domain accuracy. The next sampling step should include those missing types through a declared source-based sampling protocol, without using current model outputs to manufacture class balance.

### Compare and review the candidate

`inspection-local.html` shows all three observations beside each exact source, retaining definitions, raw distributions and request hashes. A separate filter finds any differing recorded choices; those differences do not enter the semantic-error count. Native labels remain separate from independent references. No actual product reference annotations exist.

The scorer requires `--variant baseline`, `--variant repeat` or `--variant local` for this multi-variant collection. The reference metric section applies only to that selected variant. Review case hashes bind the exact question definition and source packet. Baseline and repeat use identical blind cases and may share genuinely blind reviews; the candidate has different hashes, and cross-contract review imports are rejected. Synthetic tests demonstrate these mechanics without adding human labels to the real collection.

```powershell
python -m research.plan_locality summarize research/source-plan-locality-2026-10-07 --output research/new-locality-comparison.json
python -m research.relation_review research/source-plan-locality-2026-10-07 --variant local --annotations local-reviewer-a.jsonl --annotations local-reviewer-b.jsonl --output research/new-locality-review.json --html research/new-locality-inspection.html
```

Give independent reviewers only the applicable `review-baseline.html` or `review-local.html`. They must not see the comparison/inspection files first. All 262 Python tests and three relevant browser suites pass: the new comparison/review binding workflow, existing activity inspection and existing relation inspection. The live H1 harness and prior source/results remain preserved. This candidate is not promoted; the next work is reference and cross-domain coverage, not another unbounded wording sweep. Receipt: `research/source-plan-locality-delivery-2026-10-07.json`.

## Broader source expressions and exact review citations

The fixed sample in `research/source-plan-transfer-2026-10-07` selects six expressions per domain from five existing development traces. Within each actor's available model-text units, source order is divided into thirds and two units per third are chosen by a fixed identity hash. The imported source identities and hashes are frozen. No semantic cue term, reward, native annotation value or Jev output directly enters selection. Reimporting a changed source identity is a different sample. These temporal strata are not phases of task behavior; search's available prose, for example, follows tool activity. Missing private reasoning stays unobserved.

| Domain | Available model-text units | Selected | Recorded choices | Plan present | Plan absent | Request failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Software | 17 | 6 | 6 | 3 | 3 | 0 |
| Search | 7 | 6 | 6 | 0 | 6 | 0 |
| Retail | 16 | 6 | 6 | 1 | 5 | 0 |
| Telecom | 22 | 6 | 6 | 2 | 4 | 0 |
| Airline | 83 | 6 | 3 | 0 | 3 | 3 |

These are observed argmax choices, not accuracy estimates. The software positives describe pasting example code, running it and running it again to reproduce the issue. Telecom positives include “Let's troubleshoot further” and a request that the customer run a SIM-status check. The retail positive introduces exchange options. The latter heading and customer-directed request need explicit review of proposed work versus reporting options, and ownership of an intended step versus asking another actor to act. These are implementation-assistant concerns, not independently adjudicated errors. The formula/transition boundary from the previous comparison also remains open.

All 30 requests were attempted, with 27 saved results. Three late airline expressions failed with HTTP 400. Two sanitized errors explicitly report `max_tokens_exceeded`. The first failed request was repeated twice for diagnostics, but the diagnostic filter omitted the error-type value; its cause remains unconfirmed. There were 32 total attempts and no changed-request fallback. The 27 successful responses report 159,669 input and 1,182 output tokens; failed-request usage is unknown. The error receipts bind the exact frozen request hash, and the report shows all three results as unobserved. No confidence threshold, assumed negative label or implicit truncation was introduced.

The next context optimization should have its own packet version and evidence audit. Start by measuring repeated content and required subject/instruction/actor context in these real long prefixes. Lossless deduplication and removal of source evidence are different changes. Preserve exact source references and cutoffs, disclose omissions, and compare any modified requests on a frozen sample before claiming sufficient context or improved tagging. A smaller request alone is not proof of semantic accuracy.

The review workflow now allows several exact source quotes for each field, each marked as label evidence or context. Offset validation uses Unicode code points within the cited source record and rejects altered text, unsupported fields, out-of-scope records and duplicates. An identical evidence ID in source and prefix is disambiguated by its target. Export/resume and adjudication preserve the spans; the inspection page highlights the exact words. Whole-record citations remain compatible. This makes disagreements inspectable but does not certify a reviewer, establish blinding or validate a semantic judgment.

Use `review.html` for independent labels and `inspection-observed.html` to inspect results and request failures. The original `inspection.html` is an intentionally retained pre-inference snapshot. No independent product references have been added, so the candidate stays experimental and macro/training claims remain deferred. All 272 Python tests and five browser suites pass; the production source/history hashes and previous frozen research artifacts are unchanged. See `research/source-plan-transfer-delivery-2026-10-07.json`.

## Reversible representation of repeated prefix content

The three rejected airline packets contain identical feedback text and repeated tool definitions. `prefix-value-references/1-experimental` represents a duplicate `text` or `tool_contract` by referencing the same field on an earlier event. The first value remains inline. The entire request must shrink after adding the encoding explanation and fingerprint; otherwise the function returns an exact copy of the original. The current source expression stays explicit. No event is removed, and roles, actor attribution, temporal order and source locations are unchanged. Identical tool output does not establish that the environment state was identical.

The decoder rejects missing, forward, cyclic/ambiguous or changed-content references and verifies the complete expanded request against its original hash. Source content colliding with the reserved marker is rejected rather than reinterpreted. These checks prove exact reconstruction, not that a model follows the reference as intended. The encoded request has its own hash and measurement-profile field. The original source and all previous results remain immutable.

The [current provider model documentation](https://docs.typesafe.ai/models), checked 7 October 2026, lists a 32k-token limit for state plus the longest question and a 64k-token total-request limit. These limits are not converted into an invented characters-per-token guarantee. TypeSafe's [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13) also discuss indirection and irrelevant context. Reversible references introduce a representation dependency; they do not establish that all supplied context is relevant or sufficiently clear. The supplied Plan question, options and argmax rule stay unchanged in this experiment.

The frozen study includes all 30 expressions from the preceding transfer sample. Eleven requests shrink; nineteen are exact no-ops and reuse saved responses. Eight changed requests have successful baselines, so they receive fresh baseline repeats and compact requests. The three rejected requests have no baseline choice and receive compact requests without repeating the known rejected representation. All 19 new calls finish successfully. The three recovered observations select Plan absent; missing baseline values remain unobserved in the comparison.

| Measurement | Observed result | Limit |
| --- | --- | --- |
| Previously rejected requests | All three compact requests return results | Does not establish support for every long prefix or confirm the uncaptured original error cause |
| Evidence preservation | Each compact packet reconstructs its original exactly; all 66 airline events retained | Does not establish equivalent model interpretation |
| Fresh paired comparisons | Eight baseline/repeat/compact triples; no changed winners | All eight baseline choices are absent; positive-choice transfer is untested |
| Unchanged requests | Nineteen exact result reuses | These are not new stability observations |
| Airline request size | 88,014 / 88,797 / 88,943 characters become 57,102 / 57,885 / 58,031 | Serialized characters, not tokens; each retains twenty content references |
| Airline compact input tokens | 22,028 / 22,371 / 22,426 | Original failed responses provided no token usage |
| Paired successful input tokens | 51,878 baseline, 51,878 fresh repeat, 51,250 compact | These eight requests are a small development slice |
| New inference usage | 169,953 input and 836 output tokens | Nineteen fresh calls; reused results excluded |
| Product reference accuracy | Unmeasured | Independent references remain absent |

The inspection page links every content reference to its expanded source record and exposes each exact model-facing state. Source reading and request representation remain distinguishable. Prediction-blind exports bind their hashes to the selected representation; scoring keeps inline and encoded profiles separate. A matching winner is not a scored correct answer, and successful input handling cannot settle the options-heading, customer-request or formula/transition Plan boundaries.

All 280 Python tests and four browser suites pass. The old source/results and production hashes are preserved. The next evidence priority is positive/context-dependent cases and the actor/operation boundaries, rather than further repeats of these negative cases. The encoding remains experimental and is not applied to production H1. Receipt: `research/prefix-encoding-delivery-2026-10-07.json`.

## Actor, intention, offer and request — separate observations

The telecom request for the customer to run a SIM-status check follows the model's earlier statement that it would check the SIM. The request may serve that plan, while the requested operation belongs to the customer. Consequently, a rule that restricts Plan to directly model-executed work would discard a useful distinction. The new component preserves Plan and observes expression properties independently; it does not define Plan as a union of the new properties.

The distinction draws on [DIT++ communicative functions](https://dit.uvt.nl/) and its [annotation guidance](https://dit.uvt.nl/is-guida.html): offers condition the speaker's work on consent, while requests concern an addressee's action. DIT++ separates communicative function from semantic content. Our contract instead restricts interpretation to the supplied source-time evidence and does not import all implicit-function or intention conventions. The [2024 paper on combining dialogue acts and application-specific semantic content](https://aclanthology.org/2024.isa-1.15/) supplies related design motivation. These sources are neither product reference labels nor evidence of ISO compliance.

`tracker/actor_intent.py` registers `actor-intent/0.1-experimental`, with independent present/absent/unresolved questions:

| Property | Observable distinction | Important boundary |
| --- | --- | --- |
| Own intended work | The model adopts prospective work, including shared participation | Ability alone, an unaccepted offer and a report of past work do not suffice |
| Own offered work | A specific operation is offered pending preference, consent or authorization | Available products/options alone are not an offer to perform work |
| Request to another actor | The model asks for action, information, preference or permission | A consent question may also express offered work; the request does not establish compliance |
| Information presented | Factual/informational presentation, options, answers, status or reports | The observation does not certify factual truth or completion; bare structure and unendorsed quotations do not suffice |

The frozen pack includes every source from the preceding thirty-case study, without selecting new cases by these outputs. All thirty requests complete, yielding 120 choices. Their counts are descriptive:

| Property | Present | Absent | Unresolved |
| --- | ---: | ---: | ---: |
| Own intended work | 4 | 26 | 0 |
| Own offered work | 1 | 29 | 0 |
| Request to another actor | 7 | 23 | 0 |
| Information presented | 14 | 16 | 0 |

The counts overlap. Zero unresolved winners does not imply perfect coverage or certainty. This is one pass over previously inspected development data, with no independent product references, held-out evaluation, prevalence estimate or training-checkpoint comparison. Recorded provider usage is 246,572 input and 5,134 output tokens.

| Source case | Selected properties | Preserved earlier Plan |
| --- | --- | --- |
| Retail introduction to camera exchange options, `38a71d583840…` | Information presented | Present |
| Telecom request for the customer to run a SIM-status command, `6ed33ace6981…` | Request to another actor | Present |
| Airline question seeking consent to create reservations, `01f6db3ceb53…` | Own offered work and request to another actor | Absent |

These contrasts are observations for review, not adjudicated corrections. The earlier Plan request and result remain available as a separately defined measurement and are excluded from the new reference score. The model-facing request and blind review exclude previous Plan predictions. Each new choice uses argmax; no confidence floor, margin cutoff or cross-field repair changes it.

`inspection.html` adds a property summary and a reusable field/selected-option case filter. Raw winners with a separate evidence limitation remain selectable. Missing responses and questions not asked have distinct filter values. Filtering the case list does not change profile-scoped reference metrics. Descriptive counts span the retained representation profiles, so they do not establish representation equivalence. The report preserves exact source/prefix evidence and the reversible representation audit.

The study and review scorer reproduce their frozen cases, requests, blind exports and summaries. All 286 Python tests and four browser suites pass, including overlapping properties, missing-choice filters, raw winners with evidence limitations, exact citations, review eligibility and desktop/mobile layout. Synthetic reviews used by tests remain outside the real collection. Earlier artifacts and production source/history hashes remain unchanged. Receipt: `research/actor-intent-delivery-2026-10-07.json`.

The next required evidence is independent annotation of these distinctions, plus mixed, quoted, indirect and context-dependent expressions across additional sources. Full operation-target extraction and links to actual attempts/results remain unimplemented in this component. The formula/transition Plan boundary remains open. Keep this component experimental until its accuracy and usefulness for a complete-trajectory investigation are measured.

## Complete telecom trajectory: what the tags can and cannot explain

The existing AgentProcessBench telecom record (`tau2_telecom:query-34`, record 921, sample 1) provides a complete non-programming development investigation. All 22 eligible monitored-agent spans now have current `semantic-activity/1.4` observations under `argmax/1`. The pass adds 18 calls to four exact cached observations; it does not change the definitions, source boundaries or previous winners. The new calls report 111,907 input and 13,675 output tokens. Both sparse and complete snapshots remain frozen in `research/telecom-full-2026-10-07`.

| Investigation question | Source-supported finding | Interpretation boundary |
| --- | --- | --- |
| Who performs the requested work? | The assistant requests customer checks/actions; four customer-side calls are recorded, with zero assistant dispatches. | Requests do not establish agent execution. External results have unestablished visibility until information is communicated to the assistant. |
| Does the requested work change? | The request moves from switching off Airplane Mode to checking SIM status after the customer reports continued lack of signal (`e9`, `e13`, `e14`). | A zero Revise tally does not describe this change of target; adjacency alone is not a validated adaptation metric. |
| What supports the ending? | The customer-side reseating result records signal/data restoration (`e22`), followed by the customer's recovery report (`e23`). | This is recorded outcome evidence, not an assistant verification attempt or an activity reference label. No later assistant completion statement is recorded. |
| Are intentions separated from attempts? | Two intended-check spans select Plan and Inspect together (`u4aba401e658c6ffbcbe7`, `uf263e4f21678e601fe52`). | Preserve both winners. These spans require independent review before treating Inspect counts as performed information-seeking. |
| Does Assess count feedback interpretation? | Three Assess choices include anticipated usefulness and a general statement about reseating. | A useful feedback-response measure needs an explicit feedback target and actor/time relationship; the tally alone does not provide that. |

`findings.json` preserves five assistant-authored findings/concerns with 15 exact, offset-bound source citations. These notes are not independent references or an adjudicated error matrix. The current membership counts are Coordinate 7, Plan 3, Assess 3, Inspect 2, Reason 2 and Hypothesize 1; other core categories select present zero times. Memberships overlap. All 242 core decisions are available, but no precision/recall or whole-trajectory semantic accuracy has been established.

The packet audit reconstructs all 22 exact requests. Each subject is complete; the long system-policy record is clipped as supporting context in every packet. External customer call/result records are excluded from the model-facing evidence. Thus complete unit coverage is distinct from complete context coverage and from correct interpretation. The unchanged harness still needs independent evidence for the intended-operation and feedback-target boundaries exposed here.

The live unit inspector now shows nearby or all source records, keeping customer events and empty records visible. The selected span is highlighted using Unicode code-point offsets. Following words in the same message and later records are explicitly marked beyond the cutoff; external-result visibility stays unestablished. The inspection view cannot add this retrospective evidence to Jev's packet. Do not use it as a prediction-blind review surface.

The complete reference pack at `after-reference/review.html` is separate from the prediction-exposing `inspection.html`. The before/after packs share the same cases hash; their prediction snapshots differ. Independent references remain empty, and the scorer reports no accuracy. All earlier frozen research remains unchanged; the live history intentionally appends only the 18 new observations. Thirteen activity regression tests and four browser workflows pass, including exact context boundaries, preserved packets and live source inspection. See `research/telecom-full-delivery-2026-10-07.json` for the execution and preservation receipt.
