import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import diagnostic_direct as direct, diagnostic_search as search
from tracker.schema import dumps
from tracker.diagnostic_worker import CallBudgetReached


def source(records):
    return dict(schema='diagnostic-input/1', id='payload-test', task='Recorded task', trace=dumps(records),
                complete_recorded_text=True, action_coverage='recorded')


class DiagnosticPayloadTests(unittest.TestCase):
    def test_complete_native_command_and_lossless_coverage(self):
        s=source([dict(id='a',actor='agent',kind='action',text='write '+('line\n'*600))])
        old=search.index(s,search.ACCESS_VERSION);new=search.index(s,search.PAYLOAD_VERSION)
        self.assertGreater(sum(f['origin']=='trace' for f in old),1)
        self.assertEqual(sum(f['origin']=='trace' for f in new),1)
        self.assertEqual(new[0]['text'],s['trace'])
        self.assertEqual(new[0]['actor'],'agent')

    def test_embedded_command_in_unknown_export_preserves_object_without_actor_inference(self):
        command=json.dumps({'tool':'edit_file','source':['print("😀")']*300},ensure_ascii=False,indent=2)
        s=source([dict(role='trace',content='LLM_OUTPUT:\n'+command+'\nTOOL_OUTCOME: added')])
        fragments=search.index(s,search.PAYLOAD_VERSION)
        self.assertEqual(''.join(f['text'] for f in fragments if f['origin']=='trace'),s['trace'])
        containing=[f for f in fragments if 'edit_file' in f['text']]
        self.assertEqual(len(containing),1)
        self.assertGreater(len(containing[0]['text']),search.FRAGMENT_CHARS)
        self.assertNotIn('actor',containing[0])
        self.assertIn('😀',containing[0]['text'])

    def test_quoted_user_and_returned_commands_keep_their_recorded_roles(self):
        payload=json.dumps({'command':'write '+('code '*500)})
        s=source([dict(role='user',content='[action] '+payload),dict(role='tool',content=payload),
                  dict(role='assistant',content='I will consider that example.')])
        for f in search.index(s,search.PAYLOAD_VERSION):
            if 'command' in f['text']:
                self.assertIn(f['actor'],{'user','tool'})
                self.assertFalse(search.candidate_compatible('evaluator_bypass','action',f))

    def test_oversize_and_malformed_content_falls_back_without_loss(self):
        s=source([dict(role='trace',content='[action] {bad json}\n'+json.dumps({'command':'x'*40000}))])
        fs=search.index(s,search.PAYLOAD_VERSION)
        self.assertEqual(''.join(f['text'] for f in fs if f['origin']=='trace'),s['trace'])
        self.assertTrue(all(len(f['text'])<=search.PAGE_CHARS for f in fs))
        for page in search.pages(fs):
            self.assertLessEqual(sum(len(f['text']) for f in page),search.PAGE_CHARS)
            self.assertLessEqual(sum(len(dumps(f)) for f in page),search.PAGE_SERIALIZED_CHARS)

    def test_legacy_protocol_unchanged_and_request_budget_resumable(self):
        s=source([dict(role='assistant',content=json.dumps({'command':'echo '+('x '*1800)})) for _ in range(6)])
        self.assertNotIn('payload_boundaries',search.protocol(search.ACCESS_VERSION))
        calls=[]
        def transport(req):
            calls.append(req)
            return dict(model=req['model'],answers={key:dict(type='choice',probabilities={k:int(k=='none') for k in q['criteria']}) for key,q in req['questions'].items()})
        def limited(req):
            if calls:raise CallBudgetReached()
            return transport(req)
        with TemporaryDirectory() as temp:
            result=search.execute(s,Path(temp),limited,version=search.PAYLOAD_VERSION)
            self.assertFalse(result['coverage']['scan_complete'])
            self.assertTrue(all(v['value'] is None for v in result['metrics'].values()))
            done=search.execute(s,Path(temp),transport,version=search.PAYLOAD_VERSION)
            self.assertTrue(done['coverage']['scan_complete'])
            self.assertEqual(len(calls),done['coverage']['pages_total'])
            self.assertTrue(search.audit(s,done,temp)['exact_replay'])
            for req in calls:self.assertLessEqual(len(dumps(req)),search.REQUEST_CHARS)

    def test_escape_expansion_cannot_exceed_serialized_page_limit(self):
        s=source([dict(id='a',actor='agent',kind='action',text='\\'*7970)])
        self.assertLess(len(s['trace']),search.PAGE_CHARS)
        fragments=search.index(s,search.PAYLOAD_VERSION)
        self.assertGreater(sum(f['origin']=='trace' for f in fragments),1)
        self.assertEqual(''.join(f['text'] for f in fragments if f['origin']=='trace'),s['trace'])
        for page in search.pages(fragments):
            self.assertLessEqual(sum(len(dumps(f)) for f in page),search.PAGE_SERIALIZED_CHARS)
