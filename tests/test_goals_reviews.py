import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tracker.adapters import normalize
from tracker.goals import catalog, focus_candidates
from tracker.jev import packet
from tracker.observe import analyze
from tracker.reviews import options, validate
from tracker.schema import InputError
from tracker.store import ReviewConflict, Store


def planned_run():
    steps = [{"step_id": 1, "source": "user", "message": "Fix the parser and add regression tests."}]
    for i, (plan, path) in enumerate([
        ("I will inspect the parser.", "parser.py"),
        ("I will inspect the tests.", "tests.py"),
        ("Return to earlier work.", "parser.py"),
        ("I will inspect the parser.", "parser.py"),
    ], 2):
        steps.append({"step_id": i, "source": "agent", "message": plan,
                      "tool_calls": [{"tool_call_id": str(i), "function_name": "read_file", "arguments": {"path": path}}],
                      "observation": {"results": [{"source_call_id": str(i), "content": path}]}})
    return normalize({"schema_version": "ATIF-v1.7", "session_id": "planned", "agent": {"name": "test"}, "steps": steps})[0]


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.run = planned_run()
        self.registry = catalog(self.run)
        self.actions = analyze(self.run)["actions"]
        self.plans = [g for g in self.registry["goals"] if g["kind"] == "expressed_plan"]

    def assignment(self, aid, gid):
        return {aid: {"focus_goal": {"value": gid, "status": "decided"}}}

    def test_extractive_candidates_are_stable_and_prefix_bounded(self):
        self.assertEqual(len(self.plans), 2)
        self.assertEqual(len(self.plans[0]["references"]), 2)
        events = {e["id"]: e for e in self.run["events"]}
        for g in self.plans:
            for ref in g["references"]:
                s = ref["selector"]
                self.assertEqual(events[ref["event_id"]]["text"][s["start"]:s["end"]], g["text"])
        first = focus_candidates(self.run, self.actions[0]["event_id"])
        self.assertEqual(len(first["candidates"]), 2)
        self.assertEqual(len(first["candidates"][1]["references"]), 1)
        self.assertNotIn("I will inspect the tests.", json.dumps(packet(self.run, self.actions[0]["event_id"])))
        shorter = copy.deepcopy(self.run)
        shorter["events"] = shorter["events"][:self.actions[1]["index"]]
        self.assertEqual(catalog(shorter)["goals"][1]["id"], self.plans[0]["id"])

    def test_quoted_and_code_plans_are_not_commitments(self):
        run = copy.deepcopy(self.run)
        expression = next(e for e in run["events"] if e["actor"] == "agent" and e["kind"] == "message")
        expression["text"] = "> I will steal data.\n```\nI will delete tests.\n```\nI will read the parser."
        texts = [g["text"] for g in catalog(run)["goals"] if g["kind"] == "expressed_plan"]
        self.assertNotIn("I will steal data.", texts)
        self.assertNotIn("I will delete tests.", texts)
        self.assertIn("I will read the parser.", texts)

    def test_candidates_do_not_imply_pursuit_or_completion(self):
        analysis = analyze(self.run)
        self.assertEqual(analysis["goal_tracking"]["coverage"]["assigned"], 0)
        self.assertEqual(analysis["goal_tracking"]["coverage"]["pursued_plans"], 0)
        self.assertTrue(all(g["attainment"] == "unobserved" for g in analysis["goal_tracking"]["goals"]))

    def test_adjacent_commitments_stay_one_literal_plan_block(self):
        run = copy.deepcopy(self.run)
        expression = next(e for e in run["events"] if e["actor"] == "agent" and e["kind"] == "message")
        text = "Now let's modify equality. We will use a filtered dictionary."
        expression["text"] = text
        candidates = focus_candidates(run, self.actions[0]["event_id"])["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[1]["text"], text)

    def test_return_is_distinct_from_reobservation_after_unknown_gap(self):
        ids = [a["event_id"] for a in self.actions]
        ga, gb = (g["id"] for g in self.plans)
        semantics = {**self.assignment(ids[0], ga), **self.assignment(ids[1], gb), **self.assignment(ids[2], ga)}
        tracked = analyze(self.run, semantics)["goal_tracking"]
        self.assertEqual([t["kind"] for t in tracked["transitions"]], ["first_focus", "switch", "return"])
        del semantics[ids[1]]
        tracked = analyze(self.run, semantics)["goal_tracking"]
        self.assertEqual([t["kind"] for t in tracked["transitions"]], ["first_focus", "focus_reobserved"])
        self.assertEqual(tracked["graph"]["edges"], [])

    def test_initial_objective_is_retained_across_context_and_actor_boundary(self):
        run = copy.deepcopy(self.run)
        root = run["events"][0]; root["copied_context"] = True
        # A child with no instruction inherits the recorded ancestor objective.
        actor = root["trajectory_id"]
        for e in run["events"][1:]:
            e["trajectory_id"] = actor + "/child"
        tracked = analyze(run)["goal_tracking"]
        root_id = tracked["roots"][actor]
        self.assertTrue(all(a["root_id"] == root_id for a in tracked["assignments"]))
        request = packet(run, self.actions[0]["event_id"])
        self.assertEqual(request["state"]["authorized_instructions"][0]["event_id"], root["id"])

    def test_long_objective_has_bounded_packet_and_recorded_truncation(self):
        self.run["events"][0]["text"] = "A" * 9000 + "HIDDEN_END"
        request = packet(self.run, self.actions[0]["event_id"])
        self.assertNotIn("HIDDEN_END", json.dumps(request))
        self.assertIn(self.run["events"][0]["id"], request["state"]["missingness"]["truncated_event_ids"])


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "db.sqlite")
        self.run = planned_run(); self.store.add([self.run])
        self.aid = analyze(self.run)["actions"][0]["event_id"]

    def payload(self, value="apply", revision=0, field="mode"):
        return {"event_id": self.aid, "field": field, "value": value, "reviewer": "test reviewer",
                "note": "Fixture review, not a real evaluation", "expected_revision": revision}

    def test_review_audit_preserves_model_source_and_clear_restores_original(self):
        original = {"mode": {"value": "explore", "status": "decided", "probabilities": {"explore": .99}}}
        self.store.record(self.run["id"], self.aid, "test", "fixture", "packet", original)
        result = self.store.review(self.run["id"], self.payload())
        bundle = self.store.get(self.run["id"], raw=True)
        action = bundle["analysis"]["actions"][0]
        self.assertEqual(action["mode"], "apply")
        self.assertEqual(action["observation_status"], "reviewed")
        self.assertEqual(action["semantic"]["mode"]["probabilities"], {})
        self.assertEqual(bundle["model_observations"][self.aid], original)
        self.assertEqual(bundle["run"]["raw"], self.run["raw"])
        self.store.review(self.run["id"], self.payload(None, result["review_revision"]))
        reopened = Store(self.store.path).get(self.run["id"])
        self.assertEqual(len(reopened["reviews"]), 2)
        self.assertEqual(reopened["analysis"]["actions"][0]["mode"], "explore")
        self.assertEqual(reopened["analysis"]["reviewed_actions"], 0)

    def test_stale_concurrent_review_is_rejected(self):
        def save(value):
            try:
                return self.store.review(self.run["id"], self.payload(value))
            except ReviewConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, ["apply", "verify"]))
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(len(self.store.reviews(self.run["id"])), 1)

    def test_missing_value_and_future_goal_are_rejected(self):
        p = self.payload(); del p["value"]
        with self.assertRaises(InputError): validate(self.run, p)
        future = next(g["id"] for g in catalog(self.run)["goals"] if g["text"] == "I will inspect the tests.")
        self.assertNotIn(future, options(self.run, self.aid)["focus_goal"])
        with self.assertRaises(InputError): validate(self.run, self.payload(future, field="focus_goal"))

    def test_reviewer_abstention_does_not_fall_back_to_heuristic(self):
        self.store.review(self.run["id"], self.payload("unresolved"))
        action = self.store.get(self.run["id"])["analysis"]["actions"][0]
        self.assertEqual(action["mode"], "unresolved")
        self.assertIn("Reviewer abstained", action["mode_basis"])

    def test_review_queue_groups_repeated_actions(self):
        doc = {"trajectory": [{"action": "unknown operation", "observation": ""} for _ in range(40)]}
        run = normalize(doc, "swe-agent")[0]; self.store.add([run])
        queue = self.store.get(run["id"])["analysis"]["review_queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(len(queue[0]["event_ids"]), 40)


if __name__ == "__main__":
    unittest.main()
