# Policy age and behavior

Training health can show the generation-policy age of recorded training uses, its coverage, and saved behavior measures grouped by age. It reads explicit shared policy counters. It does not subtract generation steps from learner steps, parse checkpoint names, or use upload time as a training coordinate.

## Producer contract

The existing `training-records/1` and `/2` transport accepts optional `policy_history` on an immutable sample and `learner_policy` on an immutable use. Older records remain readable with unknown policy age. Do not rewrite them or infer missing counters from their names.

```json
{
  "schema": "generation-policy-history/1",
  "token_count": 8,
  "segments": [
    {"start": 0, "end": 5, "policy": {
      "schema": "policy-clock/1", "clock": "run-uuid/actor-publications",
      "unit": "policy_publication", "index": 12
    }},
    {"start": 5, "end": 8, "policy": {
      "schema": "policy-clock/1", "clock": "run-uuid/actor-publications",
      "unit": "policy_publication", "index": 13
    }}
  ]
}
```

The matching use could have `learner_policy` equal to `{"schema":"policy-clock/1","clock":"run-uuid/actor-publications","unit":"policy_publication","index":14}`. Five targets then have age two, and three have age one. A mixed-version sample does not receive one invented generation version.

`clock` is a producer-declared shared identity, unique to the policy stream and counter origin. A reset, branch, independent actor or unrelated training run needs a distinct clock. Use `optimizer_update` for completed optimizer updates, or `policy_publication` for published policy revisions. Publication intervals and optimizer updates need not coincide. The native producer must establish that generation and learner indexes refer to the same clock; the tracker cannot verify that from two integers alone.

Segments are sorted, non-overlapping half-open positions in the generated target-token array, excluding prompt/environment tokens. Up to 4096 segments are accepted. Gaps remain unobserved. The history's token count must match the use's recorded model-token count. Future generation indexes, different clock identities/units and missing history remain unresolved. Indexes are nonnegative safe integers. Record the capture basis in the containing record's existing `evidence` field.

## Measurement definitions

- Mean age is token-weighted over targets with comparable generation and learner counters. Masked targets are included; this is a generation-age measure, not effective gradient exposure.
- Coverage is comparable targets divided by recorded target tokens. Uses lacking token counts remain visible in the state breakdown but cannot enter that denominator.
- Mixed-version use fraction includes only complete, nonempty policy histories.
- Backward and optimizer receipts are separate stages. Reuse counts again within a stage; summing both stages would double-count the same work.
- Each clock is shown separately. The line's horizontal coordinate is the recorded producer learner step; its vertical value is policy age in the selected clock's unit.
- Saved behavior comparisons use complete histories. Uniform ages get separate groups; mixed histories get their own group. Each immutable source rollout counts once within a group, even when several samples or uses refer to it. Shared sources across groups are reported. This is whole-rollout context, not token-level behavior attribution or a causal effect of age.

Selecting a curve point or age group opens exact uses, source rollouts and behavior maps. Export preserves selected records, generation history, learner clock, sample identities, recipe context and the snapshot ID. Existing saved observations are read without Jev calls.

## Native TRL capture

On the documented TRL 1.13.0 CPU path, `confirm_optimizer_steps=True` now captures policy counters automatically. Each `train()` session starts a new actor clock at zero. The counter advances after a verified, non-skipped native AdamW callback, even when sample receipt delivery fails. Duplicate callbacks do not advance it twice. An unverified/custom optimizer or irreconcilable callback invalidates the clock. This counter is not a parameter hash; a completed update may leave particular weights unchanged.

The sample records the counter surrounding synchronous generation. A use records the policy used for its backward pass. The optimizer confirmation retains that backward policy, rather than replacing it with the post-update counter. Evaluation can record generation history but does not manufacture training uses. External parameter replacement during a session, asynchronous generation, GPU/distributed execution and other native trainers need separate adapters and validation.

See the [native audit](../research/policy-age-2026-10-12/README.md) for the tested scope. This adds a useful conditioning variable for existing recovery and strategy measures; it does not establish semantic-label accuracy.
