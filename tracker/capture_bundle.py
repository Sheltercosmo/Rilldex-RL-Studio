"""Offline transport for the same packets used by Outbox HTTP delivery.

Bundles are copies of outstanding payloads, not acknowledgments or workspace
backups. Export holds a SQLite read snapshot; import reuses normal idempotency.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

from .schema import InputError, digest, dumps

VERSION = 'jev-capture-bundle/1'
MAX_RECORDS = 50000
MAX_PACKET = 20 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
PACKETS = ('training_records', 'training_recipes', 'continuation_studies', 'execution_records', 'generation_cohorts', 'trainer_telemetry', 'run_records')


def kind(payload):
    if not isinstance(payload, dict):
        raise InputError('Capture packet must be an object')
    found = [key for key in PACKETS if key in payload]
    if len(found) > 1 or found and 'document' in payload:
        raise InputError('Capture packet mixes transport types')
    return found[0] if found else 'rollout'


def validate(payload, producer):
    packet_kind = kind(payload)
    if packet_kind == 'rollout':
        from .ingest_contract import normalize_snapshot
        if payload.get('producer') != producer:
            raise InputError('Capture producer does not match manifest')
        normalize_snapshot(payload)
    else:
        from importlib import import_module
        module = 'training_lineage' if packet_kind == 'training_records' else packet_kind
        packet = payload[packet_kind]
        if not isinstance(packet, dict) or packet.get('producer') != producer:
            raise InputError('Capture producer does not match manifest')
        import_module('.' + module, __package__).validate(packet)
    return packet_kind


def export(outbox, destination):
    source, target = Path(outbox).expanduser().resolve(), Path(destination).expanduser()
    if not source.is_file():
        raise InputError('Outbox does not exist; no empty outbox was created')
    entries, total = [], 0
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        identity = db.execute('SELECT producer,outbox_id FROM identity').fetchone()
        if not identity:
            raise InputError('Not an initialized training outbox')
        sent = db.execute("SELECT count(*) FROM queue WHERE state='sent'").fetchone()[0]
        # Exclusive creation protects earlier exports and the source itself.
        with target.open('xb') as stream:
            try:
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for row in db.execute("SELECT id,payload FROM queue WHERE state!='sent' ORDER BY id"):
                        raw = row['payload'].encode('utf-8')
                        total += len(raw)
                        if len(entries) >= MAX_RECORDS or len(raw) > MAX_PACKET or total > MAX_TOTAL:
                            raise InputError('Capture exceeds bundle limits: 50,000 packets / 2 GiB / 20 MiB per packet')
                        payload = json.loads(raw)
                        packet_kind = validate(payload, identity['producer'])
                        name = f'packets/{len(entries):06d}.json'
                        archive.writestr(name, raw)
                        entries.append(dict(path=name, sha256=hashlib.sha256(raw).hexdigest(),
                                            bytes=len(raw), kind=packet_kind, queued_id=row['id']))
                    manifest = dict(schema=VERSION, producer=identity['producer'], outbox_id=identity['outbox_id'],
                                    created_at=datetime.now(timezone.utc).isoformat(), entries=entries,
                                    previously_delivered=sent)
                    archive.writestr('manifest.json', dumps(manifest))
            except BaseException:
                stream.close()
                target.unlink(missing_ok=True)
                raise
    return {**summary(manifest), 'path': str(target.resolve()), 'outbox_changed': False}


def summary(manifest):
    return {'schema': VERSION, 'producer': manifest['producer'], 'packets': len(manifest['entries']),
            'kinds': dict(Counter(e['kind'] for e in manifest['entries'])),
            'previously_delivered': manifest.get('previously_delivered', 0),
            'note': 'Pending and blocked packets only. Export does not clear the outbox; return import receipts to acknowledge delivery. Previously delivered packets are not included; import into their receiving workspace.'}


def _manifest(archive):
    infos = archive.infolist()
    names = [i.filename for i in infos]
    if len(names) != len(set(names)) or len(names) > MAX_RECORDS + 1 or 'manifest.json' not in names:
        raise InputError('Invalid capture bundle member list')
    if archive.getinfo('manifest.json').file_size > 16 * 1024 * 1024:
        raise InputError('Capture manifest exceeds size limit')
    manifest = json.loads(archive.read('manifest.json'))
    if not isinstance(manifest, dict) or manifest.get('schema') != VERSION:
        raise InputError('Unsupported capture bundle schema')
    entries = manifest.get('entries')
    producer = manifest.get('producer')
    if not isinstance(entries, list) or not isinstance(producer, str) or not producer.strip() or len(producer) > 240 or not isinstance(manifest.get('outbox_id'), str) or not manifest['outbox_id']:
        raise InputError('Invalid capture manifest')
    expected = {'manifest.json'}
    total, ids = 0, set()
    for index, entry in enumerate(entries):
        name = f'packets/{index:06d}.json'
        if not isinstance(entry, dict) or entry.get('path') != name or name not in names:
            raise InputError('Capture packet order or path is invalid')
        queued_id = entry.get('queued_id')
        if type(queued_id) is not int or queued_id < 1 or queued_id in ids:
            raise InputError('Capture queue identity is invalid or repeated')
        ids.add(queued_id)
        info = archive.getinfo(name)
        total += info.file_size
        if info.file_size > MAX_PACKET or info.file_size != entry.get('bytes') or total > MAX_TOTAL:
            raise InputError('Capture packet size exceeds limits or differs from manifest')
        expected.add(name)
    if set(names) != expected:
        raise InputError('Unexpected capture bundle members')
    return manifest


def _payload(archive, entry, producer):
    raw = archive.read(entry['path'])
    if hashlib.sha256(raw).hexdigest() != entry.get('sha256'):
        raise InputError('Capture packet checksum does not match manifest')
    value = json.loads(raw)
    if validate(value, producer) != entry.get('kind'):
        raise InputError('Capture packet type does not match manifest')
    return value


def _open(source):
    return zipfile.ZipFile(source, 'r')


def inspect(source):
    try:
        with _open(source) as archive:
            manifest = _manifest(archive)
            for entry in manifest['entries']:
                _payload(archive, entry, manifest['producer'])
            return {**summary(manifest), 'validated': True}
    except (zipfile.BadZipFile, ValueError, KeyError, UnicodeError, RuntimeError) as exc:
        raise InputError('Invalid capture bundle: ' + str(exc)) from exc


def receive(store, source, *, with_receipts=False):
    # Validate every packet before writing. Re-read from the same open archive;
    # do not extract paths or load an unbounded batch into memory.
    try:
        with _open(source) as archive:
            manifest = _manifest(archive)
            for entry in manifest['entries']:
                _payload(archive, entry, manifest['producer'])
            accepted, reused, errors, blocked, acknowledgments = 0, 0, [], set(), []
            for entry in manifest['entries']:
                payload = _payload(archive, entry, manifest['producer'])
                key = payload.get('rollout_id') if entry['kind'] == 'rollout' else entry['path']
                if key in blocked:
                    errors.append({'packet': entry['path'], 'error': 'An earlier revision of this rollout failed'})
                    continue
                try:
                    if entry['kind'] == 'rollout':
                        result = store.ingest(payload)
                        changed = result['received']
                    else:
                        from importlib import import_module
                        module = 'training_lineage' if entry['kind'] == 'training_records' else entry['kind']
                        result = import_module('.' + module, __package__).receive(store, payload[entry['kind']])
                        changed = bool(result['inserted'])
                    accepted += int(changed)
                    reused += int(not changed)
                    if with_receipts:
                        acknowledgments.append({'outbox_id': manifest['outbox_id'], 'producer': manifest['producer'],
                                                'queued_id': entry['queued_id'], 'payload_sha256': entry['sha256'],
                                                'receipt': result})
                except ValueError as exc:
                    blocked.add(key)
                    errors.append({'packet': entry['path'], 'error': str(exc)})
            result = {**summary(manifest), 'accepted': accepted, 'already_present': reused,
                    'failed': len(errors), 'errors': errors[:30], 'complete': not errors,
                    'note': 'Each packet commits separately. Retrying reuses accepted identities; no model calls. Keep the source outbox and bundle until transfer is verified.'}
            if with_receipts:
                result['acknowledgments'] = acknowledgments
            return result
    except (zipfile.BadZipFile, KeyError, UnicodeError, RuntimeError) as exc:
        raise InputError('Invalid capture bundle: ' + str(exc)) from exc


def acknowledge(outbox, receipt_file):
    """Explicitly return receiving-workspace receipts to their original outbox.

    Verify all identities/hashes/receipt IDs before clearing any packet. The
    caller chooses the receipt file; this is a local handoff, not remote auth.
    """
    source = Path(outbox).expanduser().resolve()
    path = Path(receipt_file).expanduser()
    if not source.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise InputError('Use an existing outbox and a receipt file up to 32 MiB')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema') != 'jev-capture-receipts/1' or not isinstance(value.get('acknowledgments'), list):
        raise InputError('Unsupported capture receipt file')
    acknowledgments = value['acknowledgments']
    if len(acknowledgments) > MAX_RECORDS:
        raise InputError('Too many capture receipts')
    import time
    with closing(sqlite3.connect(source.as_uri() + '?mode=rw', uri=True)) as db:
        db.row_factory = sqlite3.Row
        with db:
            db.execute('BEGIN IMMEDIATE')
            identity = db.execute('SELECT producer,outbox_id FROM identity').fetchone()
            updates, seen = [], set()
            for ack in acknowledgments:
                if not isinstance(ack, dict) or not identity or ack.get('producer') != identity['producer'] or ack.get('outbox_id') != identity['outbox_id']:
                    raise InputError('Receipts belong to a different outbox; nothing was cleared')
                queued_id = ack.get('queued_id')
                if type(queued_id) is not int or queued_id in seen:
                    raise InputError('Invalid or repeated queue identity in receipt file')
                seen.add(queued_id)
                row = db.execute('SELECT * FROM queue WHERE id=?', (queued_id,)).fetchone()
                if row is None:
                    raise InputError('Receipt references an unknown queued packet')
                receipt = ack.get('receipt')
                if not isinstance(receipt, dict) or receipt.get('revision') != row['revision']:
                    raise InputError('Receipt revision does not match queued packet')
                if row['state'] == 'sent':
                    prior = json.loads(row['receipt'])
                    if prior['id'] != receipt.get('id'):
                        raise InputError('Receipt identity differs from previous delivery')
                    continue
                raw = row['payload'].encode('utf-8')
                if hashlib.sha256(raw).hexdigest() != ack.get('payload_sha256'):
                    raise InputError('Receipt content differs from queued packet')
                payload = json.loads(raw); packet_kind = kind(payload)
                if packet_kind == 'rollout':
                    from .ingest_contract import normalize_snapshot
                    expected = normalize_snapshot(payload)['id']
                else:
                    prefix = {'training_records':'training-packet-', 'training_recipes':'recipe-packet-',
                              'continuation_studies':'continuation-packet-', 'execution_records':'execution-packet-',
                              'generation_cohorts':'cohort-packet-', 'trainer_telemetry':'telemetry-packet-', 'run_records':'run-packet-'}[packet_kind]
                    expected = prefix + digest(payload[packet_kind])
                if receipt.get('id') != expected:
                    raise InputError('Receipt acknowledges different data')
                updates.append((dumps(receipt), time.time(), queued_id))
            db.executemany("UPDATE queue SET state='sent',receipt=?,sent=?,error=NULL,payload='',bytes=0 WHERE id=?", updates)
    return {'acknowledged': len(updates), 'already_acknowledged': len(seen) - len(updates),
            'note': 'Only packets with matching receipts were cleared. Keep the receiving workspace or its backup.'}
