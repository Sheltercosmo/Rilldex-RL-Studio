"""Bounded identity/order probe; never replaces production observations.

Run with python -m scripts.check_candidate_stability RUN_ID OUTPUT --prompt-key.
This is an engineering sensitivity check, not an annotation accuracy estimate.
"""
import argparse
import copy
import getpass
import json
import os
from pathlib import Path

from tracker.jev import DEFAULT_MODEL, JEV_HARNESS, JevClient, packet, validate_answers
from tracker.schema import digest
from tracker.store import Store


def renamed_request(request):
    request = copy.deepcopy(request)
    criteria = request["questions"]["focus_goal"]["criteria"]
    ids = sorted(k for k in criteria if k not in {"unresolved", "no_suitable_candidate"})
    mapping = {key: f"candidate-{len(ids)-i:03d}" for i,key in enumerate(ids)}
    request["questions"]["focus_goal"]["criteria"] = {mapping.get(k,k): v for k,v in criteria.items()}
    candidates = request["state"]["goal_candidates"]
    for candidate in candidates["candidates"]:
        candidate["id"] = mapping[candidate["id"]]
    candidates["root_id"] = mapping.get(candidates["root_id"], candidates["root_id"])
    candidates["candidate_set_hash"] = digest(candidates["candidates"])
    return request, {v:k for k,v in mapping.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id"); parser.add_argument("output")
    parser.add_argument("--db", default=".tracker/tracker.sqlite")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--prompt-key", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("Use 1–10 probe actions")
    if args.prompt_key:
        os.environ["JEV_API_KEY"] = getpass.getpass("Jev API key (not saved): ")
    store = Store(args.db); bundle = store.get(args.run_id, raw=True)
    client = JevClient()
    saved = bundle["model_observations"]
    eligible = [a["event_id"] for a in bundle["analysis"]["actions"] if
                saved.get(a["event_id"], {}).get("_provenance", {}).get("harness") == JEV_HARNESS]
    # Cover the whole rollout deterministically, rather than only its beginning.
    chosen = eligible if len(eligible) <= args.limit else [eligible[round(i*(len(eligible)-1)/max(1,args.limit-1))] for i in range(args.limit)]
    report = {"run_id": args.run_id, "model": DEFAULT_MODEL, "harness": JEV_HARNESS,
              "probe": "Remap opaque goal IDs to reverse their lexical order; all candidate descriptions unchanged.",
              "limits": "Single repeated observation per action. Same development trace; not held-out accuracy or calibrated stability evidence.", "results": []}
    for aid in chosen:
        request, inverse = renamed_request({**packet(bundle["run"], aid), "model": DEFAULT_MODEL})
        response = client.transport(request)
        if response.get("model") != DEFAULT_MODEL:
            raise ValueError("Unexpected provider model")
        observed = validate_answers(response, request)["focus_goal"]
        baseline = saved[aid]["focus_goal"]
        mapped_value = inverse.get(observed["value"], observed["value"])
        report["results"].append({"event_id": aid, "request_hash": digest(request),
            "baseline": {"value":baseline["value"], "status":baseline["status"], "probabilities":baseline["probabilities"]},
            "probe": {"value":mapped_value, "status":observed["status"],
                      "probabilities":{inverse.get(k,k):v for k,v in observed["probabilities"].items()}},
            "same_choice":mapped_value == baseline["value"], "same_status":observed["status"] == baseline["status"],
            "usage":response.get("usage")})
        # Save completed probes even if a later request fails.
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"event_id":aid, "same_choice":report["results"][-1]["same_choice"], "same_status":report["results"][-1]["same_status"]}), flush=True)


if __name__ == "__main__":
    main()
