import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.jev import packet
from tracker.observe import analyze
from tracker.schema import InputError
from tracker.store import Store
from tracker.watch import DirectoryWatcher
from test_tracker import harbor

FIXTURES = Path(__file__).parent/"fixtures"/"harbor"


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"job"; self.root.mkdir()
        self.trial = self.root/"trial-a"; (self.trial/"agent").mkdir(parents=True)
        self.trace = self.trial/"agent"/"trajectory.json"
        self.store = Store(Path(self.temp.name)/"tracker.sqlite")
        self.watcher = DirectoryWatcher(self.store,self.root,producer="test-producer")

    def write(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data),encoding="utf-8")

    def test_restarts_and_result_only_updates_preserve_logical_identity(self):
        self.write(self.trace,harbor())
        self.write(self.trial/"config.json",{"task":{"path":"tasks/parser"},"agent":{"name":"test","env":{"TOKEN":"DO_NOT_COPY"}}})
        first = self.watcher.poll(); self.assertEqual(first["ingested"],1)
        run0 = self.store.list()[0]
        self.assertEqual(run0["ingestion"]["state"],"in_progress")
        restarted = DirectoryWatcher(Store(self.store.path),self.root,producer="test-producer")
        self.assertEqual(restarted.poll()["ingested"],0)
        self.write(self.trial/"result.json",{"task_name":"parser","finished_at":"2026-10-06T12:00:00Z",
            "verifier_result":{"rewards":{"reward":-2.5}},"agent_result":{"n_input_tokens":246810,"cost_usd":0.1}})
        final = restarted.poll(); self.assertEqual(final["ingested"],1)
        self.assertEqual(len(self.store.list()),1)
        bundle = self.store.get(self.store.list()[0]["id"],raw=True)
        self.assertEqual(bundle["ingestion"]["revision"],1)
        self.assertEqual(bundle["ingestion"]["state"],"complete")
        self.assertEqual(bundle["run"]["outcome"]["rewards"],{"reward":-2.5})
        self.assertNotIn("DO_NOT_COPY",json.dumps(bundle["run"]["sources"]))
        self.assertNotIn("verified_success",bundle["run"]["outcome"])
        request = packet(bundle["run"],bundle["analysis"]["actions"][0]["event_id"])
        self.assertNotIn("246810",json.dumps(request))
        self.assertNotIn("verifier_result",json.dumps(request))
        self.assertEqual(self.store.get(run0["id"],raw=True)["run"]["raw"],harbor())

    def test_partial_json_recovers_without_creating_bad_revision(self):
        self.trace.write_text('{"steps":',encoding="utf-8")
        self.assertEqual(self.watcher.poll()["deferred"],1)
        self.assertEqual(self.store.list(),[])
        self.write(self.trace,harbor())
        self.assertEqual(self.watcher.poll()["ingested"],1)
        self.assertEqual(self.store.list()[0]["ingestion"]["revision"],0)

    def test_missing_continuation_is_incomplete_then_stitched_without_copied_actions(self):
        source = json.loads((FIXTURES/"hello-world-context-summarization-linear-history.trajectory.json").read_text())
        continuation = json.loads((FIXTURES/"hello-world-context-summarization-linear-history.trajectory.cont-1.json").read_text())
        self.write(self.trace,source)
        self.write(self.trial/"result.json",{"task_name":"hello","finished_at":"2026-10-06T12:00:00Z"})
        report = self.watcher.poll(); self.assertEqual(report["ingested"],1,report)
        self.assertEqual(self.store.list()[0]["ingestion"]["state"],"in_progress")
        self.write(self.trace.parent/"trajectory.cont-1.json",continuation)
        report = self.watcher.poll(); self.assertEqual(report["ingested"],1,report)
        bundle = self.store.get(self.store.list()[0]["id"],raw=True)
        self.assertEqual(bundle["analysis"]["metrics"]["actions"],5)
        self.assertEqual(bundle["analysis"]["metrics"]["copied_context_events"],4)
        self.assertEqual(bundle["ingestion"]["state"],"complete")
        self.assertEqual(len(bundle["run"]["raw"]["documents"]),2)
        self.assertTrue(all(e["source_pointer"].startswith('/documents/') for e in bundle["run"]["events"]))
        self.assertEqual({a["trajectory_id"] for a in bundle["analysis"]["actions"]},{"main"})

    def test_swe_retry_wrapper_does_not_duplicate_attempt_files(self):
        def attempt(action):
            return {"history":[{"role":"user","content":"Fix parser"}],"trajectory":[{"action":action,"observation":"output","execution_time":.1}],"info":{"exit_status":"submitted"}}
        outer = self.root/"parser-1.traj"
        self.write(outer,{"attempts":[attempt("ls"),attempt("pwd")],**attempt("pwd")})
        self.write(self.root/"attempt_0"/outer.name,attempt("ls"))
        report=self.watcher.poll(); self.assertEqual(report["ingested"],2,report)
        self.assertEqual(len(self.store.list()),2)
        self.assertEqual({r["ingestion"]["rollout_id"] for r in self.store.list()}, {"attempt_0/parser-1.traj","attempt_1/parser-1.traj"})
        self.assertEqual(self.watcher.poll()["ingested"],0)

    def test_per_rollout_policy_metadata_overrides_defaults(self):
        self.write(self.trace,harbor())
        self.write(self.trial/"tracking.json",{"checkpoint":"policy-31","training_step":31,"task_id":"explicit-task"})
        watcher=DirectoryWatcher(self.store,self.root,producer="test",metadata={"checkpoint":"default","experiment":"e"})
        self.assertEqual(watcher.poll()["ingested"],1)
        m=self.store.list()[0]["metadata"]
        self.assertEqual((m["checkpoint"],m["training_step"],m["task_id"]),("policy-31",31,"explicit-task"))
        self.assertEqual(m["experiment"],"e")

    def test_reference_escape_is_rejected_without_reading_outside_root(self):
        doc=harbor();doc["continued_trajectory_ref"]="../../../outside.json"
        self.write(self.trace,doc)
        report=self.watcher.poll()
        self.assertEqual(report["deferred"],1)
        self.assertEqual(self.store.list(),[])

    def test_task_files_are_read_only_from_explicit_task_root(self):
        tasks=Path(self.temp.name)/"tasks"; task=tasks/"parser"; task.mkdir(parents=True)
        (task/"task.toml").write_text('[agent]\ntimeout_sec=60\n[environment]\nnetwork_mode="no-network"\n',encoding="utf-8")
        (task/"instruction.md").write_text('Fix the parser.',encoding="utf-8")
        self.write(self.trace,harbor());self.write(self.trial/"config.json",{"task":{"path":"parser"}})
        watcher=DirectoryWatcher(self.store,self.root,producer="p",task_root=tasks)
        report=watcher.poll();self.assertEqual(report["ingested"],1,report)
        bundle=self.store.get(self.store.list()[0]["id"])
        self.assertTrue(any(f["key"]=="agent.timeout_sec" and f["value"]==60 for f in bundle["run"]["environment_context"]["facts"]))


class FormatGuardTests(unittest.TestCase):
    def test_harbor_session_is_not_invented_task_identity(self):
        run=normalize(harbor())[0]
        self.assertIsNone(run["metadata"]["task_id"])
        self.assertEqual(run["metadata"]["session_id"],"task-one")

    def test_malformed_structures_raise_useful_input_errors(self):
        for key,value in [("steps",[None]),("agent",None),("extra",[]),("subagent_trajectories",[{}])]:
            with self.subTest(field=key):
                doc=harbor();doc[key]=value
                with self.assertRaises(InputError): normalize(doc)
        for key,value in [("tool_calls",{}),("observation",[]),("step_id",[]),("extra",[]),("reasoning_content",{})]:
            with self.subTest(step_field=key):
                doc=harbor();doc["steps"][0][key]=value
                with self.assertRaises(InputError): normalize(doc)

    def test_continuation_cycles_are_rejected(self):
        doc=harbor();doc["continued_trajectory_ref"]="trajectory.json"
        bundle={"tracker_bundle":"harbor/1","root":"trajectory.json","documents":[{"path":"trajectory.json","document":doc}]}
        with self.assertRaises(InputError): normalize(bundle)

    def test_swe_demo_instruction_is_not_actual_task(self):
        doc={"history":[{"role":"user","content":"Demo","is_demo":True},{"role":"user","content":"Actual task"}],"trajectory":[{"action":"ls","observation":"x"}],
             "replay_config":json.dumps({"agent":{"tools":{"execution_timeout":20},"model":{"api_key":"DO_NOT_COPY","name":"m"}}})}
        run=normalize(doc)[0]
        self.assertEqual(analyze(run)["goals"][0]["text"],"Actual task")
        self.assertNotIn("DO_NOT_COPY",json.dumps(run["sources"]))
        self.assertTrue(any(f["key"]=="agent.tools.execution_timeout" for f in run["environment_context"]["facts"]))


if __name__ == "__main__":
    unittest.main()
