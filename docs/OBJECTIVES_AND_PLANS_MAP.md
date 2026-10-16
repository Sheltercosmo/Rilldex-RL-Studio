# Objectives & plans: proposed higher-level behavior map

Direction updated 13 October 2026 from the user's objective/plan/branch example.

**Additional native hierarchy:** explicit goal/control captures now support nested branches, sibling operation counts, scoped reports, full branch history and exact source drilldown. This does not extract hierarchy automatically from arbitrary prose. [Contract](DECLARED_WORK_TREE.md) · [Public replay](../research/nested-plan-map-2026-10-13/README.md).

**Semantic hierarchy status:** first supported hierarchy implemented as **Plans & attempts**, alongside the primary Unit map and Rollout story. It renders saved Plan → step → preparation/attempt/check links, bound feedback and saved connections; structured task lists retain item identity and reported state history. A record cutoff filters available evidence, and every branch opens its supporting units. It does not yet extract general nested objectives, subplans, hypothesis variants, adoption or abandonment. [Implementation evidence](../research/work-hierarchy-2026-10-13/README.md).

## What exists

| View or evidence | Current capability | Missing for this request |
| --- | --- | --- |
| Unit map | Source-bound contributions, actions, feedback and typed connections; exact source inspection | A compact hierarchy of enduring objectives and alternative approaches |
| Work path, formerly Work overview | Groups supported same-work contributions into visits; shows returns, corrections, saved scope and plan-step links | It remains a route through observed work, not a nested objective/strategy tree |
| Plan evidence | Some selected Plan units contain organized steps; some actions link to attempts, preparation or checking of those steps | General nested plan identity, adoption, revisions and alternative branches |
| Native task lists | Supported structured task-list declarations retain items and declared states | General prose plans; accepted tool state; verified completion |
| Outcome evidence | Scoped operation outcomes and some source-backed failed-attempt/return relationships | Reliable branch-level lifecycle or objective achievement |

Implementation references: `work_navigation.py`, `work_route_context.py`, `declared_plans.py`, `plan_relations.py`, and the current `rollout-map` UI. Available evidence varies by saved observer; code support does not imply every rollout has these observations.

## Intended experience

Keep one **Behavior map** workspace. Its detailed Unit map is a primary feature. The implemented **Plans & attempts** view is the first subset of the proposed **Objectives & plans** hierarchy. Work-path navigation remains a supporting view of the same graph.

The new view should look like a mind map: objectives at the left, plans and work branches expanding to the right, then subplans, hypotheses, variants and attempts. Start collapsed to meaningful branches. Show a compact state, recent evidence and unit count on each node. Selecting a node opens its relevant units in the existing map and inspector, preserving the path back.

Containment lines organize the mind map. Separate, labeled cross-links show dependencies, shared prerequisites, alternative approaches, revisions, returns and branch rejoining. A shared check must not be duplicated into invented independent work. The stored model is a graph; the tree is one readable projection.

Provide two time controls: **As of this step** for what had been observed at that cutoff, and **Full rollout** for the recorded history. Retain superseded plans and abandoned alternatives as collapsed branches. Highlight the observed active frontier only when evidence establishes it; rollout termination alone does not close every item.

The user's example is the intended structure, not a classification rule that every trace must fit:

```text
Objective A
└─ Plan: steps 1, 2, 3
   ├─ Branch 1 → subplan → branches 1.1, 1.2
   ├─ Branch 2 → subplan → branch 2.1
   └─ Branch 3 → subplan
      ├─ 3.1 → hypothesis → variant 1 → failed attempt
      │                      └─ revision / retry → variant 2 → active attempt
      ├─ 3.2 → waiting on a recorded dependency
      └─ 3.3 → not yet attempted in the observed trace
```

## Representation and boundaries

Every enduring work item needs its own ID, readable natural-language target, actor, source evidence and observed lifetime. Units are contributions to these items; they are not automatically new work items. Changing a sentence or making another tool call does not create a branch.

| Object or connection | Requirement |
| --- | --- |
| Objective | Recorded requested or adopted outcome, with origin and adoption distinguished |
| Plan and plan step | Expressed organization toward an objective; bare next-action orientation stays a unit |
| Subplan | Organization scoped to an existing work item, with an evidenced parent relationship |
| Alternative / variant | A distinct proposed approach to the same evidenced target, not merely different wording or an arbitrary next action |
| Hypothesis | An expressed tentative proposition with evidence links; an attempt may test it without establishing its truth |
| Attempt | A recorded execution episode bound to the relevant item or variant; retry links refer to an earlier attempt |
| Depends on | A stated or established prerequisite; temporal adjacency is insufficient |
| Revises / replaces / returns to | Explicitly bound earlier items and source-time evidence, retaining the earlier version |

Avoid a single ambiguous status. Keep **agent-declared work state** and **observed attempt/result state** separately, then display the most useful supported badge with its evidence source:

- Planned: expressed intended work; adoption may still be unknown.
- In progress: explicitly active declaration or a captured open attempt with known lifecycle.
- Waiting: a recorded dependency or blocking condition. No later action alone is insufficient.
- Not pursued: an expressed decision not to continue. An unattempted plan item remains **No observed attempt**, not "ignored".
- Failed attempt: outcome of a particular attempted operation or criterion, not automatic objective failure.
- Reported complete: an agent or task-list claim.
- Verified complete: evidence meets the declared acceptance criterion at the relevant scope.
- Unknown: missing or conflicting evidence. It remains visible and distinct from pending work.

A failed test does not automatically refute the hypothesis; a successful tool call does not complete the branch. The user should be able to inspect exactly which relationship connects either conclusion.

## Build order

1. Inventory and reuse existing unit contents, Plan steps, native task lists, work identities and outcome evidence. Measure what is already representable on complete real traces. Do not regenerate unchanged observations.
2. Define the small missing contracts: hierarchical parentage, alternative approach identity, plan adoption/revision, attempt-to-branch binding and lifecycle observations. Keep proposals and Jev selections auditable; use raw argmax over supplied options without confidence gates.
3. Produce one complete, reviewed rollout graph before aggregate metrics. Show unattached contributions in an explicit unplaced group, rather than guessing a parent to make the drawing tidy.
4. Render the collapsible mind map and cross-links over that graph, with source/unit drilldown and a time cutoff. Preserve the existing Unit map and saved receipts.
5. Evaluate parentage, identity, state scope and temporal leakage on fresh traces in several domains. Only then derive branch abandonment, recovery, plan-step progression or strategy-switch measurements across training.

First acceptance cases should include planned work followed in order, an unplanned but useful prerequisite, an explicit abandoned alternative, a failed attempt followed by a different variant, two branches sharing a check, and incomplete capture that must remain unknown. These are evaluation requirements, not claims of current support.

The main product question for this view is: **What was the agent trying to accomplish, which approaches did it pursue, and how did those approaches evolve?** The Unit map provides the evidence that makes this answer inspectable.

## Implemented projection updates

Native nested goals and control flow are now supported through the strict [declared work tree capture](DECLARED_WORK_TREE.md). For saved semantic plans, the [attempt path](PLAN_ATTEMPT_PATH.md) places dispatched work, returned feedback and linked assessments together, with explicit recurrence lines and compact intervening work. These are complementary projections in Plans & attempts, not separate graph stores. Free-prose hierarchical parentage and general strategy-variant inference remain unfinished.

Saved return pairs also expose captured input differences and intervening work in the same inspector. This lets a researcher distinguish a changed command from the same command after an edit without reading the full trace. Field differences do not create variant identities or infer why an outcome changed; those remain separate evidence requirements.

The [reviewed work outline](WORK_OUTLINE.md) now represents nested objectives/subgoals, alternative approaches, prerequisites, replacements and explicit scoped decisions over any saved graph. It adds a source-backed editing surface inside Plans & attempts, stable work identity across immutable revisions and links into existing Plan attempts. This is a retrospective review path; general automatic extraction and independently validated branch lifecycle remain unfinished.

The reviewed outline now uses a bounded, two-sided mind-map canvas with branch folding, scope up/down, pan/zoom, fit, a minimap and evidence pop-ups. Explicit stop/defer cards are gray; missing decisions remain distinct. Linked-plan retry badges count unique later attempt dispatches, separating repeated attempts from explicit returns after an error report. Parent counts deduplicate dispatches and disclose their nested scope. See [canvas and retry evidence](../research/work-canvas-2026-10-13/README.md) for definitions, public-source checks and limits.
