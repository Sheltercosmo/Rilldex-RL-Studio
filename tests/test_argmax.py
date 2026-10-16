"""Decision policy and offline migration contracts, not semantic accuracy tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.activity import ActivityClient, units
from tracker.adapters import normalize
from tracker.jev import JevClient, SELECTION_POLICY, validate_answers
from tracker.observe import goal_scope
from tracker.schema import InputError, digest, dumps
from tracker.store import Store
from test_activity import reasoning_run, response
from test_tracker import harbor, response_for


class SelectionTests(unittest.TestCase):
    def select(self, probabilities, **answer):
        request = {"questions": {"tag": {"criteria": dict.fromkeys(probabilities, "option")}},
                   "state": {"missingness": {}, "cutoff_event_id": "e1"}}
        return validate_answers({"answers": {"tag": {"type": "choice", "probabilities": probabilities, **answer}}}, request)["tag"]

    def test_confidence_and_provider_choice_never_control_selection(self):
        probabilities = {"present": .34, "absent": .33, "unresolved": .33}
        for metadata in ({}, {"confidence": 0}, {"confidence": 1}, {"confidence": None}, {"choice": "absent"}):
            selected = self.select(probabilities, **metadata)
            self.assertEqual((selected["value"], selected["status"]), ("present", "decided"))
            self.assertEqual(selected["selection_policy"], SELECTION_POLICY)
            self.assertNotIn("threshold", selected)

    def test_special_options_win_without_a_floor(self):
        for winner in ("unresolved", "not_applicable", "no_suitable_candidate"):
            selected = self.select({"a": .3, "b": .3, winner: .4}, confidence=1)
            self.assertEqual((selected["value"], selected["status"]), (winner, winner))

    def test_exact_ties_follow_criteria_order_not_reported_choice(self):
        selected = self.select({"absent": .5, "present": .5, "unresolved": 0}, choice="present")
        self.assertEqual(selected["value"], "absent")
        self.assertEqual(selected["provider_choice"], "present")

    def test_grouped_mass_cannot_overrule_the_selected_relationship(self):
        scope = goal_scope({"goal_relation": {"value": "outside", "status": "decided",
                             "probabilities": {"direct": .3, "supporting": .3, "outside": .4}}})
        self.assertEqual(scope["value"], "outside")
        self.assertAlmostEqual(scope["probabilities"]["connected"], .6)


def legacy_result(client, run, subject_id):
    saved = client.evaluate(run, subject_id)
    request = client.request(run, subject_id)
    saved["_provenance"].pop("selection_policy")
    saved["_provenance"]["threshold"] = .9
    saved["_provenance"]["packet_hash"] = digest({"request": request, "threshold": .9})
    key = "plan" if isinstance(client, ActivityClient) else "mode"
    target = "present" if key == "plan" else "explore"
    alternatives = list(request["questions"][key]["criteria"])
    other = next(v for v in alternatives if v != target)
    saved[key].update(value=target, status="unresolved", probabilities={v: .51 if v == target else .49 if v == other else 0 for v in alternatives}, confidence=0, threshold=.9)
    for k, v in saved.items():
        if not k.startswith("_"):
            v.pop("selection_policy", None)
            v.pop("provider_choice", None)
    return saved


class ReselectionTests(unittest.TestCase):
    def test_exact_packets_reselect_without_transport_and_stale_packets_fail(self):
        run = reasoning_run(); uid = units(run)[0]["id"]
        client = ActivityClient(transport=response)
        saved = legacy_result(client, run, uid); original = copy.deepcopy(saved)
        client.transport = lambda _: self.fail("Offline reselection must never call Jev")
        result = client.reselect(saved, run, uid)
        self.assertEqual(result["plan"]["status"], "decided")
        self.assertEqual(result["_provenance"]["provider_calls"], 0)
        self.assertEqual(result["_provenance"]["original_result_hash"], digest(saved))
        self.assertEqual(saved, original)
        self.assertTrue(client.cache_matches(result, run, uid))
        changed = copy.deepcopy(run); changed["events"][0]["text"] += " New condition."
        with self.assertRaises(InputError): client.reselect(saved, changed, uid)
        tampered = copy.deepcopy(saved); tampered["_request"]["state"]["scope"] = "different"
        with self.assertRaises(InputError): client.reselect(tampered, run, uid)

    def test_store_preserves_history_sources_and_migrates_both_layers_idempotently(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "test.sqlite")
            run = normalize(harbor())[0]; store.add([run])
            action_id = next(e["id"] for e in run["events"] if e["kind"] == "action")
            uid = units(run)[0]["id"]
            for table, client, subject_id in (("observations", JevClient(transport=response_for), action_id),
                                             ("activity_observations", ActivityClient(transport=response), uid)):
                saved = legacy_result(client, run, subject_id); p = saved["_provenance"]
                with store.connect() as c:
                    c.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?)", (run["id"], subject_id, p["harness"], p["model"], p["packet_hash"], dumps(saved), "2026-01-01"))
            preview = store.reselect_observations()
            self.assertEqual(sum(t["eligible"] for t in preview["tables"].values()), 2)
            self.assertEqual(sum(t["written"] for t in preview["tables"].values()), 0)
            report = store.reselect_observations(apply=True)
            self.assertEqual(sum(t["written"] for t in report["tables"].values()), 2)
            self.assertEqual(report["provider_calls"], 0)
            self.assertEqual(store.get(run["id"], raw=True)["run"], run)
            self.assertEqual(store.observations(run["id"])[action_id]["mode"]["status"], "decided")
            self.assertEqual(store.activity_observations(run["id"])[uid]["plan"]["status"], "decided")
            again = store.reselect_observations(apply=True)
            self.assertEqual(sum(t["already_current"] for t in again["tables"].values()), 2)
            with store.connect() as c:
                for table in ("observations", "activity_observations"):
                    self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 2)
                    old = json.loads(c.execute(f"SELECT result FROM {table} WHERE created_at='2026-01-01'").fetchone()[0])
                    self.assertEqual(old["_provenance"]["threshold"], .9)

    def test_reselection_retains_required_evidence_gate(self):
        run = reasoning_run(); run["events"][1]["text"] = "x" * 5001
        uid = units(run)[0]["id"]; client = ActivityClient(transport=response)
        result = client.reselect(legacy_result(client, run, uid), run, uid)
        self.assertEqual(result["plan"]["selection_status"], "decided")
        self.assertEqual(result["plan"]["status"], "unresolved")
        self.assertIn("truncated", result["plan"]["evidence_gate"])


if __name__ == "__main__":
    unittest.main()
