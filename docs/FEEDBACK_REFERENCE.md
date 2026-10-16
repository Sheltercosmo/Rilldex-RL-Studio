# Feedback reference across activities

Implemented 11 October 2026 as a reusable operation within the [RL engineering framework](RL_ENGINEERING_FRAMEWORK.md). This is an initial part of Slice 2. It does not complete a recovery diagnosis or establish general semantic accuracy.

## The engineering problem

The original feedback harness only asked whether an `Orient.situation` described a previous response. That scope misses reports, requests and decisions which also describe results. On retained public airline and retail traces, the original scope submits **zero questions after feedback**. It cannot support a claim that these agents never assess feedback.

The new, optional `agent-contribution-feedback/1` scope inspects an already selected, coherent agent text contribution regardless of its primary activity. It uses the actual contribution and its source citation. A report remains Report; a request remains Coordinate. There is no extra activity label, generated entity or segmentation pass.

The request asks which supplied responses the contribution explicitly describes or interprets. A finite direct response-set question is selected by Jev's raw maximum-probability option. Correctness, causal influence, silent use through action arguments, revision and successful recovery are separate questions. The implementation uses the existing selector, local retrieval, cache, execution budget, observer registry, property graph, typed analysis plan and monitor receipts.

## Scope and evidence contract

| Contract | Current behavior |
|---|---|
| Unit eligibility | Selected agent semantic units from nonempty message/reasoning source spans; excludes user/system/environment contributions, dispatch payloads, copied or hidden context, and undecoded inline media |
| Response eligibility | Prior visible responses bound to selected actions by the adapter, in the same actor, trajectory and recorded context under `feedback-references/2` |
| Retrieval | Three recent responses plus up to two older local FTS matches; the new context protocol filters scope before ranking, including before constructing the FTS corpus; no embedding or candidate model |
| Selection | All nonempty subsets of offered responses, `none_of_these`, `unresolved`; maximum 33 options with five candidates; no confidence cutoff |
| Relationship | Existing `assesses` edge, with `from_field=contribution`, exact source/evidence spans, response-set identity and request hash |
| Coverage | Offered/omitted candidates, incomplete response text/media, incomplete contribution context and unresolved choices remain recorded |
| Compatibility | Old scopes, requests, observer artifacts and graph identities remain unchanged; the new scope has a separate frozen history protocol/path |
| Accuracy | Not independently measured; new public contribution questions are prepared but not yet executed |

The scope requires `assessment-direct-sets/1`. Candidate retrieval is incomplete for distant paraphrases and temporal references. An absent edge alone is never a negative. A selected edge remains the inspector's observation, not an established psychological or causal fact.

## One reusable measurement

`feedback_reference` is available in **Add monitor → Work episodes & source checks → Explicit feedback reference within three text events**, with a semantic observer.

Its denominator starts from native visible action/result bindings, including actions without selected semantic units. Thus an extraction gap cannot make the response disappear from the measurement population. Each unique response is an opportunity; the inspection window is the next **three nonempty agent text events** by the response recipient in the same trajectory and recorded context. Events are used for the window so changing semantic segmentation does not change the horizon.

**Named corrections:** the rollout map's **Review relationships** control can now annotate an exact contribution/response pair as present, absent or unresolved. The opt-in `relationship-review/1` observer protocol preserves original units, sources and earlier receipts. Its present witnesses can resolve a response; absent reviews only resolve negatives when the complete window and every relevant contribution are covered. Named annotations are not independent ground truth. The existing measurement predicate and horizon are unchanged. [Contract, public example and validation](../research/relationship-correction-2026-10-11/README.md).

- **Referenced:** at least one supported, prefix-grounded reference edge occurs within the window. A positive witness does not require waiting for the rest of the window.
- **No reference in the window:** all three events are captured; their non-whitespace text is covered by selected units; every relevant unit has a complete contribution-scope inspection or an explicit absent pair review; and every selection/review rules out a reference to the complete response. Unobserved media and context remain unknown.
- **Unknown:** incomplete windows, source segmentation, inspections, candidates, media or selection evidence. A missing or inconsistent selected edge is also unknown.
- **Not applicable:** no visible bound tool response exists. A pure reasoning trace is not treated as a failed tool-feedback user.

The rate is references / decidable opportunities. Unknowns are retained and counted separately. This is not references / all responses, nor a success or recovery rate. The dashboard prioritizes reference and coverage counts and labels chart tooltips with unknown opportunities. Receipts expose each response, contributing units, edges and unknown reasons. Existing monitor infrastructure supplies rollout trends, investigation comparisons and training-population joins when actual training coordinates/sample facts exist.

Do not compare conditional rates when coverage differs substantially. For example, the retained software observer yields 19 referenced responses and 14 unknowns among 33 responses. Its 19/19 conditional rate does **not** mean the model referenced every response. Airline and retail remain unavailable under their retained observers rather than becoming zero-valued metrics.

## Prepare and budget before executing

**Question setup is now available in Add monitor.** Choose **Inspection feedback** for the existing inspection-anchored relationship query, or **All tool feedback** for the three-text-event opportunity measure. These have different denominators; neither establishes correct feedback use or recovery. Set exact experiment/environment/split values, then **Check evidence** to inspect source and observer coverage before saving. The check is read-only and makes no model calls; it does not certify accuracy. Missing inputs include actionable setup guidance and source/graph links.

The saved population constrains current and future matching rollouts, chart denominators and evidence cases. Split spellings are producer-defined; missing metadata does not match a named value. The [implementation and audit](../research/framework-core-2026-10-11/question-setup/README.md) describe the API, source boundaries and compatibility behavior. CLI preparation below remains the route for new semantic observations.

The CLI performs a free feedback preflight during history preparation:

```powershell
python -m rilldex semantic rebuild-history .tracker/my-contribution-observer `
  --from-directory research/history-reuse-2026-10-11/software `
  --run-id 23a6f4b7c76c919e74ae6d50 `
  --feedback-scope agent-contribution-feedback/1 `
  --feedback-reference-rule assessment-direct-sets/1 `
  --feedback-linkage adapter-feedback-links/1 `
  --feedback-retrieval feedback-context-recent-plus-lexical/1 `
  --prepare-only
```

This preserves the base extraction and returns question counts by activity, exact serialized request bytes, largest request, option count and omitted candidates. It performs no model calls or semantic selections. Byte counts are **not** tokenizer measurements, cost estimates or a whole-history budget: target-identity work is separate, and exact cache hits may reduce actual requests.

With `JEV_API_KEY` configured in the execution environment, resume within a chosen budget:

```powershell
python -m rilldex semantic rebuild-history .tracker/my-contribution-observer `
  --max-new-calls 40 --max-input-bytes 1500000
python -m rilldex semantic rebuild-history .tracker/my-contribution-observer --audit-only
python -m rilldex semantic register .tracker/my-contribution-observer `
  --run-id 23a6f4b7c76c919e74ae6d50 --label "Contribution feedback review"
```

The numbers are example ceilings, not a completion promise. A stop leaves a resumable workspace; incomplete history cannot be registered. Use the existing exact-decision reuse option where appropriate. Ingestion/training does not wait for semantic inspection.

## Context consistency and versioned upgrades · 16 October 2026

New semantic workspaces default to `readable-context/3`; new `feedback-references/2` histories use `feedback-context-recent-plus-lexical/1`. Base extraction prefixes and feedback retrieval exclude other recorded contexts, copied records, unavailable material and unresolved prior order. A unit with unresolved order can still receive local activity inspection, but receives no guessed history. Candidate membership, ranking and request context are scoped before inspection. Missing context IDs share an unspecified scope: source data that omits session boundaries cannot establish isolation.

The map, graph queries, feedback opportunities, timing, follow-through and work paths now apply the same necessary source checks to saved assessment, evidence-use and revision links. Incompatible links remain in the original graph and audit record but cannot become positive evidence in these projections. Invalid source citations, future evidence and unavailable order do not become negative behavior labels. Generic graph queries report recorded matches, not complete behavior incidence.

Existing workspaces, requests, caches and explicit `feedback-references/1` histories remain pinned. Initializing an existing workspace without a context-policy override resumes its saved policy. Do not silently recalculate an old history under new rules. New derived measurements carry new extraction versions; old receipts preserve their saved definition and output. These changes leave Jev's maximum-probability option selection unchanged.

[Consistency controls and installed-package validation](../research/relationship-consistency-2026-10-16/README.md) cover these boundaries. They establish mechanical consistency, not semantic entailment or independently measured retrieval recall. Other relationship families and legacy explicit harness protocols require their own validation.

## Validation and remaining gates

[Public-source audit and browser evidence](../research/feedback-contributions-2026-10-11/README.md) distinguish packet coverage, existing-selection replay and authored mechanics tests. No new Jev or Luna calls were made in this implementation pass; the worker environment has no configured Jev credential. The existing server's in-memory credential was not accessed or moved.

Before enabling this across training rollouts:

1. Independently label held-out contributions and response references in several domains, including none/ambiguous/distant cases. Measure opportunity-level errors and coverage, not only agreement on positive examples.
2. Execute the frozen questions under a bounded budget; compare direct source review and reusable graph-derived measurements on the same opportunities.
3. Reduce repeated context using validated evidence selection and exact caching. The expanded software preflight approximately doubles serialized request bytes; broad inspection is not established as cost-effective at training scale.
4. Validate the new [recovery-window composition](RECOVERY_WINDOWS.md) on real captured workloads. The deterministic operation now retains existing feedback references beside criterion/state changes and comparable checks, but executed controls do not validate semantic references or causal influence. A report of success or a tool error string alone is insufficient.

Native extraction and deterministic JSON/state queries should run broadly. More expensive semantic operations should be explicitly scoped and scheduled asynchronously until their measured accuracy and cost justify larger coverage. Missing sampled observations must retain their missingness, rather than being counted as absence of behavior.

## Timing of saved assessments

Add monitor → Analysis → **First saved assessment after other actions** measures
whether at least one same-recipient dispatch is recorded between a native-bound
text response and its earliest eligible saved `assesses` link. Choose an observer
with source-bound semantic units and feedback links; source-only input exposes
missing observations without inventing negative cases. The legacy native
`assesses_response_group` profile does not provide this unit-level relation.

The rate is conditional on supported links and comparable order. Missing links,
ambiguous origins, context changes and incomplete or boundary-crossing parallel
dispatch groups stay unknown. This does not establish first actual assessment,
ignored feedback, execution latency or causal use. Compare annotation coverage
alongside the value; changing coverage can change the rate.

Inspect rollouts → Open map → Explain value groups all response opportunities
and opens the matching group first. Each case shows the returned excerpt, exact
intervening actions and saved assessment with full-source links. The selected
case survives reload. See the [source replay and validation](../research/feedback-timing-2026-10-13/README.md).
