# From work maps to rollout measures

## Compare repeated attempts

Open **Overview → Behavior → Distributions → Revisit patterns** to compare
changed inputs, changed feedback and repeated records across rollout windows.
Select a category, then a case, to open both attempts and their recorded input
differences. **Compare attempts** reopens the evidence; the back link restores
the chart selection. Links retain the original graph version.

Distribution shares include unresolved pairs. Unlinked actions are outside
this population; missing observations and observed rollouts with no pairs are
shown separately. [Validation](../research/revisit-distributions-2026-10-21/README.md).

**Behavior map → Work path → Review repeated work** uses the same comparisons. Select a
repeated target to see native input differences, ordered feedback and linked
assessments. **Compare pair** opens the return context and its source evidence.
Feedback fragments are grouped by their source record, without duplicating
returned results. [Validation](../research/work-review-native-2026-10-21/README.md).

For inspected **Approach changes**, case cards show the agent's selected stated
reason alongside earlier and later responses. Search these passages, expand the
recorded dispatches, or use **Inspect stated reason** to open its exact source.
Work path shows the same reason. A later response is evidence to inspect, not an
automatic recovery verdict; exports retain its source and comparison version.

**Errors on repeated work** tracks errors reported on the next same-work attempt
after an earlier error. Case cards and Work path show both inspections and link
to the original responses. Unknown inspections remain visible; inspected earlier
responses without an error are excluded. No reported error is not verified
success. Continuous workers with work links and execution inspection add this
monitor automatically; saved graphs without the report observations remain unknown.

In **Review repeated work**, select **Errors on both attempts** to find affected
targets. **Work timeline → Procedure changes** shows approach and response status
together; select a mark to open its exact pair. Counts follow the visible window.

In **Monitors**, add **Changed inputs on work revisits** or **Repeated inputs and
feedback**, and select a saved work-identity observer. Continuous model observation
adds both automatically. Open a chart point, then **Explain value**, to inspect
input differences, both responses and intervening operations.

```python
from rilldex import Workspace
result = Workspace("study.sqlite").repeated_work(graph_id)
```

Native tool arguments are compared when available; text exports use the full
recorded action text. Feedback is compared in source order. Unknown comparisons
remain outside the rate and retain their evidence. Matching records do not prove
a failed loop: files or prerequisites may have changed between attempts. No model
calls are made. [Validation](../research/repeated-work-2026-10-21/README.md).

## Work structure

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

Annotations bound to one recorded action count once, including across Plan
steps and work branches. Their individual cards and relationship witnesses stay
inspectable. Identical text from separate calls is counted separately; without
an exact source binding, action identities remain separate.

An attempt-path card groups activity units from the same captured call. Stage
response counts also ignore annotation splits; conflicting material readings
remain visible. Plan measures exclude cross-session bindings and unknown order.
Saved counts refresh offline from the same evidence, retaining earlier receipts.

Definition: `work-structure-measures/2`, projection dependency
`work-hierarchy/13`. The registered `work_structure` operation and seven count
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

In **Overview → Behavior → Distributions → Approach changes**, **After an error** compares
the response following each approach in the selected windows. Select a segment
to inspect or export its exact attempt pairs. Unresolved follow-up stays visible;
an inspected response with no reported error does not establish task success.

The design applies the [Graphectory paper's](https://arxiv.org/html/2512.02393v3)
separation of contextual phases and action outcomes without assuming that tool
names identify intent. It also follows the reusable-analysis direction in
[Docent Analysis Plans](https://docs.transluce.org/analysis/analysis-plans): reuse
saved observations for a new deterministic question before purchasing another
model reading. Neither comparison establishes competitive superiority.
