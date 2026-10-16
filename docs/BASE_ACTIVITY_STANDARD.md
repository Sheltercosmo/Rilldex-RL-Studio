# Base semantic activities

Version: `behavioral-unit-standard/2`. Implemented in `tracker/base_standard.py`, with unit-first execution in `tracker/base_units.py`. This is the full working base vocabulary, replacing the proposed six-function design, which remains withdrawn. The definitions cover task work, information use, action, choice and interaction. Coverage and boundary accuracy still require evidence across real traces; Other and Unresolved expose gaps rather than forcing all text into a convenient class.

## Unit and classification rule

A unit is one meaningful contribution to the current work or interaction. A coherent contribution may contain a situation, rationale, immediate needed correction, purpose or polite wording. These do not automatically become separate units or co-occurring activities. Conversely, a paragraph is not automatically one unit merely because the source groups it that way.

First decide whether the proposed span is coherent, needs a broader span, needs splitting, is only nonbehavioral source material, or is unresolved. A repair state does not enter category classification or content extraction. The current source sentence/dispatch boundaries are proposals, not validated semantic boundaries. A broader-unit repair cannot be declared complete without identifying that broader span.

For a coherent unit, select **one** base activity in **one** bounded Jev question. These are competing answers to the same question: what contribution does this unit make? Supporting features belong in its content fields. A hierarchy's parent and subtype are one classification, not two counted events.

## Full category contract

| Activity | Required contribution | Excludes / closest boundary | Example |
|---|---|---|---|
| **Orient** | Establish the current task situation, relevant gap/requirement or immediate work needed | Local rationale and next-step wording alone do not become Plan, Reason or Hypothesize | “Since the reproduction code lacks the decorator, we need to add it to the class to replicate the issue.” |
| **State knowledge** | Introduce an existing fact, definition, rule or procedure without deriving it or retrieving it externally in this unit | Restating current task context is Orient; applying a rule to derive task content is Reason; an actual lookup is Inspect | “Newton’s second law is F = ma.” |
| **Plan** | Organize a broader piece of work toward a goal through an approach, substantive stages, subgoals or dependencies | A bare next action or needed local fix is Orient; choosing among approaches without organizing their execution is Decide | “Trace configuration loading, repair propagation, then test encrypted and unencrypted responses.” |
| **Hypothesize** | Introduce a tentative explanation, assumption or candidate solution for an unresolved question | Known setup gaps are Orient; a supported derivation is Reason; selecting a candidate is Decide | “The failure may be caused by stale authentication tokens.” |
| **Reason** | Perform substantive calculation, inference, comparison or derivation of task content | A connective or work rationale alone is insufficient; testing a particular existing claim is Verify; a short reason subordinate to an explicit choice stays within Decide | “17 × 23 = 17 × 20 + 17 × 3 = 391.” |
| **Decide** | Select, commit to or abandon an option among explicit or contextually established alternatives | Listing possibilities is Hypothesize; organizing broader work is Plan; merely announcing a next step is Orient | “Of binary search and a linear scan, I’ll use binary search because the list is sorted.” |
| **Inspect / retrieve** | Actually seek external information through observation, reading, searching or retrieval | Announcing it is Orient; asking another actor is Coordinate; checking an established target is Verify | A dispatched search for files containing `ResultLevelCache` |
| **Construct / modify** | Produce/change a task artifact or attempt a domain-state mutation through the unit itself | Stating a needed edit is Orient; communicating a result is Report; a dispatch alone does not establish its effect | A recorded file creation or edit; producing the substantive content of an artifact |
| **Verify / check** | Attempt to check an established claim, artifact, state or criterion, through tools or substantive textual checking | Announcing a check is Orient; deriving new content without a check target is Reason; reading without that purpose is Inspect | Recompute an earlier total to check it; run a reproduction script against the claimed issue |
| **Coordinate / request** | Seek another actor’s action, information, clarification or delegation/handoff | The requested action is content, not performed work; incidental politeness does not add Social | “Please send your order number so I can find the purchase.” |
| **Report / deliver** | Communicate a result, status, concise answer or finished artifact to a recipient | Internal current-work descriptions are Orient; substantive calculation, artifact creation and refusal retain their own functions even in user-facing text | “The answer to your question is 42.” |
| **Decline / abstain** | Refuse requested work, set a boundary on assistance, or explicitly withhold an answer/commitment | Describing a limitation without withholding the requested contribution is not automatically Decline; uncertainty alone is not abstention | “I cannot provide the requested answer because the evidence does not establish it.” |
| **Social / acknowledge** | Greet, thank, apologize, empathize, encourage or acknowledge as the unit’s contribution | Substantive requests, refusals or task updates with polite wording use their substantive category | “Thank you.” |

**Other** means an observable contribution outside the current vocabulary. **Unresolved** means insufficient evidence or an unsettled boundary between candidate categories. Neither is a substantive category to hide systematic failures in. An Other case should be reviewed for a missing activity; an Unresolved case should be reviewed for its unit boundary, missing context or competing definitions.

## Rules for the difficult pairs

1. **Orient versus Plan:** ask whether the contribution establishes what is currently needed or actually organizes a broader approach. Intent words, sentence length and number of verbs are not the criterion.
2. **Orient versus Hypothesize:** a stated setup gap and a needed correction do not create an explanatory possibility. Hypothesize must contribute a candidate account/solution that is not established.
3. **Orient versus Reason:** describing the current gap and immediate adjustment can be one Orient contribution even with “since” or “therefore.” Reason must contribute substantive derived task content.
4. **State knowledge versus Reason:** stating an existing rule is knowledge; applying it to derive something for this task is reasoning. This distinction does not certify that the rule is true or reveal a private memory process.
5. **Reason / Inspect versus Verify:** when the unit's contribution is checking a specific existing target, classify Verify. Arithmetic or retrieval is its method, not a second activity count.
6. **Hypothesize / Plan versus Decide:** proposing a possibility, organizing work and selecting an option are different contributions. A choice's short rationale remains with that choice; a detailed standalone derivation may warrant another unit.
7. **Orient / Plan versus Construct / Inspect / Verify:** a description, recommendation or announcement is not a performed operation. Use source dispatch/artifact evidence and the actual contribution of the expression.
8. **Coordinate versus the requested operation:** “Please run the test” is a request. The recipient's later test attempt is a separate unit with its own source.
9. **Report versus substantive work:** output channel alone is insufficient. A computation or artifact-producing unit does not become Report simply because a user can read it. Communicating the result is a distinct contribution when the source establishes it.
10. **Social versus substantive communication:** polite wording inside a request/refusal is a feature of that unit. A standalone greeting or acknowledgement is itself an interaction unit.

If two definitions still apply to the same contribution after these rules, do not assign both and claim the problem is solved. Mark the ambiguity, inspect the source boundary/context, and add the case to the contrast set before changing the contract.

## Distinct later layers

- **Content:** each accepted category routes directly to useful natural-language fields. Orient has local focus, situation, needed work and purpose. Plan has organized work scope and expressed approach. Reason has focus and derivation; Hypothesize has phenomenon and candidate account. Action and communication categories have their relevant target/content fields. Social need not invent entity fields.
- **Status and mechanism:** intended/requested/attempted/reported, hypothetical/asserted, tool/action type, source channel and outcome evidence are distinct dimensions. They are not extra base-activity badges. This version does not yet claim a complete separate status extractor.
- **Relationships:** Assess connects established content to evidence/criteria; Revise connects earlier and replacement content. Identity, use of evidence, plan implementation and response to feedback follow the necessary local records. The base classifier does not answer those questions.
- **Macro analysis:** plans, investigations, recurrent work, exploration, approach changes and training shifts require supported structure over units. Category frequency alone does not establish them.

## Jev and measurement contract

Each stage is a bounded choice using raw argmax. Unit validation precedes category selection, which precedes direct content extraction. No confidence cutoff or cross-question probability ranking applies. Saved stages are checked against their exact current source and resumed without repeating completed calls. All choices, missing candidates and source boundaries remain inspectable.

The user explicitly supplies one whole-unit Orient reference. Other contrast expectations are implementation-authored until independently reviewed. The 17-case version-2 development pack includes examples for every base category, real tool dispatches, and the user reference. It is an implementation/definition check, not an accuracy benchmark. The same category must use the same definition across adapters. Unsupported language, modality, source scope or candidate coverage stays visible.

At one common unit layer, category counts are exclusive and use accepted/repair/unobserved denominators. Do not mix them with the former eleven independent membership counts or call an inspector-version difference a training change.
