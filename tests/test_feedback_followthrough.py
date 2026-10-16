"""Authored data-flow controls, not semantic accuracy measurements."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import json
from urllib.request import urlopen

from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker import graph_store
from tracker.feedback_followthrough import project
from tracker.schema import InputError, digest
from tracker.store import Store
from rilldex import Workspace


def fixture(*, batch=False, same=False, omit_next_unit=False):
    def call(i, value): return dict(id=i,type='function',function=dict(name='tool',arguments='{"command":"'+value+'"}'))
    messages=[dict(role='user',content='Complete the task.'),
        dict(role='assistant',content='Run the operation.',tool_calls=[call('a','run --user')]),
        dict(role='tool',tool_call_id='a',content='ERROR: --user is unsupported.'),
        dict(role='assistant',content='The flag is unsupported. Try another invocation.',
             tool_calls=[call('b','run --user' if same else 'python -m run --user')]+([call('c','inspect')] if batch else [])),
        dict(role='tool',tool_call_id='b',content='ERROR: --user is unsupported.')]
    if batch:messages.append(dict(role='tool',tool_call_id='c',content='Inspection result.'))
    messages.append(dict(role='assistant',content='Reported done.'))
    run=normalize(chat_document(messages))[0]
    units=[]
    for e in run['events']:
        if e['actor']=='user' or not e['text'].strip():continue
        if omit_next_unit and e['kind']=='action' and e.get('source_message_index')==3:continue
        units.append(dict(id='unit-'+e['id'],kind='action' if e['kind']=='action' else 'semantic' if e['actor']=='agent' else 'feedback',
            actor=e['actor'],activity='execute' if e['kind']=='action' else 'orient' if e['actor']=='agent' else None,
            status='selected',source=dict(event_id=e['id'],start=0,end=len(e['text']),text=e['text'])))
    feedback=next(u for u in units if u['kind']=='feedback')
    reference=next(u for u in units if u['source']['text'].startswith('The flag'))
    relation=dict(type='responds_to',**{'from':reference['id'],'to':feedback['id']},evidence=[deepcopy(feedback['source']),deepcopy(reference['source'])])
    doc=dict(schema='semantic-unit-map/1',source_hash=digest(run),units=units,relations=[relation])
    graph=graph_store.build(run,dict(observer=dict(id='feedback-test',label='Authored reference'),document=doc))
    return run,graph,reference,feedback


def rehash(graph):
    graph['nodes'].sort(key=lambda n:n['id']);graph['edges'].sort(key=lambda e:e['id'])
    graph['id']='graph-'+digest({k:v for k,v in graph.items() if k!='id'})
    return graph


class FeedbackFollowthroughTests(unittest.TestCase):
    def test_changed_command_and_repeated_error_are_evidence_not_recovery(self):
        _,g,_,_=fixture();before=deepcopy(g);out=project(g);row=out['rows'][0]
        self.assertEqual(row['following_selection'],'same_response_dispatches')
        self.assertEqual(row['origin_status'],'unique')
        self.assertEqual(row['following'][0]['dispatch_comparison']['status'],'changed')
        self.assertEqual(row['feedback']['text'],row['following'][0]['outputs'][0]['text'])
        self.assertNotIn('recovered',str(out['counts']))
        self.assertEqual(out['counts']['with_returned_output'],1);self.assertEqual(g,before)

    def test_prefix_before_dispatch_and_after_dispatch_before_output(self):
        _,g,ref,_=fixture();full=project(g)['rows'][0]
        before=project(g,ref['source']['event_id'])['rows'][0]
        self.assertEqual(before['following_selection'],'not_recorded');self.assertEqual(before['following'],[])
        during=project(g,full['following'][0]['event_id'])['rows'][0]
        self.assertEqual(during['following'][0]['outputs'],[])
        with self.assertRaises(InputError):project(g,'absent')

    def test_parallel_batch_not_silently_reduced_to_one_action(self):
        _,g,_,_=fixture(batch=True);row=project(g)['rows'][0]
        self.assertEqual(row['following_selection'],'same_response_dispatches')
        self.assertEqual(len(row['following']),2)
        self.assertEqual([len(a['outputs']) for a in row['following']],[1,1])

    def test_separate_generation_is_distinguished_from_same_response(self):
        _,g,_,_=fixture(batch=True)
        row=project(g)['rows'][0]
        for a in row['following']:
            e=next(n['properties'] for n in g['nodes'] if n['id']=='event:'+a['event_id'])
            e['parent_id']='later-message';e['source_message_index']=20
        self.assertEqual(project(rehash(g))['rows'][0]['following_selection'],'next_recorded_batch')

    def test_native_action_is_kept_without_semantic_unit(self):
        _,g,_,_=fixture(omit_next_unit=True);row=project(g)['rows'][0]
        self.assertTrue(row['following'][0]['node_id'].startswith('event:'))
        self.assertEqual(len(row['following'][0]['outputs']),1)

    def test_identical_payload_ignores_call_identity(self):
        _,g,_,_=fixture(same=True)
        self.assertEqual(project(g)['rows'][0]['following'][0]['dispatch_comparison']['status'],'identical')

    def test_other_context_and_hidden_events_are_not_followups(self):
        for field,value in [('context_id','other'),('trajectory_id','parallel'),('actor','other-agent'),('copied_context',True),('agent_visibility','not_established')]:
            with self.subTest(field=field):
                _,g,_,_=fixture();next_id=project(g)['rows'][0]['following'][0]['event_id']
                next(n for n in g['nodes'] if n['id']=='event:'+next_id)['properties'][field]=value
                self.assertEqual(project(rehash(g))['rows'][0]['following'],[])

    def test_bad_or_future_reference_evidence_excluded(self):
        for invalid in ['not-a-span',dict(event_id='absent',start=0,end=1,text='x')]:
            _,g,_,_=fixture();edge=next(e for e in g['edges'] if e['type']=='responds_to');edge['properties']['evidence']=[invalid]
            out=project(rehash(g));self.assertEqual(out['rows'],[]);self.assertEqual(len(out['excluded']),1)
        _,g,_,_=fixture();future=max((n['properties'] for n in g['nodes'] if n['kind']=='event'),key=lambda e:e['index'])
        next(e for e in g['edges'] if e['type']=='responds_to')['properties']['evidence']=[dict(event_id=future['id'],start=0,end=len(future['text']),text=future['text'])]
        self.assertEqual(project(rehash(g))['rows'],[])

    def test_unobserved_later_cutoff_does_not_make_reference_eligible(self):
        _,g,_,_=fixture();future=max((n['properties'] for n in g['nodes'] if n['kind']=='event'),key=lambda e:e['index'])
        next(e for e in g['edges'] if e['type']=='responds_to')['properties']['cutoff']=dict(event_id=future['id'],end=len(future['text']))
        self.assertEqual(project(rehash(g))['rows'],[])

    def test_source_only_and_unbound_feedback_keep_unknown(self):
        run,g,_,_=fixture();self.assertEqual(project(graph_store.build(run))['rows'],[])
        g['edges']=[e for e in g['edges'] if e['type']!='response_to']
        row=project(rehash(g))['rows'][0]
        self.assertEqual(row['origin_status'],'unbound');self.assertIsNone(row['original_action'])
        self.assertEqual(row['following'][0]['dispatch_comparison']['status'],'unavailable')

    def test_database_access_is_scoped_and_restart_stable(self):
        run,g,_,_=fixture()
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'workspace.sqlite';store=Store(path);store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            for _ in range(2):self.assertEqual(Workspace(path,observer=g['observer']).feedback_followthrough(g['id']),project(g))
            with self.assertRaises(InputError):Workspace(path,observer='other').feedback_followthrough(g['id'])
            with self.assertRaises(InputError):Workspace(path).feedback_followthrough(g['id'],limit=1)


import test_generation_cohort_transport as transport


class FeedbackHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_exact_graph_and_prefix_contract_over_http(self):
        run,g,ref,_=fixture();self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,g)
        endpoint=self.start_server()
        for suffix,expected in [('',project(g)),('&through='+ref['source']['event_id'],project(g,ref['source']['event_id']))]:
            with urlopen(endpoint+'/api/feedback-followthrough?graph='+g['id']+suffix,timeout=10) as response:
                self.assertEqual(json.load(response),expected)


if __name__=='__main__':unittest.main()
