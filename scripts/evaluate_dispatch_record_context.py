"""Compare exact-quote and enclosing-record evidence on the saved reader trials."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_dispatch_reader import FIXTURE
from scripts.evaluate_public_episodes import load_evidence
from tracker.adapters import normalize
from tracker.dispatch_context import expand
from tracker.dispatch_reading import Reader, VERSION
from tracker.schema import InputError, digest, dumps


def compare():
    evidence = json.loads(FIXTURE.read_text(encoding='utf8'))
    sources = {s['id']: s['document'] for s in load_evidence()['sources']}
    pairs = []
    for case in evidence['cases']:
        source = case['source']
        run = normalize(sources[source['id']])[0] if source['kind'] == 'public_episode' else source['run']
        if digest(run) != case['source_hash']: raise InputError('Trial source changed')
        reader = Reader(run, case['event_id'], record_context=False, protocol=VERSION, **case['settings'])
        for turn in case['turns']:
            if digest(reader.request()) != turn['request_hash']: raise InputError('Trial reading changed')
            reader.advance(turn['response'])
        for index, original in enumerate(reader.result['requests']):
            if digest(original) != case['comparison_hashes'][index]: raise InputError('Original comparison changed')
            expanded = expand(run, original)
            context = expanded['state']['source_context']
            pairs.append({'case_id': case['id'], 'comparison_index': index,
                'source_hash': case['source_hash'], 'original_request_hash': digest(original),
                'expanded_request_hash': digest(expanded),
                'original_bytes': len(dumps(original).encode('utf8')),
                'expanded_bytes': len(dumps(expanded).encode('utf8')),
                'context_event_ids': [r['id'] for r in context['records']],
                'omitted_event_ids': [r['event_id'] for r in context['not_included']]})
    return {'schema': 'dispatch-record-context-comparison/1', 'source_fixture_hash': digest(evidence),
            'comparisons': pairs,
            'interpretation': 'Records recovered from exact sources. Added context is not proof of correct interpretation, complete retrieval or detector accuracy.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('outputs/dispatch-record-context.json'))
    args = parser.parse_args(); report = compare()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(report), encoding='utf8')
    print(dumps({'comparisons': len(report['comparisons']),
                 'max_request_bytes': max(r['expanded_bytes'] for r in report['comparisons'])}))
