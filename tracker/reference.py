"""Frozen, prediction-blind reference packets and explicit benchmark denominators.

This module never calls a model, changes source runs, or turns review overrides
into independent reference labels. Human provenance is declared, not authenticated.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import json

from .contracts import catalog, CONTRACT_VERSION
from .jev import packet, QUESTIONS, JEV_HARNESS, JevClient, selection_profile
from .observe import analyze, MODES, HARNESS_VERSION
from .schema import InputError, digest
from .sequence import observe as sequence

REFERENCE_VERSION = "reference-benchmark/1"
FIELDS = ("mode", "feedback_response")


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _fingerprint(case):
    return digest({k: v for k, v in case.items() if k != "case_hash"})


def prepare(bundles, output, *, group_map=None, per_run=12, seed="reference-pilot-1"):
    if isinstance(per_run, bool) or not isinstance(per_run, int) or not 0 <= per_run <= 10000:
        raise InputError("per_run must be 0 (all) or 1-10000")
    output = Path(output)
    if output.exists():
        raise InputError("Reference output must be a new directory; existing annotations are never overwritten")
    group_map = group_map or {}
    if not isinstance(group_map, dict):
        raise InputError("Group map must map run IDs to group/split/exposure objects")
    cases, predictions, inventory, seen_runs = [], [], [], set()
    group_splits, task_groups, source_splits = {}, {}, {}
    for bundle in sorted(bundles, key=lambda b: b["run"]["id"]):
        run = bundle["run"]
        rid = run["id"]
        if rid in seen_runs:
            raise InputError("Duplicate run in reference preparation")
        seen_runs.add(rid)
        metadata = run["metadata"]
        grouping = group_map.get(rid, {})
        if not isinstance(grouping, dict):
            raise InputError("Each group-map entry must be an object")
        group = grouping.get("group", metadata.get("task_id") or "unassigned")
        split = grouping.get("split", "development")
        exposure = grouping.get("exposure", "previously_inspected")
        if not isinstance(group, str) or not group.strip() or split not in {"development", "holdout"}:
            raise InputError("Supply a nonempty group and development/holdout split")
        if exposure not in {"previously_inspected", "unseen"}:
            raise InputError("Exposure must be previously_inspected or unseen")
        if split == "holdout" and (not grouping.get("group") or exposure != "unseen"):
            raise InputError("Holdout requires an explicit group and declared unseen exposure")
        if group in group_splits and group_splits[group] != split:
            raise InputError("A reference group cannot cross development and holdout")
        group_splits[group] = split
        source_hash = digest(run["raw"])
        if source_hash in source_splits and source_splits[source_hash] != split:
            raise InputError("Identical source content cannot cross development and holdout")
        source_splits[source_hash] = split
        task = metadata.get("task_id")
        if task and task in task_groups and task_groups[task] != group:
            raise InputError("Runs of one task must share a reference group")
        if task:
            task_groups[task] = group
        # Use unreviewed observations; displayed retrospective corrections are not
        # allowed to improve the baseline used for independent validation.
        model = bundle.get("model_observations", {})
        if any(o.get("_reviews") for o in model.values()):
            raise InputError("Model predictions contain review overlays; export raw model observations")
        analysis = analyze(run, model)
        actions = analysis["actions"]
        selected = sorted(actions, key=lambda a: digest([seed, rid, a["event_id"]]))[:per_run or len(actions)]
        selected_ids = {a["event_id"] for a in selected}
        selected = [a for a in actions if a["event_id"] in selected_ids]
        by_id = {e["id"]: e for e in run["events"]}
        run_cases = []
        for action in selected:
            eid = action["event_id"]
            request = packet(run, eid)
            if model.get(eid):
                provenance = model[eid].get("_provenance", {})
                if not JevClient(model=provenance.get("model")).cache_matches(model[eid], run, eid):
                    raise InputError("Stored prediction does not match this reference packet; reobserve or use an explicitly versioned external baseline")
            # A reference reviewer can inspect the whole available actor prefix,
            # and separately assess the exact bounded inspector context.
            # Model labels, policy metadata, final reward and future results are
            # excluded. Raw trace text itself may still reveal model identity.
            prefix = [{k: deepcopy(e[k]) for k in ("id", "index", "kind", "text", "source_pointer", "trajectory_id", "copied_context", "tool", "arguments", "parent_id", "call_id", "source_call_id", "related_action_ids", "media") if k in e}
                      for e in run["events"] if e["trajectory_id"] == action["trajectory_id"] and e["index"] <= action["index"]]
            case = {"case_id": digest([REFERENCE_VERSION, rid, eid])[:24], "run_id": rid,
                    "event_id": eid, "source_hash": source_hash,
                    "group": group, "split": split, "trajectory_id": action["trajectory_id"],
                    "fields": {f: deepcopy(QUESTIONS[f]) for f in FIELDS},
                    "available_prefix": prefix, "inspector_state": request["state"],
                    "request_hash": digest(request),
                    "guidance": "Label from available prefix before opening predictions. Assess bounded-context sufficiency separately. Unknown and not-applicable are not negative observations."}
            case["case_hash"] = _fingerprint(case)
            cases.append(case)
            run_cases.append(case["case_id"])
            values = {}
            for field in FIELDS:
                obs = action["semantic"].get(field, {})
                values[field] = {
                    "value": action["mode"] if field == "mode" else obs.get("value", "unresolved"),
                    "status": "decided" if field == "mode" and action["mode"] != "unresolved" else obs.get("status", "unresolved"),
                    "basis": action["mode_basis"] if field == "mode" else obs.get("basis", "Jev" if obs else "not_observed"),
                    "method": "evidence_gate" if obs.get("source") == "evidence_gate" else "jev" if obs else "heuristic" if field == "mode" else "not_observed",
                    "probabilities": obs.get("probabilities", {}),
                }
            predictions.append({"case_id": case["case_id"], "case_hash": case["case_hash"], "values": values,
                                "profile": {"observation": HARNESS_VERSION, "semantic": deepcopy(model.get(eid, {}).get("_provenance", {}))}})
        inventory.append({"run_id": rid, "group": group, "split": split, "exposure": exposure,
                          "task_id": task, "adapter": run["adapter"], "adapter_version": run["adapter_version"],
                          "source_uri": metadata.get("source_uri"), "reference_scope": grouping.get("reference_scope", "unspecified"),
                          "actions": [{k: a[k] for k in ("event_id", "trajectory_id", "index", "parent_id", "feedback_opportunity")} for a in actions],
                          "case_ids": run_cases, "source_events": len(by_id), "selected_actions": len(selected),
                          "complete_action_sample": len(selected) == len(actions),
                          "selection_probability": min(1, per_run / len(actions)) if per_run and actions else 1,
                          "ingestion_state": (bundle.get("ingestion") or {}).get("state", "unrecorded")})
    if not cases:
        raise InputError("No eligible actions to prepare")
    if set(group_map) - seen_runs:
        raise InputError("Group map contains run IDs absent from the selected corpus")
    manifest = {"version": REFERENCE_VERSION, "contracts": catalog(), "semantic_harness": JEV_HARNESS,
                "selection": {"seed": seed, "per_run": per_run, "method": "Deterministic hash-ranked uniform action sample within each selected rollout; whole actor prefixes supplied. Not a population-random rollout sample."},
                "runs": inventory, "cases_hash": digest(cases),
                "limits": ["Default corpus is development data, not an unseen holdout.", "Group/exposure and human provenance are declared, not independently authenticated.", "Sparse labels cannot validate whole-rollout macro rates or closure.", "Predictions are frozen separately; do not give them to the reference reviewer.", "Source extraction still requires a separate raw-producer audit; normalized prefixes are not independent proof."]}
    manifest["manifest_hash"] = digest(manifest)
    predictions = [{**p, "manifest_hash": manifest["manifest_hash"]} for p in predictions]
    labels = [{"case_id": c["case_id"], "case_hash": c["case_hash"], "manifest_hash": manifest["manifest_hash"],
               "reviewer": None, "reference_kind": None, "values": {f: {"value": None, "evidence_ids": [], "note": "",
                    "extraction": "not_reviewed", "context_sufficiency": "not_reviewed"} for f in FIELDS}} for c in cases]
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(output / "cases.jsonl", cases)
    _write_jsonl(output / "predictions.jsonl", predictions)
    _write_jsonl(output / "labels.jsonl", labels)
    template = (Path(__file__).parent / "web/reference.html").read_text(encoding="utf-8")
    reviewer_data = json.dumps({"cases": cases, "labels": labels}, ensure_ascii=False).replace("<", "\\u003c")
    (output / "review.html").write_text(template.replace("__REFERENCE_DATA__", reviewer_data), encoding="utf-8")
    return {"output": str(output), "cases": len(cases), "runs": len(inventory), "manifest_hash": manifest["manifest_hash"],
            "reference_labels": 0, "holdout_cases": sum(c["split"] == "holdout" for c in cases)}


def _rates(records, choices):
    valid = [r for r in records if r["reference"] not in {"unresolved", "not_applicable"}]
    decided = [r for r in valid if r["prediction"] not in {None, "unresolved", "not_applicable"}]
    n, d = len(valid), len(decided)
    confusion = Counter((r["reference"], r["prediction"] or "missing_prediction") for r in records)
    per_class = {}
    for choice in choices:
        if choice in {"unresolved", "not_applicable"}:
            continue
        tp = sum(r["reference"] == choice and r["prediction"] == choice for r in valid)
        predicted = sum(r["prediction"] == choice for r in valid)
        support = sum(r["reference"] == choice for r in valid)
        per_class[choice] = {"support": support, "predicted": predicted, "true_positive": tp,
                             "precision": tp / predicted if predicted else None, "recall": tp / support if support else None}
    return {"reference_cases": len(records), "scorable_cases": n, "decided_cases": d,
            "decision_coverage": d / n if n else None,
            "selective_accuracy": sum(r["reference"] == r["prediction"] for r in decided) / d if d else None,
            "overall_correct_share": sum(r["reference"] == r["prediction"] for r in valid) / n if n else None,
            "ambiguous_reference_cases": sum(r["reference"] == "unresolved" for r in records),
            "resolved_on_ambiguous_reference": sum(r["reference"] == "unresolved" and r["prediction"] not in {None, "unresolved"} for r in records),
            "not_applicable_reference_cases": sum(r["reference"] == "not_applicable" for r in records),
            "missing_predictions": sum(r["prediction"] is None for r in records),
            "confusion": [{"reference": k[0], "prediction": k[1], "count": v} for k,v in sorted(confusion.items())],
            "per_class": per_class}


def _closure(actions):
    actors = defaultdict(list)
    for action in actions:
        actors[action["trajectory_id"]].append(action)
    output = {}
    for actor, rows in actors.items():
        if any(a["mode"] == "unresolved" for a in rows) or sequence(rows)["summary"]["excluded_batch_pairs"]:
            output[actor] = "unresolved"
            continue
        checks = [i for i,a in enumerate(rows) if a["mode"] == "verify"]
        output[actor] = "no_check_observed" if not checks else "application_after_check" if any(a["mode"] == "apply" for a in rows[checks[-1]+1:]) else "no_later_application_observed"
    return output


def evaluate(directory, labels_path=None, predictions_path=None, *, split="holdout"):
    if split not in {"development", "holdout"}:
        raise InputError("Choose development or holdout explicitly")
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("version") != REFERENCE_VERSION or manifest.get("contracts", {}).get("version") != CONTRACT_VERSION:
        raise InputError("Unsupported reference or measurement version")
    if digest({k:v for k,v in manifest.items() if k != "manifest_hash"}) != manifest.get("manifest_hash"):
        raise InputError("Reference manifest changed")
    cases = _read_jsonl(directory / "cases.jsonl")
    if digest(cases) != manifest["cases_hash"] or any(c.get("case_hash") != _fingerprint(c) for c in cases):
        raise InputError("Reference evidence changed")
    by_case = {c["case_id"]: c for c in cases}
    if len(by_case) != len(cases):
        raise InputError("Duplicate reference case")
    def load_records(path, kind):
        rows = _read_jsonl(path)
        indexed = {}
        for r in rows:
            cid = r.get("case_id")
            if cid not in by_case or cid in indexed:
                raise InputError(f"Unknown or duplicate {kind} case")
            if r.get("manifest_hash") != manifest["manifest_hash"] or r.get("case_hash") != by_case[cid]["case_hash"]:
                raise InputError(f"Stale {kind} evidence identity")
            indexed[cid] = r
        return indexed
    labels = load_records(labels_path or directory / "labels.jsonl", "reference")
    predictions = load_records(predictions_path or directory / "predictions.jsonl", "prediction")
    records = defaultdict(list)
    profiles = {}
    skips = Counter()
    evaluated = {}
    selected = [c for c in cases if c["split"] == split]
    for case in cases:
        cid = case["case_id"]
        reference = labels.get(cid, {})
        prediction = predictions.get(cid, {})
        if set(reference.get("values", {})) - set(FIELDS) or set(prediction.get("values", {})) - set(FIELDS):
            raise InputError("Unknown reference or prediction field")
        for field in FIELDS:
            label = reference.get("values", {}).get(field, {})
            value = label.get("value")
            pred = prediction.get("values", {}).get(field)
            if pred:
                if pred.get("value") not in QUESTIONS[field]["criteria"] or pred.get("status") not in {"decided", "unresolved", "not_applicable"}:
                    raise InputError("Invalid prediction value/status")
                if (pred["status"] == "not_applicable") != (pred["value"] == "not_applicable" and pred["status"] != "unresolved") or (pred["status"] == "decided" and pred["value"] == "unresolved"):
                    raise InputError("Contradictory prediction value/status")
            if value is None:
                if case["split"] == split:
                    skips[field + ".unlabeled"] += 1
                continue
            if value not in QUESTIONS[field]["criteria"]:
                raise InputError("Reference value is outside the metric contract")
            if reference.get("reference_kind") not in {"human", "model_proposal"} or not isinstance(reference.get("reviewer"), str) or not reference["reviewer"].strip():
                raise InputError("Labeled references need a reviewer and explicit human/model_proposal provenance")
            prefix_ids = {e["id"] for e in case["available_prefix"]}
            evidence = label.get("evidence_ids")
            if not isinstance(evidence, list) or not evidence or any(e not in prefix_ids for e in evidence):
                raise InputError("Reference evidence must cite supplied prefix events")
            if label.get("extraction") not in {"valid", "invalid", "uncertain"} or label.get("context_sufficiency") not in {"sufficient", "insufficient", "uncertain"}:
                raise InputError("Reference must assess extraction and inspector-context sufficiency")
            if case["split"] != split:
                continue
            if reference["reference_kind"] != "human":
                skips[field + ".model_proposal"] += 1
                continue
            if label["extraction"] != "valid":
                skips[field + ".extraction_" + label["extraction"]] += 1
                continue
            pv = pred["value"] if pred and pred["status"] in {"decided", "not_applicable"} else "unresolved" if pred else None
            stored_profile = prediction.get("profile", {})
            semantic_profile = stored_profile.get("semantic", {})
            profile = {"observation": stored_profile.get("observation"),
                       "model": semantic_profile.get("model"), "harness": semantic_profile.get("harness"),
                       "selection_policy": selection_profile(semantic_profile),
                       "method": pred.get("method", "jev" if "Jev" in pred.get("basis", "") else "heuristic" if field == "mode" else "not_observed") if pred else "missing",
                       "declared_external_profile": stored_profile.get("external")}
            profile_id = digest(profile)[:16]
            profiles[profile_id] = profile
            row = {"case_id": cid, "run_id": case["run_id"], "reference": value, "prediction": pv, "profile_id": profile_id,
                   "context_sufficiency": label["context_sufficiency"], "group": case["group"]}
            records[field].append(row)
            evaluated[(cid, field)] = row
    summaries = {f: _rates(records[f], QUESTIONS[f]["criteria"]) for f in FIELDS}
    context = {f: {status: _rates([r for r in records[f] if r["context_sufficiency"] == status], QUESTIONS[f]["criteria"])
                   for status in ("sufficient", "insufficient", "uncertain")} for f in FIELDS}
    adapters = {r["run_id"]: r["adapter"] for r in manifest["runs"]}
    adapter_slices = {adapter: {f: _rates([r for r in records[f] if adapters[r["run_id"]] == adapter], QUESTIONS[f]["criteria"]) for f in FIELDS}
                      for adapter in sorted(set(adapters.values()))}
    profile_slices = {pid: {"profile": profile, "metrics": {f: _rates([r for r in records[f] if r["profile_id"] == pid], QUESTIONS[f]["criteria"]) for f in FIELDS}}
                      for pid, profile in sorted(profiles.items())}
    macro = []
    case_by_event = {(c["run_id"], c["event_id"]): c["case_id"] for c in cases}
    for run in manifest["runs"]:
        if run["split"] != split:
            continue
        rows = []
        for action in run["actions"]:
            cid = case_by_event.get((run["run_id"], action["event_id"]))
            r = evaluated.get((cid, "mode"))
            if r is None or r["prediction"] is None:
                break
            rows.append((action, r))
        if not rows or len(rows) != len(run["actions"]):
            macro.append({"run_id": run["run_id"], "status": "incomplete_reference_or_predictions", "required_actions": len(run["actions"]), "covered_actions": sum((case_by_event.get((run["run_id"], a["event_id"])), "mode") in evaluated for a in run["actions"])})
            continue
        reference_actions = [{**a, "mode": r["reference"]} for a,r in rows]
        predicted_actions = [{**a, "mode": r["prediction"]} for a,r in rows]
        ref, pred = Counter(a["mode"] for a in reference_actions), Counter(a["mode"] for a in predicted_actions)
        n = len(rows)
        refseq, predseq = sequence(reference_actions)["summary"], sequence(predicted_actions)["summary"]
        count = refseq["observed_pairs"]
        transitions = sorted(set(refseq["counts"]) | set(predseq["counts"]))
        macro.append({"run_id": run["run_id"], "status": "complete_reference", "actions": n,
                      "purpose_share_error": {m: (pred[m]-ref[m])/n for m in MODES},
                      "reference_unresolved_actions": ref["unresolved"],
                      "transition_share_error": {k: (predseq["counts"].get(k,0)-refseq["counts"].get(k,0))/count for k in transitions} if count else None,
                      "eligible_pairs": count,
                      "closure": {"reference": _closure(reference_actions), "prediction": _closure(predicted_actions),
                                  "scope": "Recorded sequence only; trajectory completion and artifact freshness are not established."}})
    return {"version": REFERENCE_VERSION, "manifest_hash": manifest["manifest_hash"], "split": split,
            "status": "no_reference_labels" if not any(records.values()) else "reference_evaluated",
            "selected_cases": len(selected), "reference_groups": sorted({r["group"] for rs in records.values() for r in rs}),
            "metrics": summaries, "context_slices": context, "adapter_slices": adapter_slices,
            "profile_slices": profile_slices, "mixed_predictor_profiles": len(profiles) > 1, "excluded": dict(skips), "macro": macro,
            "limits": ["Declared human provenance is not authenticated and disagreement adjudication is external.",
                       "Classification scores are conditional on valid extraction; extraction failures are reported separately.",
                       "Pooled results can mix predictor methods; use profile slices before attributing scores to Jev or another model.",
                       "Unresolved and not-applicable reference labels are disclosed separately from ordinary class accuracy.",
                       "Within-rollout action samples and repeated actions are correlated; no action-IID confidence intervals are reported.",
                       "Macro outputs require complete action references; no checkpoint-shift validity is established by this report."]}
