"""The public sweagent RL messages export; trace content is never executed."""
from pathlib import Path
import json

from .schema import InputError, content_text, digest, event


def matches(doc):
    return (isinstance(doc.get("messages"), list) and isinstance(doc.get("instance"), dict)
            and isinstance(doc.get("instance_id"), str) and "n_steps" in doc and "exit_status" in doc)


def append_events(doc, events, warnings):
    if not matches(doc) or not doc["instance_id"].strip():
        raise InputError("SWE RL export requires messages, instance, instance_id, n_steps and exit_status")
    if isinstance(doc["n_steps"], bool) or not isinstance(doc["n_steps"], int) or doc["n_steps"] < 0:
        raise InputError("SWE RL n_steps must be a nonnegative integer")
    if doc["exit_status"] is not None and not isinstance(doc["exit_status"], str):
        raise InputError("SWE RL exit_status must be text when present")
    if doc["instance"].get("instance_id") not in (None, doc["instance_id"]):
        raise InputError("SWE RL task identities disagree")
    seen_calls, initial_user, assistant_turns = set(), False, 0
    for i, message in enumerate(doc["messages"]):
        p = f"/messages/{i}"
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
            raise InputError(f"Unsupported SWE RL message role at {p}")
        role = message["role"]
        extra = message.get("extra") if message.get("extra") is not None else {}
        if not isinstance(extra, dict):
            raise InputError(f"{p}/extra must be an object")
        text, media = content_text(message.get("content"))
        shared = {"timestamp": message.get("timestamp"), "producer_extra": extra}
        if media:
            warnings.append("Referenced media preserved, but its visual/audio content is not analyzed.")
        if role == "assistant":
            assistant_turns += 1
            parent = event(events, kind="message", text=text, pointer=p + "/content", media=media, **shared)
            actions = extra.get("actions") if extra.get("actions") is not None else []
            if not isinstance(actions, list):
                raise InputError(f"{p}/extra/actions must be a list")
            for j, action in enumerate(actions):
                if not isinstance(action, dict) or not isinstance(action.get("command"), str):
                    raise InputError(f"{p}/extra/actions/{j} requires a command string")
                cid = action.get("tool_call_id")
                if not isinstance(cid, str) or not cid or cid in seen_calls:
                    raise InputError("SWE RL tool_call_id must be nonempty and unique")
                seen_calls.add(cid)
                event(events, kind="action", text=action["command"], pointer=f"{p}/extra/actions/{j}/command",
                      call_id="swe-rl:" + cid, tool="shell", arguments={"command": action["command"]},
                      parent_id=parent["id"], extraction="structured-command", batch_size=len(actions), **shared)
            if not actions:
                parent["action_extraction"] = "no_structured_actions"
                warnings.append("Some assistant turns have no structured actions; their text is retained without guessing commands.")
        elif role == "tool":
            cid = message.get("tool_call_id")
            if cid is not None and (not isinstance(cid, str) or not cid):
                raise InputError(f"{p}/tool_call_id must be a nonempty string when present")
            event(events, kind="feedback", text=text, pointer=p + "/content", media=media,
                  actor="harness" if extra.get("synthetic") else "environment",
                  source_call_id="swe-rl:" + cid if cid else None,
                  link_basis="source_call_id" if cid else "unlinked",
                  feedback_origin="harness" if extra.get("synthetic") else "environment", **shared)
        elif role == "user":
            if not initial_user and not extra.get("synthetic"):
                event(events, kind="instruction", text=text, pointer=p + "/content", actor="user", media=media, **shared)
                initial_user = True
            else:
                event(events, kind="context", text=text, pointer=p + "/content", media=media,
                      actor="harness" if extra.get("synthetic") else "unclassified_user", **shared)
                warnings.append("Later user-role messages are retained as context, not inferred authorized objective changes.")
        else:
            event(events, kind="message", text=text, pointer=p + "/content", actor="system", media=media, **shared)
    if assistant_turns != doc["n_steps"]:
        warnings.append(f"Producer n_steps={doc['n_steps']} differs from {assistant_turns} recorded assistant turns.")


def grading_source(trajectory_path, document, grading_path):
    """Explicit filename pairing plus content binding; never search nearby files."""
    trajectory_path, grading_path = Path(trajectory_path), Path(grading_path)
    data = json.loads(grading_path.read_text(encoding="utf-8-sig"))
    return pair_grading(trajectory_path.name, document, grading_path.name, data)


def pair_grading(trajectory_name, document, grading_name, data):
    if not isinstance(trajectory_name, str) or not isinstance(grading_name, str):
        raise InputError("Grading pairing requires trajectory and grading filenames")
    trajectory_path, grading_path = Path(trajectory_name), Path(grading_name)
    if trajectory_path.name != trajectory_name or grading_path.name != grading_name:
        raise InputError("Grading pairing accepts basenames, not file paths")
    if not isinstance(document, dict) or not matches(document):
        raise InputError("--grading is supported only for the SWE RL messages export")
    if grading_path.name != trajectory_path.stem + "_rewards.json":
        raise InputError("Grading filename must match the trajectory basename plus _rewards.json")
    if not trajectory_path.stem.startswith(document["instance_id"] + "_"):
        raise InputError("Trajectory basename does not match its recorded instance_id")
    if not isinstance(data, dict):
        raise InputError("Grading record must be an object")
    return {"kind": "swe_rl_grading", "name": grading_path.name, "data": data,
            "scope": {"trajectory_content_hash": digest(document), "task_id": document["instance_id"],
                      "trajectory_name": trajectory_path.name, "join_basis": "matching archive basename; caller-supplied pairing"}}
