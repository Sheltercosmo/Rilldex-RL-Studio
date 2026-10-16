# Behavior structure: replacing the flat tag set

Status: **the six-function replacement below is withdrawn following the user's subsequent correction on 7 October 2026.** It remains a record of an unsuccessful design hypothesis, not the current standard. The `behavior-moves/0.1` development outputs must not become default annotations or feed extraction/relations. Its default UI integration was removed before server deployment.

## Controlling user correction

- The complete decorator passage discussed below is **one Orient unit**, not five co-occurring activities and not a premise/proposal decomposition into separate base behaviors. This is a user-provided reference, not an assistant interpretation to override with the experimental classifier.
- Assess belongs at the relationship layer. Do not classify assessment relationships before their source units and relevant local contents are established.
- This Orient passage is not Plan. In the follow-up, the user explicitly reiterates that it contains no large plan, hypothesis creation or reasoning. Do not keep asking the user to supply a taxonomy, and do not reinterpret this case using grammatical connective cues.
- Unit boundaries must preserve the meaningful piece of task work. Clauses, verbs and grammatical dependencies are not automatically behavioral units. A unit can contain context, justification and next-step language while remaining Orient.
- Once a unit/category is established, extract its useful natural-language target/content directly, with source evidence. Do not require grammatical subject/object classification, canonical entity identity or cross-unit relationships first.
- For the referenced Orient example, a source-bound extraction candidate is **the reproduction code**, with situation **does not use the `invariant` decorator**. These are assistant-proposed local fields; only the whole-unit Orient classification was supplied by the user. Keep that attribution distinction explicit.

The live SWERL unit visible with the correction reads “Let me start by exploring the codebase to understand its structure.” It currently has no saved base or entity annotation. Do not claim that the five-tag labels came from that selected SWERL unit; they belong to the earlier decorator example.

### Operational distinctions to encode next

Judge the contribution of the complete unit to task work, not every verb or connective in it. These are implementation rules constrained by the user's reference; the reference does not independently validate every possible boundary case.

| Category | Positive requirement | Insufficient trigger |
|---|---|---|
| Orient | Establish the present task situation, relevant gap/requirement and immediate work needed to proceed | A rationale and local needed change do not create extra activity types |
| Plan | Specify an approach that organizes a larger piece of work toward a goal, through substantive stages, dependencies or a strategy | “We need to add X,” “first,” a single next operation or its immediate purpose |
| Hypothesize | Introduce a new tentative explanation or candidate account of something not established | Restating a known gap or identifying a needed correction |
| Reason | Perform substantive inference, calculation or derivation of task content | Using “since,” giving a work rationale, or identifying the immediate consequence of a stated setup gap in an Orient unit |
| Assess | A typed relationship between established content and the evidence/criterion being used to assess it | A standalone tag on an unestablished base unit |

For the decorator reference, retain one unit and one base category: Orient. Its useful local content can describe the reproduction setup, the missing decorator and the needed addition. Those content fields are neither new behavior units nor proof of a plan or assessment relation. A natural-language target must be useful at that scope; a vague label such as “the issue” may be source-exact and still be analytically inadequate.

### Direct extraction check

`orient-unit-content/0.1` asks only for target, situation and needed work on this already user-established whole Orient unit. It requires no prior entity, predicate or relation result. A single Jev call returns “the issue” as target, the missing-decorator clause as situation and the addition-plus-purpose clause as needed work. Exact source selection and raw argmax pass, but target specificity and operation/purpose scope remain deficient against the assistant's proposed useful-field contract. It is not promoted or presented as a solved extraction. The frozen source, user category reference, request and output are in `research/orient-unit-content-2026-10-07`. The sole human reference establishes category and whole-unit scope, not independently scored field boundaries.

## Withdrawn proposal and evidence

## What is wrong with the current design

The eleven independent activity questions mix a local function, an operation, claim status, communication purpose and a relationship to earlier work. They also apply to sentence-sized units that can contain several moves. Their positive answers form a bag of labels, not a decomposition.

In the current software example, six of seventeen annotated model-text units receive at least three tags. In telecom, one of twenty-two does. These are descriptive counts for two development traces, not error rates or general population estimates. A five-tag software sentence contains a premise, proposed work and purpose, but every tag is attached to the whole sentence. The selected opening sentence receives Orient and Plan for a single announced next step.

Independent yes/no questions cannot establish which label is the useful local function. Choosing the greatest probability across those questions would not fix the definitions or segmentation and would violate their separate decision contracts.

## Structure before additional labels

1. Preserve the source message or dispatch as the container, including its source order and cutoff.
2. Propose the smallest useful behavioral moves within it. A move expresses one local function; it can contain an operation plus its object, qualification and purpose. Do not split every verb into a behavior event. Shared words and inherited qualification require explicit scope rather than invented text.
3. Select one local function for each move. If the candidate still contains distinct functions, request a split; if the boundary or function is unsupported, preserve that state rather than forcing a winner among substantive functions.
4. Only then extract fields that its category needs. Operation type, hypothetical status, actor and intended versus attempted work are named dimensions or content fields, not competing badges.
5. Bind local entities and claims to the appropriate move. Connect moves with evidenced relationships. Build larger plan or investigation objects later.

The same source span may provide context to several records. It does not thereby create several independent behavior events.

## Candidate local functions

This small set is a development hypothesis. It needs contrast cases and accuracy evaluation before replacing the live harness. Definitions should change when examples do not support reliable separation.

| Function | What this move does | Boundary |
|---|---|---|
| State or describe | Supplies context, a condition, an observation report or an explanatory claim | A stated observation remains a claim until linked to its source; mere description does not establish inference |
| Derive or interpret | Computes, compares, infers or interprets a conclusion from inputs | Give the conclusion this function and represent its premises as inputs; do not add Report just because it is written in a message |
| Propose work | Announces or recommends an intended operation or desired state | A single next step is not evidence of organized planning or execution |
| Request or coordinate | Seeks another actor's information, action, clarification or handoff | A request may contain a desired operation without performing it |
| Perform an operation | Carries out an observable operation or produces an artifact through the expression/dispatch itself | A dispatch establishes an attempt under its source convention; effect and success require separate evidence |
| Deliver a result | Presents an answer or artifact as a result for a recipient | Requires delivery context; ordinary statements in an internal work discussion are not automatically Deliver |

Other observed function, not applicable, unresolved function and split needed remain explicit choices with distinct meanings. A terminal outcome alone must not convert a historical statement into delivery or execution. If a delivery includes substantial derivation, retain those as separate child moves rather than assigning both labels to the entire passage.

A subtype may refine one function. The parent is derived from that subtype, never judged or counted as another co-occurring function. Do not introduce subtypes until a concrete inspection question requires them.

## Where the old distinctions belong

| Existing label | Proposed representation |
|---|---|
| Orient | Context/task description under State; not an extra tag for mentioning the task in a proposal |
| Inspect or retrieve | Operation content, with its status: intended, requested, attempted, reported, etc. |
| Reason or derive | Derive or interpret function, with input and conclusion fields |
| Hypothesize | Candidate-explanation/solution content and commitment status on the relevant claim; not a second generic activity on every inference |
| Plan or decompose | Propose work for an intention; ordering, dependency and subgoal relationships for organization; larger plan objects after those exist |
| Execute or construct | Perform function with operation content and observable dispatch/artifact evidence |
| Verify | A check operation or explicit checking purpose, plus claim/criterion and attempt status; reading used in a check need not create two behavior events |
| Interpret or assess | A specific Derive or interpret subtype that consumes feedback, with the assessed input separate from the conclusion |
| Revise | A supported relationship between earlier and replacement content; the replacement still has its own local function |
| Coordinate or request | Request or coordinate function |
| Report or deliver | State for an observation/status claim; Deliver for explicit result delivery. Reporting is not automatically an additional function on every statement |

This is not a mechanical migration table. Existing winners alone cannot determine these new values. It requires new source-bound decisions. Entity extraction must follow the selected function and actual operation content, not fan out through every old positive tag.

## Source examples and readable output

These decompositions are implementation-author proposals for development review, not independently validated annotations. Exact source spans and saved old labels are in `research/activity-structure-2026-10-07.json`.

**“First, let's start by reproducing the results of the issue.”**

- One proposed-work move: reproduce the issue's results.
- Intended status; next-step wording. No separately supported Orient event or larger plan organization.

**“The output is `True`, which means the issue is not being reproduced.”**

- State: the output is `True`.
- Interpret: the issue is not being reproduced.
- The first claim is an explicit input to the second. Link the reported output to environment feedback only in the later reference layer.

**“Since the reproduction code does not use the `invariant` decorator, we need to add it to the `ID` class to replicate the issue.”**

- State: the reproduction code lacks the decorator.
- Propose work: add it to the class.
- A justification connects the stated condition to the proposed work; replicate the issue is its expressed purpose.
- Do not add five whole-sentence activity labels. Preserve the local pronoun and resolve it in the dependent entity/reference layer. The purpose clause is not evidence that reproduction occurred.

## Jev decision order

Candidate segmentation and evidence construction occur outside Jev. Offer source-bound alternatives with explicit missing-candidate/split states. Jev chooses the raw argmax within each bounded question. Then ask one local-function question per accepted move, followed by only the relevant category fields. Same-dimension choices compete in one question; separate dimensions have separate questions.

Preserve all source scopes, candidate omissions, raw choices and inspector versions. A validation conflict is visible beside the choice, not a reason to silently choose a runner-up. Grammar/parser proposals can suggest boundaries but cannot alone establish behavior functions. No confidence threshold is introduced.

## Analysis and display

The default unit view should be a sequence/tree of moves: one function label per move, its content beneath it, and relationships between the moves. Status and operation detail belong in named fields. Larger plans/investigations form a later layer with their own membership evidence. Raw legacy labels remain in an inspection panel rather than being repackaged as validated structure.

Count each move once within its function distribution. Parent rollups are sums of their exclusive leaves. Analyze intended retrieval separately from attempted retrieval using status, and keep outcome evidence separate. At message level, report presence without treating several child moves as several messages. Retain unresolved/split-needed units and missing annotation coverage in denominators.

Assess structure through source coverage, usable boundaries, category consistency, field accuracy and relationship accuracy. Once validated, inspect sequences such as reported feedback → interpretation → proposed change → attempted operation. A tag co-occurrence matrix cannot establish that sequence or a causal relationship. Do not compare the new move counts with old sentence/tag counts as a training shift; reprocess a common version first.

## Next bounded implementation

Freeze contrast examples across software, telecom, retrieval and reasoning; propose move boundaries; select one local function; extract the useful category fields; validate before linking. Reuse the current provenance and source-highlight machinery. Do not expand entity or macro passes under the old multi-tag routing while this base representation is being corrected.
