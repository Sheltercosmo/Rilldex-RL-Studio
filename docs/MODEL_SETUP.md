# Local and API model setup

No model is needed to collect data, capture trainer metrics, inspect source records or query saved analyses. Enable semantic observation only when you want new model-selected annotations.

## Candidate LLM

The worker runs an argument list, writes one request packet to stdin, and reads a JSON candidate object from stdout. Requests include source evidence, stage instructions and a response contract. You can run a local model directly or call a hosted API in that process.

The supplied [chat-completions adapter](../examples/chat_candidate_proposer.py) supports a local server or hosted endpoint that accepts `messages` and JSON-object `response_format` and returns `choices[0].message.content`. It requires no provider SDK. Not all model servers implement this contract; adapt the script for your provider if necessary.

Set these variables in the candidate worker environment:

| Variable | Local example | Hosted example |
| --- | --- | --- |
| `RILLDEX_LLM_URL` | `http://127.0.0.1:8000/v1/chat/completions` | Your provider's HTTPS chat-completions URL |
| `RILLDEX_LLM_MODEL` | Your served model identifier | Your pinned API model identifier |
| `RILLDEX_LLM_API_KEY` | Only if your local server requires it | Your provider credential |

Use `export NAME="value"` in Bash or `$env:NAME="value"` in PowerShell. Credentials are read from the environment and are not placed in launch files or command arguments.

From a checkout, configure the supplied script:

```sh
rilldex --db study.sqlite semantic watch-init observations --experiment run-a --label "Activities and work" --candidate-producer my-model-prompt-v1 --candidate-command python examples/chat_candidate_proposer.py
rilldex --db study.sqlite semantic watch-budget observations --max-new-calls 100 --max-candidate-calls 100 --max-input-bytes 2000000
rilldex --db study.sqlite semantic watch-run observations --follow --candidate-command python examples/chat_candidate_proposer.py
```

Use an absolute script path when launching from another directory. Use the same command on resume. Change the producer version and create a fresh observer configuration when changing the model or prompting. The sample adapter makes one request per invocation and does not retry automatically; JSON validity does not establish semantic accuracy.

## Decision model

The built-in decision provider is **Jev/Typesafe**, separate from your candidate LLM. Set `JEV_API_KEY` in the observer environment before starting the worker. The current pinned model is defined in `tracker.jev.DEFAULT_MODEL`. Normal `HTTP_PROXY` / `HTTPS_PROXY` configuration is respected by the HTTP client; for loopback services, set `NO_PROXY=127.0.0.1,localhost` if needed.

Each decision chooses the maximum-probability option in the supplied finite set. Candidate generation, evidence retrieval and structural validation happen outside that selection. There is no confidence threshold. The Jev key is removed from the candidate subprocess environment.

### Custom/local decision engines

Python integrations can supply `transport(request)` to `tracker.semantic_workspace.execute()` or `tracker.semantic_watch.run_once()`. The callable receives the complete decision request and must return the requested model identity plus an `answers` object. Each answer has `type: "choice"` and a normalized `probabilities` mapping containing **exactly** the supplied criterion names. Raw argmax selection remains in Rilldex.

This is a developer integration interface, not a CLI model switch or an installed local inference engine. The staged pipeline currently pins the built-in request model identity; a different decision engine needs a separately versioned protocol/cache identity before production use. Do not relabel a local model as Jev or reuse Jev decisions for it. The supported turnkey pairing is a local/API candidate command plus Jev API selection.

## Budget and restart

`watch-init` permits zero new calls. `watch-budget` explicitly raises lifetime request and UTF-8 byte ceilings; these are not token or currency limits. Failed or interrupted provider invocations remain accounted for. Exact compatible candidates and decisions are reused. `rilldex semantic watch-status observations` shows queued, blocked and published work and retained usage reports.

[Continuous observation and recovery](CONTINUOUS_OBSERVATION.md) covers live prefixes, staged layers and resuming a blocked rollout.

[Experimental attachment review](ATTACHMENT_REVIEW.md) compares qualifier and intention attachments without changing saved maps.
