"""Replay saved live Jev receipts; transformations are paired, not new samples."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from scripts.evaluate_harness_generalization import requests, evaluation_cases, representations
from scripts.evaluate_long_context import records
from tracker.jev import validate_answers
from tracker.schema import digest
from receipt_replay import recorded_sqlite_metadata


class HarnessReadingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved=json.loads((Path(__file__).parent/'fixtures/harness_reading_evidence.json').read_text(encoding='utf8'))['sets']
        cls.enterClassContext(recorded_sqlite_metadata(cls.saved))

    def test_current_source_matches_historical_receipts(self):
        current={(r['case_id'],r['format'],r['layer']):r for r in requests()}
        self.assertEqual(len(current),96)
        for row in self.saved['harness']:
            with self.subTest(case=row['case_id'],format=row['format'],layer=row['layer']):
                now=current[(row['case_id'],row['format'],row['layer'])]
                current_request = deepcopy(now['request'])
                if row['layer'] == 'macro':
                    self.assertIn('feedback_reading_scope', current_request['state'])
                    current_request['state'].pop('feedback_reading_scope')
                historical = deepcopy(row['request'])
                if row['layer'] == 'macro':
                    # Purpose now separates combined dispatches from unknowns.
                    # Its current exact-request evidence has a separate suite.
                    current_request['questions'].pop('mode',None)
                    historical['questions'].pop('mode',None)
                self.assertEqual(current_request,historical)
                answer=validate_answers(row['response'],row['request'])[row['answer_key']]
                self.assertEqual(answer['value'],row['reference'])

    def test_long_history_refinement_uses_actual_source_and_live_choices(self):
        current={(r['case_id'],r['arm']):r for r in records()}
        for row in self.saved['long_refined']:
            with self.subTest(case=row['case_id'],arm=row['arm']):
                self.assertEqual(current[(row['case_id'],row['arm'])]['request'],row['request'])
                self.assertEqual(validate_answers(row['response'],row['request'])[row['answer_key']]['value'],row['reference'])

    def test_diagnostic_full_context_corrected_all_six_baseline_misses(self):
        for row in self.saved['long_baseline']:
            prediction=validate_answers(row['response'],row['request'])[row['answer_key']]['value']
            self.assertEqual(prediction==row['reference'],row['arm']=='complete_prefix')

    def test_all_receipts_bound_to_exact_requests_and_requested_models(self):
        for rows in self.saved.values():
            for row in rows:
                self.assertEqual(digest(row['request']),row['request_hash'])
                self.assertEqual(row['response']['model'],row['request']['model'])
                validate_answers(row['response'],row['request'])

    def test_local_purpose_controls_and_repeated_ambiguous_lookup(self):
        rows=self.saved['purpose_ablation']
        def correct(row):
            return validate_answers(row['response'],row['request'])['mode']['value']==row['reference']
        controls=[r for r in rows if not r['case_id'].startswith('airline-')]
        for arm,expected in [('baseline',15),('expressions',18),('production',18)]:
            selected=[r for r in controls if r['arm']==arm]
            self.assertEqual(len(selected),18)
            self.assertEqual(sum(map(correct,selected)),expected)
        # Repeated calls expose classifier variability; do not erase misses by
        # keeping only a successful response to an identical request.
        lookup=[r for r in rows if r['case_id']=='airline-3-e7']
        self.assertEqual(sum(correct(r) for r in lookup if r['arm']=='production'),5)
        refined=[r for r in lookup if r['arm']=='production_boundary']
        self.assertEqual(len(refined),9)
        self.assertTrue(all(map(correct,refined)))

    def test_public_policy_never_becomes_agent_authored_prose(self):
        from tracker.adapters import normalize
        for case in evaluation_cases():
            if case['origin']!='public_trace':continue
            self.assertEqual(case['document']['messages'][0]['role'],'system')
            policy=case['document']['messages'][0]['content']
            for name,doc in representations(case['document']):
                run=normalize(doc)[0]
                matches=[e for e in run['events'] if e['text']==policy]
                self.assertEqual(len(matches),1)
                self.assertEqual(matches[0]['actor'],'system')
