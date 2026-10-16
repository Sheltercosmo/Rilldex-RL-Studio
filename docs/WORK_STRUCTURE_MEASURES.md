# From work maps to rollout measures

Open **Behavior map → Plans & attempts**. Expand the available work summary to
compare branch effort and depth. **Track across rollouts** opens a prefilled
monitor with the same evidence observer and experiment (when recorded). Review
its population and save it. The monitor uses the normal dashboard, investigation
filters and value export. Open a value, choose **Explain value**, then a case to
return to the exact work item and frozen graph.

These measures reuse saved evidence. Creating them does not call Jev, Luna or
another provider. They apply to supported graphs regardless of whether capture
used HTTP, JSONL, JSON snapshots or a completed import. The input must contain
the required evidence; a transport adapter cannot supply missing semantics.

| Evidence basis | Per-rollout measures | Meaning |
|---|---|---|
| Semantic Plan and action-to-step links | Plan steps with linked attempts; distinct dispatches linked as Plan attempts | A preparation or check alone is not an attempt. One action linked to several steps counts once in the dispatch measure. |
| Producer-declared goal tree | Declared goals with recorded visits; native goal operation requests | A visit requires a goal's own entry/operation record. Shared source occurrences count once. Requests do not prove tool execution. |
| Reviewed objective/approach outline | Explicit work-resume, work-stop and work-deferral decisions | Counts source-bound decisions. Failure, inactivity and unmentioned alternatives do not imply a stop or deferral. |

Each basis remains separate. Missing support produces an unavailable value, not
zero. A supported profile with no matching witness produces zero recorded
matches; this does not establish that incomplete annotations captured every
decision or attempt.

Branch rows show recorded state, depth and effort with the counting unit named.
Root depth is zero. Control nodes do not add goal depth. Reviewed work with
multiple parents retains a minimum/maximum depth rather than choosing one path.
Parent effort includes captured descendant scopes; overlapping branches are not
additive. Semantic Plan effort counts attempts, whereas reviewed-outline effort
includes its linked preparations, attempts and checks. Do not compare their
numbers as the same construct.

## During training and after replay

The map can inspect a partial source and restrict evidence to a recorded moment.
Moving the cutoff excludes future declarations, attempts and decisions. A
monitor created from this view measures each completed rollout, not the map's
temporary cutoff. The dashboard keeps incomplete/failed capture snapshots out
of completed-rollout statistics. A failed task may still have a complete
capture and a recorded unsuccessful outcome; capture state and task outcome
are separate.

Recorded experiment and training coordinates place values on training curves.
Without them, values remain inspectable with **No training coordinates recorded**;
import time is not substituted for a training clock. Within-step display order
is not a generation-time claim. Source revisions replace a sample's current
population contribution, while previous measurement receipts and graphs remain
available. Replaying unchanged evidence reuses the cached projection.

Definition: `work-structure-measures/1`, projection dependency
`work-hierarchy/12`. The registered `work_structure` operation and seven count
measures share the projection used by the map. They do not estimate exploration
quality, exploitation, causal efficiency, ignored plans or verified success.
Independent semantic accuracy and RL training benefit remain unestablished.

[Source reconciliation and lifecycle checks](../research/work-structure-measures-2026-10-14/README.md)
cover a published nested-agent example, a development-reviewed software graph,
and authored transport/revision controls. See [getting started](GETTING_STARTED.md)
for capture choices and [the goal-tree contract](DECLARED_WORK_TREE.md) for
producer instrumentation.


## Decisions and recorded follow-through

A branch's decision history now shows **Recorded follow-through**: preparations,
attempts, checks, returned feedback and assessed feedback after that statement,
until its next statement or the selected observation cutoff. Each action opens
its exact saved role, response and assessment witnesses. The Work timeline shows
the same counts when a statement marker is selected.

This answers a narrower, useful question than an inferred strategy score: “What
recorded work followed this decision, and which returned evidence was assessed?”
A completion claim remains a statement. In the retained public software trace,
the statement that the PDF is complete is followed by a directory listing. That
check establishes recorded file-presence feedback, not correctness of the PDF,
the dataset or the task. The conversion decision has four linked attempts.

Windows are source-record ranges, not causal execution intervals. Overlapping
conflicting statements and unresolved ordering have no attributed counts.
Missing execution mappings are unavailable, not zero. Shared parentage keeps
its scope; branch totals can overlap. Feedback or assessments after the next
statement are excluded from the earlier window. A current observation cutoff
does not establish that a window is complete. Unlinked execution cannot support
an ignored-plan or compliance judgment.

The projection now also rejects plan-action links across source contexts,
responses before a dispatch, and assessment links from another context. Version
10 invalidates cached work projections without changing immutable annotations.
No provider is called by this projection or by the public Python entry point:

```python
from rilldex import Workspace

workspace = Workspace("study.sqlite", observer="your-saved-observer")
# Use a graph_id from workspace.graphs().rows; scope is enforced.
result = workspace.work_structure(graph_id, cutoff_event_id=None)
for window in result["decision_windows"]:
    print(window["label"], window["decision_types"],
          window["status"], window["counts"])
```

The existing `work_structure` analysis operation returns the same windows.
Their `decision_ids`, `binding_ids`, action memberships and response links make
custom investigation possible without exporting the database or re-tagging.
This is an inspectable deterministic join over reviewed evidence, not a newly
validated semantic classifier or a universal exploration/exploitation measure.

The design applies the [Graphectory paper's](https://arxiv.org/html/2512.02393v3)
separation of contextual phases and action outcomes without assuming that tool
names identify intent. It also follows the reusable-analysis direction in
[Docent Analysis Plans](https://docs.transluce.org/analysis/analysis-plans): reuse
saved observations for a new deterministic question before purchasing another
model reading. Neither comparison establishes competitive superiority.
