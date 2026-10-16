import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.observe import analyze
from tracker.reference import prepare, evaluate, _read_jsonl, _write_jsonl
from tracker.schema import InputError
from tracker.schema import digest
from tracker.jev import packet, JEV_HARNESS, JevClient
from test_tracker import response_for


def bundle(commands=None, task="repo-task", **metadata):
    commands = commands or ["cat parser.py", "edit parser.py", "pytest", "submit"]
    run = normalize({"history": [{"role": "user", "content": "Fix parser"}],
                     "trajectory": [{"action": c, "observation": "RESULT-"+str(i)} for i,c in enumerate(commands)],
                     "info": {"exit_status": "submitted", "private_score": "FUTURE-OUTCOME"}},
                    "swe-agent", {"task_id": task, "checkpoint": "HIDDEN-POLICY", **metadata})[0]
    return {"run": run, "analysis": analyze(run), "model_observations": {}}


def fill_labels(path, modes, *, kind="human", extraction="valid"):
    rows = _read_jsonl(path / "labels.jsonl")
    cases = {c["case_id"]: c for c in _read_jsonl(path / "cases.jsonl")}
    for i, row in enumerate(rows):
        row.update(reviewer="synthetic-test-reviewer", reference_kind=kind)
        row["values"]["mode"].update(value=modes[i], evidence_ids=[cases[row["case_id"]]["event_id"]],
                                    extraction=extraction, context_sufficiency="sufficient")
    _write_jsonl(path / "labels.jsonl", rows)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "reference"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_labels_does_not_fabricate_accuracy_or_holdout(self):
        report = prepare([bundle()], self.root, per_run=0)
        self.assertEqual(report["reference_labels"], 0)
        self.assertEqual(report["holdout_cases"], 0)
        result = evaluate(self.root, split="development")
        self.assertEqual(result["status"], "no_reference_labels")
        self.assertIsNone(result["metrics"]["mode"]["selective_accuracy"])
        self.assertEqual(evaluate(self.root)["selected_cases"], 0)

    def test_packet_blinding_cutoff_and_current_feedback_exclusion(self):
        b = bundle()
        prepare([b], self.root, per_run=0)
        cases = _read_jsonl(self.root / "cases.jsonl")
        serialized = json.dumps(cases)
        self.assertNotIn("HIDDEN-POLICY", serialized)
        self.assertNotIn("FUTURE-OUTCOME", serialized)
        self.assertNotIn('"probabilities"', serialized)
        self.assertNotIn("RESULT-0", json.dumps(cases[0]))
        self.assertIn("RESULT-0", json.dumps(cases[1]))
        self.assertNotIn("RESULT-1", json.dumps(cases[1]))
        for case in cases:
            current = next(e for e in case["available_prefix"] if e["id"] == case["event_id"])
            self.assertTrue(all(e["index"] <= current["index"] for e in case["available_prefix"]))

    def test_group_leakage_and_seen_holdout_rejected(self):
        b1, b2 = bundle(task="a"), bundle(task="b")
        groups = {b1["run"]["id"]: {"group": "repo", "split": "development"},
                  b2["run"]["id"]: {"group": "repo", "split": "holdout", "exposure": "unseen"}}
        with self.assertRaisesRegex(InputError, "cannot cross"):
            prepare([b1,b2], self.root, group_map=groups)
        with self.assertRaisesRegex(InputError, "declared unseen"):
            prepare([b1], self.root, group_map={b1["run"]["id"]: {"group": "repo", "split": "holdout"}})
        self.assertFalse(self.root.exists())

    def test_stale_case_and_duplicate_reference_rejected(self):
        prepare([bundle()], self.root)
        labels = _read_jsonl(self.root / "labels.jsonl")
        _write_jsonl(self.root / "labels.jsonl", labels + labels[:1])
        with self.assertRaisesRegex(InputError, "duplicate"):
            evaluate(self.root)
        labels[0]["case_hash"] = "changed"
        _write_jsonl(self.root / "labels.jsonl", labels)
        with self.assertRaisesRegex(InputError, "Stale"):
            evaluate(self.root)

    def test_same_raw_source_cannot_hide_in_another_holdout_group(self):
        left, right = bundle(task="a"), bundle(task="b")
        with self.assertRaisesRegex(InputError, "Identical source"):
            prepare([left, right], self.root, group_map={
                left["run"]["id"]: {"group": "a", "split": "development"},
                right["run"]["id"]: {"group": "b", "split": "holdout", "exposure": "unseen"}})

    def test_selective_accuracy_and_recall_have_distinct_denominators(self):
        prepare([bundle(["cat a", "opaque_command", "pytest"])], self.root, per_run=0)
        fill_labels(self.root, ["explore", "explore", "apply"])
        result = evaluate(self.root, split="development")
        m = result["metrics"]["mode"]
        self.assertEqual(m["scorable_cases"], 3)
        self.assertEqual(m["decided_cases"], 2)
        self.assertEqual(m["selective_accuracy"], .5)
        self.assertEqual(m["overall_correct_share"], 1/3)
        self.assertEqual(m["per_class"]["explore"]["recall"], .5)
        self.assertEqual(result["macro"][0]["purpose_share_error"]["explore"], -1/3)

    def test_model_proposals_and_invalid_extraction_are_not_reference_truth(self):
        prepare([bundle(["cat a"])], self.root, per_run=0)
        fill_labels(self.root, ["explore"], kind="model_proposal")
        result = evaluate(self.root, split="development")
        self.assertEqual(result["status"], "no_reference_labels")
        self.assertEqual(result["excluded"]["mode.model_proposal"], 1)
        fill_labels(self.root, ["explore"], extraction="invalid")
        result = evaluate(self.root, split="development")
        self.assertEqual(result["excluded"]["mode.extraction_invalid"], 1)
        self.assertIsNone(result["metrics"]["mode"]["selective_accuracy"])

    def test_sparse_annotation_never_establishes_whole_run_macro(self):
        prepare([bundle()], self.root, per_run=1)
        fill_labels(self.root, ["explore"])
        result = evaluate(self.root, split="development")
        self.assertEqual(result["macro"][0]["status"], "incomplete_reference_or_predictions")
        self.assertNotIn("purpose_share_error", result["macro"][0])

    def test_unknown_purpose_prevents_positive_closure_claim(self):
        prepare([bundle(["pytest", "opaque_command"])], self.root, per_run=0)
        fill_labels(self.root, ["verify", "unresolved"])
        result = evaluate(self.root, split="development")
        self.assertEqual(set(result["macro"][0]["closure"]["reference"].values()), {"unresolved"})

    def test_evidence_outside_prefix_is_rejected(self):
        prepare([bundle()], self.root, per_run=0)
        fill_labels(self.root, ["explore", "apply", "verify", "report"])
        labels = _read_jsonl(self.root / "labels.jsonl")
        labels[0]["values"]["mode"]["evidence_ids"] = ["future-event"]
        _write_jsonl(self.root / "labels.jsonl", labels)
        with self.assertRaisesRegex(InputError, "supplied prefix"):
            evaluate(self.root, split="development")

    def test_reference_export_preserves_existing_labels_and_source(self):
        b = bundle(); saved = copy.deepcopy(b)
        prepare([b], self.root)
        with self.assertRaisesRegex(InputError, "never overwritten"):
            prepare([b], self.root)
        self.assertEqual(b, saved)

    def test_missing_predictions_are_not_counted_as_success_or_hidden(self):
        prepare([bundle(["cat a"])], self.root, per_run=0)
        fill_labels(self.root, ["explore"])
        _write_jsonl(self.root / "predictions.jsonl", [])
        result = evaluate(self.root, split="development")
        self.assertEqual(result["metrics"]["mode"]["missing_predictions"], 1)
        self.assertEqual(result["metrics"]["mode"]["overall_correct_share"], 0)
        self.assertIsNone(result["metrics"]["mode"]["selective_accuracy"])

    def test_stale_inspector_packet_cannot_become_a_frozen_baseline(self):
        b = bundle(["cat a"])
        action = b["analysis"]["actions"][0]["event_id"]
        b["model_observations"] = {action: {"mode": {"status": "decided", "value": "explore"},
            "_provenance": {"harness": JEV_HARNESS, "packet_hash": "wrong", "threshold": .9}}}
        with self.assertRaisesRegex(InputError, "does not match"):
            prepare([b], self.root)

    def test_heuristic_and_semantic_predictions_keep_distinct_quality_slices(self):
        b = bundle(["cat a", "edit a"])
        action = b["analysis"]["actions"][1]["event_id"]
        b["model_observations"] = {action: JevClient(transport=response_for).evaluate(b["run"], action)}
        prepare([b], self.root, per_run=0)
        fill_labels(self.root, ["explore", "apply"])
        result = evaluate(self.root, split="development")
        self.assertTrue(result["mixed_predictor_profiles"])
        self.assertEqual({p["profile"]["method"] for p in result["profile_slices"].values()}, {"heuristic", "jev"})


if __name__ == "__main__":
    unittest.main()
