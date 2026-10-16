"""Experiment integrity checks; these are not semantic reference labels."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import expression_challenge as experiment
from tracker.schema import InputError


def response(request):
    answers = {}
    for key, question in request["questions"].items():
        options = list(question["criteria"])
        top = 0.4 if len(options) > 2 else 0.6
        answers[key] = {"type": "choice", "choice": options[-1], "confidence": 0.999,
                        "probabilities": {option: top if i == 0 else (1-top)/(len(options)-1)
                                          for i, option in enumerate(options)}}
    return {"model": request["model"], "answers": answers}


class ExpressionChallengeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "frozen"
        experiment.prepare(self.directory)

    def fake_run(self, variant="current"):
        with patch.dict(os.environ, {"JEV_API_KEY": "synthetic-test-only"}), \
             patch.object(experiment.JevClient, "_post", side_effect=response) as transport, \
             redirect_stdout(io.StringIO()):
            experiment.run(self.directory, variant, "development")
        return transport.call_count

    def test_variants_preserve_evidence_and_keep_authored_proposals_outside_requests(self):
        manifest, cases = experiment.load(self.directory)
        self.assertEqual(len(cases), 32)
        self.assertEqual(sum(c["set"] == "challenge" for c in cases), 12)
        for case in cases:
            current = case["requests"]["current"]
            for variant, request in case["requests"].items():
                self.assertEqual(request["state"], current["state"])
                self.assertEqual(set(request), {"state", "questions", "model"})
                self.assertEqual(request["state"]["subject"]["text"], case["target"]["text"])
                self.assertEqual(request["model"], manifest["model"])
                for key, question in current["questions"].items():
                    if key != "expression": self.assertEqual(request["questions"][key], question)
            self.assertNotIn("expression", case["requests"]["faceted"]["questions"])
            self.assertEqual(sum(k.startswith("expression_") for k in case["requests"]["faceted"]["questions"]), 8)

    def test_run_is_resumable_without_repeated_calls_and_uses_argmax(self):
        self.assertEqual(self.fake_run(), 20)
        path = self.directory / "current-development.jsonl"
        original = path.read_bytes()
        self.assertEqual(self.fake_run(), 0)
        self.assertEqual(path.read_bytes(), original)
        report = experiment.summarize(self.directory)
        self.assertIsNone(report["semantic_accuracy"])
        self.assertEqual(report["independent_reference_labels"], 0)
        self.assertEqual(report["results"]["current/development"]["completed_cases"], 20)
        first = json.loads(path.read_text().splitlines()[0])
        self.assertEqual(first["answers"]["orient"]["value"], "present")
        self.assertEqual(first["answers"]["orient"]["status"], "decided")

    def test_modified_frozen_input_is_rejected(self):
        path = self.directory / "cases.json"
        cases = json.loads(path.read_text())
        cases[0]["requests"]["current"]["state"]["subject"]["text"] = "changed"
        path.write_text(json.dumps(cases))
        with self.assertRaisesRegex(InputError, "Frozen challenge cases changed"):
            experiment.load(self.directory)

    def test_corrupt_results_cannot_silently_enter_comparisons(self):
        self.fake_run()
        path = self.directory / "current-development.jsonl"
        original = path.read_text()
        first = json.loads(original.splitlines()[0])
        alterations = [
            ("duplicate", original + json.dumps(first) + "\n"),
            ("wrong set", None), ("wrong model", None), ("wrong decision", None),
        ]
        for name, text in alterations:
            changed = deepcopy(first)
            if name == "wrong set": changed["set"] = "challenge"
            elif name == "wrong model": changed["model"] = "different-model"
            elif name == "wrong decision": changed["answers"]["orient"]["value"] = "absent"
            path.write_text(text or json.dumps(changed) + "\n")
            with self.subTest(name=name), self.assertRaises(InputError):
                experiment.summarize(self.directory)

    def test_faceted_contradiction_is_exposed_without_rewriting_choices(self):
        self.fake_run("faceted")
        path = self.directory / "faceted-development.jsonl"
        record = json.loads(path.read_text().splitlines()[0])
        answer = record["answers"]["expression_assertion"]
        answer["probabilities"] = {"present": 0.3, "absent": 0.4, "unresolved": 0.3}
        answer["value"] = "absent"
        path.write_text(json.dumps(record) + "\n")
        report = experiment.summarize(self.directory)["results"]["faceted/development"]
        self.assertEqual(report["contradictions"], 1)
        self.assertNotIn("assertion", report["checks"][0]["returned"])

    def test_cases_without_proposals_do_not_get_an_accuracy_or_match_score(self):
        manifest_path = self.directory / "manifest.json"
        cases_path = self.directory / "cases.json"
        manifest, cases = experiment.load(self.directory)
        for case in cases: case.pop("proposal")
        manifest["cases_hash"] = experiment.digest(cases)
        cases_path.write_text(json.dumps(cases))
        manifest_path.write_text(json.dumps(manifest))
        self.fake_run()
        result = experiment.summarize(self.directory)
        self.assertIsNone(result["semantic_accuracy"])
        report = result["results"]["current/development"]
        self.assertIsNone(report["proposal_matches"])
        self.assertTrue(all(c["matches_authored_proposal"] is None for c in report["checks"]))


if __name__ == "__main__": unittest.main()
