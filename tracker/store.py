"""SQLite persistence. Raw run snapshots are immutable; repeated imports are idempotent."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .observe import analyze, HARNESS_VERSION
from .schema import dumps, digest
from .schema import InputError
from . import reviews as review_logic


class ReviewConflict(InputError):
    pass


class ReadSnapshot:
    """Read-only connection facade; nested helpers never end the transaction."""
    def __init__(self, path, connection):
        self.path, self.connection = path, connection

    @contextmanager
    def connect(self):
        yield self.connection

    @contextmanager
    def read_snapshot(self):
        yield self


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, imported_at TEXT NOT NULL,
                    document TEXT NOT NULL, analysis TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS semantic_observers (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operation_observations (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    protocol_id TEXT NOT NULL, source_hash TEXT NOT NULL,
                    protocol TEXT NOT NULL, result TEXT NOT NULL,
                    workspace TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operation_observation_run ON operation_observations(run_id,protocol_id);
                CREATE TABLE IF NOT EXISTS observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS activity_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS relation_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS entity_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS reference_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS occurrence_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS frame_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS move_observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                    harness TEXT NOT NULL, model TEXT NOT NULL, packet_hash TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,event_id,harness,model,packet_hash)
                );
                CREATE TABLE IF NOT EXISTS activity_component_collections (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_component_records (
                    id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES activity_component_collections(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), unit_id TEXT NOT NULL, document TEXT NOT NULL,
                    UNIQUE(collection_id,run_id,unit_id,id)
                );
                CREATE INDEX IF NOT EXISTS activity_component_run ON activity_component_records(run_id,unit_id);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
                    status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS review_run ON reviews(run_id, id);
                CREATE TABLE IF NOT EXISTS rollout_revisions (
                    producer TEXT NOT NULL, rollout_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id),
                    state TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(producer,rollout_id,revision)
                );
                CREATE INDEX IF NOT EXISTS revision_run ON rollout_revisions(run_id);
                CREATE TABLE IF NOT EXISTS diagnostic_workers (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS diagnostic_attempts (
                    id TEXT PRIMARY KEY, worker_id TEXT NOT NULL REFERENCES diagnostic_workers(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), source_hash TEXT NOT NULL,
                    document TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS diagnostic_attempt_worker ON diagnostic_attempts(worker_id,run_id,created_at);
                CREATE TABLE IF NOT EXISTS rollout_measurements (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    observer TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS rollout_measurement_latest ON rollout_measurements(run_id,observer,created_at);
                CREATE TABLE IF NOT EXISTS source_studies (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS study_episodes (
                    study_id TEXT NOT NULL REFERENCES source_studies(id), id TEXT NOT NULL,
                    document TEXT NOT NULL, PRIMARY KEY(study_id,id)
                );
                CREATE TABLE IF NOT EXISTS source_investigations (
                    id TEXT PRIMARY KEY, study_id TEXT NOT NULL,
                    document TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            from .graph_store import initialize as initialize_graphs
            initialize_graphs(c)
            from .monitoring import initialize as initialize_monitors
            initialize_monitors(c)
            from .connections import initialize as initialize_connections
            initialize_connections(c)
            from .producer_health import initialize as initialize_producers
            initialize_producers(c)
            from .strategy_profiles import initialize as initialize_profiles
            initialize_profiles(c)
            from .behavior_distributions import initialize as initialize_distributions
            initialize_distributions(c)
            from .failure_investigations import initialize as initialize_investigations
            initialize_investigations(c)
            from .question_bundles import initialize as initialize_questions
            initialize_questions(c)
            from .investigation_workspace import initialize as initialize_workspace
            initialize_workspace(c)
            from .investigation_plans import initialize as initialize_plans
            initialize_plans(c)
            from .evaluation_receipts import initialize as initialize_evaluations
            initialize_evaluations(c)
            from .training_lineage import initialize as initialize_training
            initialize_training(c)
            from .trainer_telemetry import initialize as initialize_telemetry
            initialize_telemetry(c)
            from .execution_records import initialize as initialize_executions
            initialize_executions(c)
            from .generation_cohorts import initialize as initialize_cohorts
            initialize_cohorts(c)
            # Serialize additive migration across concurrent servers.
            c.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in c.execute("PRAGMA table_info(jobs)")}
            for name, kind in {"owner_id":"TEXT", "lease_expires_at":"REAL", "heartbeat_at":"REAL",
                               "started_at":"TEXT", "finished_at":"TEXT", "inspector_profile":"TEXT"}.items():
                if name not in columns:
                    c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @contextmanager
    def read_snapshot(self):
        """Pin related reads to one committed WAL view without blocking writers."""
        with self.connect() as c:
            c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN')
            c.execute('SELECT rootpage FROM sqlite_schema LIMIT 1').fetchone()
            yield ReadSnapshot(self.path, c)

    def add(self, runs):
        prepared = [(r, analyze(r)) for r in runs]
        for run, analysis in prepared:
            analysis["review_revision"] = 0
            analysis["review_queue"] = review_logic.queue(run, analysis)
        result = []
        with self.connect() as c:
            for run, analysis in prepared:
                cursor = c.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?)",
                                   (run["id"], datetime.now(timezone.utc).isoformat(), dumps(run), dumps(analysis)))
                from .rollout_metrics import save, source_record
                save(c, source_record(run))
                from .graph_store import build as build_graph, save as save_graph
                save_graph(c, build_graph(run))
                result.append({"id": run["id"], "imported": cursor.rowcount == 1, "actions": analysis["metrics"]["actions"]})
        return result

    def add_study(self, study, episodes):
        """Atomic internal import of a computed source study and immutable evidence."""
        from .source_study import build
        rebuilt = build(**{key: study[key] for key in ("title", "pack", "checkpoints", "metrics", "provenance", "limitations")}, episodes=episodes)
        if rebuilt != study:
            raise InputError("Study summary does not match its source measurement records")
        with self.connect() as c:
            cursor = c.execute("INSERT OR IGNORE INTO source_studies VALUES (?,?,?)",
                               (study["id"], dumps(study), datetime.now(timezone.utc).isoformat()))
            if cursor.rowcount:
                c.executemany("INSERT INTO study_episodes VALUES (?,?,?)", [(study["id"], e["id"], dumps(e)) for e in episodes])
        return {"id": study["id"], "imported": cursor.rowcount == 1, "episodes": len(episodes)}

    def studies(self):
        with self.connect() as c:
            docs = [json.loads(r[0]) for r in c.execute("SELECT document FROM source_studies ORDER BY imported_at,id")]
        return [{k: doc[k] for k in ("id", "title", "version", "pack", "checkpoints")} for doc in docs]

    def study(self, study_id):
        with self.connect() as c:
            row = c.execute("SELECT document FROM source_studies WHERE id=?", (study_id,)).fetchone()
        if not row:
            raise KeyError(study_id)
        return json.loads(row[0])

    def study_episode(self, study_id, episode_id):
        with self.connect() as c:
            row = c.execute("SELECT document FROM study_episodes WHERE study_id=? AND id=?", (study_id, episode_id)).fetchone()
        if not row:
            raise KeyError(episode_id)
        return json.loads(row[0])

    def save_investigation(self, study_id, request):
        from .source_investigation import build
        value=build(self.study(study_id),request,lambda eid:self.study_episode(study_id,eid))
        with self.connect() as c:
            existing=c.execute('SELECT document FROM source_investigations WHERE id=?',(value['id'],)).fetchone()
            if existing and existing[0]!=dumps(value):raise InputError('Investigation identity collision')
            c.execute('INSERT OR IGNORE INTO source_investigations VALUES (?,?,?,?)',
                      (value['id'],study_id,dumps(value),datetime.now(timezone.utc).isoformat()))
        return {'id':value['id'],'study_id':study_id,'comparison_id':value['comparison_id'],
                'download_url':'/api/studies/'+study_id+'/investigations/'+value['id']+'?download=1'}

    def investigation(self, study_id, identifier):
        from .source_investigation import validate
        with self.connect() as c:
            row=c.execute('SELECT document FROM source_investigations WHERE study_id=? AND id=?',(study_id,identifier)).fetchone()
        if row is None:raise KeyError(identifier)
        return validate(json.loads(row[0]),identifier,study_id)

    def investigations(self, study_id):
        self.study(study_id)
        with self.connect() as c:
            rows=c.execute('SELECT id,document,created_at FROM source_investigations WHERE study_id=? ORDER BY created_at DESC,id',(study_id,)).fetchall()
        from .source_investigation import validate
        result=[]
        for row in rows:
            value=validate(json.loads(row['document']),row['id'],study_id)
            result.append({'id':value['id'],'selection':value['selection'],'note_preview':value['note'][:160],
                           'created_at':row['created_at']})
        return result

    def ingest(self, payload):
        """Atomically append an explicitly identified producer snapshot.

        A producer supplies sequential revisions starting at zero. Retries are
        idempotent; stale or conflicting payloads cannot move the latest pointer.
        No task/session identifier is guessed to be a logical rollout identity.
        """
        from .ingest_contract import normalize_snapshot
        from .jev import packet, JEV_HARNESS
        run = normalize_snapshot(payload)
        producer, rollout_id = payload['producer'], payload['rollout_id']
        revision, state = payload['revision'], payload['state']
        analysis = analyze(run)
        analysis["review_revision"] = 0
        analysis["review_queue"] = review_logic.queue(run, analysis)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            existing = c.execute("SELECT * FROM rollout_revisions WHERE producer=? AND rollout_id=? AND revision=?",
                                 (producer, rollout_id, revision)).fetchone()
            if existing:
                if existing["run_id"] != run["id"] or existing["state"] != state:
                    raise ReviewConflict("This producer revision already exists with different content or state")
                return {"id": run["id"], "revision": revision, "imported": False, "received": False, "reused_observations": 0}
            latest = c.execute("SELECT * FROM rollout_revisions WHERE producer=? AND rollout_id=? ORDER BY revision DESC LIMIT 1",
                               (producer, rollout_id)).fetchone()
            expected = latest["revision"] + 1 if latest else 0
            if revision != expected:
                raise ReviewConflict(f"Expected revision {expected}; received {revision}")
            inserted = c.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?)", (run["id"], now, dumps(run), dumps(analysis)))
            from .rollout_metrics import save, source_record
            save(c, source_record(run))
            from .graph_store import build as build_graph, save as save_graph
            save_graph(c, build_graph(run))
            c.execute("INSERT INTO rollout_revisions VALUES (?,?,?,?,?,?)", (producer, rollout_id, revision, run["id"], state, now))
            reused = 0
            if latest and latest["run_id"] != run["id"]:
                cached = {}
                for row in c.execute("SELECT * FROM observations WHERE run_id=? ORDER BY created_at", (latest["run_id"],)):
                    cached[row["event_id"]] = row
                for action in analysis["actions"]:
                    saved = cached.get(action["event_id"])
                    if not saved:
                        continue
                    result = json.loads(saved["result"]); p = result.get("_provenance", {})
                    if p.get("harness") != JEV_HARNESS:
                        continue
                    from .jev import JevClient
                    if not JevClient(model=p.get("model")).cache_matches(result, run, action["event_id"]):
                        continue
                    c.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)",
                              (run["id"], action["event_id"], saved["harness"], saved["model"], saved["packet_hash"], saved["result"], now))
                    reused += 1
            if reused:
                observations = {}
                for item in c.execute("SELECT event_id,result FROM observations WHERE run_id=? ORDER BY created_at", (run["id"],)):
                    observations[item["event_id"]] = json.loads(item["result"])
                reviews = [{**json.loads(r["payload"]), "id": r["id"], "created_at": r["created_at"]}
                           for r in c.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY id", (run["id"],))]
                analysis = analyze(run, review_logic.apply(observations, reviews))
                analysis["review_revision"] = reviews[-1]["id"] if reviews else 0
                analysis["review_queue"] = review_logic.queue(run, analysis)
                c.execute("UPDATE runs SET analysis=? WHERE id=?", (dumps(analysis), run["id"]))
        return {"id": run["id"], "revision": revision, "imported": inserted.rowcount == 1, "received": True, "reused_observations": reused}

    def source_status(self, run_id):
        """Small live receipt for a pinned source; do not fetch full histories."""
        with self.connect() as c:
            if not c.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise KeyError(run_id)
            current = c.execute('SELECT * FROM rollout_revisions WHERE run_id=? ORDER BY revision DESC LIMIT 1',
                                (run_id,)).fetchone()
            if current is None:
                return {'run_id': run_id, 'tracked': False}
            latest = c.execute('SELECT * FROM rollout_revisions WHERE producer=? AND rollout_id=? ORDER BY revision DESC LIMIT 1',
                               (current['producer'], current['rollout_id'])).fetchone()
        return {'run_id': run_id, 'tracked': True, 'producer': current['producer'],
                'rollout_id': current['rollout_id'], 'revision': current['revision'],
                'state': current['state'], 'latest_revision': latest['revision'],
                'latest_state': latest['state'], 'latest_run_id': latest['run_id'],
                'latest_received_at': latest['created_at'], 'is_latest': latest['run_id'] == run_id}

    def lineage(self, run_id):
        with self.connect() as c:
            row = c.execute("SELECT * FROM rollout_revisions WHERE run_id=? ORDER BY revision DESC LIMIT 1", (run_id,)).fetchone()
            if not row:
                return None
            history = [dict(r) for r in c.execute("SELECT * FROM rollout_revisions WHERE producer=? AND rollout_id=? ORDER BY revision",
                                                (row["producer"], row["rollout_id"]))]
        return {"producer": row["producer"], "rollout_id": row["rollout_id"], "revision": row["revision"],
                "state": row["state"], "is_latest": history[-1]["run_id"] == run_id, "history": history}

    def latest_revision(self, producer, rollout_id):
        with self.connect() as c:
            row = c.execute("SELECT rr.*, r.document FROM rollout_revisions rr JOIN runs r ON r.id=rr.run_id WHERE producer=? AND rollout_id=? ORDER BY revision DESC LIMIT 1",
                            (producer, rollout_id)).fetchone()
        if row is None:
            return None
        return {"revision":row["revision"],"run_id":row["run_id"],"state":row["state"],
                "metadata":json.loads(row["document"])["metadata"]}

    def get(self, run_id, raw=False):
        with self.connect() as c:
            c.execute("BEGIN")
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            reviews = [{**json.loads(r["payload"]), "id": r["id"], "created_at": r["created_at"]}
                       for r in c.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY id", (run_id,))]
            observations = {}
            activities = {r["event_id"]: json.loads(r["result"]) for r in c.execute(
                "SELECT event_id,result FROM activity_observations WHERE run_id=? ORDER BY created_at", (run_id,))}
            relations = {r['event_id']: json.loads(r['result']) for r in c.execute(
                'SELECT event_id,result FROM relation_observations WHERE run_id=? ORDER BY created_at', (run_id,))}
            entity_history = [dict(r) | {'result':json.loads(r['result'])} for r in c.execute(
                'SELECT * FROM entity_observations WHERE run_id=? ORDER BY created_at', (run_id,))]
            reference_history = [dict(r) | {'result':json.loads(r['result'])} for r in c.execute(
                'SELECT * FROM reference_observations WHERE run_id=? ORDER BY created_at', (run_id,))]
            occurrence_history = [dict(r) | {'result':json.loads(r['result'])} for r in c.execute(
                'SELECT * FROM occurrence_observations WHERE run_id=? ORDER BY created_at', (run_id,))]
            frame_history = [dict(r) | {'result':json.loads(r['result'])} for r in c.execute(
                'SELECT * FROM frame_observations WHERE run_id=? ORDER BY created_at', (run_id,))]
            move_history = [dict(r) | {'result':json.loads(r['result'])} for r in c.execute(
                'SELECT * FROM move_observations WHERE run_id=? ORDER BY created_at', (run_id,))]
            entities = {r['event_id']:r['result'] for r in entity_history}
            if raw:
                activity_history = [dict(r) | {"result": json.loads(r["result"])} for r in c.execute(
                    "SELECT * FROM activity_observations WHERE run_id=? ORDER BY created_at", (run_id,))]
                for record in c.execute("SELECT event_id,result FROM observations WHERE run_id=? ORDER BY created_at", (run_id,)):
                    observations[record["event_id"]] = json.loads(record["result"])
        if row is None:
            raise KeyError(run_id)
        run = json.loads(row["document"])
        revision = reviews[-1]["id"] if reviews else 0
        analysis = json.loads(row["analysis"])
        if analysis.get("review_revision", 0) != revision or analysis.get("harness_version") != HARNESS_VERSION:
            self.refresh(run_id)
            return self.get(run_id, raw=raw)
        if not raw:
            run.pop("raw", None)
        bundle = {"run": run, "analysis": analysis, "imported_at": row["imported_at"],
                  "review_revision": revision, "reviews": reviews, "ingestion": self.lineage(run_id)}
        from .activity import analyze as analyze_activity
        bundle["activity"] = analyze_activity(run, activities)
        from .unit_graph import build as build_unit_graph
        bundle['unit_graph'] = build_unit_graph(run, bundle['activity'], relations, entities)
        from .entity_extraction import historical_summary
        history_by_unit = {}
        for record in entity_history:
            history_by_unit.setdefault(record['event_id'],[]).append(record)
        for node in bundle['unit_graph']['nodes']:
            extraction=node['entity_extraction']
            current=extraction.get('observation',{}).get('_provenance',{}).get('request_hash')
            extraction['previous_observations']=[historical_summary(r) for r in history_by_unit.get(node['id'],[])
                                                 if r['result']['_provenance'].get('request_hash') != current]
        from .entity_occurrences import project_graph as project_occurrences
        project_occurrences(run, bundle['unit_graph'], occurrence_history)
        from .reference_resolution import project_graph as project_references
        project_references(run, bundle['unit_graph'], reference_history)
        from .local_frames import project_graph as project_frames
        project_frames(run, bundle['unit_graph'], frame_history)
        if raw:
            bundle["model_observations"] = observations
            bundle["activity_observation_history"] = activity_history
            bundle['entity_observation_history'] = entity_history
            bundle['reference_observation_history'] = reference_history
            bundle['occurrence_observation_history'] = occurrence_history
            bundle['frame_observation_history'] = frame_history
            bundle['move_observation_history'] = move_history
        return bundle

    def record_moves(self, run_id, unit_id, result):
        """Import complete source-current moves; preserve all other observations."""
        from .behavior_moves import MoveClient
        with self.connect() as c:
            row = c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None: raise KeyError(run_id)
        p = result.get('_provenance', {})
        if not MoveClient(model=p.get('model')).cache_matches(result, json.loads(row['document']), unit_id):
            raise InputError('Move result must be complete and match current source evidence')
        key = (run_id, unit_id, p['harness'], p['model'], p['packet_hash'])
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT result FROM move_observations WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?', key).fetchone()
            if previous:
                if json.loads(previous['result']) != result: raise InputError('Completed move observations are immutable')
                return
            c.execute('INSERT INTO move_observations VALUES (?,?,?,?,?,?,?)', (*key, dumps(result), datetime.now(timezone.utc).isoformat()))

    def record_frames(self, run_id, unit_id, result):
        """Import a completed, source-current frame inspection without rewriting history."""
        from .local_frames import FrameClient, is_extension
        bundle = self.get(run_id)
        p = result.get('_provenance', {})
        client = FrameClient(nodes=bundle['unit_graph']['nodes'], model=p.get('model'))
        if not client.cache_matches(result, bundle['run'], unit_id):
            raise InputError('Frame result must be complete and match current local evidence')
        key = (run_id, unit_id, p['harness'], p['model'], p['packet_hash'])
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT result FROM frame_observations WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?', key).fetchone()
            stamp = datetime.now(timezone.utc).isoformat()
            if previous:
                old = json.loads(previous['result'])
                if old == result: return
                if not is_extension(old, result): raise InputError('Completed or conflicting frame observations are immutable')
                c.execute('UPDATE frame_observations SET result=?,created_at=? WHERE run_id=? AND event_id=? AND harness=? AND model=? AND packet_hash=?', (dumps(result), stamp, *key))
            else:
                c.execute('INSERT INTO frame_observations VALUES (?,?,?,?,?,?,?)', (*key, dumps(result), stamp))

    def list(self):
        with self.connect() as c:
            c.execute("BEGIN")
            rows = c.execute("SELECT * FROM runs ORDER BY imported_at DESC, id").fetchall()
            revisions = c.execute("SELECT * FROM rollout_revisions ORDER BY producer,rollout_id,revision").fetchall()
            review_versions = dict(c.execute("SELECT run_id,MAX(id) FROM reviews GROUP BY run_id").fetchall())
        # A reviewer can commit an annotation immediately before the materialized
        # view refresh. Do not compare its old unreviewed counts in that window.
        stale = [r['id'] for r in rows if
                 (json.loads(r['analysis']).get('review_revision',0)!=review_versions.get(r['id'],0) or
                  json.loads(r['analysis']).get('harness_version')!=HARNESS_VERSION)]
        if stale:
            for run_id in stale:
                self.refresh(run_id)
            return self.list()
        histories, lineages = {}, {}
        for revision in revisions:
            history=histories.setdefault((revision['producer'],revision['rollout_id']),[])
            history.append(dict(revision))
            lineages[revision['run_id']] = revision
        result = []
        for row in rows:
            revision = lineages.get(row['id'])
            ingestion = None
            if revision is not None:
                history=histories[(revision['producer'],revision['rollout_id'])]
                ingestion={'producer':revision['producer'],'rollout_id':revision['rollout_id'],'revision':revision['revision'],
                           'state':revision['state'],'is_latest':history[-1]['run_id']==row['id'],'history':history}
            if ingestion and not ingestion["is_latest"]:
                continue
            run, a = json.loads(row["document"]), json.loads(row["analysis"])
            result.append({"id": row["id"], "metadata": run["metadata"], "adapter": run["adapter"],
                           "sampling_hash":digest(run["metadata"].get("sampling",{})),
                           "adapter_version":run["adapter_version"],
                           "environment_context_hash":run.get("environment_context",{}).get("configuration_hash"),
                           "ingestion": ingestion,
                           "metrics": a["metrics"], "harness_version": a["harness_version"],
                           "inspector_signature": a.get("inspector_signature", "heuristic"),
                           "inspector_profiles": a.get("inspector_profiles", []),
                           "reviewed_actions": a.get("reviewed_actions", 0),
                           "semantic_coverage": a.get("semantic_coverage", 0),
                           "warnings": run["warnings"], "imported_at": row["imported_at"],
                           "outcome": {k: run["outcome"].get(k) for k in ("verified_success", "termination")}})
        return result

    def record_operation_observation(self,run,protocol,result,workspace,validation):
        from .operation_workspace import protocol as current_protocol
        from .operation_outcomes import audit,action_outcomes
        from .rollout_metrics import operation_record,save
        if protocol!=current_protocol():raise InputError('Operation protocol differs')
        if audit(run,result,workspace)!=validation:raise InputError('Operation registration audit differs')
        action_outcomes(run,result)
        key=digest({'protocol':protocol,'result':result});source_hash=digest(run)
        measurement=operation_record(run,protocol,result,key)
        with self.connect() as c:
            source=c.execute('SELECT document FROM runs WHERE id=?',(run['id'],)).fetchone()
            if source is None or digest(json.loads(source['document']))!=source_hash:
                raise InputError('Operation registration source differs from stored rollout')
            c.execute('INSERT OR IGNORE INTO operation_observations VALUES (?,?,?,?,?,?,?,?)',
                (key,run['id'],protocol['id'],source_hash,dumps(protocol),dumps(result),str(Path(workspace).resolve()),datetime.now(timezone.utc).isoformat()))
            save(c,measurement)
        return {'id':key,'run_id':run['id'],'protocol_id':protocol['id'],'source_hash':source_hash,
                'response_count':len(result['observations']),
                'metrics_url':'/rollouts?observer='+protocol['id']+'&metric=operation_failed_fraction&run='+run['id']}

    def operation_observation(self,identifier):
        with self.connect() as c:
            row=c.execute('SELECT * FROM operation_observations WHERE id=?',(identifier,)).fetchone()
            if row is None:raise InputError('Unknown operation observation')
            source=c.execute('SELECT document FROM runs WHERE id=?',(row['run_id'],)).fetchone()
        run=json.loads(source['document']);result=json.loads(row['result']);definition=json.loads(row['protocol'])
        if digest(run)!=row['source_hash'] or digest({'protocol':definition,'result':result})!=identifier:
            raise InputError('Stored operation observation changed')
        from .operation_outcomes import action_outcomes
        aggregate=action_outcomes(run,result);events={e['id']:e for e in run['events']}
        missing=[e['id'] for e in run['events'] if e['kind']=='action' and e['actor']=='agent'
                 and not e.get('copied_context') and e['id'] not in aggregate]
        return {'id':identifier,'run_id':run['id'],'protocol':definition,'source_hash':row['source_hash'],
                'result':result,'action_outcomes':aggregate,
                'actions_without_observed_response':missing,
                'actions':{aid:events[aid] for aid in aggregate},'workspace':row['workspace'],
                'validation':'Audited against exact saved decisions at registration; independent accuracy unmeasured.'}

    def observations(self, run_id):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM observations WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        result = {}
        for row in rows:
            result[row["event_id"]] = json.loads(row["result"])
        return result

    def activity_observations(self, run_id):
        with self.connect() as c:
            return {r["event_id"]: json.loads(r["result"]) for r in c.execute(
                "SELECT event_id,result FROM activity_observations WHERE run_id=? ORDER BY created_at", (run_id,))}

    def record_activity(self, run_id, unit_id, result):
        from .activity import ActivityClient, HARNESS
        p = result["_provenance"]
        run = self.get(run_id, raw=True)["run"]
        if p.get("source") != "jev" or not ActivityClient(model=p["model"]).cache_matches(result, run, unit_id):
            raise InputError("Activity result does not match the exact current subject packet")
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO activity_observations VALUES (?,?,?,?,?,?,?)",
                      (run_id, unit_id, HARNESS, p["model"], p["packet_hash"], dumps(result), datetime.now(timezone.utc).isoformat()))

    def import_activity_components(self, directory, name=None):
        from .activity_components import prepare_import
        with self.connect() as c:
            def reader(rid):
                row=c.execute('SELECT document FROM runs WHERE id=?',(rid,)).fetchone()
                if row is None:raise InputError('Import source trajectory before component observations')
                return json.loads(row[0])
            collection,records=prepare_import(directory,reader,name)
        inserted=0
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT document FROM activity_component_collections WHERE id=?',(collection['id'],)).fetchone()
            if old and json.loads(old[0])!=collection:raise InputError('Existing immutable component collection differs')
            c.execute('INSERT OR IGNORE INTO activity_component_collections VALUES (?,?,?)',
                      (collection['id'],dumps(collection),datetime.now(timezone.utc).isoformat()))
            for record in records:
                old=c.execute('SELECT document FROM activity_component_records WHERE id=?',(record['id'],)).fetchone()
                if old and json.loads(old[0])!=record:raise InputError('Existing immutable component result differs')
                inserted+=c.execute('INSERT OR IGNORE INTO activity_component_records VALUES (?,?,?,?,?)',
                    (record['id'],collection['id'],record['run_id'],record['subject']['id'],dumps(record))).rowcount
        return {'collection_id':collection['id'],'inserted_records':inserted,'records':len(records),
                'real_subjects':collection['real_subjects'],'skipped_nonreal_cases':collection['skipped_nonreal_cases'],'provider_calls':0}

    def activity_component_catalog(self, run_id=None):
        with self.connect() as c:
            query='SELECT collection_id,run_id,COUNT(*) AS records,COUNT(DISTINCT unit_id) AS units FROM activity_component_records'
            rows=c.execute(query+(' WHERE run_id=?' if run_id else '')+' GROUP BY collection_id,run_id', (run_id,) if run_id else ()).fetchall()
            counts={}
            for row in rows:counts.setdefault(row['collection_id'],[]).append(dict(row))
            collections=[json.loads(r[0]) for r in c.execute('SELECT document FROM activity_component_collections ORDER BY imported_at,id')]
            names={r['id']:json.loads(r['document'])['metadata'].get('task_id') or r['id'] for r in c.execute('SELECT id,document FROM runs')}
        return {'collections':[{**v,'available_runs':[dict(r,task_id=names[r['run_id']]) for r in counts[v['id']]]}
                               for v in collections if v['id'] in counts]}

    def activity_component_comparison(self, collection_id, reference, candidate, run_id=None):
        from .activity_components import summary,compare
        with self.connect() as c:
            row=c.execute('SELECT document FROM activity_component_collections WHERE id=?',(collection_id,)).fetchone()
            if not row:raise KeyError(collection_id)
            collection=json.loads(row[0])
            if reference==candidate or any(v not in collection['variants'] for v in (reference,candidate)):
                raise InputError('Select two different variants in this collection')
            query='SELECT document FROM activity_component_records WHERE collection_id=?'
            rows=c.execute(query+(' AND run_id=?' if run_id else ''), (collection_id,run_id) if run_id else (collection_id,)).fetchall()
        records=[summary(json.loads(r[0])) for r in rows]
        return {'collection':collection,'records':records,'comparison':compare(records,reference,candidate)}

    def activity_component_record(self, record_id):
        from .activity_context import visible_prefix
        with self.connect() as c:
            row=c.execute('SELECT document FROM activity_component_records WHERE id=?',(record_id,)).fetchone()
            if not row:raise KeyError(record_id)
            record=json.loads(row[0]);run=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(record['run_id'],)).fetchone()[0])
        return {**record,'source_prefix':visible_prefix(run,record['subject'])}

    def record(self, run_id, event_id, harness, model, packet_hash, result):
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)",
                      (run_id, event_id, harness, model, packet_hash, dumps(result), datetime.now(timezone.utc).isoformat()))

    def reselect_observations(self, *, apply=False):
        """Append argmax decisions from exact saved distributions, with no API calls."""
        from .jev import JevClient, SELECTION_POLICY
        from .activity import ActivityClient
        report = {"selection_policy": SELECTION_POLICY, "applied": apply, "provider_calls": 0, "tables": {}}
        changed_runs = set()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
            if apply and c.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
                raise InputError("Finish observation jobs before reselecting saved distributions")
            runs = {r["id"]: json.loads(r["document"]) for r in c.execute("SELECT id,document FROM runs")}
            for table, client_type in (("observations", JevClient), ("activity_observations", ActivityClient)):
                latest = {(r["run_id"], r["event_id"]): r for r in c.execute(f"SELECT * FROM {table} ORDER BY created_at")}
                counts = report["tables"][table] = {"eligible": 0, "already_current": 0, "written": 0, "skipped": {}, "changed_statuses": 0}
                for (rid, subject_id), row in latest.items():
                    saved = json.loads(row["result"])
                    try:
                        client = client_type(model=saved["_provenance"]["model"])
                        result = client.reselect(saved, runs[rid], subject_id)
                    except (InputError, KeyError) as err:
                        reason = str(err)
                        counts["skipped"][reason] = counts["skipped"].get(reason, 0) + 1
                        continue
                    if result is saved:
                        counts["already_current"] += 1
                        continue
                    counts["eligible"] += 1
                    counts["changed_statuses"] += sum(v.get("status") != saved.get(k, {}).get("status") for k, v in result.items() if not k.startswith("_"))
                    if apply:
                        p = result["_provenance"]
                        cur = c.execute(f"INSERT OR IGNORE INTO {table} VALUES (?,?,?,?,?,?,?)",
                                        (rid, subject_id, p["harness"], p["model"], p["packet_hash"], dumps(result), datetime.now(timezone.utc).isoformat()))
                        counts["written"] += cur.rowcount
                        changed_runs.add(rid)
        for rid in changed_runs:
            self.refresh(rid)
        return report

    def reviews(self, run_id):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{**json.loads(r["payload"]), "id": r["id"], "created_at": r["created_at"]} for r in rows]

    def review(self, run_id, payload):
        run = self.get(run_id, raw=True)["run"]
        reviewed = review_logic.validate(run, payload)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            revision = c.execute("SELECT COALESCE(MAX(id),0) FROM reviews WHERE run_id=?", (run_id,)).fetchone()[0]
            if revision != reviewed["expected_revision"]:
                raise ReviewConflict("Another review was saved. Reload this run before applying your review.")
            cur = c.execute("INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)",
                            (run_id, dumps(reviewed), datetime.now(timezone.utc).isoformat()))
            new_revision = cur.lastrowid
        self.refresh(run_id)
        return {"review_id": new_revision, "review_revision": new_revision}

    def refresh(self, run_id):
        with self.connect() as c:
            # One transaction keeps a concurrent model result or review from
            # overwriting a newer materialized analysis with an older snapshot.
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = json.loads(row["document"])
            observations = {}
            for row in c.execute("SELECT event_id,result FROM observations WHERE run_id=? ORDER BY created_at", (run_id,)):
                observations[row["event_id"]] = json.loads(row["result"])
            reviews = [{**json.loads(r["payload"]), "id": r["id"], "created_at": r["created_at"]}
                       for r in c.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY id", (run_id,))]
            analysis = analyze(run, review_logic.apply(observations, reviews))
            analysis["review_revision"] = reviews[-1]["id"] if reviews else 0
            analysis["review_queue"] = review_logic.queue(run, analysis)
            c.execute("UPDATE runs SET analysis=? WHERE id=?", (dumps(analysis), run_id))
        return analysis
