"""Keep successful controls and unresolved target-identification misses visible."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker.jev import validate_answers
from tracker.schema import digest
from scripts.evaluate_generated_target_identity import identity, transform, NEGATIVES


class GeneratedTargetIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads((Path(__file__).parent/'fixtures/generated-generalization-target-identity.json').read_text(encoding='utf8'))

    def test_actual_responses_reproduce_partial_improvement_and_remaining_miss(self):
        for row in self.fixture['rows']:
            request=self.fixture['requests'][row['request_hash']]
            self.assertEqual(digest(request),row['request_hash'])
            answers=validate_answers(row['response'],request)
            for key,score in row['scores'].items():
                self.assertEqual(answers[key]['value'],score['raw_prediction'])
                self.assertEqual(identity(score['raw_prediction']),score['prediction'])
                self.assertEqual(score['correct'],score['expected_identity']==score['prediction'])
        groups=self.fixture['groups']
        self.assertEqual([groups[a]['correct'] for a in ('original','binary_identity','result_identity')],[13,11,16])
        for arm in ('original','binary_identity','result_identity'):
            self.assertEqual(groups[arm]['pairs'],17)
            self.assertEqual(groups[arm]['positive_pairs'],6)
            self.assertEqual(groups[arm]['false_identities'],0)
            self.assertIn('simulation/e8/a0',groups[arm]['failures'])

    def test_only_decision_framing_changes_not_evidence_or_native_context(self):
        rows=self.fixture['rows'];requests=self.fixture['requests']
        originals={(r['case_id'],r['event_id']):requests[r['request_hash']] for r in rows if r['arm']=='original'}
        for row in rows:
            original=originals[row['case_id'],row['event_id']]
            actual=requests[row['request_hash']]
            self.assertEqual(actual,transform(original,row['arm']))
            a,b=deepcopy(actual['state']),deepcopy(original['state'])
            a.pop('comparison_rule');b.pop('comparison_rule')
            self.assertEqual(a,b)
            if row['case_id'].startswith('control_'):
                self.assertNotIn('WITHHELD_FUTURE_RESULT',str(actual))
            if row['arm']=='binary_identity':
                for key,q in actual['questions'].items():
                    before=original['questions'][key]['criteria']
                    self.assertEqual(q['criteria']['same_work_target'],before['same_work_target'])
                    self.assertEqual(q['criteria']['unresolved'],before['unresolved'])
                    for label in NEGATIVES:self.assertIn(before[label],q['criteria']['not_same'])

    def test_missed_identity_is_not_hidden_by_pooled_negative_accuracy(self):
        groups=self.fixture['groups']
        self.assertEqual(groups['original']['missed_identities'],3)
        self.assertEqual(groups['binary_identity']['missed_identities'],5)
        self.assertEqual(groups['result_identity']['missed_identities'],1)
        self.assertEqual(groups['result_identity']['unknown_pairs'],1)
        self.assertEqual(groups['selected_public_trace_existing_annotation/result_identity']['correct'],2)
        self.assertEqual(groups['existing_authored_layer_control/result_identity']['correct'],4)
        self.assertEqual(groups['fresh_authored_scenario/result_identity']['correct'],8)


class GeneratedTargetPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).parent/'fixtures'
        cls.fixture=json.loads((folder/'generated-generalization-target-packet.json').read_text(encoding='utf8'))
        cls.original=json.loads((folder/'generated-generalization-target-identity.json').read_text(encoding='utf8'))
        cls.methods=json.loads((folder/'generated-generalization-method-recall.json').read_text(encoding='utf8'))

    def test_single_pass_wording_does_not_hide_lost_subtype_fidelity(self):
        groups=self.fixture['groups']
        self.assertEqual(groups['result_six_way']['correct'],16)
        self.assertEqual(groups['result_six_way']['full_relation_correct'],14)
        self.assertEqual(groups['result_six_way']['full_relation_failures'],
                         ['simulation/e8/a0','service/e12/a0','service/e12/a1'])
        self.assertEqual(groups['method_packet']['full_relation_correct'],1)
        for row in self.fixture['rows']:
            request=self.fixture['requests'][row['request_hash']]
            self.assertEqual(digest(request),row['request_hash'])
            answers=validate_answers(row['response'],request)
            for key,score in row['scores'].items():
                self.assertEqual(answers[key]['value'],score['raw_prediction'])
                self.assertEqual(score['relation_correct'],score['raw_prediction']==score['expected_target_relation'])

    def test_six_way_arm_retains_source_and_negative_relationship_definitions(self):
        originals={(r['case_id'],r['event_id']):self.original['requests'][r['request_hash']]
                   for r in self.original['rows'] if r['arm']=='original'}
        for row in self.fixture['rows']:
            if row['arm']!='result_six_way':continue
            request=self.fixture['requests'][row['request_hash']]
            original=originals[row['case_id'],row['event_id']]
            self.assertEqual(request,transform(original,'result_six_way'))
            for key,question in request['questions'].items():
                self.assertEqual(set(question['criteria']),set(original['questions'][key]['criteria']))
                for label in (*NEGATIVES,'unresolved'):
                    self.assertEqual(question['criteria'][label],original['questions'][key]['criteria'][label])

    def test_method_packet_contrast_changes_no_saved_method_evidence(self):
        row=next(r for r in self.fixture['rows'] if r['arm']=='method_packet')
        actual=self.fixture['requests'][row['request_hash']]
        method=self.methods['cases']['simulation']['receipts'][row['method_request_hash']]['request']
        self.assertEqual(actual['state'],method['state'])
        self.assertEqual(actual['model'],method['model'])
        original=next(self.original['requests'][r['request_hash']] for r in self.original['rows'] if
                      r['arm']=='original' and r['case_id']=='simulation' and r['event_id']=='e8')
        self.assertEqual(actual['questions']['a0']['criteria'],original['questions']['a0']['criteria'])
        self.assertEqual(row['scores']['a0']['raw_prediction'],'same_work_target')
