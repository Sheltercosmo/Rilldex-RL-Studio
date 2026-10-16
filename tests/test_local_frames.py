import copy
import json
from pathlib import Path
import tempfile
import unittest

from tracker.activity import ActivityClient, analyze
from tracker.adapters import normalize
from tracker.entity_extraction import EntityClient
from tracker.jobs import Worker
from tracker.local_frames import FrameClient, sources, frames, is_extension, token_candidates, project_graph, attachment_differences
from tracker.schema import InputError, dumps
from tracker.store import Store
from research.occurrence_controls import fixed_response


TEXT = 'We will modify the method to exclude the key from the comparison.'


def fixture(path):
    run = normalize({'schema_version': 'ATIF-v1.7', 'session_id': 'frame-fixture', 'agent': {'name': 'test', 'version': '1'},
        'steps': [{'step_id': 1, 'source': 'agent', 'message': TEXT}, {'step_id': 2, 'source': 'agent', 'message': 'Later evidence: success.'}]})[0]
    store = Store(path); store.add([run]); uid = next(u['id'] for u in analyze(run)['units'] if u['eligible'])
    base = ActivityClient(transport=lambda r: fixed_response(r, lambda k,q: 'present' if k == 'plan' else 'intended' if k == 'expression' else 'not_applicable' if k == 'revision_target' else 'absent')).evaluate(run, uid)
    store.record_activity(run['id'], uid, base)
    def local(req):
        return fixed_response(req, lambda k,q: ('local_expression' if k == 'plan__intended_operation' else 'no_local_expression') if req['state']['stage'] == 'field_presence' else next(iter(q['criteria'])))
    worker = Worker(store, entities=True, autostart=False, client=EntityClient(transport=local))
    worker.submit(run['id']); worker._process(worker._claim()); worker.close()
    return store, run, uid


def response(req):
    state = req['state']
    if state['stage'] == 'predicate_heads':
        cs = {key+'@'+c['id']: c for key,f in state['fields'].items() for c in f['candidates']}
        return fixed_response(req, lambda k,q: 'covered' if k.endswith('@coverage') else 'predicate_head' if cs[k]['text'] in {'modify','exclude'} else 'not_predicate_head')
    cs = {c['id']: c for c in state['candidates']}; head = state['frame']['head']['text']
    r = fixed_response(req, lambda k,q: 'subject' if cs[k]['text'] == 'We' else 'direct_object' if cs[k]['text'] in ({'the method','method'} if head == 'modify' else {'the key','key'}) else 'oblique' if head == 'exclude' and cs[k]['text'] in {'the comparison','comparison'} else 'other_predicate')
    for a in r['answers'].values(): a.update(choice='unresolved', confidence=0)
    return r


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store, self.run, self.uid = fixture(Path(self.tmp.name)/'s.sqlite')
        self.bundle = self.store.get(self.run['id'],raw=True); self.nodes = self.bundle['unit_graph']['nodes']

    def test_separate_heads_own_arguments_without_entity_or_activity_mutation(self):
        original = copy.deepcopy(self.nodes); client = FrameClient(nodes=self.nodes,transport=response)
        saved = client.evaluate(self.run,self.uid); projected = frames(saved)
        self.assertEqual([f['head']['text'] for f in projected],['modify','exclude'])
        for f in projected:
            objects = {a['candidate']['text'] for a in f['arguments'] if a['decision']['value']=='direct_object'}
            self.assertEqual(objects, {'the method','method'} if f['head']['text']=='modify' else {'the key','key'})
            self.assertTrue(all(a['decision']['selection_policy']=='argmax/1' and a['decision']['confidence']==0 for a in f['arguments']))
        self.assertEqual(self.nodes,original);self.assertTrue(client.cache_matches(saved,self.run,self.uid))

    def test_local_scope_and_token_offsets_are_exact(self):
        req = FrameClient(nodes=self.nodes).request(self.run,self.uid)
        self.assertNotIn('Later evidence', str(req)); node = next(n for n in self.nodes if n['id']==self.uid)
        for f in req['state']['fields'].values():
            for c in f['candidates']: self.assertEqual(node['text'][c['start']-node['start']:c['end']-node['start']],c['text'])
        selection={'start':0,'text':' '.join(['word']*98)+' `file.py`'}
        cs,coverage=token_candidates(node,selection); self.assertEqual((len(cs),coverage['omitted']),(96,3))
        cs,_=token_candidates(node,{'start':0,'text':'modify `__eq__` now'});self.assertEqual([c['text'] for c in cs],['modify','`__eq__`','now'])

    def test_partial_second_frame_resumes_without_repeating_successful_calls(self):
        calls=[];checkpoints=[]
        def transport(req):
            calls.append(req)
            if len(calls)==3:raise InputError('second frame failed')
            return response(req)
        client=FrameClient(nodes=self.nodes,transport=transport)
        with self.assertRaises(InputError):client.evaluate(self.run,self.uid,checkpoint=lambda s:checkpoints.append(json.loads(dumps(s))) or True)
        partial=checkpoints[-1];self.assertEqual(len(partial['_arguments']),1)
        self.assertTrue(client.heads_match(partial,self.run,self.uid));self.assertFalse(client.cache_matches(partial,self.run,self.uid))
        saved=client.evaluate(self.run,self.uid,resume=partial)
        self.assertEqual(len(calls),4);self.assertEqual(calls[2],calls[3]);self.assertTrue(is_extension(partial,saved))
        self.assertFalse(is_extension(saved,partial));self.assertEqual(len(saved['_arguments']),2)
        changed=copy.deepcopy(saved);changed['_heads'][next(iter(changed['_heads']))]['value']='changed'
        self.assertFalse(is_extension(partial,changed))

    def test_worker_persistence_monotone_checkpoint_export_and_cache(self):
        calls=[]
        def transport(req):
            calls.append(req)
            if len(calls)==3:raise InputError('interrupted second frame')
            return response(req)
        worker=Worker(self.store,frames=True,autostart=False,client=FrameClient(transport=transport));self.addCleanup(worker.close)
        worker.submit(self.run['id']);worker._process(worker._claim());self.assertEqual(worker.list()[0]['status'],'failed')
        partial=self.store.get(self.run['id'],raw=True);self.assertEqual(len(partial['frame_observation_history']),1)
        node=next(n for n in partial['unit_graph']['nodes'] if n['id']==self.uid);self.assertEqual(node['local_frames']['status'],'partial')
        worker.submit(self.run['id']);worker._process(worker._claim());self.assertEqual(worker.list()[0]['status'],'complete')
        done=self.store.get(self.run['id'],raw=True);self.assertEqual(done['entity_observation_history'],self.bundle['entity_observation_history'])
        self.assertEqual(len(done['frame_observation_history']),1);self.assertEqual(done['unit_graph']['coverage']['frame_observed_units'],1)
        worker.submit(self.run['id']);worker._process(worker._claim());self.assertEqual(len(calls),4)

    def test_stale_upstream_does_not_reuse_frame_and_no_heads_remains_explicit(self):
        client=FrameClient(nodes=self.nodes,transport=response);saved=client.evaluate(self.run,self.uid)
        node=next(n for n in self.nodes if n['id']==self.uid);node['entity_extraction']['observation']['_provenance']['request_hash']='changed'
        self.assertFalse(client.cache_matches(saved,self.run,self.uid))
        client=FrameClient(nodes=self.nodes,transport=lambda r:fixed_response(r,lambda k,q:'no_predicate' if k.endswith('@coverage') else 'not_predicate_head'))
        saved=client.evaluate(self.run,self.uid);self.assertEqual(saved['_argument_requests'],{});self.assertEqual(saved['_provenance']['transport_calls'],1)
        self.assertTrue(client.cache_matches(saved,self.run,self.uid))

    def test_completed_import_is_idempotent_and_conflicting_results_are_immutable(self):
        saved=FrameClient(nodes=self.nodes,transport=response).evaluate(self.run,self.uid)
        self.store.record_frames(self.run['id'],self.uid,saved)
        self.store.record_frames(self.run['id'],self.uid,saved)
        self.assertEqual(len(self.store.get(self.run['id'],raw=True)['frame_observation_history']),1)
        changed=copy.deepcopy(saved);changed['_provenance']['elapsed_seconds']+=1
        with self.assertRaises(InputError):self.store.record_frames(self.run['id'],self.uid,changed)
        malformed=copy.deepcopy(saved);child=next(iter(malformed['_arguments'].values()));child['answers'].pop(next(iter(child['answers'])))
        self.assertFalse(FrameClient(nodes=self.nodes).cache_matches(malformed,self.run,self.uid))
        with self.assertRaises(InputError):self.store.record_frames(self.run['id'],self.uid,malformed)

    def test_cross_route_difference_is_source_bound_not_a_semantic_override(self):
        saved=FrameClient(nodes=self.nodes,transport=response).evaluate(self.run,self.uid)
        first=frames(saved)[0];second=copy.deepcopy(first);second.update(id='other-route',source_field='coordinate__requested_operation')
        chosen=next(a for a in second['arguments'] if a['candidate']['text']=='the method')
        chosen['decision']['value']='subject'
        differences=attachment_differences([first,second]);self.assertEqual(len(differences),1)
        self.assertEqual({d['choice'] for d in differences[0]['decisions']},{'subject','direct_object'})
        second['head']['start']+=1
        self.assertEqual(attachment_differences([first,second]),[])
        changed=copy.deepcopy(saved);changed['_provenance']['completion']='awaiting_arguments'
        with self.assertRaises(InputError):self.store.record_frames(self.run['id'],self.uid,changed)


if __name__=='__main__':unittest.main()
