# Synchronized training investigations

Open **Monitor management** and choose a research question, or use **Investigate interval** on a behavior chart. Shift-drag also selects an inclusive interval on a chart. Enter a reference interval, confirm the experiment and measures, then capture once. This saves one database snapshot across the panels; opening the result does not run inference.

## What the comparison answers

| Question | Evidence shown | Important boundary |
|---|---|---|
| Is performance improving on comparable tasks? | Outcomes, train/eval split, task composition and separate configuration cohorts | Recorded task identity does not control unrecorded difficulty or budget. |
| Are useful rollouts filtered or delayed? | Declared and delivered membership; generated, scored, admitted, backward and optimizer membership; component scores before/after selection | Missing selection/use receipts are unknown. Declarations retain their own coordinate system. |
| Is recovery improving? | Recorded changed-input rechecks, recovery windows, repeated failed follow-ups, unresolved windows; linked semantic revisions when available | A completed action is not a passing criterion. Recorded input changes are not inferred semantic revisions. |
| Does reward agree with independent outcomes? | Reward/outcome measures and relevant delivery verification; custom evaluator monitors can be attached | A source success flag does not prove evaluator independence. |
| Is more compute producing progress? | Outcomes, work/verification measures, native token-use coverage and masking where captured | Actions are not compute. GPU-hour efficiency requires resource allocation and comparable evaluation evidence. |

The five bundles reveal current measurement coverage and missing prerequisites. Adding starter definitions creates deterministic monitors; it does not schedule semantic extraction. Choose an existing compatible observation protocol for semantic measures. Existing code-defined monitors can be attached to a bundle and included in the same interval capture.

## Clocks, populations and definitions

- Source `training_step` selects the intervals. Different training clocks, step bases, sampling definitions, reward definitions, splits and environment versions remain separate cohorts.
- Learner records join through exact sample/source revision identity, not equal step numbers. Reuse is retained; backward and optimizer use remain separate.
- Score comparisons keep scorer, component and definition separate. Their denominators cover samples with a record for that component; they cannot recover unlogged scores. Multiple score records for one component/sample are ambiguous, not silently averaged.
- Masking is `1 - sum(loss_tokens) / sum(model_tokens)` over use receipts containing both counts. It is not causal gradient contribution or a universal health threshold.
- Generation declarations retain their own clocks. Unaligned declarations cannot prove closure of the selected source population.
- Charts use raw per-step values, pooling numerator/denominator for ratio measures. Missing steps remain gaps. Reference and selected summaries show measured rollouts, decidable opportunities and unresolved opportunities.

## Evidence, history and reliability

**Reference evidence / Selected evidence** open immutable measurement receipts. Recovery evidence shows the failed check, relevant recorded change and later check/result. The linked rollout map uses the same receipt. Counts of repeated-failure windows can overlap; they are not unique attempts or wasted compute.

Each measure retains its definition version, observation protocol, used graph/harness definitions, available annotation coverage and exact audit associations. Reviewer roles are self-declared. Coverage and agreement on sampled opportunities do not establish general semantic accuracy or detect opportunities omitted by the extractor.

Record curriculum, sampling, reward/grader, budget, restart or infrastructure events with an explicit clock and basis. Only matching events appear on a curve. These are researcher-recorded annotations, not automatic incident detection. Corrections can supersede earlier events through the API; both remain stored.

Use **Plan a check** and the existing findings workflow to document a competing explanation and follow-up evidence. A coincident configuration change is a candidate explanation, not an established cause.

## Late arrivals and reproducibility

The saved population, receipts, history and audits do not change after capture. **Compare with latest arrivals** creates a child comparison; it does not overwrite the original. Export downloads the saved document. Live SQLite analysis and capture are available without export or the UI:

```python
from rilldex import Workspace

workspace = Workspace("workspace.sqlite", experiment="my-training-run")
review = workspace.investigate_interval(
    baseline=[80, 95], current=[96, 111],
    title="Reward plateau after selection",
    hypothesis="Generated outcomes may improve while the admitted population stays flat.",
)
print(review["id"], review["snapshot"]["learning_context"])

workspace.annotate_history(
    kind="sampling", title="Sampling support changed",
    detail="Reference the actual resolved configuration and native log here.",
    step=112, clock="policy", basis="generation",
    investigation_id=review["id"],
)

latest = workspace.investigate_interval(
    baseline=review["controls"]["baseline"],
    current=review["controls"]["current"],
    monitor_ids=review["controls"]["monitor_ids"],
    environment=review["controls"]["environment"],
    parent_id=review["id"],
)
```

Captures support at most 24 monitors and 20,000 source rollouts. Narrow the interval or measure selection for large studies.

HTTP: `POST /api/investigations/interval` saves; `/api/investigations/interval/preview` reads without saving. `GET /api/monitoring/questions` lists bundle readiness; `/activate` and `/bind` configure them. `POST /api/experiment-history` records events. Existing investigation export and follow-up endpoints accept these captures.

## Validation and limits

The authored engineering replay in `research/validate_interval_workflow.py` uses 64 rollouts over 16 generation steps, each with 12 tool actions and explicit state/check records. It asserts generated reward 0.25 → 0.75, admitted reward 0.50 → 0.50, masking 20% → 60%, different learner coordinates and two undelivered members. A separate 512-rollout, 32-step test verifies that late arrivals change a new comparison without rewriting the original apparent regression.

These controls validate transport, arithmetic, evidence binding and workflow. They do not reproduce the cited experiments, validate general semantic extraction, establish causal diagnoses, or certify native capture across every RL framework. No model API is used by this investigation layer.
