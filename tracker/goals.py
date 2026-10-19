"""Stable, extractive goal candidates and evidence-bounded pursuit transitions.

Candidate presence is not pursuit, and pursuit is not attainment. The registry
does not merge paraphrases or silently replace a user's original objective.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from .schema import digest
from .capabilities import recorded_scope
from .work_order import Evidence as OrderEvidence

GOAL_VERSION = "goals/4"
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
        if e.get("context_id") is not None: key = (*key, e["context_id"])
        reference = {"event_id": e["id"], "index": e["index"], "source_pointer": e["source_pointer"],
                     "selector": selector, "copied_context": e["copied_context"]}
        if key in by_key:
            by_key[key]["references"].append(reference)
            return by_key[key]
        goal = {"id": "g-" + digest(key)[:14], "text": text, "trajectory_id": e["trajectory_id"],
                "context_id": e.get("context_id"),
                "kind": kind, "basis": basis, "first_index": e["index"], "references": [reference],
                "attainment": "unobserved"}
        goals.append(goal); by_key[key] = goal
        return goal

    for e in sorted(run["events"], key=lambda e: e["index"]):
        actor = recorded_scope(e)
        if e["kind"] == "instruction" and e["text"].strip():
            if actor not in roots:
                g = add(e["text"], e, "recorded_objective", basis="retained initial instruction" if e["copied_context"] else "initial source instruction")
                roots[actor] = g["id"]
            else:
                g = add(e["text"], e, "retained_context" if e["copied_context"] else "additional_instruction",
                        basis="source user-role context; supersession not inferred")
            instructions.append({"goal_id": g["id"], "event_id": e["id"], "index": e["index"],
                                 "trajectory_id": e["trajectory_id"], "context_id": e.get("context_id"), "kind": g["kind"], "copied_context": e["copied_context"]})
        if e["actor"] == "agent" and e["kind"] in {"message", "reasoning"} and not e["copied_context"]:
            for text, selector, basis in _plan_spans(e):
                add(text, e, "expressed_plan", selector, basis)
    return {"version": GOAL_VERSION, "goals": goals,
            "roots": {actor:gid for (actor,context),gid in roots.items() if context is None},
            "context_roots": [dict(trajectory_id=actor,context_id=context,goal_id=gid)
                              for (actor,context),gid in roots.items() if context is not None],
            "instruction_ledger": instructions}


def applicable_root(registry, actor, context_id=None):
    """A delegated agent can inherit an ancestor task if no local task is recorded."""
    while actor:
        if context_id is None and actor in registry["roots"]:
            return registry["roots"][actor]
        for root in registry.get("context_roots", []):
            if (root["trajectory_id"],root["context_id"]) == (actor,context_id):
                return root["goal_id"]
        actor = actor.rpartition("/")[0]
    return None


def focus_candidates(run, action_id, registry=None, limit=16):
    registry = registry or catalog(run)
    action = action_id if isinstance(action_id, dict) else next(e for e in run["events"] if e["id"] == action_id)
    root_id = applicable_root(registry, action["trajectory_id"], action.get("context_id"))
    available = []
    for g in registry["goals"]:
        if g.get("context_id") != action.get("context_id"): continue
        refs = [r for r in g["references"] if r["index"] < action["index"]]
        if not refs or g["kind"] in {"retained_context", "additional_instruction"}:
            continue
        if g["trajectory_id"] != action["trajectory_id"] and g["id"] != root_id:
            continue
        available.append({**g, "references": refs, "last_index": refs[-1]["index"]})
    # Root plus current explicit plans and recent older plans. No future reference
    # may leak into this action's packet, even when a phrase occurs again later.
    roots = [g for g in available if g["id"] == root_id]
    if not roots: root_id = None
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
    transitions, assignments, points = [], [], []
    order = OrderEvidence({e['id']: e for e in run['events'] if not e.get('copied_context')})
    edges = Counter()
    for action in sorted(actions, key=lambda a: a['index']):
        actor, eid = action["trajectory_id"], action["event_id"]
        observation = action["semantic"].get("focus_goal", {})
        candidates = focus_candidates(run, action, registry)
        valid = {g["id"] for g in candidates["candidates"]}
        gid = observation.get("value") if observation.get("status") == "decided" and observation.get("value") in valid else None
        status = "decided" if gid else "no_suitable_candidate" if observation.get("status") == NO_CANDIDATE else "unresolved"
        assignment = {"event_id": eid, "goal_id": gid, "status": status,
                      "root_id": candidates["root_id"], "trajectory_id": actor,
                      "context_id": action.get("context_id"), "order_known": order.is_ordered(eid),
                      "source": observation.get("source", "jev") if observation else "unobserved",
                      "candidate_set_hash": candidates["candidate_set_hash"], "omitted_candidates": candidates["omitted_count"]}
        assignments.append(assignment)
        action["focus_goal_id"] = gid
        action["goal_id"] = candidates["root_id"]
        points.append({'event_id': eid, 'unit_id': eid, 'group_id': gid,
                       'identity_status': 'assigned' if gid else 'unresolved'})
        if gid:
            goal = goals[gid]; goal["event_ids"].append(eid); goal["modes"][action["mode"]] += 1
    labels = {'first': 'first_focus', 'switch': 'switch', 'returned': 'return',
              'continued': 'continue', 'resumed': 'continue', 'reobserved': 'focus_reobserved',
              'unordered': 'focus_observed_order_unknown'}
    tails = {}
    for row in order.recurrences(points):
        event = order.events[row['event_id']]
        tails[recorded_scope(event)] = row
        gid, before = row['group_id'], row['previous_group_id']
        if not gid: continue
        transition = labels[row['kind']]
        goal = goals[gid]
        goal['returns'] += int(transition == 'return')
        goal['visits'] += int(row['order_known'] and transition != 'continue')
        transitions.append({'event_id': row['event_id'], 'from': before, 'to': gid, 'kind': transition,
                            'trajectory_id': event['trajectory_id'], 'context_id': event.get('context_id'),
                            'previous_event_id': row['previous_event_id'], 'order_evidence': row['order_evidence'],
                            'basis': 'action-to-goal assignments with source order evidence; attainment is unobserved'})
        if before: edges[(before, gid)] += 1
    for row in tails.values():
        if row['group_id'] and row['order_known']:
            goals[row['group_id']]['pursuit_status'] = 'last_observed_focus'
    for g in goals.values():
        if g["event_ids"] and g["pursuit_status"] != "last_observed_focus":
            g["pursuit_status"] = "observed_focus"
    unresolved_ids = [a["event_id"] for a in assignments if not a["goal_id"]]
    root_ids = set(registry["roots"].values()) | {r['goal_id'] for r in registry.get('context_roots',[])}
    graph_nodes = [{"id": g["id"], "label": "Initial task · " + g["trajectory_id"] if g["kind"] == "recorded_objective" else g["text"], "event_ids": g["event_ids"], "modes": g["modes"],
                    "goal_status": g["pursuit_status"]} for g in goals.values() if g["event_ids"] or g["id"] in root_ids]
    if unresolved_ids:
        graph_nodes.append({"id": "unresolved-focus", "label": "Unresolved work objective", "event_ids": unresolved_ids,
                            "modes": {"unresolved": len(unresolved_ids)}, "goal_status": "unresolved"})
    return {**registry, "goals": list(goals.values()), "assignments": assignments, "transitions": transitions,
            "coverage": {"eligible": len(actions), "assigned": len(actions)-len(unresolved_ids), "unresolved": len(unresolved_ids),
                         "unordered_assignments": sum(bool(a['goal_id']) and not a['order_known'] for a in assignments),
                         "unresolved_recurrences": sum(t['kind'] == 'focus_reobserved' for t in transitions),
                         "plan_candidates": sum(g["kind"] == "expressed_plan" for g in goals.values()),
                         "pursued_plans": sum(g["kind"] == "expressed_plan" and bool(g["event_ids"]) for g in goals.values())},
            "graph": {"nodes": graph_nodes, "edges": [{"source": s, "target": t, "count": count} for (s,t),count in edges.items()]},
            "definition": "Goals come from recorded instructions or exact model-authored plans. Focus requires a semantic selection or review. Returns require ordered endpoints and observed intervening work on another goal in the same context; complete bracketed parallel dispatches are allowed. Unknown order preserves assignments without inventing edges or returns. Attainment remains unobserved without verification."}
