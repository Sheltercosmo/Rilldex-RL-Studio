# Rollout story: understand a case before opening its trace

Implemented 13 October 2026 in the existing Behavior map workspace. This is a deterministic presentation of saved records and annotations. It adds no model calls, new semantic labels, inferred objectives or diagnostic classifications.

## Researcher questions

The useful starting questions are: what was the task or expressed focus, what did the agent attempt, what came back, what did it do with that information, and what result did it report? An overview must answer these without requiring the reader to decode tool JSON, chase unlabeled arrows, or open a separate source viewer.

The product should have one map workspace with progressive detail. Unit map remains the detailed primary view. Rollout story is the overview. Work path remains an experimental view of saved work grouping; disputed grouping is not used to construct the story.

## What changed

- A compact route strip shows meaningful targets and response previews across the whole recorded rollout. Each card jumps to its readable moment below.
- The overview distinguishes the annotated agent focus, original user request, reported result and recorded evaluation fields. The original request is available in place; a dataset final label is not silently translated into success.
- Moments combine actions with their explicitly linked feedback and explicitly associated agent contributions. Source-parent identity groups calls from one agent message. Grouped dispatches do not imply parallel execution, execution order or strategy branches.
- Each moment displays the action target, available summary, response preview, recorded checks and recognized saved relationships. Links name revisions, assessment, evidence use, returns, plan correspondence or work overlap. Grouped links retain their individual evidence.
- Review points filters to moments with saved changes, checks, feedback-use relations or returned top-level error fields. Counts keep their full-rollout denominator. A zero-match state does not imply absence of errors.
- Full evidence and original response text expand in place. Exact units remain one click away in Unit map.
- Unit map itself now uses the same readable feedback previews in its default Work & results mode. Full source and saved annotations remain unchanged.

## Evidence boundaries

The dotted spine is recording order, not a causal chain. Mere adjacency never creates a retry, assessment or strategy switch. The story uses saved typed relations for those claims and does not merge work targets from the currently disputed work groups.

Response formatting recognizes a nonempty top-level string `error` as a **Returned error field**; it does not label operation failure. Nested error text may be retrieved content. A recognized retrieval result shows its document count and first-document excerpt; complete responses remain attached. Other scalar fields, structured payloads, plain text and empty responses have explicit fallbacks.

Native check results remain scoped to the check. Native task-list states are attributed to agent declarations. A final answer/report is not verified completion. Missing response links and missing feedback-use links remain visible. The screen is explicitly retrospective (Whole rollout), not a causal as-of-time view.

The projection retains every visible Unit-map record, including unpaired feedback and unannotated source records. System/developer context is retained under Coverage; user requests stay in the overview. Empty wrappers are folded only by the pre-existing Unit-map projection rules. Actor and trajectory boundaries prevent cross-participant batching. Independently unvalidated semantic annotations remain unvalidated after rendering.

## Research grounding and differentiation

[TraceView](https://arxiv.org/html/2606.22110) uses iteration and detailed Thought–Action–Result graph views. Its small formative study (five researchers) identifies short meaningful node summaries and understandable relation explanations as useful improvements. We adopt the overview/detail principle and concise context; this study does not establish our UI's effectiveness or extraction accuracy.

[Graph of Trace](https://arxiv.org/html/2606.15116) separates monitoring, graph validation and rendering, and represents scientific work through task/dependency nodes. It explicitly reports missing dependencies and possible monitor interpretation errors. This supports separating a readable view from the process that establishes task identity and parentage. Our current story deliberately reuses saved evidence; the proposed objective hierarchy still needs its own evaluated extraction contract.

[AgentRx](https://arxiv.org/html/2602.02475) distinguishes critical unrecoverable failure from an earlier failure that an agent can recover from. It builds diagnosis on a validation log. That distinction informs our refusal to turn every error response into rollout failure or a subsequent call into recovery. We did not implement AgentRx or its failure taxonomy here.

[Docent](https://docent.transluce.org/signup) already offers behavior rubrics, transcript evidence, and aggregate charts across training steps or models. Graph views and readable summaries are also established prior art. We should not market this presentation as uniquely invented. The intended distinction is the integration of understandable targets, explicit feedback/revision relations, scoped outcomes, exact unit evidence and training measurements in one workflow. The harder objective/plan/alternative hierarchy remains described in `OBJECTIVES_AND_PLANS_MAP.md`, not supplied by this view.

## Validation and limits

Projection tests cover explicit versus absent association, sibling dispatches, actor/trajectory boundaries, ambiguous feedback ownership, nested errors, retrieval previews, assessment links, native checks, dataset labels, missing records and input immutability. Real saved retrieval and math/reference graphs, plus a source-only projection, were checked for complete record accounting. Their semantic annotations were not revalidated or recalculated.

Browser verification covers wide/narrow layout, review-point filtering, jumping to hidden moments, inline evidence, exact-unit drilldown, observer changes and a reasoning-only trace. Artifacts are saved under `research/rollout-story-2026-10-13`.

Remaining gaps: full objective/plan hierarchy; adoption and abandonment evidence; branch lifecycle; scoped hypothesis/variant identity; cost per branch; temporal playback; and matched comparisons of strategy paths across training. These should enrich this workspace after the missing relations have been validated, rather than create more disconnected pages. No assertion is made that a researcher will never need the original trace: the target is to make ordinary case inspection self-contained, while preserving source access for disputed or missing evidence.
