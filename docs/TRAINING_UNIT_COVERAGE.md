# Connect training tokens to saved behavior units

Implemented 12 October 2026. Training health now links each recorded use to
**Training coverage** in the existing behavior map. Researchers can inspect which
saved activities contain eligible target tokens, which have nonzero or zero
observed policy-loss derivatives, and which tokens cannot be assigned. Selecting
a unit opens its target, source and saved relationships alongside these counts.

This answers a narrower, necessary question than causal learning attribution:
**which parts of the observed behavior occur in this recorded training use?**
It does not establish which behavior caused an improvement, whether an activity
label is correct, or how an optimizer changed model parameters.

## Portable evidence contract

An optional `source_alignment` belongs to `use.data.policy_gradient` in either
training-record schema. It describes the same native `target_tokens` array as the
[derivative observation](POLICY_GRADIENT_OBSERVATIONS.md):

```json
{
  "schema": "training-token-source/1",
  "status": "mapped",
  "basis": "Producer's exact mapping procedure and capture boundary",
  "source_hash": "digest of the exact normalized source snapshot",
  "spans": [
    {"event_id": "recorded-event-id", "start": 0, "end": 4},
    null
  ]
}
```

This is an authored schema example. Offsets are half-open Unicode code-point
intervals in the named event's text. Each target has exactly one span or `null`.
Null means unassigned, including special tokens; it never means zero derivative.
The source is the sample's pinned producer revision, not the latest rollout.
One target cannot be split across multiple source events by this contract.

Alternatively record `{schema: "training-token-source/1", status: "unavailable",
reason: "…"}`. Historical uses without this field remain valid and visibly lack
the connection. Adding it to an already-recorded immutable use is a conflict;
do not rewrite history or regenerate paid annotations to populate this view.

The receiving system checks the exact source hash, event existence, bounds,
sample/source experiment and resolved derivative component. A selected graph must
belong to that same source snapshot. Ambiguous sample declarations and inconsistent
source revisions cannot silently select a substitute. Generation provenance does
not establish that the learner used the same prompt or attention context.

## Automatic native capture and its limits

The existing opt-in TRL `capture_policy_gradients=True` path now attempts this
mapping once at generation. No additional model call or user-tuned threshold is
needed. It uses the native tokenizer and the captured completion event, then
requires both exact decoding and exact non-special token-ID re-encoding. Fast
tokenizer offsets supply the spans. Special targets remain unassigned. Slow
tokenizers, changed decoding, failed round trips, and complex structured
completions yield an unavailable reason instead of a nearest-text guess.

The source API is informed by [Transformers' fast-tokenizer alignment methods](https://huggingface.co/docs/transformers/main_classes/tokenizer).
Locally exercised versions are Transformers 5.19.0 and Tokenizers 0.23.3. Current
unversioned Tokenizers documentation describes a different prerelease API; it is
not evidence that those APIs exist in every installation. The bridge is verified
against the installed runtime and retains the derivative's tokenizer identity.

The existing native derivative scope remains: pinned TRL CPU runtime, text-only
policy surrogate, no auxiliary losses or mixed precision. This does not establish
native support for packed multi-turn tool streams, multimodal inputs, vLLM,
distributed trainers, verl or AReaL. Their producers can supply the same explicit
contract, but need their own native alignment/noninterference validation.

## Projection and population arithmetic

`training-unit-exposure/1` joins one immutable training use to one immutable graph.
Every token is accounted for once as unit-assigned, crossing/overlapping units,
unannotated source, non-agent/unestablished source, or unmapped token. A token must
fit wholly inside exactly one non-overlapping saved unit. No fractional credit,
nearest-unit matching, or guessed activity is used. Shared Unicode offsets from
byte-level tokens are supported; each native token still counts once.

Activity totals aggregate the assigned unit tokens. Counts distinguish all mapped
tokens from eligible mask positions and exact zero/nonzero derivatives. Empty
eligible sets have no derivative mean. Source-only maps retain event-level counts
without inventing semantic units. Changing annotations selects a new graph and
projection; older exports stay pinned. Existing graph edges remain untouched.

The read-only `/api/training-spans` endpoint accepts `training_schema`,
`training_producer`, `training_experiment`, `training_id` and `graph`. It reads
one use/sample by indexed identity and returns its projection and export identity.
Backward and optimizer-confirmed receipts remain separate; the latter carry the
earlier backward observation, not an additional derivative computation.

## Evidence and remaining work

[Audit, native control, public-text replay and browser proof](../research/training-span-alignment-2026-10-12/README.md).
The public example uses an existing assistant-authored reference and explicitly
synthetic training values. It is not a native training run or independent semantic
accuracy benchmark. The native control has real derivatives but no semantic
annotations; these two evidence types must not be conflated.

Next: validate independent unit/reference accuracy, native multi-turn alignment
and annotation-version-safe population trends. Bound and materialize summaries
before enabling full token capture at production scale. Per-use storage and
single-process join timings do not establish end-to-end training overhead.
