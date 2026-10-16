"""Conservative observations: semantic interpretations are separate from source facts."""
from __future__ import annotations

import re
import shlex
from collections import Counter, defaultdict

from .schema import digest
from .jev import selection_profile
from .goals import track as track_goals
from .evidence import inspect as inspect_evidence
from .sequence import observe as observe_sequence
from .capabilities import links, feedback_support, withheld, inspect as inspect_capabilities

HARNESS_VERSION = "macro/0.8.0"
MODES = ("explore", "apply", "verify", "coordinate", "report", "unresolved")
MODE_LABELS = {"explore": "Explore", "apply": "Apply approach", "verify": "Verify",
               "coordinate": "Coordinate", "report": "Report", "unresolved": "Unresolved"}


def goal_scope(semantic):
    """Map the selected relationship; never let regrouping overrule its choice."""
    original = semantic.get("goal_relation", {})
    if original.get("source") == "review" and original.get("status") == "decided":
        value = {"direct": "connected", "supporting": "connected", "outside": "outside", "conflicting": "conflicting"}.get(original.get("value"), "unresolved")
        return {"value": value, "status": "decided" if value != "unresolved" else "unresolved", "probabilities": {}, "basis": "reviewed goal relationship"}
    p = original.get("probabilities", {})
    if not p:
        return {"value": "unresolved", "status": "unresolved", "probabilities": {}, "basis": "not observed"}
    probabilities = {"connected": p.get("direct", 0) + p.get("supporting", 0),
                     "outside": p.get("outside", 0), "conflicting": p.get("conflicting", 0),
                     "unresolved": p.get("unresolved", 0)}
    value = {"direct": "connected", "supporting": "connected", "outside": "outside", "conflicting": "conflicting"}.get(original.get("value"), "unresolved")
    missing = original.get("evidence", {}).get("missingness", {})
    decided = original.get("status") == "decided" and value != "unresolved"
    decided = decided and not missing.get("required_truncated_event_ids", missing.get("truncated_event_ids")) and not missing.get("objective_missing")
    return {"value": value if decided else "unresolved", "status": "decided" if decided else "unresolved",
            "probabilities": probabilities, "basis": "selected goal relationship mapped to scope; grouped probabilities are descriptive only"}


def action_features(action: dict) -> dict:
    text, tool, args = action["text"].strip(), action.get("tool", ""), action.get("arguments", {})
    try:
        parts = shlex.split(text, posix=True)
    except ValueError:
        parts = text.split()
    command = parts[0] if parts else ""
    mode, basis = "unresolved", "unrecognized tool semantics"
    # A compound shell program is not safely described by its first executable.
    compound = bool(re.search(r"(?:&&|\|\||;|(?<!\|)\|(?!\|))", text))
    if tool in {"read_file", "file_read", "web_search", "search", "list_files"}:
        mode, basis = "explore", "tool schema convention"
    elif tool in {"write_file", "file_write", "edit_file", "apply_patch"}:
        mode, basis = "apply", "tool schema convention"
    elif tool in {"run_tests", "test", "pytest"}:
        mode, basis = "verify", "tool schema convention"
    elif tool in {"delegate", "spawn_agent", "ask_user"}:
        mode, basis = "coordinate", "tool schema convention"
    elif tool in {"submit", "finish"}:
        mode, basis = "report", "tool schema convention"
    elif not compound:
        if command in {"ls", "pwd", "cat", "head", "tail", "rg", "grep", "find", "find_file", "search_file", "search_dir", "open", "goto", "scroll_up", "scroll_down"}:
            mode, basis = "explore", "recognized read/search command"
        elif command in {"edit", "create", "apply_patch", "touch", "mkdir"}:
            mode, basis = "apply", "recognized modification command"
        elif command in {"pytest", "unittest"} or re.match(r"python\S*\s+-m\s+(pytest|unittest)\b", text) or re.match(r"(?:npm|pnpm|yarn)\s+test\b", text):
            mode, basis = "verify", "recognized test invocation"
        elif command == "submit":
            mode, basis = "report", "submission command"
    resource = next((str(args[k]) for k in ("path", "file_path", "filename", "url", "query") if args.get(k)), None)
    if not resource:
        if command in {"open", "cat", "head", "tail", "create", "pytest"} and len(parts) > 1:
            resource = next((p for p in parts[1:] if not p.startswith("-")), None)
        elif command in {"find_file", "search_file", "search_dir", "rg", "grep", "find"}:
            resource = "search: " + " ".join(parts[1:])
    resource = resource or ("workspace" if command in {"ls", "pwd", "goto", "scroll_up", "scroll_down"} else f"{tool}: {command or 'action'}")
    return {"mode": mode, "mode_basis": basis, "resource": resource[:180], "command": command,
            "signature": digest({"tool": tool, "arguments": args, "text": text}),
            "observation_status": "heuristic" if mode != "unresolved" else "unresolved"}


def analyze(run: dict, semantic: dict | None = None) -> dict:
    events = run["events"]
    by_id = {e["id"]: e for e in events}
    linked = links(run)
    goals = [{"id": f"g{i+1}", "text": e["text"], "evidence": [e["id"]],
              "trajectory_id": e["trajectory_id"], "kind": "recorded instruction", "index": e["index"]}
             for i, e in enumerate(events) if e["kind"] == "instruction" and not e["copied_context"]]
    actions, seen, prior_by_actor, seen_feedback, targets = [], {}, {}, {}, {}
    for e in events:
        if e["kind"] != "action" or e["copied_context"]:
            continue
        actor = e["trajectory_id"]
        feat = action_features(e)
        obs = linked["by_action"].get(e["id"], [])
        support = feedback_support(run, e, linked)
        prior = prior_by_actor.get(actor)
        key = (actor, feat["signature"])
        previous_occurrence = seen.get(key)
        latest_goal = next((g for g in reversed(goals) if g["trajectory_id"] == actor and g["index"] < e["index"]), None)
        semantic_observations = dict((semantic or {}).get(e["id"], {}))
        if support["status"] != "available":
            semantic_observations["feedback_response"] = withheld(support, semantic_observations.get("feedback_response"))
        scope = goal_scope(semantic_observations)
        mode_obs = semantic_observations.get("mode", {})
        observer = "Reviewer" if mode_obs.get("source") == "review" else "Jev"
        if mode_obs.get("status") == "decided" and mode_obs.get("value") in MODES:
            feat.update(mode=mode_obs["value"], mode_basis=f"{observer} observation", observation_status="reviewed" if observer == "Reviewer" else "semantic")
        elif mode_obs:
            suggestion = feat["mode"]
            feat.update(mode="unresolved", mode_basis=f"{observer} abstained; heuristic suggestion was {suggestion}", observation_status="unresolved")
        exact_repeat = previous_occurrence is not None
        consecutive = bool(prior and prior["signature"] == feat["signature"])
        prior_feedback = seen_feedback.get(key)
        current_feedback = [o["text"] for o in obs]
        # Equality of result text is deliberately not equality of environment state.
        same_result = bool(exact_repeat and current_feedback and prior_feedback == current_feedback)
        target_key = (actor, feat["resource"])
        last_target = targets.get(target_key)
        target_visit = "first" if last_target is None else "continued" if prior and prior["resource"] == feat["resource"] else "returned"
        a = {"event_id": e["id"], "index": e["index"], "trajectory_id": actor,
             **feat, "text": e["text"], "tool": e.get("tool"), "goal_id": latest_goal["id"] if latest_goal else None,
             "feedback_ids": [o["id"] for o in obs], "parent_id": e.get("parent_id"),
             "feedback_opportunity": support["opportunity"], "feedback_support": support,
             "exact_repeat": exact_repeat, "consecutive_repeat": consecutive,
             "previous_occurrence": previous_occurrence, "same_result_text": same_result,
             "consecutive_run_length": prior["consecutive_run_length"] + 1 if consecutive else 1,
             "target_visit": target_visit, "previous_target_action": last_target,
             "macro": {"goal_scope": scope}, "semantic": semantic_observations}
        actions.append(a)
        seen[key] = e["id"]
        seen_feedback[key] = current_feedback
        prior_by_actor[actor] = a
        targets[target_key] = e["id"]
    goal_tracking = track_goals(run, actions)
    episodes = []
    for a in actions:
        # Contiguous mode/goal episodes are a presentation grouping, not inferred intent.
        if episodes and all(episodes[-1][k] == a[k] for k in ("mode", "goal_id", "focus_goal_id", "trajectory_id")):
            episodes[-1]["event_ids"].append(a["event_id"])
        else:
            episodes.append({"id": f"p{len(episodes)+1}", "mode": a["mode"], "goal_id": a["goal_id"],
                             "focus_goal_id": a["focus_goal_id"], "trajectory_id": a["trajectory_id"], "event_ids": [a["event_id"]]})
    resources, modes, edges, prior_nodes = {}, {}, Counter(), {}
    for a in actions:
        rid = digest({"actor": a["trajectory_id"], "resource": a["resource"]})[:12]
        node = resources.setdefault(rid, {"id": rid, "label": a["resource"], "trajectory_id": a["trajectory_id"], "event_ids": [], "modes": Counter(), "revisits": 0})
        node["event_ids"].append(a["event_id"]); node["modes"][a["mode"]] += 1
        node["revisits"] += int(a["exact_repeat"])
        a["resource_id"] = rid
        actor = a["trajectory_id"]
        if actor in prior_nodes:
            edges[(prior_nodes[actor], rid)] += 1
        prior_nodes[actor] = rid
        modes.setdefault(a["mode"], []).append(a["event_id"])
    sequence = observe_sequence(actions)
    transitions = Counter((p["source"],p["target"]) for p in sequence["pairs"])
    distribution = {m: len(modes.get(m, [])) for m in MODES}
    n = len(actions)
    metrics = {
        "actions": n, "mode_counts": distribution,
        "sequence": sequence["summary"],
        "exact_repeats": sum(a["exact_repeat"] for a in actions),
        "consecutive_repeats": sum(a["consecutive_repeat"] for a in actions),
        "same_result_repeats": sum(a["same_result_text"] for a in actions),
        "longest_identical_run": max((a["consecutive_run_length"] for a in actions), default=0),
        "linked_feedback": sum(bool(a["feedback_ids"]) for a in actions),
        "distinct_targets": len(resources), "copied_context_events": sum(e["copied_context"] for e in events),
        "target_returns": sum(a["target_visit"] == "returned" for a in actions),
        "goal_scope_counts": dict(Counter(a["macro"]["goal_scope"]["value"] for a in actions)),
        "completion_claims": sum(e.get("completion_claim") is True and not e["copied_context"] for e in events),
        "goal_assignments": goal_tracking["coverage"]["assigned"],
        "goal_returns": sum(t["kind"] == "return" for t in goal_tracking["transitions"]),
        "feedback_opportunities": sum(a["feedback_opportunity"] for a in actions),
        "feedback_response_counts": dict(Counter(
            a["semantic"].get("feedback_response", {}).get("value")
            if a["semantic"].get("feedback_response", {}).get("status") == "decided" else "unresolved"
            for a in actions if a["feedback_opportunity"])),
        "semantic_actions": sum(a["observation_status"] == "semantic" for a in actions),
        "unresolved_actions": distribution["unresolved"],
    }
    profiles = sorted({(o["_provenance"].get("model"), o["_provenance"].get("harness"),
                        selection_profile(o["_provenance"])) for o in (semantic or {}).values() if o.get("_provenance")})
    reviewed = any(o.get("_reviews") for o in (semantic or {}).values())
    scope_labels = {"connected": "Task connected", "outside": "Outside task", "conflicting": "Conflicting", "unresolved": "Unresolved"}
    scope_transitions, prior_scope = Counter(), {}
    for a in actions:
        actor, value = a["trajectory_id"], a["macro"]["goal_scope"]["value"]
        if actor in prior_scope:
            scope_transitions[(prior_scope[actor], value)] += 1
        prior_scope[actor] = value
    return {"harness_version": HARNESS_VERSION, "inspector_signature": digest({"profiles": profiles, "review": "review/1" if reviewed else None}) if profiles or reviewed else "heuristic",
            "inspector_profiles": profiles,
            "semantic_coverage": sum(bool(o.get("_provenance")) for o in (semantic or {}).values()),
            "reviewed_actions": sum(bool(o.get("_reviews")) for o in (semantic or {}).values()),
            "run_id": run["id"], "goals": goals, "goal_tracking": goal_tracking,
            "actions": actions, "episodes": episodes, "metrics": metrics, "sequence":sequence,
            "verification": inspect_evidence(run, actions), "capabilities": inspect_capabilities(run, actions),
            "map": {"nodes": list(resources.values()), "edges": [{"source": s, "target": t, "count": v} for (s,t),v in edges.items()]},
            "flow": {"nodes": [{"id": m, "label": MODE_LABELS[m], "event_ids": modes.get(m, [])} for m in MODES],
                     "edges": [{"source": s, "target": t, "count": v} for (s,t),v in transitions.items()]},
            "scope_flow": {"nodes": [{"id": m, "label": label, "event_ids": [a["event_id"] for a in actions if a["macro"]["goal_scope"]["value"] == m]} for m,label in scope_labels.items()],
                           "edges": [{"source": s, "target": t, "count": v} for (s,t),v in scope_transitions.items()]},
            "definitions": {"repeat": "Exact tool, argument and command equality after a previous occurrence in the same agent trajectory. This does not establish wasted work.",
                            "map": "Nodes are observed work targets. Edges follow recorded action order within an agent; spatial distance has no semantic meaning.",
                            "mode": "Conservative command/tool heuristics until Jev observations are present. Apply approach does not establish optimal exploitation.",
                            "sequence":sequence["definition"],
                            "goals": goal_tracking["definition"],
                            "goal_scope": "Task-connected maps a selected direct or supporting relationship. Grouped probabilities are descriptive and do not override the selected option. No probability or confidence floor is applied.",
                            "target_return": "A target is revisited after at least one action on another target in the same agent. This is separate from repeating an identical command."}}
