"""Replay or repeat complete public episodes against a blinded model review."""
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker.jev import DEFAULT_MODEL, JevClient, validate_answers
from tracker.schema import InputError, digest, dumps

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/public_episode_reading_evidence.json'
FIELDS = ('mode', 'goal_relation', 'feedback_response')


def load_evidence():
    return json.loads(FIXTURE.read_text(encoding='utf8'))


def requests(evidence, client):
    """Use every selected episode action; references never enter the request."""
    references = {row['id']: row for row in evidence['review']['rows']}
    seen = set()
    for source in evidence['sources']:
        run = normalize(source['document'])[0]
        for action in run['events']:
            if action['kind'] != 'action':
                continue
            case_id = source['id'] + '-' + action['id']
            if case_id in seen or case_id not in references:
                raise InputError('Public episode references do not match its actions')
            seen.add(case_id)
            request = client.request(run, action['id'])
            yield {'id': case_id, 'episode': source['id'], 'run_id': run['id'], 'source_url': source['source_url'],
                   'action_id': action['id'], 'source_hash': digest(run),
                   'request_hash': digest(request), 'request': request}
    if seen != set(references):
        raise InputError('Public episode reference has no corresponding action')


def recorded_requests(evidence, client):
    """Replay captured packets without substituting this host's runtime metadata."""
    if client.harness != evidence['harness']:
        raise InputError('Recorded harness differs; use --live to evaluate the current harness')
    baseline = {row['id']: row for row in evidence['phases']['production']}
    references = {row['id'] for row in evidence['review']['rows']}
    seen = set()
    for source in evidence['sources']:
        run = normalize(source['document'])[0]
        for action in run['events']:
            if action['kind'] != 'action':
                continue
            case_id = source['id'] + '-' + action['id']
            if case_id in seen or case_id not in baseline:
                raise InputError('Recorded requests do not match the public episode actions')
            seen.add(case_id)
            row = baseline[case_id]
            receipt = evidence['receipts'][row['request_hash']]
            if digest(receipt['request']) != row['request_hash'] or row['source_hash'] != digest(run):
                raise InputError('Recorded public-episode request or source differs')
            request = deepcopy(receipt['request'])
            if request['state']['cutoff_event_id'] != action['id']:
                raise InputError('Recorded public-episode cutoff differs')
            # A different model remains pending unless it has its own exact receipt.
            request['model'] = client.model
            yield {'id': case_id, 'episode': source['id'], 'run_id': run['id'],
                   'source_url': source['source_url'], 'action_id': action['id'],
                   'source_hash': digest(run), 'request_hash': digest(request), 'request': request}
    if seen != set(baseline) or seen != references:
        raise InputError('Recorded public-episode requests and references differ')


def score(response, request, reference):
    if response.get('model') != request['model']:
        raise InputError('Public episode response model differs from the request')
    answers = validate_answers(response, request)
    result = {}
    for field in FIELDS:
        answer = answers[field]
        value = answer['value'] if answer['status'] == 'decided' else answer['status']
        label = reference['fields'][field]
        result[field] = {'prediction': value, 'reference': label['value'],
                         'ambiguous': label['ambiguous'], 'alternatives': label['alternatives'],
                         'matches_primary': value == label['value'],
                         'reference_reason': label['reason'], 'reference_evidence_ids': label['evidence_ids'],
                         'matches_reviewed_options': value in [label['value'], *label['alternatives']],
                         'source': answer.get('source', 'model'),
                         'basis': answer.get('basis') or answer.get('evidence_gate'),
                         'probabilities': answer.get('probabilities', {})}
    return result


def summarize(rows):
    groups = {field: {'reviewed': 0, 'unambiguous': 0, 'unambiguous_matches': 0,
                     'ambiguous': 0, 'ambiguous_primary_matches': 0,
                     'ambiguous_option_matches': 0, 'unambiguous_disagreements': [],
                     'unresolved_without_inference': 0,
                     'not_applicable_without_inference': 0} for field in FIELDS}
    for row in rows:
        for field, value in row.get('scores', {}).items():
            group = groups[field]
            group['reviewed'] += 1
            group['unresolved_without_inference'] += value['source'] == 'evidence_gate' and value['prediction'] == 'unresolved'
            group['not_applicable_without_inference'] += value['source'] == 'evidence_gate' and value['prediction'] == 'not_applicable'
            if value['ambiguous']:
                group['ambiguous'] += 1
                group['ambiguous_primary_matches'] += value['matches_primary']
                group['ambiguous_option_matches'] += value['matches_reviewed_options']
            else:
                group['unambiguous'] += 1
                group['unambiguous_matches'] += value['matches_primary']
                if not value['matches_primary']:
                    group['unambiguous_disagreements'].append(row['id'])
    return groups


def evaluate(output, *, live=False, max_calls=0, client=None, evidence=None):
    if type(max_calls) is not int or max_calls < 0:
        raise InputError('Maximum calls must be a nonnegative integer')
    evidence = evidence if evidence is not None else load_evidence()
    client = client or JevClient()
    root = Path(output); root.mkdir(parents=True, exist_ok=True)
    rows = list(requests(evidence, client) if live else recorded_requests(evidence, client))
    references = {row['id']: row for row in evidence['review']['rows']}
    results = []; calls = 0; cached = 0

    def save():
        report = {'schema': 'public-episode-reading-report/1', 'model': client.model,
                  'harness': client.harness, 'selection': evidence['selection'],
                  'request_source': 'current harness' if live else 'recorded packets',
                  'total_actions': len(rows), 'new_calls': calls, 'cached_responses': cached,
                  'pending': len(rows) - sum('scores' in r for r in results),
                  'groups': summarize(results), 'results': results,
                  'review_scope_notes': evidence['review_scope_notes'],
                  'interpretation': evidence['interpretation']}
        (root / 'report.json').write_text(dumps(report), encoding='utf8')
        return report

    for row in rows:
        result = {k: v for k, v in row.items() if k != 'request'}
        path = root / (row['request_hash'] + '.json')
        attempt = root / (row['request_hash'] + '.attempt.json')
        receipt = json.loads(path.read_text(encoding='utf8')) if path.exists() else \
            evidence['receipts'].get(row['request_hash'])
        if receipt is not None:
            if receipt['request'] != row['request']:
                raise InputError('Saved public-episode request differs')
            cached += 1
        elif live and calls < max_calls:
            if attempt.exists():
                raise InputError('Inspect the earlier incomplete attempt before retrying: ' + row['request_hash'])
            attempt.write_text(dumps({'request_hash': row['request_hash'], 'status': 'reserved'}), encoding='utf8')
            calls += 1
            try:
                response = client.transport(row['request'])
                receipt = {'request': row['request'], 'response': response}
                path.write_text(dumps(receipt), encoding='utf8')
            except Exception as error:
                attempt.write_text(dumps({'request_hash': row['request_hash'], 'status': 'stopped',
                                          'error_type': type(error).__name__}), encoding='utf8')
                results.append(result); save()
                raise
        if receipt is not None:
            result['scores'] = score(receipt['response'], row['request'], references[row['id']])
        results.append(result)
        save()
    return save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/public-episode-reading')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--prompt-key', action='store_true')
    parser.add_argument('--max-calls', type=int, default=0)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    args = parser.parse_args()
    if args.max_calls < 0:
        parser.error('--max-calls must be nonnegative')
    if args.live and args.prompt_key:
        os.environ['JEV_API_KEY'] = getpass.getpass('Jev credential (process only): ')
    report = evaluate(args.output, live=args.live, max_calls=args.max_calls, client=JevClient(model=args.model))
    print(dumps({key: report[key] for key in ('model', 'harness', 'total_actions', 'new_calls',
                                            'cached_responses', 'pending', 'groups')}))
