"""Protocol/scoring tests, not diagnostic accuracy evidence."""
from copy import deepcopy
import unittest

from research.process_error_pilot import request,validate,score,tool_error_guess
from tracker.schema import InputError
from tests.test_chat_messages import source


class FirstErrorPilotTests(unittest.TestCase):
    def setUp(self):
        self.row=source();self.req=request(self.row,'test-case')
        self.response=dict(schema='first-error-pilot-response/1',case_id='test-case',choice='message_3',
            rationale='Authored protocol fixture, not a model judgment.',evidence_message_indices=[3,4])
        self.reference=dict(dataset='authored',first_error=dict(message_index=3),tool_error_guess=None)

    def test_only_assistant_options_and_no_hidden_task_or_grading_fields(self):
        self.assertEqual(set(self.req['choices']),{'message_1','message_3','message_5','none','unresolved'})
        for marker in ('PRIVATE_USER_SCENARIO','PRIVATE_TARGET','PRIVATE_TASK_RULE','FUTURE_ANSWER','step_labels','final_label'):
            self.assertNotIn(marker,str(self.req))
        self.assertEqual([m['index'] for m in self.req['messages']],list(range(6)))

    def test_unresolved_does_not_become_no_error_or_wrong_location(self):
        response={**self.response,'choice':'unresolved','evidence_message_indices':[]}
        result=score(self.req,response,self.reference)
        self.assertFalse(result['determined']);self.assertIsNone(result['exact_match'])
        self.assertIsNone(result['error_presence_match'])
        result=score(self.req,{**response,'choice':'none'},self.reference)
        self.assertTrue(result['determined']);self.assertFalse(result['exact_match'])

    def test_localization_distinguishes_wrong_error_position_from_wrong_presence(self):
        response={**self.response,'choice':'message_5','evidence_message_indices':[5]}
        result=score(self.req,response,self.reference)
        self.assertTrue(result['error_presence_match']);self.assertFalse(result['exact_match'])
        self.assertTrue(score(self.req,self.response,self.reference)['exact_match'])

    def test_source_response_binding_and_citation_grain_are_strict(self):
        for edits in ({'case_id':'other'},{'choice':'message_2'},{'choice':{}},
                      {'evidence_message_indices':[4]},{'evidence_message_indices':[3,3]},
                      {'evidence_message_indices':[True]},{'evidence_message_indices':[3,99]}):
            with self.subTest(edits=edits),self.assertRaises(InputError):validate(self.req,{**self.response,**edits})

    def test_rule_uses_native_assistant_call_id_not_adjacency_or_customer_actions(self):
        row=deepcopy(self.row);row['messages'][4]['content']='{"error":"not found"}'
        self.assertEqual(tool_error_guess(row),3)
        row['messages'][4].pop('tool_call_id');self.assertIsNone(tool_error_guess(row))
        row=deepcopy(self.row);row['messages'][4]['content']='{"error":"not found"}'
        row['messages'][3]['role']='user';self.assertIsNone(tool_error_guess(row))


if __name__=='__main__':unittest.main()
