"""Common event contracts across provider item formats and downstream readers."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from rilldex import responses_document, chat_sessions_document
from tracker.adapters import normalize
from tracker.activity import units, packet as activity_packet
from tracker.capabilities import links
from tracker.graph_store import build
from tracker.import_batch import read_bytes
from tracker.jev import packet
from tracker.schema import InputError, dumps
from tracker.semantic_extraction import generation_request
from tracker.semantic_map import evidence
from tracker.store import Store
from tracker.work_order import Evidence


def fixture():
    return responses_document([
        {'role':'system','content':'Inspect stock before reserving. Do not exceed available stock.'},
        {'role':'user','content':[{'type':'input_text','text':'Reserve two seats on service T7.'}]},
        {'type':'reasoning','id':'rs1','summary':[{'type':'summary_text','text':'I will inspect the service and then reserve the seats.'}],
         'encrypted_content':'PRIVATE_ENCRYPTED_REASONING'},
        {'type':'function_call','id':'fc1','call_id':'c1','name':'dispatch','arguments':'{"service":"T7"}','status':'completed'},
        {'type':'function_call_output','call_id':'c1','output':'There are 3 seats available.'},
        {'type':'custom_tool_call','id':'ct1','call_id':'c2','name':'reserve','input':'service T7; seats 2','status':'completed'},
        {'type':'custom_tool_call_output','call_id':'c2','output':[{'type':'input_text','text':'Reservation accepted.'}]},
        {'type':'message','id':'m1','role':'assistant','content':[{'type':'output_text','text':'Two seats reserved.'}]},
    ], tools=[{'type':'function','name':'dispatch','description':'Read availability for a service without changing it.',
               'parameters':{'type':'object','properties':{'service':{'type':'string'}}}},
              {'type':'custom','name':'reserve','description':'Reserve seats using the supplied service and count.'}])


class ResponsesItemsTests(unittest.TestCase):
    def test_native_ids_payloads_summaries_and_source_pointers_survive(self):
        doc=fixture();original=deepcopy(doc);run=normalize(doc)[0]
        self.assertEqual(run['adapter_version'],'responses-items/1')
        self.assertEqual(doc,original);self.assertEqual(run['raw'],original)
        actions=[e for e in run['events'] if e['kind']=='action']
        self.assertEqual([a['call_id'] for a in actions],['c1','c2'])
        self.assertEqual(actions[1]['arguments'],{'input':'service T7; seats 2'})
        self.assertEqual(actions[1]['source_item_id'],'ct1')
        self.assertEqual(actions[1]['source_pointer'],'/items/5')
        self.assertEqual(actions[0]['tool_contract']['source_pointer'],'/tools/0')
        self.assertIsNone(run['outcome']['verified_success'])
        summary=next(e for e in run['events'] if e.get('channel')=='reasoning_summary')
        self.assertEqual(summary['source_text_parts'][0]['source_pointer'],'/items/2/summary/0/text')
        self.assertNotIn('PRIVATE_',dumps(run['events']))
        self.assertEqual(len(links(run)['records']),2)
        self.assertFalse(any('parent_id' in a for a in actions))

    def test_macro_reads_local_purpose_without_inventing_a_parent(self):
        doc=responses_document([
            {'role':'user','content':'Investigate device A7.'},
            {'role':'assistant','content':'Read the device to test whether calibration produced 3.3 volts.'},
            {'type':'function_call','call_id':'c1','name':'dispatch','arguments':'{"device":"A7"}'}],
            tools=[{'type':'function','name':'dispatch','description':'Read the current sensor voltage.'}])
        run=normalize(doc)[0];action=run['events'][-1];state=packet(run,action['id'])['state']
        self.assertIsNone(state['parent_expression'])
        self.assertIn('test whether calibration',state['recent_expressions'][-1]['text'])
        self.assertNotIn('parent_id',action)

    def test_malformed_namespace_is_a_capture_error_not_an_internal_exception(self):
        for where in ('definition','call'):
            doc=fixture()
            target=doc['tools'][0] if where=='definition' else doc['items'][3]
            target['namespace']={'invalid':'object'}
            with self.assertRaisesRegex(InputError,'namespace'):normalize(doc)

    def test_parallel_requests_and_reverse_results_keep_native_correspondence(self):
        doc=fixture();a=doc['items'][3];b=deepcopy(a);b.update(id='fc2',call_id='parallel',arguments='{"service":"T8"}')
        doc['items'][4:4]=[b,{'type':'function_call_output','call_id':'parallel','output':'T8 result'}]
        run=normalize(doc)[0];linked=links(run)
        self.assertEqual(len(linked['records']),3)
        self.assertEqual(len(linked['parallel_action_groups']),1)
        by_id={e['id']:e for e in run['events']}
        for row in linked['records']:
            self.assertEqual(by_id[row['action_id']]['call_id'],by_id[row['feedback_id']]['source_call_id'])
        ordering=Evidence(by_id)
        self.assertFalse(ordering.is_ordered(next(e['id'] for e in run['events'] if e.get('call_id')=='c1')))

    def test_all_three_semantic_readers_receive_contracts_and_prefix_only(self):
        run=normalize(fixture())[0]
        a=next(e for e in run['events'] if e.get('call_id')=='c1')
        u=next(u for u in units(run) if u['event_id']==a['id'])
        for req in (packet(run,a['id']),activity_packet(run,u['id']),
                    generation_request(run,evidence(run,a['id']),'inspect')):
            self.assertIn('Read availability',dumps(req))
            self.assertNotIn('There are 3 seats',dumps(req))
            self.assertNotIn('Reservation accepted',dumps(req))
            self.assertNotIn('PRIVATE_',dumps(req))
        summary=next(u for u in units(run) if 'inspect the service' in u['text'])
        self.assertIn('/tools/1',dumps(activity_packet(run,summary['id'])))

    def test_mixed_agent_sessions_keep_local_ids_definitions_and_offsets(self):
        a=fixture();b=fixture();b['tools'][0]['description']='Only this second context has this definition.'
        doc=chat_sessions_document([{**a,'trajectory_id':'agent','context_id':'first'},
                                    {**b,'trajectory_id':'agent','context_id':'reset'}])
        run=normalize(doc)[0];self.assertEqual(len(links(run)['records']),4)
        action=next(e for e in run['events'] if e.get('call_id')=='c1' and e['context_id']=='first')
        req=packet(run,action['id'])
        self.assertNotIn('Only this second',dumps(req))
        self.assertIn('/sessions/0/tools/0',dumps(req))
        part=next(e for e in run['events'] if e.get('source_text_parts'))['source_text_parts'][0]
        self.assertTrue(part['source_pointer'].startswith('/sessions/0/items/'))

    def test_json_jsonl_store_and_source_graph_preserve_the_same_evidence(self):
        doc=fixture();run=normalize(doc)[0]
        for name in ('responses.json','responses.jsonl'):
            imported=read_bytes(dumps(doc).encode(),name=name,meta={'experiment':'responses-test'})[0]
            self.assertEqual(run['events'],imported['events'])
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'store.sqlite');store.add([run])
            saved=store.get(run['id'],raw=True)['run']
            self.assertEqual(saved['events'],run['events'])
            self.assertEqual(build(saved)['edges'],build(run)['edges'])

    def test_missing_refs_and_encrypted_items_are_explicit_gaps(self):
        doc=responses_document([{'type':'item_reference','id':'missing'},
            {'type':'reasoning','id':'r1','summary':[],'encrypted_content':'PRIVATE_DATA'},
            {'role':'user','content':'Continue the work.'}])
        run=normalize(doc)[0]
        self.assertEqual(run['events'][0]['context_kind'],'uninterpreted_response_item')
        self.assertEqual(run['events'][1]['context_kind'],'unobserved_reasoning')
        self.assertFalse(any(e['kind']=='action' for e in run['events']))
        self.assertNotIn('PRIVATE_DATA',dumps(run['events']))
        self.assertTrue(any('item_reference' in w for w in run['warnings']))

    def test_unknown_media_is_not_dropped_or_read_as_text(self):
        doc=fixture();doc['items'][4]['output']=[{'type':'input_text','text':'See the chart.'},
            {'type':'input_image','image_url':'https://example.invalid/chart.png'}]
        run=normalize(doc)[0];feedback=next(e for e in run['events'] if e['kind']=='feedback')
        self.assertEqual(feedback['text'],'See the chart.')
        self.assertEqual(feedback['media'][0]['type'],'input_image')
        self.assertTrue(any('have not been inspected' in w for w in run['warnings']))

    def test_invalid_attempts_stay_visible_but_bad_capture_identity_is_rejected(self):
        doc=fixture();doc['items'][3]['arguments']='{unfinished'
        run=normalize(doc)[0]
        self.assertEqual(next(e for e in run['events'] if e['kind']=='action')['argument_status'],'invalid_json_object')
        for mutation in ('duplicate_call','duplicate_item','wrong_result','raw_response','unmarked','mixed'):
            doc=fixture()
            if mutation=='duplicate_call':doc['items'][5]['call_id']='c1'
            elif mutation=='duplicate_item':doc['items'][5]['id']='fc1'
            elif mutation=='wrong_result':doc['items'][4]['type']='custom_tool_call_output'
            elif mutation=='raw_response':doc={'object':'response','output':doc['items']}
            elif mutation=='unmarked':doc.pop('trajectory_format')
            else:doc['messages']=[]
            with self.subTest(mutation=mutation),self.assertRaises(InputError):normalize(doc)


if __name__=='__main__':unittest.main()
