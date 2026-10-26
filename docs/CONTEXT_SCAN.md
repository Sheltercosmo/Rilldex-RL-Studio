# Context scan

Select an agent step in the **Unit map**, then choose **Scan context**. The matrix shows the input mixture in recorded order. Select a tile or category to read its source; use the arrows to move between blocks. **Export scan** saves the composition and inspection cues.

Colors distinguish instructions, agent history, tool results and definitions. Explicit `context_kind` values also identify `summary`, `memory` and `retrieval`. Area measures characters, including serialized structured content—not tokens or attention.

Weave imports use the selected call’s captured `inputs`. Other adapters show the earlier history in the same trajectory, labeled **Recorded history**. To inspect the exact request, add a snapshot to the imported document:

```json
{
  "context_snapshots": [{
    "step_pointer": "/messages/5/content",
    "messages": [{"role": "user", "content": "Fix the parser"}],
    "tools": []
  }]
}
```

Use the selected step’s native source pointer and the actual messages/tools sent for that request. Repetition, oversized blocks and changes between captured requests are inspection cues. They do not establish why an agent failed.

**Review this block with Jev** sends the block, recorded instructions and selected action to the server-configured Jev model. Set `JEV_API_KEY` on the server. Reviews are cached against the exact input, limited to 60,000 characters, and identify candidate concerns rather than causal conclusions.
