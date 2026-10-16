# Record compatibility across frameworks and environments

Rilldex separates three decisions:

1. **Evidence shape:** a conversation, an environment episode, a generation, or a supported structured trajectory.
2. **Delivery:** batch import, append-only JSONL, updating JSON snapshots, or revisioned worker delivery through the outbox/HTTP API.
3. **Training provenance:** recorded experiment, task, sample/group identity, generation and learner steps, policy version, training method and training-use records. These facts are supplied independently; a filename or receipt timestamp is not a training clock.

Harbor and SWE-agent are only the supported **multi-file job layout**, which joins their trajectory files and companion results. They do not define the analysis data model. Other producers should use a common evidence shape or a tested native reader. “Compatible through a common record” and “native framework integration validated” remain separate claims; see [coverage evidence](INTEGRATION_COVERAGE.md).

## Choose evidence by the task, not the trainer name

| Evidence supplied | What survives ingestion | Useful analysis | Boundary |
| --- | --- | --- | --- |
| `messages` with roles, tool calls and result IDs | Message text, call arguments, parallel call/result identities, explicit outcome | Activity and relation analysis, feedback sequences, tool behavior | No result link is invented from message proximity. Extra fields remain raw; media is not visually inspected. |
| `Episode` with actions, observations and explicit endings | Environment transitions, reward, terminated/truncated or unsplit done; optional model response and turn identity | Episode return, response/action/feedback relations, later semantic analysis of recorded model text | Capture must supply JSON-safe visible state. Private `info` stays outside agent-visible evidence. Truncation is not task failure. |
| `prompt` and `completion` text | Exact recorded text and explicit outcome | Reasoning activity, answer/output and reward analysis | Internal environment actions, missing intermediate steps and training clock stay unknown. Token IDs require the matching tokenizer before capture. |
| ATIF or another supported native export | Structure actually recorded by that reader | Measures supported by that evidence; native links where available | Import support does not establish full runtime integration with the originating trainer. |

This works for software tasks, retrieval, customer-service tools, interactive environments and reasoning tasks **when their producer exposes the corresponding evidence**. The environment label alone cannot enable a metric. Use preflight or `Workspace.metric_availability()` to inspect actual coverage. Semantic observations still require an analysis pass; file ingestion alone does not produce validated semantic labels.

## Minimal file capture

Each JSONL line can be a full unmarked conversation:

```json
{"messages":[{"role":"user","content":"What is 7 + 5?"},{"role":"assistant","content":"12"}],"outcome":{"reward":1},"metadata":{"environment":"arithmetic"}}
```

Or a generation:

```json
{"prompt":"What is 7 + 5?","completion":"12","outcome":{"reward":1}}
```

```bash
rilldex --db study.sqlite watch ./outputs --mode exports --experiment run-a --producer run-a/files
```

This catches up existing lines and follows new complete lines. Stop and repeat with the same database, paths and producer to resume. For one updating JSON file per rollout, use `--mode snapshots`; its safe default is in-progress. Explicit rollout/revision/state envelopes preserve identity and completion for both file collectors. Raw JSONL lines represent completed records; append token chunks only after assembling a full record. Do not collect the same logical samples through several independent routes unless their explicit identities are preserved.

`--format auto` recognizes unambiguous common shapes. `--format chat-messages` or `--format generation` resolves a deliberately mixed record. Explicit portable version markers remain supported. Environment episodes require the versioned contract because generic `steps`/`done` fields do not establish transition or ending semantics. Arbitrary JSON and provider response chunks are not silently converted.

Reward/success on unmarked common records come from `outcome.reward` and `outcome.success`. Generic top-level `score` or `reward` fields are not guessed. The native verl reader has its own documented score convention. Preflight explains these boundaries and reports missing measures.

## Capture in a rollout loop

```python
from rilldex import Outbox, chat_document, generation_document, Episode

capture = Outbox(
    "worker-0.sqlite", producer="run-a/worker-0",
    endpoint="http://127.0.0.1:8765",
).start()

def record_conversation(rollout_id, messages, *, complete=False, reward=None):
    capture.log(
        rollout_id, chat_document(messages, reward=reward),
        state="complete" if complete else "in_progress",
        metadata={"experiment": "run-a"},
    )

# Invoke from the producer with its real, accumulated history.
# On shutdown: capture.close(). Pending snapshots remain on disk.
```

For environment capture, `Episode(episode_id="episode-42")` supports `gym_step`, `openenv_step`, and explicit `step`. `model_response` retains the recorded model text alongside the dispatched action; the episode ID is required for those turn bindings. It never asks another model to reconstruct missing reasoning. A finished generation can use `generation_document(prompt, completion, reward=reward)`.

Each worker owns one outbox and a unique stable producer. Reuse a rollout ID for its revisions, not for a different sample. Worker-local IDs may coincide across different producers. Supply actual policy/clock provenance for asymmetric or mixed-server rollouts; do not merge their identities or infer policy age from receipt order. Training selection, backward and optimizer membership require the separate [training ledger](TRAINING_LINEAGE.md), not a change to the rollout document reader.

## Setup and analysis remain code-accessible

```bash
rilldex setup --mode snapshots --format chat-messages --root ./outputs --experiment run-a --save-launch job.rilldex.json
```

The selected schema is retained in generated local, SSH, Docker, cloud and notebook setup, launch files and offline worker examples. The Connections UI uses this same catalog and planner. Existing commands that omit `--mode` keep their historical native-layout default; choose JSON/JSONL explicitly in code. New UI setup defaults to JSONL.

```python
from rilldex import Workspace
ws = Workspace("study.sqlite", experiment="run-a")
availability = ws.metric_availability()
```

Analysis and graph tables use the normalized evidence, independently of transport. No export is required for the existing native workspace analysis API.

## Validation in this change

- Authored controls: unmarked parallel-tool conversation with out-of-order results and null `tool_calls`; reasoning generation; environment episode with recorded model text and truncation; verl flat generation export.
- Public non-software control: pinned airline simulation in `tests/fixtures/tau-bench/airline-0.json`, with provenance in that fixture directory.
- Compared normalized events, explicit outcomes, source metrics and graph edges across JSON/JSONL batch import, JSONL follow/replay, updating JSON collection/restart and revisioned outbox delivery.
- A real ephemeral loopback server accepted five distinct worker namespaces, including reused worker-local rollout IDs and restarted outboxes. Evidence matched the source records; ambiguous packets were rejected without adding rollouts.
- Existing marked portable adapter versions remain unchanged, avoiding unnecessary invalidation of saved analysis. This adds recognition of previously unsupported unmarked shapes; it does not recalculate semantic annotations.
- Ambiguous shapes, unsupported portable versions, incomplete token chunks, raw unversioned environment steps and incompatible native-layout selections are rejected.

These checks run on Windows in the current workspace. They are contract and transport validation, not new distributed/GPU trainer, cloud-credential, browser-vision or semantic-classification accuracy validation.

## Upstream basis

- [verl rollout tracing](https://verl.readthedocs.io/en/latest/advance/rollout_trace.html) distinguishes the agent loop, individual LLM calls and tool evidence. A flat generation export cannot replace the richer history.
- [ART client architecture](https://art.openpipe.ai/fundamentals/art-client/) captures trajectories at the client boundary. This supports integrating at the record-producing loop instead of naming every trainer in the file picker.
- [OpenEnv environment guide](https://huggingface.co/docs/openenv/en/guides/first-environment) exposes actions and observations as an environment contract. Rilldex keeps that contract separate from conversation history and training-use provenance.
