# RL method adaptation

The product uses a common evidence model and small native configuration readers. Monitoring depends on the actual credit estimator, policy objective, loss reduction, filtering and execution schedule; a framework or method name is insufficient.

Current settings readers: **TRL, verl, AReaL, NeMo RL, OpenRLHF and slime**, at the revisions in `tracker.training_setup.PINS`. Config reading does not establish complete native capture support. Unknown revisions remain reviewable without publishing a standard recipe.

**verl-agent / GiGPO** is now a separate pinned reader. It does not inherit the upstream verl interpretation: episode groups, trajectories and anchor-state groups have different roles. Its setup automatically recommends episode baseline/length weighting, state-group coverage and agreement between episode and state advantage terms. State-specific recommendations are omitted when the effective state weight is zero. Similarity grouping, dynamic sampling and GSPO ratios are read independently. PF-PPO reweighting and unverified versions require review. See [native controls and public export evidence](../research/gigpo-adaptation-2026-10-12/README.md).

File preflight calls flattened input/output rows **generated responses**, and counts **records**. These may be individual turns in longer episodes. Quoted history remains context; no episode IDs, execution links, success or complete-episode count is inferred. This presentation change does not rewrite existing imports or annotations.

Slime also has a [paired native debug-file import](SLIME_DEBUG_IMPORT.md), which retains sample joins, token context and native training fields through the existing outbox and training-sample view. Its CPU writer controls validate file semantics, not a complete distributed trainer or optimizer-use capture.

**TRL A*-PO** uses an explicit trainer selector (`trainer="a2po"`) and a separate `trl-a2po-setup/1` settings contract. Cached reference baselines and sequence regression do not inherit online-group or PPO-clipping interpretations. Eleven examples now cover seven framework readers and distinct TRL trainers. Its [native capture adapter](TRL_A2PO_CAPTURE.md) is separately validated on the pinned CPU runtime; configuration recognition alone still does not establish runtime support.

## Episode capture beneath method-specific monitoring

`environment-episode/2` preserves the recorded model response, dispatched action and returned observation with stable episode/turn identity. The behavior map displays those dispatch bindings separately from semantic relationships. Missing text remains missing; **Turns with model text** measures capture coverage. Gymnasium termination/truncation and OpenEnv/native `done` keep their distinct meanings. Neither return nor termination becomes task success. This layer supports method-specific credit analysis but does not invent native state groups, advantages, optimizer use or policy versions.

The pinned GiGPO ALFWorld action projector mutates its input list; capture the original text before projection. Four executed Gymnasium controls test capture invariance and source links. They use authored responses, not a trained policy, and do not establish GiGPO training integration. See the [episode capture audit](../research/gigpo-episode-capture-2026-10-12/README.md).

## Minimal native export

```python
from tracker.training_setup import prepare, record

# args must be the trainer's effective arguments, after validation and overrides.
# Supports nested Namespace/SimpleNamespace, flat dotted argparse keys and dicts.
request = prepare("openrlhf", args, version=native_commit, resolved=True)
reference = record(outbox, experiment, request)

# Attach the reference to data["recipe"] on the corresponding sample/use record.
# Read again when effective settings change. Earlier references remain immutable.
```

For OmegaConf-based frameworks, first call `OmegaConf.to_container(config, resolve=True)`. For NeMo RL use the validated native model's `model_dump(mode="json")`. Do not copy a training preset and claim it is the effective runtime configuration.

`prepare` copies recognized settings only. It does not execute callbacks, YAML/Hydra expressions, shell scripts or model calls. Native record delivery remains a separate integration responsibility. File previews are available in **Connections → Training setup** and do not register an experiment.

## Automatic monitoring priorities

The training-health dashboard now applies these priorities to **recorded data**, through `training-dashboard/4`. Sampling settings select generation diagnostics; the exact learner recipe selects use diagnostics. A group-sampled population consumed by a critic-based learner therefore opens the corresponding training-use stream. Undelivered or unverified learner settings cannot inherit the sampling method. Compatible native gradients and measurable policy history can select a useful view even without a recognized framework reader.

Users choose a population and leave **View → Automatic** selected. The page explains its choice, preserves manual choices, and offers **Use automatic view** to return. Detailed settings/capture requirements expand in place. Scalar-advantage and token-inclusion charts require observed denominators; missing arrays are not replaced by empty curves or zero-valued cards. No monitor thresholds or trainer parameters are tuned. The [validation](../research/method-aware-dashboard-2026-10-12/README.md) includes ten configurations across all seven readers and independent generation/use settings.

| Question | Method-sensitive requirements |
|---|---|
| Is task performance improving? | Named rewards and independent task outcomes, at generation/evaluation coordinates |
| Which rollouts reach training? | Actual admission decisions, repeated-use receipts, sample/token masks |
| Where does the learning signal come from? | Prompt groups, batch baselines, or value/return/advantage alignment as applicable |
| How are policy updates weighted? | Token/sequence ratio unit; clipped, capped, smooth or additive objective semantics; exact loss reduction |
| Is sampling aligned with training? | Behavior/learner identities, sampler probabilities, policy age, partial-rollout segments and actor/critic clocks |

Missing evidence is not a zero. A recipe declaration establishes intended settings, not observed execution or causal credit. Custom processing remains explicit rather than inheriting the built-in method's metrics. Current capability checks control the numerical views; recommendations do not synthesize unavailable measurements.

The UI calls these **Training settings**, **Training data**, **Learning signal**, **Policy age**, and **Capture requirements**. Detailed native terminology stays available in expandable provenance.

See the [pinned source review and validation](../research/rl-method-adaptation-2026-10-12/README.md), [training observation contract](TRAINING_RECIPE_OBSERVATIONS.md), and [engineering framework](RL_ENGINEERING_FRAMEWORK.md).

Behavior comparisons now expose the source-declared progress basis and preserve it in cohort separation. New Work focus views use the same parallel-work ordering rule as the rollout map, with old explicit views retaining their previous rule. See [projection validation](../research/work-focus-distributions-2026-10-12/README.md).

**Behavior across training** joins an existing monitor to generation samples and exact use streams without depending on the estimator or objective. The two native clocks, repeated source use and missing annotation coverage remain separate. See [usage and measurement contract](BEHAVIOR_TRAINING_TIMELINES.md).

**Critic-based RL:** the generic [value observation contract](VALUE_OBSERVATIONS.md) now turns aligned native values and return targets into automatic diagnostics. Five framework settings families are exercised; a complete native distributed critic adapter is still pending. The value-fitting role, policy-baseline role and native position unit are independent of the framework name.

The Slime file integration now provides **Retained batch signals** directly from pinned source exports. Advantage-only and value/return arrays are supported without selecting an assumed RL estimator. Existing source snapshots become useful automatically; complete training-use capture remains a separate capability.

**Reward relationships:** paired component correlations now use the same captured samples, with complete native groups separated from overall task-mix variation. Verified multi-reward settings select this view automatically. The native TRL adapter captures ordered reward-matrix columns under both aggregation modes without extra reward calls. [Definitions, capture and boundaries](REWARD_RELATIONSHIPS.md).
