"""Follow one JSON snapshot per rollout, independent of the trainer framework.

Raw files use relative-path identities and automatically numbered revisions.
Explicit envelopes keep their producer identities, revisions and state exactly,
so the same record can also be delivered through the HTTP/outbox route.
"""
from .adapters import FORMATS, detect
from .ingest_contract import explicit_envelope
from .output_files import matching_paths
from .schema import InputError, digest, metadata as normalize_metadata
from .watch import DirectoryWatcher


class SnapshotWatcher(DirectoryWatcher):
    def __init__(self, store, root, *, producer, format='auto', metadata=None,
                 pattern='*.json', snapshot_state='in_progress', max_files=1000):
        super().__init__(store, root, producer=producer, max_files=max_files)
        if format not in FORMATS:
            raise InputError('Choose a supported document format')
        if not isinstance(pattern, str) or not pattern.endswith('.json') or any(c in pattern for c in '/\\'):
            raise InputError('Snapshot pattern must be a filename glob ending in .json, such as rollout-*.json')
        if snapshot_state not in {'in_progress', 'complete'}:
            raise InputError('Snapshot state must be in_progress or complete; explicit envelopes supply their own state')
        if metadata is not None and not isinstance(metadata, dict):
            raise InputError('Metadata must be an object')
        self.metadata = normalize_metadata(metadata)
        if not self.metadata.get('experiment'):
            raise InputError('JSON collection requires an experiment; set --experiment or metadata.experiment')
        self.format, self.pattern, self.snapshot_state = format, pattern, snapshot_state

    def _paths(self):
        return matching_paths(self)

    def _payload(self, path, document, *, source_path=None):
        envelope = explicit_envelope(document, producer=self.producer, format=self.format, metadata=self.metadata)
        if envelope is not None:
            return envelope
        from .weave_import import is_call
        if is_call(document):
            raise InputError('A Weave call is not a rollout snapshot. Import the calls export with Import files or rilldex import.')
        relative = path.relative_to(self.root).as_posix()
        fmt = self.format
        if fmt == 'auto' and all(k in document for k in ('input', 'output', 'step')):
            fmt = detect(document)
        payload = {'producer': self.producer, 'rollout_id': relative, 'document': document, 'format': fmt,
                   'metadata': {**self.metadata, 'source_snapshot_path': relative}, 'state': self.snapshot_state}
        # A one-off final import can declare completion after live collection.
        # Restarting its old default must not downgrade this identical source.
        # A changed document still uses the declared default; explicit envelopes
        # always control their own state and never use this inference.
        if self.snapshot_state == 'in_progress':
            latest = self.store.latest_revision(self.producer, relative)
            if latest and latest['state'] == 'complete':
                completed = {**payload, 'state': 'complete'}
                if latest['metadata'].get('watch_fingerprint') == digest(completed):
                    payload = completed
        return payload

    def _snapshot(self, path, document, *, source_path=None):
        if 'document' not in document:
            return super()._snapshot(path, document, source_path=source_path)
        payload = self._payload(path, document)
        for read_path, signature in self._read_set.items():
            if self._signature(read_path) != signature:
                raise InputError('Producer files changed during collection; retrying on the next poll')
        receipt = self.store.ingest(payload)
        return {'path': path.relative_to(self.root).as_posix(),
                'status': 'ingested' if receipt['received'] else 'unchanged', 'state': payload['state'], **receipt}
