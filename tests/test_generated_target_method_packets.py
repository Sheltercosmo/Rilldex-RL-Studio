"""Keep the target reader diagnostic sourceful and isolated from label changes."""
from copy import deepcopy
from pathlib import Path
import unittest

from tracker import method_comparison
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import checked_span, read


class GeneratedTargetMethodPacketControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).parent/'fixtures'
        cls.fixture=read(folder/'generated-generalization-target-method-packets.json')
        cls.rows=[{**row,'request':cls.fixture['requests'][row['request_hash']],
                   **cls.fixture['sources'][row['case_id']]} for row in cls.fixture['rows']]
        cls.originals=read(folder/'generated-generalization-target-identity.json')['requests']

    def test_actual_decisions_preserve_the_rule_only_miss_and_all_subtypes(self):
        self.assertEqual(self.fixture['groups']['method_rule_only']['correct'],16)
        self.assertEqual(self.fixture['groups']['method_rule_only']['failures'],['simulation/e8/a0'])
        self.assertEqual(self.fixture['groups']['method_evidence_packet']['correct'],17)
        self.assertEqual(self.fixture['groups']['method_evidence_packet']['failures'],[])
        for row in self.rows:
            self.assertEqual(digest(row['request']),row['request_hash'])
            answers=validate_answers(row['response'],row['request'])
            for key,score in row['scores'].items():
                self.assertEqual(answers[key]['value'],score['prediction'])
                self.assertEqual(score['correct'],score['expected']==score['prediction'])
        service=[r for r in self.rows if r['arm']=='method_evidence_packet' and
                 r['case_id']=='service' and r['event_id']=='e12']
        self.assertEqual(len(service),2)
        self.assertTrue(all(r['scores'][r['packet_id']]['prediction']=='different_work_same_subject' for r in service))

    def test_rule_only_is_one_field_change_with_all_pair_questions_preserved(self):
        rows=[r for r in self.rows if r['arm']=='method_rule_only']
        self.assertEqual(len(rows),14)
        self.assertEqual(sum(len(r['reference']) for r in rows),17)
        for row in rows:
            original=self.originals[row['original_request_hash']]
            request=deepcopy(row['request'])
            self.assertNotEqual(request['state']['rule'],original['state']['rule'])
            request['state']['rule']=original['state']['rule']
            self.assertEqual(request,original)
            self.assertEqual(row['source_comparison']['target'],row['source_comparison']['supplied'])

    def test_method_packet_preserves_original_target_words_and_exact_native_reader(self):
        rows=[r for r in self.rows if r['arm']=='method_evidence_packet']
        self.assertEqual(len(rows),17)
        for row in rows:
            original=self.originals[row['original_request_hash']]
            key=row['packet_id'];prior=next(p for p in original['state']['prior_actions'] if p['id']==key)
            actual=row['request']
            self.assertEqual(actual['questions'],{key:original['questions'][key]})
            self.assertEqual(len(actual['questions'][key]['criteria']),6)
            method=method_comparison.pair_request(row['source'],row['document'],prior['unit_id'],
                original['state']['current_action']['unit_id'],version=method_comparison.NATIVE_VERSION)
            self.assertEqual(digest(method),row['method_request_hash'])
            expected=deepcopy(method)
            expected['questions']={key:original['questions'][key]}
            expected['state']['comparison_rule']=expected['state']['rule']
            self.assertEqual(actual,expected)

    def test_method_selected_ranges_are_exact_source_in_same_context_before_cutoff(self):
        for row in self.rows:
            if row['arm']!='method_evidence_packet':continue
            request=row['request'];state=request['state'];source=row['source']
            events={e['id']:e for e in source['events']};at=events[state['cutoff']['event_id']]
            for ref in state['source_ranges']:
                event=checked_span(source,ref,state['cutoff'])
                self.assertEqual((event['trajectory_id'],event.get('context_id')),
                                 (at['trajectory_id'],at.get('context_id')))
                self.assertEqual(event['text'][ref['start']:ref['end']],ref['text'])
            self.assertNotIn('WITHHELD_FUTURE_RESULT',str(request))
        # This arm selects an evidence interval; it must not pretend to isolate only wording.
        rover=next(r for r in self.rows if r['arm']=='method_evidence_packet' and
                   r['case_id']=='simulation' and r['event_id']=='e8')
        self.assertNotEqual(rover['source_comparison']['target'],rover['source_comparison']['supplied'])
