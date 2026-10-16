from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import feedback_assessment as fa, monitoring, monitor_evidence, graph_store
from tracker.schema import event, digest, dumps, InputError
from tracker.semantic_extraction import read
from tracker.adapters import normalize
from tracker.store import Store


def fixture(text='The result shows the package is missing.',response='package not installed',closed=True):
    events=[]
    event(events,kind='action',text='which package',pointer='/call',trajectory_id='main',call_id='a')
    event(events,kind='feedback',text=response,pointer='/response',trajectory_id='main',actor='environment',source_call_id='a')
    if text:event(events,kind='reasoning',text=text,pointer='/reaction',trajectory_id='main')
    if closed:event(events,kind='action',text='FUTURE_ACTION_SECRET',pointer='/next',trajectory_id='main',call_id='b')
    return {'id':'test','adapter':'test','adapter_version':'test','metadata':{},'events':events}


def transport(choice='first'):
    def decide(req):
        return {'model':req['model'],'answers':{key:{'type':'choice','choice':'ignored','confidence':0,
            'probabilities':{k:int(k==(next(iter(q['criteria'])) if choice=='first' else choice)) for k in q['criteria']}}
            for key,q in req['questions'].items()}}
    return decide


class FeedbackAssessmentTests(unittest.TestCase):
    def observed(self,run,choice='first'):
        with tempfile.TemporaryDirectory() as root:
            return fa.execute(run,root,transport(choice))[0]

    def test_exact_source_window_no_future_reward_and_cached_argmax(self):
        run=fixture();run['outcome']={'recorded_reward':987654321}
        with tempfile.TemporaryDirectory() as root:
            result,calls=fa.execute(run,root,transport());o=result['observations'][0]
            self.assertEqual((o['value'],calls),(1,1));self.assertEqual(o['assessment_event_id'],'e3')
            req=read(Path(root)/'decisions'/f"{o['request_hash']}.json")['request']
            self.assertNotIn('FUTURE_ACTION_SECRET',dumps(req));self.assertNotIn('987654321',dumps(req))
            self.assertEqual(fa.execute(run,root,lambda r:self.fail('Cache was not reused'))[1],0)
            result['observations'][0]['value']=0
            with self.assertRaisesRegex(InputError,'replay'):fa.audit(run,result,root)

    def test_absence_requires_closed_readable_window(self):
        self.assertEqual(self.observed(fixture(),'none')['counts']['not_observed'],1)
        end=self.observed(fixture(closed=False),'none')['observations'][0]
        self.assertIsNone(end['value']);self.assertIn('censored',end['reason'])
        self.assertEqual(self.observed(fixture(closed=False))['counts']['assessed'],1)

    def test_no_prose_closed_window_needs_no_inference_but_open_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            result,calls=fa.execute(fixture(text=''),root,lambda r:self.fail('No prose should not call model'))
            self.assertEqual((result['counts']['not_observed'],calls),(1,0))
        self.assertEqual(self.observed(fixture(text='',closed=False))['counts']['unknown'],1)

    def test_visibility_copied_ambiguous_and_cross_trajectory_bindings(self):
        for changes in ({'agent_visible':False},{'agent_visibility':'not_established'},{'copied_context':True},
                        {'trajectory_id':'other'},{'source_call_id':'missing'},{'actor':'user'}):
            run=fixture();run['events'][1].update(changes)
            self.assertEqual(fa.windows(run),[])
        run=fixture();run['events'][2]['trajectory_id']='other'
        self.assertEqual(self.observed(run)['counts']['not_observed'],1)

    def test_user_interrupt_is_censored_and_new_user_response_not_imported(self):
        run=fixture();run['events'][2]['actor']='user';run['events'][3].update(kind='message',text='after user instruction')
        o=self.observed(run)['observations'][0]
        self.assertIsNone(o['value']);self.assertEqual(o['expression_event_ids'],[])

    def test_media_and_oversized_text_never_become_measured_absences(self):
        run=fixture(response='data:image/png;base64,QUJDRA==')
        for choice in ('first','none'):
            o=self.observed(run,choice)['observations'][0]
            self.assertIsNone(o['value']);self.assertFalse(o['complete_readable_evidence'])
        run=fixture(response='x'*(fa.MAX_CHARS+20))
        o=self.observed(run)['observations'][0];self.assertIsNone(o['value']);self.assertIsNone(o['request_hash'])

    def test_batch_and_interleaved_results_are_explicit_unknowns(self):
        run=fixture();run['events'][0]['batch_size']=2
        self.assertIn('batch',self.observed(run)['observations'][0]['reason'])
        run=fixture();event(run['events'],kind='feedback',text='late chunk',pointer='/late',trajectory_id='main',actor='environment',source_call_id='a')
        self.assertIn('interleave',self.observed(run)['observations'][0]['reason'])

    def test_one_call_multiple_feedback_chunks_is_one_opportunity(self):
        run=fixture();extra=deepcopy(run['events'][1]);extra['id']='extra';extra['index']=1.5;extra['text']='more output';run['events'].insert(2,extra)
        result=self.observed(run)
        self.assertEqual(result['counts']['response_groups'],1)
        self.assertEqual(result['observations'][0]['response_event_ids'],['e2','extra'])

    def test_budget_interruption_preserves_decisions_without_publishing_partial_result(self):
        from tracker.feedback_cli import BudgetReached
        run=fixture();event(run['events'],kind='feedback',text='done',pointer='/response2',trajectory_id='main',actor='environment',source_call_id='b')
        event(run['events'],kind='message',text='That worked.',pointer='/last',trajectory_id='main')
        calls=[]
        def limited(req):
            if calls:raise BudgetReached()
            calls.append(req);return transport()(req)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(BudgetReached):fa.execute(run,root,limited)
            self.assertFalse((Path(root)/'result.json').exists())
            self.assertEqual(read(Path(root)/'execution.json')['status'],'interrupted')
            self.assertEqual(len(list((Path(root)/'decisions').glob('*.json'))),1)
            result,count=fa.execute(run,root,transport());self.assertEqual(count,1)
            self.assertEqual(result['counts']['assessed'],2)

    def test_saved_metric_graph_and_monitor_receipt_bind_every_opportunity(self):
        doc={'schema_version':'ATIF-v1.7','session_id':'feedback','agent':{'name':'test','version':'1'},'steps':[
            {'step_id':1,'source':'user','message':'Find the executable.'},
            {'step_id':2,'source':'agent','message':'Locate it.','tool_calls':[{'tool_call_id':'a','function_name':'shell','arguments':{'command':'which pkg'}}],
             'observation':{'results':[{'source_call_id':'a','content':'not found'}]}},
            {'step_id':3,'source':'agent','message':'The package is not installed.','tool_calls':[{'tool_call_id':'b','function_name':'shell','arguments':{'command':'install pkg'}}]}]}
        run=normalize(doc,'harbor',{'experiment':'test','training_step':2})[0]
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'db.sqlite');store.add([run]);folder=Path(root)/'observer'
            result,_=fa.execute(run,folder,transport());saved=fa.register(store,run,result,folder)
            graph=graph_store.read(store,saved['graph_id'])
            self.assertEqual(len([e for e in graph['edges'] if e['type']=='assesses_response_group']),1)
            self.assertFalse(any(n['kind']=='unit' for n in graph['nodes']))
            monitor=monitoring.create(store,{'name':'Feedback','kind':'metric','observer':saved['observer'],'metric':'feedback_assessment_fraction'})
            monitoring.sync(store);v=monitoring.cases(store,monitor['id'])['rows'][0]['measurement']
            receipt=monitor_evidence.read(store,v['id'])
            self.assertEqual(receipt['graph']['id'],graph['id']);self.assertEqual(receipt['measurement']['value'],1)
            self.assertEqual(receipt['explanation']['feedback_assessment'],result)
            self.assertEqual(monitoring.snapshot(store)['runs'][0]['semantic_graphs'],0)
            self.assertEqual(monitoring.rollout(store,run['id'])['graph']['observer'],'source')
            self.assertEqual(fa.register(store,run,result,folder),saved)

    def test_rejected_legacy_selector_cannot_be_enabled_as_a_monitor(self):
        with self.assertRaisesRegex(InputError,'retained for audit'):
            monitoring.validate({'name':'Failed development observer','kind':'metric','metric':'feedback_assessment_fraction',
                                 'observer':fa.protocol(fa.LEGACY)['id']})

    def test_overload_and_authentication_errors_require_separately_accounted_retry(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from tracker.jev import JevClient
        with patch.dict('os.environ',{'JEV_API_KEY':'test-only'}),patch('tracker.jev.time.sleep'),patch('tracker.jev.urllib.request.urlopen') as send:
            send.side_effect=HTTPError('https://example.invalid',529,'overloaded',{},None)
            with self.assertRaisesRegex(InputError,'529'):JevClient().transport({'test':True})
            self.assertEqual(send.call_count,1)
            send.reset_mock();send.side_effect=HTTPError('https://example.invalid',401,'unauthorized',{},None)
            with self.assertRaisesRegex(InputError,'401'):JevClient().transport({'test':True})
            self.assertEqual(send.call_count,1)
