"""Replay actual Jev receipts; no provider calls or fabricated predictions."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.evaluate_reading_context import requests, score
from scripts.evaluate_environment_reading import requests as definition_requests
from tracker.jev import validate_answers
from tracker.schema import digest


def comparable(request):
    result=deepcopy(request)
    # SQLite's version is provenance; the selected passages must still match.
    result.get('state',{}).get('context_retrieval',{}).get('retrieval',{}).pop('sqlite_version',None)
    return result


class EnvironmentReadingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((Path(__file__).parent/'fixtures/environment_reading_evidence.json').read_text(encoding='utf-8'))

    def test_saved_requests_have_exact_hashes_and_pinned_model(self):
        for run in self.data['runs'].values():
            for key, receipt in run['receipts'].items():
                self.assertEqual(key,digest(receipt['request']))
                self.assertEqual(receipt['response']['model'],run['model'])

    def test_current_context_requests_replay_all_delivered_decisions(self):
        saved=self.data['runs']['reading-context-final']
        actual={r['case_id']:r for r in requests(saved['model'],['current'])}
        self.assertEqual(len(actual),len(saved['results']))
        for row in saved['results']:
            with self.subTest(case=row['case_id']):
                receipt=saved['receipts'][row['request_hash']]
                self.assertEqual(comparable(actual[row['case_id']]['request']),comparable(receipt['request']))
                scores=score(receipt['response'],{**row,'request':receipt['request']})
                self.assertEqual(scores,row['scores'])
                self.assertTrue(all(v['correct'] for v in scores.values()))

    def test_definition_ablation_uses_only_visible_evidence_as_reference(self):
        saved=self.data['runs']['environment-reading-final']
        actual={(r['case_id'],r['variant']):r for r in definition_requests(saved['model'])}
        for row in saved['results']:
            receipt=saved['receipts'][row['request_hash']]
            self.assertEqual(comparable(actual[row['case_id'],row['variant']]['request']),comparable(receipt['request']))
            answer=validate_answers(receipt['response'],receipt['request'])['mode']
            prediction=answer['value'] if answer['status']=='decided' else answer['status']
            self.assertEqual(prediction,row['expected_visible_answer'])
            if row['case_id'].startswith('opaque-') and row['variant']=='without_definitions':
                self.assertEqual(prediction,'unresolved')

    def test_baseline_failures_reproduce_and_prefix_ablation_resolves_context_loss(self):
        saved=self.data['runs']['reading-context-baseline']
        for row in saved['results']:
            receipt=saved['receipts'][row['request_hash']]
            scores=score(receipt['response'],{**row,'request':receipt['request']})
            self.assertEqual(scores,row['scores'])
            if row['arm']=='current':self.assertTrue(any(not v['correct'] for v in scores.values()))
            elif row['kind']=='authored':self.assertTrue(all(v['correct'] for v in scores.values()))


if __name__=='__main__':unittest.main()
