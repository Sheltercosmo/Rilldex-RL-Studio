"""Retain rejected prompt experiments rather than treating them as fixes."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker.jev import validate_answers
from tracker.schema import digest


class GeneratedRelationshipAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets=json.loads((Path(__file__).parent/'fixtures/generated-generalization-relationships.json').read_text(encoding='utf8'))['sets']

    def test_actual_outputs_and_hashes_reproduce_reported_misses(self):
        for experiment in self.sets.values():
            for row in experiment['rows']:
                self.assertEqual(digest(row['request']),row['request_hash'])
                self.assertEqual(row['request']['model'],row['response']['model'])
                actual=validate_answers(row['response'],row['request'])
                for key,score in row['scores'].items():
                    self.assertEqual(actual[key]['value'],score['prediction'])
                    self.assertEqual(score['correct'],score['expected']==score['prediction'])

    def test_more_instructions_were_not_a_validated_fix(self):
        self.assertEqual(self.sets['plan']['groups']['original']['correct'],35)
        self.assertEqual(self.sets['plan']['groups']['independent_roles']['correct'],32)
        self.assertEqual(self.sets['target']['groups']['original']['correct'],10)
        self.assertEqual(self.sets['target']['groups']['result_and_means']['correct'],10)

    def test_ablation_preserves_actual_source_and_candidate_inventory(self):
        for experiment in self.sets.values():
            originals={(r.get('version'),r['case_id'],r['event_id']):r for r in experiment['rows'] if r['arm']=='original'}
            for row in experiment['rows']:
                original=originals[row.get('version'),row['case_id'],row['event_id']]['request']
                q=deepcopy(row['request'])
                self.assertTrue(q['state']['comparison_rule'].startswith(original['state']['comparison_rule']))
                q['state']['comparison_rule']=original['state']['comparison_rule']
                self.assertEqual(q,original)

    def test_identical_plan_request_can_have_different_live_responses(self):
        rows=[r for r in self.sets['plan']['rows'] if r['arm']=='original' and r['case_id']=='software' and r['event_id']=='e12']
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['request'],rows[1]['request'])
        self.assertNotEqual(rows[0]['scores']['s1']['prediction'],rows[1]['scores']['s1']['prediction'])
