# Compare annotations and their measurement impact

Use this when an activity count, branch pattern or relation-based measure looks
suspicious, or when comparing an original map with a reviewed observer. The
comparison answers what changed in the representation and whether the same
research question gives a different recorded result. It does not certify either
annotation as ground truth.

## In the map

Open a contribution, choose **Review unit boundary, activity and content**, edit
and preview. The existing impact panel now includes activity-count changes,
split/merge groups, observed activity-transition changes and changed relationship
groups. Saving remains a separate action. A legacy overlapping baseline can still
be repaired when an exact comparison is unavailable.

## From Python, without export or inference

Use the immutable graph IDs from `workspace.graphs()` or the map export. Both must
describe the same source revision. Leave `observer` unset when comparing two
different observation sets. Set `history=True` when inspecting historical versions.

```python
from rilldex import Workspace
from tracker.graph_queries import PRESETS

workspace = Workspace("study.sqlite", experiment="training-run", history=True)
comparison = workspace.annotation_changes(
    baseline_graph_id,
    reviewed_graph_id,
    requirements=[PRESETS["assessment_of_inspection_feedback"]],
)

print(comparison["activity_counts"])
print(comparison["units"]["boundary_changes"])
print(comparison["relationships"]["changes"])
for measure in comparison["measurements"]:
    print(measure["delta"], measure["same_anchor_population"])
    print(measure["changed_cases"])  # Exact units and retained path witnesses
```

Each explicit requirement executes the existing graph-query engine on both
snapshots. The result retains both denominators, matched anchors, unavailable
states and the cases behind a changed answer. Equal denominator counts do not
imply the same population: changed anchor membership is checked by source span.
No rate delta is calculated if either recorded-match fraction is unavailable.

`tracker.annotation_changes.compare(before_graph, after_graph)` also accepts
complete immutable graph documents directly. `summary(result)` creates the
compact representation used by the review preview. Neither function saves data,
changes observations or invokes a model.

## Matching and interpretation

- Unit alignment uses exact event, trajectory and Unicode-codepoint spans.
  Node IDs may differ. Overlapping baselines, changed source text, stale graph
  identities and dangling endpoints are rejected.
- Overlap groups identify splits, merges and other boundary changes for review.
  They are not fuzzy matches and never relocate a relationship to a replacement
  unit. Content comparison reports changed fields, not semantic equivalence.
- Activity and transition counts describe stored agent units. Source records,
  feedback units and different actor trajectories are not mixed into that
  sequence. Unannotated source between units remains possible.
- Typed relationship structure matches by source-bound endpoints, retaining
  multiplicity. Evidence/provenance changes are reported separately. Derived
  objects match only when both identity and content remain unchanged.
- Missing, removed or invalidated connections are not observations of absent
  behavior. Graph-query fractions retain their **recorded matches only** meaning.
  Annotation coverage, reviewer declarations and dependency impact stay visible.

Separating exact boundaries from labels follows the established distinction in
[spaCy's span scorer](https://spacy.io/api/scorer#score_spans). This implementation
does not use spaCy or compute an independent accuracy score. An independently
reviewed, task-disjoint reference evaluation is still needed.

## Older workspaces

Read-only analysis now handles the two training-record schemas independently.
A missing newer sample table no longer prevents graph/table access. Table results
and the catalog expose `source_coverage.available_schemas` and
`source_coverage.unavailable_schemas`; frozen datasets preserve that information.
An unavailable feed raises a clear error. This does not migrate the original
workspace or treat missing trainer evidence as zero use.

This compatibility repair covers the training-record union and optional execution
records. It is not a guarantee that every historical schema is supported.

## Evidence

[Audit](../research/2026-10-15-annotation-impact.md) records source controls,
retained review comparisons, a public software trace, installed-package checks
and the actual browser preview. These establish comparison and correction
mechanics, not fresh automatic annotation accuracy.
