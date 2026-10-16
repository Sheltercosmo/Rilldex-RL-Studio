# Independent samples and source-rollout context

Implemented 11 October 2026. One episode can now produce several samples, each with its own scores, filter decisions and recorded uses. This opt-in contract extends the existing intake, ledger, saved investigations and comparisons. It does not introduce a new training engine or claim a new native trainer integration.

## Producer contract

Use `training-records/2` for independent identities; existing `training-records/1` producers remain supported. A sample is identified by `(experiment, sample.producer, sample.id)`. Source producer and sample producer may differ. Record identities remain scoped by packet producer and experiment and cannot be reused across the two schema versions in the updated receiver.

```python
from tracker.capture import Outbox

outbox = Outbox("training-export.sqlite", producer="training-exporter")
outbox.log_training("experiment-a", [{
    "id": "sample/episode-42/turn-2",
    "revision": 0,
    "kind": "sample",
    "sample": {"producer": "training-exporter", "id": "episode-42/turn-2"},
    "evidence": {"basis": "native training exporter record"},
    "data": {
        "split": "train",
        "task_id": "task-7",
        "source": {"producer": "environment-worker", "rollout_id": "episode-42", "revision": 0},
        "interaction_ids": ["native-completion-id-2"],
    },
}], schema="training-records/2")
```

The identifiers above are illustrative. Take actual values from the producer. Scores, selection and use retain their existing data contracts and reference the same independent `sample` object. They can arrive before its declaration or source. Send them through `Outbox.log_training`, `POST /api/training-records`, or `training-records import` with the v2 packet schema. The SDK still defaults to v1; an old running collector must be upgraded before it can accept v2 packets.

`data.source` is optional. If present, it requires producer, rollout ID and exact nonnegative revision. It may contain `spans`, a nonempty list of `{event_id, source_pointer, start, end, text}` referring to normalized events of that pinned source. Bounds are Unicode codepoints, text must match exactly, and spans may not overlap within an event. Copied/private/external event evidence is not accepted as an observed span. Invalid mappings stay unresolved rather than falling back to the latest revision or whole episode. Source experiment conflicts also prevent a join.

`interaction_ids` preserves a unique list of producer-declared model-call identifiers. It is not a validated interaction graph. A source reference establishes provenance; exact spans establish text correspondence. Neither proves what input tokens the model saw, which tokens received loss, or that a future episode outcome belongs to a selected earlier turn.

Declarations and uses remain immutable revision-zero facts; a second declaration for the same independent sample is a conflict. Different sample IDs mapping to one source are valid. Source-less samples remain visible with unknown behavior coverage.

## Optional episode and token evidence

Generation-only producers can also attach `data.generation_context` with schema
`generation-token-context/1`, tokenizer identity, capture boundary and native
input/output token IDs, without inventing a training export or loss mask. It is
immutable sample evidence. [Continuation experiments](CONTINUATION_STUDIES.md)
use these facts to check exact prefixes and join later verifier outcomes.
Optional `data.continuation` preserves the declared study, arm and draw identity.

The generic v2 sample can also declare `episode: {producer, id}` and opt-in generation/export token context. These preserve logical execution identity and exact token evidence separately from the source rollout. [Contract, capture cost, UI and AReaL component evidence](TRAINING_TOKEN_CONTEXT.md). Token context belongs to the immutable declaration; later evidence cannot silently replace it.

## Counting rules

| Quantity | Unit and weighting |
| --- | --- |
| Generated/scored/admitted/backward/optimizer stage count | Distinct declared samples with recorded membership; repeated uses do not add samples |
| Behavior mean | Each distinct bound source rollout once, within the selected population |
| Pooled opportunities | Sum the monitor's counts once per distinct source rollout, preserving unknowns |
| Within-group difference | Source-weighted mean on each side, then equal weight per comparable recorded group |
| Cross-metric rank association | Each distinct source rollout once in the paired union; retain all paired sample IDs |

For example, two samples referring to an episode with one recovery do not create two recovery opportunities. An episode can appear on both sides if its samples receive different selection decisions. The UI discloses that overlap; the sides are not independent experiments. Common-support selection retains samples measured by every monitor, then deduplicates source weight. Missing source evidence remains explicit. Conflicting measurements for one immutable source are rejected rather than resolved by arrival order.

Behavior values are labelled **whole-source context**. They are not measurements restricted to sample spans and do not establish causal training credit. There is no token-weighted mode without validated token alignment. An earlier sample's contextual episode recovery may happen later; do not use it as a pre-action predictor.

V1 and v2 identities stay in separate cohorts. Saved v1 comparisons retain their original arithmetic and identity hashes. V2 projections/selection/comparison results have new schema versions and explicit weighting. The existing investigation store pins both versions. The database uses a sibling table for v2 facts so existing nine-column v1 inserts remain compatible; old collectors cannot serve the new table.

## Researcher workflow

In **Overview → Training samples**, choose an existing behavior monitor and a named filter. Read both sample coverage and distinct source coverage. Open **Training evidence** to see sample ID, source revision, interaction declarations and exact spans. Save an investigation, compare other monitors, and inspect the pinned source behavior map. No model call is needed to join or aggregate retained observations.

The authored recovery demonstration contains three samples linked to two episodes: recovery is 1/2 decidable opportunities with three additional unknown opportunities. Counting the duplicated episode twice would instead give 2/3, an incorrect source-level rate. The old 12-sample native TRL comparison also replays exactly. [Audit and validation](../research/independent-samples-2026-10-11/README.md).

Remaining work: native multi-sample exporter validation; per-call visible-context and training-input artifacts; mixed-policy generation segments; expected group completeness; distributed/resume lineage; independent semantic accuracy and production throughput. These are separate acceptance gates, not implied by accepting v2 JSON.
