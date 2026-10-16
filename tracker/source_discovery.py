"""Read-only, bounded evidence for selecting a collector. Never infer completion.

Discovery suggests a fixed route. It does not switch live collectors, invent
producer identities or advance ingestion cursors. Actual collection revalidates.
"""
from collections import Counter, defaultdict
import fnmatch
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

from .adapters import normalize, detect
from .ingest_contract import normalize_snapshot
from .schema import InputError
from .watch import DirectoryWatcher

MAX_ENTRIES = 5000
FILES_PER_KIND = 6
MAX_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
SUFFIXES = ('.json', '.jsonl', '.traj')
from .input_catalog import catalog as input_catalog
LABELS = {m['id']: m['label'] for m in input_catalog()['modes']}
LABELS['import'] = 'Completed multi-rollout bundle'


def _walk(root):
    paths, visited, links, limited = [], 0, 0, False
    def scan(directory, depth=0):
        nonlocal visited, links, limited
        if depth > 32:
            limited = True
            return
        with os.scandir(directory) as entries:
            for entry in entries:
                if visited >= MAX_ENTRIES:
                    limited = True
                    return
                visited += 1
                if entry.is_symlink():
                    links += 1
                    continue
                path = Path(entry.path)
                if not path.resolve().is_relative_to(root):
                    links += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    scan(path, depth + 1)
                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in SUFFIXES:
                    paths.append(path)
    scan(root)
    return sorted(paths), {'entries_seen': visited, 'skipped_links': links, 'listing_limited': limited}


def _kind(path):
    if path.suffix == '.jsonl': return 'exports'
    if path.suffix == '.traj' or path.name == 'trajectory.json' or path.name.endswith('.trajectory.json'): return 'native'
    return 'snapshots'


def _decode(doc, path):
    if not isinstance(doc, dict):
        raise InputError('The record is not a trajectory object')
    producer, experiment = None, None
    if 'document' in doc:
        if path.suffix == '.traj':
            raise InputError('Explicit rollout envelopes require .json or .jsonl, not a native .traj filename')
        run = normalize_snapshot(doc)
        producer = doc['producer']
        experiment = run['metadata'].get('experiment')
        return ('exports' if path.suffix == '.jsonl' else 'snapshots'), [run], producer, experiment
    # Match the existing export/snapshot readers' special case for verl rows.
    fmt = detect(doc) if all(k in doc for k in ('input','output','step')) else 'auto'
    if path.suffix == '.traj' and isinstance(doc.get('attempts'), list):
        if not doc['attempts']:
            raise InputError('Retry wrapper has no recorded attempts yet')
        run = normalize(doc['attempts'][0], 'swe-agent')[0]
        return 'native', [run], None, run['metadata'].get('experiment')
    runs = normalize(doc, fmt)
    if len(runs) > 1 or doc.get('tracker_bundle'):
        return 'import', runs, None, None
    if path.suffix == '.jsonl':
        route = 'exports'
    elif _kind(path) == 'native' and runs[0]['adapter'] in {'harbor', 'swe-agent'}:
        route = 'native'
    elif path.suffix == '.traj':
        raise InputError('This .traj content is not supported by the native directory reader')
    else:
        route = 'snapshots'
    return route, runs, producer, runs[0]['metadata'].get('experiment')


def _pattern(route, good, paths, bad, inspected):
    if route == 'native':
        return None, any(_kind(p) == 'native' for p in bad)
    if route == 'import':
        return None, True
    suffix = '.jsonl' if route == 'exports' else '.json'
    pattern = '*' + suffix
    unwanted = [p for p in paths if p in inspected and p.suffix == suffix and p not in good]
    # Suggest from observed separation, without claiming unseen files decoded.
    if unwanted:
        names = sorted({p.name for p in good})
        if len(names) < 2:
            exact = names[0]
            if not any(c in exact for c in '*?[') and not any(p.name == exact for p in unwanted):
                return exact, False
            return None, True
        prefix = re.sub(r'\d+$', '', os.path.commonprefix(names))
        if not prefix or any(c in prefix for c in '*?['):
            return None, True
        pattern = prefix + '*' + suffix
        if any(fnmatch.fnmatchcase(p.name, pattern) for p in unwanted):
            return None, True
    return pattern, False


def discover(root):
    if not isinstance(root, str) or not root.strip():
        raise InputError('Choose an output directory on the collector host or an S3/GCS prefix')
    if '://' in root:
        from .cloud_watch import CloudWatcher, source
        source(root)
        with tempfile.TemporaryDirectory(prefix='jev-discover-') as tmp:
            local = SimpleNamespace(root=Path(tmp), max_files=MAX_ENTRIES, source_suffixes=SUFFIXES,
                                    _within=DirectoryWatcher._within)
            remote = CloudWatcher(local, root).mirror(limit=FILES_PER_KIND * 3, byte_budget=MAX_BYTES)
            report = discover(tmp)
            report.update(root=root, cloud=remote)
            if remote['pending'] or remote['errors']:
                report['incomplete'] = True
                report['recommended_route'] = None
            return report
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise InputError('Output directory does not exist on this collector. For a remote job, run discovery on that host or use a mounted/synced directory.')
    paths, scan = _walk(directory)
    buckets = defaultdict(list)
    for path in paths: buckets[_kind(path)].append(path)
    selected = [p for group in buckets.values() for p in group[:FILES_PER_KIND]]
    samples, routes, remaining = [], {}, MAX_BYTES
    bad = set()
    def record(doc, path, row):
        route, runs, producer, experiment = _decode(doc, path)
        if path.suffix == '.jsonl' and route == 'import':
            raise InputError('A JSONL line contains multiple rollouts; use a supported one-rollout export')
        group = routes.setdefault(route, {})
        item = group.setdefault(path, {'formats': Counter(), 'producers': set(), 'experiments': set(), 'records': 0})
        item['records'] += len(runs)
        item['formats'].update(r['adapter'] for r in runs)
        if producer: item['producers'].add(producer)
        if experiment: item['experiments'].add(experiment)
        samples.append({'path': path.relative_to(directory).as_posix(), 'line': row, 'status': 'decoded',
                        'route': route, 'formats': sorted({r['adapter'] for r in runs})})
    for path in selected:
        relative = path.relative_to(directory).as_posix()
        try:
            if path.suffix not in SUFFIXES:
                raise InputError('Collector filename patterns are case-sensitive; use a lowercase .json, .jsonl or .traj extension')
            before = path.stat()
            if not path.resolve().is_relative_to(directory): raise InputError('Source moved outside the selected directory')
            if path.suffix != '.jsonl' and before.st_size > min(MAX_FILE_BYTES, remaining):
                samples.append({'path': relative, 'status': 'limited', 'detail': 'File exceeds the remaining discovery byte budget'})
                bad.add(path); continue
            with path.open('rb') as stream:
                if path.suffix == '.jsonl':
                    decoded = 0
                    for line in range(1, 21):
                        raw = stream.readline(min(MAX_FILE_BYTES, remaining) + 1)
                        if not raw:
                            if not decoded: samples.append({'path': relative, 'status': 'waiting', 'detail': 'No committed records yet'})
                            break
                        if len(raw) > min(MAX_FILE_BYTES, remaining):
                            samples.append({'path': relative, 'status': 'limited', 'detail': 'Record exceeds the remaining discovery byte budget'})
                            bad.add(path); break
                        remaining -= len(raw)
                        if not raw.endswith(b'\n'):
                            samples.append({'path': relative, 'line': line, 'status': 'waiting', 'detail': 'Last record is not newline-committed yet'})
                            break
                        text = raw.decode('utf-8-sig' if line == 1 else 'utf-8').strip()
                        if text:
                            record(json.loads(text), path, line); decoded += 1
                            if decoded == 2: break
                    else:
                        samples.append({'path': relative, 'status': 'limited', 'detail': 'No record decoded within the first 20 lines'})
                        bad.add(path)
                else:
                    raw = stream.read(min(MAX_FILE_BYTES, remaining) + 1)
                    if len(raw) > min(MAX_FILE_BYTES, remaining): raise InputError('File grew beyond the discovery byte budget')
                    remaining -= len(raw)
                    record(json.loads(raw.decode('utf-8-sig')), path, None)
            after = path.stat()
            if after.st_size < before.st_size or (path.suffix != '.jsonl' and (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns)):
                raise InputError('File changed during discovery; check again')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            bad.add(path)
            samples.append({'path': relative, 'status': 'unresolved', 'detail': str(exc)})
    # A file with a malformed later sampled row cannot establish a safe route.
    options = []
    for route, group in sorted(routes.items()):
        good = set(group) - bad
        if not good: continue
        inspected = {directory / s['path'] for s in samples}
        pattern, needs_filter = _pattern(route, good, paths, bad, inspected)
        formats, producer_set, experiments, records = Counter(), set(), set(), 0
        for path in good:
            formats.update(group[path]['formats']); producer_set.update(group[path]['producers'])
            experiments.update(group[path]['experiments']); records += group[path]['records']
        producers = sorted(producer_set)
        options.append({'mode': route, 'label': LABELS[route], 'format': 'auto', 'pattern': pattern,
                        'files_decoded': len(good), 'records_decoded': records,
                        'formats': dict(formats), 'examples': [p.relative_to(directory).as_posix() for p in sorted(good)[:5]],
                        'producers': producers, 'experiments': sorted(experiments),
                        'needs_filter': needs_filter, 'applicable': route != 'import' and not needs_filter and len(producers) <= 1})
    incomplete = scan['listing_limited'] or len(selected) < len(paths) or any(s['status'] == 'limited' for s in samples)
    recommended = options[0]['mode'] if len(options) == 1 and options[0]['applicable'] and not scan['listing_limited'] else None
    status = 'recognized' if recommended else 'mixed' if len(options) > 1 else 'review' if options else 'empty' if not paths and not scan['listing_limited'] else 'unresolved'
    return {'schema': 'source-discovery/1', 'root': str(directory), 'status': status, 'persisted': False,
            'candidate_files': len(paths), 'sampled_files': len(selected), 'bytes_read': MAX_BYTES - remaining,
            **scan, 'incomplete': incomplete, 'recommended_route': recommended, 'routes': options,
            'samples': samples, 'limits': {'entries': MAX_ENTRIES, 'files_per_kind': FILES_PER_KIND, 'bytes': MAX_BYTES},
            'note': 'Bounded sample: at most 6 files per layout and 2 JSONL records in the first 20 lines. No data imported, cursor advanced, completion inferred or model called. Actual collection revalidates every record.'}
