# Declared work trees

`declared-work-tree/1` is an optional, framework-neutral capture attached to any supported trajectory document as `declared_work_tree` (or `extra.declared_work_tree`). The ordinary import path validates it and materializes it into the same immutable source graph. **Plans & attempts** displays nested goals and control declarations, with source-bound records and a record cutoff.

This is explicit producer evidence. It does not automatically discover subplans in arbitrary prose, assign semantic activity tags, or prove that captured parentage is correct. A producer must supply the actual structure and scope. The adapter-independent contract is reusable; the ReAcTree paper conversion is a bounded research example, not native support for every agent framework.

## Capture contract

Top-level fields are exactly `schema`, `producer`, `nodes`, and `records`. `producer` names the capture implementation/version. IDs are local to this capture. Every citation is `{event_id, start, end, text}`, referencing a non-copied canonical event with matching character offsets and exact text.

Each node has:

- `id`: unique nonempty string.
- `kind`: `goal`, `sequence`, `fallback`, or `parallel`.
- `label`: the exact cited source wording. Control labels equal their kind.
- `parent_id`: another node, or null for a root goal.
- `evidence`: one exact citation to its declaration.

Goals and control nodes alternate. Thus a goal can expand into a sequence, and each step in that sequence can itself expand into a fallback group. Parent declarations must precede children in the same recorded trajectory. Missing parents, cycles, malformed spans and ambiguous IDs are rejected. The producer supplies parentage; matching words alone never links general product data.

Each scoped record has `node_id`, `kind` and `evidence`. Its node must be a declared goal, and its citation cannot precede that declaration or cross trajectories. Supported kinds are `entered`, `operation`, `observation`, `statement`, `reported_complete`, and `reported_failed`. A native operation record is a source-protocol request; it does not manufacture a canonical tool dispatch, semantic attempt relationship, or verified environment effect.

The capture is retained in raw source. `graph_store` adds `declared_work_node` and `declared_work_record` nodes and the typed edges `contains_declared_work`, `scopes_declared_work_record`, and `declared_work_at`. Source and semantic graph versions without this optional capture remain unchanged. Existing semantic Plan steps and native task-list monitors continue to use their own contracts.

## Researcher view

The nested view stays inside the existing Behavior map workspace. The objective opens into a compact set of sibling branches; **Open subgoals** changes focus without losing the breadcrumb path. Failure shortcuts lead to the relevant alternatives and evidence. **Open work history** shows all captured records for one leaf. Cards and the side panel retain exact source/unit drilldown.

Cards distinguish branch state from report counts over descendants. Effort counts use distinct source occurrences of captured `operation` records; multiple scope links do not duplicate a parent total. Bars scale against the largest sibling count. Sibling scopes may share a request, so their counts are not additive. Work directly scoped to the parent is shown separately. No token-cost, causal-efficiency or strategy-quality claim is inferred from these counts.

The record cutoff filters both declarations and records. An unvisited declared alternative is **No recorded visit**, never ignored or abandoned. Reports do not propagate into parent completion. Later work after a completion/failure report is displayed explicitly; contradictory reports at the same source position remain conflicting. `parallel` means a declared control type; it does not establish simultaneous execution.

This release provides a useful representation and source-capture path. Recorded visits and distinct native operation requests can now be tracked across rollouts through the [work-structure measures](WORK_STRUCTURE_MEASURES.md). Free-text parentage, enduring paraphrase identity, hypothesis variants, cross-trajectory delegation and independent semantic validation remain separate work.

## Research basis and verification

[ReAcTree](https://arxiv.org/html/2511.02424v2) separates subgoal agents from sequence/fallback/parallel controls. Its published Listing 7 supplies a concrete nested failure path. [Pinned upstream code](https://github.com/Choi-JaeWoo/ReAcTree/blob/88b737f1eb8f2b68d3b01bdb7ad46e4c00b3ff3b/src/reactree.py) also makes clear that a control named parallel does not by itself establish concurrent execution. These distinctions informed the capture and display boundaries.

[Replay, checks and screenshots](../research/nested-plan-map-2026-10-13/README.md) preserve the public source and implementation limits. No Jev, Luna or other model inference is required for this projection.
