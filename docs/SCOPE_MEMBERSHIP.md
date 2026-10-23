# Source qualifications

Extract work contents and their qualifications from one saved semantic unit using a local/API candidate model and Jev. Saved results appear in the unit inspector and native analysis tables. Base units and graph relationships stay unchanged.

```python
from rilldex import Workspace

workspace = Workspace("study.sqlite")
result = workspace.extract_work_contents(
    GRAPH_ID, UNIT_ID, "./content-pilot",
    candidate_calls=4, decision_calls=12, input_bytes=100000,
    relations=True,
)
print(result["saved"]["map_url"])
saved = workspace.work_contents(GRAPH_ID, UNIT_ID)
attachments = workspace.table("work_attachments")
```

[Configure the models](MODEL_SETUP.md) first. New workspaces separate an operation from its stated purpose while keeping the base activity unit intact. Generation supplies contents, then qualification expressions; Jev selects attachment across all contents. The generator no longer proposes scopes. A check retains its question, and proposed work remains distinct from execution.

New extractions keep conditions separately addressable, retain offered work, and avoid duplicating a broad activity heading alongside its concrete constituent actions. Existing directories keep their saved protocol automatically.

Limits are lifetime totals for the directory. Resume to reuse saved work and its original extraction protocol; raise limits to continue. One schema/citation repair per generation stage is allowed within the same budget. Original completions remain inspectable. `result["status"]`, usage and pending feature IDs show progress; `bound` or `review` can be `None` before their stage completes. Provider failures without a saved response require an explicit retry. Reported tokens remain separate from payload bytes.

The unit panel refreshes saved progress every five seconds. `content_extractions`, `work_contents`, `work_attachments` and `work_content_relations` support SQL, Python and research exports without model calls. Join using `extraction_id`; content and feature IDs are local to that extraction. Pending and unresolved decisions remain separate from negative decisions. Each directory has one current record; exports freeze that record. Generated items and selected relationships remain experimental interpretations, not verified execution or whole-map accuracy.

`relations=True` adds purpose, stated order, condition and response-to checks. Candidate pairs are constructed in code; no extra generative call is needed. New extractions inspect temporal wording on separate pages, distinguishing sequence from coordination, condition and purpose. One selection supplies both order directions. Each page retains the full unit text and uses raw argmax, with at most 32 questions. Enable this on an existing directory to reuse its contents and attributes; later resumes remember the setting. The CLI equivalent is `--relations`. Relationship calls share the same lifetime budget; old directories retain their protocol.

For a saved packet, use `python -m rilldex.scopes packet.json UNIT_ID ./content-pilot --candidate-calls 4 --decision-calls 12 --input-bytes 100000`. Python accepts custom transports and `max_repairs=0` to disable repair. `direct_arguments=False` replays the earlier attachment protocol; changed protocols require a separate directory.

Optional syntax assistance: install `rilldex[nlp]` and a local spaCy pipeline, then add `--spacy-model en_core_web_sm`. Python accepts a saved parser record through `syntax=`. Syntax supplies token locations and dependency evidence; it does not override Jev’s raw argmax. No pipeline downloads occur automatically, and the core installation still needs no runtime dependencies.

## Current evidence

The [cross-domain trial](../research/cross-domain-work-2026-10-21/README.md) covers seven public software, airline and retrieval passages plus four controls. The latest inventory passed required-content, count and mode checks after citation repair. A [temporal follow-up](../research/local-order-2026-10-22/README.md) corrected the remaining unsupported ordering link and matched expected temporal links across 17 development passages. Neither study establishes independent accuracy or whole-map validity.

Earlier outputs and failures remain replayable: [content granularity](../tests/fixtures/scoped_content_granularity.json), [scope membership](../tests/fixtures/scope_membership.json), [staged extraction](../tests/fixtures/scoped_workflow.json) and [local relationships](../tests/fixtures/local_work_relations.json). Scope selection cannot recover omitted contents or guarantee their types.

Integration checks cover cached resume across protocol versions, partial progress, SQL/export, desktop/mobile navigation and an installed wheel outside the checkout. These checks use authored responses; live Jev trials are reported separately with exact usage and retained errors.
