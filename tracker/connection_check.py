"""Bounded source preflight using the collector's actual decoding contract.

Never ingests, advances a cursor or asks an inference provider. This is a source
sample, not proof that a job is complete or that delivery will remain healthy.
"""
import json

from .ingest_contract import normalize_snapshot
from .import_batch import preflight
from .schema import InputError
from .watch import MAX_FILE_BYTES, ReadBudgetExceeded

FILE_LIMIT = 5
ROWS_PER_FILE = 2
LINE_LIMIT = 20
BYTE_LIMIT = 32 * 1024 * 1024


def check(watcher, paths):
    runs, samples, seen = [], [], set()
    watcher.read_budget = BYTE_LIMIT

    def accept(payload, path, line=None):
        run = normalize_snapshot(payload)
        identity = (payload['producer'], payload['rollout_id'])
        if identity in seen:
            return
        seen.add(identity)
        runs.append(run)
        samples.append({'path': path, 'line': line, 'status': 'valid', 'adapter': run['adapter']})

    is_export = hasattr(watcher, '_envelope')
    for path in paths[:FILE_LIMIT]:
        relative = path.relative_to(watcher.root).as_posix()
        try:
            if is_export:
                count = 0
                with path.open('rb') as stream:
                    before = watcher._signature(path)
                    for line in range(1, LINE_LIMIT + 1):
                        raw = stream.readline(min(MAX_FILE_BYTES, watcher.read_budget) + 1)
                        if not raw:
                            if not count:
                                samples.append({'path': relative, 'status': 'waiting', 'detail': 'No committed records yet'})
                            break
                        if len(raw) > MAX_FILE_BYTES:
                            raise InputError(f'Line {line} exceeds the 20 MiB record limit')
                        if len(raw) > watcher.read_budget:
                            raise ReadBudgetExceeded('Preview byte limit reached; collection can validate the remaining sources')
                        watcher.read_budget -= len(raw)
                        if not raw.endswith(b'\n'):
                            samples.append({'path': relative, 'line': line, 'status': 'waiting',
                                            'detail': 'Waiting for a newline to commit this record'})
                            break
                        text = raw.decode('utf-8-sig' if line == 1 else 'utf-8').strip()
                        if text:
                            try:
                                accept(watcher._envelope(json.loads(text), relative, line), relative, line)
                            except (ValueError, TypeError) as e:
                                raise InputError(f'Line {line}: {e}') from e
                            count += 1
                            if count >= ROWS_PER_FILE:
                                break
                    else:
                        samples.append({'path': relative, 'status': 'limited', 'detail': 'Reached the preview line limit'})
                    # An append does not invalidate already committed lines. Rewrites
                    # are checked by durable prefix validation during collection.
                    after = watcher._signature(path)
                    if before and after and after[0] < before[0]:
                        raise InputError('File was truncated during preview; check again')
            else:
                watcher._read_set = {}
                document, _ = watcher._read(path)
                attempts = document.get('attempts') if path.suffix == '.traj' else None
                if isinstance(attempts, list):
                    if not attempts:
                        raise InputError('No retry attempts recorded yet')
                    child = path.parent / 'attempt_0' / path.name
                    document = watcher._read(child)[0] if child.exists() else attempts[0]
                    if not isinstance(document, dict):
                        raise InputError('Retry attempt must be an object')
                    payload = watcher._payload(child, document,
                                               source_path=None if child.exists() else relative + '#/attempts/0')
                else:
                    payload = watcher._payload(path, document)
                # Only collector-generated snapshots receive an automatic revision.
                if 'document' not in document:
                    payload['revision'] = 0
                for read_path, signature in watcher._read_set.items():
                    if watcher._signature(read_path) != signature:
                        raise InputError('Source changed during preview; check again')
                accept(payload, relative)
        except ReadBudgetExceeded as e:
            samples.append({'path': relative, 'status': 'limited', 'detail': str(e)})
            break
        except (OSError, ValueError, TypeError) as e:
            samples.append({'path': relative, 'status': 'deferred', 'detail': str(e)})
    return {'schema': 'connection-check/1', 'persisted': False, 'checked_files': len({s['path'] for s in samples}),
            'file_limit': FILE_LIMIT, 'rows_per_file': ROWS_PER_FILE, 'samples': samples,
            'coverage': preflight(runs) if runs else None,
            'note': 'Sample only: up to 5 files, 2 JSONL records per file, within the first 20 lines and 32 MiB total. '
                    'No records imported or model calls made. Collection validates every received record, '
                    'including revision order and previously accepted bytes.'}
