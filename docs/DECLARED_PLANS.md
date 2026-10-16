# Structured task-list declarations

Current version: `declared-plan-history/2`, 11 October 2026. This source operator records what an agent puts in a supported task-list tool call. It supplies readable targets and status histories without a model call. It does not classify prose as Plan, change primary activity tags, infer work identity, assert that a tool accepted a call, or verify that a task was completed. Saved v1 measurements remain replayable with their original graphs and definitions.

## Capture contract

| Profile | Native call | Required item contents | Canonical reported status |
| --- | --- | --- | --- |
| `langchain-todos/1` | `write_todos({todos: [...]})` | `content`, `status` | pending / active / completed |
| `openhands-tasks/1` | `task_tracker({command: "plan", task_list: [...]})` | `title`, optional `notes`, `status` (documented default: todo) | pending / active / completed |
| `openhands-codeact-tasks/1` | Same native call, with a recorded schema requiring IDs | `id`, `title`, `status`; optional `notes` | pending / active / completed |

These are whole-list declarations. OpenHands `view` is not a declaration. The profiles use the inspected [LangChain schema](https://github.com/langchain-ai/langchain/blob/d9b8dd5183280a1811a0d21e304e05db8c06c90c/libs/langchain_v1/langchain/agents/middleware/todo.py) and [OpenHands schema/executor](https://github.com/OpenHands/software-agent-sdk/blob/3934349da2db0433238621542173a00a8af7439c/openhands-tools/openhands/tools/task_tracker/definition.py). Profile revisions identify the source specification used by this observer, not the installed version of the recorded agent.

The operator consumes canonical action events, so the same rules apply after chat-message or ATIF import. It requires structured arguments, agent attribution and an uncopied native dispatch. Tool-like prose is not parsed into an action. Extra custom fields, unsupported statuses, malformed payloads, unusable item text and oversized lists remain issues rather than guessed declarations. A matching tool name does not certify its implementation; customized tools need their own validated profile.

The older [OpenHands CodeAct 0.54.0 schema](https://github.com/OpenHands/OpenHands/blob/4aae68ae53477d05010a509f1f1e3f02e61b1831/openhands/agenthub/codeact_agent/tools/task_tracker.py) requires native task IDs. This is a distinct profile from the newer software-agent-sdk schema above. It is selected only when the captured tool contract explicitly requires a string `id` alongside `title` and `status`. A payload containing an ID without that contract is not sufficient evidence for this profile.

The `nebius-openhands/1` adapter imports complete native rows from the public SWE-rebench OpenHands dataset, preserving message content, serialized and decoded arguments, tool schemas, call/result bindings and original source pointers. Optional Parquet `tool_calls: null` is normalized only on this native path. The historical `nebius` selector also recognizes complete native rows; incomplete structured-chat rows fail instead of silently becoming empty events. The producer's `resolved` field and patch/evaluation data remain outcomes, outside agent-visible messages. Dataset position never supplies a training step.

## Graph and measurement meaning

Snapshots and items are typed graph objects. They retain native status, profile revision, event ID and argument pointer. `declared_plan_at` attaches a list to its dispatch, `contains_declared_plan_item` attaches its items, and `previous_plan_declaration` and `updates_declared_plan` retain successive declarations. `retains_declared_plan_text` connects unique exact-text items; the identified CodeAct profile uses `retains_declared_plan_id` and separately records changed titles. The raw source graph stays unchanged. Auxiliary objects do not become fake activity cards; the existing map renders the original dispatches, a connecting line and readable issued lists in the inspector.

Comparison lanes are trajectory + context + actor + tool. This prevents unrelated agents or list tools from being merged. Neither source-order position within a parallel batch nor a repeated name establishes semantic item identity.

Three monitors are available under **Add monitor → analysis measure**, using the **source** observer:

- **Structured plan declarations**: valid recorded writes, including explicit empty lists. No supported writes gives unavailable, not a claim that no planning happened. Invalid payload counts remain in coverage.
- **Reported-complete items reopened**: each completed item in a declaration has one opportunity at the next valid list declaration in its lane. Unique native ID with unchanged title, or unique exact text in an ID-less profile, establishes the comparison. Retained pending/active status is positive; retained completed status is negative. Renamed, dropped, duplicated, unordered, profile-changing, or interrupted-by-invalid-write comparisons are unknown. The numerator is positive opportunities; the denominator excludes unknowns, which are also reported. A final completed item without another declaration has no follow-up opportunity.
- **Initial task-list entries reported complete**: each entry in the first captured supported list per lane is one opportunity. A completed status is positive; pending/active is negative. Earlier malformed declarations or ambiguous ordering make the entries unknown. Missing or empty initial lists provide no denominator. This distinguishes the initial recorded status; it does not establish when the agent planned or performed that work.

Per-rollout values, pooled opportunity bins, cohort filters, immutable receipts and saved review samples use the existing monitor engine. The reopened measure describes reporting behavior. A rise is an investigation lead: it cannot distinguish premature completion reports, discovered regressions, changed requirements or incorrect tracking on its own.

Review packets show structured arguments for whole action events and identify the exact source entry when several cases share one list call. This subject is checked against the captured argument pointer and title; it is not the predicted monitor answer. Partial text windows do not expose additional argument fields. Text citations still identify recorded text spans; they are not JSON-pointer citations. The original source event remains available to audit the arguments.

## Validation and next boundary

The [original authored controls](../research/declared-plans-2026-10-11/README.md) cover schemas, state transitions, isolation, unknowns and receipt replay. The [public transfer audit](../research/declared-plan-transfer-2026-10-11/README.md) additionally reconciles all 1,211 calls and 1,191 returned responses across 20 real captures. Four captures contain ten list declarations. Two first lists already report most or all entries complete, demonstrating why list existence alone cannot establish prospective planning. These are evaluation traces with no recorded training clock, not a representative prevalence sample. No independent semantic accuracy or task-success gain is established.

This is an optional input layer where structured declarations are captured. Free-text plans still need validated extraction. Connecting declared steps to actual attempts and checks requires independent source-bound correspondence; exact text equality or task IDs must not substitute for that layer.
