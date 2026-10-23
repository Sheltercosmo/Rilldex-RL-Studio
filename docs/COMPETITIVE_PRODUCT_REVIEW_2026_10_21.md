# Rilldex product comparison and improvement plan

21 October 2026 · Rilldex commit `44dea004a2e071b438767993a5935d66941a6583`

Rilldex should make its existing research capabilities easier to reach, understand, and validate before expanding its feature catalog. Its lightweight installation, durable capture, explicit evidence gaps, and reproducible investigations are useful foundations. The largest adoption gap is between successfully starting the application and obtaining the first useful behavioral finding from a researcher's own rollouts.

The strongest comparison set is W&B plus Weave for training integration, Langfuse and Phoenix for trace inspection, SwanLab for trainer adoption, and Inspect Scout for research on saved transcripts. Goodfire Silico and LangSmith contribute relevant investigation and evaluation workflows. A graph, a custom Python detector, local deployment, or evidence citations alone is not a sufficiently distinctive position.

**Scope and evidence**

The local package was built and installed into a fresh Windows Python 3.12 environment. Its doctor check, packaged web assets, startup, and installed portable-workflow smoke passed. That workflow exercised partial-file handling, duplicate-free resume, portable execution, and saved/overridden UI ports without model calls. This is an installation and workflow check, not a throughput benchmark.

The empty dashboard, setup and source-connection screens, populated overview, and map entry controls were inspected in the browser. Populated data used a copy of an existing saved research fixture plus explicitly synthetic training examples. Browser tooling timed out during later canvas and external-demo inspection; those timeouts are not attributed to either product's performance. Competitor comparisons below use official documentation and selected public source files. Full signed-in vendor workflows, hosted infrastructure, and detector accuracy were not tested. W&B's public tracing SDK is not its complete hosted platform; public vendor documentation is not proof of comparative usability or accuracy.

Selected competitor source snapshots are retained in `research/competitive-audit-2026-10-21/source-snapshots.json`. No product implementation was changed by this review.

**What competitors do that matters for Rilldex**

| Product | Verified product or implementation detail | What to adopt or account for |
| --- | --- | --- |
| W&B and Weave | Weave connects RL trajectories with training metrics. Its public SDK has a run-context helper carrying the active W&B run ID and step, and checks for mismatched projects. | Make correlation metadata automatic where the framework exposes it. Preserve the distinction between a logged step and proven optimizer use. [Tracing](https://site.wandb.ai/traces/), [run-context code](https://github.com/wandb/weave/blob/master/weave/trace/wandb_run_context.py) |
| Langfuse | The example-project entry point lets visitors explore existing data. The setup component distinguishes pending from working instrumentation. Its graph implementation has aggregated and expanded modes, persisted selection, and worker-based layout. | Provide a useful example immediately, verify the first received record, and progressively reveal graph detail. Graph visualization itself is already competitive territory. [Example project](https://langfuse.com/docs/demo), [setup code](https://github.com/langfuse/langfuse/blob/main/web/src/features/traces/TracesSetupPage.tsx), [graph design](https://github.com/langfuse/langfuse/blob/main/web/src/features/trace-graph-view/README.md) |
| Phoenix | Trace-detail code provides a resizable tree/detail split, URL-addressable span selection, remembered panel widths, and a reusable detail view for comparisons. Another component turns a span into a dataset example. | Preserve inspection context while moving between cases and turn a finding into a reusable research case. Rilldex already has deep links; this is a consistency and workflow improvement. [Trace details](https://github.com/Arize-ai/phoenix/blob/main/js/app/src/pages/trace/TraceDetails.tsx), [dataset action](https://github.com/Arize-ai/phoenix/blob/main/js/app/src/pages/trace/SpanToDatasetExampleDialog.tsx) |
| SwanLab | verl exposes a logger configuration; the Transformers callback handles rank-zero logging, metric names, configuration, evaluation, and checkpoint metadata. | A researcher should not need to design an ingestion protocol to get basic run context. Keep advanced metadata available without making it the first interaction. [verl integration](https://docs.swanlab.cn/en/guide_cloud/integration/integration-verl.html), [callback code](https://github.com/SwanHubX/SwanLab/blob/main/swanlab/integration/transformers.py) |
| Inspect Scout | Scanners operate on saved transcripts, with custom logic, evidence references, resumable jobs, and a results viewer. Public source connectors include Weave, Phoenix, and LangSmith. Validation supports labeled cases and development and held-out test splits. | This is a direct research-workflow competitor and an interoperability model. Existing trace stores are an input channel; validation belongs in everyday use. [Workflow](https://meridianlabs-ai.github.io/inspect_scout/), [connectors](https://github.com/meridianlabs-ai/inspect_scout/blob/main/src/inspect_scout/sources/__init__.py), [validation](https://meridianlabs-ai.github.io/inspect_scout/validation.html) |
| LangSmith | Annotation queues organize review around rubrics, progress, individual cases, and pairwise judgments. Evaluation comparisons highlight regressions and improvements. | Make a researcher's next decision obvious: review the suspicious case, compare it with a reference, or retain it for later evaluation. [Queues](https://docs.langchain.com/langsmith/annotation-queues), [evaluation](https://docs.langchain.com/langsmith/evaluation-types) |
| Goodfire Silico | Its documented workflow moves from a research question through a plan and experiment to a report with source links. Access requires an authorized account and Lab. Its LLM offering includes activation- and action-based monitoring. | Learn from the question-to-report workflow. Do not equate its infrastructure or internal-model access with a simpler saved-rollout tool, or claim a detection winner. [First experiment](https://docs.goodfire.com/getting-started/), [access](https://docs.goodfire.com/quickstart/), [LLM product](https://www.goodfire.com/language) |

**Installation is a strength to preserve, with one important handoff problem**

Rilldex's core wheel declares no mandatory runtime dependencies and bundles the web assets. A user can inspect source data without a GPU or model credentials. Its CI configuration already covers installed wheels on Windows, Linux, and macOS across Python 3.11–3.13; this review ran the Windows path only. [Packaging](../pyproject.toml), [existing CI](../.github/workflows/portable-smoke.yml)

Phoenix also provides a local Python installation. Langfuse's current Compose file runs a web service, worker, PostgreSQL, ClickHouse, Redis, and MinIO, followed by account/project setup. This gives Rilldex a simpler local deployment footprint than that Langfuse configuration, without establishing a capability or performance advantage. [Phoenix installation](https://arize.com/docs/phoenix/self-hosting/deployment-options), [Langfuse deployment](https://langfuse.com/self-hosting/local), [Compose code](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml)

The handoff problem is semantic setup. The documentation provides a chat-completions candidate adapter under `examples/`, but that script was absent from the installed distribution. The documentation correctly describes using it from a checkout; nevertheless, someone who followed the main install command must acquire an additional file or implement an adapter to reach the distinctive feature. Candidate generation and Jev decisions are separate roles, with separate configuration and request budgets. [Model setup](MODEL_SETUP.md), [sample adapter](../examples/chat_candidate_proposer.py)

**Prioritized improvements**

P0 means before the next broad researcher trial. P1 means the next focused product iteration. P2 means follow demonstrated usage and measurement. These priorities are judgments about likely adoption value, not measured conversion rates.

| Priority | Improvement | Completion criterion |
| --- | --- | --- |
| P0 | A guided first session with an included example | A new user reaches one meaningful, source-backed finding without credentials or reading the integration guide. |
| P0 | A complete model setup path in the installed package | A user configures a supported candidate endpoint and decision provider, checks readiness, and starts a bounded pilot without locating repository scripts. |
| P0 | A clear import-to-analysis handoff | Every import shows received data, missing capabilities, and the next available action, then opens a relevant rollout. |
| P0 | Capability and readiness shown where features are used | A user can tell whether a view is ready, needs metadata, needs annotations, or is unvalidated for their integration. |
| P1 | Research-oriented navigation and progressive map detail | Users can answer a defined feedback/recovery question without learning the full internal vocabulary. |
| P1 | Existing-tool import and validated trainer recipes | One supported W&B/Weave input path and one native trainer path work on independently supplied research data. |
| P1 | Case-level comparisons | Researchers can compare matched tasks across checkpoints while retaining reward, version, source, and missingness context. |
| P1 | Validation integrated into detector use | Users can retain labels, apply a frozen validation set to a new detector version, and inspect disagreements. |
| P1 | Complete-run telemetry views | Long runs retain an overview of the full interval while allowing precise inspection of raw points. |
| P1 | A readable research handoff | A colleague can open a findings summary and inspect its evidence without reconstructing the author's workflow. |
| P1 | A documented versioned release path | Installation and model setup work from a pinned release outside the checkout. |
| P2 | Targeted frontend and API maintainability work | The most-used inspection workflow has stable contracts and focused interaction tests; measured bottlenecks guide optimization. |

**1. Make the first screen a choice of useful tasks**

The fresh dashboard shows zero rollouts, zero trainer logs, zero behavior maps, eight active monitor definitions, empty measure cards, and an Add monitor action. This is truthful but gives the user work before demonstrating value. The visual styling is already consistent; the more consequential issue is information hierarchy.

Use an empty-workspace welcome panel with three choices: Open an example, Import saved rollouts, and Connect a running experiment. Once data exists, replace it with the current overview. Show a compact status progression: data received, source inspectable, behavior analysis ready. Distinguish enabled monitor definitions from monitors that have produced results. An included example should explain one question, show its answer and counterexamples, and offer a direct path to the user's data. Clearly label authored demonstrations and public recorded traces. Reuse the existing fixture and snapshot mechanisms rather than building a separate demo application. [Current dashboard](../tracker/web/monitoring.html), [product-tour fixture](../scripts/product_tour_fixture.py)

**2. Finish the installed semantic setup workflow**

Ship the candidate adapter as an importable installed module or generate it through a setup command. Provide named connection presets, explicit model identities, an endpoint check, and a contract check. Keep advanced custom transports available. A custom transport should retain its own protocol and cache identity rather than impersonating the built-in decision model.

Offer a small pilot over a user-selected sample before a larger scan. Show candidate and decision call counts separately, cached work, incomplete rollouts, and the reason for a blocked stage. Current request/byte ceilings are useful; do not present them as currency estimates. If reliable provider usage and pricing are available, add a labeled estimate. Otherwise report actual usage and keep the spending limit explicit. Existing cache, restart, and budgeting behavior should remain the underlying mechanism. [Model setup](MODEL_SETUP.md), [continuous observation](CONTINUOUS_OBSERVATION.md)

**3. Turn import and scan setup into a continuous workflow**

Data & workflows already offers output detection, previews, import, directory watching, generated deployment commands, and delivery health. Consolidate these into a beginner path: select source, preview, confirm mapping, import, inspect. Default a safe producer identity and allow editing it under advanced options. Explain identities when needed for resume; avoid making users invent them before seeing a trace.

After import, show actual counts and capabilities: source events present, training coordinates missing, semantic analysis not yet run. Offer the next valid action. Reward scan setup currently generates preview/run/status commands and explicitly does not execute them. Keep this headless path, but add an optional local managed-worker action with an explicit budget and resumable status. A remote collector should display where its worker must run. [Connection UI](../tracker/web/connections.html), [scan setup](../tracker/web/reward-checks.js)

**4. Make readiness and compatibility part of the product**

The integration matrix carefully distinguishes native execution, export parsing, replay, and untested hooks. Surface the relevant distinction on each framework card. A successful parse must not imply complete behavioral evidence or verified optimizer-use attribution.

For each analysis, display a small readiness summary with actionable missing requirements. For example, recovery analysis can require a comparable criterion and recheck, whereas source inspection needs neither. Preserve unknown, unscanned, out-of-scope, and unavailable states. Move long methodological explanations into expandable details while leaving the limitation that changes interpretation visible. This improves clarity without weakening the evidence contract. [Integration coverage](INTEGRATION_COVERAGE.md), [recovery requirements](RECOVERY_WINDOWS.md)

**5. Organize inspection around a research question**

The current map offers Unit map, Rollout story, Plans & attempts, Work path, card-text modes, and multiple connection filters. These are useful analytical views, but the first-time user has to infer which one answers their question. All relationships is the default connection mode in the active map code.

Add question presets such as Follow a failed check, Inspect a retry, Compare attempts, and Review a suspicious reward result. Each should select the relevant view and relationships while preserving access to the full graph. Start with a readable summary and a selected evidence path; expose all edges on demand. Use short user-facing terms, with exact internal definitions in the inspector. Do not imply that a recorded plan is a completed action or that a temporal association proves causation.

Rilldex already supports selected-unit and selected-edge URLs, an evidence inspector, search, zoom, and alternate views. Improve the defaults and continuity rather than rebuilding these controls. [Active map route](../tracker/server.py), [map UI](../tracker/web/rollout-map.html), [map state](../tracker/web/rollout-map.js)

**6. Adapt to the researcher's existing tools**

Start with a read-only import from W&B/Weave exports or APIs, preserving external run IDs, trace IDs, source links, model/checkpoint identity, and timestamps. Then add one further source based on pilot demand, such as Phoenix, LangSmith, or ATIF. Inspect Scout's explicit connector modules show that this is already an expected workflow in the research category.

Treat OpenTelemetry as a way to reuse recorded execution information, not as a source of missing semantic facts. A span hierarchy does not establish which feedback caused a revision. Similarly, a logged W&B step is useful correlation context but is not an optimizer consumption receipt. Native trainer recipes should capture available context automatically and identify what remains unavailable. Publish the exact versions exercised and test interruption/resume in a real GPU workflow when that environment is available. [Trainer telemetry](TRAINER_TELEMETRY.md), [coverage matrix](INTEGRATION_COVERAGE.md)

**7. Make checkpoint comparison reach individual cases**

The current aligned curves, shared intervals, raw values, smoothing, and update inspector are valuable. Extend the common path from selecting a changed interval to comparing representative rollout cases. Pair the same task across checkpoints when task identity supports it; show an unmatched label otherwise. Keep task, reward definition, environment version, checkpoint, and evidence coverage beside the comparison.

Offer filters for improved, regressed, unchanged, and unresolved outcomes. Let a researcher inspect changes in action sequence, failed checks, revisions, and verification results. Show denominators and distinguish changed case composition from changed behavior. Uncertainty estimates should respect the sampling unit and repeated tasks rather than treating every action as independent. This would make the behavioral structure useful in a concrete RL analysis instead of requiring the researcher to assemble the comparison manually.

**8. Extend the existing human review into reusable validation**

Rilldex already freezes review samples, hides a prediction until a judgment is saved, retains citations and label revisions, and reports false positives, false negatives, unresolved cases, and scope disagreements. The monitor dialog exposes Review all outcomes. This is an existing strength, not a missing feature. [Review implementation](../tracker/web/measurement-review.js), [review contract](MEASUREMENT_REVIEWS.md)

Make that path visible from detector results and consolidate compatible reviews into named validation sets. Add explicit development and held-out splits, version-to-version comparison, and a disagreement browser. Keep labels separate from model predictions and source corrections. Report coverage alongside accuracy; a detector that abstains or fails to inspect many cases should not look excellent merely because its small decided subset is correct. Built-in diagnostic protocols and custom binary monitors may require different review frames, so advertise supported validation routes explicitly. Use existing frozen samples and append-only labels as the foundation.

**9. Show the whole training run without loading every raw point**

The telemetry snapshot currently returns the latest 1,000 records and at most 64 series, with truncation information. The populated dashboard visibly showed 1,000+ logs. This is an honest bound, but a full-run analysis can require earlier behavior that falls outside it. [Snapshot implementation](../tracker/trainer_telemetry.py)

Add server-side time/step range queries and overview aggregation, then fetch raw values for the selected interval. Preserve extrema or event markers so a short spike does not disappear into an average. Show full-run versus selected-window counts and distinguish plotted points from stored records. Acceptance should include a long synthetic run with an early anomaly and a late anomaly; both remain discoverable, and exporting a selected range reproduces its recorded values. Raising the browser cap alone is not a satisfactory solution.

**10. Package findings for a collaborator**

Portable workspace snapshots, frozen investigations, exported evidence, and code-based analysis already exist. The next useful addition is a readable report view over those records: research question, selected cohorts, finding, counterevidence, unresolved cases, detector/model versions, and links to exact cases.

Offer a local HTML or similar review package alongside the existing machine-readable export. A lab colleague should be able to read the conclusion before navigating the full application. Reopening must not trigger new model calls or silently replace the original evidence. A shared hosted service can wait until demand warrants access control and operational work. [Investigation export](../tracker/web/investigate.js), [workflow smoke](../scripts/workflow_smoke.py)

**11. Improve release distribution and the first-use documentation**

The README's default installation uses a Git URL. Offer a documented pinned release and downloadable wheel; consider a package-registry release when ready. Keep a separate collector environment as the recommended route when trainer dependencies conflict. The existing cross-platform wheel CI is a good foundation, so extend it to the complete installed model-setup example instead of creating a parallel installation system.

Structure the main guide around four outcomes: inspect an example, import ten rollouts, run one bounded check, and compare two checkpoints. Keep deployment and schema reference material linked from those steps. State clearly which stages need no model, which use Jev, and which also need a candidate model. Include a concrete expected result after each command. Avoid letting a successful launch stand in for successful analysis.

**12. Improve code boundaries where they support these workflows**

Rilldex's dependency-free server and local SQLite are appropriate for its present use. Competitors' React, GraphQL, ClickHouse, and worker stacks solve different scale and collaboration requirements; adopting them wholesale would introduce substantial installation and maintenance cost.

The active map page loads many cooperating scripts, and its controller manages selection, evidence, graph layers, review, and view state. Isolate one stable map-state contract and a few high-value view models before extending the UI. Derive or validate frontend response shapes against existing versioned backend contracts. Add focused interaction checks for importing a case, opening exact evidence, switching views, returning to the same selection, and restoring an exported investigation.

Profile large traces before choosing virtualization or worker-based layout. Langfuse's graph design shows a useful worker/cancellation boundary, but its own README still lists node virtualization as future work; do not assume every competitor has solved every large-graph problem. No comparative performance claim is justified by this review. [Rilldex map controller](../tracker/web/rollout-map.js), [Langfuse layout design](https://github.com/langfuse/langfuse/blob/main/web/src/features/trace-graph-view/README.md)

**A practical sequence for the next researcher trial**

First deliver the included example, installed model adapter, import handoff, and readiness states as one complete path. Next deliver one real trainer integration and one existing-tool import, together with case comparison and detector validation. Then improve report sharing and full-run telemetry, guided by the pilots that encounter those needs. Keep performance and architectural changes tied to measured constraints.

Use a small set of observable outcomes to assess these changes: time to the first supported finding, percentage of users reaching it without help, incorrect conclusions from missing evidence, setup failures, time to review a detector disagreement, and successful reproduction by a second researcher. Record trial conditions and preserve failures. The product promise should be demonstrated on researchers' actual experiments, not inferred from the number of features or the appearance of a graph.
