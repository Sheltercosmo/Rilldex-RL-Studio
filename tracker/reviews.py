"""Append-only reviews are observations, not edits to a model's original answer."""
from __future__ import annotations

from copy import deepcopy

from .goals import focus_candidates, focus_question
from .schema import InputError

REVIEW_VERSION = "review/1"


def options(run, event_id):
    from .jev import QUESTIONS
    event = next((e for e in run["events"] if e["id"] == event_id), None)
    if event is None or event["kind"] != "action" or event["copied_context"]:
        raise InputError("Review subject must be a non-copied action in this run")
    candidate_packet = focus_candidates(run, event_id)
    questions = {**QUESTIONS, "focus_goal": focus_question(candidate_packet)}
    return {key: q["criteria"] for key,q in questions.items()}


def validate(run, payload):
    if not isinstance(payload, dict):
        raise InputError("Review must be an object")
    if "value" not in payload:
        raise InputError("Review requires an explicit value; null clears an existing review")
    choices = options(run, payload.get("event_id"))
    field, value = payload.get("field"), payload.get("value")
    if field not in choices:
        raise InputError("Unknown review field")
    if value is not None and (not isinstance(value, str) or value not in choices[field]):
        raise InputError("Review value must be one of this event's available options")
    reviewer, note = payload.get("reviewer", ""), payload.get("note", "")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
        raise InputError("Supply a reviewer label of 1–120 characters")
    if not isinstance(note, str) or len(note) > 4000:
        raise InputError("Review note must contain at most 4,000 characters")
    revision = payload.get("expected_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise InputError("Review requires a nonnegative expected_revision")
    evidence = payload.get("evidence_ids", [payload["event_id"]])
    valid = {e["id"] for e in run["events"]}
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 64 or any(not isinstance(e, str) or e not in valid for e in evidence):
        raise InputError("Review evidence must reference 1–64 existing events")
    return {"event_id": payload["event_id"], "field": field, "value": value,
            "reviewer": reviewer.strip(), "note": note, "evidence_ids": list(dict.fromkeys(evidence)),
            "expected_revision": revision, "version": REVIEW_VERSION}


def apply(observations, reviews):
    result = deepcopy(observations)
    latest = {}
    for r in reviews:
        latest[(r["event_id"], r["field"])] = r
    for (eid, field), r in latest.items():
        if r["value"] is None:
            continue
        observation = result.setdefault(eid, {})
        status = "unresolved" if r["value"] == "unresolved" else "not_applicable" if r["value"] == "not_applicable" else "no_suitable_candidate" if r["value"] == "no_suitable_candidate" else "decided"
        original = observation.get(field)
        observation[field] = {"value": r["value"], "status": status, "source": "review",
                              "probabilities": {}, "confidence": None, "review_id": r["id"],
                              "reviewer": r["reviewer"], "note": r["note"], "evidence_ids": r["evidence_ids"],
                              "annotation_mode": "retrospective", "model_observation": original}
        observation.setdefault("_reviews", []).append(r["id"])
    return result


def queue(run, analysis):
    """Group recurring unresolved cases; a queue entry is not a failure verdict."""
    grouped = {}
    assignments = {a["event_id"]: a for a in analysis["goal_tracking"]["assignments"]}
    for action in analysis["actions"]:
        reasons = []
        if action["mode"] == "unresolved":
            reasons.append("purpose unresolved")
        focus = assignments[action["event_id"]]
        if focus["status"] == "no_suitable_candidate":
            reasons.append("goal candidates do not cover observed work")
        elif focus["status"] == "unresolved" and "focus_goal" in action["semantic"]:
            reasons.append("goal focus unresolved")
        if not action["feedback_ids"]:
            reasons.append("result not recorded or not linked")
        if not reasons:
            continue
        key = (action["trajectory_id"], action["signature"], tuple(reasons))
        row = grouped.setdefault(key, {"event_ids": [], "reasons": reasons, "preview": action["text"][:180],
                                       "trajectory_id": action["trajectory_id"]})
        row["event_ids"].append(action["event_id"])
    return sorted(grouped.values(), key=lambda r: (-len(r["event_ids"]), r["event_ids"][0]))
