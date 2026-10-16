"""Adapters interpret source-specific roles; they never execute trace content."""
from __future__ import annotations

import json
import re

from .schema import SCHEMA_VERSION, InputError, content_text, digest, event, metadata

ADAPTER_VERSION = "adapters/1"
FORMAT_VERSIONS = {"harbor": "harbor/2", "swe-agent": "swe-agent/2", "harbor-bundle": "harbor-bundle/1", "swe-rl": "swe-rl/1", "agent-process-bench": "agent-process-bench/1", "devai": "devai/1"}
FORMAT_VERSIONS['verl-generation'] = 'verl-generation/1'
FORMAT_VERSIONS['tau-bench'] = 'tau-bench/2'
FORMAT_VERSIONS['nebius-openhands'] = 'nebius-openhands/1'
FORMAT_VERSIONS.update({'chat-messages':'chat-messages/1','environment-episode':'environment-episode/1','generation':'generation/1','atif':'atif/1'})
FORMATS = ("auto", "harbor", "harbor-bundle", "swe-agent", "swe-rl", "mini-swe-agent", "nebius", "agent-process-bench", "devai", "verl-generation", "chat-messages", "environment-episode", "generation", "atif", "tau-bench")
FORMATS += ('nebius-openhands',)
FORMATS += ('slime-debug',)
FORMAT_VERSIONS['slime-debug'] = 'slime-debug/1'


def detect(document: dict) -> str:
    if document.get('trajectory_format') == 'environment-episode/2': return 'environment-episode'
    if document.get('trajectory_format') == 'slime-debug/1': return 'slime-debug'
    from .nebius_openhands import matches as openhands_matches
    if openhands_matches(document):return 'nebius-openhands'
    from .swe_rl import matches
    from .tau_bench import matches as tau_matches
    if tau_matches(document):return 'tau-bench'
    if document.get('trajectory_format') in {'chat-messages/1','environment-episode/1','generation/1'}:
        return document['trajectory_format'].removesuffix('/1')
    if document.get('trajectory_format') == 'devai/1':
        return 'devai'
    if all(key in document for key in ("messages", "tools", "data_source", "query_index", "sample_index", "total_index", "step_labels")):
        return "agent-process-bench"
    if document.get("tracker_bundle") == "harbor/1":
        return "harbor-bundle"
    if str(document.get("trajectory_format", "")).startswith("mini-swe-agent-"):
        return "mini-swe-agent"
    if matches(document):
        return "swe-rl"
    if "rows" in document:
        return "nebius"
    if "steps" in document and "agent" in document:
        return "harbor"
    rows = document.get("trajectory", [])
    if rows and isinstance(rows, list):
        if not isinstance(rows[0], dict):
            raise InputError("trajectory entries must be objects")
        if "action" in rows[0] or "observation" in rows[0]:
            return "swe-agent"
        if "role" in rows[0] and "instance_id" in document:
            return "nebius"
    # Source shape is shared by imports, HTTP/outbox delivery and file collectors.
    # Explicit unknown versions must never fall through to an approximate reader.
    if document.get('trajectory_format'):
        raise InputError('Unsupported trajectory_format: '+str(document['trajectory_format']))
    from .portable import detect_record
    common = detect_record(document)
    if common:
        return common
    raise InputError('Unrecognized record. Supply a messages conversation, prompt/completion generation, '
                     'an environment-episode contract, ATIF, or a supported framework export. '
                     'Arbitrary JSON and token chunks need an explicit capture projection.')


def normalize(document: dict, fmt: str = "auto", meta: dict | None = None, sources=None) -> list[dict]:
    if not isinstance(document, dict):
        raise InputError("A trajectory must be a JSON object")
    fmt = detect(document) if fmt == "auto" else fmt
    # The historical "Nebius dataset JSON" selector covers two distinct native
    # datasets. Dispatch by the actual row schema before the legacy text reader.
    from .nebius_openhands import matches as openhands_matches
    if fmt=='nebius' and openhands_matches(document):fmt='nebius-openhands'
    if fmt not in FORMATS:
        raise InputError(f"Unsupported format: {fmt}")
    _validate_shape(document, fmt)
    if fmt=='tau-bench' and 'simulations' in document:
        from .tau_bench import split
        return [run for doc in split(document) for run in normalize(doc,fmt,meta,sources)]
    if fmt in {'nebius','nebius-openhands'} and "rows" in document:
        result = []
        for i, wrapper in enumerate(document["rows"]):
            if wrapper.get("truncated_cells"):
                raise InputError(f"Dataset row {i} contains truncated cells")
            row_meta = {"dataset_row": wrapper.get("row_idx"), **(meta or {})}
            result.extend(normalize(wrapper["row"], fmt, row_meta, sources))
        if not result:
            raise InputError("Dataset response has no rows")
        return result
    events, warnings = [], []
    result_meta = metadata(meta)
    if fmt in {"harbor", "harbor-bundle", "atif"}:
        source = _harbor_bundle(document, events, warnings) if fmt == "harbor-bundle" else document
        if fmt in {"harbor","atif"}:
            _harbor(document, events, warnings)
        extra = source.get("extra") or {}
        # Only explicitly supplied training provenance is used; session_id is not a checkpoint.
        result_meta = metadata({**extra.get("tracking", {}), **result_meta})
        result_meta.setdefault("task_id", extra.get("task_id"))
        result_meta.setdefault("session_id", source.get("session_id"))
        result_meta.setdefault("model", source.get("agent", {}).get("model_name"))
        result_meta.setdefault("environment", "atif" if fmt=='atif' else "harbor")
        result_meta["source_schema"] = source.get("schema_version")
        outcome = {"final_metrics": source.get("final_metrics"), "termination": extra.get("termination")}
        outcome["final_metrics_pointer"] = "/final_metrics" if fmt in {"harbor","atif"} else f"/documents/{next(i for i,d in enumerate(document['documents']) if d['path']==document['root'])}/document/final_metrics"
    elif fmt=='slime-debug':
        from .slime_debug import append_events
        outcome=append_events(document,events,warnings,result_meta)
    elif fmt=='tau-bench':
        from .tau_bench import append_events
        outcome=append_events(document,events,warnings,result_meta)
    elif fmt=='nebius-openhands':
        from .nebius_openhands import append_events
        outcome=append_events(document,events,warnings,result_meta)
    elif fmt in {'chat-messages','environment-episode','generation'}:
        from .portable import append_events
        outcome=append_events(document,fmt,events,warnings,result_meta)
    elif fmt == "agent-process-bench":
        from .chat_messages import append_messages, apb_metadata
        bfcl=document.get('data_source','').startswith('bfcl')
        append_messages(document, events, warnings,flat_tool_definitions=bfcl,unlinked_agent_results=bfcl)
        if bfcl:
            warnings.append('BFCL tool messages are retained as supplied model-conversation results. Missing call IDs stay unlinked; inline tool-call markup remains source text, not a fabricated dispatch.')
        result_meta = metadata({**apb_metadata(document), **result_meta})
        outcome = {"source_process_annotation": {"labels": document["step_labels"], "source_pointer": "/step_labels",
                   "unit": "whole assistant message", "target": "goal-oriented net contribution, not activity membership"},
                   "source_final_annotation": {"value": document.get("final_label"), "source_pointer": "/final_label"}}
        warnings.extend(["Process-reference labels are retrospective and are not semantic activity labels.",
                         "Only recorded messages enter behavior evidence. Private task scenarios, reference answers and final grading stay outside the observation packets.",
                         "Available reasoning is only what the source recorded; missing reasoning is unobserved."])
    elif fmt == 'verl-generation':
        from .verl_generation import append_events
        outcome = append_events(document, events, result_meta)
        warnings.extend([
            'Flattened generation export: serialized input and output are preserved. Internal turns, tool dispatches and environment responses cannot be reconstructed.',
            'Logged step is the source iteration, not a verified generating-policy version. Reward is the producer score, not independent task success.',
            'Ground truth and evaluator fields stay in raw source, outside agent-visible events.'])
    elif fmt == 'devai':
        from .devai import append_events
        append_events(document, events)
        result_meta.setdefault('environment', 'devai-openhands')
        models = {r.get('step_usage', {}).get('model') for r in document['trajectory']} - {None}
        if len(models) == 1:
            result_meta.setdefault('model', next(iter(models)))
        outcome = {'recorded_steps': len(document['trajectory'])}
        warnings.append('DevAI action strings and terminal output are recorded evidence; no exit status, policy checkpoint or independent task-success judgment is inferred.')
    elif fmt == "swe-agent":
        _swe(document, events, warnings)
        info = document.get("info") or {}
        result_meta.setdefault("task_id", document.get("instance_id") or info.get("instance_id"))
        result_meta.setdefault("environment", "swe-agent")
        outcome = {"termination": info.get("exit_status"), "evaluation": info.get("evaluation"),
                   "submission": info.get("submission"), "model_stats": info.get("model_stats")}
    elif fmt == "swe-rl":
        from .swe_rl import append_events
        append_events(document, events, warnings)
        result_meta.setdefault("task_id", document["instance_id"])
        result_meta.setdefault("environment", "swe-rl")
        result_meta.setdefault("task_revision", document["instance"].get("base_commit"))
        outcome = {"termination": document.get("exit_status"), "patch": document.get("model_patch"),
                   "recorded_assistant_turns": document["n_steps"]}
    elif fmt == "mini-swe-agent":
        from . import mini_swe
        if mini_swe.is_v2(document): mini_swe.append_events(document, events, warnings)
        else: _nebius(document, events, warnings, field="messages", text_key="content")
        info = document.get("info") or {}
        result_meta.setdefault("task_id", document.get("instance_id") or info.get("instance_id"))
        result_meta.setdefault("environment", "mini-swe-agent")
        result_meta["source_schema"] = document.get("trajectory_format")
        outcome = {"termination": info.get("exit_status"), "submission": info.get("submission"),
                   "model_stats": info.get("model_stats")}
    else:
        _nebius(document, events, warnings)
        result_meta.setdefault("task_id", document.get("instance_id"))
        result_meta.setdefault("model", document.get("model_name"))
        result_meta.setdefault("environment", "swe-agent")
        result_meta.setdefault("source_uri", "https://huggingface.co/datasets/nebius/SWE-agent-trajectories")
        outcome = {"termination": document.get("exit_status"), "verified_success": document.get("target"),
                   "evaluation_log": document.get("eval_logs"), "patch": document.get("generated_patch")}
        warnings.append("Public convenience sample; no policy checkpoint was provided by this dataset.")
    if not events:
        raise InputError("Trajectory contains no events")
    if len(events) > 100_000:
        raise InputError("Trajectory exceeds 100,000 events; split by trajectory document")
    result_meta = metadata(result_meta)
    if not result_meta.get("task_id"):
        warnings.append("Task identity missing: excluded from paired checkpoint comparisons.")
    if not result_meta.get("checkpoint") and not result_meta.get("policy_version"):
        warnings.append("Policy version missing: policy identity cannot be verified. Rollout trends use explicit experiment and training_step when provided.")
    for e in events:
        e.setdefault("trajectory_id", "main")
        e.setdefault("copied_context", False)
        e["content_hash"] = digest({"kind": e["kind"], "text": e["text"]})
    version = FORMAT_VERSIONS.get(fmt, ADAPTER_VERSION)
    if fmt in {'chat-messages','generation'} and 'trajectory_format' not in document:
        version = fmt+'/unmarked-1'
    if fmt == 'environment-episode' and document.get('trajectory_format') == 'environment-episode/2':
        version = 'environment-episode/2'
    if fmt=='agent-process-bench' and document.get('data_source','').startswith('bfcl'):
        version='agent-process-bench/2'
    if fmt == 'mini-swe-agent' and mini_swe.is_v2(document): version = mini_swe.VERSION
    run = {"schema": SCHEMA_VERSION, "adapter": fmt, "adapter_version": version,
           "metadata": result_meta, "events": events, "outcome": outcome,
           "warnings": list(dict.fromkeys(warnings)), "raw": document}
    run["id"] = digest({"raw": document, "metadata": result_meta, "adapter": version})[:24]
    if 'work_state' in document or 'work_state' in (document.get('extra') or {}):
        from .work_state import capture
        capture(run)  # Reject misbound evidence before it can enter population metrics.
    if 'declared_work_tree' in document or 'declared_work_tree' in (document.get('extra') or {}):
        from .declared_work_tree import capture
        capture(run)
    from .context import attach
    return [attach(run, sources)]


def _validate_shape(document, fmt, depth=0):
    if fmt=='atif':fmt='harbor'
    if depth > 32:
        raise InputError("Subagent nesting exceeds 32")
    def objects(value, path):
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            raise InputError(f"{path} must be a list of objects")
        return value

    for key in ("info", "extra", "agent"):
        if key in document and document[key] is not None and not isinstance(document[key], dict):
            raise InputError(f"/{key} must be an object")
    if isinstance(document.get("extra"),dict) and "tracking" in document["extra"] and not isinstance(document["extra"]["tracking"],dict):
        raise InputError("/extra/tracking must be an object")
    if fmt == "harbor":
        if not isinstance(document.get("agent"), dict):
            raise InputError("/agent must be an object")
        for i, step in enumerate(objects(document.get("steps"), "/steps")):
            path = f"/steps/{i}"
            for field in ("extra","metrics"):
                if step.get(field) is not None and not isinstance(step[field],dict):
                    raise InputError(f"{path}/{field} must be an object")
            sid = step.get("step_id")
            if isinstance(sid, bool) or not isinstance(sid, (int, str)):
                raise InputError(f"{path}/step_id must be an integer or string")
            for call in objects(step.get("tool_calls"), path + "/tool_calls"):
                if not isinstance(call.get("tool_call_id"), str):
                    raise InputError(f"{path}: tool_call_id must be a string")
            observation = step.get("observation")
            if observation is not None and not isinstance(observation, dict):
                raise InputError(f"{path}/observation must be an object")
            for result in objects((observation or {}).get("results"), path + "/observation/results"):
                if result.get("source_call_id") is not None and not isinstance(result["source_call_id"], str):
                    raise InputError(f"{path}: source_call_id must be a string")
            if step.get("reasoning_content") is not None and not isinstance(step["reasoning_content"], str):
                raise InputError(f"{path}/reasoning_content must be text")
        for child in objects(document.get("subagent_trajectories"), "/subagent_trajectories"):
            if not isinstance(child.get("trajectory_id"), str):
                raise InputError("Subagent trajectory_id must be a string")
            _validate_shape(child, "harbor", depth + 1)
    elif fmt in {"swe-agent", "nebius", "mini-swe-agent"}:
        for key in ("trajectory", "history", "messages", "rows"):
            if key in document:
                objects(document[key], "/" + key)


def _harbor_bundle(document, events, warnings):
    """Follow only explicit continuation references in supplied documents."""
    from pathlib import PurePosixPath
    documents = document.get("documents")
    if not isinstance(documents, list) or not documents or len(documents) > 32:
        raise InputError("Harbor bundle needs 1–32 supplied documents")
    by_path = {}
    for i, item in enumerate(documents):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("document"), dict):
            raise InputError("Bundle entries require path and document")
        path = item["path"]
        if path in by_path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
            raise InputError("Bundle paths must be distinct relative POSIX paths without parent traversal")
        by_path[path] = (i, item["document"])
    current, visited = document.get("root"), set()
    if not isinstance(current, str):
        raise InputError("Bundle root must name a supplied document")
    root_source = None
    while current:
        if current in visited:
            raise InputError("Continuation reference cycle")
        if current not in by_path:
            warnings.append(f"Continuation document missing: {current}")
            break
        visited.add(current)
        index, source = by_path[current]
        _validate_shape(source, "harbor")
        root_source = root_source or source
        _harbor(source, events, warnings, prefix=f"/documents/{index}/document", trajectory_id="main")
        reference = source.get("continued_trajectory_ref")
        if reference is not None and not isinstance(reference, str):
            raise InputError("continued_trajectory_ref must be a relative path string")
        if reference and (PurePosixPath(reference).is_absolute() or ".." in PurePosixPath(reference).parts or "\\" in reference):
            raise InputError("Continuation references must stay inside the supplied document tree")
        current = str(PurePosixPath(current).parent / reference) if reference else None
    if root_source is None:
        raise InputError("Bundle root document missing")
    if len(visited) != len(documents):
        raise InputError("Bundle contains unreferenced documents; import independent trajectories separately")
    if not current:
        warnings[:] = [w for w in warnings if not w.startswith("External continuation is referenced")]
    return root_source


def _harbor(doc, events, warnings, prefix="", trajectory_id="main", ancestors=()):
    if len(ancestors) > 32:
        raise InputError("ATIF subagent nesting exceeds 32")
    if not isinstance(doc.get("steps"), list):
        raise InputError("ATIF steps must be a list")
    version = str(doc.get("schema_version", ""))
    if not re.fullmatch(r"ATIF-v1\.[0-8]", version):
        raise InputError(f"Unsupported ATIF schema version: {version or 'missing'}")
    trajectory_id = str(doc.get("trajectory_id") or trajectory_id) if not prefix else trajectory_id
    call_namespace = prefix + "#" + trajectory_id if prefix else trajectory_id
    seen_steps, seen_calls = set(), set()
    for i, step in enumerate(doc["steps"]):
        sid = step.get("step_id")
        if sid in seen_steps or sid is None:
            raise InputError("ATIF step_id must be present and unique within a trajectory")
        seen_steps.add(sid)
        pointer = f"{prefix}/steps/{i}"
        source = step.get("source")
        if source not in {"agent", "user", "system"}:
            raise InputError(f"Unknown ATIF source at {pointer}")
        shared = {"trajectory_id": trajectory_id, "timestamp": step.get("timestamp"),
                  "copied_context": step.get("is_copied_context") is True, "step_id": sid}
        text, media = content_text(step.get("message"))
        msg = event(events, kind="instruction" if source == "user" else "message", text=text,
                    pointer=pointer + "/message", actor=source, media=media, **shared)
        if media:
            warnings.append("Referenced media preserved, but its visual/audio content is not analyzed.")
        if step.get("reasoning_content"):
            event(events, kind="reasoning", text=step["reasoning_content"], actor=source,
                  pointer=pointer + "/reasoning_content", parent_id=msg["id"], **shared)
        if step.get("metrics"):
            msg["metrics"] = step["metrics"]
        step_actions = []
        for j, call in enumerate(step.get("tool_calls") or []):
            cid = call.get("tool_call_id")
            if not cid or cid in seen_calls:
                raise InputError("ATIF tool_call_id must be present and unique within a trajectory")
            seen_calls.add(cid)
            args = call.get("arguments", {})
            if not isinstance(args, dict):
                raise InputError("ATIF tool arguments must be an object")
            command = next((args[k] for k in ("command", "cmd", "code", "keystrokes") if isinstance(args.get(k), str)), None)
            added = event(events, kind="action", text=command or json.dumps(args, ensure_ascii=False),
                  pointer=f"{pointer}/tool_calls/{j}", actor=source, call_id=f"{call_namespace}:{cid}",
                  tool=str(call.get("function_name", "unknown")), arguments=args, parent_id=msg["id"], **shared)
            step_actions.append(added)
        # Terminus exports some executed command batches inside the JSON message,
        # without structured tool_calls. Keep the entire batch as one observation unit.
        if source == "agent" and not step_actions and doc.get("agent", {}).get("name") == "terminus-2":
            try:
                decoded = json.loads(text)
            except (ValueError, TypeError):
                decoded = None
            commands = decoded.get("commands") if isinstance(decoded, dict) else None
            if isinstance(decoded, dict) and isinstance(decoded.get("task_complete"), bool):
                msg["completion_claim"] = decoded["task_complete"]
            if isinstance(commands, list) and commands and all(isinstance(c, dict) and isinstance(c.get("keystrokes"), str) for c in commands):
                added = event(events, kind="action", text="\n".join(c["keystrokes"].rstrip() for c in commands),
                              pointer=pointer + "/message", actor=source, tool="terminus_command_batch",
                              arguments={"commands": commands}, call_id=f"{call_namespace}:parsed-batch:{sid}",
                              parent_id=msg["id"], extraction="terminus-json-command-batch", **shared)
                step_actions.append(added)
        for j, obs in enumerate((step.get("observation") or {}).get("results") or []):
            text, media = content_text(obs.get("content"))
            cid = obs.get("source_call_id")
            refs = obs.get("subagent_trajectory_ref") or []
            related = [step_actions[0]["id"]] if not cid and not refs and len(step_actions) == 1 else []
            event(events, kind="feedback", text=text, pointer=f"{pointer}/observation/results/{j}",
                  actor="environment", source_call_id=f"{call_namespace}:{cid}" if cid else None,
                  media=media, subagent_refs=refs, related_action_ids=related,
                  link_basis="source_call_id" if cid else "single action in same step" if related else "unlinked",
                  **shared)
            if related:
                warnings.append("Some results have no call ID; correspondence uses the unique action in the same source step and is marked accordingly.")
            if refs:
                warnings.append("Subagent document order is not global execution order; cross-agent temporal edges are not inferred.")
        if (step.get("extra") or {}).get("context_management"):
            warnings.append("Context-management metadata retained in source; copied context excluded from action counts.")
    children = doc.get("subagent_trajectories") or []
    ids = [c.get("trajectory_id") for c in children]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise InputError("Embedded ATIF subagents require distinct trajectory_id values")
    for i, child in enumerate(children):
        child_id = str(child["trajectory_id"])
        _harbor(child, events, warnings, f"{prefix}/subagent_trajectories/{i}", f"{trajectory_id}/{child_id}",
                (*ancestors, trajectory_id))
    if doc.get("continued_trajectory_ref"):
        warnings.append("External continuation is referenced but not loaded; this document may be incomplete.")
    if any(s.get("is_copied_context") for s in doc["steps"]):
        warnings.append("Copied user-role context is retained as evidence; it is not counted as a new user objective or an objective change.")


def _swe(doc, events, warnings):
    history = doc.get("history") or []
    for i, row in enumerate(history):
        if row.get("role") == "user" and row.get("content") and not row.get("is_demo"):
            text, media = content_text(row["content"])
            event(events, kind="instruction", text=text, pointer=f"/history/{i}/content", actor="user", media=media)
            break
    if not events and doc.get("problem_statement"):
        event(events, kind="instruction", text=str(doc["problem_statement"]), pointer="/problem_statement", actor="user")
    for i, row in enumerate(doc.get("trajectory") or []):
        p = f"/trajectory/{i}"
        thought = row.get("thought") or row.get("response") or ""
        parent = event(events, kind="reasoning", text=str(thought), pointer=p + ("/thought" if row.get("thought") else "/response"))
        cid = f"swe:{i}"
        if row.get("action"):
            action = str(row["action"])
            event(events, kind="action", text=action, pointer=p + "/action", call_id=cid,
                  tool="shell", arguments={"command": action}, parent_id=parent["id"],
                  execution_time=row.get("execution_time"), recorded_state=row.get("state"), extra_info=row.get("extra_info"))
        if row.get("observation") is not None:
            event(events, kind="feedback", text=str(row["observation"]), pointer=p + "/observation",
                  actor="environment", source_call_id=cid if row.get("action") else None)


def _nebius(doc, events, warnings, field="trajectory", text_key="text"):
    """In this dataset later `user` messages are shell feedback, not authorized goal changes."""
    pending = None
    initial_user_seen = False
    for i, row in enumerate(doc.get(field) or []):
        if field=='trajectory' and ('content' in row or row.get('tool_calls')):
            raise InputError('Structured chat trajectory cannot use the legacy Nebius text reader; supply the complete native OpenHands row or a chat-messages envelope')
        p = f"/{field}/{i}"
        role = row.get("role")
        text, media = content_text(row.get(text_key) or row.get("system_prompt") or "")
        if role in {"ai", "assistant"}:
            parent = event(events, kind="message", text=text, pointer=p + "/" + text_key, media=media)
            blocks = list(re.finditer(r"```(?:bash|sh|shell)?\s*\n(.*?)```", text, re.S))
            if len(blocks) == 1:
                match = blocks[0]
                command = match.group(1).strip()
                pending = f"nebius:{i}"
                event(events, kind="action", text=command, pointer=p + "/" + text_key, call_id=pending,
                      tool="shell", arguments={"command": command}, parent_id=parent["id"],
                      span={"start": match.start(1), "end": match.end(1)}, extraction="single-command-fence")
            else:
                pending = None
                warnings.append("Assistant messages without exactly one command block remain unparsed, not guessed.")
        elif role == "user" and not initial_user_seen:
            initial_user_seen = True
            event(events, kind="instruction", text=text, pointer=p + "/" + text_key, actor="user", media=media)
        elif role == "user":
            event(events, kind="feedback", text=text, pointer=p + "/" + text_key, actor="environment", source_call_id=pending, media=media)
            pending = None
        else:
            event(events, kind="message", text=text, pointer=p + "/system_prompt", actor=role or "unknown")
