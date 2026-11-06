"""Portable source regeneration and actual response replay, not fresh accuracy."""
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.evaluate_heldout_generalization import FIXTURE, evaluate, requests, source_request
from tracker.jev import validate_answers
from tracker.schema import digest, dumps
from tracker.semantic_extraction import read


def semantic_fields(request):
    result = deepcopy(request)
    # Executor reports deliberately hash the entire recording for provenance;
    # that binding may change even when their inspected source pair does not.
    if result["state"].get("stage") == "executor_reports":
        result["state"].pop("source_hash")
    return result


class HeldoutGeneralizationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = read(FIXTURE)
        cls.cases = {case["case_id"]: case for case in cls.fixture["review"]["cases"]}

    def source(self, case_id):
        return self.fixture["sources"][self.fixture["case_source_views"][case_id]]

    def test_frozen_requests_replay_real_responses_without_relabeling_them_as_current(self):
        matches = Counter()
        with patch("urllib.request.urlopen", side_effect=AssertionError("Offline replay must not call a provider")):
            generated = list(requests(self.fixture))
        self.assertEqual(len(generated), 21)
        for row, request in generated:
            with self.subTest(observation=row["id"]):
                self.assertEqual(digest(request), row["request_hash"])
                self.assertEqual(digest(row["response"]), row["response_hash"])
                self.assertEqual(row["response"]["model"], request["model"])
                answers = validate_answers(row["response"], request)
                for key, score in row["recorded_scores"].items():
                    self.assertEqual(answers[key]["value"], score["prediction"])
                    self.assertTrue(score["reference_match"])
                    matches[row["layer"]] += 1
        self.assertEqual(matches, Counter(macro=10, activity=10, executor_report=2))

    def test_live_evaluation_uses_current_requests_and_keeps_historical_references(self):
        old = {row['id']: request for row, request in requests(self.fixture)}
        current = list(requests(self.fixture, current=True))
        for row, request in current:
            if row['layer'] == 'macro':
                self.assertNotEqual(request, old[row['id']])
                self.assertIn('feedback_reading_scope', request['state'])
            else:
                self.assertEqual(request, old[row['id']])
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            report = evaluate(directory, live=True, max_calls=0)
            self.assertEqual(report['request_origin'], 'current_readers')
            self.assertEqual(report['status'], 'pending')
            result = read(Path(directory) / 'report.json')
            expected = {row['id']: digest(request) for row, request in current}
            for row in result['results']:
                self.assertEqual(row['request_hash'], expected[row['id']])
                self.assertEqual(row['reference_request_hash'], digest(old[row['id']]))

    def test_pre_live_review_and_exact_event_provenance_survive_without_private_state(self):
        self.assertEqual(digest(self.fixture["review"]), self.fixture["pre_live_review_hash"])
        self.assertEqual(len(self.fixture["sources"]), 5)
        excluded = set(self.fixture["review"]["scope"]["excluded_simulation_ids"])
        for source in self.fixture["sources"].values():
            self.assertNotIn(source["simulation_id"], excluded)
            self.assertEqual(digest(source["run"]), source["projection_hash"])
            self.assertEqual(digest(source["run"]["events"]), source["native_event_records_hash"])
            self.assertEqual(source["run"]["raw"], {})
            self.assertEqual(source["run"]["outcome"], {})
            self.assertEqual(source["run"]["metadata"], {})
        for case in self.cases.values():
            self.assertEqual(case["normalized_source_hash"], self.source(case["case_id"])["original_source_hash"])
            self.assertEqual(case["references"]["status"], "model_reviewed_pre_live_development_judgment")

    def test_every_evidence_reference_is_visible_at_its_native_cutoff(self):
        checked = 0
        for row, request in requests(self.fixture):
            events = {event["id"]: event for event in self.source(row["case_id"])["run"]["events"]}
            cutoff = events[request["state"]["cutoff_event_id"]]

            def walk(value):
                nonlocal checked
                if isinstance(value, dict):
                    event_id = value.get("event_id") or (value.get("id") if "kind" in value and "text" in value else None)
                    if event_id in events:
                        event = events[event_id]
                        self.assertLessEqual(event["index"], cutoff["index"], (row["id"], event_id))
                        self.assertFalse(event["kind"].startswith("external_"), (row["id"], event_id))
                        self.assertNotEqual(event.get("agent_visibility"), "not_established")
                        checked += 1
                    for item in value.values():
                        walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)

            walk(request["state"])
        self.assertGreater(checked, 400)

    def test_later_results_and_private_participant_payloads_do_not_change_reader_evidence(self):
        private_changed = 0
        future_changed = 0
        marker = "UNOBSERVED_PRIVATE_OR_FUTURE_SENTINEL"
        for row in self.fixture["observations"]:
            case = self.cases[row["case_id"]]
            run = self.source(row["case_id"])["run"]
            baseline = source_request(run, case["event_id"], row["layer"], self.fixture["model"])
            cutoff = next(event for event in run["events"] if event["id"] == baseline["state"]["cutoff_event_id"])
            changed = deepcopy(run)
            changed.update(raw={"evaluator": marker, "private_user_state": marker},
                           outcome={"success": True, "recorded_reward": 999}, metadata={"private_hint": marker})
            for event in changed["events"]:
                private = event["kind"].startswith("external_") or event.get("agent_visibility") == "not_established"
                future = event["index"] > cutoff["index"]
                if private or future:
                    event["text"] = marker
                    if "arguments" in event:
                        event["arguments"] = {"unobserved_payload": marker}
                    event["content_hash"] = digest(event["text"])
                    private_changed += int(private)
                    future_changed += int(future)
            regenerated = source_request(changed, case["event_id"], row["layer"], self.fixture["model"])
            with self.subTest(observation=row["id"]):
                self.assertEqual(semantic_fields(regenerated), semantic_fields(baseline))
                self.assertNotIn(marker, dumps(regenerated))
                if row["layer"] == "executor_report":
                    self.assertNotEqual(regenerated["state"]["source_hash"], baseline["state"]["source_hash"])
        self.assertGreater(private_changed, 0)
        self.assertGreater(future_changed, 0)

    def test_visible_payment_claim_changes_both_readers_and_line_instances_stay_literal(self):
        case = self.cases["telecom-11-e38"]
        run = self.source(case["case_id"])["run"]
        changed = deepcopy(run)
        next(event for event in changed["events"] if event["id"] == "e36")["text"] = "I have not made the overdue payment."
        for layer in ("macro", "activity"):
            before = source_request(run, "e38", layer, self.fixture["model"])
            after = source_request(changed, "e38", layer, self.fixture["model"])
            self.assertNotEqual(before, after)
            self.assertIn("I have not made the overdue payment.", dumps(after))
        for event_id, line_id in (("e15", "L1001"), ("e18", "L1002")):
            request = source_request(run, event_id, "macro", self.fixture["model"])
            self.assertIn(line_id, request["state"]["current_action"]["text"])
        # No synthetic prediction is asserted for the altered claim.

    def test_failed_test_in_handoff_payload_is_not_an_executor_error_of_transfer(self):
        observation = next(row for row in self.fixture["observations"] if row["layer"] == "executor_report")
        source = self.source(observation["case_id"])
        request = source_request(source["run"], "e52", "executor_report", self.fixture["model"])
        self.assertIn("Speed test fails", request["state"]["action"]["text"])
        self.assertEqual(request["state"]["response"]["text"], "Transfer successful")
        answers = validate_answers(observation["response"], request)
        self.assertEqual({key: answers[key]["value"] for key in ("error", "warning")},
                         {"error": "not_reported", "warning": "not_reported"})
        self.assertEqual(request["state"]["source_hash"], source["projection_hash"])
        historical = next(request for row, request in requests(self.fixture) if row["id"] == observation["id"])
        self.assertEqual(historical["state"]["source_hash"], source["original_source_hash"])
        self.assertEqual(semantic_fields(historical), semantic_fields(request))

    def test_runner_is_portable_offline_and_never_persists_process_credentials(self):
        sentinel = "NOT_A_REAL_CREDENTIAL_REPLAY_SECRET"
        read_text = Path.read_text

        def without_local_archives(path, *args, **kwargs):
            self.assertNotIn(".tracker", path.parts)
            return read_text(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"JEV_API_KEY": sentinel}), \
                patch("urllib.request.urlopen", side_effect=AssertionError("Replay must not use the network")), \
                patch.object(Path, "read_text", without_local_archives), redirect_stdout(io.StringIO()):
            result = evaluate(directory)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["new_calls_this_invocation"], 0)
            self.assertEqual({layer: group["reference_matches"] for layer, group in result["groups"].items()},
                             {"macro": 10, "activity": 10, "executor_report": 2})
            for path in Path(directory).rglob("*.json"):
                self.assertNotIn(sentinel, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
