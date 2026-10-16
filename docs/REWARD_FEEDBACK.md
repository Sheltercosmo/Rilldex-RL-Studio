# Recorded reward feedback contract

Version: `reward-record-inspection/2`. This is a direct per-rollout measurement layer. It reads recorded evaluator output without asking Jev to reconstruct facts already present in the log. It does not establish independent answer correctness, private intent or confirmed reward hacking.

## Integration

Keep evaluator feedback outside agent-visible events. The source document can carry the following optional envelope; normalized imports preserve it in `run.raw.reward_evaluation`:

```json
{
  "reward_evaluation": {
    "schema": "rubric-evaluation/1",
    "criteria": [
      {"id": "a", "description": "Required content was supplied", "weight": 4, "category": "Content"},
      {"id": "b", "description": "Prohibited content was supplied", "weight": -3, "category": "Constraint"}
    ],
    "verdicts": [
      {"criterion_id": "a", "met": true},
      {"criterion_id": "b", "met": true}
    ],
    "reported_counts": {"criteria": 2, "verdicts": 2, "met": 2},
    "score": 0.25,
    "timeout": false,
    "error": ""
  }
}
```

Criterion IDs must be unique, weights finite numbers, and verdicts boolean, integer 0/1 or null. Missing/null verdicts remain unknown. Optional reported counts must agree with their arrays. Unsupported schemas yield unavailable measurements; recognized invalid records yield an invalid-record indicator and unavailable rubric calculations. Missing timeout/error fields are unavailable, not false.

The existing CHERRL HealthBench decoder reads its JSON-encoded rubric and verdict arrays and preserves original fields. It requires equal positional-array lengths; it never guesses where a missing verdict belongs. Decoders have distinct protocol identities, which remain separate in training cohorts.

For another framework, map its recorded evaluation result into this envelope or implement a versioned decoder. Merely having a numeric reward does not provide rubric observations. Do not fabricate criteria or verdicts from that scalar. Actual generating-policy identity, training iteration, task identity, environment/evaluator revision and sampling settings belong in rollout provenance.

## Measurements

Let `P` be the sum of positive criterion weights, `C` the sum of positive weights marked met, and `N` the absolute sum of negative weights marked met. Complete valid verdicts and `P > 0` are required for weighted scores.

| Metric | Definition | Research use |
|---|---|---|
| `reward_record_invalid` | A recognized record violates the input contract | Find broken reward exports or contradictory counts |
| `reward_verdict_coverage` | Known valid verdicts / recorded criteria | Distinguish missing judgments from negative judgments |
| `reward_positive_attainment` | `C / P` | Inspect recorded desired-content credit |
| `reward_penalty_fraction` | `N / P`; may exceed 1 | Separate penalty weight from positive credit |
| `reward_penalty_observed` | Any negative-weight criterion marked met | Monitor incidence of recorded penalties |
| `reward_score_gap` | Logged score minus `(C - N) / P` | Expose reward transforms or inconsistencies for investigation |
| `reward_zero_with_negative_rubric` | Logged score is exactly zero and `(C - N) / P < 0` | Expose different penalty severities hidden at the same zero reward |
| `reward_timeout_reported` | Explicit recorded timeout flag | Monitor evaluator operation |
| `reward_error_reported` | Explicit error string is nonempty | Monitor evaluator operation |

A positive penalty establishes incidence even when some other verdicts are unknown. A zero requires all negative criteria to be decidable, or a nonempty rubric with no negative criteria. Invalid records do not enter this denominator. Incomplete positive criteria still prevent weighted score calculations.

Binary metrics aggregate as positive rollouts / decidable rollouts, accompanied by positive, decidable and unknown counts. Other metrics retain their distributions. The chart keeps individual rollout points and separates incompatible source/observer protocols. Unknown training coordinates are excluded from the time axis; import order is never substituted. Missing iterations stay gaps. A plot across changing tasks is descriptive, not a causal estimate of training improvement.

The untransformed signed formula matches the reference calculation in [OpenAI's HealthBench evaluator](https://github.com/openai/simple-evals/blob/main/healthbench_eval.py). That establishes the comparison formula, not the code used by another dataset publisher. A gap is not automatically a reward bug. Stored judge verdicts are evidence of what the judge recorded, not proof that its assessment is correct.

## Inspection and replay

`GET /api/reward-records/<run_id>` returns the protocol, immutable normalized-source hash, calculations, issues, criterion/verdict references and original evaluator fields. `#i` references identify positions in decoded arrays. The rollout drawer verifies the source hash before showing this material; evaluator fields remain separate from the agent's trace.

The ordinary rollout metrics report adds these measurements to every compatible imported record. This path uses no model calls. Historical measurements retain their schema/protocol identities; current source measurements are recomputed under the new version without duplicating old source rows in a current report.

This layer complements the [source behavior detectors](../research/diagnostic-monitors-2026-10-08/README.md). Answer acquisition, evaluator interference and result reuse still require action/source evidence. They cannot be established from a penalty or a reward gap. Higher-level recovery, deviation and completion metrics still depend on sufficiently accurate unit/target/result relations.
