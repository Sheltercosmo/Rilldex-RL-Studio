# Public rollout comparison

Replayed 16 published mini-SWE-agent trajectories from two model submissions on eight SWE-bench Verified tasks: 1,794 source events, 594 parsed actions and 578 linked returns. Source bytes, dispatch counts and explicit tool-call bindings reconcile with the native records.

Sources: [SWE-bench experiments](https://github.com/SWE-bench/experiments/tree/40f164d5b8f1d249bf95a6df8b74b577fd8e519d/evaluation/verified). The [manifest](manifest.json) pins trace/result hashes and URLs. Selection takes the first and last sorted task in each outcome pairing; this is coverage sampling, not a prevalence estimate.

Separate publisher verdicts now attach through existing evaluation receipts and can be selected for a frozen comparison. Four task pairs retain their outcome; two change in each direction. Missing, unfinished or multiple selected reports remain unresolved. Native model/agent versions are retained; unknown evaluation times remain null. Source-only behavior paths display **not measured**.

```sh
python -m research.replay_public_case_comparisons --download --cache .tracker/public-cases --db .tracker/public-cases/study.sqlite
```

Validation: 119 targeted Python and 371 frontend tests; desktop/mobile evidence, map/back/reload and recapture, including an installed wheel outside the checkout. No model calls or benchmark reruns. These are evaluation variants, not RL checkpoints; semantic annotation accuracy and evaluator correctness are not established by this replay.

AgentLens provides relevant process-reference ideas, but its announced repository returned 404 during this check. Its labels were not used as independent ground truth. [Paper](https://arxiv.org/abs/2605.12925).
