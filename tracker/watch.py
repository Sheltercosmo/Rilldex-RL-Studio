"""Read-only producer directory polling with restart-safe revision ingestion."""
from __future__ import annotations

import hashlib
import json
import os
import time
import tomllib
from pathlib import Path

from .context import HARBOR_CONFIG_PATHS, pick, result_projection
from .schema import InputError, digest

MAX_FILE_BYTES = 20 * 1024 * 1024


class ReadBudgetExceeded(InputError):
    pass


class DirectoryWatcher:
    def __init__(self, store, root, *, producer, format="auto", metadata=None, task_root=None, max_files=1000):
        self.store, self.root = store, Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise InputError("Watch root must be an existing output directory")
        if format not in {"auto", "harbor", "swe-agent"}:
            raise InputError("Watcher format must be auto, harbor or swe-agent")
        if not isinstance(producer,str) or not producer.strip() or len(producer)>240:
            raise InputError("Supply a producer label of 1–240 characters")
        self.producer, self.format = producer, format
        if metadata is not None and not isinstance(metadata,dict):
            raise InputError("Watcher metadata defaults must be an object")
        self.metadata = dict(metadata or {})
        self.task_root = Path(task_root).expanduser().resolve() if task_root else None
        if self.task_root and not self.task_root.is_dir():
            raise InputError("Explicit task root must be an existing directory")
        self.max_files = max_files
        self._read_set = {}
        self._stable = {}
        self.read_budget = None

    @staticmethod
    def _within(path, root):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise InputError("Referenced path escapes the explicitly selected directory")
        return resolved

    def _read(self, path, *, optional=False, root=None, encoding="json"):
        path = self._within(path, root or self.root)
        try:
            before = path.stat()
        except FileNotFoundError:
            if optional:
                self._read_set[path] = None
                return None
            raise InputError(f"Referenced source is not available yet: {path.name}") from None
        if before.st_size > MAX_FILE_BYTES:
            raise InputError(f"{path.name} exceeds the 20 MiB file limit")
        if self.read_budget is not None:
            if before.st_size > self.read_budget:
                raise ReadBudgetExceeded('Preview byte limit reached; collection can validate the remaining sources')
            self.read_budget -= before.st_size
        data = path.read_bytes()
        after = path.stat()
        if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns) or len(data) != before.st_size:
            raise InputError(f"{path.name} changed while being read; retrying on the next poll")
        self._read_set[path] = (after.st_size,after.st_mtime_ns)
        text = data.decode("utf-8-sig")
        value = json.loads(text) if encoding == "json" else tomllib.loads(text) if encoding == "toml" else text
        if encoding != "text" and not isinstance(value,dict):
            raise InputError(f"{path.name} must contain an object")
        return value, hashlib.sha256(data).hexdigest()

    def _source(self, path, kind, projection=None, *, root=None, encoding="json"):
        read = self._read(path, optional=True, root=root, encoding=encoding)
        if read is None:
            return None
        data, sha = read
        return {"name":str(path.resolve().relative_to(root or self.root)).replace("\\","/"), "kind":kind,
                "data":projection(data) if projection else data, "projection":projection is not None, "source_sha256":sha}

    def _paths(self):
        result = []
        def scan(directory, depth=0):
            if depth > 32:
                raise InputError("Output tree exceeds 32 directory levels; select a narrower root")
            for entry in os.scandir(directory):
                if entry.is_symlink():
                    continue
                path = Path(entry.path)
                try:
                    self._within(path,self.root)
                except InputError:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    scan(path,depth+1)
                elif entry.is_file(follow_symlinks=False):
                    swe = path.suffix == ".traj" and self.format in {"auto","swe-agent"}
                    harbor = (path.name == "trajectory.json" or path.name.endswith(".trajectory.json")) and self.format in {"auto","harbor"}
                    if swe or harbor:
                        result.append(path)
                        if len(result) > self.max_files:
                            raise InputError(f"More than {self.max_files} trajectory candidates; select a narrower output root or increase --max-files")
        scan(self.root)
        return sorted(result)

    def _harbor(self, path, document):
        documents, current, visited = [], path, set()
        complete_chain = True
        while current:
            current = self._within(current,self.root)
            if current in visited or len(visited) >= 32:
                raise InputError("Continuation cycle or more than 32 documents")
            visited.add(current)
            read = (document,None) if current == path.resolve() else self._read(current, optional=True)
            if read is None:
                complete_chain = False
                break
            data = read[0]
            documents.append({"path":str(current.relative_to(self.root)).replace("\\","/"),"document":data})
            reference = data.get("continued_trajectory_ref")
            if reference is not None and not isinstance(reference,str):
                raise InputError("Continuation reference must be a relative path string")
            if reference and (Path(reference).is_absolute() or ".." in Path(reference).parts or "\\" in reference):
                raise InputError("Continuation reference must stay inside the producer tree")
            current = current.parent/reference if reference else None
        bundled = len(documents) > 1 or document.get("continued_trajectory_ref")
        trace = {"tracker_bundle":"harbor/1","root":str(path.relative_to(self.root)).replace("\\","/"),"documents":documents} if bundled else document
        # Official layout: trial/agent/trajectory.json; multi-step traces live
        # under trial/steps/<step>/agent/trajectory.json.
        trial = path.parent.parent if path.parent.name == "agent" else path.parent
        step_name = None
        if trial.parent.name == "steps":
            step_name, trial = trial.name, trial.parent.parent
        sources = []
        config_source = self._source(trial/"config.json","harbor_trial_config",lambda d:pick(d,HARBOR_CONFIG_PATHS))
        result_source = self._source(trial/"result.json","harbor_trial_result",result_projection)
        sources.extend(s for s in (config_source,result_source) if s)
        config = config_source["data"] if config_source else {}
        result = result_source["data"] if result_source else {}
        meta = {}
        task = config.get("task") or {}
        task_id = result.get("task_name") or task.get("name") or task.get("path")
        if task_id:
            meta.update(task_id=str(task_id),task_id_basis="Harbor producer task metadata")
        if result.get("task_checksum"):
            meta["task_revision"] = result["task_checksum"]
        if step_name:
            meta["producer_step"] = step_name
            if task_id:
                meta["task_id"] += "::" + step_name
        if self.task_root and task.get("path"):
            task_path = self._within(self.task_root/str(task["path"]),self.task_root)
            for filename,kind,encoding in [("task.toml","harbor_task_config","toml"),("instruction.md","harbor_instruction","text")]:
                project = (lambda d:pick(d,("schema_version","agent.timeout_sec","agent.user","environment.cpus","environment.memory_mb","environment.os","environment.network_mode","environment.allowed_hosts","verifier.timeout_sec","verifier.environment_mode","multi_step_reward_strategy"))) if encoding == "toml" else None
                source = self._source(task_path/filename,kind,project,root=self.task_root,encoding=encoding)
                if source:
                    source["name"] = "task-source/" + source["name"]
                    sources.append(source)
        terminal = isinstance(result.get("finished_at"),str) and bool(result["finished_at"])
        state = "failed" if terminal and result.get("exception_info") else "complete" if terminal else "in_progress"
        if not complete_chain:
            state = "in_progress"
        tracking = self._read(trial/"tracking.json",optional=True)
        if tracking:
            meta.update(tracking[0])
        return trace, sources, meta, state

    def _payload(self, path, document, *, source_path=None):
        relative = str(path.relative_to(self.root)).replace("\\","/")
        meta = {}
        if path.suffix == ".traj":
            info = document.get("info") or {}
            if not isinstance(info,dict):
                raise InputError("SWE-agent info must be an object")
            state = "complete" if isinstance(info.get("exit_status"),str) and info["exit_status"] else "in_progress"
            trace, sources, fmt = document, [], "swe-agent"
            meta.update(task_id=document.get("instance_id") or info.get("instance_id") or path.stem,
                        task_id_basis="SWE-agent instance field or producer .traj filename")
            if source_path:
                meta["embedded_attempt_source"] = source_path
        else:
            trace, sources, meta, state = self._harbor(path, document)
            fmt = "harbor-bundle" if trace.get("tracker_bundle") else "auto"
        # CLI metadata supplies defaults; per-rollout metadata is authoritative.
        meta = {**self.metadata, **meta}
        if path.suffix == ".traj":
            tracking = self._read(path.with_suffix(".tracking.json"),optional=True)
            if tracking:
                meta.update(tracking[0])
        payload = {"producer":self.producer,"rollout_id":relative,"document":trace,"format":fmt,
                   "sources":sources,"metadata":meta,"state":state}
        return payload

    def _snapshot(self, path, document, *, source_path=None):
        payload = self._payload(path, document, source_path=source_path)
        relative = payload['rollout_id']
        state = payload['state']
        fingerprint = digest(payload)
        latest = self.store.latest_revision(self.producer,relative)
        if latest and latest["metadata"].get("watch_fingerprint") == fingerprint:
            return {"path":relative,"status":"unchanged","id":latest["run_id"]}
        # A whole read set is checked again before committing a snapshot.
        for read_path,signature in self._read_set.items():
            if self._signature(read_path) != signature:
                raise InputError("Producer files changed during collection; retrying on the next poll")
        payload["metadata"]["watch_fingerprint"] = fingerprint
        payload["revision"] = latest["revision"] + 1 if latest else 0
        receipt = self.store.ingest(payload)
        return {"path":relative,"status":"ingested", "state":state, **receipt}

    @staticmethod
    def _signature(path):
        try:
            stat = path.stat()
            return stat.st_size, stat.st_mtime_ns
        except FileNotFoundError:
            return None

    def poll(self, stop=None):
        rows = []
        for path in self._paths():
            if stop and stop.is_set():
                break
            # Include missing optional sidecars in the signature set: a late
            # result or tracking file must invalidate an unchanged trajectory.
            cached = self._stable.get(path)
            if cached and all(self._signature(p) == sig for p,sig in cached[0].items()):
                rows.extend({**row,'status':'unchanged'} for row in cached[1])
                continue
            self._read_set = {}
            start = len(rows)
            try:
                document, _ = self._read(path)
                attempts = document.get("attempts") if path.suffix == ".traj" else None
                if isinstance(attempts,list):
                    # RetryAgent's root duplicates its chosen attempt. Prefer
                    # actual attempt files, or recover embedded attempts when
                    # those files are absent. Both use the same logical identity.
                    for index,attempt in enumerate(attempts):
                        child = path.parent/f"attempt_{index}"/path.name
                        if not child.exists():
                            if not isinstance(attempt,dict):
                                raise InputError("Retry attempt must be an object")
                            rows.append(self._snapshot(child,attempt,source_path=str(path.relative_to(self.root))+f"#/attempts/{index}"))
                    continue
                rows.append(self._snapshot(path,document))
                self._stable[path] = (dict(self._read_set), rows[start:])
            except (OSError,ValueError,TypeError) as error:
                rows.append({"path":str(path.relative_to(self.root)),"status":"deferred","error":str(error)})
        return {"producer":self.producer,"scanned":len(rows),"ingested":sum(r["status"]=="ingested" for r in rows),
                "deferred":sum(r["status"]=="deferred" for r in rows),"entries":rows}

    def run(self, interval=2.0, once=False):
        previous_errors = None
        try:
            while True:
                report = self.poll()
                errors = [(r["path"],r.get("error")) for r in report["entries"] if r["status"]=="deferred"]
                if once or report["ingested"] or errors != previous_errors:
                    print(json.dumps(report,ensure_ascii=False),flush=True)
                previous_errors = errors
                if once:
                    return report
                time.sleep(interval)
        except KeyboardInterrupt:
            print(json.dumps({"producer":self.producer,"status":"stopped"}),flush=True)
