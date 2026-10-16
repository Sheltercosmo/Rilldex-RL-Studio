"""Reference alignment controls; fixture judgments are not accuracy evidence."""
from copy import deepcopy
import unittest

from research.apb_reference_audit import check,source_packet
from tests.test_chat_messages import source


class ProcessReferenceTests(unittest.TestCase):
    def test_packet_has_only_recorded_context_and_explicit_message_indices(self):
        row=source();before=deepcopy(row);packet=source_packet(row)
        self.assertEqual(packet['assistant_message_indices'],[1,3,5])
        self.assertEqual(packet['messages'],row['messages']);self.assertEqual(row,before)
        for private in ('PRIVATE_USER_SCENARIO','PRIVATE_TARGET','PRIVATE_TASK_RULE','FUTURE_ANSWER','step_labels','final_label'):
            self.assertNotIn(private,str(packet))
        packet['messages'][0]['content']='changed'
        self.assertEqual(row,before)

    def test_first_error_uses_message_index_and_never_expands_a_label_per_call(self):
        row=source();row['step_labels']['3']=-1
        second=deepcopy(row['messages'][3]['tool_calls'][0]);second['id']='second'
        row['messages'][3]['tool_calls'].append(second)
        result=check(row)
        self.assertEqual(result['first_error'],dict(status='recorded_first_error',message_index=3))
        self.assertEqual(result['counts']['reference_labels'],3)
        current=next(r for r in result['references'] if r['message_index']==3)
        self.assertEqual(len(current['related_event_ids']),3)
        self.assertEqual(current['label'],-1)

    def test_missing_earlier_label_prevents_a_claim_about_the_first_error(self):
        row=source();row['step_labels']['3']=-1;del row['step_labels']['1']
        result=check(row)
        self.assertEqual(result['first_error'],dict(status='unknown',message_index=None))
        self.assertEqual(result['counts']['missing_labels'],1)
        row=source();row['step_labels']['1']=-1;del row['step_labels']['5']
        self.assertEqual(check(row)['first_error'],dict(status='recorded_first_error',message_index=1))

    def test_no_error_requires_complete_reference_coverage(self):
        row=source();self.assertEqual(check(row)['first_error']['status'],'no_recorded_error')
        del row['step_labels']['3']
        self.assertEqual(check(row)['first_error']['status'],'unknown')


if __name__=='__main__':unittest.main()
