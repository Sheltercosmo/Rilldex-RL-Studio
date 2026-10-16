import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tracker.adapters import normalize
from tracker.jobs import Worker
from tracker.jev import JevClient
from tracker.schema import InputError
from tracker.store import Store
from test_tracker import harbor, response_for


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"jobs.sqlite")
        self.run = normalize(harbor())[0]; self.store.add([self.run])
        self.run_id = self.run["id"]

    def worker(self, **kwargs):
        worker = Worker(self.store, **kwargs)
        self.addCleanup(worker.close)
        return worker

    def row(self, job_id):
        with self.store.connect() as c:
            return dict(c.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone())

    def wait_for(self, predicate):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            value = predicate()
            if value: return value
            time.sleep(.01)
        self.fail("Timed out waiting for worker transition")

    def finished(self, job_id):
        return self.wait_for(lambda: self.row(job_id)["status"] not in {"queued","running"})

    def test_concurrent_submissions_are_idempotent_and_queue_bound_is_atomic(self):
        worker = self.worker(autostart=False,max_queued=2)
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _:worker.submit(self.run_id),range(16)))
        self.assertEqual(len(set(ids)),1)
        runs=[normalize(harbor(),meta={"seed":str(i)})[0] for i in range(8)]
        self.store.add(runs)
        def submit(run):
            try: return worker.submit(run["id"])
            except InputError: return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted=list(pool.map(submit,runs))
        self.assertEqual(sum(x is not None for x in accepted),1)
        self.assertEqual(len(worker.list()),2)

    def test_two_workers_claim_each_job_once(self):
        first = self.worker(autostart=False); second = self.worker(autostart=False)
        job_id=first.submit(self.run_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed=list(pool.map(lambda w:w._claim(),[first,second]))
        self.assertEqual(sum(row is not None for row in claimed),1)
        self.assertEqual(next(row for row in claimed if row)["id"],job_id)

    def test_heartbeat_keeps_inflight_request_owned_when_another_worker_starts(self):
        entered, release = threading.Event(), threading.Event()
        def transport(request):
            entered.set()
            if not release.wait(4): raise InputError("Test transport timed out")
            return response_for(request)
        worker=self.worker(client=JevClient(transport=transport),lease_seconds=.3)
        self.addCleanup(release.set)
        job_id=worker.submit(self.run_id); self.assertTrue(entered.wait(2))
        first_deadline=self.row(job_id)["lease_expires_at"]
        self.wait_for(lambda: time.time()>first_deadline and self.row(job_id)["lease_expires_at"]>first_deadline)
        self.worker(autostart=False)
        self.assertEqual(self.row(job_id)["status"],"running")
        self.assertEqual(self.row(job_id)["owner_id"],worker.owner)
        release.set(); self.finished(job_id)
        self.assertEqual(self.row(job_id)["status"],"complete")
        self.assertEqual(len(self.store.observations(self.run_id)),3)

    def test_expired_owner_cannot_commit_a_late_response(self):
        worker=self.worker(autostart=False)
        job_id=worker.submit(self.run_id); row=worker._claim()
        with self.store.connect() as c:
            c.execute("UPDATE jobs SET lease_expires_at=0 WHERE id=?",(job_id,))
        restarted=self.worker(autostart=False)
        self.assertEqual(self.row(job_id)["status"],"interrupted")
        action=self.store.get(self.run_id)["analysis"]["actions"][0]
        result=JevClient(transport=response_for).evaluate(self.run,action["event_id"])
        self.assertFalse(worker._record(row,action["event_id"],result,1))
        self.assertEqual(self.store.observations(self.run_id),{})
        self.assertNotEqual(restarted.submit(self.run_id),job_id)

    def test_shutdown_discards_inflight_result_and_marks_interrupted(self):
        entered, release=threading.Event(),threading.Event()
        def transport(request):
            entered.set(); release.wait(4); return response_for(request)
        worker=self.worker(client=JevClient(transport=transport))
        self.addCleanup(release.set)
        job_id=worker.submit(self.run_id); self.assertTrue(entered.wait(2))
        # close invalidates ownership before waiting for the network thread.
        closer=threading.Thread(target=worker.close); closer.start()
        self.wait_for(lambda:self.row(job_id)["status"]=="interrupted")
        release.set(); closer.join(3); worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())
        self.assertEqual(self.store.observations(self.run_id),{})
        self.assertEqual(self.row(job_id)["status"],"interrupted")

    def test_recovery_refreshes_results_saved_before_a_crash(self):
        worker=self.worker(autostart=False)
        job_id=worker.submit(self.run_id); row=worker._claim()
        action=self.store.get(self.run_id)["analysis"]["actions"][0]
        result=JevClient(transport=response_for).evaluate(self.run,action["event_id"])
        self.assertTrue(worker._record(row,action["event_id"],result,1))
        self.assertEqual(self.store.get(self.run_id)["analysis"]["semantic_coverage"],0)
        with self.store.connect() as c:
            c.execute("UPDATE jobs SET lease_expires_at=0 WHERE id=?",(job_id,))
        self.worker(autostart=False)
        self.assertEqual(self.row(job_id)["status"],"interrupted")
        self.assertEqual(self.row(job_id)["progress"],1)
        self.assertEqual(self.store.get(self.run_id)["analysis"]["semantic_coverage"],1)

    def test_failure_preserves_completed_observations_and_resubmit_skips_them(self):
        calls=[]
        def transport(request):
            calls.append(request["state"]["cutoff_event_id"])
            if len(calls)==2: raise InputError("Simulated provider failure")
            return response_for(request)
        worker=self.worker(client=JevClient(transport=transport))
        first=worker.submit(self.run_id); self.finished(first)
        self.assertEqual(self.row(first)["status"],"failed")
        self.assertEqual(self.row(first)["progress"],1)
        self.assertEqual(self.store.get(self.run_id)["analysis"]["semantic_coverage"],1)
        second=worker.submit(self.run_id); self.finished(second)
        self.assertEqual(self.row(second)["status"],"complete")
        self.assertEqual(self.row(second)["total"],2)
        self.assertEqual(calls.count(calls[0]),1)
        self.assertEqual(len(self.store.observations(self.run_id)),3)

    def test_partial_batch_and_restart_reuse_only_exact_cached_requests(self):
        calls=[]
        def transport(request):
            calls.append(request); return response_for(request)
        client=JevClient(transport=transport)
        action=self.store.get(self.run_id)["analysis"]["actions"][0]
        stale=client.evaluate(self.run,action["event_id"])
        stale["_provenance"]["packet_hash"]="old-request"
        self.store.record(self.run_id,action["event_id"],stale["_provenance"]["harness"],client.model,"old-request",stale)
        calls.clear()
        worker=self.worker(client=client,max_actions=1)
        first=worker.submit(self.run_id); self.finished(first)
        self.assertEqual(self.row(first)["status"],"partial")
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["state"]["cutoff_event_id"],action["event_id"])
        worker.close()
        restarted=self.worker(client=client,max_actions=2)
        second=restarted.submit(self.run_id); self.finished(second)
        self.assertEqual(self.row(second)["status"],"complete")
        self.assertEqual(len(calls),3)
        third=restarted.submit(self.run_id); self.finished(third)
        self.assertEqual(self.row(third)["total"],0)
        self.assertEqual(len(calls),3)

    def test_queued_work_survives_restart_and_requires_matching_profile(self):
        worker=self.worker(autostart=False)
        job_id=worker.submit(self.run_id); worker.close()
        different=self.worker(autostart=False,client=JevClient(model="jev-different-pinned-version"))
        self.assertIsNone(different._claim())
        self.assertEqual(self.row(job_id)["status"],"queued")
        restarted=self.worker(client=JevClient(transport=response_for))
        self.finished(job_id)
        self.assertEqual(self.row(job_id)["status"],"complete")

    def test_old_database_migration_retains_jobs_and_marks_unknown_ownership(self):
        old=Path(self.temp.name)/"old.sqlite"
        with sqlite3.connect(old) as c:
            c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,status TEXT,progress INTEGER DEFAULT 0,total INTEGER DEFAULT 0,error TEXT,created_at TEXT)")
            c.execute("INSERT INTO jobs(run_id,status,created_at) VALUES ('old','running','yesterday')")
            c.execute("INSERT INTO jobs(run_id,status,created_at) VALUES ('old-queued','queued','yesterday')")
        c.close()
        migrated=Store(old); worker=Worker(migrated,autostart=False); self.addCleanup(worker.close)
        self.assertEqual([r["status"] for r in worker.list()],["interrupted","interrupted"])
        self.assertTrue(all(r["error"] for r in worker.list()))


if __name__=="__main__": unittest.main()
