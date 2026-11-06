"""Source recall, exact citations, state order and no cross-history leakage."""
from copy import deepcopy
import unittest

from tracker.adapters import normalize
from tracker.activity import packet, units
from tracker.readable_context import contains, resolve_quote
from tracker.semantic_extraction import prefix, context_scope, generation_request
from tracker.semantic_map import evidence
from tracker.semantic_workspace import DEFAULT_CONTEXT
from tracker.source_retrieval import select
from tracker.schema import dumps, InputError


def fixture():
    messages=[{'role':'user','content':'Investigate device A7.'},
              {'role':'assistant','content':'I conclude that device A7 is defective.'}]
    for i in range(15):
        messages += [{'role':'assistant','content':f'Inspect station {i}.','tool_calls':[
            {'id':f'c{i}','type':'function','function':{'name':'read','arguments':'{}'}}]},
            {'role':'tool','tool_call_id':f'c{i}','content':f'Weather station {i} temperature is 20.'}]
    messages.append({'role':'assistant','content':'I retract my earlier conclusion that device A7 is defective.'})
    run=normalize({'messages':messages})[0]
    return run,evidence(run,run['events'][-1]['id'])


class SourceRetrievalTests(unittest.TestCase):
    def test_distant_statement_retained_in_both_readers_and_old_policy_replays(self):
        run,ref=fixture();old=deepcopy(run)
        baseline,_=prefix(run,ref,{**DEFAULT_CONTEXT,'schema':'readable-context/4'})
        current,_=prefix(run,ref,DEFAULT_CONTEXT)
        self.assertNotIn('e2',[e['id'] for e in baseline])
        self.assertIn('e2',[e['id'] for e in current]);self.assertEqual(old,run)
        u=next(u for u in units(run) if u['event_id']==ref['event_id'])
        req=packet(run,u['id']);earlier=next(u for u in units(run) if u['event_id']=='e2')
        self.assertIn(earlier['id'],req['questions']['revision_target']['criteria'])
        self.assertLessEqual(len(req['state']['earlier_units']),12)

    def test_long_middle_match_is_readable_and_source_quote_resolves(self):
        run,ref=fixture();first=run['events'][1]
        first['text']='unrelated telemetry '*450+'device A7 is defective'+' unrelated samples'*450
        current,_=prefix(run,ref,DEFAULT_CONTEXT)
        match=next(e for e in current if e['id']==first['id'])
        offset=first['text'].index('device A7')
        self.assertIn('device A7 is defective',match['text'])
        self.assertTrue(contains(match,{'start':offset,'end':offset+len('device A7 is defective')}))
        citation=resolve_quote(run,current,{'event_id':first['id'],'quote':'device A7 is defective'})
        self.assertEqual(citation['start'],offset)
        req=generation_request(run,ref,'assess',context_policy=DEFAULT_CONTEXT)
        self.assertEqual(req['prefix'],current)

    def test_future_other_context_hidden_and_unknown_order_cannot_affect_retrieval(self):
        run,ref=fixture();original,_=prefix(run,ref,DEFAULT_CONTEXT)
        for kind in ('future','context','private','copied','unordered'):
            candidate=deepcopy(run);bad=deepcopy(candidate['events'][1]);bad['id']='distractor';bad['text']='device A7 is defective '*100
            if kind=='future':bad['index']=candidate['events'][-1]['index']+1;candidate['events'].append(bad)
            else:
                if kind=='context':bad['context_id']='different'
                elif kind=='private':bad['agent_visible']=False
                elif kind=='copied':bad['copied_context']=True
                else:bad['order_known']=False
                candidate['events'].insert(2,bad)
            selected,_=prefix(candidate,ref,DEFAULT_CONTEXT)
            self.assertEqual(selected,original,kind)

    def test_latest_matching_state_and_native_dispatch_stay_in_source_order(self):
        run,ref=fixture()
        feedback=[e for e in run['events'] if e['kind']=='feedback']
        feedback[0]['text']='Device A7 status disabled.'
        feedback[-1]['text']='Device A7 status enabled; replaces its previous disabled status.'
        selected,_=prefix(run,ref,DEFAULT_CONTEXT)
        ids=[e['id'] for e in selected]
        self.assertLess(ids.index(feedback[0]['id']),ids.index(feedback[-1]['id']))
        dispatch=next(e for e in run['events'] if e.get('call_id')==feedback[0]['source_call_id'])
        self.assertIn(dispatch['id'],ids)
        report=context_scope(run,ref,DEFAULT_CONTEXT)['context_projection']['source_retrieval']
        self.assertTrue(all(r['event_id'] in ids for r in report['selected']))

    def test_no_match_and_binary_payload_do_not_invent_context(self):
        report=select([{'id':'a','text':'data:image/png;base64,'+'SECRET'*100}], 'SECRET')
        self.assertEqual(report['selected'],[])
        self.assertEqual(select([{'id':'a','text':'device B9'}],'volcano')['selected'],[])
        with self.assertRaises(InputError):select([], 'test',limit=0)

    def test_only_observed_history_reaches_all_semantic_generation_stages(self):
        run,ref=fixture()
        from tracker.semantic_extraction import request
        for stage in ('activity','content','plan_structure','feedback','requested_work_correspondence'):
            req=request(run,ref,stage,'Read this source.',{'yes':'supported','unresolved':'unknown'},context_policy=DEFAULT_CONTEXT)
            self.assertIn('I conclude that device A7',dumps(req))
            self.assertIn('source-prefix-retrieval/1',dumps(req))
