# Plan attempt path

The Plans & attempts view now answers: **What was tried for this step, what came back, what did the agent make of it, and what work happened between attempts?** It uses the existing graph rather than a separate classification pipeline or a new navigation destination.

The expressed plan remains the overview. Each declared step selects its own path. All linked work shows preparation, attempt and check roles; Compare attempts keeps attempts expanded and presents intervening linked work as compact context. Explicit same-target relationships draw violet return lines. Dashed chronology is visually separate. The evidence drawer opens exact responses, assessments and relationship witnesses in place; source-unit links retain the selected plan step. Source cutoffs remove future evidence. The selected step is addressable with `plan_step`.

`work-hierarchy/3` adds `stage_paths` to the existing read-only hierarchy endpoint. Rows reference original action nodes and saved role/response/assessment links. The projection includes original edge IDs for every displayed relationship, and its export is content-addressed. One dispatch may support multiple stages or roles; each stage counts it once. Stage counts are not additive rollout totals. A response connected by two source representations is shown once with both witnesses. A review that assesses several responses retains those separate bindings.

Return lines require a saved same-target, return-after-error, or completed-call-after-failure relationship between two actions already linked to this stage. Cross-actor, cross-trajectory and non-earlier targets are excluded. These lines do not create transitive identity or a new recovery judgment. Intervening work requires only stage membership and strictly intermediate source records: it is labeled as context, not as a cause. Source-order positions do not establish execution order for parallel actions.

The path counts actions with returned feedback and actions with a saved assessment by the acting agent. These are coverage counts, not assessment correctness or quality. Missing links remain unknown. Agent assessments are claims. A quiet tool response, a final report, or a directory listing does not establish verified objective completion.

Current natural-language content comes from saved semantic annotations, with their existing limitations and review notes. The view does not repair extraction errors, infer missing subplans, classify novel strategy variants, or assign unlinked work to a plan. Native hierarchical capture and task-list history remain supported in the same workspace.

The next substantive map work is broader independently reviewed work identity and branch parentage, followed by comparisons across rollout populations. Do not create personality, exploration-quality or recovery rates from this display's source order.

See [public replay and validation](../research/plan-attempt-path-2026-10-13/README.md).

## Captured input comparison

Work-hierarchy/4 adds an exact pair comparison to each saved return in the selected stage. The return card states whether captured tool/argument fields changed, or whether only recorded action text is comparable. Its evidence drawer shows changed values, bounded string differences, intervening actions and their existing stage assignments. Researchers can inspect an intermediate edit and return to the comparison without losing their selected step.

This is source-field arithmetic, not strategy classification. Equal calls can run against different state. Source-ordered context is not a causal repair claim. Cross-context and sibling dispatches cannot acquire an ordered comparison. No saved graph, monitor value or relationship is rewritten. See [reproducible comparison evidence](../research/attempt-input-comparison-2026-10-13/README.md).

## Retry counts

`work-hierarchy/6` adds `stage_paths[].retry_summary` with unique later-dispatch counts, original witness IDs, previous attempt IDs and an explicit error-return subset. Both endpoints must be attempts in this step; checks and preparation are excluded. The same dispatch is counted once even when several pair witnesses exist. Counts use saved links and remain partial evidence. Reviewed outline cards aggregate these counts only through unique expressed-plan citations and reviewed parentage; ancestors and children overlap. See [definitions and replay](../research/work-canvas-2026-10-13/README.md).
