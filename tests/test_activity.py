import copy
import tempfile
import time
import unittest
from pathlib import Path

from tracker.activity import ACTIVITIES, HARNESS, ActivityClient, analyze, packet, segments, units
from tracker.adapters import normalize
from tracker.jobs import Worker
from tracker.schema import InputError
from tracker.store import Store


def reasoning_run():
    return normalize({"schema_version": "ATIF-v1.7", "agent": {"name": "example"}, "steps": [
        {"step_id": 1, "source": "user", "message": "Find the integer solutions and explain the result."},
        {"step_id": 2, "source": "agent", "message": "I will factor the expression. Perhaps both roots are positive.\nThe product is negative, so the roots have opposite signs."},
        {"step_id": 3, "source": "agent", "message": "I retract the assumption that both roots are positive.", "reasoning_content": "Substitution checks both candidates."},
        {"step_id": 4, "source": "agent", "message": "The two solutions are -2 and 3."}
    ]})[0]


def response(request, choices=None):
    """Synthetic transport fixture; never used as semantic reference truth."""
    choices = choices or {}
    answers = {}
    for key, question in request["questions"].items():
        choice = choices.get(key, "asserted" if key == "expression" else "not_applicable" if key == "revision_target" else "absent")
        answers[key] = {"type": "choice", "choice": choice, "probabilities": {k: float(k == choice) for k in question["criteria"]}, "confidence": 1.0}
    return {"model": request["model"], "answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}


class ActivityTests(unittest.TestCase):
    def test_lossless_codepoint_spans_protect_code_quotes_and_unclosed_fences(self):
        for text in ["🧭 First. Second! Third?\n\n> Quoted. Not ours.\n```py\nx = 'A. B'\n```\nEnd.",
                     "start\n~~~~python\nx=1\n", "", "  \n", "2.5 is a number. Next."]:
            spans = list(segments(text))
            self.assertEqual("".join(text[a:b] for a,b,_ in spans), text)
            self.assertEqual([b for _,b,_ in spans][:-1], [a for a,_,_ in spans][1:])
            if "```" in text:
                code = [text[a:b] for a,b,k in spans if k == "code_or_payload"]
                self.assertEqual(len(code), 1); self.assertIn("A. B", code[0])
                self.assertEqual(len([s for s in spans if s[2] == "quoted"]), 1)

    def test_reasoning_only_work_has_units_without_tool_calls(self):
        run = reasoning_run(); observed = analyze(run)
        self.assertEqual(observed["coverage"]["action_dispatch"]["eligible_units"], 0)
        self.assertEqual(observed["coverage"]["model_span"]["eligible_units"], 6)
        self.assertTrue(any(u["text"] == "Substitution checks both candidates." for u in observed["units"]))
        self.assertEqual(observed["coverage"]["model_span"]["processed_units"], 0)
        self.assertTrue(all(not u["activities"] for u in observed["units"]))

    def test_prefix_excludes_later_sentence_future_results_and_other_agents(self):
        run = reasoning_run(); subject = units(run)[0]
        run["outcome"]["secret_final_reward"] = "FUTURE_REWARD_MARKER"
        state = packet(run, subject["id"])["state"]
        self.assertEqual(state["subject"]["text"], "I will factor the expression. ")
        self.assertNotIn("Perhaps", str(state)); self.assertNotIn("FUTURE_REWARD", str(state))
        changed = copy.deepcopy(run)
        changed["events"].append({"id":"foreign","index":0,"kind":"feedback","trajectory_id":"other","text":"OTHER_AGENT_SECRET","source_pointer":"/other"})
        self.assertNotIn("OTHER_AGENT", str(packet(changed,subject["id"])))

    def test_multiple_memberships_and_expression_are_independent(self):
        run = reasoning_run(); unit = units(run)[1]
        client = ActivityClient(transport=lambda r: response(r,{"reason":"present","hypothesize":"present","expression":"hypothetical"}))
        result = client.evaluate(run,unit["id"])
        tagged = next(u for u in analyze(run,{unit["id"]:result})["units"] if u["id"] == unit["id"])
        self.assertEqual(tagged["activities"], ["reason","hypothesize"])
        self.assertEqual(tagged["expression"]["value"], "hypothetical")
        self.assertEqual(tagged["status"], "decided")

    def test_revision_requires_valid_earlier_candidate_link(self):
        run = reasoning_run(); unit = next(u for u in units(run) if "retract" in u["text"])
        no_link = ActivityClient(transport=lambda r: response(r,{"revise":"present","revision_target":"no_suitable_candidate"})).evaluate(run,unit["id"])
        tagged = next(u for u in analyze(run,{unit["id"]:no_link})["units"] if u["id"] == unit["id"])
        self.assertNotIn("revise",tagged["activities"]); self.assertIn("revise",tagged["unresolved_activities"])
        target = units(run)[1]["id"]
        linked = ActivityClient(transport=lambda r: response(r,{"revise":"present","revision_target":target})).evaluate(run,unit["id"])
        tagged = next(u for u in analyze(run,{unit["id"]:linked})["units"] if u["id"] == unit["id"])
        self.assertIn("revise",tagged["activities"]); self.assertEqual(tagged["revision_target"],target)

    def test_changed_prefix_invalidates_cache_but_preserves_original(self):
        run=reasoning_run();unit=units(run)[1];client=ActivityClient(transport=response);result=client.evaluate(run,unit["id"])
        changed=copy.deepcopy(run);changed["events"][0]["text"]="Changed task"
        self.assertFalse(client.cache_matches(result,changed,unit["id"]))
        tagged=next(u for u in analyze(changed,{unit["id"]:result})["units"] if u["id"]==unit["id"])
        self.assertEqual(tagged["status"],"stale");self.assertEqual(tagged["observation"],result)
        self.assertEqual(tagged["activities"],[])

    def test_truncation_abstains_and_invalid_distributions_fail(self):
        run=reasoning_run();run["events"][1]["text"]="x"*5001;unit=units(run)[0]
        result=ActivityClient(transport=lambda r:response(r,{"plan":"present"})).evaluate(run,unit["id"])
        self.assertEqual(result["plan"]["status"],"unresolved")
        def bad(request):
            out=response(request);out["answers"]["plan"]["probabilities"]["present"]=float('nan');return out
        with self.assertRaises(InputError):ActivityClient(transport=bad).evaluate(run,unit["id"])

    def test_clipped_background_does_not_erase_complete_subject_decisions(self):
        run=reasoning_run();run["events"][0]["text"]="x"*5001;unit=units(run)[0]
        request=packet(run,unit["id"])
        self.assertTrue(request["state"]["missingness"]["truncated_event_ids"])
        self.assertEqual(request["state"]["missingness"]["required_truncated_event_ids"],[])
        result=ActivityClient(transport=lambda r:response(r,{"plan":"present"})).evaluate(run,unit["id"])
        self.assertEqual(result["plan"]["status"],"decided")
        self.assertEqual(result["plan"]["selection_policy"], "argmax/1")

    def test_initial_visible_instruction_survives_followup_messages(self):
        run=reasoning_run()
        for i in (1,2,3): run["events"].insert(i,{"id":f"user{i}","index":i-.5,"kind":"instruction","actor":"user","trajectory_id":"main","text":f"Follow-up {i}","source_pointer":f"/followup/{i}"})
        unit=units(run)[-1]
        instructions=packet(run,unit["id"])["state"]["authorized_instructions"]
        self.assertEqual(instructions[0]["id"],run["events"][0]["id"])
        self.assertEqual(len(instructions),3)

    def test_nonprogramming_tool_types_do_not_become_coding_purposes(self):
        run=normalize({"schema_version":"ATIF-v1.7","agent":{"name":"booking"},"steps":[
            {"step_id":1,"source":"user","message":"Find a refundable fare."},
            {"step_id":2,"source":"agent","message":"I will search available fares.","tool_calls":[{"tool_call_id":"x","function_name":"find_fares","arguments":{"refundable":True}}],"observation":{"results":[{"source_call_id":"x","content":"No available fares."}]}}
        ]})[0]
        observed=analyze(run);action=next(u for u in observed["units"] if u["kind"]=="action_dispatch")
        self.assertEqual(action["action_type"]["value"],"unmapped_tool")
        self.assertEqual(action["expression"]["value"],"recorded_dispatch")
        self.assertEqual(action["activities"],[])
        self.assertNotIn("No available fares",str(packet(run,action["id"])))

    def test_activity_worker_persists_separately_and_resumes_exact_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/"test.sqlite");run=reasoning_run();store.add([run])
            worker=Worker(store,client=ActivityClient(transport=response),max_actions=2,activity=True,autostart=False)
            try:
                job=worker.submit(run["id"]);worker._process(worker._claim())
                self.assertEqual(store.observations(run["id"]),{})
                self.assertEqual(len(store.activity_observations(run["id"])),2)
                self.assertEqual(store.get(run["id"])["activity"]["coverage"]["model_span"]["processed_units"],2)
                worker.submit(run["id"]);worker._process(worker._claim())
                self.assertEqual(len(store.activity_observations(run["id"])),4)
                self.assertEqual(len(store.get(run["id"],raw=True)["activity_observation_history"]),4)
                self.assertTrue(all(v["_provenance"]["harness"]==HARNESS for v in store.activity_observations(run["id"]).values()))
            finally:worker.close()

    def test_source_linked_payload_is_preserved_but_not_counted_twice(self):
        text = "I will check.\n```bash\n  pytest\n```\nThen report."
        run = normalize({"trajectory":[{"role":"user","text":"Check the tests."},{"role":"assistant","text":text}]},"nebius")[0]
        observed = analyze(run)
        payload = next(u for u in observed["units"] if u["kind"] == "action_payload")
        self.assertFalse(payload["eligible"])
        self.assertEqual(payload["status"],"excluded")
        action = next(u for u in observed["units"] if u["kind"] == "action_dispatch")
        self.assertEqual(payload["represented_by"],[action["event_id"]])
        self.assertEqual(observed["coverage"]["model_span"]["eligible_units"],2)
        parent = next(e for e in run["events"] if e["kind"] == "message")
        self.assertEqual("".join(u["text"] for u in observed["units"] if u["event_id"] == parent["id"]),text)
        self.assertNotIn(payload["id"],str(packet(run,action["id"])))
        with self.assertRaises(InputError):packet(run,payload["id"])
        # Equal content in a different source field is not a source-span link.
        changed = copy.deepcopy(run)
        next(e for e in changed["events"] if e["kind"]=="action")["source_pointer"] = "/another/action"
        self.assertEqual(analyze(changed)["represented_payload_units"],0)
        changed = copy.deepcopy(run)
        next(e for e in changed["events"] if e["kind"]=="action")["span"]["end"] = len(text)+1
        self.assertEqual(analyze(changed)["represented_payload_units"],0)

    def test_standalone_code_remains_model_authored_content(self):
        run = reasoning_run();run["events"][1]["text"] = "```python\nprint(42)\n```"
        observed = analyze(run)
        code = next(u for u in observed["units"] if u["syntax"]=="code_or_payload")
        self.assertEqual(code["kind"],"model_span");self.assertTrue(code["eligible"])
        self.assertEqual(observed["represented_payload_units"],0)


if __name__ == "__main__":unittest.main()
