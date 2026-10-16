# Correcting units within an investigation

Implemented 11 October 2026. A researcher can correct a contribution's boundary, primary activity and readable content in the existing rollout map, inspect the dependency impact, then continue the same graph or analysis measure on a reviewed observer. This is correction machinery; named annotations are not independent semantic gold or Jev selections.

## Workflow

1. Open a contribution from a rollout or saved measurement. **Review source units behind this measurement** opens its original observation input. In a recovery receipt, this is the semantic input graph, not the derived graph containing state and recovery witnesses. The original receipt and investigation link remain available.
2. Open **Review unit boundary, activity and content**. Review the complete eligible source window. Split at a cursor/selection or merge adjacent contributions. A boundary change clears the affected classification/content so they must be reviewed again.
3. Choose one primary activity. Describe its summary and immediate work target, plus the category-specific fields that are expressed. Local next-step announcements normally belong to Orient. Assess and Revise remain relationships. Plan content has explicit intended stages, readable stage targets, optional organization links and a completion criterion; these are not executed steps.
4. Supply an annotator and rationale. Preview the replaced units, removed connections, work bindings and relationship reviews that need rechecking. Save an immutable graph revision.
5. Review work membership and relationships against the new contributions. The work-target editor prefills the unit's readable target; correspondence to earlier work still requires a separate binding.
6. From a measurement-led correction, **Monitor this reviewed observer** creates the same graph/analysis definition and population with the reviewed observer. The original monitor stays enabled and its values stay fixed. Later corrections on the same reviewed observer materialize through the existing background service. The resulting link opens that monitor in the overview; **Show all monitors** restores the full view.

Saved population comparisons do not silently change. Add the reviewed monitor through the existing comparison workflow when a new comparison is wanted. A change to the feedback-reference evidence does not necessarily change recorded criterion recovery; the outcome and its semantic explanation remain separately inspectable.

## Source and content contract

The preview also reports changes in activity counts, boundaries, recorded
activity transitions and relationship groups. Code users can compare the same
immutable versions and rerun explicit graph measures through
`Workspace.annotation_changes(...)`. [Usage and limits](ANNOTATION_CHANGES.md).

`tracker/unit_reviews.py` uses `semantic_extraction.windows`, `partition`, the current base activity definitions, `generation_request`, `validate_proposals` and the Plan contract. Every non-whitespace character in one eligible window must be covered exactly once. Overlap, dropped content and empty units are rejected. Native action dispatches remain indivisible. Windows do not bridge excluded action payloads. Browser selection offsets are converted from UTF-16 to source Unicode codepoints.

The editor supports agent semantic/action units and eligible agent source events that have no annotation yet. Incomplete or overlapping legacy segmentation opens as one unresolved whole-window proposal, with an explicit warning; it is not presented as a validated unit. Units spanning excluded source regions require source-binding repair first. Reviews of derived state/request graphs are rejected; use the original observation graph. This release does not edit user, feedback or private evaluator units.

New content requires exact source support in the visible prefix, within the same recorded context and trajectory. Future, private, copied-context and mismatched source evidence is rejected. The browser preserves citations on existing fields and anchors newly entered fields to the unit being reviewed. Earlier-prefix citations can be supplied through the API. Structural citation validation does not prove that the wording is entailed by the source.

Other and Unresolved carry no asserted category-specific content and retain a needs-review status. A selected named review carries its own provenance; it does not fabricate a raw-argmax request or confidence value. Unchanged units retain their original identities and properties, including legacy content representations. A changed unit receives a new content/provenance-bound identity.

## Invalidation and composition

The source graph is never overwritten. Edges touching replaced units or removed Plan stages are removed, and no semantic edge is moved to a replacement by its offset or position. Native event ordering/action-response correspondence remains unchanged. When an action unit changes, its unique native result correspondence can be rebuilt from the retained source event link.

Unrelated explicit unit relationships remain. Named work subjects whose origin changed, their dependent memberships, and invalid named relationship endpoints are removed. Unaffected named bindings/reviews are rebuilt and revalidated. Original edges suppressed by an earlier relationship review are filtered before reapplying retained reviews, preventing a removed endpoint from being resurrected.

Older work-scope, action-identity/method and feedback-coverage observations lack sufficiently precise dependency records. The review clears those layers conservatively and removes their identity/scope edges. This can reduce coverage elsewhere in the rollout; the preview states that cost. Missing coverage becomes unknown, not a negative behavior observation. Finer dependency invalidation remains future work.

Observer composition follows units → work bindings → relationship reviews. Repeated edits under the same combination keep the observer identity; an initial unit correction creates a separate reviewed observer. Graph hashes change, invalidating dependent analysis caches through the existing executor. Previous graph snapshots, analysis outputs and measurement receipts remain readable. Duplicate submissions are idempotent; conflicting stale edits require opening the latest reviewed graph.

## API

- `GET /api/unit-reviews?graph=…&unit=…&window=…` returns an editable document, exact window, activity/content definitions and limitations. `unit` can be an eligible source-event node. `window` is optional.
- `POST /api/unit-reviews/preview` validates and projects the document without persistence or inference; returns its proposed graph identity and dependency impact.
- `POST /api/unit-reviews` saves that correction and wakes the existing monitor service.
- `POST /api/unit-reviews/monitor` takes `graph_id` and `monitor_id`; creates/enables the same graph/analysis measurement for the reviewed observer, preserving the original definition and receipts.

The correction document is `unit-review/1`, with `base_graph_id`, `window_id`, `revision: {author, note}` and `units`. Each unit supplies source-codepoint `start`/`end`, one `activity`, and `fields` under that activity's existing content contract. Plan also supplies `plan_structure`. Obtain a template rather than guessing field names. No endpoint invokes a model.

The updated collector advertises `capabilities.unit_review`. The browser loads the editor only when that capability or a new receipt review context exists. Older running collectors continue to work without the new controls.

## Evidence and remaining work

[Correction audit](../research/unit-correction-2026-10-11/README.md) retains authored recovery/Unicode controls, a public software development trace, exact browser results and the regression log. The tests establish immutable correction, dependency handling, measurement continuation and UI behavior. They do not establish automatic segmentation/classification accuracy, independent annotation agreement, broad native training support or production-scale operating cost.
