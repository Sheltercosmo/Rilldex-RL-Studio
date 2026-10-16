# Generation and exported training-token evidence

Implemented 11 October 2026. The generic [independent sample contract](INDEPENDENT_TRAINING_SAMPLES.md) accepts optional `data.episode` and `data.token_context`. These facts support investigations of context transformations and mixed-policy samples. A transcript or a rollout-level policy label cannot reconstruct them.

## Generic record

`episode` is `{producer, id}`: a producer-declared logical episode reference, distinct from the source document and independent sample identity. `token_context` uses this contract:

```json
{
  "schema": "training-token-context/1",
  "tokenizer_id": "producer-recorded-vocabulary-and-revision",
  "boundary": "producer-recorded export stage",
  "generation": {
    "input_ids": [11, 12],
    "output_ids": [13, 14],
    "policy_versions": [4, 5],
    "logprobs": [-0.25, -0.25]
  },
  "training": {
    "input_ids": [11, 12, 13, 14],
    "loss_mask": [0, 0, 1, 1],
    "policy_versions": [-1, -1, 4, 5],
    "logprobs": [0, 0, -0.25, -0.25]
  }
}
```

The example is authored. Supply actual recorded arrays and a common tokenizer identity. Generation policy/logprob arrays align with output tokens; training arrays align with the entire unpadded input. Policy versions and logprobs are optional. Version `-1` means unknown, never policy version zero. Token IDs are nonnegative integers; masks are binary integers. Sequences are bounded to 131,072 tokens. Invalid lengths, types and nonfinite numbers fail atomically. Different tokenizer spaces need a different comparison contract; declaring a common tokenizer is a producer assertion, not independently verified by this system.

The backend retains raw evidence in the immutable sample declaration and computes a hashed summary. It reports positional equality of generation input+output against exported input, differing positions, first difference, token/mask counts and recorded policy versions on masked tokens. It does not use edit distance or semantic alignment. A shift can produce many differing positions; the number is not a count of semantic edits. No confidence threshold, model inference or hidden correctness judgment is involved.

In **Training samples → Evidence**, expand **Generation / export tokens match/differ**. Saved investigations preserve the summary and raw record. A matching sequence does not verify attention semantics, tokenizer correctness, reward assignment or downstream consumption. An intentional context transformation may legitimately differ. Loss masks at export are not proof of actual optimizer use. Exported samples may be transformed again later; the capture boundary remains visible.

This field belongs to an immutable declaration. Decide the capture policy before emitting that declaration; adding token evidence later under the same sample ID is a conflict. It cannot recover unrecorded historical tokens. A future multi-boundary artifact mechanism must preserve that history explicitly rather than rewriting declarations.

## Experimental AReaL bridge

`tracker.areal_capture` reads supplied interaction objects and already-exported tensor rows. It does not import AReaL/Torch, invoke `to_tensor_dict`, propagate rewards, change masks, or call a model. It is source-component tested against commit `298412a40f5b84ae6b2042987e81777e6dd0f284`; **ordinary native runtime and trainer integration are unverified**.

```python
from tracker.areal_capture import capture, UPSTREAM_COMMIT

# supplied_interactions and supplied_rows must already exist at the native
# producer's declared boundary. This snippet does not install a trainer hook.
capture(
    outbox, supplied_interactions, supplied_rows,
    experiment="experiment-a",
    episode_id=actual_episode_id,
    export_style="individual",                 # or actual "concat"
    upstream_commit=UPSTREAM_COMMIT,
    boundary="prepared interaction export before trainer transforms",
    tokenizer_id=actual_tokenizer_identity,
    sample_context={"split": "train", "task_id": actual_task_id},
    source=actual_pinned_source_reference,      # optional; otherwise unknown
    capture_token_context=True,                # default False
)
```

The caller must verify the installed upstream revision and supply stable experiment, episode and native interaction IDs. Sample IDs include episode, interaction and export style; changing export style creates distinct samples. `interaction_ids` identifies each exported row's anchor interaction. It is not a complete graph of every earlier interaction whose tokens may be included in a concatenated mask. The bridge keeps mixed token versions instead of choosing one guessed policy version or training clock.

Supply exactly one tensor row per interaction, up to 250 interactions in a packet. A packet must represent one logical rollout: mixed or partially missing native `rollout_index` membership is rejected, requiring the caller to split grouped exports first. An explicit native `rollout_reward` is retained as a separate logical-rollout reward-reference component; conflicting references are rejected. Prepared row reward, original row reward and logical normalization reference remain distinct.

Right-padding is removed only with a contiguous attention mask and zero loss mask on padding. Unsupported layouts fail rather than being silently reshaped. No reward component is treated as an independently verified task outcome. No selection, backward or optimizer record is invented. Native grouping/reward transformations after this boundary remain unobserved.

Default capture retains sample/episode identity and scores without reading or copying token tensors. Full arrays are opt-in for selected samples or debugging runs; large GPU-to-CPU transfers and storage costs need measurement on the actual deployment. The lightweight and full modes cannot be mixed for the same already-declared sample. Empty exports should be handled by the caller; skipped/incomplete upstream interactions are not counted as successful samples.

## Evidence and remaining gates

[Retained component audit](../research/areal-export-2026-10-11/README.md): individual, concatenated and branched exports, mixed policy versions, incomplete interaction exclusion, and a deliberately changed exported input. Python tests, persisted snapshots, outbox/HTTP delivery and browser review exercise the new contract. No pretrained model or paid endpoint is used.

The ordinary import probe fails in this environment, and the pinned package contains Unix-specific imports outside the export routines. The source-component runner explicitly omits package initializers and uses standard logging and postponed annotations. Its results do **not** close the native integration gate. `audit.py --native-package --name <fresh-name>` is provided for a correctly provisioned compatible runtime; that mode has not passed here. A native exporter run, actual learner-input reconciliation, masks/packing/distributed behavior, and capture-on/off noninterference under real training remain required.
