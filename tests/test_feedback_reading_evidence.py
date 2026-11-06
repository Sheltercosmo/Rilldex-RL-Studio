"""Replay saved live responses through the current reader and stored analysis."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.evaluate_feedback_reading import cases, requests
from scripts.evaluate_reading_context import score
from tracker.adapters import normalize
from tracker.jev import JevClient
from tracker.schema import digest
from tracker.store import Store


class FeedbackReadingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / 'fixtures/feedback_reading_evidence.json'
        cls.evidence = json.loads(path.read_text(encoding='utf8'))

    def test_all_saved_trials_reproduce_scores_including_failed_definitions(self):
        for key, receipt in self.evidence['receipts'].items():
            self.assertEqual(key, digest(receipt['request']))
            self.assertEqual(receipt['response']['model'], receipt['request']['model'])
        for phase, report in self.evidence['phases'].items():
            groups = defaultdict(lambda: {'decisions': 0, 'correct': 0, 'failures': []})
            for row in report['results']:
                receipt = self.evidence['receipts'][row['request_hash']]
                scores = score(receipt['response'], {**row, 'request': receipt['request']})
                self.assertEqual(scores, row['scores'], (phase, row['id'], row['format']))
                for dimension, value in scores.items():
                    group = groups['/'.join([row['kind'], row['arm'], dimension])]
                    group['decisions'] += 1
                    group['correct'] += int(value['correct'])
                    if not value['correct']:
                        group['failures'].append(row['id'] + '/' + row['format'])
            self.assertEqual(dict(groups), report['groups'])
        first = self.evidence['phases']['response-boundary']['groups']
        self.assertEqual(first['response_boundary/response_definition/feedback_response']['correct'], 12)
        final = self.evidence['phases']['response-boundary-v2']['groups']
        self.assertEqual(final['authored/response_definition_v2/mode']['correct'], 12)

    def test_current_requests_and_source_hashes_match_the_final_live_trial(self):
        current = {(row['id'], row['format']): row for row in requests(('production',))}
        saved = self.evidence['phases']['response-boundary-v2']['results']
        self.assertEqual(len(current), 38)
        for row in saved:
            generated = current[(row['id'], row['format'])]
            self.assertEqual(generated['source_hash'], row['source_hash'])
            self.assertEqual(generated['reference'], row['reference'])
            self.assertEqual(generated['request_hash'], row['request_hash'])
            self.assertEqual(generated['request'], self.evidence['receipts'][row['request_hash']]['request'])

    def test_live_receipt_replay_survives_storage_refresh_and_reopening(self):
        sources = {(row['id'], row['format']): row for row in cases()}
        saved = self.evidence['phases']['response-boundary-v2']['results']
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen',
                side_effect=AssertionError('Saved response replay must stay offline')):
            store = Store(Path(directory) / 'replay.sqlite')
            for row in saved:
                case = sources[(row['id'], row['format'])]
                run = normalize(case['document'])[0]
                receipt = self.evidence['receipts'][row['request_hash']]

                def replay(request):
                    self.assertEqual(request, receipt['request'])
                    return deepcopy(receipt['response'])

                result = JevClient(transport=replay).evaluate(run, row['action_id'])
                # These are historical live outputs, not new provider calls.
                result['_provenance']['execution'] = 'saved_live_receipt_replay'
                store.add([run])
                p = result['_provenance']
                store.record(run['id'], row['action_id'], p['harness'], p['model'], p['packet_hash'], result)
                store.refresh(run['id'])
                analysis = Store(store.path).get(run['id'])['analysis']
                action = next(a for a in analysis['actions'] if a['event_id'] == row['action_id'])
                expected = row['reference']['feedback_response']
                self.assertEqual(action['semantic']['feedback_response']['value'], expected)
                self.assertGreaterEqual(analysis['metrics']['feedback_response_counts'].get(expected, 0), 1)


if __name__ == '__main__':
    unittest.main()
