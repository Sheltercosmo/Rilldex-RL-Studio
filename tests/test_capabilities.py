import copy
import json
import unittest

from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.jev import JevClient, packet
from tracker.observe import analyze
from tracker.schema import InputError, digest
from tracker.swe_rl import pair_grading
from test_tracker import harbor, response_for


def swe_rl():
    return {"instance_id": "repo__project-1", "instance": {"instance_id": "repo__project-1", "base_commit": "commit-a"},
            "n_steps": 3, "exit_status": "Submitted", "model_patch": "FINAL_PATCH",
            "messages": [
                {"role": "system", "content": "Use the shell."},
                {"role": "user", "content": "Fix the parser."},
                {"role": "assistant", "content": "Inspect files.", "extra": {"actions": [{"command": "ls", "tool_call_id": "a"}]}},
                {"role": "tool", "content": "parser.py", "tool_call_id": "a"},
                {"role": "user", "content": "Harness reminder: check existing tests.", "extra": {"synthetic": "combo_ground"}},
                {"role": "assistant", "content": "Check the parser.", "extra": {"actions": [{"command": "pytest", "tool_call_id": "b"}]}},
                {"role": "tool", "content": "1 passed in 1s", "tool_call_id": "b", "extra": {"synthetic": "combo_ground"}},
                {"role": "assistant", "content": "Submit.", "extra": {"actions": [{"command": "submit", "tool_call_id": "c"}]}}]}


class SweRLTests(unittest.TestCase):
    def test_real_export_shape_preserves_actions_links_context_and_pointers(self):
        doc = swe_rl(); before = copy.deepcopy(doc)
        run = normalize(doc)[0]; a = analyze(run)
        self.assertEqual(doc, before)
        self.assertEqual(run["adapter"], "swe-rl")
        self.assertEqual([e["text"] for e in run["events"] if e["kind"] == "instruction"], ["Fix the parser."])
        self.assertEqual([x["text"] for x in a["actions"]], ["ls", "pytest", "submit"])
        self.assertEqual([len(x["feedback_ids"]) for x in a["actions"]], [1, 1, 0])
        self.assertIsNone(run["metadata"].get("checkpoint"))
        self.assertNotIn("training_step", run["metadata"])
        for e in run["events"]:
            value = doc
            for part in e["source_pointer"].strip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
            self.assertEqual(value, e["text"])
        self.assertEqual(a["capabilities"]["source"]["feedback_origins"], {"environment": 1, "harness": 1})
        req = packet(run, a["actions"][1]["event_id"])
        self.assertEqual(len(req["state"]["harness_context"]), 1)
        self.assertEqual(len(req["state"]["authorized_instructions"]), 1)
        self.assertNotIn("FINAL_PATCH", json.dumps(req))
        self.assertNotIn("1 passed", json.dumps(req))

    def test_duplicate_calls_bad_roles_and_inconsistent_task_are_rejected(self):
        doc = swe_rl(); doc["messages"][-1]["extra"]["actions"][0]["tool_call_id"] = "a"
        with self.assertRaises(InputError): normalize(doc)
        doc = swe_rl(); doc["messages"][2]["role"] = "developer"
        with self.assertRaises(InputError): normalize(doc)
        doc = swe_rl(); doc["instance"]["instance_id"] = "different"
        with self.assertRaises(InputError): normalize(doc)
        doc = swe_rl(); doc["messages"][2]["extra"]["actions"] = ""
        with self.assertRaises(InputError): normalize(doc)

    def test_unstructured_assistant_command_is_not_guessed(self):
        doc = swe_rl(); doc["messages"][2]["extra"] = {}; doc["messages"][2]["content"] = "```sh\nrm file\n```"
        run = normalize(doc)[0]; analysis = analyze(run)
        self.assertEqual(len(analysis["actions"]), 2)
        self.assertEqual(len(analysis["capabilities"]["source"]["unlinked_feedback_ids"]), 1)
        self.assertEqual(analysis["capabilities"]["measurements"]["work_sequence"]["status"], "limited")

    def test_explicit_grading_pair_is_bound_to_exact_content_and_never_leaks(self):
        doc = swe_rl(); grade = {"resolved": False, "final_reward": 0, "output": "SECRET_GRADER_OUTPUT"}
        source = pair_grading("repo__project-1_0.json", doc, "repo__project-1_0_rewards.json", grade)
        run = normalize(doc, sources=[source])[0]
        self.assertFalse(run["outcome"]["verified_success"])
        self.assertEqual(run["outcome"]["rewards"], {"final_reward": 0})
        self.assertEqual(run["sources"][0]["data"], grade)
        self.assertNotIn("SECRET_GRADER_OUTPUT", json.dumps(packet(run, analyze(run)["actions"][-1]["event_id"])))
        changed = copy.deepcopy(doc); changed["messages"][1]["content"] = "Different task"
        with self.assertRaises(InputError): normalize(changed, sources=[source])
        with self.assertRaises(InputError): pair_grading("repo__project-1_0.json", doc, "repo__project-1_1_rewards.json", grade)
        with self.assertRaises(InputError): pair_grading("wrong_task_0.json", doc, "wrong_task_0_rewards.json", grade)
        with self.assertRaises(InputError): normalize(doc, sources=[{**source, "data": {"resolved": "false"}}])

    def test_two_grades_cannot_silently_overwrite_each_other(self):
        doc = swe_rl()
        source = pair_grading("repo__project-1_0.json", doc, "repo__project-1_0_rewards.json", {"resolved": True})
        with self.assertRaises(InputError): normalize(doc, sources=[source, {**source, "name": "other.json", "data": {"resolved": False}}])


class EvidenceRequirementTests(unittest.TestCase):
    def test_missing_call_ids_do_not_match_each_other(self):
        run = normalize(swe_rl())[0]
        for e in run["events"]:
            e.pop("call_id", None); e.pop("source_call_id", None)
        analysis = analyze(run)
        request = packet(run, analysis["actions"][-1]["event_id"])
        self.assertTrue(all(not x["feedback"] for x in request["state"]["prior_actions"]))
        self.assertNotIn("feedback_response", request["questions"])
        self.assertEqual(analysis["metrics"]["linked_feedback"], 0)

    def test_cross_agent_and_future_feedback_are_not_used(self):
        run = normalize(swe_rl())[0]
        rows = analyze(run)["actions"]
        f = next(e for e in run["events"] if e["kind"] == "feedback")
        f["trajectory_id"] = "another-agent"
        self.assertIn(f["id"], links(run)["unlinked_ids"])
        f["trajectory_id"] = "main"; f["index"] = rows[1]["index"] + 1
        request = packet(run, rows[1]["event_id"])
        self.assertEqual(request["state"]["prior_actions"][0]["feedback"], [])
        self.assertNotIn("feedback_response", request["questions"])

    def test_textless_feedback_remains_an_unknown_opportunity(self):
        doc = swe_rl(); doc["messages"][3]["content"] = ""
        run = normalize(doc)[0]; a = analyze(run)["actions"][1]
        self.assertTrue(a["feedback_opportunity"])
        self.assertEqual(a["feedback_support"]["status"], "unresolved")
        req = packet(run, a["event_id"])
        self.assertNotIn("feedback_response", req["questions"])
        result = JevClient(transport=response_for).evaluate(run, a["event_id"])
        self.assertEqual(result["feedback_response"]["source"], "evidence_gate")
        self.assertEqual(result["feedback_response"]["status"], "unresolved")

    def test_media_feedback_is_not_claimed_as_fully_inspected(self):
        doc = harbor(); doc["steps"][1]["tool_calls"] = doc["steps"][1]["tool_calls"][:1]
        doc["steps"][1]["observation"]["results"] = [{"source_call_id": "a", "content": [{"type": "image", "path": "unread.png"}]}]
        run = normalize(doc)[0]; action = analyze(run)["actions"][-1]
        self.assertTrue(action["feedback_opportunity"])
        self.assertNotIn("feedback_response", packet(run, action["event_id"])["questions"])

    def test_first_action_status_is_deterministic_not_a_jev_inference(self):
        run = normalize(swe_rl())[0]; aid = analyze(run)["actions"][0]["event_id"]
        request = packet(run, aid)
        self.assertNotIn("feedback_response", request["questions"])
        result = JevClient(transport=response_for).evaluate(run, aid)
        self.assertEqual(result["feedback_response"]["status"], "not_applicable")
        self.assertEqual(result["feedback_response"]["probabilities"], {})

    def test_no_usable_text_skips_inference_and_does_not_invent_an_objective(self):
        doc = swe_rl(); doc["messages"] = doc["messages"][:3]; doc["n_steps"] = 1
        doc["messages"][1]["content"] = [{"type": "image", "path": "unread-task.png"}]
        doc["messages"][2]["content"] = ""
        doc["messages"][2]["extra"]["actions"][0]["command"] = ""
        run = normalize(doc)[0]; aid = analyze(run)["actions"][0]["event_id"]
        req = packet(run, aid)
        self.assertTrue(req["state"]["missingness"]["objective_missing"])
        self.assertEqual(req["questions"], {})
        def forbidden(request):
            self.fail("Unsupported measurements must not call inference")
        result = JevClient(transport=forbidden).evaluate(run, aid)
        self.assertEqual(result["_provenance"]["execution"], "evidence_gates_only")
        self.assertEqual(result["goal_relation"]["status"], "unresolved")

    def test_old_unsupported_decision_is_withheld_without_rewriting_original(self):
        doc = swe_rl(); doc["messages"][3]["content"] = ""
        run = normalize(doc)[0]; aid = analyze(run)["actions"][1]["event_id"]
        original = {aid: {"feedback_response": {"status": "decided", "value": "method_change"}}}
        before = copy.deepcopy(original)
        analysis = analyze(run, original)
        self.assertEqual(original, before)
        obs = analysis["actions"][1]["semantic"]["feedback_response"]
        self.assertEqual(obs["status"], "unresolved")
        self.assertEqual(obs["withheld_observation"]["value"], "method_change")

    def test_unknown_purpose_cannot_claim_no_check_or_closure(self):
        doc = swe_rl(); doc["messages"][2]["extra"]["actions"][0]["command"] = "unknown-command"
        run = normalize(doc)[0]; analysis = analyze(run)
        self.assertEqual(analysis["verification"]["actor_tails"][0]["status"], "unresolved")
        self.assertEqual(analysis["capabilities"]["measurements"]["verification_closure"]["status"], "limited")


if __name__ == "__main__":
    unittest.main()
