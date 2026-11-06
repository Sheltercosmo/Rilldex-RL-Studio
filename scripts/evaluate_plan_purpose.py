"""Controlled Plan/Coordinate clarification on saved source-bound requests.

The five recorded baselines are replayed, not submitted again. Two optional
wording controls have fresh two-message source documents and regenerated
references. References are model-reviewed development judgments, never model
inputs or human ground truth; the ambiguous simulation baseline is unscored.
No network is used unless ``live=True`` (or ``--live``) is explicitly supplied.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest, dumps
from tracker.semantic_extraction import checked_span, read, request as activity_request, write
from tracker.semantic_map import evidence


CLARIFICATION = (
    "Imperative grammar alone does not establish a request to another actor. "
    "Use the recorded speaker, addressee, and capabilities to determine whose work "
    "the passage organizes or requests. Multiple substantive stages of the agent's "
    "own intended work can be Plan, including self-guidance phrased as imperatives. "
    "An explicit request that another actor act, supply information, or authorize "
    "an action remains Coordinate even when it contains ordered stages. Available "
    "tools indicate possible capabilities, not proof of who is being addressed or "
    "what was done. A single local next step is not thereby Plan. If ownership or "
    "addressing remains genuinely ambiguous, do not invent an addressee. Use only "
    "the source and context available at this unit's cutoff; later execution must "
    "never be used to settle the interpretation. An expressed plan or request "
    "does not establish execution or success."
)

RECORDED_CASES = (
    ("simulation", "e2", {
        "status": "ambiguous", "label": None,
        "plausible_labels": ["plan", "coordinate"],
        "note": "Ordered movement and verification, but the imperative does not explicitly name its addressee. No hard-correct label.",
    }),
    ("service", "e2", {
        "status": "development_reference", "label": "plan",
        "note": "Model-reviewed reading: organize reservation followed by retrieval/checking. Implicit addressee remains a limitation, as in simulation.",
    }),
    ("software", "e2", {
        "status": "development_reference", "label": "plan",
        "note": "Model-reviewed reading: organize reproduction, repair, and retesting. Implicit addressee remains a limitation, as in simulation.",
    }),
    ("multiagent", "e4", {
        "status": "development_reference", "label": "coordinate",
        "note": "The recorded delegate dispatch explicitly assigns the inspection to worker; it does not itself inspect the lot.",
    }),
    ("public_airline", "e10", {
        "status": "development_reference", "label": "coordinate",
        "note": "The current contribution asks the user to confirm cancellation. Its asserted refund eligibility is not certified as true.",
    }),
)

WORDING_CONTROLS = (
    ("simulation_first_person", "plan",
     "I will first follow the north corridor to G; then I will read the position sensor and check that the rover reached G."),
    ("simulation_addressed_user", "coordinate",
     "Please do the following yourself on your console: first follow the north corridor to G; then read the position sensor and tell me whether the rover reached G."),
)


def _validate_source(request, run):
    """Audit exact references and prefix scope without assessing semantics."""
    state = request["state"]
    cutoff = state["subject"]
    current = checked_span(run, cutoff, cutoff)
    if state["cutoff_event_id"] != current["id"] or state["cutoff_codepoint"] != cutoff["end"]:
        raise ValueError("Request cutoff differs from its subject")
    events = {event["id"]: event for event in run["events"]}
    ref_count = 0

    def walk(value):
        nonlocal ref_count
        if isinstance(value, dict):
            if {"event_id", "source_pointer", "start", "end", "text"} <= value.keys():
                checked_span(run, value, cutoff)
                ref_count += 1
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(state)
    for item in state["prefix"]:
        event = events[item["id"]]
        if event["index"] > current["index"]:
            raise ValueError("Future event in activity prefix")
        if (event["trajectory_id"], event.get("context_id")) != (current["trajectory_id"], current.get("context_id")):
            raise ValueError("Cross-trajectory/context activity prefix")
        if event["source_pointer"] != item["source_pointer"] or event["actor"] != item["actor"]:
            raise ValueError("Prefix attribution differs from source")
        if not item.get("text_projection"):
            expected = event["text"][:cutoff["end"]] if event["id"] == current["id"] else event["text"]
            if item["text"] != expected:
                raise ValueError("Unprojected prefix text differs from source")
    return {"exact_references_checked": ref_count, "prefix_events_checked": len(state["prefix"]),
            "cutoff_event_id": current["id"], "future_events_present": False}


def _load_recorded(workspaces, name, event_id, reference):
    root = Path(workspaces) / name
    config = read(root / "workspace.json")
    source_path = root / "runs" / (config["run_id"] + ".json")
    run = read(source_path)
    selected = read(root / "results" / (config["run_id"] + ".json"))
    units = [unit for unit in selected["units"] if unit["source"]["event_id"] == event_id]
    if len(units) != 1:
        raise ValueError(f"Expected one selected unit at {name}/{event_id}")
    unit = units[0]
    decision_path = root / "decisions" / (unit["activity_request"] + ".json")
    saved = read(decision_path)
    original = deepcopy(saved["request"])
    if original["state"]["stage"] != "activity" or set(original["questions"]) != {"choice"}:
        raise ValueError("Saved decision is not a single activity choice")
    _validate_source(original, run)
    validate_answers(saved["response"], original)
    return dict(case_id=name, event_id=event_id, source_kind="recorded", run=run,
                reference=deepcopy(reference), original_request=original,
                original_response=deepcopy(saved["response"]),
                provenance={"source_path": str(source_path.resolve()), "source_hash": digest(run),
                            "run_id": run["id"], "unit_id": unit["id"],
                            "decision_path": str(decision_path.resolve()),
                            "saved_request_hash": digest(original),
                            "saved_response_hash": digest(saved["response"])})


def _synthetic_control(simulation, case_id, label, text):
    """Generate source and context afresh; never retain stale source quotations."""
    original = simulation["original_request"]
    initial = next(event for event in simulation["run"]["events"] if event["id"] == "e1")
    document = {
        "messages": [{"role": "user", "content": initial["text"]},
                     {"role": "assistant", "content": text}],
        "tools": deepcopy(simulation["run"]["raw"]["tools"]),
    }
    run = normalize(document)[0]
    current = next(event for event in run["events"] if event["actor"] == "agent")
    ref = evidence(run, current["id"])
    # The recorded reading proposal describes the old wording. Do not copy it,
    # its source references, or its request hash into this new source control.
    # Remove only its per-label prose augmentation, preserving fixed definitions.
    criteria = {key: value.split(" Candidate interpretation for this source:", 1)[0]
                for key, value in original["questions"]["choice"]["criteria"].items()}
    context = {key: deepcopy(original["state"][key]) for key in
               ("activity_routing", "expression_form", "contribution_scope") if key in original["state"]}
    fresh = activity_request(run, ref, "activity", original["questions"]["choice"]["instructions"],
                             criteria, deepcopy(original["state"].get("context_policy")), **context)
    fresh["model"] = original["model"]
    _validate_source(fresh, run)
    return dict(case_id=case_id, event_id=current["id"], source_kind="synthetic_wording_control",
                run=run, document=document, original_request=fresh, original_response=None,
                reference={"status": "development_reference", "label": label,
                           "note": "Model-authored wording control with explicit work ownership; not human-labeled evidence."},
                provenance={"source_hash": digest(run), "document_hash": digest(document), "run_id": run["id"],
                            "derived_from_case": "simulation", "derived_from_source_hash": simulation["provenance"]["source_hash"],
                            "reconstruction": "New two-message document normalized and all context/subject references regenerated. No later events exist.",
                            "candidate_policy": "No inherited candidate reading or candidate-specific criterion prose; both arms share this policy."})


def cases(workspaces="outputs/generated-generalization-refined", include_variants=True):
    rows = [_load_recorded(workspaces, *case) for case in RECORDED_CASES]
    if include_variants:
        rows.extend(_synthetic_control(rows[0], *control) for control in WORDING_CONTROLS)
    return rows


def evaluate(directory="outputs/plan-purpose", workspaces="outputs/generated-generalization-refined",
             live=False, client=None, include_variants=True):
    """Prepare/replay offline; submit only uncached new arms when live=True.

    ``client`` may be a JevClient with a bounded transport supplied by the caller.
    With variants enabled, this uses at most nine new requests: seven clarified
    arms and two synthetic baselines. Five actual baselines reuse saved responses.
    """
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    source_cases = cases(workspaces, include_variants)
    rows, manifest, groups = [], [], {}
    active_client = client or JevClient()
    for case in source_cases:
        case_id = case["case_id"]
        if case["source_kind"] == "synthetic_wording_control":
            source_path = root / "sources" / case_id / "run.json"
            write(source_path, case["run"])
            write(source_path.with_name("document.json"), case["document"])
            case["provenance"]["source_path"] = str(source_path.resolve())
        base = case["original_request"]
        case_manifest = {key: deepcopy(case[key]) for key in ("case_id", "event_id", "source_kind", "reference", "provenance")}
        case_manifest["arms"] = {}
        for arm in ("original", "ownership_clarification"):
            req = deepcopy(base)
            if arm == "ownership_clarification":
                req["questions"]["choice"]["instructions"] += " " + CLARIFICATION
                expected = deepcopy(req)
                expected["questions"]["choice"]["instructions"] = base["questions"]["choice"]["instructions"]
                if expected != base:
                    raise ValueError("Clarification changes more than choice instructions")
            audit = _validate_source(req, case["run"])
            key = digest(req)
            request_path = root / "requests" / case_id / arm / (key + ".json")
            receipt_path = root / "receipts" / (key + ".json")
            write(request_path, req)
            result = {"case_id": case_id, "event_id": case["event_id"], "source_kind": case["source_kind"],
                      "arm": arm, "request_hash": key, "source_hash": digest(case["run"]),
                      "reference": deepcopy(case["reference"]), "audit": audit,
                      "request_path": str(request_path.relative_to(root))}
            case_manifest["arms"][arm] = {"request_hash": key, "request_path": result["request_path"], "audit": audit}
            response = None
            if arm == "original" and case["original_response"] is not None:
                response = case["original_response"]
                result["response_origin"] = "replayed_saved_observation"
                write(receipt_path, {"request": req, "response": response,
                                     "provenance": case["provenance"]})
            elif receipt_path.exists():
                saved = read(receipt_path)
                if saved["request"] != req:
                    raise ValueError("Cached request differs")
                response = saved["response"]
                result["response_origin"] = "cached_new_observation"
            elif live:
                if active_client.model != req["model"]:
                    raise ValueError("Client model differs from saved-request model")
                response = active_client.transport(req)
                validate_answers(response, req)
                write(receipt_path, {"request": req, "response": response})
                result["response_origin"] = "live_new_observation"
            else:
                result.update(status="prepared", prediction=None, reference_match=None)
            group = groups.setdefault(arm, {"planned": 0, "completed": 0, "pending": 0,
                                           "scored_development_references": 0, "reference_matches": 0,
                                           "unscored_ambiguous": 0, "predictions": {}})
            group["planned"] += 1
            if response is not None:
                answer = validate_answers(response, req)["choice"]
                prediction = answer["value"] if answer["status"] == "decided" else answer["status"]
                scored = case["reference"]["status"] != "ambiguous"
                result.update(status="complete", prediction=prediction,
                              reference_match=(prediction == case["reference"]["label"]) if scored else None,
                              probabilities=answer["probabilities"], response_hash=digest(response),
                              receipt_path=str(receipt_path.relative_to(root)))
                group["completed"] += 1
                group["predictions"][prediction] = group["predictions"].get(prediction, 0) + 1
                if scored:
                    group["scored_development_references"] += 1
                    group["reference_matches"] += int(result["reference_match"])
                else:
                    group["unscored_ambiguous"] += 1
            else:
                group["pending"] += 1
            rows.append(result)
            print(case_id, case["event_id"], arm, result["prediction"] or "prepared", flush=True)
        manifest.append(case_manifest)

    pairs = []
    for case in source_cases:
        pair = {row["arm"]: row for row in rows if row["case_id"] == case["case_id"]}
        left, right = pair["original"], pair["ownership_clarification"]
        pairs.append({"case_id": case["case_id"], "reference_status": case["reference"]["status"],
                      "original": left["prediction"], "ownership_clarification": right["prediction"],
                      "changed": left["prediction"] != right["prediction"]
                      if left["status"] == right["status"] == "complete" else None})
    report = {"schema": "plan-purpose-ablation/1", "model": source_cases[0]["original_request"]["model"],
              "status": "complete" if all(row["status"] == "complete" for row in rows) else "prepared_partial",
              "groups": groups, "pairs": pairs, "results": rows,
              "scope": "Five actual activity requests and optional two synthetic wording controls. Each pair changes only generic choice instructions. Actual baselines replay prior observations; synthetic controls have no inherited candidate proposals. References are model-reviewed development judgments, not human ground truth, and are never sent to the model. Simulation original remains ambiguous and unscored; implicit addressee is also a limitation of the service/software development labels. This is a small prompt-sensitivity probe, not a population accuracy estimate.",
              "no_future_policy": "Every subject/reference is checked against normalized source and cutoff. Every prefix remains within its recorded trajectory/context and at or before cutoff. Synthetic documents contain only the task and tested utterance. No later execution is used to resolve the label."}
    write(root / "manifest.json", {"schema": "plan-purpose-manifest/1", "clarification": CLARIFICATION,
                                    "references_sent_to_model": False, "cases": manifest})
    write(root / "report.json", report)
    return {key: value for key, value in report.items() if key != "results"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/plan-purpose")
    parser.add_argument("--workspaces", default="outputs/generated-generalization-refined")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prompt-key", action="store_true")
    parser.add_argument("--no-variants", action="store_true")
    args = parser.parse_args()
    if args.live and args.prompt_key:
        os.environ["JEV_API_KEY"] = getpass.getpass("Jev credential for this process: ")
    print(dumps(evaluate(args.output, args.workspaces, args.live, include_variants=not args.no_variants)))
