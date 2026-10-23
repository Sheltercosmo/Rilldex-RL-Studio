# Model setup

Collection, trainer signals and source inspection need no model credentials. For semantic activities and relationships, use **Data & workflows → Models** or the installed commands below.

## Configure

| Variable | Value |
| --- | --- |
| `RILLDEX_LLM_PRESET` | `local` (port 8000), `ollama` (port 11434), or `custom` |
| `RILLDEX_LLM_URL` | Full HTTPS or loopback `/v1/chat/completions` URL; overrides the preset |
| `RILLDEX_LLM_MODEL` | Explicit candidate model identifier |
| `RILLDEX_LLM_API_KEY` | Candidate credential, when required |
| `JEV_API_KEY` | Jev/Typesafe decision credential |

Use `export NAME="value"` in Bash or `$env:NAME="value"` in PowerShell, then start Rilldex in that environment. The UI provides both templates. Proxy environment variables are respected; local servers may need `NO_PROXY=127.0.0.1,localhost`.

The installed adapter accepts chat completions with JSON-object `response_format`. The candidate model proposes source-bound alternatives; Jev selects the maximum-probability supplied option. No confidence threshold is used.

For staged work-content extraction directly from a saved graph, see [source qualifications](SCOPE_MEMBERSHIP.md). It supports bounded generation, contract repair, partial results and resume through Python, without an export step. This remains experimental and does not replace the main map extractor.

## Check and try one rollout

```sh
python -m rilldex.models check
python -m rilldex.models probe
python -m rilldex.models pilot ./pilot --db study.sqlite --run-id ROLLOUT_ID --candidate-calls 20 --decision-calls 20 --input-bytes 1000000
```

`check` is offline. `probe` makes one candidate request to test the JSON contract, not semantic accuracy. New pilots extract activities, connect plans and work targets, inspect execution feedback, and compare approaches. Open the activity map while analysis is pending; **Plans & attempts** and **Review approach comparisons** link to completed results. Remote workers use the same command.

Limits are **lifetime totals for that pilot directory**, not token or currency estimates. Restart with the same directory and limits to reuse saved work; raise limits to continue a blocked pilot. Interrupted attempts remain counted. A changed model or endpoint requires a new directory. Secrets stay in the environment.

All stages share the allowance. Comparisons grow with action and plan counts; a small pilot may stop before all pairs are inspected. Old directories retain their original protocols. Plan links distinguish direct preparation, attempts and checks; upstream work is retained separately instead of becoming a direct plan link. One action can support several steps. These links do not establish completion. Work links describe shared targets and scope overlap, not causal retries or successful recovery. Semantic selections remain fallible; inspect their source evidence.

For an older pilot, click **Inspect execution feedback** or add `--inspect-feedback` to its command. Existing annotations and decisions are reused. Reported errors connect to later returns to the same work; retrieved error text is inspected in its tool context. No reported error is not a success verdict. Uninspected or unreadable feedback stays unknown.

To add approach comparisons to an older pilot with work links, click **Compare approaches** or add `--inspect-approaches`. Each repeated-work pair uses up to two decision calls: confirm comparable work, then compare procedure and stated reason. Native arguments are included when captured. Progress survives a stop between calls; evidence-limit gaps remain visible. A changed procedure does not establish success or exploration.

## Continuous or custom workers

After a pilot, observe the experiment with the same models:

```sh
python -m rilldex.models watch ./observations --db study.sqlite --experiment trial --from-pilot ./pilot --follow
```

This reuses the pilot's exact saved requests and follows existing and arriving completed rollouts under one observer. New workers start at zero additional allowance. Set `--candidate-calls`, `--decision-calls` and `--input-bytes` to permit new analysis; omitted limits retain saved ceilings on restart. Add `--retry-run ROLLOUT_ID` to resume a blocked job. **Models → Observe an experiment continuously** generates the command.

All analysis stages share that allowance. Error, revisit, approach-change and coverage measures appear in **Overview → Behavior measures** for the experiment. Paused monitors remain paused. Status: `rilldex --db study.sqlite semantic watch-status ./observations`. Keep both the database and worker directory on durable storage. This is a local worker, not a distributed scheduler.

For a new worker, omitting `--from-pilot` selects the current installed protocol. Custom proposers still use `semantic watch-init --behavior-links` and `semantic watch-run`, with `python -m rilldex.candidate` or a JSON stdin/stdout command. See [continuous observation](CONTINUOUS_OBSERVATION.md).

To restart, reuse the worker directory; `--from-pilot` is no longer required. Saved protocols, labels, prefix settings and limits remain pinned. In the UI, choose **Resume saved worker** and leave limits blank. After a package update, choose **Refresh after package update** or add `--refresh-worker`: it replays saved evidence offline and resumes only if published maps are unchanged. Refresh keeps prior usage and blocked jobs; `--retry-run` remains explicit.

Custom decision transports remain available through `tracker.semantic_workspace.execute()` and `tracker.semantic_watch.run_once()`. Return the requested model identity and normalized probabilities for exactly the supplied choices. A different decision engine needs its own versioned protocol/cache identity; do not relabel it as Jev. The turnkey pairing is a local/API candidate plus Jev API selection.
