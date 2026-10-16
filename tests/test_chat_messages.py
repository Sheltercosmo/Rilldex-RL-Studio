import copy
import unittest

from tracker.activity import packet, units
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.schema import InputError


def source():
    return {"total_index":7,"query_index":2,"sample_index":0,"data_source":"tau2_retail",
            "question":"PRIVATE_USER_SCENARIO", "ground_truth":{"answer":"PRIVATE_TARGET"},
            "task_description":{"hidden":"PRIVATE_TASK_RULE"}, "answer_text":"FUTURE_ANSWER",
            "tools":[{"type":"function","function":{"name":"lookup_order","description":"Read an order.","parameters":{"type":"object"}}}],
            "messages":[{"role":"system","content":"Ask before changing an order."},
                        {"role":"assistant","content":"How can I help?"},
                        {"role":"user","content":"Please check my order."},
                        {"role":"assistant","content":"I will retrieve the order.","tool_calls":[{"id":"call-a","type":"function","function":{"name":"lookup_order","arguments":"{\"order\":42}"}}]},
                        {"role":"tool","content":"Order dispatched.","tool_call_id":"call-a"},
                        {"role":"assistant","content":"Your order has been dispatched."}],
            "step_labels":{"1":1,"3":1,"5":1},"final_label":1}


class ChatMessagesTests(unittest.TestCase):
    def test_nonfinite_argument_text_remains_inspectable_and_hashable(self):
        from tracker.schema import digest
        doc=source();doc['messages'][3]['tool_calls'][0]['function']['arguments']='{"order":NaN}'
        run=normalize(doc)[0]
        action=next(e for e in run['events'] if e['kind']=='action')
        self.assertEqual(action['argument_status'],'invalid_json_object')
        self.assertEqual(action['raw_arguments'],'{"order":NaN}')
        self.assertTrue(digest(run))

    def test_bfcl_flat_contract_is_preserved_without_rewriting_its_schema(self):
        doc=source();doc['data_source']='bfcl_multi_turn_base'
        definition=doc['tools'][0]['function']
        definition['parameters']['type']='dict'
        definition['response']={'type':'dict','properties':{'value':{'type':'integer'}}}
        doc['tools']=[definition];original=copy.deepcopy(doc)
        run=normalize(doc)[0]
        self.assertEqual(doc,original)
        self.assertEqual(run['adapter_version'],'agent-process-bench/2')
        action=next(e for e in run['events'] if e['kind']=='action')
        self.assertEqual(action['tool_contract'],dict(source_pointer='/tools/0',definition=definition,source_format='bfcl-function/1'))
        doc['data_source']='tau2_retail'
        with self.assertRaisesRegex(InputError,'Tool definitions'):normalize(doc)

    def test_bfcl_legacy_markup_does_not_invent_a_dispatch_or_binding(self):
        doc=source();doc['data_source']='bfcl_multi_turn_base'
        doc['tools']=[doc['tools'][0]['function']]
        doc['messages'][3]={'role':'assistant','content':'<tool_call>{"name":"lookup_order","arguments":{"order":42}}</tool_call>'}
        doc['messages'][4].pop('tool_call_id')
        run=normalize(doc)[0]
        self.assertFalse(any(e['kind']=='action' for e in run['events']))
        feedback=next(e for e in run['events'] if e['kind']=='feedback')
        self.assertIsNone(feedback['source_call_id'])
        self.assertEqual(feedback['agent_visibility'],'recorded_agent_result')
        self.assertEqual(links(run)['records'],[])
        self.assertEqual(run['outcome']['source_process_annotation']['labels'],doc['step_labels'])

    def test_reference_label_is_one_message_judgment_even_with_multiple_calls(self):
        doc=source();call=copy.deepcopy(doc['messages'][3]['tool_calls'][0]);call['id']='call-b'
        doc['messages'][3]['tool_calls'].append(call)
        run=normalize(doc)[0]
        actions=[e for e in run['events'] if e['kind']=='action']
        self.assertEqual(len(actions),2)
        self.assertEqual({e['source_message_index'] for e in actions},{3})
        annotation=run['outcome']['source_process_annotation']
        self.assertEqual(annotation['unit'],'whole assistant message')
        self.assertEqual(len(annotation['labels']),3)
        self.assertTrue(all('step_labels' not in str(e) for e in run['events']))

    def test_label_aliases_and_noninteger_values_cannot_change_the_reference_grain(self):
        for key,value in [('01',1),('１',1),('1',1.0),('1',True),('1','1')]:
            with self.subTest(key=key,value=value):
                doc=source();doc['step_labels'][key]=value
                with self.assertRaises(InputError):normalize(doc)

    def test_native_roles_exact_pointers_and_tool_contract(self):
        doc=source();run=normalize(doc)[0]
        self.assertEqual(run["adapter"],"agent-process-bench")
        self.assertEqual(run["events"][0]["kind"],"context")
        self.assertEqual(run["events"][2]["kind"],"instruction")
        action=next(e for e in run["events"] if e["kind"]=="action")
        self.assertEqual(action["arguments"],{"order":42})
        self.assertEqual(action["tool_contract"]["source_pointer"],"/tools/0")
        self.assertEqual(action["source_pointer"],"/messages/3/tool_calls/0")
        subject=next(u for u in units(run) if u["kind"]=="action_dispatch")
        self.assertIn("Read an order.",str(packet(run,subject["id"])))
        self.assertEqual(len(links(run)["records"]),1)
        self.assertEqual(run["outcome"]["source_process_annotation"]["labels"],doc["step_labels"])

    def test_private_scenario_and_grading_never_enter_activity_packets(self):
        run=normalize(source())[0]
        for unit in units(run):
            if unit["eligible"]:
                evidence=str(packet(run,unit["id"]))
                for private in ("PRIVATE_USER_SCENARIO","PRIVATE_TARGET","PRIVATE_TASK_RULE","FUTURE_ANSWER","step_labels","final_label"):
                    self.assertNotIn(private,evidence)
        action=next(u for u in units(run) if u["kind"]=="action_dispatch")
        self.assertNotIn("Order dispatched.",str(packet(run,action["id"])))

    def test_invalid_generated_arguments_are_preserved(self):
        doc=source();doc["messages"][3]["tool_calls"][0]["function"]["arguments"]="{invalid"
        run=normalize(doc)[0];action=next(e for e in run["events"] if e["kind"]=="action")
        self.assertEqual(action["raw_arguments"],"{invalid")
        self.assertEqual(action["argument_status"],"invalid_json_object")
        self.assertTrue(any("invalid JSON" in w for w in run["warnings"]))

    def test_missing_result_link_stays_unknown_and_duplicate_calls_fail(self):
        doc=source();doc["messages"][4]["tool_call_id"]="other"
        run=normalize(doc)[0]
        self.assertEqual(len(links(run)["records"]),0)
        self.assertTrue(any(e["kind"]=="external_feedback" and e["source_call_id"]=="other" for e in run["events"]))
        doc=source();doc["messages"][3]["tool_calls"]*=2
        with self.assertRaises(InputError):normalize(doc)

    def test_step_reference_scope_and_unsupported_actor_are_checked(self):
        doc=source();doc["step_labels"]["2"]=1
        with self.assertRaises(InputError):normalize(doc)
        doc=source();doc["messages"][3]["role"]="user"
        with self.assertRaises(InputError):normalize(doc)
        doc=source();doc["messages"][0]["role"]="developer"
        with self.assertRaises(InputError):normalize(doc)

    def test_customer_tool_result_is_not_assistant_knowledge_or_action(self):
        doc=source();doc["data_source"]="tau2_telecom"
        doc["messages"][3]["role"]="user";doc["messages"][3]["content"]="PRIVATE_SIMULATOR_COMMENT"
        del doc["step_labels"]["3"]
        doc["messages"][4]["content"]="PRIVATE_CUSTOMER_DEVICE_STATE"
        doc["messages"][5]["content"]="Please describe what the device shows."
        run=normalize(doc)[0]
        self.assertEqual(sum(e["kind"]=="action" for e in run["events"]),0)
        self.assertEqual(sum(e["kind"]=="external_action" for e in run["events"]),1)
        for unit in units(run):
            if unit["eligible"]:
                evidence=str(packet(run,unit["id"]))
                self.assertNotIn("PRIVATE_SIMULATOR_COMMENT",evidence)
                self.assertNotIn("PRIVATE_CUSTOMER_DEVICE_STATE",evidence)

    def test_truncated_current_tool_contract_is_required_evidence(self):
        doc=source();doc["tools"][0]["function"]["description"]="x"*9000
        run=normalize(doc)[0];action=next(u for u in units(run) if u["kind"]=="action_dispatch")
        self.assertEqual(packet(run,action["id"])["state"]["missingness"]["required_truncated_event_ids"],["tool_contract:/tools/0"])


if __name__=="__main__":unittest.main()
