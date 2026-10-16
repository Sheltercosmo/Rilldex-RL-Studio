# Value predictions and returns

Training health automatically shows this view when bound `value-observation/1` records arrive. It supports token, turn and state positions independently of the RL framework. No metric thresholds or chart formulas need configuration. Versioned settings readers can identify a critic-based component; arbitrary producers can declare the same contract explicitly.

Two roles remain separate: **Policy advantage baseline** observes the values used to construct policy credit; **Value-model fitting** observes inputs to the critic loss. The latter does not establish a policy update. Native model/version, target kind, input digest and increasing position indexes remain inspectable. Different roles, units, models or definitions become separate selectable series automatically. Values from different versions of the same model can be followed over training.

| Display | Calculation and boundary |
|---|---|
| Value prediction error | Mean `(value − return)²` over eligible recorded positions; not clipped/scaled trainer loss. |
| Mean prediction bias | Mean `value − return`; complements variance measures that ignore constant bias. |
| Explained return variance | `1 − Var(return − value) / Var(return)`; population variances, no epsilon, negative values retained. Constant returns are unavailable. |
| Within-sample share of value variation | Sum of squared deviations from each sample-use mean divided by sum of squared deviations from the pooled mean. Constant values are unavailable. Low values are a descriptive inspection signal, not a flattening diagnosis. |

Cards summarize the selected retained history. Curves recompute at each recorded learner step. Every eligible position counts once per use; repeated use counts again. Backward and optimizer stages remain separate. Producers must namespace actor and critic records separately when their learner-step clocks are incomparable. These are capture-population measurements, not estimates that correct for missing shards or selective logging. No averages of per-shard variances or per-sample errors replace pooled statistics.

The observation's mask can differ from the actor's loss mask, especially with sparse value supervision or turn-level credit. Neither is substituted for the other. The `definition` must distinguish reward transforms, target estimator, discount/bootstrap/truncation rules, normalization and the sampling/position scope. A changed definition creates a new series; a changed training recipe creates a new use stream. A prepared vector alone is not a completed-use receipt.

```python
from tracker.value_observations import observation

# At the native loss/credit boundary, copy the exact detached inputs.
# No new model forward, return reconstruction, or GAE recomputation.
captured = observation(
    component="rl-policy",  # exact critic-based component in use recipe
    definition=native_value_definition,
    unit="token", role="value_fit", target_kind="lambda_return",
    value_model=value_model_id, value_version=value_version,
    input_digest=native_input_digest,
    positions=native_position_indexes,
    mask=value_mask.detach().cpu().to(dtype=torch.int64).tolist(),
    values=predicted_values.detach().cpu().tolist(),
    returns=return_targets.detach().cpu().tolist(),
)
# After native backward succeeds, attach to that sample's existing use receipt:
use_record["data"]["value_observation"] = captured
use_record["data"]["recipe"] = actual_use_recipe_reference
outbox.log_training(experiment, [use_record])
```

Each observation is one sample-use vector, not a batch tensor. Producers own exact sample identity and position semantics. Copying GPU tensors synchronizes and has a cost; the CPU control does not establish production overhead. Framework hooks must preserve distributed identity, padding, masks, actor/critic clocks and noninterference before claiming native integration.

Select a chart point to inspect its sample uses, then **Inspect value positions** for paired predictions/targets and inclusion flags. The table pages through 50 positions; exports retain the full vector. Mixed definitions are never silently pooled. Missing or late recipe bindings remain visible; arrival of the exact declaration can resolve the view without rewriting the observation.

Validation includes five settings-reader families, boundary/numerical tests, and four executed OpenRLHF CPU loss-kernel controls. This is **not a full native OpenRLHF trainer adapter**. See the [source review and audit](../research/value-observations-2026-10-12/README.md).
