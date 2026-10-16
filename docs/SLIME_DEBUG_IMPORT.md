# Inspect paired Slime debug dumps

The `slime-dump` command imports native rollout and format-2 training dumps into the existing source store and training-sample view. It uses Slime's own debug-export boundary; it does not require a custom reward callback or semantic inference. This is a batch-file integration, not a live trainer hook.

Enable these native Slime options:

```text
--save-debug-rollout-data /logs/rollout_{rollout_id}.pt
--save-debug-train-data /logs/train_{rollout_id}.pt
```

Check a completed pair and queue delivery:

```text
python -m rilldex slime-dump /logs/rollout_8.pt --train /logs/train_8.pt --experiment my-rl-job --session my-job-branch --producer slime-worker --tokenizer actual-tokenizer-revision --upstream-commit 05e3b017fed9e02de418c2fbac9d75602a534be5 --output /logs/inspection-8 --outbox /logs/tracker.sqlite
python -m rilldex outbox /logs/tracker.sqlite --producer slime-worker --endpoint http://127.0.0.1:8765 --send
```

Use the actual native revision and a stable job/branch identity. A resumed branch with changed identity semantics needs a new session. Reusing the same session and producer preserves retry identity. Supply the actual common tokenizer identity; the importer neither downloads a tokenizer nor guesses decoded text. Native `.pt` files require Torch; primitive JSON exports do not. Loading is CPU-only with `weights_only=True`. Unsupported objects fail rather than triggering unsafe pickle loading or automatic tensor-reference dereferencing.

Without `--outbox`, the command only validates and writes evidence. A different report cannot overwrite an existing evidence directory. Keep the original dumps. The output directory contains the report, source snapshots, normalized sample records, and the primitive native training dump including DP layout and learning-signal arrays.

After delivery, open **Overview → Training samples**, select the experiment, and inspect **Token context**. The view shows exact positional token-ID equality, differences, exported masks and source links. The source inspector retains each native rollout sample and its matched training row. The report additionally gives native join coverage and numerical differences between retained rollout log probabilities on aligned response tokens. It applies no arbitrary pass/fail tolerance.

Samples carry a readable `display_name` such as **Batch 8 · position 3**, separate from immutable identity and task ID. This optional field is available to other training-record producers as well. It changes presentation only; matching, cohorts, counts and historical receipts continue to use their original identities.

## Automatic learning-signal inspection

**Overview → Training health → Retained batch signals** now reads exported advantages, values and returns automatically, including from existing imports. Select a signal to see mask-aware means, spread, exact-zero counts or paired value–return error by Slime rollout batch. No extra importer argument, annotation run or metric formula is required.

Select a chart point, then **Inspect native fields** to open exact response-token positions and masks. Full vectors load only for that case. Readable batch/position names remain separate from immutable sample IDs. Different import sessions and tokenizer/native revisions form separate series.

These are retained batch fields. The source export occurs after the native actor training call but retains earlier values; it does not identify per-sample backward/optimizer uses or exact value-model versions. Effective estimator and target settings are absent. Do not interpret these curves as confirmed-use diagnostics, current critic accuracy or method comparisons without additional context. [Source review and reconciliation](../research/retained-rl-signals-2026-10-12/README.md).

## What is established

- Pairing requires equal native batch IDs and the pinned format. `rollout_position` is preferred. A unique native `sample_index` can be used only when position is absent. Array order, DP-gather order, prompt similarity and token equality are never identity fallbacks. Contradictory IDs or duplicate positions fail the whole preparation.
- The source snapshot and independent sample are distinct. Explicit logical rollout IDs can connect sibling samples within the native batch. Group size is not inferred from surviving rows. Rollout batch IDs are reported as `slime_rollout_batch` coordinates, not optimizer steps or policy versions.
- Generation/export sequences and actual exported response loss masks are retained. Prompt mask positions are zero under this native contract. Per-token advantages, values and returns stay in the native evidence; they are not collapsed into an invented scalar advantage.
- Native scalar reward is a named score, not independent task success. Structured reward objects remain in the original source rather than selecting an arbitrary component.
- Sources and training packets are enqueued in one local transaction. Backpressure rolls the queue operation back. Delivery remains at least once and per packet; partial collector arrival is possible and visible. Sample/source joins can resolve after retry without inventing intermediate facts.

## Limits

Import each immutable paired batch once its files are complete. Do not use rollout-only sample declarations as placeholders and then mutate their token context. Changes to a retained sample under the same experiment/session/position conflict with its immutable declaration; use the actual distinct native run/branch identity instead of silently rewriting evidence.

The import accepts up to 1000 samples and 100 MB per file; individual HTTP packets remain subject to the outbox's 20 MiB bound. Large jobs need bounded native exports. This is not a production throughput result.

Missing training rows are unknown, not rejected samples. Train dump presence does not establish the optimizer applications or all backward uses that occurred. Weight-version lists have no token interval mapping here, so they cannot establish policy age. Flat response text may interleave model and environment content. It stays source context with unestablished ownership; tool calls, coherent agent units and semantic graphs require a separate native trajectory/interaction capture. No paid observations are triggered by import or dashboard reads.

The pinned native writer and four-sample CPU controls validate the format and delivery. They do not validate full Slime/Megatron/SGLang execution, asynchronous scheduling, GPU collectives, semantic accuracy or real training outcomes. See [source audit, tests and reproducible evidence](../research/slime-debug-import-2026-10-12/README.md).
