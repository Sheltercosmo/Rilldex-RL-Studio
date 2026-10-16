"""Bounded, persistent observation jobs with transactional claims and leases."""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

from .jev import JEV_HARNESS, JevClient
from .schema import InputError, dumps


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Worker:
    def __init__(self, store, client=None, max_actions=100, *, max_queued=20,
                 lease_seconds=60, autostart=True, activity=False, relations=False, entities=False, references=False, occurrences=False, frames=False, complete_run=False):
        if not 1 <= max_actions <= 100 or not 1 <= max_queued <= 20 or lease_seconds <= 0:
            raise InputError("Observer limits must be 1–100 actions, 1–20 jobs and a positive lease")
        from .activity import ActivityClient, HARNESS as ACTIVITY_HARNESS, SEGMENTATION_VERSION
        from .unit_graph import RelationClient, HARNESS as RELATION_HARNESS
        from .entity_extraction import EntityClient, HARNESS as ENTITY_HARNESS
        from .reference_resolution import ReferenceClient, HARNESS as REFERENCE_HARNESS
        from .entity_occurrences import OccurrenceClient, HARNESS as OCCURRENCE_HARNESS
        if sum((activity,relations,entities,references,occurrences,frames)) > 1:
            raise InputError('Choose one observation harness per worker')
        self.activity = activity
        self.relations, self.entities, self.complete_run = relations, entities, complete_run
        self.references = references
        self.occurrences = occurrences
        self.frames = frames
        self.harness = REFERENCE_HARNESS if references else ENTITY_HARNESS if entities else RELATION_HARNESS if relations else ACTIVITY_HARNESS if activity else JEV_HARNESS
        self.result_table = 'reference_observations' if references else 'entity_observations' if entities else 'relation_observations' if relations else "activity_observations" if activity else "observations"
        self.store, self.client = store, client or (ReferenceClient() if references else EntityClient() if entities else RelationClient() if relations else ActivityClient() if activity else JevClient())
        if occurrences:
            self.harness=OCCURRENCE_HARNESS;self.result_table='occurrence_observations';self.client=client or OccurrenceClient()
        if frames:
            from .local_frames import FrameClient, HARNESS as FRAME_HARNESS
            self.harness=FRAME_HARNESS;self.result_table='frame_observations';self.client=client or FrameClient()
        self.max_actions, self.max_queued, self.lease_seconds = max_actions, max_queued, lease_seconds
        self.owner = uuid.uuid4().hex
        profile = {"model":self.client.model,"harness":self.harness,"selection_policy":self.client.selection_policy}
        if activity: profile["segmentation_version"] = SEGMENTATION_VERSION
        if complete_run: profile['completion'] = 'entire_run'
        self.profile = dumps(profile)
        self.stop, self.wake = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="jev-observer")
        self.last_error = None
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            recovered = self._recover(c)
        self._refresh_recovered(recovered)
        if autostart:
            self.thread.start()

    def _recover(self, c):
        # Another process's live jobs remain its property. Expired jobs require
        # resubmission: an in-flight remote request may already have been charged.
        now = time.time()
        run_ids = [r[0] for r in c.execute("""SELECT DISTINCT jobs.run_id FROM jobs JOIN runs ON runs.id=jobs.run_id
                    WHERE status='running' AND (lease_expires_at IS NULL OR lease_expires_at<=?)""",(now,))]
        c.execute("""UPDATE jobs SET status='interrupted', owner_id=NULL, lease_expires_at=NULL,
                     finished_at=?, error='Observer lease expired; resubmit to resume saved observations'
                     WHERE status='running' AND (lease_expires_at IS NULL OR lease_expires_at<=?)""",
                  (timestamp(), now))
        c.execute("""UPDATE jobs SET status='interrupted', finished_at=?,
                     error='Legacy queued job has no pinned inspector profile; resubmit'
                     WHERE status='queued' AND inspector_profile IS NULL""", (timestamp(),))
        return run_ids

    def _refresh_recovered(self, run_ids):
        # A crash can happen after a result commit and before the derived view
        # was refreshed. Recovery must expose those saved results in the UI.
        for run_id in run_ids:
            self.store.refresh(run_id)

    def submit(self, run_id):
        self.store.get(run_id)
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            recovered = self._recover(c)
            row = c.execute("SELECT id,inspector_profile FROM jobs WHERE run_id=? AND status IN ('queued','running')", (run_id,)).fetchone()
            if row:
                if row["inspector_profile"] != self.profile:
                    raise InputError("Another observer profile has an active job for this run; finish it before starting this harness")
                job_id = row[0]
            else:
                if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= self.max_queued:
                    raise InputError("Observer queue is full; finish queued work before adding more")
                cur = c.execute("INSERT INTO jobs(run_id,status,created_at,inspector_profile) VALUES (?,?,?,?)", (run_id, "queued", timestamp(), self.profile))
                job_id = cur.lastrowid
        self._refresh_recovered(recovered)
        self.wake.set()
        return job_id

    def list(self):
        with self.store.connect() as c:
            return [dict(x) for x in c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100")]

    def _claim(self):
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            recovered = self._recover(c)
            row = c.execute("SELECT * FROM jobs WHERE status='queued' AND inspector_profile=? ORDER BY id LIMIT 1", (self.profile,)).fetchone()
            if row:
                now = time.time()
                c.execute("""UPDATE jobs SET status='running',owner_id=?,lease_expires_at=?,heartbeat_at=?,started_at=?
                             WHERE id=? AND status='queued'""", (self.owner,now+self.lease_seconds,now,timestamp(),row["id"]))
        self._refresh_recovered(recovered)
        return dict(row) if row else None

    def _owned_update(self, job_id, assignments, values):
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            updated = c.execute(f"UPDATE jobs SET {assignments} WHERE id=? AND status='running' AND owner_id=? AND lease_expires_at>?",
                                (*values,job_id,self.owner,time.time()))
            return updated.rowcount == 1

    def _heartbeat(self, job_id, done, lost):
        while not done.wait(self.lease_seconds / 3):
            if self.stop.is_set():
                return
            try:
                now = time.time()
                if not self._owned_update(job_id,"lease_expires_at=?,heartbeat_at=?",(now+self.lease_seconds,now)):
                    lost.set(); return
            except sqlite3.Error:
                lost.set(); return

    def _record(self, row, event_id, result, progress):
        p = result["_provenance"]
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            owned = c.execute("SELECT 1 FROM jobs WHERE id=? AND status='running' AND owner_id=? AND lease_expires_at>?",
                              (row["id"],self.owner,time.time())).fetchone()
            if not owned or self.stop.is_set():
                return False
            c.execute(f"INSERT OR IGNORE INTO {self.result_table} VALUES (?,?,?,?,?,?,?)",
                      (row["run_id"],event_id,self.harness,p["model"],p["packet_hash"],dumps(result),timestamp()))
            if self.entities and p.get('completion')=='complete':
                import json
                key=(row['run_id'],event_id,self.harness,p['model'],p['packet_hash'])
                previous=json.loads(c.execute('SELECT result FROM entity_observations WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',key).fetchone()[0])
                if (previous['_provenance'].get('completion')=='awaiting_span' and previous['_availability']==result['_availability']
                    and previous['_request']==result['_request'] and previous['_span_request']==result['_span_request']):
                    c.execute('UPDATE entity_observations SET result=?,created_at=? WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',(dumps(result),timestamp(),*key))
            if self.references and p.get('completion')=='complete':
                import json
                key=(row['run_id'],event_id,self.harness,p['model'],p['packet_hash'])
                previous=json.loads(c.execute('SELECT result FROM reference_observations WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',key).fetchone()[0])
                if (previous['_provenance'].get('completion')=='awaiting_relationship' and previous['_target_choices']==result['_target_choices']
                    and previous['_request']==result['_request'] and previous['_relation_request']==result['_relation_request']):
                    c.execute('UPDATE reference_observations SET result=?,created_at=? WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',(dumps(result),timestamp(),*key))
            if self.occurrences and p.get('completion')=='complete':
                import json
                key=(row['run_id'],event_id,self.harness,p['model'],p['packet_hash'])
                previous=json.loads(c.execute('SELECT result FROM occurrence_observations WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',key).fetchone()[0])
                if (previous['_provenance'].get('completion')=='awaiting_boundary' and previous['_membership']==result['_membership']
                    and previous['_request']==result['_request'] and previous['_boundary_request']==result['_boundary_request']):
                    c.execute('UPDATE occurrence_observations SET result=?,created_at=? WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',(dumps(result),timestamp(),*key))
            if self.frames:
                import json
                from .local_frames import is_extension
                key=(row['run_id'],event_id,self.harness,p['model'],p['packet_hash'])
                previous=json.loads(c.execute('SELECT result FROM frame_observations WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',key).fetchone()[0])
                if is_extension(previous,result):
                    c.execute('UPDATE frame_observations SET result=?,created_at=? WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?',(dumps(result),timestamp(),*key))
            c.execute("UPDATE jobs SET progress=? WHERE id=?", (progress,row["id"]))
        return True

    def _process(self, row):
        done, lost = threading.Event(), threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat,args=(row["id"],done,lost),daemon=True,name="jev-job-lease")
        heartbeat.start()
        status, error = "complete", None
        try:
            bundle = self.store.get(row["run_id"], raw=True)
            cached = self.store.activity_observations(row["run_id"]) if self.activity else self.store.observations(row["run_id"])
            if self.relations or self.entities or self.references or self.occurrences or self.frames:
                with self.store.connect() as c:
                    import json
                    cached = {r['event_id']:json.loads(r['result']) for r in c.execute(f'SELECT event_id,result FROM {self.result_table} WHERE run_id=? ORDER BY created_at',(row['run_id'],))}
            subjects = [{"event_id":u["id"]} for u in bundle["activity"]["units"] if u["eligible"]] if self.activity or self.relations or self.entities else bundle["analysis"]["actions"]
            if self.entities:
                self.client.activity = bundle['activity']
                subjects = [{'event_id':u['id']} for u in bundle['unit_graph']['nodes'] if u['entity_extraction']['routes']]
            if self.references:
                from .reference_resolution import subjects as reference_subjects
                self.client.nodes = bundle['unit_graph']['nodes']
                subjects = [{'event_id':u['id']} for u in self.client.nodes if reference_subjects(u)]
            if self.occurrences:
                from .entity_occurrences import eligible_fields
                self.client.nodes=bundle['unit_graph']['nodes']
                subjects=[{'event_id':u['id']} for u in self.client.nodes if eligible_fields(u)]
            if self.frames:
                from .local_frames import sources as frame_sources
                self.client.nodes=bundle['unit_graph']['nodes']
                subjects=[{'event_id':u['id']} for u in self.client.nodes if frame_sources(bundle['run'],u)]
            pending = [a for a in subjects if not self.client.cache_matches(cached.get(a["event_id"],{}),bundle["run"],a["event_id"])]
            batch = pending if self.complete_run else pending[:self.max_actions]
            if not self._owned_update(row["id"],"total=?",(len(batch),)):
                return
            for i, action in enumerate(batch):
                if self.stop.is_set() or lost.is_set():
                    raise InputError("Observer interrupted; resubmit to resume saved observations")
                if self.entities:
                    result = self.client.evaluate(bundle['run'],action['event_id'],resume=cached.get(action['event_id']),
                                                  checkpoint=lambda saved: self._record(row,action['event_id'],saved,i))
                elif self.references or self.occurrences or self.frames:
                    result=self.client.evaluate(bundle['run'],action['event_id'],resume=cached.get(action['event_id']),
                                                checkpoint=lambda saved:self._record(row,action['event_id'],saved,i))
                else:
                    result = self.client.evaluate(bundle["run"],action["event_id"])
                if lost.is_set() or not self._record(row,action["event_id"],result,i+1):
                    status, error = "interrupted", "Observer ownership lost; resubmit to resume saved observations"
                    return
            status = "partial" if len(pending)>len(batch) else "complete"
        except Exception as exc:
            status = "interrupted" if self.stop.is_set() or lost.is_set() else "failed"
            error = str(exc) if isinstance(exc,InputError) else type(exc).__name__
        finally:
            try:
                self.store.refresh(row["run_id"])
            except Exception as exc:
                status, error = "failed", "Could not refresh saved observations: " + type(exc).__name__
            try:
                self._owned_update(row["id"],"status=?,error=?,finished_at=?,owner_id=NULL,lease_expires_at=NULL",(status,error,timestamp()))
            finally:
                done.set(); heartbeat.join(timeout=2)

    def run(self):
        while not self.stop.is_set():
            try:
                row = self._claim()
                if row:
                    self._process(row)
                    self.last_error = None
                    continue
            except Exception as exc:
                # Storage failures must not silently kill the queue thread.
                self.last_error = type(exc).__name__
            self.wake.wait(1); self.wake.clear()

    def close(self):
        self.stop.set(); self.wake.set()
        with self.store.connect() as c:
            c.execute("""UPDATE jobs SET status='interrupted',error='Observer stopped; resubmit to resume saved observations',
                         finished_at=?,owner_id=NULL,lease_expires_at=NULL WHERE status='running' AND owner_id=?""",(timestamp(),self.owner))
        if self.thread.is_alive():
            self.thread.join(timeout=2)
