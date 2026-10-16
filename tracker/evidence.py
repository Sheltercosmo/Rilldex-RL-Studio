"""Verification activity, recorded outcomes and resource coverage.

Text printed by a test process is a reported result, not proof of task success
or of a particular artifact version. Missing provenance remains explicit.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

EVIDENCE_VERSION = "verification-evidence/2"
PYTEST_COMMAND = re.compile(r"^(?:pytest\b|python\S*\s+-m\s+pytest\b)")
PYTEST_SUMMARY = re.compile(r"(?m)^(?:=+\s*)?((?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|warnings?)(?:,?\s*))+)(?:in\s+[\d.]+s[^\n]*)?\s*(?:=+)?$")


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0


def reported_summary(action, events):
    # Recognize the actual test invocation, not text that merely quotes a result.
    if not PYTEST_COMMAND.match(action["text"].strip()) or re.search(r"[;|&]",action["text"]):
        return None
    matches = []
    for eid in action["feedback_ids"]:
        for match in PYTEST_SUMMARY.finditer(events[eid]["text"]):
            counts = {}
            for count,status in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|warnings?)",match.group(1)):
                counts[status] = int(count)
            matches.append({"event_id":eid,"text":match.group(0),"counts":counts,
                "source_pointer":events[eid]["source_pointer"],"span":{"start":match.start(),"end":match.end()},
                "basis":"recognized pytest summary in linked environment text; not independently verified"})
    return matches[-1] if len(matches) == 1 else None


def resources(run):
    outcome = run["outcome"]
    reports = []
    def add(label, values, mapping, source):
        if not isinstance(values,dict):
            return
        selected = {name:{"value":values[key],"source_field":key} for key,name in mapping.items() if number(values.get(key))}
        if selected:
            reports.append({"label":label,"values":selected,"source":source})
    producer = outcome.get("producer_usage") or {}
    add("Producer usage",producer.get("values"),{"n_input_tokens":"input_tokens","n_output_tokens":"output_tokens","n_cache_tokens":"cached_tokens","cost_usd":"cost_usd"},
        {"source_id":producer.get("source_id"),"pointer":producer.get("pointer")})
    add("Trajectory totals" if run["adapter"] != "harbor-bundle" else "First continuation document totals", outcome.get("final_metrics"),
        {"total_prompt_tokens":"input_tokens","total_completion_tokens":"output_tokens","total_cached_tokens":"cached_tokens","total_cost_usd":"cost_usd"},
        {"pointer":outcome.get("final_metrics_pointer","/final_metrics")})
    add("Agent instance statistics",outcome.get("model_stats"),{"tokens_sent":"input_tokens","tokens_received":"output_tokens","instance_cost":"cost_usd","api_calls":"api_calls"},
        {"pointer":"/info/model_stats"})
    rows = [e for e in run["events"] if e["kind"] == "action" and not e["copied_context"]]
    durations = [e for e in rows if number(e.get("execution_time"))]
    return {"reports":reports,"execution":{"seconds":sum(e["execution_time"] for e in durations) if durations else None,
            "recorded_actions":len(durations),"eligible_actions":len(rows),"complete":bool(rows) and len(durations)==len(rows),
            "event_ids":[e["id"] for e in durations]},
            "definition":"Reports retain their scope and are not added together. Cached input tokens are a subset of total input. Execution time covers only actions with explicit durations; unknown durations are not zero."}


def inspect(run, actions):
    events = {e["id"]:e for e in run["events"]}
    checks, actors = [], defaultdict(list)
    for action in actions:
        actors[action["trajectory_id"]].append(action)
        if action["mode"] == "verify":
            checks.append({"event_id":action["event_id"],"trajectory_id":action["trajectory_id"],"text":action["text"],
                "basis":action["mode_basis"],"feedback_ids":action["feedback_ids"],"reported_summary":reported_summary(action,events),
                "artifact_version":"unrecorded","scope":"the recorded check; task-wide coverage not established"})
    tails = []
    for actor, rows in actors.items():
        last_check = next((a for a in reversed(rows) if a["mode"]=="verify"),None)
        after = [a["event_id"] for a in rows if a["mode"]=="apply" and (not last_check or a["index"]>last_check["index"])]
        batch_sizes = Counter(a.get("parent_id") for a in rows if a.get("parent_id"))
        uncertain = [a["event_id"] for a in rows if a["mode"] == "unresolved" or batch_sizes.get(a.get("parent_id"), 0) > 1]
        tails.append({"trajectory_id":actor,"last_check":last_check["event_id"] if last_check else None,
                      "application_after_check":after,
                      "status":"unresolved" if uncertain else "no_check_observed" if not last_check else "application_after_check" if after else "no_later_application_observed",
                      "unresolved_event_ids": uncertain, "scope": "recorded action sequence",
                      "limitation":"Unknown purposes or ambiguous batches prevent closure classification. This recorded sequence does not establish a complete trajectory, verification freshness or premature stopping."})
    claims = [{"event_id":e["id"],"trajectory_id":e["trajectory_id"],"source_pointer":e["source_pointer"],
               "claim":"producer-recorded task_complete=true","support":"not established"}
              for e in run["events"] if e.get("completion_claim") is True and not e["copied_context"]]
    outcome = run["outcome"]
    return {"version":EVIDENCE_VERSION,"checks":checks,"actor_tails":tails,"completion_claims":claims,
            "outcome":{"termination":outcome.get("termination"),"dataset_verified_success":outcome.get("verified_success") if isinstance(outcome.get("verified_success"),bool) else None,
                       "rewards":outcome.get("rewards"),"producer_lifecycle":outcome.get("producer_lifecycle"), "grading": outcome.get("grading"),
                       "definition":"Submission, completion claims, numeric verifier rewards and task success are separate observations."},
            "resources":resources(run)}
