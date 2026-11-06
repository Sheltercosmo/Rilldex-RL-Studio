"""Current interval readers retain visible source and exclude other histories."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import action_targets, method_comparison, work_patterns
from tracker.schema import digest, dumps, InputError
from tracker.semantic_budget import BudgetReached
from tracker.semantic_extraction import Pipeline, load_extraction, read, windows
from tests.test_action_scope_pages import fixture, transport as base_transport
from tests.test_plan_relations import Provider
from tests.method_comparison_fixture import native_response


def transport(request):
    if request['state'].get('stage')=='method_comparison':return native_response(request)
    return base_transport(request)


def insert_before(run, endpoint, identifier, **changes):
    event=next(e for e in run['events'] if e['id']==endpoint)
    added=deepcopy(event)
    added.update(id=identifier,text='EXCLUDED_'+identifier,source_pointer='/audit/'+identifier,
                 kind='message',actor='agent')
    added.update(changes)
    for e in run['events']:
        if e['index']>=added['index']:e['index']+=1
    run['events'].insert(next(i for i,e in enumerate(run['events']) if e['id']==endpoint),added)
    return added


class IntervalSourceIsolationTests(unittest.TestCase):
    def extract(self,folder,run):
        engine=Pipeline(folder,Provider(Path(folder)/'candidates'),transport)
        extraction=engine.run(run)
        targets,_=action_targets.execute(run,extraction,engine,version=action_targets.INTERVAL_VERSION)
        view=load_extraction(run,folder,action_target_version=action_targets.INTERVAL_VERSION)
        return engine,targets,view['document']

    def test_interleaved_sessions_complete_target_method_and_resume(self):
        run=fixture(3)
        middle=[e for e in run['events'] if e['kind']=='action'][1]
        middle['context_id']='session-b'
        for e in run['events']:
            if e['kind']=='feedback' and e.get('source_call_id')==middle.get('call_id'):
                e['context_id']='session-b'
        with TemporaryDirectory() as folder:
            engine,targets,doc=self.extract(folder,run)
            self.assertEqual(targets['coverage']['compared_pairs'],1)
            self.assertEqual(len(doc['work_history']['recurrences']),1)
            original=deepcopy((run,doc));requests=[]
            def stop(req):
                if len(requests)==1:raise BudgetReached({'limit':'jev_requests'})
                requests.append(req);return transport(req)
            engine.transport=stop
            with self.assertRaises(BudgetReached):
                method_comparison.execute(run,doc,engine,version=method_comparison.RELATED_VERSION)
            def resume(req):
                self.assertNotIn(digest(req),[digest(r) for r in requests])
                requests.append(req);return transport(req)
            engine.transport=resume
            result,audit=method_comparison.execute(run,doc,engine,version=method_comparison.RELATED_VERSION)
            self.assertTrue(audit['argmax_replayed'])
            self.assertEqual(result['counts']['same_work_pairs'],1)
            self.assertEqual(result['counts']['selected_pairs'],1)
            self.assertEqual(len(requests),2)
            self.assertEqual((run,doc),original)
            for req in requests:
                self.assertEqual(req['state']['source_hash'],digest(run))
                self.assertEqual(req['state']['base_map_hash'],digest(doc))
                self.assertNotIn(middle['text'],dumps(req))
                self.assertIn(dict(event_id=middle['id'],reason='different_recorded_context'),req['state']['omitted_source_events'])

    def test_private_copied_and_nonvisible_records_never_reenter_gap_metadata(self):
        run=fixture(2);endpoint=[e for e in run['events'] if e['kind']=='action'][-1]['id']
        injected=[insert_before(run,endpoint,'external',kind='external_feedback',actor='environment',agent_visibility='not_established'),
                  insert_before(run,endpoint,'invisible',agent_visible=False),
                  insert_before(run,endpoint,'copied',copied_context=True)]
        with TemporaryDirectory() as folder:
            engine,targets,doc=self.extract(folder,run)
            requests=[]
            engine.transport=lambda req:(requests.append(req),transport(req))[1]
            result,_=method_comparison.execute(run,doc,engine,version=method_comparison.RELATED_VERSION)
            self.assertEqual(result['counts']['selected_pairs'],1)
            saved_target=[read(p)['request'] for p in (Path(folder)/'decisions').glob('*.json')
                          if read(p)['request']['state'].get('stage')=='action_targets']
            self.assertEqual(len(saved_target),1)
            patterns=work_patterns.build(run,doc,include_returns=True)
            self.assertTrue(patterns['runs'])
            for payload in [*saved_target,*requests,doc['work_history'],patterns]:
                encoded=dumps(payload)
                for event in injected:self.assertNotIn(event['text'],encoded)
            for req in [*saved_target,*requests]:
                self.assertTrue({e['id'] for e in injected}<={e['event_id'] for e in req['state']['omitted_source_events']})
                self.assertEqual(req['state']['source_hash'],digest(run))
            context=doc['work_history']['recurrences'][0]['context']
            self.assertEqual(context['schema'],'recurrence-context/3')
            self.assertEqual({e['event_id'] for e in context['excluded_source_events']},{e['id'] for e in injected})

    def test_legacy_method_reader_is_unchanged_and_invalid_cross_context_pair_rejected(self):
        from tests.method_comparison_fixture import repeat_sample
        run,doc=repeat_sample();actions=[u for u in doc['units'] if u['kind']=='action']
        args=(run,doc,actions[0]['id'],actions[1]['id'])
        for version in (method_comparison.VERSION,method_comparison.NATIVE_VERSION):
            self.assertEqual(method_comparison.pair_request(*args,version=version),
                             method_comparison._pair_request(*args,version=version))
        next(e for e in run['events'] if e['id']==actions[0]['source']['event_id'])['context_id']='other'
        doc['source_hash']=digest(run)
        with self.assertRaisesRegex(InputError,'outside the visible recorded context'):
            method_comparison.pair_request(*args,version=method_comparison.RELATED_VERSION)

    def test_hidden_user_before_real_request_is_not_a_window_or_objective(self):
        run=fixture(2)
        visible=insert_before(run,run['events'][0]['id'],'visible-user',kind='instruction',actor='user')
        visible['text']='Inspect the recorded items.'
        hidden=[insert_before(run,visible['id'],'hidden-user-flag',kind='instruction',actor='user',agent_visible=False),
                insert_before(run,visible['id'],'hidden-user-visibility',kind='instruction',actor='user',agent_visibility='not_established')]
        eligible={w['event_id'] for w in windows(run,include_user=True)}
        self.assertIn(visible['id'],eligible)
        self.assertFalse({e['id'] for e in hidden}&eligible)
        with TemporaryDirectory() as folder:
            _,_,doc=self.extract(folder,run)
            self.assertEqual(doc['objective']['text'],visible['text'])
            self.assertEqual([r['event_id'] for r in doc['objective']['evidence']],[visible['id']])
            for event in hidden:self.assertNotIn(event['text'],dumps(doc['objective']))

    def test_safe_context_relation_indices_still_address_original_document(self):
        from tests.test_work_paths import fixture as path_fixture
        from tracker.recurrence_context import safe_build
        run,doc=path_fixture()
        for event in run['events']:
            if event['index']>=3:event['index']+=1
        run['events'].insert(3,dict(id='foreign',index=3,context_id='other'))
        foreign=deepcopy(doc['units'][3]);foreign.update(id='foreign-unit')
        foreign['source']['event_id']='foreign';doc['units'].append(foreign)
        doc['relations'].insert(0,dict(type='assesses',**{'from':'foreign-unit','to':'2'}))
        context=safe_build(run,doc,'1','4')
        self.assertEqual(context['assessment_relation_indices'],[4])
        self.assertEqual(doc['relations'][context['assessment_relation_indices'][0]],
                         {'from':'3','to':'2','type':'assesses'})

    def test_unknown_order_is_omitted_and_cannot_supply_comparison_endpoints(self):
        from tests.method_comparison_fixture import repeat_sample
        run,doc=repeat_sample();actions=[u for u in doc['units'] if u['kind']=='action']
        unknown=insert_before(run,actions[-1]['source']['event_id'],'unordered',order_known=False)
        doc['source_hash']=digest(run)
        request=method_comparison.pair_request(run,doc,actions[0]['id'],actions[-1]['id'],
                                              version=method_comparison.RELATED_VERSION)
        self.assertNotIn(unknown['text'],dumps(request))
        self.assertIn(dict(event_id=unknown['id'],reason='order_not_established'),request['state']['omitted_source_events'])
        for endpoint in actions:
            altered=deepcopy(run)
            next(e for e in altered['events'] if e['id']==endpoint['source']['event_id'])['order_known']=False
            changed={**doc,'source_hash':digest(altered)}
            with self.assertRaises(InputError):
                method_comparison.pair_request(altered,changed,actions[0]['id'],actions[-1]['id'],
                                               version=method_comparison.RELATED_VERSION)
