# Register reusable analysis operations

Implemented 11 October 2026. The investigation executor now uses registered deterministic operators for parameter validation, dependency validation, source binding and execution. Monitor setup reads the same registered observer contract, and monitor plan construction expands declared dependency slots. This is the analysis foundation for portable behavior investigations; it does not run or validate automatic semantic extraction.

## Responsibilities

| Module | Responsibility |
| --- | --- |
| [analysis_registry.py](../tracker/analysis_registry.py) | Operator, parameter, dependency and source-binding contracts; trusted registration and dependency-plan expansion |
| [analysis_operations.py](../tracker/analysis_operations.py) | The 18 built-in registrations and concrete materialization/reduction behavior |
| [investigation_plans.py](../tracker/investigation_plans.py) | Common DAG/source validation, execution, cache integrity and immutable receipts |
| [analysis_contracts.py](../tracker/analysis_contracts.py) | Built-in meaning descriptions, common evidence inventory and discovery of current registered contracts |
| [analysis_metrics.py](../tracker/analysis_metrics.py) | Versioned measurement definitions and reducers over operator outputs |

An operation answers a typed analysis question. A measurement defines how its output becomes a rate/count and evidence cases. A domain profile supplies domain meaning. An investigation recipe composes these. Registering an operation does not automatically define a valid metric, renderer or semantic observer.

## Operator declaration

Trusted Python initialization can register an operation before serving requests. The browser sends only a registered name and declarative parameters. There is no HTTP code upload, import-path execution or automatic plugin discovery.

```python
from tracker.analysis_operations import REGISTRY
from tracker.analysis_registry import Operation, Parameters
from tracker.analysis_contracts import projection

def recorded_events(context):
    return {
        "run_id": context.run["id"],
        "events": len(context.run["events"]),
    }

REGISTRY.register(Operation(
    name="example_recorded_events",
    version="example-recorded-events/1",
    contract=projection(
        "Recorded events", "How many events were captured?",
        "captured event", [],
        "Counts recorded events, not effort or semantic activities.",
        "Example only; validate against the intended producer.",
        observer="source",
    ),
    parameters=Parameters(
        ("run_id", "source_hash", "graph_id"),
        identifiers=("run_id", "source_hash", "graph_id"),
    ),
    execute=recorded_events,
))
```

This example illustrates the extension mechanism, not a new recommended dashboard metric. The registry rejects duplicate names, missing dependency registrations, unsupported source bindings and declarations requesting model calls. Callbacks are trusted application code; the deterministic declaration is not a sandbox for malicious installed extensions.

## Dependencies and evidence binding

A fixed dependency declares its producer operation and a stable slot name. The current recovery operation declares one work_state input named recorded_state, inherits that input's rollout and binds its own evidence graph. The common engine verifies that the graph and dependencies belong to the same source revision before executing any node.

Population comparisons declare a homogeneous variadic input operation. They reject duplicate rollout contributions. Definitions requiring complete focus/reference membership declare that explicitly; existing subset-compatible comparison definitions retain their prior rules.

Registry.projection_plan() expands fixed dependency slots using supplied source bindings. It preserves existing monitor node names and parameters, including recovery's two-node plan. Population plans still require explicit cohorts. Current composition supports per-rollout operations and terminal population reductions; general population-to-population programs and automatic semantic jobs are further work.

Capability checks remain structural. Common known capabilities use the existing evidence inventory. Unrecognized requirements appear as missing; registration cannot turn them into observed evidence. Each operator still validates the detailed evidence and retains its own opportunity, unknown and censoring semantics.

## Identity and correction

Cache keys remain operation name/version, explicit parameters and hashes of upstream outputs. Descriptor presentation and setup metadata are outside measurement identity. Old output graphs, monitor definitions and saved receipts keep their identifiers.

Changing behavior requires a new operation version and, where applicable, a new measurement definition. Changing guidance alone does not. The exported investigation_plans.OPS view remains available for existing version-pinned consumers; register operations through the registry rather than adding names to that compatibility dictionary.

Every source is checked even for a cache hit. Callbacks receive copies of parameters, upstream outputs and evidence so accidental mutation cannot rewrite a preceding receipt or the submitted plan. Returned outputs must be JSON objects. Stored-source or cached-output corruption fails explicitly.

This registry does not complete unit correction or its full downstream invalidation path. Existing immutable relationship/work corrections continue to flow into new graph-bound result identities.

## Validation and remaining work

[The migration audit](../research/operation-registry-2026-10-11/README.md) freezes all 18 old operations over public/development observations and authored recovery controls, then recomputes them in fresh databases. New extension tests exercise a source operation and a dependent operation without adding executor branches.

The next product slice carries the same investigation population, clock, observer and comparison through training-selection charts and rollout review. Independently validated semantic observations, inference scheduling, arbitrary new capability probes, a broader metric extension interface and a second native trainer remain separate delivery work.
