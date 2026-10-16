"""Append-only imported component results; never an overlay on live H1 labels.

The initial input adapter reads frozen experiment cases and response journals.
Source-span validation is independent of semantic accuracy and provider identity.
"""
from collections import Counter
import json
from pathlib import Path
import re

from .activity import units
from .activity_context import audit, visible_prefix, TEXT_PACKET_SCHEMA
from .jev import SELECTION_POLICY, validate_answers
from .schema import InputError, digest, dumps

VERSION = "activity-components/1"
PACKET_HARNESSES = {"semantic-activity/1.4", "semantic-activity/1.5", "activity-verify/0.1-experimental"}
STATE_FIELDS = {"harness", "taxonomy_version", "unit_version", "subject", "activity_definitions",
                "annotation_boundaries", "authorized_instructions", "earlier_units",
                "prior_environment_or_harness_context", "cutoff_event_id", "cutoff_codepoint", "missingness", "scope"}
LIMITS = ["Imported results are source-bound and argmax-validated, not authenticated provider records or independent references.",
          "Differences describe observer outputs on the same source, not semantic error or training progress.",
          "A missing field is not a negative label. Different option definitions are not counted as comparable choices.",
          "Repeated or reused records remain separate; reuse is not an additional inference or independent repeat.",
          "Evidence checks cover registered normalized text packets and current tool contracts; they do not certify prompt quality, relevance or raw-source extraction."]


def read(path, *, lines=False):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024: raise InputError("Component input exceeds 64 MiB per file")
    text = path.read_text(encoding="utf-8")
    return [json.loads(s) for s in text.splitlines() if s.strip()] if lines else json.loads(text)


def prepare_import(directory, run_reader, name=None):
    """Validate the complete collection before a caller starts its write transaction."""
    try:
        return _prepare_import(Path(directory), run_reader, name)
    except (KeyError, TypeError, StopIteration) as error:
        raise InputError("Malformed component package or missing source run: " + str(error)) from error


def _prepare_import(directory, run_reader, name):
    manifest, cases = read(directory / "manifest.json"), read(directory / "cases.json")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 1000 or digest(cases) != manifest.get("cases_hash"):
        raise InputError("Frozen component cases changed or exceed supported limits")
    if manifest.get("selection_policy") != SELECTION_POLICY: raise InputError("Component selection policy must be argmax/1")
    variants = manifest.get("variants")
    if (not isinstance(variants, list) or not 1 <= len(variants) <= 12 or len(set(variants)) != len(variants)
            or any(not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", v) for v in variants)):
        raise InputError("Invalid component variants")
    if len({c["case_id"] for c in cases}) != len(cases): raise InputError("Duplicate component case IDs")
    if any(c.get("set") != "development" for c in cases): raise InputError("This adapter imports development experiments only")
    if set().union(*(set(c["requests"]) for c in cases)) != set(variants): raise InputError("Request variants differ from manifest")
    journals = {}
    for variant in variants:
        rows = read(directory / (variant + "-development.jsonl"), lines=True)
        if len({r["case_id"] for r in rows}) != len(rows): raise InputError("Duplicate component results")
        journals[variant] = {r["case_id"]: r for r in rows}
        if set(journals[variant]) != {c["case_id"] for c in cases}: raise InputError("Component results must cover the complete frozen case set")
    collection_id = digest(manifest)
    runs, prepared, seen_subjects = {}, [], set()
    skipped = 0
    for case in cases:
        # Authored design fixtures must never become monitored model trajectories.
        if case.get("origin") != "real":
            skipped += 1
            continue
        rid, subject = case["run_id"], case["target"]
        identity = (rid, subject["id"])
        if identity in seen_subjects: raise InputError("Duplicate source subject in one collection")
        seen_subjects.add(identity)
        if rid not in runs: runs[rid] = run_reader(rid)
        run = runs[rid]
        if digest(run["raw"]) != case["source_hash"]: raise InputError("Component source hash differs from saved run")
        actual = next((u for u in units(run) if u["id"] == subject["id"]), None)
        if actual != subject or not subject["eligible"]: raise InputError("Component subject is not an exact current eligible source unit")
        prefix = visible_prefix(run, subject)
        if case.get("source_prefix") != prefix: raise InputError("Component prefix differs from the saved visible source cutoff")
        for variant in variants:
            request, row = case["requests"][variant], journals[variant][case["case_id"]]
            state, questions = request["state"], request["questions"]
            if state.get("harness") not in PACKET_HARNESSES or set(state) != STATE_FIELDS:
                raise InputError("Unsupported component packet schema")
            if (any(state['subject'].get(k)!=subject.get(k) for k in ('id','event_id','kind','trajectory_id','source_pointer','start','end'))
                    or state['subject'].get('text')!=subject['text'][:5000]):
                raise InputError('Component request does not target its declared source subject')
            if (row["variant"], row["set"], row["model"], row["selection_policy"], row["request_hash"]) != (
                    variant, "development", manifest["model"], SELECTION_POLICY, digest(request)) or request["model"] != manifest["model"]:
                raise InputError("Component result provenance differs from frozen request")
            if not questions or len(questions) > 64 or any(q.get("type") != "choice" or not q.get("criteria") for q in questions.values()):
                raise InputError("Components require bounded choice questions")
            checked = audit(prefix, state, subject, packet_schema=TEXT_PACKET_SCHEMA)
            if checked["status"] != "audited": raise InputError("Component evidence fails source/cutoff binding checks")
            contract = state["subject"].get("tool_contract")
            source_contract = subject.get("tool_contract")
            if bool(contract)!=bool(source_contract):raise InputError('Component subject tool contract is missing or unsupported')
            if contract:
                if not source_contract or contract != {"source_pointer": source_contract["source_pointer"],
                    "definition_text": dumps(source_contract["definition"])[:8000], "source_characters": len(dumps(source_contract["definition"]))}:
                    raise InputError("Component tool contract differs from the source")
            required=([subject['id']] if len(subject['text'])>5000 else [])
            if source_contract and len(dumps(source_contract['definition']))>8000:
                required.append('tool_contract:'+source_contract['source_pointer'])
            if (state['missingness'].get('required_truncated_event_ids')!=required
                    or state['missingness'].get('objective_missing')!=(not state['authorized_instructions'])):
                raise InputError('Component evidence-gate declarations differ from supplied evidence')
            if set(row["answers"]) != set(questions): raise InputError("Component field ownership differs from its question set")
            answers = validate_answers({"answers": {q: {"type": "choice", "probabilities": a["probabilities"],
                "choice": a.get("provider_choice"), "confidence": a.get("confidence")} for q,a in row["answers"].items()}}, request)
            for q, value in answers.items():
                if any(row["answers"][q].get(k) != value.get(k) for k in ("value", "status", "selection_status", "selection_policy", "evidence_gate")):
                    raise InputError("Component winner or evidence status differs from argmax validation")
            document = {"version": VERSION, "collection_id": collection_id, "case_id": case["case_id"],
                "variant": variant, "run_id": rid, "source_hash": case["source_hash"], "subject": subject,
                "domain": case.get("domain"), "request": request, "result": row, "packet_schema": TEXT_PACKET_SCHEMA,
                "context_coverage": checked, "fields": list(questions), "provider_identity": "declared_in_import"}
            document["id"] = digest({"collection":collection_id,"case":case["case_id"],"variant":variant})
            prepared.append(document)
    if not prepared: raise InputError("No real source-bound component observations to import")
    collection = {"id": collection_id, "version": VERSION, "name": name or directory.name, "manifest": manifest,
                  "variants": variants, "real_subjects": len(seen_subjects), "records": len(prepared),
                  "skipped_nonreal_cases": skipped, "limits": LIMITS}
    return collection, prepared


def summary(document):
    request, result = document["request"], document["result"]
    return {k: document[k] for k in ("id", "collection_id", "case_id", "variant", "run_id", "domain", "subject")} | {
        "harness": request["state"]["harness"], "model": request["model"], "selection_policy": result["selection_policy"],
        "request_hash": result["request_hash"], "fields": document["fields"],
        "questions": request["questions"],
        "answers": {q: {k:a.get(k) for k in ("value", "status", "selection_status", "evidence_gate")} for q,a in result["answers"].items()},
        "reuse_basis": result.get("reuse_basis"), "usage": result.get("usage"), "elapsed_seconds": result.get("elapsed_seconds")}


def compare(records, reference, candidate):
    """Same-source comparisons; missing/changed definitions are not negatives."""
    by_source = {}
    for record in records:
        if record["variant"] in {reference, candidate}:
            by_source.setdefault((record["run_id"],record["subject"]["id"]), {})[record["variant"]] = record
    totals=Counter(); rows=[]
    for (run_id, unit_id), pair in by_source.items():
        left, right = pair.get(reference), pair.get(candidate)
        row={"run_id":run_id,"unit_id":unit_id,"subject":(left or right)["subject"],
             "reference_id":left["id"] if left else None,"candidate_id":right["id"] if right else None,"fields":[]}
        if not left or not right:
            totals['unpaired_units']+=1;row['comparison_kind']='unpaired';rows.append(row);continue
        totals['paired_units']+=1
        same=(left['request_hash'],left['model'],left['selection_policy'])==(right['request_hash'],right['model'],right['selection_policy'])
        row['comparison_kind']='same_request_reuse' if same and right.get('reuse_basis') else 'same_request_repeat' if same else 'changed_request'
        totals[row['comparison_kind']+'_units']+=1
        for field in dict.fromkeys([*left['fields'],*right['fields']]):
            a,b=left['answers'].get(field),right['answers'].get(field)
            status='candidate_only' if a is None else 'reference_only' if b is None else 'options_changed' if left['questions'][field]['criteria']!=right['questions'][field]['criteria'] else 'comparable'
            entry={'field':field,'reference':a,'candidate':b,'status':status,'choice_changed':False,'evidence_status_changed':False}
            totals[status+'_fields']+=1
            if status=='comparable':
                entry['choice_changed']=a['value']!=b['value'];entry['evidence_status_changed']=(a['status'],a.get('evidence_gate'))!=(b['status'],b.get('evidence_gate'))
                totals['changed_choices']+=entry['choice_changed'];totals['changed_evidence_statuses']+=entry['evidence_status_changed']
            row['fields'].append(entry)
        row['changed_choices']=sum(f['choice_changed'] for f in row['fields'])
        rows.append(row)
    return {'reference':reference,'candidate':candidate,'totals':dict(totals),'rows':rows,'limits':LIMITS}
