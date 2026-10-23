# Weave import

Import a full calls export through **Data & workflows → Import files**, or:

```sh
rilldex --db study.sqlite import calls.jsonl --format weave
rilldex --db study.sqlite serve
```

Accepts native JSONL call records, a JSON array, or `{ "calls": [...] }`. Export child calls too. Calls group by project and trace ID; identical snapshots deduplicate even when file order changes. Conflicting versions of one call require a fresh snapshot export.

Later exports update the same rollout through saved revisions. Earlier snapshots remain inspectable without increasing the current rollout count. Reimporting an older snapshot does not move the current version backwards. Correcting a finished call requires an explicit ingestion revision.

The source map retains nesting, call IDs, source links, exceptions, unfinished calls and available W&B run/step context. OpenAI chat-completion and Anthropic message outputs are decoded for LLM calls. Input history stays copied context; unknown payloads stay source records. Marked scorer subtrees are excluded from model behavior counts. Arbitrary scores, parent relationships and logging steps do not become reward, semantic causality or optimizer-use evidence.

Saved exports only: no live account synchronization or object-reference fetching. A root call does not prove all children were exported. Separate model calls and completion choices retain separate contexts; cross-call behavior relationships require further analysis.

Validated against the [native call schema](https://github.com/wandb/weave/blob/25398c8b06a027f2333e2635b969169c6940982d/weave/shared/trace_server_interface.py), [SDK serialization](https://github.com/wandb/weave/blob/25398c8b06a027f2333e2635b969169c6940982d/weave/trace/call.py), and a recorded public tool-call payload. Local tests cover file/CLI/HTTP import, grouping, graphs, source pointers and duplicates. A signed-in Weave workflow has not been tested.
