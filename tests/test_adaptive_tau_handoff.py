"""Policy boundary checks; these are not reference labels for agent quality."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('adaptive_tau',Path(__file__).resolve().parents[1]/'scripts/run_adaptive_tau.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


class AdaptiveTauHandoffTests(unittest.TestCase):
    def packet(self,role='assistant'):return {'role':role,'messages':[]}

    def respond(self,message,role='assistant'):
        p=self.packet(role)
        return h.validate_response(p,{'request_hash':h.digest(p),'message':message})

    def test_customer_never_sees_agent_tools_or_results(self):
        messages=[{'role':'user','content':'My request'},
            {'role':'assistant','content':None,'tool_calls':[{'name':'private_lookup','arguments':{}}]},
            {'role':'tool','content':'Private reservation'},
            {'role':'assistant','content':'What I chose to tell the customer','raw_data':'provider metadata'}]
        user=h.visible_messages(messages,'user')
        self.assertEqual(user,[{'role':'user','content':'My request'},
            {'role':'assistant','content':'What I chose to tell the customer'}])
        service=h.visible_messages(messages,'assistant');service[0]['content']='changed'
        self.assertEqual(messages[0]['content'],'My request')
        self.assertEqual(service[2]['content'],'Private reservation')

    def test_stale_and_extra_fields_rejected(self):
        packet=self.packet()
        with self.assertRaisesRegex(ValueError,'different request'):
            h.validate_response(packet,{'request_hash':'old','message':{'content':'a'}})
        with self.assertRaises(ValueError):self.respond({'content':'a','hidden_reasoning':'b'})

    def test_native_turn_contract(self):
        call={'name':'lookup','arguments':{'id':'a'}}
        self.assertEqual(self.respond({'content':None,'tool_calls':[call]})['tool_calls'],[call])
        self.assertEqual(self.respond({'content':'Hello'},'user')['content'],'Hello')
        for message in [{'content':''},{'content':'x','tool_calls':[call]},
                        {'tool_calls':[call,call]},{'tool_calls':[{'name':'x','arguments':'{}'}]}]:
            with self.assertRaises(ValueError):self.respond(message)
        with self.assertRaises(ValueError):self.respond({'tool_calls':[call]},'user')


if __name__=='__main__':unittest.main()
