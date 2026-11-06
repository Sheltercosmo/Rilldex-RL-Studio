"""Replay production requests, preserving the observed subtype disagreement."""
from pathlib import Path
import unittest

from scripts.evaluate_generated_target_interval_production import records
from scripts.evaluate_generated_target_identity_controls import records as identity_records
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import read


class GeneratedTargetIntervalProductionTests(unittest.TestCase):
    def test_exact_production_packets_and_actual_outcomes_remain_replayable(self):
        fixture=read(Path(__file__).parent/'fixtures/generated-generalization-target-interval-production.json')
        rows=list(records())
        self.assertEqual((fixture['pairs'],fixture['correct']),(20,19))
        self.assertEqual(len(rows),20)
        for row in rows:
            self.assertEqual(row['request'],fixture['requests'][row['request_hash']])
            saved=next(r for r in fixture['rows'] if r['request_hash']==row['request_hash'])
            answers=validate_answers(saved['response'],row['request'])
            for key,score in saved['scores'].items():
                self.assertEqual(answers[key]['value'],score['prediction'])
                self.assertEqual(score['correct'],score['expected']==score['prediction'])
        failures=[r for r in fixture['rows'] if not all(s['correct'] for s in r['scores'].values())]
        self.assertEqual([(r['case_id'],r['event_id'],r['packet_id']) for r in failures],[('service','e12','a0')])
        self.assertEqual(failures[0]['scores']['a0']['prediction'],'different_instance')
        controls=[r for r in fixture['rows'] if r['case_id'].startswith(('declared_','undeclared_'))]
        self.assertEqual(len(controls),3)
        self.assertTrue(all(all(s['correct'] for s in r['scores'].values()) for r in controls))

    def test_reference_adjudication_preserves_the_original_failed_label_and_source_grain(self):
        folder=Path(__file__).parent/'fixtures'
        frozen=read(folder/'generated-generalization-target-interval-production.json')
        review=read(folder/'generated-generalization-target-reference-adjudication.json')['cases'][0]
        original=next(r for r in frozen['rows'] if r['request_hash']==review['request_hash'])
        self.assertFalse(original['scores']['a0']['correct'])
        self.assertEqual(original['reference']['a0'],review['original_reference'])
        self.assertEqual(original['scores']['a0']['prediction'],review['observed_prediction'])
        self.assertEqual(set(review['acceptable_source_readings']),{'different_work_same_subject','different_instance'})
        self.assertEqual(review['status'],'ambiguous_reference_grain')

    def test_fresh_explicit_ids_resolve_same_record_different_record_and_fallback(self):
        frozen=read(Path(__file__).parent/'fixtures/generated-generalization-target-explicit-identity.json')
        self.assertEqual((frozen['pairs'],frozen['correct']),(4,4))
        expected={'created_record_readback':'different_work_same_subject',
                  'other_requested_record_readback':'different_instance',
                  'same_request_permitted_fallback':'same_work_target',
                  'separate_requests_same_slot':'different_instance'}
        for row in identity_records():
            self.assertEqual(row['request'],frozen['requests'][row['request_hash']])
            saved=next(r for r in frozen['rows'] if r['request_hash']==row['request_hash'])
            answer=validate_answers(saved['response'],row['request'])['a0']['value']
            self.assertEqual(answer,expected[row['case_id']])
            self.assertEqual(saved['reference'],row['reference'])
            self.assertNotIn('reference',row['request'])
