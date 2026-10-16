"""Evidence availability and one shared definition of action/result linkage.

Availability is not semantic accuracy. Missing evidence never becomes a negative
behavior label, and source records remain the authority behind every count.
"""
from collections import Counter, defaultdict

CAPABILITY_VERSION = "measurement-evidence/1"


def links(run):
    actions = [e for e in run["events"] if e["kind"] == "action" and not e.get("copied_context")]
    by_id = {a["id"]: a for a in actions}
    calls = defaultdict(list)
    for action in actions:
        if action.get("call_id"):
            calls[(action["trajectory_id"], action["call_id"])].append(action)
    joined, records, unlinked = defaultdict(list), [], []
    for feedback in run["events"]:
        if feedback["kind"] != "feedback" or feedback.get("copied_context"):
            continue
        if feedback.get("source_call_id"):
            targets = calls[(feedback["trajectory_id"], feedback["source_call_id"])]
        else:
            targets = [by_id[a] for a in feedback.get("related_action_ids", []) if a in by_id]
        # No linking None == None; no future actions, copied actions, cross-agent
        # association or ambiguous duplicate identifiers.
        if len(targets) != 1 or targets[0]["trajectory_id"] != feedback["trajectory_id"] or targets[0]["index"] >= feedback["index"]:
            unlinked.append(feedback["id"])
            continue
        action = targets[0]
        joined[action["id"]].append(feedback)
        records.append({"action_id": action["id"], "feedback_id": feedback["id"],
            "basis": feedback.get("link_basis") or ("adapter call correspondence" if feedback.get("source_call_id") else "adapter related action"),
            "origin": feedback.get("feedback_origin", "environment" if feedback.get("actor") == "environment" else "unclassified")})
    previous, prior = {}, {}
    for action in actions:
        prior[action["id"]] = previous.get(action["trajectory_id"])
        previous[action["trajectory_id"]] = action
    batches = Counter((a["trajectory_id"], a["parent_id"]) for a in actions if a.get("parent_id"))
    return {"by_action": dict(joined), "records": records, "unlinked_ids": unlinked,
            "prior_by_action": prior, "batch_sizes": batches}


def feedback_support(run, action, linked=None):
    linked = linked if linked is not None else links(run)
    prior = linked["prior_by_action"].get(action["id"])
    result = {"status": "not_applicable", "reason": "No earlier non-copied action is recorded in this agent trajectory.",
              "prior_action_id": prior["id"] if prior else None, "feedback_ids": [], "opportunity": False}
    if prior is None:
        return result
    batches = linked["batch_sizes"]
    if any(batches.get((e["trajectory_id"], e.get("parent_id")), 0) > 1 or e.get("batch_size", 0) > 1 for e in (prior, action)):
        return {**result, "status": "unresolved", "reason": "The adjacent action pair touches a multi-action expression; execution order is unestablished."}
    replies = [e for e in linked["by_action"].get(prior["id"], []) if e["index"] < action["index"]]
    result.update(feedback_ids=[e["id"] for e in replies], opportunity=bool(replies))
    if not replies:
        return {**result, "status": "unresolved", "reason": "No corresponding result is recorded before this action."}
    if not any(e["text"].strip() for e in replies):
        return {**result, "status": "unresolved", "reason": "The linked result contains no usable text for this measurement."}
    if any(e.get("media") or e.get("subagent_refs") for e in replies):
        return {**result, "status": "unresolved", "reason": "The linked result references media or delegated evidence not read by this text measurement."}
    return {**result, "status": "available", "reason": "A preceding action and its linked textual feedback are recorded before the current action."}


def withheld(support, original=None):
    value = "not_applicable" if support["status"] == "not_applicable" else "unresolved"
    result = {"value": value, "status": value, "source": "evidence_gate", "probabilities": {},
              "basis": support["reason"], "support": support}
    if original and original.get("source") != "evidence_gate":
        result["withheld_observation"] = original
    return result


def inspect(run, actions):
    events = run["events"]
    linked = links(run)
    source_actions = [e for e in events if e["kind"] == "action" and not e.get("copied_context")]
    supports = [feedback_support(run, e, linked) for e in source_actions]
    available = sum(s["status"] == "available" for s in supports)
    opportunities = sum(s["opportunity"] for s in supports)
    unresolved_contexts = sum(s["status"] == "unresolved" for s in supports)
    batches = Counter((e["trajectory_id"], e.get("parent_id")) for e in source_actions if e.get("parent_id"))
    ambiguous_batches = sum(n > 1 for n in batches.values())
    objectives = [e["id"] for e in events if e["kind"] == "instruction" and e["text"].strip() and not e.get("copied_context")]
    unresolved = sum(a["mode"] == "unresolved" for a in actions)
    unparsed = sum(e.get("action_extraction") == "no_structured_actions" for e in events if not e.get("copied_context"))
    continuation_missing = any("continuation" in w.lower() and ("not loaded" in w.lower() or "missing" in w.lower()) for w in run.get("warnings", []))
    termination = run.get("outcome", {}).get("termination")
    ending = bool(isinstance(termination, str) and termination.strip()) or bool((run.get("outcome", {}).get("producer_lifecycle") or {}).get("finished_at"))
    measurements = {
        "work_sequence": {"status": "unavailable" if not actions else "limited" if unresolved or ambiguous_batches or not objectives or unparsed else "available",
            "reason": "Purpose labels remain unvalidated; unknown purposes and ambiguous-order pairs stay explicit.",
            "counts": {"actions": len(actions), "unresolved_purposes": unresolved, "multi_action_expressions": ambiguous_batches,
                       "expressions_without_structured_actions": unparsed}},
        "feedback_response": {"status": "available" if available and not unresolved_contexts else "limited" if available else "not_applicable" if supports and not unresolved_contexts else "unavailable",
            "reason": "Only ordered pairs with linked textual feedback can be submitted for response classification.",
            "counts": {"linked_opportunities": opportunities, "text_supported_opportunities": available,
                       "unresolved_contexts": unresolved_contexts,
                       "no_prior_action": sum(s["status"] == "not_applicable" for s in supports)}},
        "verification_closure": {"status": "available" if actions and not unresolved and not ambiguous_batches and not unparsed and ending and not continuation_missing else "limited" if actions else "unavailable",
            "reason": "Observed checks can be inspected. Whole-trajectory closure also requires resolved purposes, unambiguous order and a recorded ending; artifact freshness is unrecorded.",
            "counts": {"unresolved_purposes": unresolved, "multi_action_expressions": ambiguous_batches,
                       "ending_recorded": ending, "missing_continuation": continuation_missing}},
    }
    return {"version": CAPABILITY_VERSION, "measurements": measurements,
        "source": {"actions": len(source_actions), "linked_feedback": len(linked["records"]),
            "unlinked_feedback_ids": linked["unlinked_ids"], "feedback_origins": dict(Counter(r["origin"] for r in linked["records"])),
            "link_bases": dict(Counter(r["basis"] for r in linked["records"])), "objective_event_ids": objectives,
            "recorded_checkpoint": run["metadata"].get("checkpoint"), "recorded_task": run["metadata"].get("task_id"),
            "artifact_versions": "unrecorded"},
        "definition": "Availability describes the recorded evidence, not validated measurement accuracy. Missing observations, unsupported modalities and ambiguous ordering remain visible."}
