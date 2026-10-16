"""Stable, extractive goal candidates and evidence-bounded pursuit transitions.

Candidate presence is not pursuit, and pursuit is not attainment. The registry
does not merge paraphrases or silently replace a user's original objective.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from .schema import digest

GOAL_VERSION = "goals/2"
UNRESOLVED = "unresolved"
NO_CANDIDATE = "no_suitable_candidate"
PLAN_PATTERN = re.compile(
    r"(?:^|(?<=[.!?])\s+)(?P<plan>(?:(?:First|Next|Now|Then)[,:]?\s+)?(?:"
    r"(?:I|We|we)\s+(?:will|shall|need to|should|am going to|are going to)|"
    r"(?:I|We|we)['’]ll|[Ll]et['’]s|Let us|Plan:)"
    r"[^\n]{3,1200}?(?:[.!?](?=\s|$)|$))", re.MULTILINE)


def _plan_spans(e):
    text = e["text"]
    try:
        decoded = json.loads(text)
    except (ValueError, TypeError):
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("plan"), str) and decoded["plan"].strip():
        plan = decoded["plan"].strip()
        if len(plan) <= 1200:
            yield plan, {"format": "json-string", "key": "plan"}, "structured plan field"
        return
    # Code, quotes and tool output are not the model's expressed commitments.
    hidden = [(m.start(), m.end()) for m in re.finditer(r"```.*?```|(?m:^>[^\n]*$)", text, re.S)]
    spans = []
    for match in PLAN_PATTERN.finditer(text):
        start, end = match.span("plan")
        if any(start < right and end > left for left, right in hidden):
            continue
        # Adjacent commitments form one literal plan block. Splitting a plan and
        # its immediately stated implementation into competing Choice options
        # creates artificial ambiguity. This is an extractive block, not a
        # semantic paraphrase merge or a claim that all steps share one goal.
        if spans and text[spans[-1][1]:start].isspace() and end - spans[-1][0] <= 1200:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    for start, end in spans:
        yield text[start:end], {"start": start, "end": end, "unit": "unicode-codepoint"}, "expressed-plan block candidate"


def catalog(run):
    goals, by_key, roots, instructions = [], {}, {}, []

    def add(text, e, kind, selector=None, basis=None):
        key = (e["trajectory_id"], kind, " ".join(text.split()).casefold())
        reference = {"event_id": e["id"], "index": e["index"], "source_pointer": e["source_pointer"],
                     "selector": selector, "copied_context": e["copied_context"]}
        if key in by_key:
            by_key[key]["references"].append(reference)
            return by_key[key]
        goal = {"id": "g-" + digest(key)[:14], "text": text, "trajectory_id": e["trajectory_id"],
                "kind": kind, "basis": basis, "first_index": e["index"], "references": [reference],
                "attainment": "unobserved"}
        goals.append(goal); by_key[key] = goal
        return goal

    for e in run["events"]:
        actor = e["trajectory_id"]
        if e["kind"] == "instruction" and e["text"].strip():
            if actor not in roots:
                g = add(e["text"], e, "recorded_objective", basis="retained initial instruction" if e["copied_context"] else "initial source instruction")
                roots[actor] = g["id"]
            else:
                g = add(e["text"], e, "retained_context" if e["copied_context"] else "additional_instruction",
                        basis="source user-role context; supersession not inferred")
            instructions.append({"goal_id": g["id"], "event_id": e["id"], "index": e["index"],
                                 "trajectory_id": actor, "kind": g["kind"], "copied_context": e["copied_context"]})
        if e["actor"] == "agent" and e["kind"] in {"message", "reasoning"} and not e["copied_context"]:
            for text, selector, basis in _plan_spans(e):
                add(text, e, "expressed_plan", selector, basis)
    return {"version": GOAL_VERSION, "goals": goals, "roots": roots, "instruction_ledger": instructions}


def applicable_root(registry, actor):
    """A delegated agent can inherit an ancestor task if no local task is recorded."""
    while actor:
        if actor in registry["roots"]:
            return registry["roots"][actor]
        actor = actor.rpartition("/")[0]
    return None


def focus_candidates(run, action_id, registry=None, limit=16):
    registry = registry or catalog(run)
    action = action_id if isinstance(action_id, dict) else next(e for e in run["events"] if e["id"] == action_id)
    root_id = applicable_root(registry, action["trajectory_id"])
    available = []
    for g in registry["goals"]:
        refs = [r for r in g["references"] if r["index"] < action["index"]]
        if not refs or g["kind"] in {"retained_context", "additional_instruction"}:
            continue
        if g["trajectory_id"] != action["trajectory_id"] and g["id"] != root_id:
            continue
        available.append({**g, "references": refs, "last_index": refs[-1]["index"]})
    # Root plus current explicit plans and recent older plans. No future reference
    # may leak into this action's packet, even when a phrase occurs again later.
    roots = [g for g in available if g["id"] == root_id]
    plans = sorted((g for g in available if g["id"] != root_id), key=lambda g: g["last_index"], reverse=True)
    included = roots + plans[:max(0, limit-len(roots))]
    return {"candidates": included, "omitted_count": len(available)-len(included), "root_id": root_id,
            "cutoff": action["id"] if "id" in action else action["event_id"], "candidate_set_hash": digest(included)}


def focus_question(candidate_packet):
    criteria = {g["id"]: {"goal": g["text"], "origin": g["kind"],
                           "evidence_events": [r["event_id"] for r in g["references"]]}
                for g in candidate_packet["candidates"]}
    criteria[NO_CANDIDATE] = "The action has an observable work objective, but no supplied candidate expresses it. Do not choose a vaguely related goal."
    criteria[UNRESOLVED] = "The action's current focus is ambiguous or insufficient evidence is available."
    return {"type": "choice", "instructions": "Which supplied goal is the narrowest explicit work objective pursued by `current_action`, given `parent_expression`, recorded instructions and previous actions? Choose an existing goal again when work returns to it. A newly mentioned plan is only a candidate; it must match the action. Do not infer completion, hidden motives or an unexpressed subgoal. Candidate IDs are identifiers; judge their descriptions.", "criteria": criteria}


def track(run, actions, registry=None):
    registry = registry or catalog(run)
    goals = {g["id"]: {**g, "event_ids": [], "pursuit_status": "candidate" if g["kind"] == "expressed_plan" else "recorded",
                        "visits": 0, "returns": 0, "modes": Counter()} for g in registry["goals"]}
    previous, seen, transitions, assignments = {}, defaultdict(set), [], []
    edges = Counter()
    for action in actions:
        actor, eid = action["trajectory_id"], action["event_id"]
        observation = action["semantic"].get("focus_goal", {})
        candidates = focus_candidates(run, action, registry)
        valid = {g["id"] for g in candidates["candidates"]}
        gid = observation.get("value") if observation.get("status") == "decided" and observation.get("value") in valid else None
        status = "decided" if gid else "no_suitable_candidate" if observation.get("status") == NO_CANDIDATE else "unresolved"
        assignment = {"event_id": eid, "goal_id": gid, "status": status,
                      "root_id": candidates["root_id"], "trajectory_id": actor,
                      "source": observation.get("source", "jev") if observation else "unobserved",
                      "candidate_set_hash": candidates["candidate_set_hash"], "omitted_candidates": candidates["omitted_count"]}
        assignments.append(assignment)
        action["focus_goal_id"] = gid
        action["goal_id"] = candidates["root_id"]
        if gid:
            goal = goals[gid]; goal["event_ids"].append(eid); goal["modes"][action["mode"]] += 1
            before = previous.get(actor)
            if before == gid:
                transition = "continue"
            elif before is None and gid in seen[actor]:
                transition = "focus_reobserved"
                goal["visits"] += 1
            elif gid in seen[actor]:
                transition = "return"
                goal["returns"] += 1; goal["visits"] += 1
            else:
                transition = "first_focus" if before is None else "switch"
                goal["visits"] += 1
            transitions.append({"event_id": eid, "from": before, "to": gid, "kind": transition,
                                "trajectory_id": actor, "basis": "action-to-goal assignments, not inferred intention"})
            if before:
                edges[(before, gid)] += 1
            previous[actor] = gid; seen[actor].add(gid)
        else:
            # Do not draw a continuous goal edge through unobserved behavior.
            previous[actor] = None
    for actor, gid in previous.items():
        if gid:
            goals[gid]["pursuit_status"] = "last_observed_focus"
    for g in goals.values():
        if g["event_ids"] and g["pursuit_status"] != "last_observed_focus":
            g["pursuit_status"] = "previously_pursued"
    unresolved_ids = [a["event_id"] for a in assignments if not a["goal_id"]]
    graph_nodes = [{"id": g["id"], "label": "Initial task · " + g["trajectory_id"] if g["kind"] == "recorded_objective" else g["text"], "event_ids": g["event_ids"], "modes": g["modes"],
                    "goal_status": g["pursuit_status"]} for g in goals.values() if g["event_ids"] or g["id"] in registry["roots"].values()]
    if unresolved_ids:
        graph_nodes.append({"id": "unresolved-focus", "label": "Unresolved work objective", "event_ids": unresolved_ids,
                            "modes": {"unresolved": len(unresolved_ids)}, "goal_status": "unresolved"})
    return {**registry, "goals": list(goals.values()), "assignments": assignments, "transitions": transitions,
            "coverage": {"eligible": len(actions), "assigned": len(actions)-len(unresolved_ids), "unresolved": len(unresolved_ids),
                         "plan_candidates": sum(g["kind"] == "expressed_plan" for g in goals.values()),
                         "pursued_plans": sum(g["kind"] == "expressed_plan" and bool(g["event_ids"]) for g in goals.values())},
            "graph": {"nodes": graph_nodes, "edges": [{"source": s, "target": t, "count": count} for (s,t),count in edges.items()]},
            "definition": "Goals come from recorded instructions or exact model-authored plans. Focus requires a semantic selection or review. Return means a previously selected goal is selected again; attainment remains unobserved without verification."}
