"""Shared source validation for delivery and read-only connection checks."""
from .adapters import normalize
from .schema import InputError


def explicit_envelope(document, *, producer, format, metadata):
    if not isinstance(document, dict):
        raise InputError('Each source record must be an object')
    if 'document' not in document:
        return None
    allowed = {'producer', 'rollout_id', 'revision', 'state', 'document', 'format', 'metadata', 'sources'}
    if set(document) - allowed:
        raise InputError('Unknown fields in ingestion envelope')
    if document.get('producer', producer) != producer:
        raise InputError('Envelope producer differs from this connection')
    if not isinstance(document.get('metadata', {}), dict):
        raise InputError('Envelope metadata must be an object')
    return {**document, 'producer': producer, 'format': document.get('format', format),
            'metadata': {**metadata, **document.get('metadata', {})}}


def normalize_snapshot(payload):
    if not isinstance(payload, dict):
        raise InputError('Supply an ingestion envelope object')
    producer, rollout_id = payload.get('producer'), payload.get('rollout_id')
    for name, value in (('producer', producer), ('rollout_id', rollout_id)):
        if not isinstance(value, str) or not value.strip() or len(value) > 240:
            raise InputError(f'{name} must contain 1–240 characters')
    revision = payload.get('revision')
    if type(revision) is not int or revision < 0:
        raise InputError('revision must be a nonnegative integer starting at zero')
    if payload.get('state') not in {'in_progress', 'complete', 'failed'}:
        raise InputError('state must be in_progress, complete or failed; it does not establish task success')
    meta = payload.get('metadata', {})
    if not isinstance(meta, dict):
        raise InputError('metadata must be an object')
    runs = normalize(payload.get('document'), payload.get('format', 'auto'),
                     {**meta, 'producer': producer, 'logical_rollout_id': rollout_id}, payload.get('sources'))
    if len(runs) != 1:
        raise InputError('Each ingestion revision must contain exactly one rollout document')
    return runs[0]
