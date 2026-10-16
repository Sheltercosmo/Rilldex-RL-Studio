# Continuation experiments

Implemented 13 October 2026. Open **Training health → Additional evidence → Continuation experiments**.
This view imports experiments performed by an external sampler. It makes no model
calls and never changes a trainer's objective. The plan map remains a view of work
inside a rollout; this view records actual producer-declared sampling forks.

**Product role:** this is an optional evidence adapter and viewer for an externally
run check. The [investigation scope decision](RL_ENGINEERING_FRAMEWORK.md#scope-correction-learn-an-investigation-from-a-method--13-october)
puts the research question, comparable cases, competing explanations and follow-up
decision first. This view alone does not provide that complete workflow, and its
remaining technical limitations are not an automatic implementation roadmap for
the blog's proposed training method. A saved investigation's **Checks & findings**
can now attach its displayed result as immutable evidence for a check. The check
and original population remain separately pinned; a later score correction
requires a new reviewed finding. See [the shared workflow](TRAINING_INVESTIGATIONS.md#follow-up-checks-and-returned-evidence).

## What the researcher can inspect

Choose a study within the experiment/environment filters. See before/after success
rates and coverage together, the selected token interval, generated probe-token
cost, and individual continuation branches. Open a branch for its recorded source
unit map, sampling context and backward/optimizer membership. Export freezes the
displayed design, contributing outcomes, record revisions/digests and calculation
version. Subsequent score corrections produce a different snapshot ID.

Missing declarations, incomplete outcomes, duplicate/conflicting score records,
nonbinary scores, different policies/tokenizers/settings, mismatched prefixes and
reused draw identities cannot silently produce a complete comparison. Partial rates
describe only the eligible received outcomes. Missing observations are not failures.
Unplanned sample declarations are disclosed and excluded from the fixed denominator.
Generation costs count recorded output token IDs, with coverage; they exclude
prefill, cache costs, tool work, verifier work and judging.

## Recording from a sampler

The existing durable outbox has a new method:

```python
outbox.log_continuation_studies(experiment, [study])
outbox.log_training(experiment, sample_and_score_records,
                    schema="training-records/2")
outbox.start()
```

It uses the same local queue, bounded capacity, exact acknowledgements and replay
rules as training facts. `POST /api/continuation-studies` accepts:

```json
{
  "schema": "continuation-studies/1",
  "producer": "sampler-worker",
  "experiment": "training-job",
  "studies": ["replace this string with the study object below"]
}
```

The JSON envelope above is schematic, not a ready-to-import experiment. A study is:

| Field | Meaning |
|---|---|
| `id`, `label`, `basis` | Immutable producer ID, readable name and evidence origin. A changed design requires a new ID. |
| `master` | `{producer, id}` reference to an independent `training-records/2` sample. |
| `task_id`, `policy_version` | Actual task and generating policy identities; every participating sample must agree. |
| `tokenizer_id` | Common token vocabulary and revision. |
| `settings_digest` | Digest of native sampling settings, excluding the deliberately different input prefix. |
| `budget_definition` | Explicit budget semantics, e.g. fixed remaining completion allowance versus a fixed total horizon. |
| `environment`, `environment_version`, `environment_kind` | Environment identity/version and `text` or `sandbox`. |
| `verifier` | `{producer, component, definition}` selecting exactly one binary score record per sample. Latest explicit revision wins within that record. |
| `selection` | `prospective`, `retrospective` or `unknown`; describes when the window was selected relative to probe outcomes. |
| `independent_draws` | Boolean producer declaration; required for independent-binomial intervals, not independently certified. |
| `arms` | Exactly `before` and `after`, each defined below. |
| `step`, `step_basis` | Optional paired producer coordinate and clock definition. Retained in evidence; no cross-study training timeline is implemented yet. |
| `confirmation_of` | Optional `{producer, id}` pointing to an earlier study in the same experiment. Requires prospective selection. |

Each arm contains `prefix_tokens`, `prefix_digest`, `state_id` and `samples`.
`samples` is the fixed list of 1–256 planned independent `{producer, id}` sample
identities. They must be unique across both arms and distinct from the master.
Neither text equality nor file order constructs membership. Declare the planned
sample IDs before sampling where possible, and preserve them through retries.

`prefix_digest = tracker.schema.digest(input_token_ids)`. `prefix_tokens` counts
the entire unpadded model input, including the original prompt. Both gates must
match the corresponding prefix of the master's recorded generation input+output
tokens; the before gate cannot lie inside the original prompt. The span length is
`after.prefix_tokens - before.prefix_tokens`. These checks use token identity,
not substring matching or a judge's interpretation.

Sandbox gates require an opaque native `state_id`; text gates have null state IDs.
Matching IDs are recorded declarations, not validation of snapshot/restore fidelity.
Private environment contents need not be embedded in the study design.

Every sample, including the master, can record generation tokens without claiming
any training export or loss mask:

```python
sample_data["generation_context"] = {
    "schema": "generation-token-context/1",
    "tokenizer_id": native_tokenizer_identity,
    "boundary": "native sampler output",
    "input_ids": native_prompt_token_ids,
    "output_ids": native_completion_token_ids,
}
```

Optional output-aligned `policy_versions` and `logprobs` retain their native values.
The sequence is bounded to 131072 input+output tokens. This is an optional field on
independent sample declarations, with no learner facts implied. Existing
`token_context` generation/export evidence also works; if both are supplied, their
generation IDs, tokenizer and common optional observations must agree.

Each child additionally records:

```python
sample_data["continuation"] = {
    "study": {"producer": study_producer, "id": study_id},
    "arm": "before",  # or after
    "draw_id": native_unique_draw_id,
    "settings_digest": native_settings_digest,
    "budget_definition": native_budget_definition,
    "state_id": native_restored_state_id_or_none,
}
```

Policy/environment fields also belong to that declaration. Source references use
the existing exact `data.source` revision mapping; absent source text does not
prevent token/outcome comparison but has no unit-map link. Already immutable
declarations cannot be enriched in place. Capture this evidence at generation or
use new independent sample identities for a separately recorded export.

For confirmation, both gates, master, task, policy, tokenizer, environment,
settings, budget and verifier must match the discovery design. Planned sample IDs
and recorded draw IDs must be disjoint from discovery. Missing discovery draw
declarations withhold confirmation. These checks establish consistency of supplied
records, not proof of fresh physical execution or random-seed independence.

```powershell
python -m rilldex --db .tracker/tracker.sqlite continuation-studies import study.json
python -m rilldex --db .tracker/tracker.sqlite training-records import samples-and-scores.json
python -m rilldex --db .tracker/tracker.sqlite continuation-studies view --experiment training-job
```

`GET /api/continuation-studies` accepts experiment, environment, limit (1–50,
default 20) and offset. The UI pages ten studies at a time. Scoped filters also
include design-only experiments before their sources arrive. Existing live
training-revision events refresh the displayed comparison as records arrive.

## Statistics and interpretation

For each arm, success rate is successful eligible draws divided by eligible draws.
The after-minus-before difference is available only when both fixed arms are
complete, contexts match and master prefixes verify. Confidence intervals additionally
require declared independent draws and no duplicate draw identities. Per-arm
intervals use Wilson; the difference uses the nominal 95% Newcombe-Wilson method
without continuity correction. This is an approximate fixed-design interval, not
an anytime-valid confidence sequence or correction for searching many windows.

With authored 1/16 versus 15/16 controls, the difference is +87.5 percentage points,
with a nominal interval approximately +56.3 to +94.8 points. This does not assign
93% causal token credit, establish a correct loss multiplier, or prove subsequent
training improvement. The data can describe a useful candidate span while leaving
the learning rule unresolved.

Primary references informing the design:

- [VinePPO](https://arxiv.org/abs/2410.01679): Monte Carlo value estimation from intermediate states.
- [BPO](https://arxiv.org/html/2607.14171v1): explicit restored-state branches and sibling returns.
- [MaxRL](https://arxiv.org/html/2602.02710v3): problem-level reweighting differs from within-trajectory localization.
- [Newcombe, 1998](https://doi.org/10.1002/(SICI)1097-0258(19980430)17:8%3C873::AID-SIM779%3E3.0.CO;2-I): independent-proportion difference intervals.

## Validation and remaining work

Contract/transport tests cover outcomes arriving late, corrected rewards, unknown
scores, exact prefixes, metadata conflicts, mixed policies, duplicate draws,
confirmation reuse, source-less scopes and lost acknowledgements. Browser controls
are explicitly authored, in an isolated database; they are not the supplied post's
real continuations. No Jev or Luna calls are needed for capture, joins or statistics.

Still required: native sampler integration and real external branch traces; a
production-scale token evidence store; sampling genealogy across arbitrary nested
forks; multi-study training curves; controlled interventions/selection-aware
inference; and linking span weighting to scalable native training instrumentation.
The existing CPU derivative adapter's 131072-position limits and scalar-advantage
restriction remain. This feature does not claim the full 16 × 100k experiment works.
