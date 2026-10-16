"""Prediction-blind, multi-label activity references and disagreement-aware scoring.

Human identity and blinding are declarations, not authentication. This workflow
does not call Jev, invent references, or promote model proposals to ground truth.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from .activity import ACTIVITIES, HARNESS, UNIT_VERSION, TAXONOMY_VERSION, SEGMENTATION_VERSION, packet, units, analyze
from .jev import SELECTION_POLICY
from .schema import InputError, digest, dumps
from .activity_context import visible_prefix as prefix, audit as audit_context
from .review_resolution import collect as collect_reviews, resolve as resolve_reviews
from .review_evidence import validate_spans

VERSION = "activity-reference/1"


def fingerprint(value, key):
    return digest({k: v for k, v in value.items() if k != key})


def build(bundles, *, per_kind=6, group_map=None, seed="activity-reference-1", selected_units=None):
    if isinstance(per_kind, bool) or not isinstance(per_kind, int) or not 0 <= per_kind <= 100:
        raise InputError("per-kind must be 0 (all) or 1–100")
    group_map = group_map or {}
    if not isinstance(group_map, dict) or selected_units is not None and not isinstance(selected_units, dict):
        raise InputError("Group map and selected units must be run-ID maps")
    cases, predictions, inventory = [], [], []
    corpus_bytes = 0
    group_splits, task_groups, source_splits, seen = {}, {}, {}, set()
    for bundle in sorted(bundles, key=lambda b: b["run"]["id"]):
        run = bundle["run"]; rid = run["id"]; meta = run["metadata"]
        if rid in seen: raise InputError("Duplicate run")
        seen.add(rid)
        grouping = group_map.get(rid, {})
        if not isinstance(grouping, dict): raise InputError("Each group entry must be an object")
        group = grouping.get("group", meta.get("task_id") or rid)
        split, exposure = grouping.get("split", "development"), grouping.get("exposure", "previously_inspected")
        if not isinstance(group, str) or not group.strip() or split not in {"development", "holdout"} or exposure not in {"previously_inspected", "unseen"}:
            raise InputError("Invalid reference grouping")
        if split == "holdout" and (not grouping.get("group") or exposure != "unseen"):
            raise InputError("Holdout requires an explicit task group and unseen declaration")
        source_hash = digest(run["raw"])
        task = meta.get("task_id")
        if group in group_splits and group_splits[group] != split or source_hash in source_splits and source_splits[source_hash] != split:
            raise InputError("A task group or identical source cannot cross splits")
        if task and task in task_groups and task_groups[task] != group:
            raise InputError("One task must retain one reference group")
        group_splits[group] = source_splits[source_hash] = split
        if task: task_groups[task] = group
        # Read raw saved observations, never a human correction overlay.
        observations = {r["event_id"]: r["result"] for r in bundle.get("activity_observation_history", [])}
        if any(o.get("_reviews") for o in observations.values()):
            raise InputError("Review overlays cannot be frozen as model predictions")
        analysis = analyze(run, observations)
        analyzed = {u["id"]: u for u in analysis["units"]}
        eligible = [u for u in units(run) if u["eligible"]]
        if selected_units is not None:
            chosen_ids = selected_units.get(rid, [])
            if not isinstance(chosen_ids, list) or len(set(chosen_ids)) != len(chosen_ids) or set(chosen_ids) - {u["id"] for u in eligible}:
                raise InputError("Selected units must be distinct eligible IDs")
            chosen = [u for u in eligible if u["id"] in chosen_ids]
        else:
            picked = set()
            for kind in ("model_span", "action_dispatch"):
                candidates = sorted((u for u in eligible if u["kind"] == kind), key=lambda u: digest([seed, rid, u["id"]]))
                picked.update(u["id"] for u in candidates[:per_kind or len(candidates)])
            chosen = [u for u in eligible if u["id"] in picked]
        for subject in chosen:
            request = packet(run, subject["id"])
            case = {"case_id": digest([VERSION, rid, subject["id"], HARNESS])[:24], "run_id": rid,
                    "group": group, "split": split, "source_hash": source_hash,
                    "adapter": run["adapter"], "domain": meta.get("environment", "unrecorded"),
                    "environment_family": meta.get("environment_family", "unrecorded"),
                    "subject": deepcopy(subject), "available_prefix": prefix(run, subject),
                    "fields": request["questions"], "inspector_state": request["state"],
                    "request_hash": digest(request)}
            case["case_hash"] = fingerprint(case, "case_hash")
            corpus_bytes += len(dumps(case).encode("utf-8"))
            if corpus_bytes > 32 * 1024 * 1024 or len(cases) >= 2000:
                raise InputError("Reference export exceeds 32 MiB or 2000 units; select fewer units/runs without truncating evidence")
            cases.append(case)
            observed = analyzed[subject["id"]]; saved = observed["observation"]
            p = saved.get("_provenance", {})
            values = {}
            for field in request["questions"]:
                raw = saved.get(field, {})
                value, status = raw.get("value"), raw.get("status", "unobserved")
                reason = raw.get("evidence_gate")
                if not observed["current_packet"]:
                    value, status = None, "stale" if saved else "unobserved"
                elif field == "revise" and value == "present" and field in observed["unresolved_activities"]:
                    status, reason = "unresolved", "Revision membership lacks a selected valid earlier reference."
                values[field] = {"value": value, "status": status, "evidence_gate": reason,
                                 "probabilities": raw.get("probabilities", {})}
            profile = {"model": p.get("model"), "harness": HARNESS, "unit_version": UNIT_VERSION,
                       "segmentation_version": SEGMENTATION_VERSION,
                       "taxonomy_version": TAXONOMY_VERSION, "selection_policy": SELECTION_POLICY,
                       "current_packet": observed["current_packet"]}
            predictions.append({"case_id": case["case_id"], "case_hash": case["case_hash"], "values": values, "profile": profile})
        inventory.append({"run_id": rid, "group": group, "split": split, "exposure": exposure,
                          "adapter": run["adapter"], "domain": meta.get("environment", "unrecorded"),
                          "environment_family": meta.get("environment_family", "unrecorded"),
                          "source_hash": source_hash, "eligible_by_kind": dict(Counter(u["kind"] for u in eligible)),
                          "sampled_by_kind": dict(Counter(u["kind"] for u in chosen))})
    if set(group_map) - seen or selected_units is not None and set(selected_units) - seen:
        raise InputError("Selection maps refer to absent runs")
    if not cases: raise InputError("No eligible reference units")
    manifest = {"version": VERSION, "harness": HARNESS, "unit_version": UNIT_VERSION, "taxonomy_version": TAXONOMY_VERSION,
                "segmentation_version": SEGMENTATION_VERSION,
                "selection_policy": SELECTION_POLICY, "seed": seed, "per_kind": per_kind,
                "sampling": "explicit development case list" if selected_units is not None else "hash-ranked sample separately within each run and unit kind",
                "runs": inventory, "cases_hash": digest(cases), "predictions_hash": digest(predictions),
                "limits": ["Normalized evidence is not independent verification of raw extraction.",
                           "Reviewer identity and blindness are declared, not authenticated.",
                           "Two agreeing independent human reviews or explicit adjudication are required for scored references.",
                           "Model proposals and prediction-exposed reviews remain inspectable but do not enter human accuracy scores.",
                           "This sample does not establish whole-trajectory or training-shift accuracy."]}
    manifest["manifest_hash"] = fingerprint(manifest, "manifest_hash")
    return {"manifest": manifest, "cases": cases, "predictions": predictions}


def files(package):
    manifest = package["manifest"]
    blind = {"version": VERSION, "manifest_hash": manifest["manifest_hash"], "cases": package["cases"], "limits": manifest["limits"]}
    template = (Path(__file__).parent / "web/activity-reference.html").read_text(encoding="utf-8")
    return {"manifest.json": json.dumps(manifest, indent=2),
            "cases.jsonl": "".join(dumps(c) + "\n" for c in package["cases"]),
            "predictions.jsonl": "".join(dumps(p) + "\n" for p in package["predictions"]),
            "annotations.jsonl": "",
            "review.html": template.replace("__ACTIVITY_REFERENCE_DATA__", json.dumps(blind, ensure_ascii=False).replace("<", "\\u003c")),
            "README.txt": "Give only review.html to each independent reviewer. It contains no model predictions.\n"
                          "Each reviewer exports a separate annotations JSONL file; keep them unchanged.\n"
                          "The evaluator preserves disagreements. An adjudicator can import reviews and record a separate resolution.\n"
                          "Score with: python -m rilldex activity-reference evaluate FOLDER --annotations reviewer-a.jsonl --annotations reviewer-b.jsonl\n"
                          "Add --html results.html for an interactive inspection report. Use a new path; previous reports are preserved.\n"
                          "Results expose predictions and reviewed labels. Never give results.html or predictions.jsonl to a blind independent reviewer.\n"
                          "Add --split development for development cases. Model proposals are excluded from human accuracy.\n"}


def prepare(bundles, output, **options):
    output = Path(output)
    if output.exists(): raise InputError("Use a new reference directory; frozen cases and annotations are never overwritten")
    package = build(bundles, **options)
    output.mkdir(parents=True)
    for name, content in files(package).items():
        (output / name).write_text(content, encoding="utf-8")
    return {"output": str(output), "cases": len(package["cases"]), "manifest_hash": package["manifest"]["manifest_hash"], "reference_labels": 0}


def archive(package):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        for name, content in files(package).items(): zip_file.writestr(name, content)
    return buffer.getvalue()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def validate_annotation(row, case, manifest_hash):
    if row.get("case_hash") != case["case_hash"] or row.get("manifest_hash") != manifest_hash:
        raise InputError("Annotation does not match frozen case and manifest")
    if not isinstance(row.get("annotation_id"), str) or not row["annotation_id"].strip() or not isinstance(row.get("reviewer"), str) or not row["reviewer"].strip():
        raise InputError("Annotation needs an ID and reviewer")
    if row.get("reference_kind") not in {"human", "model_proposal"} or row.get("exposure") not in {"prediction_blind", "seen_predictions"} or row.get("annotation_type") not in {"independent", "adjudication"}:
        raise InputError("Declare reference kind, exposure and annotation type")
    checks = row.get("checks", {})
    if not isinstance(checks, dict) or set(checks) != {"attribution", "segmentation", "context"}:
        raise InputError("Complete exactly the attribution, segmentation and context assessments")
    for key, options in {"attribution": {"valid", "invalid", "uncertain"}, "segmentation": {"usable", "split_needed", "merge_previous", "not_activity", "uncertain"}, "context": {"sufficient", "insufficient", "uncertain"}}.items():
        if checks.get(key) not in options: raise InputError("Complete attribution, segmentation and context assessments")
    values = row.get("values", {})
    if not isinstance(values, dict) or set(values) != set(case["fields"]) or any(not isinstance(v, str) or v not in case["fields"][k]["criteria"] for k, v in values.items()):
        raise InputError("Every activity/form/link field requires a supplied option; unlabeled is not absent")
    evidence = row.get("evidence_ids")
    allowed = {e["id"] for e in case["available_prefix"]} | {case["subject"]["id"]}
    if case.get("source"): allowed.add(case["source"]["id"])
    if not isinstance(evidence, list) or not evidence or any(not isinstance(e, str) or e not in allowed for e in evidence):
        raise InputError("Cite supplied subject or prefix evidence IDs")
    if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
        raise InputError("Record a rationale or ambiguity note")
    validate_spans(row,case)
    if values.get("revise") == "present" and values.get("revision_target") == "not_applicable":
        raise InputError("A present revision cannot also assert no revision; a missing supplied target may be no_suitable_candidate")


def metrics(records, binary=False):
    known = [r for r in records if r["reference"] != "unresolved"]
    decided = [r for r in known if r["prediction"] not in {"unresolved", "unobserved"}]
    confusion = defaultdict(Counter)
    for r in records: confusion[r["reference"]][r["prediction"]] += 1
    correct = sum(r["prediction"] == r["reference"] for r in decided)
    result = {"reference_units": len(records), "known_reference_units": len(known), "decided_predictions": len(decided),
              "coverage": len(decided)/len(known) if known else None,
              "accuracy_all_known_references": correct/len(known) if known else None,
              "accuracy_decided_only": correct/len(decided) if decided else None,
              "confusion": {k: dict(v) for k, v in confusion.items()},
              "cases": [{k: r[k] for k in ("case_id", "reference", "prediction", "reference_basis")} for r in records]}
    if binary:
        tp = sum(r["reference"] == "present" and r["prediction"] == "present" for r in known)
        predicted_positive = sum(r["prediction"] == "present" for r in known)
        positive = sum(r["reference"] == "present" for r in known)
        result.update(reference_positive=positive, predicted_positive=predicted_positive,
                      precision=tp/predicted_positive if predicted_positive else None,
                      recall=tp/positive if positive else None,
                      missed_positive_unresolved=sum(r["reference"] == "present" and r["prediction"] == "unresolved" for r in known),
                      missed_positive_unobserved=sum(r["reference"] == "present" and r["prediction"] == "unobserved" for r in known))
    return result


def prediction_value(prediction):
    """The scored observation can be unavailable while its argmax is preserved."""
    if prediction["status"] in {"decided", "not_applicable", "no_suitable_candidate"}:
        return prediction["value"]
    return "unobserved" if prediction["status"] in {"stale", "unobserved"} else "unresolved"


def inspection_case(case, prediction, independent_rows, adjudication, resolutions):
    """Connect measured disagreements to reviewer evidence without asserting causes."""
    assessments, findings = {}, []
    for check, good in (("attribution", "valid"), ("segmentation", "usable"), ("context", "sufficient")):
        votes = [{"annotation_id": r["annotation_id"], "reviewer": r["reviewer"], "value": r["checks"][check]} for r in independent_rows]
        values = {v["value"] for v in votes}
        if adjudication:
            basis, value = "adjudicated", adjudication["checks"][check]
        elif len(independent_rows) < 2:
            basis, value = "awaiting_two_reviews", None
        elif len(values) > 1:
            basis, value = "disagreement", None
        else:
            basis, value = "consensus", next(iter(values))
        assessments[check] = {"basis": basis, "value": value, "votes": votes}
        considered = [adjudication] if adjudication else independent_rows
        concerns = [r for r in considered if r["checks"][check] != good]
        if concerns:
            findings.append({"stage": "context" if check == "context" else "unit", "kind": "reviewer_concern",
                             "check": check, "basis": basis,
                             "detail": "Reviewer-reported " + check + " concern; this does not establish a model error.",
                             "annotation_ids": [r["annotation_id"] for r in concerns]})
        if basis == "disagreement":
            findings.append({"stage": "reference", "kind": "assessment_disagreement", "check": check,
                             "detail": "Independent reviewers disagree on " + check + "."})
    fields = []
    for resolution in resolutions:
        field = resolution["field"]; reference = resolution["reference"]
        pred = prediction["values"][field]; observed = prediction_value(pred)
        fields.append({**resolution, "prediction": deepcopy(pred), "scored_prediction": observed})
        if reference is None:
            findings.append({"stage": "reference", "kind": resolution["status"], "field": field,
                             "detail": "No scored reference: " + resolution["status"].replace("_", " ") + "."})
        elif reference == "unresolved":
            findings.append({"stage": "reference", "kind": "reference_unresolved", "field": field,
                             "detail": "The agreed reference is unresolved; this is not a negative label."})
        elif observed in {"unresolved", "unobserved"}:
            findings.append({"stage": "choice", "kind": "prediction_" + observed, "field": field,
                             "detail": "A known reference exists but the scored observation is " + observed + ". The original selected option is retained."})
        elif observed != reference:
            findings.append({"stage": "choice", "kind": "label_difference", "field": field,
                             "detail": "The scored observation differs from the reference. Unit/context concerns may coexist; this does not isolate a classifier cause."})
        if field == "revision_target" and reference == "no_suitable_candidate":
            findings.append({"stage": "link", "kind": "candidate_gap", "field": field,
                             "detail": "The reference found no suitable supplied revision target. Review candidate construction and available prefix evidence."})
    return {"case_id": case["case_id"], "group": case["group"], "adapter": case["adapter"],
            "domain": case["domain"], "subject": case["subject"], "profile": prediction["profile"],
            "profile_id": digest(prediction["profile"])[:16],
            "assessments": assessments, "findings": findings, "fields": fields,
            "available_prefix": case["available_prefix"], "inspector_state": case["inspector_state"],
            "context_coverage": {**audit_context(case["available_prefix"], case["inspector_state"], case["subject"]),
                                 "packet_basis": "Frozen reference-case packet; does not establish that a provider call occurred."},
            "field_definitions": case["fields"],
            "reviews": [deepcopy(r) for r in [*independent_rows, *([adjudication] if adjudication else [])]]}


def render_report(report):
    """This report exposes predictions. It must never replace the blind review page."""
    template = (Path(__file__).parent/"web/activity-reference-results.html").read_text(encoding="utf-8")
    return template.replace("__ACTIVITY_REFERENCE_RESULTS__", json.dumps(report, ensure_ascii=False).replace("<", "\\u003c"))


def evaluate(directory, annotations=None, *, split="holdout"):
    if split not in {"development", "holdout"}: raise InputError("Select development or holdout")
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    cases, predictions = read_jsonl(directory / "cases.jsonl"), read_jsonl(directory / "predictions.jsonl")
    if manifest.get("version") != VERSION or manifest.get("manifest_hash") != fingerprint(manifest, "manifest_hash") or digest(cases) != manifest.get("cases_hash") or digest(predictions) != manifest.get("predictions_hash"):
        raise InputError("Frozen manifest, cases or predictions changed")
    case_map = {c["case_id"]: c for c in cases}; pred_map = {p["case_id"]: p for p in predictions}
    if len(case_map) != len(cases) or set(case_map) != set(pred_map) or len(pred_map) != len(predictions):
        raise InputError("Frozen cases and predictions do not align")
    for c in cases:
        if c["case_hash"] != fingerprint(c, "case_hash") or pred_map[c["case_id"]]["case_hash"] != c["case_hash"]:
            raise InputError("Frozen case fingerprint mismatch")
    incoming=(row for path in annotations or [directory / "annotations.jsonl"] for row in read_jsonl(path))
    records=collect_reviews(incoming,case_map,manifest["manifest_hash"],validate_annotation)
    counts = Counter(); resolutions = []; grouped = defaultdict(lambda: defaultdict(list)); profiles = {}; inspected = []
    for case in cases:
        if case["split"] != split: continue
        cid = case["case_id"]; rows = records[cid]
        resolved=resolve_reviews(case,rows);counts.update(resolved['counts'])
        independent_rows=resolved['independent'];adjudication=resolved['adjudication']
        prediction = pred_map[cid]; profile_id = digest(prediction["profile"])[:16]; profiles[profile_id] = prediction["profile"]
        case_resolutions=resolved['resolutions']
        for resolution in case_resolutions:
            field=resolution['field'];reference=resolution['reference'];basis=resolution['status']
            if reference is None: continue
            pred = prediction["values"][field]
            value = prediction_value(pred)
            grouped[profile_id][field].append({"case_id": cid, "reference": reference, "prediction": value, "reference_basis": basis,
                                               "adapter": case["adapter"], "domain": case["domain"], "unit_kind": case["subject"]["kind"], "group": case["group"]})
        resolutions.extend(case_resolutions)
        inspected.append(inspection_case(case, prediction, independent_rows, adjudication, case_resolutions))
    by_profile = {}
    for profile_id, fields in grouped.items():
        summary = {"profile": profiles[profile_id], "fields": {f: metrics(rows, f in ACTIVITIES or f == "other") for f, rows in fields.items()}}
        for dimension in ("adapter", "domain", "unit_kind"):
            slices = defaultdict(lambda: defaultdict(list))
            for field, rows in fields.items():
                for row in rows: slices[row[dimension]][field].append(row)
            summary["by_" + dimension] = {s: {f: metrics(rows, f in ACTIVITIES or f == "other") for f, rows in fields.items()} for s, fields in slices.items()}
        by_profile[profile_id] = summary
    return {"version": VERSION, "manifest_hash": manifest["manifest_hash"], "split": split,
            "status": "references_scored" if grouped else "no_eligible_reference_consensus", "counts": dict(counts),
            "by_profile": by_profile, "resolutions": resolutions,
            "inspection": {"version": "activity-inspection/1", "cases": inspected,
                           "cases_by_stage": {stage: sum(any(f["stage"] == stage for f in c["findings"]) for c in inspected)
                                              for stage in ("unit", "context", "choice", "link", "reference")},
                           "counting": "Each stage counts distinct cases, not reviewers or tag memberships. Cases can appear in several stages; these are inspection reasons, not a causal error taxonomy.",
                           "relationship_scope": "The current reference fields assess revision targets. Outcome/result links are not scored by this pack.",
                           "blinding": "This report contains inspector predictions and reviewed labels. Give independent reviewers only the separate review.html."},
            "limits": manifest["limits"] + ["Unresolved/unobserved predictions reduce recall and all-reference accuracy; decided-only accuracy has its own denominator.",
                       "Context-insufficient cases are retained to expose harness errors; invalid attribution or unusable segmentation excludes the unit.",
                       "Tag counts overlap. No action-IID confidence intervals or policy-training claims are made."]}
