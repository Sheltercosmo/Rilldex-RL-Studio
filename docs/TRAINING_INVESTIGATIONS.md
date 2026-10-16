# Preserve a training comparison through case review

Implemented 11 October 2026. This completes an initial navigation loop in the [RL engineering framework](RL_ENGINEERING_FRAMEWORK.md): training population → saved comparison → exact rollout evidence → same comparison → hypothesis revision. It reuses the existing training projection, investigation storage and rollout map. It introduces no new inference or metric arithmetic.

## Researcher workflow

In **Overview → Training samples**, select an experiment, a monitor and optionally one recorded producer/filter/definition. Choose **Investigate this comparison**, or select a stage/decision/chart point and choose **Investigate selected cases**.

The resulting entry opens in **Investigations** and retains:

- The complete displayed training population and cohort comparisons, including missing source joins and observations.
- Monitor definition, observer identity, exact monitor value IDs and recorded filter revisions.
- Stage, cohort, recorded coordinate and decision used to select cases; explicit selected sample identities include the experiment and producer.
- Source graph bindings for case inspection without a monitor receipt.
- A researcher hypothesis and subsequent immutable revisions.

**Comparison scope and case selection are different.** Charts retain all cohorts in the saved comparison scope. Selecting a stage, point or decision narrows the case table only. The interface states this boundary. **Restore saved case selection** returns to the original cases. **Open current training data** reopens the experiment/monitor/filter as a live view; it does not rewrite the saved comparison.

Open a case to inspect its pinned monitor receipt, or its saved source graph where no measurement was available. The rollout map links back to the same investigation. An absent source join stays absent in that saved document after later delivery. A source graph unavailable at save time does not silently resolve to a newer graph.

Editing the hypothesis or case selection creates a new saved revision with the original evidence. The prior revision remains accessible. A live-event notification cannot refresh a saved investigation.

**Reward relationships → Investigate behavior** is an additional entry point. It freezes the health snapshot, selected reward definitions and complete-group pattern membership alongside the existing population/source bindings. Revisions preserve this reward context and its original live link. The existing comparison panel accepts those saved patterns as populations; its monitors still bind to exact saved sources. [Reward pattern rules and API](REWARD_RELATIONSHIPS.md#from-reward-patterns-to-behavior).

## API and evidence identity

`GET /api/training-populations` adds a `snapshot_id` binding the full displayed projection. `view_revision` continues to support live refresh and is not used as the save authorization token.

`POST /api/investigations/training` accepts `scope`, `snapshot_id`, `view`, `title`, and `hypothesis`. Scope uses the existing experiment/environment/monitor/selection parameters. View consists of a recorded `stage` and either null selection or `{cohort, step?, decision?}`. The server recomputes the projection and rejects stale displayed evidence, invalid scopes and empty case selections. It constructs selected identities itself; the client cannot submit replacement evidence.

A revision accepts only `parent_id`, `view`, `title` and `hypothesis`. The parent is hash-verified, and no live data is substituted. These documents use `training-investigation/1` inside the existing `failure_investigations` table and share the existing listing, hash-verified read and export routes. Historical failure-investigation documents remain unchanged.

The embedded training projection keeps its original content identity. Additional source graph bindings are stored beside it and covered by the investigation identity. Repeated identical saves return the same identifier. No new model calls or training runs occur.

## Validation and remaining work

**Linked checks implemented 13 October:** both saved rollout investigations and
training comparisons now include **Checks & findings** beside their existing
comparison and notes. A check records its hypothesis, procedure, expected
distinguishing result and optional controls/missing evidence/cost limit. Checks
can examine independent explanations or follow an earlier check. Findings append
an assessment, conclusion, limitations, next action and returned evidence. The
original question, case selection and evidence stay pinned. This closes the
bookkeeping gap between a next-experiment note and a returned result; it does not
automatically diagnose a cause or execute an experiment.

[Retained evidence and reproduction](../research/training-context-2026-10-11/README.md) include six new backend tests, eight browser check groups and a replay of existing native TRL CPU packets. The native example checks response length and filter identity, not semantic accuracy. The code path accepts any existing monitor and normalized training-record producer, but this change establishes no additional native integration support.

An initial [cross-metric comparison](POPULATION_COMPARISONS.md) now operates on one frozen declared-sample cohort, with common measured support and recorded-group contrasts. Arbitrary sample/episode matching, complete lifecycle provenance, unit boundary/activity/content correction inside recovery, independent semantic evaluation and production-scale snapshot querying remain delivery work. Saving currently copies the selected scope's full projection; large-population pagination and compact immutable manifests need measured design before scale claims.

## Follow-up checks and returned evidence

Open a saved comparison, select **Checks & findings**, and choose **Plan a check**.
The check binds the saved case selection; save changed cases first if needed.
Choose **Record finding** when evidence is available, or record an inconclusive
finding with the missing inputs. **Not run** records a decision to skip a check,
with an explanation and no result attachments. **Plan follow-up** retains an
explicit relationship to the earlier check; it does not imply causal dependence.

Supported attachments:

- **Saved comparison:** a hash-verified existing rollout/training investigation,
  including its population and source/measurement bindings. Its scope is visible
  in the inspector. A rescore or later training comparison must first be saved
  through the ordinary comparison workflow.
- **Rollout unit:** an exact graph and annotated-unit identity, with the retained
  unit text and a return link from its map. Source events, plan steps and
  unresolved references cannot be presented as annotated units. Source-only
  evidence remains usable through saved comparisons.
- **Continuation experiment:** an externally recorded study. The server checks
  the displayed snapshot identity, rejects changed evidence until reviewed and
  stores the complete projected result with the finding. Its missing/incompatible
  outcomes remain unknown. This adapter is optional.

Supports/contradicts requires at least one attachment. These labels are the
researcher's assessment, not an independently verified causal claim. Different
tasks, policies, evaluators and case populations can be attached intentionally;
the product does not automatically certify comparability. Controls and
limitations should explain those differences. No experiment or model call runs
from these controls, and opening an investigation does not recalculate semantics.

Previewed evidence links open separately while editing a finding, preserving the
unsaved form. From a saved finding, comparison and unit-map links carry a return
path to the same investigation. Later revisions are discoverable from their
parent; opening an old revision never silently switches to newer evidence.

### Persistence and API

`POST /api/investigations/follow-ups` accepts `{parent_id, action, check}`:

- `action: "plan"`: `check` contains `title`, `hypothesis`, `procedure`,
  `expected_result`; optional `controls` and `follows_check` (an existing check ID).
- `action: "result"`: `check` contains `id`, `assessment` (`supports`,
  `contradicts`, `inconclusive`, `not_run`), `conclusion`, `evidence`; optional
  `limitations` and `next_action`.

The new revision preserves the parent's document and schema, adding a
`follow_up` object with schema `investigation-followups/1`, a root identity and
checks. Check designs stay unchanged; new findings append. Existing note
revisions preserve follow-ups. Repeated identical requests against the same
parent are idempotent. Concurrent children form visible branches; there is no
mutable latest head that can overwrite another researcher's work. There is no
new database or execution engine.

`POST /api/investigations/follow-ups/preview` accepts `{evidence: [...]}` and
resolves references without saving. Clients cannot provide substitute source or
measurement data. Supported references are:

```json
{"kind":"investigation","id":"investigation-…"}
{"kind":"unit","graph_id":"graph-…","unit_id":"…"}
{"kind":"continuation","producer":"…","experiment":"…","study_id":"…","snapshot_id":"continuation-snapshot-…"}
```

`GET /api/investigations/<id>/revisions` lists direct child revisions.
`GET /api/investigations/<id>/bundle` returns the original saved document and exact
directly referenced saved comparisons. Continuation and selected-unit evidence
are embedded in the findings. Nested workflow references, full raw sources and
complete graphs are not recursively bundled; the export states this boundary.
The UI preserves server JSON representation for hash verification. Workflow
exports use `investigation-workflow-export/1`; old comparison-only exports retain
`investigation-export/1`.

Bounds: 32 checks per investigation, 32 findings per check, eight evidence items
per finding and 128 distinct direct comparison references per bundle. These are
bounded local-workspace controls, not demonstrated training-scale performance.

### Verification of this increment

120 focused Python tests pass across follow-ups, investigations, continuation
evidence and readiness/process projections. Twelve follow-up tests cover
immutable parents, branching/idempotency, corrected scores, unknown results,
unit binding, forged evidence and training-note revisions. Real HTTP controls and
desktop/mobile browser walkthroughs cover planning, returned evidence,
inconclusive findings, map/comparison return paths and export. Three authored
workflow paths exercise selection, reward review and recovery; they establish
mechanics, not automatic diagnosis, independent semantic accuracy or causal
training benefit. [Reproduction and screenshots](../research/investigation-followups-2026-10-13/README.md).

### Retrieve behavior cases for a finding

Recurrence cases also offer **Review procedure comparison**. Compare the two
recorded dispatches and their intervening context, then record a relationship,
reviewer and source explanation. Saving creates a separate immutable graph and
provides links to its map and a new comparison. This closes a local evidence gap
before attaching a result; it does not rewrite the original investigation or
claim that a changed procedure caused success. The existing procedure-change
monitor consumes reviewed pairs with unknowns retained separately.
[Review contract and validation](../research/procedure-reviews-2026-10-13/README.md).

The finding editor defaults to **Behavior case**. Choose the current saved
comparison or another saved comparison, then filter returns/repeated work or
comparable recovery checks. Filters cover focus/reference population, recorded
category, recorded versus unestablished feedback reference, and target/criterion
text. Attempt positions distinguish repeated cases with the same target.
Inspect opens connected source cards; Attach retains the entire case rather than
just a selected unit. Exact graph review notes remain visible and are embedded
in the evidence receipt. A missing graph is reported without discarding the
already saved case or claiming there were no review issues.

`GET /api/investigations/<id>/cases` accepts `family` (recurrence/recovery),
`cohort`, `status`, `feedback`, `q`, `limit` and `offset`. It reads supported
frozen projections only: `work-episodes/3` or `recovery-windows/1`. It does not
select newer annotations, remeasure or run inference. Identical duplicate
projections are deduplicated; conflicting versions for one rollout are withheld.
Counts distinguish cases, distinct rollouts, measured coverage, and first or
unresolved actions. The feedback filter describes a recorded relation, not
whether a model comprehended or ignored feedback.

The preview and follow-up result endpoints accept:

```json
{"kind":"behavior_case","investigation_id":"investigation-…","family":"recurrence","case_id":"…"}
```

The server resolves that reference inside the comparison's saved population.
Workflow export includes the original comparison plus the pinned case and review
context. Training comparisons without these saved behavior projections report
them as unavailable; selected-sample counts never masquerade as behavior cases.
The researcher can select a separate saved behavior comparison and document its
scope differences. Current integration is retained-case retrieval; automated
cross-comparison matching and independent causal diagnosis remain open.

[Validation, public cases and reproducible checks](../research/investigation-cases-2026-10-13/README.md).
