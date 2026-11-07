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
| `responses-items/1` with accumulated items | Messages, reasoning summaries, function/custom calls and linked outputs | The same maps, activity analysis and measures | Encrypted reasoning and unresolved item references stay unread; completion status is not success. |
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

The same `messages` route accepts Anthropic `tool_use`, `tool_result` and recorded
thinking blocks, native tool definitions and top-level `system`. Mixed user
messages separate tool feedback from instructions; results link by call ID.
Supply accumulated message records, not raw Claude Code stream chunks.

For Responses histories, retain the items actually exchanged with the model:

```python
from rilldex import responses_document
record = responses_document(items=recorded_items, tools=tool_definitions)
capture.log("rollout-42", record, state="in_progress")
```

Include input messages, model output items and returned tool outputs in recorded
order. A response's output alone is not the full history. Put system/developer
instructions in explicit message items. Use the same document inside a session
with `trajectory_id` and `context_id` when capturing several contexts.

## Capture multiple agents or context resets

Keep each agent's visible history and tool definitions together:

```python
from rilldex import chat_sessions_document

record = chat_sessions_document([
    {"trajectory_id": "planner", "context_id": "attempt-1",
     "messages": planner_messages, "tools": planner_tools},
    {"trajectory_id": "worker", "context_id": "attempt-1",
     "messages": worker_messages, "tools": worker_tools},
], metadata={"experiment": "run-a"})
capture.log("rollout-42", record, state="in_progress")
```

Use a new `context_id` after a reset. OpenAI-style calls and Anthropic content
blocks can coexist in separate sessions; tool-call IDs may repeat across them.
Include a handoff or summary in the receiving agent's messages when it was
actually visible. Analysis uses each recorded history separately. Session list
order does not establish concurrency or communication. Save this document as
JSON/JSONL or send it through the existing outbox; `auto` recognizes it.

Activity windows and sequence comparisons keep contexts separate. Use the
existing **Agent / context** selector to inspect each history. Transition counts
and retry measurements never join a reset to the preceding context. Work in
another context does not count as intervening work in the current one.

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

## Explain an unfamiliar environment

Supply tool descriptions and parameter schemas with chat histories. For numeric or
structured environments, add JSON Schema descriptions to `Episode`:

```python
episode = Episode(
    episode_id="trial-42",
    action_schema={"type": "integer", "oneOf": [
        {"const": 0, "title": "move left"},
        {"const": 1, "title": "move right"},
    ]},
    observation_schema={"type": "object", "properties": {
        "position": {"type": "number", "description": "Position in metres"},
    }},
)
episode.reset({"position": 0}).step(1, {"position": 0.5})
```

Use `properties` for named fields, `prefixItems` for vector dimensions, and
`const` with `title` for encoded actions. Existing Pydantic models can supply
`model_json_schema()` directly. Match the values emitted by your actual wrapper.

These definitions reach macro, activity and semantic analysis alongside the
original values. Chat tool catalogs are also available when reading a plan before
its first call. They describe the encoding; they do not assert that the agent
saw the definitions or that an action succeeded. Invalid attempted actions remain
in the trace. Schemas are stored as supplied; external references are not fetched.

New semantic workspaces retain recent context, native call/result links and up
to six relevant earlier passages, with exact source offsets. This helps recover
distant plans, revisions and drafts. Later state updates stay in source order.
Other sessions, future results and private evaluator data remain outside the
reading. Existing workspaces keep their saved context policy.

Validation includes navigation, continuous control, inventory and browser
captures, plus four public airline/telecom traces. These are evidence-preservation
checks; they do not establish a cross-environment model accuracy score. Numeric
arrays need documented meanings; image/audio references still require perception.

`python scripts/evaluate_environment_reading.py` exports a reproducible reading
test. Add `--live` with `JEV_API_KEY` to compare described, renamed and undocumented
operations. Results report model accuracy separately from capture validation.

The macro reader retrieves relevant earlier call results alongside recent steps,
including matched passages inside long results. It retains native policies and
keeps source offsets, agent/context scope and later state updates. Clipping a
policy no longer discards an otherwise supported action-purpose decision.
Recent long results retain their beginning, ending and relevant middle passages.
The response reader distinguishes routine next steps from changed settings or
methods, including algorithms selected through a parameter of the same tool.

In the behavior map, select a dispatched action and open **Action reading**.
Read that action with Jev, inspect its purpose and response to feedback, or follow
the links to earlier evidence. This also works on source-only maps. Saved readings
are reused; reviewer choices remain in place when a model reading is refreshed.

**Rollout Story → How the agent works** shows current purpose readings by agent
context, with method changes, matching calls and task-relationship markers.
Select a tile to open its evidence. **Read next** resumes pending model readings;
coverage updates as each action is saved. Unread actions remain visible.
**Combined purposes** keeps a dispatch with several requested purposes together;
it is separate from unknown purpose and does not invent an internal sequence.
Saved returns to earlier work appear here too, including reasoning-only traces.
Select a return to open its evidence in **Work path**; missing evidence stays visible.
**Across training** opens the same task in Behavior. Compare **Action purpose** or
**Task connection**, then open the actions behind a change. Reader models stay
separate; saved comparisons retain their readings and unread-action counts.

After a reader update, resume inspection to refresh outdated readings. Exact
saved requests are reused across purpose, activity, relationship and field
analysis; compatible partial readings resume from their saved stage. Earlier
readings and reviewer labels remain available in the evidence inspector.

Live development checks use `jev-1.13.0` and retain exact requests/responses:

| Check | Result |
| --- | --- |
| Task constraints, same controls | 12/15 → 15/15; three added long-result/renaming controls also passed |
| Described / renamed / undocumented operations | 11/11 · 9/9 · 11/11 |
| Chat, Anthropic and Responses purpose/activity readings | 96/96 paired decisions from nine authored operations and seven public trace actions |
| Distant revisions and repeated drafts | 0/6 → 6/6; full-prefix diagnostics also passed |
| Read versus expected-result check, across three formats | 15/18 → 18/18 after retaining local purpose |
| Fresh generated-map dispatch readings | 9/11 → 11/11 with a clearer Inspect/Verify boundary |
| Plan relationships with one candidate per decision | 35/36 → 36/36, retaining the same source context |
| Related-work method candidates | Recovered a missed route change; all nine reviewed pairs separated comparable from different work |
| Ten previously unused public airline/telecom actions | 20/20 purpose/activity judgments; both handoff-report checks passed |
| Target relationships with source intervals and recorded operation definitions | 13/17 → 16/17 against the original labels; three encoded-operation and four explicit-identity controls passed |
| Reward checks with each operation beside its own definitions | 12/14 → 14/14; eight earlier code-flow and artifact controls also passed |
| Custom requirement checks | 15/15 controlled outcomes, including partial traces, unverified completion claims and five cases with fresh requirement extraction |
| Response to feedback in long results | 0/18 → 18/18 across six authored scenarios in three formats |
| Routine progression versus revision | 9/18 → 18/18 across six additional controls; two selected public follow-ups improved from 0/2 to 2/2 |
| Combined-purpose dispatches | 26/26 controls and 2/2 missing-context cases with distinct combined/unknown categories; the eight independently authored cases improved from 6/8 to 8/8 |

These are development controls and selected public examples, not a deployment
accuracy estimate. Paired serializations are not independent samples. Repeat the
reading checks with `python scripts/evaluate_generalization.py --live --prompt-key`.
The full generated-map tests use `scripts/evaluate_generated_generalization.py`;
its candidates are explicit development artifacts, not a general-purpose worker.
`--focused --refined --public --interval` exercises the current target, plan, feedback and method
layers on six scenarios. Related-work candidates pass an independent work-instance
check; rejected pairs do not alter other work groups. Accepted comparisons reach
the action inspector and behavior measurements without merging the original paths.
Saved live evidence is under `tests/fixtures/*generalization*.json` and
`tests/fixtures/environment_reading_evidence.json`.

Feedback-reading trials are retained in `tests/fixtures/feedback_reading_evidence.json`,
including the first definition's regressions. Repeat with
`python scripts/evaluate_feedback_reading.py --output outputs/feedback --arms production --live --prompt-key`.
The final trial matches all 38 response references, but purpose still differs on
six parser cases (apply versus verify). The formats repeat 12 authored scenarios;
the two public actions come from one trace. Historical evaluation replays use
their saved requests; live evaluation uses current readers and preserves references.

Purpose trials retain the broad rewrite's clarification regression and the
original parser disagreements in `tests/fixtures/action_purpose_evidence.json`.
An independent model review found the two underlying parser references ambiguous;
their original labels remain. The final definition preserves all 38 feedback
references. Replay with `python -m unittest discover -s tests -p test_action_purpose_evidence.py`.
The independent controls were used during refinement, not held out from the final choice.

Six additional public airline/telecom episodes cover all 30 recorded tool actions.
Against an independent blinded model review, unambiguous agreement was 29/29 for
purpose, 18/27 for task connection and 22/26 for feedback response; eight ambiguous
fields remain separate. The report retains differences between action, message and
completed-dispatch scope. A missed expired-contract restriction persisted with
more context and simpler wording; one exact-clause, compact-evidence diagnostic
recognized it. These findings have not changed the production reader.
All 59 trial receipts remain in `tests/fixtures/public_episode_reading_evidence.json`.
Replay their recorded requests offline with
`python scripts/evaluate_public_episodes.py --output outputs/public-episodes`.
Use `--live --prompt-key --max-calls 30` to evaluate fresh requests.

Requirement scans also read explicitly captured environment policies and workflow
rules, scoped to their recorded agent context. Existing saved scans retain their
original protocol and can resume unchanged.

In a map, select an action and expand **Action reading**. **Same model output**
opens companion messages and tool calls using native message identities. These
links show what was recorded together; delivery and execution order require
separate harness evidence.

Focused dispatch review accepts exact rule and context quotes from a local or API
candidate worker. It preserves parallel calls, prior state and excerpt boundaries.
This Python workflow supplements the existing reader; selected rules are not a
full-policy audit. Oversized prefixes require a larger configured selection budget.

On 25 development comparisons from eight public airline/telecom dispatches, native
context improved agreement with the original unambiguous model references from
17/19 to 18/19. A separate routing review marked the remaining disagreement
ambiguous; both reference sets and all 75 valid trial receipts are retained.
These are development results, not held-out or human-rated accuracy. Replay with
`python scripts/evaluate_dispatch_reading.py`.

The remaining target disagreement concerns a fallback booking: one customer
request versus two concrete reservation attempts. An independent review found
the reference ambiguous; the original failed score remains saved. Explicit
request and record IDs resolve the tested contrasts. New pilots use one target
pair per decision, with the intervening source and native definitions; saved
pilots keep their original reader and budget history. This uses more calls than
batched comparisons on long rollouts; shared limits and cached resume still apply.

Reward checks retain native context, instruction order and operation definitions.
Private simulator state stays outside the reading. Missing definitions and
unscanned pages remain coverage gaps rather than negative findings. New CLI
scans use the current reader; resuming a workspace keeps its saved protocol.
Custom checks distinguish a concrete conflict from an unmet end goal, an unseen
helper implementation or an unverified completion claim. Unverified claims stay
unknown; visible contradictions remain findings even in partial records. The
saved comparison identifies the requirement, page and request for inspection.

On six older witness-page references, the current reader matches three exact
labels. Two other pages select independently reviewed earlier evidence of the
same compression and ordering defects. A BOM defect confirmed by 32 isolated
parser checks remains missed on its late witness page and two earlier pages with
the implementation and helpers. Single-question, single-candidate and compact
code probes also miss it; supplying more context alone does not fix this case.
Original references, failed trials and alternate-evidence reviews remain
separate. These are not whole-rollout tests.

Six complete development scenarios exercise the current readers through maps,
execution feedback, approach comparisons, work episodes and behavior measures:
software, simulation, service, multiple agents, and two public airline/telecom
prefixes. The frozen replay contains 36 selected units and 145 responses,
including reused decisions. It verifies integration, not population accuracy.

Context-reset and interleaving regressions cover requested work, action targets,
approach comparisons, recurrence intervals and revision outcomes. Private records
stay outside extraction, context inspection and current relationship readers,
including their missing-source metadata. Matching names or IDs do not carry work
across a reset. These checks do not establish coverage of unseen harnesses, unread
media or every downstream semantic judgment.

## Validation of input delivery

- Authored controls: unmarked parallel-tool conversation with out-of-order results and null `tool_calls`; reasoning generation; environment episode with recorded model text and truncation; verl flat generation export.
- Public non-software control: pinned airline simulation in `tests/fixtures/tau-bench/airline-0.json`, with provenance in that fixture directory.
- Compared normalized events, explicit outcomes, source metrics and graph edges across JSON/JSONL batch import, JSONL follow/replay, updating JSON collection/restart and revisioned outbox delivery.
- A real ephemeral loopback server accepted five distinct worker namespaces, including reused worker-local rollout IDs and restarted outboxes. Evidence matched the source records; ambiguous packets were rejected without adding rollouts.
- Existing marked portable adapter versions remain unchanged, avoiding unnecessary invalidation of saved analysis. This adds recognition of previously unsupported unmarked shapes; it does not recalculate semantic annotations.
- Ambiguous shapes, unsupported portable versions, incomplete token chunks, raw unversioned environment steps and incompatible native-layout selections are rejected.

These checks run on Windows in the current workspace. They are contract and transport validation, not new distributed/GPU trainer, cloud-credential, browser-vision or semantic-classification accuracy validation.

## Upstream basis

- [Gymnasium spaces](https://gymnasium.farama.org/api/spaces/) describe action and observation shapes. Semantic meanings must match the environment and its wrappers; [MiniGrid DoorKey](https://minigrid.farama.org/environments/minigrid/DoorKeyEnv/) documents one example of encoded actions and door states.

- Anthropic's [tool-use](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/tool_use_block.py) and [tool-result](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/tool_result_block_param.py) types define native arguments, result IDs and explicit error status.
- OpenAI's [function calling](https://developers.openai.com/api/docs/guides/function-calling) and [reasoning](https://developers.openai.com/api/docs/guides/reasoning) guides distinguish call IDs, custom inputs, output items and recorded reasoning summaries.

- [verl rollout tracing](https://verl.readthedocs.io/en/latest/advance/rollout_trace.html) distinguishes the agent loop, individual LLM calls and tool evidence. A flat generation export cannot replace the richer history.
- [ART client architecture](https://art.openpipe.ai/fundamentals/art-client/) captures trajectories at the client boundary. This supports integrating at the record-producing loop instead of naming every trainer in the file picker.
- [OpenEnv environment guide](https://huggingface.co/docs/openenv/en/guides/first-environment) exposes actions and observations as an environment contract. Rilldex keeps that contract separate from conversation history and training-use provenance.
