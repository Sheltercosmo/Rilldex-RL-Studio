"""Recorded producer context and outcomes, separate from prefix behavior evidence."""
from __future__ import annotations

import json
import math

from .schema import InputError, digest

CONTEXT_VERSION = "producer-context/1"
KINDS = {"harbor_trial_config", "harbor_trial_result", "harbor_task_config", "harbor_instruction", "swe_replay_config", "swe_rl_grading"}


def pick(document, paths):
    """A small projection avoids importing environment variables or credentials."""
    output = {}
    for path in paths:
        value = document
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is None:
            continue
        target = output
        parts = path.split(".")
        for key in parts[:-1]:
            target = target.setdefault(key, {})
        target[parts[-1]] = value
    return output


HARBOR_CONFIG_PATHS = (
    "task.path", "task.git_url", "task.git_commit_id", "task.name", "task.ref", "trial_name",
    "agent.name", "agent.model_name", "agent.override_timeout_sec", "agent.max_timeout_sec",
    "agent.override_setup_timeout_sec", "agent.extra_allowed_hosts", "agent.resume_trajectory",
    "environment.type", "environment.override_cpus", "environment.override_memory_mb",
    "environment.override_storage_mb", "verifier.disable", "verifier.override_timeout_sec",
    "timeout_multiplier", "agent_timeout_multiplier", "verifier_timeout_multiplier")
SWE_CONFIG_PATHS = (
    "agent.model.name", "agent.model.temperature", "agent.model.top_p", "agent.model.max_tokens",
    "agent.model.per_instance_cost_limit", "agent.tools.submit_command", "agent.tools.command_docs",
    "agent.tools.execution_timeout", "agent.tools.total_execution_timeout",
    "agent.tools.max_consecutive_execution_timeouts", "agent.tools.filter", "agent.tools.bundles",
    "env.repo.type", "env.repo.github_url", "env.repo.base_commit", "env.deployment.type",
    "env.deployment.image", "problem_statement.id", "problem_statement.type")


def result_projection(document):
    output = pick(document, ("id", "task_name", "trial_name", "task_id", "task_checksum", "started_at", "finished_at",
        "environment_setup", "agent_setup", "agent_execution", "verifier", "exception_info.exception_type",
        "verifier_result.rewards", "verifier_environment_mode", "agent_result.n_input_tokens",
        "agent_result.n_output_tokens", "agent_result.n_cache_tokens", "agent_result.cost_usd"))
    if isinstance(document.get("step_results"), list):
        output["step_results"] = [pick(step, ("step_name", "verifier_result.rewards", "exception_info.exception_type",
            "agent_execution", "verifier", "agent_result.n_input_tokens", "agent_result.n_output_tokens",
            "agent_result.n_cache_tokens", "agent_result.cost_usd")) for step in document["step_results"] if isinstance(step, dict)]
    return output


def validate_sources(sources):
    if not isinstance(sources, list) or len(sources) > 16:
        raise InputError("sources must contain at most 16 context artifacts")
    result, names = [], set()
    for source in sources:
        if not isinstance(source, dict) or source.get("kind") not in KINDS:
            raise InputError("Unsupported producer context source")
        name, data = source.get("name"), source.get("data")
        if not isinstance(name, str) or not 1 <= len(name) <= 1000 or name in names:
            raise InputError("Context source names must be distinct nonempty strings")
        if not isinstance(data, (dict, str)):
            raise InputError("Context source data must be an object or text")
        if source["kind"] != "harbor_instruction" and not isinstance(data, dict):
            raise InputError("Configuration/result context must be an object")
        names.add(name)
        record = {k:source[k] for k in ("kind", "name", "data", "source_sha256", "projection", "scope") if k in source}
        record["content_hash"] = digest(data)
        record["id"] = "s-" + digest(record)[:16]
        result.append(record)
    return result


def attach(run, sources=None):
    sources = list(sources or [])
    if run["adapter"] == "swe-agent":
        replay = run["raw"].get("replay_config")
        try:
            replay = json.loads(replay) if isinstance(replay, str) else replay
        except ValueError:
            run["warnings"].append("Embedded replay_config could not be parsed; environment context remains unknown.")
            replay = None
        if isinstance(replay, dict):
            sources.append({"kind":"swe_replay_config", "name":"embedded:/replay_config", "data":pick(replay,SWE_CONFIG_PATHS), "projection":True})
    if not sources:
        return run
    sources = validate_sources(sources)
    facts = []
    def fact(key, value, source, pointer, nature="declared"):
        if value is not None:
            facts.append({"key":key,"value":value,"source_id":source["id"],"pointer":pointer,"nature":nature})
    for source in sources:
        data, kind = source["data"], source["kind"]
        if kind == "harbor_trial_result":
            # Final results are retrospective evidence. Never include them in
            # the prefix-only Jev action packet.
            chosen, pointer = data, ""
            step_name = run["metadata"].get("producer_step")
            if step_name:
                matches = [(i,s) for i,s in enumerate(data.get("step_results") or []) if s.get("step_name") == step_name]
                chosen, pointer = (matches[0][1], f"/step_results/{matches[0][0]}") if len(matches) == 1 else ({}, "")
            rewards = (chosen.get("verifier_result") or {}).get("rewards")
            if isinstance(rewards, dict):
                valid = {k:v for k,v in rewards.items() if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)}
                run["outcome"]["rewards"] = valid
                fact("verifier rewards", valid, source, pointer+"/verifier_result/rewards", "recorded result")
            run["outcome"]["producer_lifecycle"] = {"finished_at":data.get("finished_at"), "exception_type":(chosen.get("exception_info") or {}).get("exception_type"),
                "scope":"step:"+step_name if step_name else "trial", "source_id":source["id"]}
            run["outcome"]["producer_usage"] = {"values":chosen.get("agent_result") or {},"source_id":source["id"],"pointer":pointer+"/agent_result"}
            fact("producer finished at", data.get("finished_at"), source,"/finished_at","recorded lifecycle")
            fact("producer exception", (chosen.get("exception_info") or {}).get("exception_type"),source,pointer+"/exception_info/exception_type","recorded lifecycle")
        elif kind == "swe_rl_grading":
            scope = source.get("scope") or {}
            if not isinstance(scope, dict):
                raise InputError("SWE grading scope must be an object")
            if run["adapter"] != "swe-rl" or scope.get("trajectory_content_hash") != digest(run["raw"]) or scope.get("task_id") != run["raw"]["instance_id"]:
                raise InputError("SWE grading must bind to this exact trajectory content and recorded task identity")
            if any(s["kind"] == "swe_rl_grading" and s["id"] != source["id"] for s in sources):
                raise InputError("Only one grading record can be attached to a SWE RL trajectory")
            if data.get("resolved") is not None and not isinstance(data["resolved"], bool):
                raise InputError("SWE grading resolved must be boolean when present")
            run["outcome"]["verified_success"] = data.get("resolved")
            run["outcome"]["grading"] = {"source_id": source["id"], "pointer": "/resolved",
                "join_basis": scope.get("join_basis", "caller-supplied content binding"),
                "definition": "Producer grading result. Pairing is supplied by the caller, not independently authenticated."}
            fact("producer resolved", data.get("resolved"), source, "/resolved", "recorded result")
            reward = data.get("final_reward")
            if isinstance(reward, (int, float)) and not isinstance(reward, bool) and math.isfinite(reward):
                run["outcome"]["rewards"] = {"final_reward": reward}
                fact("producer final reward", reward, source, "/final_reward", "recorded result")
        elif kind in {"harbor_trial_config","harbor_task_config","swe_replay_config"}:
            paths = HARBOR_CONFIG_PATHS if kind == "harbor_trial_config" else SWE_CONFIG_PATHS if kind == "swe_replay_config" else (
                "schema_version", "agent.timeout_sec", "agent.user", "environment.cpus", "environment.memory_mb",
                "environment.os", "environment.network_mode", "environment.allowed_hosts", "verifier.timeout_sec",
                "verifier.environment_mode", "multi_step_reward_strategy")
            for path in paths:
                value = data
                for part in path.split("."):
                    value = value.get(part) if isinstance(value,dict) else None
                fact(path,value,source,"/"+path.replace(".","/"))
    run["sources"] = sources
    run["environment_context"] = {"version":CONTEXT_VERSION,"facts":facts,
        "configuration_hash":digest(sorted([(f["key"],f["value"]) for f in facts if f["nature"]=="declared" and
            (f["key"].startswith(("environment.","env.","verifier.","agent.tools.")) or "timeout" in f["key"] or "cost_limit" in f["key"])],key=lambda x:(x[0],digest(x[1])))),
        "limits":"Declared settings and recorded results retain source references. A reward is not automatically task success. Defaults and missing specifications are not inferred."}
    # Context is part of the immutable snapshot identity, including late results.
    run["id"] = digest({"trace_id":run["id"],"sources":sources,"context_version":CONTEXT_VERSION})[:24]
    return run
