from copy import deepcopy
from unittest import TestCase
from tracker.packet_interning import compact,expand,FIELD,REF
from tracker.schema import InputError,dumps


class PacketInterningTests(TestCase):
    def test_exact_roundtrip_preserves_distinct_events_and_arguments(self):
        contract={'name':'book','schema':{'required':['passenger'],'description':'Full tool contract '*100}}
        original={'state':{'prefix':[{'id':'e1','text':'First action','arguments':{'passenger':'Alice'},'tool_contract':contract},
                   {'id':'e2','text':'Second action','arguments':{'passenger':'Bob'},'tool_contract':deepcopy(contract)},
                   {'id':'e3','text':'Response'},{'id':'e4','tool_contract':{'name':'unique'}}]},'questions':{'unchanged':True}}
        saved=deepcopy(original);encoded=compact(original)
        self.assertEqual(original,saved);self.assertEqual(expand(encoded),original)
        self.assertLess(len(dumps(encoded)),len(dumps(original)))
        self.assertEqual(len(encoded['state'][FIELD]['definitions']),1)
        self.assertNotEqual(encoded['state']['prefix'][0]['arguments'],encoded['state']['prefix'][1]['arguments'])
        self.assertIn('tool_contract',encoded['state']['prefix'][3])

    def test_different_contracts_do_not_merge(self):
        original={'state':{'prefix':[{'tool_contract':{'name':'x','v':1}},{'tool_contract':{'name':'x','v':2}}]}}
        self.assertEqual(compact(original),original);self.assertEqual(expand(original),original)

    def test_mutated_definition_dangling_reference_and_duplicate_field_rejected(self):
        original={'state':{'prefix':[{'tool_contract':{'name':'x'}},{'tool_contract':{'name':'x'}}]}}
        encoded=compact(original);key=encoded['state']['prefix'][0][REF]
        for mutation in ['definition','reference','duplicate','unused']:
            bad=deepcopy(encoded)
            if mutation=='definition':bad['state'][FIELD]['definitions'][key]['name']='changed'
            elif mutation=='reference':bad['state']['prefix'][0][REF]='missing'
            elif mutation=='duplicate':bad['state']['prefix'][0]['tool_contract']={}
            else:bad['state']['prefix']=[]
            with self.assertRaises(InputError):expand(bad)
        with self.assertRaises(InputError):compact(encoded)
