"""Replay source-held-out public dispatch readings; references are not model inputs.

The bundled fixture contains actual observations and exact normalized event
records, but omits private simulator/evaluator state. It is a development probe,
not human ground truth or an independent population-accuracy benchmark.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker import execution_reports
from tracker.jev import JevClient, validate_answers
from tracker.schema import InputError, digest, dumps
from tracker.semantic_extraction import (read, write, request as semantic_request,
    activity_choices, PURPOSE_ACTIVITY_ROUTING, PURPOSE_RULE)
from tracker.semantic_map import evidence
from tracker.semantic_workspace import DEFAULT_CONTEXT

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/heldout-generalization-evidence.json"
QUESTION = ("Choose exactly one activity for this established contribution. Supporting rationale, purpose or "
            "politeness are content. Classify what this unit itself does; requesting another actor to check "
            "something is Coordinate, not this agent performing Verify.")


def source_request(run, event_id, layer, model):
    """Build current production packets directly from normalized source events."""
    if layer == "macro":
        request = JevClient(model=model).request(run, event_id)
        request["questions"] = {"mode": request["questions"]["mode"]}
        return request
    if layer == "activity":
        request = semantic_request(run, evidence(run, event_id), "activity", QUESTION,
            activity_choices(PURPOSE_ACTIVITY_ROUTING), context_policy=deepcopy(DEFAULT_CONTEXT),
            expression_form="recorded action dispatch", activity_routing=PURPOSE_ACTIVITY_ROUTING)
        request["questions"]["choice"]["instructions"] += " " + PURPOSE_RULE
        request["model"] = model
        return request
    if layer == "executor_report":
        pairs = [(action, response) for action, response in execution_reports.bound_responses(run)
                 if action["id"] == event_id]
        if len(pairs) != 1:
            raise InputError("Expected one exact native executor response")
        request = execution_reports.request(run, *pairs[0])
        request["model"] = model
        return request
    raise InputError("Unknown reading layer")


def requests(fixture, *, current=False):
    cases = {case["case_id"]: case for case in fixture["review"]["cases"]}
    for row in fixture["observations"]:
        case = cases[row["case_id"]]
        source = fixture["sources"][fixture["case_source_views"][case["case_id"]]]
        if digest(source["run"]) != source["projection_hash"]:
            raise InputError("Frozen event projection changed")
        if not current and "request" in row:
            request = deepcopy(row["request"])
            if digest(request) != row["request_hash"]:
                raise InputError("Frozen request changed: " + row["id"])
            yield row, request
            continue
        request = source_request(source["run"], case["event_id"], row["layer"], fixture["model"])
        if row["layer"] == "executor_report":
            # This field identifies the original full recording, not the model's
            # evidence. The exact visible event records survive privacy projection.
            # Preserve the historical source binding rather than mislabeling the
            # original live receipt as having consumed the new projection digest.
            request["state"]["source_hash"] = source["original_source_hash"]
        if not current and digest(request) != row["request_hash"]:
            raise InputError("Current reader differs from frozen request: " + row["id"])
        yield row, request


def evaluate(directory="outputs/heldout-generalization-replay", *, live=False, client=None,
             fixture_path=FIXTURE, max_calls=21):
    fixture = read(fixture_path)
    if type(max_calls) is not int or max_calls < 0:
        raise InputError("max_calls must be a nonnegative integer")
    root = Path(directory)
    cases = {case["case_id"]: case for case in fixture["review"]["cases"]}
    model = client or JevClient(model=fixture["model"])
    if model.model != fixture["model"]:
        raise InputError("Client model differs from frozen protocol")
    rows, groups, calls = [], {}, 0
    for original, request in requests(fixture, current=live):
        row = {key: deepcopy(original[key]) for key in ("id", "case_id", "layer", "answer_keys", "request_hash")}
        row["reference_request_hash"] = original["request_hash"]
        row["request_hash"] = digest(request)
        receipt = root / "receipts" / (row["request_hash"] + ".json")
        response = None
        if not live:
            response = original["response"]
            if digest(response) != original["response_hash"]:
                raise InputError("Frozen response changed")
            row["response_origin"] = "frozen_live_observation"
        elif receipt.exists():
            saved = read(receipt)
            if saved["request"] != request:
                raise InputError("Cached request differs")
            response = saved["response"]
            row["response_origin"] = "cached"
        elif calls < max_calls:
            response = model.transport(request)
            calls += 1
            row["response_origin"] = "live"
        group = groups.setdefault(row["layer"], dict(requests=0, completed=0, scored_answers=0, reference_matches=0, mismatches=[]))
        group["requests"] += 1
        if response is None:
            row["status"] = "pending"
        else:
            if response.get("model") != request["model"]:
                raise InputError("Response model differs")
            answers = validate_answers(response, request)
            case = cases[row["case_id"]]
            expected = ({"mode": case["references"]["macro_mode"]} if row["layer"] == "macro" else
                        {"choice": case["references"]["activity"]} if row["layer"] == "activity" else
                        {key: case["executor_report_reference"][key] for key in row["answer_keys"]})
            row.update(status="complete", response_hash=digest(response), scores={})
            group["completed"] += 1
            for key in row["answer_keys"]:
                prediction = answers[key]["value"] if answers[key]["status"] == "decided" else answers[key]["status"]
                row["scores"][key] = dict(prediction=prediction, reference=expected[key], reference_match=prediction == expected[key])
                group["scored_answers"] += 1
                group["reference_matches"] += int(prediction == expected[key])
                if prediction != expected[key]:
                    group["mismatches"].append(row["id"] + "/" + key)
            write(receipt, dict(request=request, response=response))
        rows.append(row)
        print(row["id"], dumps(row.get("scores", row["status"])), flush=True)
    report = dict(schema="heldout-generalization-results/2", model=model.model,
        status="complete" if all(row["status"] == "complete" for row in rows) else "pending",
        new_calls_this_invocation=calls, fixture_hash=digest(fixture),
        pre_live_review_hash=fixture["pre_live_review_hash"], groups=groups, results=rows,
        scope=fixture["review"]["scope"], reference_reader_protocols=fixture["review"]["reader_protocols"],
        request_origin="current_readers" if live else "frozen_live_requests")
    write(root / "report.json", report)
    return {key: value for key, value in report.items() if key != "results"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/heldout-generalization-replay")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prompt-key", action="store_true")
    parser.add_argument("--max-calls", type=int, default=21)
    args = parser.parse_args()
    if args.live and args.prompt_key:
        os.environ["JEV_API_KEY"] = getpass.getpass("Jev credential for this process: ")
    print(dumps(evaluate(args.output, live=args.live, fixture_path=args.fixture, max_calls=args.max_calls)))
