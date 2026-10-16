# Work grouping from saved comparisons

**Build work groups** in the existing behavior map creates an immutable work view from saved target comparisons. It makes no model calls. The button appears when the graph has compatible `contribution-scope-pairs/2` observations and no existing work-membership layer. Earlier graphs, model responses and measurements remain unchanged.

Activity and work target are separate. Reasoning through a question and reporting its answer can concern the same question. Retrieving facts for that question is different immediate work. Retrieving two facts and retrieving only one can overlap without being identical. The source units and their primary activities are not reclassified by this step.

## What the map can establish

The `pair-derived-work/1` profile requires a resolved comparison against **every eligible ordered earlier contribution** before assigning a contribution to an existing or separate work subject. Eligibility follows the same actor, trajectory, context and source-order rules as the pair harness. Parallel dispatch siblings are not ordered predecessors.

Missing comparisons are unknown, not negative. An unresolved pair remains unresolved. If A and B are assigned different work but a later C is judged identical to both, C stays unresolved. Likewise, identity with one member and partial overlap with another member of that group cannot be forced into a transitive merge. No later evidence silently repairs earlier membership.

First comparable contributions can start a subject from their already selected, source-cited immediate target. This does not establish novelty beyond the inspected history. Different subject IDs do not establish globally distinct targets across incomparable parallel branches. Missing local meanings need repair; they are not filled from tool names or string similarity.

Cards keep readable local targets even when membership is unresolved. The coverage panel identifies the missing comparisons. **Related work** displays the original pair relations with source drilldown, independently of whether a complete group can be constructed. Existing recurrence metrics preserve their definition: gaps and unordered dispatches interrupt a fully ordered return. A visible reappearance can therefore coexist with zero fully ordered returns.

The optional `recurrence_order: "bracketed-parallel/1"` policy recognizes a return across a complete observed parallel dispatch group when both recurrence endpoints have established source order and surround the entire group. The sibling calls stay unordered. Missing contributions, incomplete batches, unordered endpoints and groups crossing an endpoint remain unresolved. This establishes recurrence in recorded contributions, not execution or completion causality.

New v4 work maps use this policy. Links to older measurement evidence keep the original policy. **Returns after other work · parallel work included**, **Return share · parallel work included**, the current **Work focus** distribution and **References when returning to work · parallel work included** use the same ordering contract and retain it in their receipts and case links. Return share means returns divided by *decidable* switch opportunities; unknown opportunities remain visible and excluded. Older monitor definitions and explicit legacy links keep their original rule.

The **References on return** monitor shortcut now includes parallel work automatically. Researchers select a relationship and earlier-work scope; an absent saved relationship remains unestablished. This composes work identity and references, without asserting why the agent returned or whether it improved. [Retained-source replay, publication controls and browser validation](../research/parallel-return-references-2026-10-12/README.md).

## Inspect a return in context

In **Behavior map → Work path**, the **Repeated work** list identifies targets with saved recurrence pairs. It shows dispatch/contribution counts, returns versus consecutive repetitions, and the number of exact procedure comparisons available. Select a target to show its first-to-last recorded window, including every intervening visit and gap. **Whole route** restores every card. This is a visual focus, not a new work grouping or metric definition.

Each recurrence pair has a direct evidence button, including repetitions collapsed into one visit. Procedure labels appear only from the same graph and exact pair. Unknown pairs remain explicit; identical command text does not generate a procedure observation. Dispatches include reads and checks, while contribution maps count contributions, not attempts. Disputed work identity withholds the procedure summary.

Use a pair button or **Returns to earlier work** to open **Previous visit → Intervening work → Returned visit**. Open a visit for its contributions, or a source witness for the exact Unit map. **Back to return context** restores the surrounding work after reference inspection. Graph, focused-target and episode links retain the selection on refresh. Connections default to the selected card or pair; **All saved links** remains available.

References to intervening work and earlier visits of the same work remain separate. They may occur later in the visit and do not explain the initial return. Unresolved visits and parallel sibling order stay visible. This presentation uses saved route and relationship evidence without new annotations or metric calculations. [Replay and browser evidence](../research/return-context-2026-10-12/README.md).

**Work-target comparisons** expand separately. They describe related questions or outcomes; they are not evidence that the agent referred to or used earlier work. Unknown custom relationship families are not automatically presented as expressed references.

## API and evidence

- `POST /api/work-grouping` with `{"base_graph_id":"graph-…"}` builds a saved view. Repeating the same request is idempotent.
- `GET /api/work-grouping?graph=graph-…` prepares only missing compatible pair requests. Add `&download=1` to export. This endpoint never sends them to a model or retries an unresolved decision.
- `GET /api/work-scope-audit?graph=graph-…` includes the derivation and checks compatible pair judgments against the current bindings.

`work-subject-bindings/4` retains the exact source and deterministic derivation. Validation reconstructs each original request and raw argmax, checks the units and source, and recomputes the bindings. Named reviews can override a binding while retaining that receipt. Unit changes invalidate the dependent pair/group layer. The existing work-target review form is used; no new review page or confidence threshold is introduced.

The work-navigation operator has an optional, versioned `target_relations: "contribution-scope-pairs/2"` projection. The map enables it for these derived views. It preserves every original relation witness and does not change recurrence counts. Existing requests without the option retain their existing projection behavior.

## Engineering limits

### Optional bounded candidate search

The Unit map's **Find earlier work** control retrieves a shortlist of source-bound earlier contributions. It combines text similarity with recent context, provides exact excerpts and return navigation, and exports prepared comparison requests. This is a candidate-retrieval aid; it does not assign identity or construct complete groups.

`GET /api/work-candidates?graph=graph-…&unit=unit-id&limit=8` prepares comparisons for one current unit. Repeat `unit` for several units, or omit it to prepare the graph. `download=1` returns an attachment. The default is eight candidates, with up to two reserved for recent context; whole-graph preparation has explicit 128-request and 4,000,000-byte caps. Deferred and unreadable pairs are reported separately. Compatible previously observed pairs, including unresolved choices, are reused rather than requested again.

The versioned `prior-work-retrieval/1` receipt retains source/graph identity, cutoff, query terms, index version, candidate methods, coverage and budgets. Future content and parallel dispatch siblings are excluded from the index and its ranking statistics. Unselected pairs are unknown. No model is called and no graph is saved by this endpoint. The existing complete-pair membership policy remains intact.

The three-source development comparison recovered 20 retained links while shortlisting 681 of 2,587 eligible pairs; this is not independent semantic accuracy or a general recall estimate. Local scanning still needs production-scale validation and incremental indexing. See [method, measured request sizes and verification](../research/work-retrieval-2026-10-13/README.md).

This contract is independent of the trainer and source adapter, but native integration coverage is a separate question. The present generic selector requires usable selected units and compatible pair receipts; it is not a claim that arbitrary raw logs can already be grouped automatically with validated accuracy.

Exhaustive eligible-pair coverage grows quadratically. Requests are batched at the existing 16-prior limit; missing-only preparation saves repeat work but does not solve long-trace scaling. Production use needs independent missed-link measurements for the bounded retrieval path, semantic review across domains, and wider native-source validation of parallel-work evidence. Do not promote this small development result into universal exploration, deviation or reward-hacking metrics.

[Public-trace experiment, cost and browser verification](../research/pair-work-grouping-2026-10-12/README.md).

[Parallel-return replay and ordering contract checks](../research/parallel-work-returns-2026-10-12/README.md).
