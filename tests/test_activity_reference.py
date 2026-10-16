"""Reference integrity, blinding and metric semantics; fixtures are not real labels."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tracker.activity import ActivityClient, units
from tracker.activity_reference import build, prepare, evaluate, read_jsonl, metrics, render_report
from tracker.schema import InputError
from test_activity import reasoning_run, response


def bundle():
    run = reasoning_run()
    run["outcome"]["reward"] = "HIDDEN-GRADE"
    run["metadata"]["checkpoint"] = "HIDDEN-POLICY"
    uid = units(run)[0]["id"]
    result = ActivityClient(transport=lambda r: response(r, {"plan": "present", "expression": "intended"})).evaluate(run, uid)
    return {"run": run, "activity_observation_history": [{"event_id": uid, "result": result}]}


def annotation(case, manifest, reviewer="test-human-A", **changes):
    values = {k: "absent" if "absent" in q["criteria"] else "not_applicable" if k == "revision_target" else "intended" for k, q in case["fields"].items()}
    values["plan"] = "present"
    return {"annotation_id": case["case_id"] + reviewer, "case_id": case["case_id"], "case_hash": case["case_hash"],
            "manifest_hash": manifest["manifest_hash"], "reviewer": reviewer, "reference_kind": "human",
            "exposure": "prediction_blind", "annotation_type": "independent", "values": values,
            "checks": {"attribution": "valid", "segmentation": "usable", "context": "sufficient"},
            "evidence_ids": [case["subject"]["id"]], "rationale": "Synthetic test reference; not an accuracy benchmark.", **changes}


class ActivityReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "frozen"
        self.bundle = bundle(); self.uid = units(self.bundle["run"])[0]["id"]
        prepare([self.bundle], self.path, selected_units={self.bundle["run"]["id"]: [self.uid]})
        self.case = read_jsonl(self.path / "cases.jsonl")[0]
        self.manifest = json.loads((self.path / "manifest.json").read_text())

    def score(self, rows):
        path = Path(self.temp.name) / "reviews.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return evaluate(self.path, [path], split="development")

    def references(self):
        return [annotation(self.case, self.manifest, reviewer) for reviewer in ("test-human-A", "test-human-B")]

    def test_blinding_and_subject_cutoff_do_not_expose_future_message_tail(self):
        blind = (self.path / "review.html").read_text(encoding="utf-8")
        for hidden in ("HIDDEN-GRADE", "HIDDEN-POLICY", '"probabilities"', "Perhaps both roots are positive."):
            self.assertNotIn(hidden, blind)
        parent = next(e for e in self.case["available_prefix"] if e["id"] == self.case["subject"]["event_id"])
        self.assertEqual(parent["text"], self.case["subject"]["text"])
        self.assertIn('"probabilities"', (self.path / "predictions.jsonl").read_text())
        self.assertEqual((self.path / "annotations.jsonl").read_text(), "")

    def test_no_references_or_one_reviewer_does_not_claim_accuracy(self):
        for rows in ([], self.references()[:1]):
            result = self.score(rows)
            self.assertEqual(result["status"], "no_eligible_reference_consensus")
            self.assertEqual(result["by_profile"], {})

    def test_exact_field_citations_preserved_without_changing_eligibility_or_scores(self):
        rows=self.references();baseline=self.score(rows)
        for row in rows:
            row['evidence_spans']=[{'field':'plan','target':'subject','evidence_id':self.case['subject']['id'],
                'start':0,'end':6,'text':self.case['subject']['text'][:6],
                'role':'label_evidence','basis':'evidence_text_unicode_codepoints/1'}]
        result=self.score(rows);self.assertEqual(result['by_profile'],baseline['by_profile'])
        self.assertEqual(result['inspection']['cases'][0]['reviews'][0]['evidence_spans'],rows[0]['evidence_spans'])
        rows[0]['evidence_spans'][0]['text']='wrong text'
        with self.assertRaises(InputError):self.score(rows)

    def test_two_agreeing_reviews_score_multiple_tags_forms_and_links(self):
        report = self.score(self.references())
        fields = next(iter(report["by_profile"].values()))["fields"]
        self.assertEqual(fields["plan"]["precision"], 1)
        self.assertEqual(fields["plan"]["recall"], 1)
        self.assertIsNone(fields["reason"]["precision"])
        self.assertIsNone(fields["reason"]["recall"])
        self.assertEqual(fields["expression"]["accuracy_all_known_references"], 1)
        self.assertEqual(fields["revision_target"]["accuracy_all_known_references"], 1)
        self.assertTrue(all(r["status"] == "consensus" for r in report["resolutions"]))

    def test_disagreement_is_retained_until_explicit_adjudication(self):
        rows = self.references(); rows[1]["values"]["plan"] = "absent"
        report = self.score(rows)
        self.assertNotIn("plan", next(iter(report["by_profile"].values()))["fields"])
        dispute = next(r for r in report["resolutions"] if r["field"] == "plan")
        self.assertEqual(dispute["status"], "disagreement"); self.assertEqual(len(dispute["votes"]), 2)
        adjudication = annotation(self.case, self.manifest, "test-adjudicator", annotation_type="adjudication", reviewed_annotation_ids=[r["annotation_id"] for r in rows])
        report = self.score([*rows, adjudication])
        resolved = next(r for r in report["resolutions"] if r["field"] == "plan")
        self.assertEqual(resolved["status"], "adjudicated"); self.assertTrue(resolved["disagreement"])
        adjudication["reviewed_annotation_ids"] = [rows[0]["annotation_id"]]
        with self.assertRaises(InputError): self.score([*rows, adjudication])

    def test_model_proposals_exposed_reviews_and_bad_units_are_not_reference_accuracy(self):
        for change in ({"reference_kind": "model_proposal"}, {"exposure": "seen_predictions"},
                       {"checks": {"attribution": "valid", "segmentation": "split_needed", "context": "sufficient"}}):
            rows = [{**r, **change} for r in self.references()]
            self.assertEqual(self.score(rows)["by_profile"], {})

    def test_missing_predictions_reduce_recall_and_all_reference_accuracy(self):
        rows = [{"case_id": str(i), "reference": "present", "prediction": p, "reference_basis": "consensus"} for i, p in enumerate(("present", "absent", "unresolved", "unobserved"))]
        result = metrics(rows, True)
        self.assertEqual(result["precision"], 1); self.assertEqual(result["recall"], .25)
        self.assertEqual(result["coverage"], .5); self.assertEqual(result["accuracy_all_known_references"], .25)
        self.assertEqual(result["accuracy_decided_only"], .5)
        self.assertEqual(result["missed_positive_unresolved"], 1); self.assertEqual(result["missed_positive_unobserved"], 1)

    def test_incomplete_reference_unknown_citation_duplicate_reviewer_are_rejected(self):
        rows = self.references()
        bad = copy.deepcopy(rows); del bad[0]["values"]["reason"]
        with self.assertRaises(InputError): self.score(bad)
        bad = copy.deepcopy(rows); bad[0]["evidence_ids"] = ["future-event"]
        with self.assertRaises(InputError): self.score(bad)
        bad = copy.deepcopy(rows); bad[1]["reviewer"] = bad[0]["reviewer"]
        with self.assertRaises(InputError): self.score(bad)
        bad = copy.deepcopy(rows); bad[0]["values"]["revise"] = "present"
        with self.assertRaises(InputError): self.score(bad)

    def test_reference_revision_can_be_known_even_when_candidate_is_missing(self):
        rows = self.references()
        for row in rows:
            row["values"].update(revise="present", revision_target="no_suitable_candidate")
        report = self.score(rows)
        fields = next(iter(report["by_profile"].values()))["fields"]
        self.assertEqual(fields["revise"]["reference_positive"], 1)
        self.assertEqual(fields["revise"]["recall"], 0)

    def test_frozen_predictions_or_cases_cannot_change_silently(self):
        path = self.path / "predictions.jsonl"
        predictions = read_jsonl(path); predictions[0]["values"]["plan"]["value"] = "absent"
        path.write_text(json.dumps(predictions[0]) + "\n")
        with self.assertRaises(InputError): self.score(self.references())
        with self.assertRaises(InputError): prepare([self.bundle], self.path)

    def test_group_leakage_holdout_declaration_and_exact_selected_ids(self):
        rid = self.bundle["run"]["id"]
        with self.assertRaises(InputError): build([self.bundle], group_map={rid: {"split": "holdout"}})
        duplicate = copy.deepcopy(self.bundle); duplicate["run"]["id"] = "second-policy"
        groups = {rid: {"group": "same-task", "split": "development"}, "second-policy": {"group": "same-task", "split": "holdout", "exposure": "unseen"}}
        with self.assertRaises(InputError): build([self.bundle, duplicate], group_map=groups)
        with self.assertRaises(InputError): build([self.bundle], selected_units={rid: ["not-an-eligible-unit"]})

    def test_stale_packet_is_frozen_as_unobserved_not_reused(self):
        changed = copy.deepcopy(self.bundle); changed["run"]["events"][0]["text"] += " Changed condition."
        package = build([changed], selected_units={changed["run"]["id"]: [self.uid]})
        self.assertEqual(package["predictions"][0]["values"]["plan"]["status"], "stale")

    def test_distributions_never_enter_review_html_and_html_cannot_execute_source(self):
        b = bundle(); b["run"]["events"][1]["text"] = '</script><script>window.SOURCE_EXECUTED=true</script>'
        from tracker.activity_reference import files
        rendered = files(build([b]))["review.html"]
        self.assertNotIn('</script><script>window.SOURCE_EXECUTED', rendered)
        self.assertNotIn('"probabilities"', rendered)

    def test_inspection_separates_case_concerns_from_field_differences(self):
        rows = self.references()
        for row in rows:
            row["checks"]["context"] = "insufficient"
            row["values"].update(plan="absent", reason="present", revise="present", revision_target="no_suitable_candidate")
        report = self.score(rows)
        stages = report["inspection"]["cases_by_stage"]
        self.assertEqual(stages, {"unit":0,"context":1,"choice":1,"link":1,"reference":0})
        case = report["inspection"]["cases"][0]
        self.assertEqual(case["assessments"]["context"]["value"], "insufficient")
        self.assertEqual(len(case["assessments"]["context"]["votes"]), 2)
        self.assertGreater(sum(f["kind"] == "label_difference" for f in case["findings"]), 1)
        self.assertEqual(case["available_prefix"], self.case["available_prefix"])
        self.assertEqual(case["reviews"][0]["evidence_ids"], rows[0]["evidence_ids"])
        self.assertEqual(next(iter(report["by_profile"].values()))["fields"]["plan"]["accuracy_all_known_references"], 0)

    def test_inspection_does_not_call_unreviewed_or_excluded_labels_errors(self):
        for rows in ([], self.references()[:1], [{**r,"reference_kind":"model_proposal"} for r in self.references()]):
            report = self.score(rows)
            self.assertEqual(report["inspection"]["cases_by_stage"]["choice"], 0)
            self.assertEqual(report["inspection"]["cases_by_stage"]["reference"], 1)
        rows = self.references(); rows[0]["checks"]["segmentation"] = "split_needed"
        report = self.score(rows); c = report["inspection"]["cases"][0]
        self.assertEqual(c["assessments"]["segmentation"]["basis"], "disagreement")
        self.assertEqual(report["by_profile"], {})
        self.assertEqual(report["inspection"]["cases_by_stage"]["unit"], 1)
        self.assertFalse(any(f["kind"] == "label_difference" for f in c["findings"]))

    def test_adjudicated_quality_preserves_earlier_concerns_without_counting_them_as_resolved_issues(self):
        rows = self.references(); rows[0]["checks"]["context"] = "insufficient"
        adjudication = annotation(self.case,self.manifest,"test-adjudicator",annotation_type="adjudication",reviewed_annotation_ids=[r["annotation_id"] for r in rows])
        report=self.score([*rows,adjudication]); c=report["inspection"]["cases"][0]
        self.assertEqual(c["assessments"]["context"]["basis"],"adjudicated")
        self.assertEqual(c["assessments"]["context"]["votes"][0]["value"],"insufficient")
        self.assertEqual(report["inspection"]["cases_by_stage"]["context"],0)
        self.assertEqual(len(c["reviews"]),3)

    def test_report_preserves_argmax_under_an_evidence_gate_and_escapes_source_content(self):
        b=copy.deepcopy(self.bundle)
        b["activity_observation_history"][0]["result"]["plan"].update(status="unresolved",evidence_gate="Synthetic missing-evidence fixture")
        directory=Path(self.temp.name)/"gated"
        prepare([b],directory,selected_units={b["run"]["id"]:[self.uid]})
        case=read_jsonl(directory/"cases.jsonl")[0]; manifest=json.loads((directory/"manifest.json").read_text())
        rows=[annotation(case,manifest,reviewer) for reviewer in ("fixture-A","fixture-B")]
        for row in rows: row["rationale"]='</script><script>window.SOURCE_EXECUTED=true</script>'
        review_path=Path(self.temp.name)/"gated.jsonl";review_path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        report=evaluate(directory,[review_path],split="development")
        field=next(f for f in report["inspection"]["cases"][0]["fields"] if f["field"]=="plan")
        self.assertEqual(field["prediction"]["value"],"present")
        self.assertEqual(field["scored_prediction"],"unresolved")
        html=render_report(report)
        self.assertNotIn('</script><script>window.SOURCE_EXECUTED',html)
        self.assertNotIn('HIDDEN-GRADE',html)
        self.assertNotIn('HIDDEN-POLICY',html)
        self.assertIn('"probabilities"',html)
        self.assertIn('separate review.html',html)

    def test_malformed_assessments_fail_with_input_error(self):
        for checks in (None, [], 'invalid', {"attribution":"valid","segmentation":"usable","context":"sufficient","extra":"unexpected"}):
            rows=self.references(); rows[0]["checks"]=checks
            with self.assertRaises(InputError): self.score(rows)

    def test_cli_writes_inspection_and_preserves_existing_reports(self):
        from tracker.cli import main
        output=Path(self.temp.name)/"results.json"; html=Path(self.temp.name)/"results.html"
        arguments=['tracker','activity-reference','evaluate',str(self.path),'--split','development','--output',str(output),'--html',str(html)]
        with patch('sys.argv',arguments), redirect_stdout(StringIO()): main()
        report=json.loads(output.read_text())
        self.assertEqual(report['inspection']['cases_by_stage']['reference'],1)
        self.assertIn('Independent reference validation is incomplete',html.read_text(encoding='utf-8'))
        before=html.read_bytes()
        with patch('sys.argv',arguments), redirect_stderr(StringIO()), self.assertRaises(SystemExit): main()
        self.assertEqual(html.read_bytes(),before)

    def test_inspection_profiles_remain_separate_when_predictions_are_missing(self):
        second=copy.deepcopy(self.bundle); second['run']['id']='second-fixture'
        second['activity_observation_history']=[]
        directory=Path(self.temp.name)/'two-profiles';prepare([self.bundle,second],directory,
            selected_units={self.bundle['run']['id']:[self.uid],second['run']['id']:[self.uid]})
        cases=read_jsonl(directory/'cases.jsonl');manifest=json.loads((directory/'manifest.json').read_text())
        reviews=Path(self.temp.name)/'two-profile-reviews.jsonl'
        reviews.write_text(''.join(json.dumps(annotation(c,manifest,name))+'\n' for c in cases for name in ('fixture-A','fixture-B')))
        report=evaluate(directory,[reviews],split='development')
        self.assertEqual(len(report['by_profile']),2)
        self.assertEqual({c['profile_id'] for c in report['inspection']['cases']},set(report['by_profile']))
        self.assertEqual(sorted(p['fields']['plan']['recall'] for p in report['by_profile'].values()),[0,1])


if __name__ == "__main__": unittest.main()
