"""Target relation provenance/cutoffs and structural deltas, not accuracy labels."""
import copy
from pathlib import Path
import tempfile
import unittest

from tracker.action_targets import (LIMIT,SCOPED_VERSION,CHARACTERIZED_VERSION,SCOPE_VERSION,argument_delta,audit,build,candidates,
    execute,path_for,relation_request)
from tracker.schema import InputError,digest
from tracker.semantic_extraction import FileCandidates,Pipeline,read,write,load_extraction
from tests.test_plan_relations import Provider,fixture,transport as base_transport


def transport(req):
    if req['state']['stage']!='action_target_correspondence':return base_transport(req)
    keys=req['questions']['choice']['criteria']
    # The provider's reported label deliberately differs from the raw winner.
    return {'model':req['model'],'answers':{'choice':{'type':'choice',
        'choice':'unresolved','confidence':0,
        'probabilities':{k:.9 if k=='a0' else .1/(len(keys)-1) for k in keys}}}}


class ActionTargetTests(unittest.TestCase):
    def setup_result(self,d):
        run=fixture();engine=Pipeline(d,Provider(Path(d)/'candidates'),transport)
        return run,engine,engine.run(run)

    def test_dependencies_cutoff_replay_and_not_feedback_or_other_actor(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d);before=copy.deepcopy(x)
            result,validation=execute(run,x,engine)
            self.assertEqual(x,before);self.assertTrue(validation['argmax_replayed'])
            self.assertEqual(len(result['relations']),4)
            self.assertEqual(result['actions'][0]['status'],'no_prior_selected_action')
            calls=engine.calls;execute(run,x,engine);self.assertEqual(engine.calls,calls)
            for edge in result['relations']:
                req=read(Path(d)/'decisions'/f"{edge['request']}.json")['request']
                index=next(e['index'] for e in run['events'] if e['id']==edge['cutoff']['event_id'])
                indices={e['id']:e['index'] for e in run['events']}
                self.assertTrue(all(indices[e['id']]<=index for e in req['state']['prefix']))
                self.assertTrue(all(p['source']['event_id']!=edge['cutoff']['event_id'] for p in req['state']['prior_actions']))
                self.assertNotIn('FUTURE FEEDBACK',str(req))
                self.assertNotIn('text',req['state']['prior_actions'][0]['source'])
                self.assertIn(req['state']['prior_actions'][0]['source']['event_id'],[e['id'] for e in req['state']['prefix']])
            action=x['units'][-1]
            first=next(u for u in x['units'] if u['kind']=='action');first['actor']='other'
            self.assertNotIn(first['id'],[c['unit_id'] for c in candidates(run,x,action)])

    def test_explicit_fallbacks_capacity_and_no_global_hash_in_local_request(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d)
            for choice in ['none_of_these','multiple_distinct_targets','unresolved']:
                result=build(run,x,lambda req:(choice,digest(req)))
                self.assertEqual(result['relations'],[])
                self.assertEqual(result['actions'][-1]['status'],choice)
            action=x['units'][-1];pool=candidates(run,x,action);req=relation_request(run,action,pool)
            self.assertNotIn('extraction_hash',req['state'])
            first=next(u for u in x['units'] if u['kind']=='action')
            x['units']=[copy.deepcopy(first) for _ in range(LIMIT+1)]+[action]
            result=build(run,x,lambda req:(_ for _ in ()).throw(AssertionError('Oversized pool must not be sent')))
            self.assertEqual(result['actions'][-1]['status'],'needs_target_candidate_retrieval')

    def test_replay_detects_modified_semantic_edges_and_source_deltas(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d);result,_=execute(run,x,engine)
            bad=copy.deepcopy(result);bad['relations'][0]['type']='successful_retry'
            with self.assertRaisesRegex(InputError,'replay'):audit(run,x,bad,d)
            x2=copy.deepcopy(x);x2['note']='changed';self.assertNotEqual(path_for(d,x),path_for(d,x2))
            x2['status']='needs_work'
            with self.assertRaisesRegex(InputError,'Complete local'):build(run,x2,engine.choose)

    def test_view_keeps_raw_relations_and_binds_retrospective_review_to_exact_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d);result,_=execute(run,x,engine)
            u=x['units'][-1]
            review={'schema':'semantic-source-review/1','source_hash':digest(run),'extraction_hash':digest(x),
                'annotator':'test reviewer','notes':[{'text':'Disputed interpretation.','kind':'relation_review',
                    'unit_ids':[u['id']],'evidence':[u['source']]}]}
            path=Path(d)/'reviews'/run['id']/f'{digest(x)}.json';write(path,review)
            view=load_extraction(run,d)
            self.assertEqual(view['validation']['review_notes'],1)
            self.assertEqual(view['validation']['action_targets']['selected_relations'],4)
            self.assertEqual(view['document']['review_origin'],'test reviewer')
            self.assertEqual(len([r for r in view['document']['relations'] if r['type']=='same_action_target']),4)
            review['extraction_hash']='different';write(path,review)
            with self.assertRaisesRegex(InputError,'bind'):load_extraction(run,d)

    def test_exact_delta_preserves_presence_null_lists_and_json_pointer_escaping(self):
        a={'argument_status':'json_object','tool':'book','arguments':{'payments':[{'amount':250}],'remove':None,'a/b':{'~':1}}}
        b={'argument_status':'json_object','tool':'book','arguments':{'payments':[{'amount':250},{'amount':1199}],'add':None,'a/b':{'~':2}}}
        delta=argument_delta(a,b);changes={c['path']:c for c in delta['changes']}
        self.assertFalse(delta['tool_changed'])
        self.assertEqual(changes['/a~1b/~0']['after'],2)
        self.assertNotIn('before',changes['/add']);self.assertIsNone(changes['/add']['after'])
        self.assertNotIn('after',changes['/remove']);self.assertIsNone(changes['/remove']['before'])
        self.assertEqual(len(changes['/payments']['after']),2)
        self.assertEqual(argument_delta(a,a)['changes'],[])
        self.assertEqual(argument_delta({},b)['status'],'not_comparable')

    def test_scoped_version_preserves_source_and_raw_argmax_with_explicit_selection(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d);before=copy.deepcopy(x)
            legacy,_=execute(run,x,engine)
            result,validation=execute(run,x,engine,version=SCOPED_VERSION)
            self.assertEqual(x,before);self.assertTrue(validation['argmax_replayed'])
            self.assertEqual(result['schema'],SCOPED_VERSION)
            self.assertNotEqual(path_for(d,x),path_for(d,x,SCOPED_VERSION))
            self.assertEqual(load_extraction(run,d)['document']['provenance']['action_target_harness'],legacy['schema'])
            view=load_extraction(run,d,action_target_version=SCOPED_VERSION)
            self.assertEqual(view['document']['provenance']['action_target_harness'],SCOPED_VERSION)
            req=read(Path(d)/'decisions'/f"{result['actions'][-1]['request']}.json")['request']
            self.assertEqual(req['state']['context_policy']['schema'],'readable-context/2')
            self.assertEqual(req['state']['current_meaning']['work_target'],x['units'][-1]['content']['work_target']['text'])
            self.assertNotIn('FUTURE FEEDBACK',str(req))
            bad=copy.deepcopy(result);bad['schema']='unsupported'
            with self.assertRaises(InputError):audit(run,x,bad,d)

    def test_scoped_packet_shares_tool_definitions_losslessly(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d)
            for e in run['events']:
                if e['kind']=='action':e['tool_contract']={'name':'same_tool','description':'Full original definition.'}
            action=x['units'][-1];pool=candidates(run,x,action)
            old=relation_request(run,action,pool);new=relation_request(run,action,pool,version=SCOPED_VERSION)
            contracts=new['state']['tool_contracts'];self.assertEqual(len(contracts),1)
            self.assertEqual(old['state']['prefix'],[{**{k:v for k,v in e.items() if k!='tool_contract_ref'},
                **({'tool_contract':contracts[e['tool_contract_ref']]} if 'tool_contract_ref' in e else {})}
                for e in new['state']['prefix']])
            self.assertTrue(all('tool_contract_ref' not in e for e in run['events']))

    def test_pair_characterization_preserves_anchor_without_false_identity(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d)
            def pair_transport(req):
                if req['state']['stage']!='action_target_pair_relation':return transport(req)
                keys=req['questions']['choice']['criteria']
                return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'same_work_target','confidence':1,
                    'probabilities':{k:.8 if k=='different_work_same_subject' else .2/(len(keys)-1) for k in keys}}}}
            engine.transport=pair_transport
            result,validation=execute(run,x,engine,version=CHARACTERIZED_VERSION)
            self.assertTrue(validation['argmax_replayed'])
            self.assertEqual(len(result['relations']),4)
            self.assertTrue(all(r['type']=='different_work_same_subject' for r in result['relations']))
            for row in result['actions'][1:]:
                self.assertEqual(row['choice'],'a0')
                self.assertEqual(row['pair_choice'],'different_work_same_subject')
                packet=read(Path(d)/'decisions'/f"{row['pair_request']}.json")['request']
                self.assertEqual(packet['state']['anchor_selection_request'],row['request'])
                self.assertEqual(len(packet['state']['prior_actions']),1)
                self.assertNotIn('FUTURE FEEDBACK',str(packet))
            calls=engine.calls;execute(run,x,engine,version=CHARACTERIZED_VERSION);self.assertEqual(engine.calls,calls)

    def test_partial_scope_preserves_raw_winner_and_composite_unit(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d);before=copy.deepcopy(x)
            def partial_transport(req):
                if req['state']['stage']!='action_target_pair_relation':return transport(req)
                keys=req['questions']['choice']['criteria']
                return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'same_work_target','confidence':1,
                    'probabilities':{k:.6 if k=='partial_work_overlap' else .4/(len(keys)-1) for k in keys}}}}
            engine.transport=partial_transport
            result,validation=execute(run,x,engine,version=SCOPE_VERSION)
            self.assertTrue(validation['argmax_replayed']);self.assertEqual(x,before)
            self.assertTrue(all(r['type']=='overlapping_work_scope' for r in result['relations']))
            view=load_extraction(run,d,action_target_version=SCOPE_VERSION)
            self.assertEqual(len(view['document']['work_paths']['paths']),5)
            self.assertTrue(view['document']['work_paths']['dispatch_coverage']['each_action_once'])


if __name__=='__main__':unittest.main()
