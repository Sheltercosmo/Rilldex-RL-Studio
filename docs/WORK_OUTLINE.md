# Source-linked work outlines

The Behavior map's existing **Plans & attempts** view now accepts a `work-outline/1` review over any saved source graph. It supplies the missing representation for enduring objectives, subgoals, approaches and hypotheses, alongside the existing unit and native plan observations. The review editor creates readable work items from exact source quotes, connects them and records explicit decisions. This is a retrospective review workflow, not automatic free-prose extraction or an independently validated semantic classifier.

## Meaning

- **Part of** connects a work item to a broader target. Multiple parents are supported; containment is acyclic. A shared child remains one stored object.
- **Alternative to** relates candidate approaches at the same declared scale. Neither alternative is automatically adopted.
- **Depends on** records an explicit prerequisite. Mere chronological order is insufficient; cyclic prerequisites are rejected in this initial contract.
- **Replaces** records an explicit replacement decision. An older approach may replace a newer one at a later point. It does not erase either approach or imply that all its effects were rolled back.
- **Pursue, defer, stop and resume** record attributed decisions for one work item. Silence, a tool error or another branch starting cannot create these states.
- **Reported complete / reported failed** stay scoped to the work item and remain claims. States never propagate from children to parents. Conflicting decisions at the same source position remain conflicting.

Work items are not new semantic units. The original unit boundaries, activities and source events remain unchanged. A single Plan contribution can organize several work items. The outline may reference that Plan and open its existing declared steps and attempt path. It never creates a Plan from a next-action announcement.

## Persistence and evidence

`GET /api/work-outline?graph=<id>` returns the existing review or an empty template. `POST /api/work-outline` validates and saves a new immutable graph version. `GET /api/work-hierarchy` exposes its projection under `work_outline`, in the same workspace used by native plans and task lists.

The document has `schema`, `base_graph_id`, a named `revision` (`author`, `note`), `items`, `links` and `decisions`. Each item has a simple local `id`, `kind`, readable `label` and `evidence`. Each link has `from`, `to`, `type` and `evidence`; each decision has `item_id`, `type` and `evidence`. A citation is `{event_id, start, end, text}` using Unicode codepoint offsets. All quotes are exact and all referenced records are non-copied participant contributions. Connections and decisions must follow the declarations and stay within the same recorded context. User requests can originate objectives/subgoals but cannot be treated as agent approaches or agent decisions.

The graph stores items, decisions, typed connections and exact source edges. Local work identity is stable within an outline's revision lineage. Editing creates a new immutable graph version, while prior source, annotations and measurements remain inspectable. Saving an unchanged review reuses the same graph. Concurrent stale edits are rejected. Stored nodes and edges are checked against the review document before projection.

A record cutoff hides later declarations, connections and decisions. It does **not** establish that the review was produced online or without future knowledge. Natural-language targets and relationships still require semantic assessment; passing source/structure checks does not establish entailment.

## Researcher workflow

Open **Review work outline** in Plans & attempts. Add a target and quote, connect it to a broader item or alternative, and add only explicit decisions with their own quotes. Items and relationships collapse individually while editing. The saved map supports nested navigation, source inspection, decision history and opening existing plan attempts. It keeps this work in one Behavior map rather than creating another disconnected page.

**Full outline** expands nested work together. A shared work item appears once as an expanded card, with explicit references from its other parents. **Focus branch** narrows the map to a chosen branch. The separate **Decisions & reports** section follows source order within that branch, including its descendants; it is not a causal chain. Conflicting statements are retained, and child outcomes never set the parent outcome. View and focus survive a trip into Unit map. Cutoffs apply to both cards and statements. The expanded layout wraps on smaller screens; it does not shrink labels to unreadable text.

**Work timeline** places each work item on a common source-record axis. It starts with items that have annotated decisions and offers an explicit switch to include items without them. It distinguishes first appearance, user request, chosen work, deferral, stopping, resumption, reported completion and reported failure. Markers open exact statements in a compact panel without leaving the map; source details can still open the precise record and its units. Adjacent observations share a numbered marker. When the same exact quote both introduces and chooses work, one marker preserves both meanings instead of displaying duplicate statements. Conflicting decisions remain separate observations.

This is a timeline of recorded expressions, not measured time spent working, hidden planning, training steps or verified outcomes. Empty spans do not establish abandonment, inactivity or missing effort. Shared work gets one row; child statements do not change a parent's state. Existing source cutoffs, outline provenance and view-preserving unit drilldown remain in force. See [implementation and checks](../research/work-timeline-2026-10-13/README.md).

The first retained software example contains ten reviewed work items, nine parent links and one scoped completion claim. It is a development review of public source, not a gold benchmark. [Replay and validation](../research/work-outline-2026-10-13/README.md).

A [later manual revision](../research/work-outline-overview-2026-10-13/README.md) preserves the synthetic-data test and the RMSE plot separately from the requested GDSC evaluation and feature-response visualization. It contains twelve work items, eleven links and six decisions/reports. It does not establish overall completion or replace the original review.

## Next work

Local purpose must remain separate from hierarchy. The experimental `work-purpose-roles/1` protocol records whole-work versus component purpose attachment over existing source-bound fields; it creates no outline parent or work-identity link. Its real-source test still has ambiguous compound descriptions and was not installed. [Design evidence, actual results and cost](../research/work-purpose-roles-2026-10-13/README.md). The next missing content representation is separately addressable work mentions inside an unchanged base contribution, with purpose/sequence/conditions bound to the relevant mention before cross-unit identity and parentage.

`tracker.work_outline_candidates` now supplies a bounded automatic-proposal contract and raw-argmax Jev selection for the same work representation. `request(graph, through)` freezes a source prefix of attributable participant expressions, its omissions and its exact graph identity. It does not send inherited activity labels or the previous reviewed outline as evidence. A supplied generator returns one to three whole-outline candidates with exact source quotes; `bind` validates their references, scope, structure and attribution before selection. Whole-bundle rejection and unresolved selection remain possible. No confidence threshold or automatic repair changes the selected option.

`fork_selected` and `save_selected` retain the complete proposal, source request and raw decision so the selected graph can be replayed. A model-selected outline is visibly distinct from a named review. Opening its review editor starts a separate reviewer attribution; a later human review does not retain the model's selection receipt as if it covered the edits. Repeated saving of the same selection reuses graph identity. Source records and base units remain unchanged.

Prepare a file-based proposal request without model calls:

```powershell
python -m tracker.work_outline_candidates <saved-graph.json> <new-output-directory>
```

An optional `--through <event-id>` bounds the input prefix. The output includes the source packet and a mechanical saved-plan reuse baseline. The baseline is a comparison aid, not an accepted outline: inherited Plan labels can be wrong and broader work can be missing. General candidate generation still requires a supplied JSON generator; it is not silently enabled by importing a rollout. The first development trial is recorded under `research/outline-proposer-2026-10-13`.

Independent evaluation of parentage, alternative identity, decision scope, extraction coverage and correction effort remains required. This prefix contract is retrospective; it does not establish online availability at earlier records or stable work identity across independently generated prefixes. Do not yet derive abandonment, plan adherence or recovery rates from these sparse development observations. Aggregate measures need explicit eligibility and coverage contracts as well as independently reviewed examples.

The [first actual proposal trial](../research/outline-proposer-2026-10-13/README.md) did not produce an accepted automatic outline. A mechanical saved-plan baseline was incomplete; the first Luna proposal failed exact-quote binding; its feedback-assisted repair passed binding but Jev chose `no_suitable_candidate` by raw argmax. No selected graph was installed. This negative result is retained, including the raw selection and its cost, instead of presenting the separate manual review as automatic extraction.

A [local work/purpose trial](../research/work-scope-frames-2026-10-13/README.md) then reused eight existing selected field pairs without a generator. It disagreed with three of seven prewritten development expectations, including checking converter availability versus converting a report. One case was intentionally unadjudicated. This experimental layer was not installed in the application. Reusing good candidate text is insufficient unless the scope distinction and selector are independently validated.

The design draws on [ReAcTree's distinction between goals and controls](https://arxiv.org/html/2511.02424v2) and [AgentTrails' separation of exact provenance from inferred relationships](https://arxiv.org/html/2607.18816). It does not claim to replicate their evaluation results or establish competitive uniqueness.

## Local contents inside a contribution

`tracker.work_mentions` adds local work/state descriptions within unchanged base units. Purpose, order, condition and response-to attach to those descriptions; none establishes cross-unit identity or parentage. The read-only `/api/work-mentions` projection audits the saved request, raw-argmax selection, source quotes, local nodes and links. A named source review can withhold a reading without rewriting the model's choice; rejection cannot be overridden into acceptance. Counts distinguish model-selected from published readings.

The Unit map and Plans & attempts inspectors display this layer in place. It creates no additional activity cards and preserves the original unit count. Unsupported readings, unobserved contributions and selected-empty content remain distinguishable. Existing base fields are available under Activity details.

The outline now starts with its objective and direct branches, with Expand all branches and Collapse nested work controls. Focusing a branch opens that branch's children. The timeline has separate expansion state so a compact overview does not remove decision history from the temporal view. The layout responds to available width rather than imposing a fixed three-column grid.

The [first local-content experiment](../research/work-mentions-2026-10-13/README.md) demonstrates why model selection alone is insufficient: all eight proposed readings were selected, including a purpose edge pointing to the negation of the intended condition. Four readings were withheld in Assistant development source review. Only four reviewed contributions, ten local descriptions and three links were published as a separate preview observation. This is not independent semantic accuracy or general automatic extraction; the original reviewed hierarchy remains unchanged. The next experiment should separate content completeness and relation support rather than approve a whole bundle with one choice.

The [component-check experiment](../research/work-mention-checks-2026-10-13/README.md)
implemented that separation, but did not establish an improvement. Optional
`work-mention-checks/1` receipts preserve description fidelity, relationship and
completeness choices separately, with source review taking precedence. The
inspector exposes these receipts as experimental. Three bounded calls still
misclassified important contents; no experimental graph was promoted to the live
observations. Omitted intended states and order need better candidate
construction and independent evaluation before identity or hierarchy inference.

### Constructing the candidate before selection

`tracker.work_mention_proposals` prepares one source-only generation request per
fixed contribution. The proposer inventories operations, circumstances, intended
effects, conditions, ordering and method descriptions, then maps those excerpts
to local work descriptions and links. These inventory roles are construction
aids, not new activity tags or accepted graph nodes. Unmapped contents require an
explicit note; a fully mapped inventory is not proof of semantic completeness.

The contract specifically separates a current adverse state from the intended
state sought by an operation. A check includes the proposition it checks without
asserting that proposition. Method restatements need not duplicate work items.
The same unchanged local-work selector receives the assembled candidate; no
threshold, automatic acceptance, provider call or graph publication is added.

Prepare from a saved `local-work-mentions/1` packet, provide one JSON response for
each hash-named request, then assemble the existing finite-option selector input:

```powershell
python -m tracker.work_mention_proposals prepare packet.json new-proposals
python -m tracker.work_mention_proposals assemble new-proposals --producer "Named generator and revision"
```

Preparation refuses an existing directory. Assembly validates exact quotes,
mapping IDs and the frozen requests; changed outputs cannot overwrite an earlier
assembly. This makes a changed construction experiment reproducible without
recalculating unchanged observations. It does not establish that a general
automatic proposer is reliable.
