"""Build source-bound work-state evidence beside a producer's tool loop.

No command execution, inferred intent, automatic success judgment or dependency
discovery. The caller supplies the actual criterion, result and input scope.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from .schema import InputError, digest


def source_ref(pointer, *, kind=None, trajectory_id=None):
    ref = {'source_pointer': pointer}
    if kind is not None: ref['kind'] = kind
    if trajectory_id is not None: ref['trajectory_id'] = trajectory_id
    return _reference(ref)


def call_ref(call_id, *, result=False, trajectory_id=None):
    """Exact adapter call identity; use source_ref when native IDs are namespaced."""
    ref = {'call_id': call_id, 'kind': 'feedback' if result else 'action'}
    if trajectory_id is not None: ref['trajectory_id'] = trajectory_id
    return _reference(ref)


def _text(value): return isinstance(value, str) and bool(value.strip())


def _reference(ref):
    if (not isinstance(ref, dict) or set(ref) - {'source_pointer', 'call_id', 'kind', 'trajectory_id'}
            or sum(key in ref for key in ('source_pointer', 'call_id')) != 1
            or any(not _text(v) for v in ref.values())
            or ('kind' in ref and ref['kind'] not in {'action', 'feedback', 'message', 'instruction', 'context'})):
        raise InputError('Use one source pointer or exact call ID, with optional kind and trajectory ID')
    return deepcopy(ref)


def object_version(value):
    """Version a JSON state value, including null; never retain its contents."""
    return 'json-sha256:' + digest(value)


def file_versions(root, paths, *, max_bytes=100_000_000):
    """Hash explicitly named regular files inside root, or record known absence.

    Reads are sequential, not an atomic filesystem snapshot or a stability
    guarantee. No file content or absolute path is added to the capture.
    """
    root = Path(root).resolve()
    if not root.is_dir() or not isinstance(paths, (list, tuple)) or not paths:
        raise InputError('File capture needs a directory and explicit relative file paths')
    if type(max_bytes) is not int or max_bytes < 0: raise InputError('Invalid file capture byte limit')
    versions = {}; total = 0
    for name in paths:
        if not _text(name) or Path(name).is_absolute() or '..' in Path(name).parts:
            raise InputError('File capture paths must stay inside the chosen directory')
        target = (root / name).resolve()
        if not target.is_relative_to(root): raise InputError('File capture resolves outside the chosen directory')
        key = Path(name).as_posix()
        if key in versions: raise InputError('Duplicate file capture path')
        if not target.exists():
            versions[key] = 'absent'; continue
        if not target.is_file(): raise InputError('Capture supports regular files only')
        h = hashlib.sha256()
        with target.open('rb') as stream:
            while block := stream.read(min(1_048_576, max_bytes - total + 1)):
                total += len(block)
                if total > max_bytes: raise InputError('File capture byte limit exceeded')
                h.update(block)
        versions[key] = 'sha256:' + h.hexdigest()
    return versions


class WorkStateRecorder:
    def __init__(self, *, environment):
        if not _text(environment): raise InputError('Supply the recorded environment identity/version')
        self.environment = environment
        self.snapshots = {}; self.checks = []; self.edits = []; self.deliveries = []

    def snapshot(self, at, objects, *, environment=None):
        env = self.environment if environment is None else environment
        if not _text(env) or not isinstance(objects, dict) or not objects or any(not _text(k) or not _text(v) for k, v in objects.items()):
            raise InputError('A snapshot needs explicit object-version strings and environment identity')
        row = {'at': _reference(at), 'environment': env, 'objects': deepcopy(objects)}
        sid = 'snapshot-' + digest(row)
        self.snapshots.setdefault(sid, {'id': sid, **row})
        return sid

    def _snapshot(self, sid):
        if not isinstance(sid, str) or sid not in self.snapshots: raise InputError('Unknown recorder snapshot')
        return sid

    def check(self, action, result, *, snapshot, criterion_id, criterion_version,
              required_objects, outcome, state_stable=None):
        sid = self._snapshot(snapshot)
        if (not _text(criterion_id) or not _text(criterion_version) or outcome not in {'passed', 'failed', 'unknown'}
                or state_stable is not None and type(state_stable) is not bool):
            raise InputError('Check needs a versioned criterion, explicit outcome and optional boolean stability assertion')
        if (not isinstance(required_objects, (list, tuple)) or not required_objects
                or any(not isinstance(k, str) for k in required_objects)
                or len(set(required_objects)) != len(required_objects)
                or any(k not in self.snapshots[sid]['objects'] for k in required_objects)):
            raise InputError('Check input scope must name captured objects exactly once')
        self.checks.append({'action': _reference(action), 'result_ref': _reference(result),
                            'snapshot_id': sid, 'binding': 'at_dispatch', 'criterion_id': criterion_id,
                            'criterion_version': criterion_version, 'required_objects': list(required_objects),
                            'result': outcome, 'state_stable': state_stable})

    def edit(self, action, result, *, before, after):
        self.edits.append({'action': _reference(action), 'result_ref': _reference(result),
                           'before_snapshot_id': self._snapshot(before), 'after_snapshot_id': self._snapshot(after)})

    def deliver(self, at, *, snapshot, requirements):
        if not isinstance(requirements, list): raise InputError('Supply explicit delivery requirements')
        for row in requirements:
            if (not isinstance(row, dict) or set(row) != {'criterion_id', 'criterion_version', 'basis'}
                    or not _text(row['criterion_id']) or not _text(row['criterion_version'])
                    or row['basis'] not in {'task', 'research_policy'}):
                raise InputError('Delivery requirements need criterion ID/version and task or research_policy basis')
        self.deliveries.append({'at': _reference(at), 'snapshot_id': self._snapshot(snapshot),
                                'requirements': deepcopy(requirements)})

    def attach(self, document, *, format='auto', metadata=None):
        """Resolve references against one actual source, then validate the result.

        Appending state does not rewrite messages or event ordering. The new raw
        document (including this evidence) intentionally has a new source hash.
        Existing state evidence is never overwritten. Missing/ambiguous/future
        references fail; no partial attachment is returned.
        """
        from .adapters import normalize
        from .work_state import CAPTURE
        if not isinstance(document, dict): raise InputError('Attach state to one trajectory document')
        if 'work_state' in document or 'work_state' in (document.get('extra') or {}):
            raise InputError('Source already has work-state evidence; do not overwrite it')
        runs = normalize(document, format, metadata)
        if len(runs) != 1: raise InputError('Attach state to one rollout, not a result collection')
        run = runs[0]
        def resolve(ref, expected=None):
            ref = _reference(ref)
            if expected and ref.get('kind', expected) != expected: raise InputError('Reference kind differs from its capture role')
            matches = []
            for e in run['events']:
                if e.get('copied_context') or expected and e['kind'] != expected: continue
                if 'kind' in ref and ref['kind'] != e['kind']: continue
                if 'trajectory_id' in ref and ref['trajectory_id'] != e['trajectory_id']: continue
                if 'source_pointer' in ref and ref['source_pointer'] != e['source_pointer']: continue
                if 'call_id' in ref and e.get('source_call_id' if e['kind'] == 'feedback' else 'call_id') != ref['call_id']: continue
                matches.append(e)
            if len(matches) != 1: raise InputError('State reference is missing or ambiguous in this source')
            if expected == 'action' and matches[0]['actor'] != 'agent': raise InputError('Agent check/edit capture cannot use another actor’s action')
            return matches[0]['id']
        capture = {'schema': CAPTURE,
                   'snapshots': [{k: deepcopy(v) for k, v in row.items() if k != 'at'} |
                                 {'event_id': resolve(row['at'])} for row in self.snapshots.values()],
                   'checks': [{k: deepcopy(v) for k, v in row.items() if k not in {'action', 'result_ref'}} |
                              {'action_id': resolve(row['action'], 'action'), 'result_event_id': resolve(row['result_ref'], 'feedback')} for row in self.checks],
                   'edits': [{k: deepcopy(v) for k, v in row.items() if k not in {'action', 'result_ref'}} |
                             {'action_id': resolve(row['action'], 'action'), 'result_event_id': resolve(row['result_ref'], 'feedback')} for row in self.edits],
                   'deliveries': [{k: deepcopy(v) for k, v in row.items() if k != 'at'} |
                                  {'event_id': resolve(row['at'])} for row in self.deliveries]}
        result = deepcopy(document); result['work_state'] = capture
        normalized = normalize(result, format, metadata)
        if normalized[0]['events'] != run['events']: raise InputError('Attaching state unexpectedly changed source events')
        return result
