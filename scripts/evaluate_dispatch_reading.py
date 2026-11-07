"""Replay focused public-dispatch readings with original and adjudicated references."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.jev import validate_answers
from tracker.schema import InputError, digest, dumps

FIXTURE = Path(__file__).resolve().parents[1]/'tests/fixtures/focused_dispatch_reading_evidence.json'


def evaluate(evidence=None):
    evidence = evidence if evidence is not None else json.loads(FIXTURE.read_text(encoding='utf8'))
    original = {r['id']: r for r in evidence['reference']['rows']}
    adjudicated = {**original, **{r['id']: r for r in evidence['adjudication']['adjudications']}}
    report = {'schema': 'focused-dispatch-reading-report/1', 'phases': {},
              'selection': evidence['selection'], 'interpretation': evidence['interpretation'],
              'excluded_trials': [{k: v for k, v in r.items() if k != 'receipt'} for r in evidence['excluded_trials']],
              'adjudication': deepcopy(evidence['adjudication'])}
    for phase, records in evidence['phases'].items():
        if {r['id'] for r in records} != set(original) or len(records) != len(original):
            raise InputError('Each arm must retain every selected comparison exactly once')
        rows = []
        for record in records:
            receipt = evidence['receipts'][record['request_hash']]
            if digest(receipt['request']) != record['request_hash'] or receipt['request']['model'] != receipt['response']['model']:
                raise InputError('Focused dispatch receipt identity differs')
            reading = validate_answers(receipt['response'], receipt['request'])['alignment']
            rows.append({**record, 'prediction': reading['value'], 'probabilities': reading['probabilities']})
        results = {'rows': rows}
        for name, refs in [('original', original), ('adjudicated', adjudicated)]:
            certain = [r for r in rows if not refs[r['id']]['ambiguous']]
            uncertain = [r for r in rows if refs[r['id']]['ambiguous']]
            results[name] = {'unambiguous': len(certain),
                'unambiguous_matches': sum(r['prediction'] == refs[r['id']]['value'] for r in certain),
                'disagreements': [r['id'] for r in certain if r['prediction'] != refs[r['id']]['value']],
                'ambiguous': len(uncertain),
                'ambiguous_primary_matches': sum(r['prediction'] == refs[r['id']]['value'] for r in uncertain),
                'ambiguous_option_matches': sum(r['prediction'] in [refs[r['id']]['value'], *refs[r['id']]['alternatives']]
                                                for r in uncertain)}
        report['phases'][phase] = results
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/focused-dispatch-reading.json')
    args = parser.parse_args()
    report = evaluate(); path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(report), encoding='utf8')
    print(dumps({arm: {k: v for k, v in result.items() if k != 'rows'} for arm, result in report['phases'].items()}))
