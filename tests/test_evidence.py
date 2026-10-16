import copy
import unittest

from tracker.adapters import normalize
from tracker.compare import compare
from tracker.observe import analyze
from test_comparison import row


def swe(steps, info=None):
    return normalize({"history":[{"role":"user","content":"Fix parser."}],"trajectory":steps,"info":info or {}},"swe-agent")[0]


class VerificationTests(unittest.TestCase):
    def test_reported_pytest_summary_has_source_span_without_task_success_claim(self):
        run=swe([{"action":"pytest tests/test_parser.py","observation":"collecting...\n================= 4 passed, 1 skipped in 0.52s =================\n"}])
        v=analyze(run)["verification"]
        check=v["checks"][0]; report=check["reported_summary"]
        self.assertEqual(report["counts"],{"passed":4,"skipped":1})
        source=next(e for e in run["events"] if e["id"]==report["event_id"])
        self.assertEqual(source["text"][report["span"]["start"]:report["span"]["end"]],report["text"])
        self.assertEqual(check["artifact_version"],"unrecorded")
        self.assertIsNone(v["outcome"]["dataset_verified_success"])

    def test_echoed_or_ambiguous_summaries_do_not_become_test_verdicts(self):
        run=swe([{"action":"echo '4 passed in 1s'","observation":"4 passed in 1s"}])
        aid=analyze(run)["actions"][0]["event_id"]
        v=analyze(run,{aid:{"mode":{"value":"verify","status":"decided"}}})["verification"]
        self.assertIsNone(v["checks"][0]["reported_summary"])
        run=swe([{"action":"pytest","observation":"1 passed in 1s\n2 passed in 2s"}])
        self.assertIsNone(analyze(run)["verification"]["checks"][0]["reported_summary"])

    def test_application_after_check_is_sequence_evidence_not_freshness(self):
        run=swe([{"action":"pytest","observation":"1 passed in 1s"},{"action":"edit 1:1\nchange\nend_of_edit","observation":"edited"}])
        v=analyze(run)["verification"]
        self.assertEqual(v["actor_tails"][0]["status"],"application_after_check")
        self.assertEqual(len(v["actor_tails"][0]["application_after_check"]),1)
        self.assertNotIn("premature_stopping",v)

    def test_unknown_execution_durations_are_not_zero(self):
        run=swe([{"action":"ls","observation":"x","execution_time":0.0},{"action":"pwd","observation":"x"},{"action":"cat a","observation":"x","execution_time":True}])
        r=analyze(run)["verification"]["resources"]["execution"]
        self.assertEqual(r["seconds"],0.0)
        self.assertEqual(r["recorded_actions"],1)
        self.assertEqual(r["eligible_actions"],3)
        self.assertFalse(r["complete"])

    def test_input_and_cache_tokens_are_not_added_together(self):
        run=swe([{"action":"ls","observation":"x"}],{"model_stats":{"tokens_sent":100,"tokens_received":20,"instance_cost":0.01},"exit_status":"submitted"})
        v=analyze(run)["verification"]
        self.assertEqual(v["resources"]["reports"][0]["values"]["input_tokens"]["value"],100)
        self.assertIsNone(v["outcome"]["dataset_verified_success"])
        self.assertEqual(v["outcome"]["termination"],"submitted")

    def test_context_changes_block_same_named_task_comparison(self):
        rows=[row("t","c0",10),row("t","c1",30)]
        rows[0]["environment_context_hash"]="before"
        rows[1]["environment_context_hash"]="after"
        self.assertEqual(compare(rows)["status"],"task_context_changed")
        del rows[0]["environment_context_hash"];del rows[1]["environment_context_hash"]
        rows[0]["metadata"]["task_revision"]="task-v1"
        rows[1]["metadata"]["task_revision"]="task-v2"
        self.assertEqual(compare(rows)["status"],"task_context_changed")


if __name__ == "__main__":
    unittest.main()
