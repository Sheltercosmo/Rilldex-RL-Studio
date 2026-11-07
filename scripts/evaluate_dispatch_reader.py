"""Replay bounded source-reading trials; report retrieval, not verdict accuracy."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker.dispatch_reading import Reader, VERSION
from tracker.schema import InputError, digest, dumps
from scripts.evaluate_public_episodes import load_evidence

FIXTURE = Path(__file__).resolve().parents[1]/'tests/fixtures/dispatch_reader_evidence.json'


def replay(evidence=None):
    evidence = evidence if evidence is not None else json.loads(FIXTURE.read_text(encoding='utf8'))
    public = {row['id']: row['document'] for row in load_evidence()['sources']}
    rows = []
    for case in evidence['cases']:
        source = case['source']
        if source['kind'] == 'reader_case':
            # Reuse the immutable source from the earlier trial, not its turns.
            shared = json.loads(FIXTURE.read_text(encoding='utf8'))
            source = next(c['source'] for c in shared['cases'] if c['id'] == source['id'])
        if source['kind'] == 'repository_fixture':
            path = FIXTURE.parent / source['path']
            path.resolve().relative_to(FIXTURE.parent.resolve())
            run = normalize(json.loads(path.read_text(encoding='utf8')))[0]
        else:
            run = normalize(public[source['id']])[0] if source['kind'] == 'public_episode' else source['run']
        if digest(run) != case['source_hash']: raise InputError('Trial source changed')
        # These immutable trials used exact quotes only. Replay their original
        # comparisons before separately evaluating newer record-context logic.
        settings = {'record_context': False, 'protocol': VERSION, **case['settings']}
        reader = Reader(run, case['event_id'], **settings); sizes = []
        for turn in case['turns']:
            request = reader.request()
            if digest(request) != turn['request_hash']: raise InputError('Recorded source-reading request changed')
            sizes.append(len(dumps(request).encode('utf8')))
            reader.consume(turn['response'])
        if reader.result is None: raise InputError('Recorded reader did not finish')
        hashes = [digest(req) for req in reader.result['requests']]
        if hashes != case['comparison_hashes']: raise InputError('Bound comparison changed')
        rows.append({'id': case['id'], 'status': reader.result['status'], 'rounds': reader.round,
                     'comparisons': len(hashes), 'max_request_bytes': max(sizes),
                     'total_request_bytes': sum(sizes), 'request_byte_limit': reader.max_bytes,
                     'coverage': reader.progress(), 'comparison_hashes': hashes,
                     'rejected_attempts': len(case.get('rejected_attempts', []))})
    return {'schema': 'dispatch-reader-replay/1', 'cases': rows, 'interpretation': evidence['interpretation'],
            'generation': evidence.get('generation'),
            'reference_review': evidence.get('reference_review'),
            'evidence_assessment': evidence.get('evidence_assessment')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/dispatch-reader.json')
    parser.add_argument('--evidence', type=Path, default=FIXTURE)
    args = parser.parse_args(); report = replay(json.loads(args.evidence.read_text(encoding='utf8'))); path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(dumps(report), encoding='utf8')
    print(dumps([{k: v for k, v in row.items() if k not in {'coverage', 'comparison_hashes'}} for row in report['cases']]))
