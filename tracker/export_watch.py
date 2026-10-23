"""Replay and follow append-only JSONL exports through the normal ingestion path.

Offsets are durable, but only advance after a receipt. A crash between receipt and
offset commit replays the same revision. Already accepted bytes may not change.
"""
from __future__ import annotations

import hashlib
import json

from .ingest_contract import explicit_envelope
from .output_files import matching_paths
from .adapters import FORMATS, detect
from .schema import InputError, digest, metadata as normalize_metadata
from .watch import DirectoryWatcher, MAX_FILE_BYTES


class ExportWatcher(DirectoryWatcher):
    def __init__(self, store, root, *, producer, format="auto", metadata=None,
                 pattern="*.jsonl", max_files=1000, max_records=100):
        # Reuse path containment, producer validation and the CLI run loop.
        super().__init__(store, root, producer=producer, max_files=max_files)
        if format not in FORMATS:
            raise InputError("Choose a supported document format")
        if not isinstance(pattern, str) or not pattern.endswith('.jsonl') or any(c in pattern for c in '/\\'):
            raise InputError("Export pattern must be a filename glob ending in .jsonl, such as worker-*.jsonl")
        if type(max_records) is not int or not 1 <= max_records <= 10000:
            raise InputError("Use 1–10000 records per file per poll")
        self.format, self.pattern, self.max_records = format, pattern, max_records
        if metadata is not None and not isinstance(metadata, dict):
            raise InputError('Metadata must be an object')
        self.metadata = normalize_metadata(metadata)
        if not self.metadata.get('experiment'):
            raise InputError("JSONL collection requires an experiment; set --experiment or metadata.experiment")
        self.config_hash = digest({'schema': 'export-watch/1', 'format': format, 'metadata': self.metadata})

    def _initialize(self):
        with self.store.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS export_cursors (
                producer TEXT NOT NULL, path TEXT NOT NULL, offset INTEGER NOT NULL,
                line INTEGER NOT NULL, prefix_sha256 TEXT NOT NULL, config_sha256 TEXT NOT NULL,
                PRIMARY KEY(producer,path))''')

    def _paths(self):
        return matching_paths(self)

    def _envelope(self, doc, relative, line):
        envelope = explicit_envelope(doc, producer=self.producer, format=self.format, metadata=self.metadata)
        if envelope is not None:
            return envelope
        from .weave_import import matches as weave_matches
        if self.format == 'weave' or self.format == 'auto' and weave_matches(doc):
            raise InputError('Weave exports contain calls, not one rollout per line. Use Import files or rilldex import to group the full export by trace ID.')
        fmt = self.format
        if fmt == 'auto' and all(k in doc for k in ('input', 'output', 'step')):
            fmt = detect(doc)
        # Physical line and relative filename identify separate samples even if
        # their contents match. Neither arrival time nor filename is a train step.
        return {'producer': self.producer, 'rollout_id': 'export-' + digest([relative, line]),
                'revision': 0, 'state': 'complete', 'format': fmt, 'document': doc,
                'metadata': {**self.metadata, 'source_export_path': relative, 'source_line': line,
                             'source_record_sha256': digest(doc)}}

    def _advance(self, relative, offset, line, sha):
        with self.store.connect() as c:
            c.execute('''INSERT INTO export_cursors VALUES (?,?,?,?,?,?)
                ON CONFLICT(producer,path) DO UPDATE SET offset=excluded.offset,
                line=excluded.line,prefix_sha256=excluded.prefix_sha256
                WHERE excluded.offset >= export_cursors.offset''',
                (self.producer, relative, offset, line, sha, self.config_hash))

    def _file(self, path, entries, stop):
        relative = path.relative_to(self.root).as_posix()
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if self._stable.get(path) == signature:
            return
        with self.store.connect() as c:
            row = c.execute('SELECT * FROM export_cursors WHERE producer=? AND path=?',
                            (self.producer, relative)).fetchone()
        offset, line = (row['offset'], row['line']) if row else (0, 0)
        if row and row['config_sha256'] != self.config_hash:
            raise InputError("Export settings changed after receipt; restore the original settings or use a new producer")
        if stat.st_size < offset:
            raise InputError("Accepted export was truncated; restore it or use a new filename for a new shard")
        with path.open('rb') as stream:
            prefix = hashlib.sha256()
            remaining = offset
            while remaining:
                if stop and stop.is_set():
                    return
                data = stream.read(min(1024 * 1024, remaining))
                if not data:
                    raise InputError("Export changed during prefix validation; retrying")
                prefix.update(data)
                remaining -= len(data)
            if row and prefix.hexdigest() != row['prefix_sha256']:
                raise InputError("Accepted export bytes changed; restore them or use a new filename for corrected data")
            for _ in range(self.max_records):
                if stop and stop.is_set():
                    return
                data = stream.readline(MAX_FILE_BYTES + 1)
                if not data:
                    after = path.stat()
                    if (after.st_size, after.st_mtime_ns) == signature:
                        self._stable[path] = signature
                    return
                if len(data) > MAX_FILE_BYTES:
                    raise InputError(f"Line {line + 1} exceeds the 20 MiB record limit")
                if not data.endswith(b'\n'):
                    entries.append({'path': relative, 'status': 'waiting', 'line': line + 1,
                                    'note': 'Waiting for a newline to commit the last record'})
                    return
                try:
                    text = data.decode('utf-8-sig' if line == 0 else 'utf-8').strip()
                    if text:
                        envelope = self._envelope(json.loads(text), relative, line + 1)
                        receipt = self.store.ingest(envelope)
                        entries.append({'path': relative, 'line': line + 1,
                                        'status': 'ingested' if receipt['received'] else 'unchanged', **receipt})
                except (ValueError, TypeError) as e:
                    raise InputError(f"Line {line + 1}: {e}") from e
                prefix.update(data)
                offset += len(data)
                line += 1
                self._advance(relative, offset, line, prefix.hexdigest())
            if stream.read(1):
                entries.append({'path': relative, 'status': 'backlog', 'line': line + 1,
                                'note': 'More records remain; collection continues on the next poll'})

    def poll(self, stop=None):
        self._initialize()
        paths = self._paths()
        entries = []
        for path in paths:
            if stop and stop.is_set():
                break
            try:
                self._file(path, entries, stop)
            except (OSError, ValueError, TypeError) as e:
                entries.append({'path': path.relative_to(self.root).as_posix(), 'status': 'deferred', 'error': str(e)})
        return {'producer': self.producer, 'scanned': len(paths), 'entries': entries,
                'ingested': sum(e['status'] == 'ingested' for e in entries),
                'deferred': sum(e['status'] == 'deferred' for e in entries),
                'waiting': sum(e['status'] == 'waiting' for e in entries),
                'backlog': sum(e['status'] == 'backlog' for e in entries)}
