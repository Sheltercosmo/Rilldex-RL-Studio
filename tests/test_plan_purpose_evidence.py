"""Replay actual Plan/Coordinate observations; never call a model or claim truth."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.evaluate_plan_purpose import _validate_source
from tracker.adapters import normalize
from tracker.jev import validate_answers
from tracker.schema import InputError, digest
from tracker.semantic_extraction import request as activity_request
from tracker.semantic_map import evidence


def reconstruct(fixture, case, arm):
    question = deepcopy(fixture["common_question"])
    overrides = deepcopy(case["question_overrides"])
    question["criteria"].update(overrides.pop("criteria"))
    question.update(overrides)
    question["instructions"] += case["arms"][arm]["instruction_suffix"]
    return {"model": fixture["model"], "state": deepcopy(case["request_state"]),
            "questions": {"choice": question}}


def rebuild_from_source(fixture, case, document):
    """Exercise production source projection with frozen activity definitions."""
    run = normalize(document)[0]
    baseline = reconstruct(fixture, case, "original")
    state = baseline["state"]
    question = baseline["questions"]["choice"]
    ref = evidence(run, case["event_id"])
    context = {key: deepcopy(state[key]) for key in
               ("activity_routing", "expression_form", "contribution_scope") if key in state}
    request = activity_request(run, ref, "activity", question["instructions"],
                               deepcopy(question["criteria"]), deepcopy(state["context_policy"]),
                               **context)
    request["model"] = baseline["model"]
    return run, request


class PlanPurposeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "fixtures" / "plan-purpose-evidence.json"
        cls.fixture = json.loads(path.read_text(encoding="utf-8"))
        cls.cases = {case["case_id"]: case for case in cls.fixture["cases"]}

    def test_real_responses_replay_with_exact_hashes_and_source_attribution(self):
        count = 0
        with patch("urllib.request.urlopen", side_effect=AssertionError("Replay must be offline")):
            for case in self.cases.values():
                self.assertEqual(digest(case["source_view"]), case["source_view_hash"])
                for arm, receipt in case["arms"].items():
                    with self.subTest(case=case["case_id"], arm=arm):
                        request = reconstruct(self.fixture, case, arm)
                        self.assertEqual(digest(request), receipt["request_hash"])
                        self.assertEqual(digest(receipt["response"]), receipt["response_hash"])
                        self.assertEqual(receipt["response"]["model"], request["model"])
                        audit = _validate_source(request, case["source_view"])
                        self.assertFalse(audit["future_events_present"])
                        answer = validate_answers(receipt["response"], request)["choice"]
                        self.assertEqual(answer["status"], "decided")
                        self.assertEqual(answer["value"], receipt["prediction"])
                        count += 1
        self.assertEqual(count, 14)

    def test_explicit_self_plan_and_addressed_request_remain_different_roles(self):
        first = self.cases["simulation_first_person"]
        directed = self.cases["simulation_addressed_user"]
        self.assertIn("I will first", first["request_state"]["subject"]["text"])
        self.assertIn("yourself on your console", directed["request_state"]["subject"]["text"])
        for case, expected in ((first, "plan"), (directed, "coordinate")):
            with self.subTest(case=case["case_id"]):
                self.assertEqual(case["reference"]["label"], expected)
                self.assertEqual([event["actor"] for event in case["source_view"]["events"]],
                                 ["user", "agent"])
                self.assertFalse(any(event["kind"] == "action" for event in case["source_view"]["events"]))
                self.assertNotIn("activity_reading_candidates", case["request_state"])
                for arm, receipt in case["arms"].items():
                    request = reconstruct(self.fixture, case, arm)
                    self.assertEqual(validate_answers(receipt["response"], request)["choice"]["value"], expected)
        self.assertEqual(first["request_state"]["tool_catalog"], directed["request_state"]["tool_catalog"])

    def test_no_scored_gain_and_ambiguous_change_is_never_counted_as_correction(self):
        for arm in ("original", "ownership_clarification"):
            scored = [case for case in self.cases.values() if case["reference"]["status"] != "ambiguous"]
            matches = sum(case["arms"][arm]["prediction"] == case["reference"]["label"] for case in scored)
            self.assertEqual((len(scored), matches), (6, 6))
            self.assertEqual(self.fixture["reported_groups"][arm]["reference_matches"], matches)
        ambiguous = self.cases["simulation"]
        self.assertEqual(ambiguous["reference"]["status"], "ambiguous")
        self.assertIsNone(ambiguous["reference"]["label"])
        self.assertEqual(ambiguous["arms"]["original"]["prediction"], "coordinate")
        self.assertEqual(ambiguous["arms"]["ownership_clarification"]["prediction"], "plan")
        self.assertTrue(all(receipt["reference_match"] is None for receipt in ambiguous["arms"].values()))
        changes = [case["case_id"] for case in self.cases.values()
                   if case["arms"]["original"]["prediction"] != case["arms"]["ownership_clarification"]["prediction"]]
        self.assertEqual(changes, ["simulation"])

    def test_paired_ablation_changes_only_generic_instructions(self):
        for case in self.cases.values():
            with self.subTest(case=case["case_id"]):
                baseline = reconstruct(self.fixture, case, "original")
                clarified = reconstruct(self.fixture, case, "ownership_clarification")
                self.assertEqual(clarified["questions"]["choice"]["instructions"],
                                 baseline["questions"]["choice"]["instructions"] + " " + self.fixture["clarification"])
                clarified["questions"]["choice"]["instructions"] = baseline["questions"]["choice"]["instructions"]
                self.assertEqual(clarified, baseline)
                self.assertNotIn("reference", baseline)
                self.assertNotIn("reference", baseline["state"])

    def test_later_execution_and_feedback_cannot_change_the_earlier_activity_packet(self):
        for name in ("simulation_first_person", "simulation_addressed_user"):
            case = self.cases[name]
            original_run, original = rebuild_from_source(self.fixture, case, deepcopy(case["document"]))
            self.assertEqual(original, reconstruct(self.fixture, case, "original"))
            for later_text in ("Motion completed; position=G.", "Stopped at N1; no arrival."):
                with self.subTest(case=name, future_result=later_text):
                    document = deepcopy(case["document"])
                    document["messages"].extend([
                        {"role": "assistant", "content": None, "tool_calls": [
                            {"id": "future-call", "type": "function", "function": {
                                "name": "advance", "arguments": '{"rover":"R2","route":["S","G"]}'}}]},
                        {"role": "tool", "tool_call_id": "future-call", "content": later_text},
                    ])
                    extended_run, rebuilt = rebuild_from_source(self.fixture, case, document)
                    self.assertGreater(len(extended_run["events"]), len(original_run["events"]))
                    self.assertEqual(rebuilt, original)
                    self.assertFalse(_validate_source(rebuilt, extended_run)["future_events_present"])

    def test_future_prefix_and_nested_evidence_injections_are_rejected(self):
        case = self.cases["simulation_first_person"]
        document = deepcopy(case["document"])
        document["messages"].append({"role": "assistant", "content": "Later I report arrival at G."})
        run, request = rebuild_from_source(self.fixture, case, document)
        future = run["events"][-1]
        bad_prefix = deepcopy(request)
        bad_prefix["state"]["prefix"].append(deepcopy(future))
        with self.assertRaisesRegex(ValueError, "Future event"):
            _validate_source(bad_prefix, run)
        bad_evidence = deepcopy(request)
        bad_evidence["state"]["activity_reading_candidates"] = {
            "readings": [{"activity": "plan", "evidence": [evidence(run, future["id"])]}]}
        with self.assertRaisesRegex(InputError, "Future evidence"):
            _validate_source(bad_evidence, run)

    def test_old_variant_quotes_and_changed_actor_attribution_are_rejected(self):
        first = self.cases["simulation_first_person"]
        request = reconstruct(self.fixture, first, "original")
        stale = deepcopy(request)
        stale["state"]["subject"] = deepcopy(self.cases["simulation"]["request_state"]["subject"])
        with self.assertRaisesRegex(InputError, "Evidence mismatch"):
            _validate_source(stale, first["source_view"])
        wrong_actor = deepcopy(request)
        wrong_actor["state"]["prefix"][-1]["actor"] = "user"
        with self.assertRaisesRegex(ValueError, "attribution"):
            _validate_source(wrong_actor, first["source_view"])


if __name__ == "__main__":
    unittest.main()
