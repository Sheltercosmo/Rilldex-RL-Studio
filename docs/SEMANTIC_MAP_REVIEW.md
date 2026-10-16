# Semantic maps: repair the output contract

7 October 2026. **Subsequent implementation:** the [executable extraction workflow](SEMANTIC_EXTRACTION_WORKFLOW.md) now selects concrete partitions, activities and readable content bundles through Jev on the complete telecom record. A resumable candidate queue works; unattended generative service integration and relation automation remain unfinished. The authored reference maps below remain separate.

This review supersedes the predicate/mention-first priorities in historical delivery notes. The product goal remains incomplete.

## Finding from reading the actual results

The current extraction is not a useful foundation for the requested analysis. It preserves source pointers, dispatch identities and some useful literal references, but often loses the work being done. Better prompts for selecting the same inadequate word fragments will not fix that.

| Current failure | Why it breaks inspection | Required output |
|---|---|---|
| Split one reproduction setup into three sentence units | Turns one contribution into several tag events | Keep the setup, artifact and immediate purpose together |
| Decorator passage gets Orient + Reason + Hypothesize + Plan + Assess | Confuses content inside a contribution with separate contributions | One Orient unit; natural-language situation, needed work and purpose; a later assessment link where supported |
| Target becomes “the issue”, a pronoun, or the entire paragraph | A reviewer cannot identify the intended work; an algorithm cannot compare target changes | Readable local target such as “Make the reproduction exercise the class invariant” |
| Plan target is the whole plan, with no organized stages | Cannot ask which step was attempted or changed | Goal, ordered/conditional stages and explicit dependencies, only when an actual broader Plan exists |
| Every semantic value must be an exact substring | Loses resolved references and complete meaning | Natural-language content **plus separate exact supporting spans** |
| Repeated `python reproduce.py` commands look identical | Misses that the script changed between checks | Link each check to the relevant earlier edit and its returned state |
| A Melbourne → Adelaide revision appears as disconnected sentence tags | Cannot distinguish answer revision from changing the task objective | Preserve both answer claims; link the new choice to the old answer and the assessed mismatch |

These findings come from complete source inspection of the two local records, not a statistical accuracy estimate. The replacement examples are authored by the implementation assistant and need independent review. They are not Jev outputs.

## Practices inspected in open projects

**Docent:** the current [Readings interface](https://github.com/TransluceAI/codex-plugins/blob/main/plugins/docent/skills/docent/readings-reference.md) supports structured outputs, citations in explanatory strings, transcript slices with original positions, content-based caching and dependent analysis stages. Those are directly useful patterns: meaning should be readable and source-linked, and one analysis can consume another. Its public [citation data model](https://github.com/TransluceAI/docent/blob/8ab199c332180100f3882fc3e7323bd22ad50434/docent/docent/data_models/citation.py) also separates output citation ranges from referenced transcript locations. File names alone are misleading: in the inspected public revision, `agent_actions.py` is empty and `intended_solution.py` is commented out. They do not demonstrate an implemented plan extractor. The public repository and current hosted documentation are not assumed to expose identical functionality.

**Inspect Scout:** [structured scanners and timeline scanning](https://meridianlabs-ai.github.io/inspect_scout/llm_scanner.html) already support schema-defined results, lists of findings, explanations and message references. Its timeline preserves execution structure and can scan individual spans. Context-window segmentation solves input size; it is not a definition of a semantic unit. We should borrow source attribution and structured output, not equate execution spans or context chunks with units of meaning. Scout can be programmed to extract this proposed schema; a fixed semantic schema alone is not a defensible distinction.

**ReasoningFlow:** its [node schema](https://github.com/jinulee-v/reasoningflow/blob/master/schema/node_labels.yaml), [edge schema](https://github.com/jinulee-v/reasoningflow/blob/master/schema/edge_labels.yaml) and real human annotations show source spans and typed discourse relationships represented separately. The local snapshot includes actual annotated chemistry, math and physics traces. Its labels and segmentation differ from our contract: for example, a local recall announcement is Planning there, and reflection is a node label. These are useful structural precedents, not product gold labels. Copying them would reproduce the user's rejected Plan boundary.

Source revisions/files read are recorded in `research/semantic-map-review-2026-10-07/sources.json`; the earlier ReasoningFlow snapshot remains in `research/reasoningflow-reference-2026-10-06`.

## The extraction we actually need

1. **Meaningful unit.** Determine exact start/end boundaries from the contribution to the work, considering surrounding context. Offer whole partitions, including merged alternatives. A “needs merge/split” response is unfinished work until repaired spans are produced. Sentence punctuation and grammatical heads are candidate hints only. A rationale, local adjustment and purpose can belong together. Split when the contribution changes, not when another verb appears.
2. **One activity at this scale.** Apply the current base definitions. Keep supporting content inside the unit. One Orient record may explain a local gap, state needed work and reference an earlier result. It does not acquire three extra base activities. Source feedback is not an agent activity.
3. **Readable local content.** Extract what the unit means, what work/claim/artifact it concerns, and the fields warranted by its activity. Resolve local pronouns from the available prefix when justified. Each value has exact evidence and retains modality, negation and attribution. An asserted false claim is still an observed claim; do not silently repair it.
4. **Separate action map.** Keep the real tool, arguments, dispatch, returned observation and source call identity. Associate the action with stated work when supported. Artifact content changes matter even when command strings do not. An action attempt is not an observed effect or verified completion.
5. **Reference bindings and relations.** Bind repeated work targets only after local descriptions exist. Relate newer content to particular earlier content: realizes, assesses, checks, revises, shifts focus, motivated by, supported by, delivers. Normal progression to a new local target does not automatically revise the earlier work. Support names the specific established content and retains unestablished claims; partial support is not whole-answer verification. A revision names what changed: answer, claim, method, local work target or root objective. Keep observed source links distinct from semantic interpretations. Mere adjacency, same nouns or evidence availability do not establish causation or plan following.
6. **Views and analysis.** Semantic, action and relation views are projections of the same records. Aggregate over meaningful work targets and explicit changes, with detail on demand. Macro diagnoses come after this layer can answer concrete trace questions reliably.

The activity vocabulary stays in [BASE_ACTIVITY_STANDARD.md](BASE_ACTIVITY_STANDARD.md). This repair is primarily about units and semantic content, not adding another taxonomy.

| Selected activity | Local content to extract when expressed |
|---|---|
| Orient | Current situation/gap, local focus, needed work, purpose |
| Plan | Goal, organizing approach, stages/subgoals, dependencies/conditions; retain source order and scope |
| Hypothesize | Unresolved phenomenon, candidate explanation, assumptions/conditions, tentative status |
| Reason | Question being derived, inputs, substantive derivation, conclusion |
| Decide | Options considered, selected/rejected option, stated basis |
| Inspect | Information sought, query/read operation, source/object being examined |
| Construct | Artifact/state target, attempted change or produced content |
| Verify | Specific claim/artifact/state checked, check procedure, criterion; result comes from later evidence |
| Coordinate | Requested information/work, recipient if known, conditions |
| Report | Delivered answer/result, its scope and qualifications |
| State knowledge / Decline / Social | Fact and subject / withheld work and reason / interaction content; no invented task entity |

No field is filled merely because its slot exists. Missing, not expressed and ambiguous differ. These are category-conditioned contents, not simultaneous activity tags.

## Jev's actual role

Jev cannot create a natural-language target that is absent from its supplied choices. The old extractor made this a word-span selection problem and then treated a winning substring as a sufficient semantic object. That was the wrong constraint.

A candidate provider outside Jev must propose meaningful partitions and coherent natural-language contents, with evidence anchors. It may use a generative LLM, reusable adapter knowledge, or a reviewer. Jev selects among the supplied alternatives using raw argmax. No confidence or winner-margin threshold is introduced. “No suitable candidate” is a real option and identifies a candidate-construction defect; it must not manufacture a confident-looking target. Relation selection comes only after the necessary local records are established.

`tracker/semantic_map.py` now supplies a source-bound map validator and a Jev request builder for these natural-language content alternatives. It restricts evidence to the unit's cutoff. The current map examples were authored directly; a general generative candidate provider, repaired partition pipeline and automatic relation extractor are **not yet implemented**. The request builder alone is not that pipeline.

## Concrete output and utility check

Two complete recorded traces are available in the local app at `/semantic-map`, with downloadable JSON, source drill-down and three views. Every recorded agent prose span and dispatch is accounted for; command text embedded in a parent message is represented once by its action event. Structural validation checks evidence, coverage, cutoffs and links. It cannot establish semantic correctness.

- **Software:** 15 agent units, 5 feedback units, 6 dispatches. Follow initial reproduction → True/not reproduced → missing decorator → corrected reproduction → False/reproduced → attempted local equality edit. The final edit has no returned result or rerun. The map identifies the reproduction file as the edit target; it does not claim a library fix.
- **Search:** 7 agent units, 3 feedback units, 3 dispatches. Follow broad search → Melbourne-focused searches → Melbourne answer → acknowledged mismatch → Adelaide choice → final answer. The root question stays unchanged. The map preserves the difference between a retrieved “opened by” statement and the response's “founded by” claim, and exposes the unverified city-year condition.
- **Plan:** neither trace needs a broader Plan under the user's definition. This is useful negative coverage, not validation of positive plan extraction. A real organized-plan trace with referenced stages remains necessary.

The acceptance question is not “did JSON validate?” It is whether an unfamiliar reviewer can recover the current work, its intended outcome, what was done, what feedback was received, what was reviewed and what changed—and follow each assertion back to evidence.

## Near work and positioning

First finish the generative candidate provider and actual merge/split execution, then test it on unseen full traces including a real organized plan and a non-programming workflow. Review unit boundaries, target specificity, meaning fidelity, claim attribution and typed links separately, and measure whether errors change answers to the trace questions above. Keep authored references distinct from independent labels. Use the two maps as an output contract, not a held-out accuracy score.

The proposed product is a reusable, evidence-linked representation of how work develops during RL, with training comparisons built on stable versions of that representation. It is not differentiated merely by tags, a graph, summaries or an LLM judge: Docent and Scout already supply much of that general analysis infrastructure. The intended distinction has to be demonstrated through faithful target/plan/artifact histories, fewer repeated custom extraction jobs, useful checkpoint comparisons and lower researcher correction effort. None of those advantages is proven yet.
