"""Continuation preserves the visible source and never skips budget omissions."""
from copy import deepcopy
import unittest
from tracker.source_evidence import search
from tracker.schema import InputError
from test_source_evidence import chat


class EvidencePageTests(unittest.TestCase):
    def setUp(self):
        self.run=chat([dict(role='assistant',content='quasar evidence '+str(i)) for i in range(23)]+[
            dict(role='assistant',content='Review the recorded work.')])
        self.query=dict(anchor={'event_id':self.run['events'][-1]['id']},text='quasar',limit=4,max_chars=4000)

    def test_all_ranked_events_can_be_reached_without_repeated_primary_matches(self):
        query=dict(self.query);ids=[];packets=[]
        while True:
            packet=search(self.run,query);packets.append(packet)
            self.assertLessEqual(packet['coverage']['source_text_chars'],4000)
            ids.extend(m['event_id'] for m in packet['matches'])
            if packet['pagination']['next_cursor'] is None:break
            query['cursor']=packet['pagination']['next_cursor']
            self.assertLess(len(packets),10)
        self.assertEqual(len(ids),23);self.assertEqual(len(set(ids)),23)
        self.assertEqual([m['rank'] for p in packets for m in p['matches']],list(range(1,24)))
        self.assertTrue(packets[-1]['pagination']['exhausted'])
        self.assertEqual(search(self.run,packets[2]['query']),packets[2])

    def test_short_budget_does_not_skip_deferred_candidates(self):
        run=chat([dict(role='assistant',content='quasar '+str(i)+'x'*1400) for i in range(9)]+[
            dict(role='assistant',content='Review.')])
        query=dict(anchor={'event_id':run['events'][-1]['id']},text='quasar',limit=8,max_chars=2000)
        first=search(run,query);second=search(run,dict(query,cursor=first['pagination']['next_cursor']))
        self.assertEqual(first['pagination']['next_cursor']['offset'],6)
        omitted=next(x['event_id'] for x in first['coverage']['deferred'] if x['reason']['kind']=='lexical_match')
        self.assertEqual(second['matches'][0]['event_id'],omitted)

    def test_cursor_binds_visible_source_query_and_budget(self):
        first=search(self.run,self.query);query=dict(self.query,cursor=first['pagination']['next_cursor'])
        for change in [dict(text='different'),dict(limit=3),dict(max_chars=3000),dict(strategy='source_and_calls')]:
            with self.subTest(change=change),self.assertRaisesRegex(InputError,'changed'):
                search(self.run,dict(query,**change))
        changed=deepcopy(self.run);changed['events'][0]['text']='changed earlier source'
        with self.assertRaisesRegex(InputError,'changed'):search(changed,query)
        future=deepcopy(self.run['events'][0]);future.update(id='future',index=999,text='quasar unseen')
        extended=deepcopy(self.run);extended['events'].append(future)
        before=search(self.run,query);after=search(extended,query)
        for key in ('pagination','matches','records'):self.assertEqual(before[key],after[key])

    def test_multiquestion_pages_keep_unique_matches_and_no_answer_claim(self):
        query=dict(self.query,questions=[dict(id='a',text='quasar'),dict(id='b',text='evidence')])
        first=search(self.run,query);second=search(self.run,dict(query,cursor=first['pagination']['next_cursor']))
        self.assertFalse({m['event_id'] for m in first['matches']} & {m['event_id'] for m in second['matches']})
        self.assertEqual({q['id'] for q in second['questions']},{'a','b'})
        self.assertTrue(all(q['status']=='candidates_retained' for q in second['questions']))

    def test_invalid_or_exhausted_cursors_fail_and_no_match_has_no_continuation(self):
        for cursor in [False,{},dict(search_id='bad',offset=1),dict(search_id='evidence-search-'+'0'*64,offset=True)]:
            with self.subTest(cursor=cursor),self.assertRaises(InputError):search(self.run,dict(self.query,cursor=cursor))
        p=search(self.run,self.query)
        with self.assertRaisesRegex(InputError,'outside'):search(self.run,dict(self.query,cursor=dict(p['pagination']['next_cursor'],offset=999)))
        empty=search(self.run,dict(self.query,text='notpresent'))
        self.assertTrue(empty['pagination']['exhausted']);self.assertIsNone(empty['pagination']['next_cursor'])

    def test_sdk_and_http_continue_exact_saved_source(self):
        import json
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from rilldex import Workspace
        from tracker.schema import digest
        from test_generation_cohort_transport import GenerationCohortTransportTests
        fixture=GenerationCohortTransportTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.store.add([self.run]);ws=Workspace(fixture.store.path)
        first=ws.search_evidence(self.run['id'],**self.query)
        second=ws.search_evidence(self.run['id'],**self.query,cursor=first['pagination']['next_cursor'])
        self.assertEqual(second['pagination']['offset'],4)
        endpoint=fixture.start_server()
        def call(query):
            body=dict(schema='investigation-plan/1',nodes=[dict(name='evidence',op='evidence_search',inputs=[],
                params=dict(run_id=self.run['id'],source_hash=digest(self.run),query=query))])
            req=Request(endpoint+'/api/investigation-plans',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=15) as r:return json.load(r)
        result=call(second['query']);self.assertEqual(result['outputs']['evidence'],second)
        again=call(second['query']);self.assertEqual(again['id'],result['id'])
        with self.assertRaises(HTTPError) as err:
            call(dict(second['query'],text='changed query'))
        self.assertEqual(err.exception.code,400)


if __name__=='__main__':unittest.main()
