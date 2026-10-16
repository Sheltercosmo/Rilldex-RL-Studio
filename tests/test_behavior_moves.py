import copy
import json
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.activity import units
from tracker.behavior_moves import MoveClient, FUNCTIONS, partitions, project
from tracker.schema import InputError, dumps
from tracker.store import Store
from research.occurrence_controls import fixed_response


def fixture(text='The output is True, which means the check failed.'):
    run=normalize({'schema_version':'ATIF-v1.7','session_id':'moves-test','agent':{'name':'test','version':'1'},
        'steps':[{'step_id':1,'source':'agent','message':text},
                 {'step_id':2,'source':'agent','message':'FUTURE RESULT MUST BE EXCLUDED.'}]})[0]
    return run,next(u['id'] for u in units(run) if u['eligible'])


def response(req):
    if req['state']['stage']=='partition':
        selected=max(req['state']['partitions'],key=lambda p:len(p['moves']))['id']
        return fixed_response(req,lambda k,q:selected)
    first=req['state']['moves'][0]['id']
    result=fixed_response(req,lambda k,q:('state' if k.startswith(first) else 'derive') if k.endswith('__function') else 'asserted')
    for a in result['answers'].values():a.update(choice='unresolved',confidence=0)
    return result


class MoveTests(unittest.TestCase):
    def test_partition_preserves_unicode_code_and_purpose(self):
        run,uid=fixture('Since 😀 `a, and b` is false, we need to modify the item to fix it.')
        req=MoveClient().request(run,uid);s=req['state']['subject'];ps=req['state']['partitions']
        self.assertGreater(len(ps),1)
        for p in ps:
            self.assertEqual(''.join(m['text'] for m in p['moves']),s['text'])
            for m in p['moves']:self.assertEqual(s['text'][m['start']-s['start']:m['end']-s['start']],m['text'])
        self.assertTrue(all(not m['text'].startswith('and b') for p in ps for m in p['moves']))
        self.assertTrue(all(not m['text'].startswith('to fix') for p in ps for m in p['moves']))
        fake={**s,'text':'a; b; c; d; e; f; g; h; i'}
        _,coverage=partitions(fake);self.assertEqual(len(coverage['omitted_cut_offsets']),2)
        self.assertGreater(coverage['omitted_subsets'],0)

    def test_selected_partition_exclusive_functions_and_separate_status(self):
        run,uid=fixture();client=MoveClient(transport=response);saved=client.evaluate(run,uid);rows=project(saved)['moves']
        self.assertEqual([r['function']['value'] for r in rows],['state','derive'])
        self.assertTrue(all(r['function']['confidence']==0 for r in rows))
        self.assertEqual([r['status']['value'] for r in rows],['asserted','asserted'])
        qs=saved['_function_request']['questions'];self.assertEqual(len(qs),4)
        self.assertTrue(all(set(q['criteria'])==set(FUNCTIONS) for k,q in qs.items() if k.endswith('__function')))
        self.assertNotIn('FUTURE RESULT',str(saved));self.assertNotIn('activity_definitions',str(saved))
        self.assertTrue(client.cache_matches(json.loads(dumps(saved)),run,uid))

    def test_function_failure_resumes_without_repeating_partition(self):
        run,uid=fixture();calls=[];checkpoints=[]
        def fail(req):
            calls.append(req['state']['stage'])
            if len(calls)==2:raise InputError('temporary failure')
            return response(req)
        client=MoveClient(transport=fail)
        with self.assertRaises(InputError):client.evaluate(run,uid,checkpoint=lambda s:checkpoints.append(json.loads(dumps(s))) or True)
        saved=client.evaluate(run,uid,resume=checkpoints[-1]);self.assertEqual(calls,['partition','functions','functions'])
        self.assertTrue(client.cache_matches(saved,run,uid))
        changed=copy.deepcopy(run);changed['events'][0]['text']='Changed source'
        self.assertFalse(client.cache_matches(saved,changed,uid))
        bad=copy.deepcopy(saved);bad['_functions'].pop(next(iter(bad['_functions'])))
        self.assertFalse(client.cache_matches(bad,run,uid))

    def test_missing_partition_does_not_invent_a_move(self):
        run,uid=fixture();calls=[]
        def missing(req):calls.append(req);return fixed_response(req,lambda k,q:'no_suitable_candidate')
        client=MoveClient(transport=missing);saved=client.evaluate(run,uid)
        self.assertEqual(len(calls),1);self.assertEqual(project(saved)['moves'],[])
        self.assertEqual(project(saved)['partition_choice'],'no_suitable_candidate')
        self.assertTrue(client.cache_matches(saved,run,uid))

    def test_raw_conflicts_are_not_repaired_or_counted_as_validated(self):
        run,uid=fixture('We should test the result.')
        def conflict(req):
            if req['state']['stage']=='partition':return response(req)
            return fixed_response(req,lambda k,q:'propose' if k.endswith('__function') else 'attempted')
        saved=MoveClient(transport=conflict).evaluate(run,uid);move=project(saved)['moves'][0]
        self.assertEqual(move['function']['value'],'propose');self.assertEqual(move['status']['value'],'attempted')
        self.assertEqual(len(move['review_reasons']),1)
        self.assertEqual(move['field_extraction_status'],'not_started')

    def test_store_import_immutable_independent_from_activity_routing(self):
        with tempfile.TemporaryDirectory() as temp:
            run,uid=fixture();store=Store(Path(temp)/'s.sqlite');store.add([run]);before=store.get(run['id'],raw=True)
            saved=MoveClient(transport=response).evaluate(run,uid)
            store.record_moves(run['id'],uid,saved);store.record_moves(run['id'],uid,json.loads(dumps(saved)))
            after=store.get(run['id'],raw=True)
            self.assertEqual(before['activity'],after['activity']);self.assertEqual(before['unit_graph'],after['unit_graph'])
            self.assertEqual(len(after['move_observation_history']),1)
            self.assertNotIn('behavior_moves',after)
            self.assertEqual(len(project(after['move_observation_history'][0]['result'])['moves']),2)
            bad=copy.deepcopy(saved);bad['_provenance']['elapsed_seconds']=12345
            with self.assertRaises(InputError):store.record_moves(run['id'],uid,bad)
            bad=copy.deepcopy(saved);bad['_functions'].clear()
            with self.assertRaises(InputError):store.record_moves(run['id'],uid,bad)
