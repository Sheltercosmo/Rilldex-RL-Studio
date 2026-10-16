import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tracker.compare import compare
from tracker.jev import JevClient
from tracker.store import Store, ReviewConflict
from test_tracker import harbor, response_for


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"test.sqlite")

    def payload(self, revision=0, **extra):
        return {"producer":"harbor-fixture", "rollout_id":"trial-1", "revision":revision,
                "state":"in_progress", "document":harbor(), "metadata":{"task_id":"task-one", "experiment":"exp", "checkpoint":"c0",
                  "environment_version":"fixture-v1", "split":"eval"}, **extra}

    def test_revisions_are_idempotent_and_expose_only_latest_snapshot(self):
        first = self.store.ingest(self.payload())
        self.assertFalse(self.store.ingest(self.payload())["imported"])
        document = harbor(); document["steps"][-1]["message"] = "Updated expression."
        final = self.store.ingest(self.payload(1, document=document, state="complete"))
        self.assertEqual([r["id"] for r in self.store.list()], [final["id"]])
        self.assertFalse(self.store.get(first["id"])["ingestion"]["is_latest"])
        self.assertEqual(self.store.get(first["id"],raw=True)["run"]["raw"], harbor())
        self.assertEqual(len(Store(self.store.path).get(final["id"])["ingestion"]["history"]), 2)
        # A retry of an earlier revision must not make it current again.
        self.store.ingest(self.payload())
        self.assertEqual(self.store.list()[0]["id"], final["id"])

    def test_conflicting_or_skipped_revisions_do_not_leave_orphan_runs(self):
        self.store.ingest(self.payload())
        changed = harbor(); changed["steps"][-1]["message"] = "Different payload."
        with self.assertRaises(ReviewConflict): self.store.ingest(self.payload(document=changed))
        with self.assertRaises(ReviewConflict): self.store.ingest(self.payload(3, document=changed))
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM runs").fetchone()[0],1)

    def test_identical_content_in_distinct_logical_rollouts_counts_separately(self):
        first = self.store.ingest(self.payload())
        second = self.store.ingest(self.payload(rollout_id="trial-2"))
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list()),2)

    def test_cache_reuse_requires_identical_prefix_packet(self):
        first = self.store.ingest(self.payload())
        bundle = self.store.get(first["id"],raw=True)
        for action in bundle["analysis"]["actions"]:
            result = JevClient(transport=response_for).evaluate(bundle["run"],action["event_id"])
            p=result["_provenance"]
            self.store.record(first["id"],action["event_id"],p["harness"],p["model"],p["packet_hash"],result)
        document = harbor()
        last = copy.deepcopy(document["steps"][-1]); last["step_id"]=4
        last["tool_calls"][0]["tool_call_id"]="d"; last["observation"]["results"][0]["source_call_id"]="d"
        document["steps"].append(last)
        second = self.store.ingest(self.payload(1,document=document))
        self.assertEqual(second["reused_observations"],3)
        self.assertEqual(self.store.get(second["id"])["analysis"]["semantic_coverage"],3)
        document["steps"][0]["message"]="Different task objective."
        third = self.store.ingest(self.payload(2,document=document,state="complete"))
        self.assertEqual(third["reused_observations"],0)
        self.assertEqual(self.store.get(third["id"])["analysis"]["semantic_coverage"],0)

    def test_incomplete_rollout_is_visible_but_excluded_from_comparison(self):
        first = self.store.ingest(self.payload())
        rows = self.store.list()
        self.assertEqual(len(rows),1)
        result = compare(rows)
        self.assertEqual(result["excluded"][0]["reason"], "Superseded or incomplete producer snapshot")
        final = self.store.ingest(self.payload(1,state="complete"))
        self.assertEqual(first["id"], final["id"])
        self.assertEqual(self.store.list()[0]["ingestion"]["state"], "complete")
        self.assertEqual(compare(self.store.list())["excluded"], [])

    def test_concurrent_conflict_is_atomic(self):
        def ingest(text):
            document=harbor(); document["steps"][0]["message"]=text
            try: return self.store.ingest(self.payload(document=document))
            except ReviewConflict: return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(ingest,["First input", "Second input"]))
        self.assertEqual(results.count("conflict"),1)
        self.assertEqual(len(self.store.list()),1)


if __name__ == "__main__":
    unittest.main()
