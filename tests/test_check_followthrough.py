"""Temporal correspondence boundaries and replay; not model accuracy tests."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError,digest,dumps
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline,FileCandidates
from tracker.feedback_assessments import linked_feedback
from tracker import stated_checks
from tracker.check_followthrough import candidates,relation_request,build,audit
from tests.test_check_candidate_repairs import choose


def fixture(directory):
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Check my gift card once I supply its ID.',
         'agent':{'thought':'I will verify the gift card balance after you send its ID.','action':None}},
        {'step':1,'user_message':'The ID is CARD_A. I believe its balance is $15.',
         'agent':{'thought':None,'action':'get_balance(CARD_A)'},'environment':'FIRST_RESPONSE_ONLY: balance is 17'},
        {'step':2,'user_message':'NEW_TERMS: use CARD_B instead.',
         'agent':{'thought':None,'action':'get_balance(CARD_B)'},'environment':'SECOND_RESPONSE_ONLY: no such card'},
        {'step':3,'user_message':'FUTURE_CLAIM: all checks passed.','agent':{'thought':None,'action':None}}]})[0]
    units=[{'id':'u-'+e['id'],'actor':e['actor'],'trajectory_id':e['trajectory_id'],'status':'selected',
        'kind':'action' if e['kind']=='action' else 'semantic','activity':'inspect' if e['kind']=='action' else 'orient',
        'source':evidence(run,e['id']),'content':{'summary':{'status':'expressed','text':e['text'],'evidence':[evidence(run,e['id'])]}}}
        for e in run['events'] if e['actor']=='agent' and e['text'].strip()]
    local={'run_id':run['id'],'source_hash':digest(run),'status':'complete_local_extraction','units':units}
    owner=units[0];check={'text':'Check the supplied gift card balance.','evidence':[owner['source']],
        'facets':[{'id':'balance','text':'Check the supplied gift card balance.','evidence':[owner['source']]}]}
    proposals={'schema':stated_checks.VERSION,'source_hash':digest(run),'extraction_hash':digest(local),
        'producer':'test fixture','units':[{'unit_id':owner['id'],'candidates':[check]}]}
    engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),lambda req:choose(req,{
        'checking_applicability':'checking_work','stated_check_contents':'c0','check_specification':'observation_only'}[req['state']['stage']]))
    stated=stated_checks.build(run,local,proposals,engine.decide,stated_checks.ROUTED_VERSION)
    return run,local,stated,engine


class CheckFollowthroughTests(unittest.TestCase):
    def test_delayed_candidates_cross_intervening_turns_without_nearest_neighbor_links(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,engine=fixture(directory);original=deepcopy(stated)
            pool=candidates(run,local,stated)
            self.assertEqual(len(pool[0]['actions']),2);self.assertEqual(pool[0]['reused_actions'],[])
            engine.transport=lambda req:choose(req,'none' if req['state']['stage']=='later_check_dispatch' else 'absent')
            result=build(run,local,stated,engine.decide)
            self.assertEqual(result['relations'],[]);self.assertEqual(stated,original)
            self.assertEqual(audit(run,local,stated,result,directory)['later_action_pairs'],2)
            calls=engine.calls;self.assertEqual(build(run,local,stated,engine.decide),result);self.assertEqual(engine.calls,calls)

    def test_dispatch_excludes_response_and_future_terms_while_material_uses_its_own_response(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,_=fixture(directory);entry=candidates(run,local,stated)[0]
            owner=entry['owner'];check=entry['item']['check'];facet=check['facets'][0]
            first,second=entry['actions'];feedback=linked_feedback(run,local)
            req=relation_request(run,local,owner,check,facet,first)
            self.assertIn('CARD_A',dumps(req));self.assertNotIn('FIRST_RESPONSE_ONLY',dumps(req))
            self.assertNotIn('NEW_TERMS',dumps(req));self.assertNotIn('FUTURE_CLAIM',dumps(req))
            response=next(f for f in feedback if f['action']['id']==second['id'])
            req=relation_request(run,local,owner,check,facet,second,response)
            self.assertIn('NEW_TERMS',dumps(req));self.assertNotIn('FIRST_RESPONSE_ONLY',dumps(req))
            self.assertIn('SECOND_RESPONSE_ONLY',req['state']['inspected_response']['text'])
            self.assertNotIn('FUTURE_CLAIM',dumps(req))
            self.assertNotIn('I believe',req['state']['inspected_response']['text'])
            self.assertIn('not returned evidence',req['state']['response_scope'])

    def test_existing_native_pairs_are_reused_and_cross_actor_or_future_pairs_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,_=fixture(directory)
            stated['observations'][0]['actions']=[{'action_unit_id':local['units'][1]['id']}]
            pool=candidates(run,local,stated)[0]
            self.assertEqual([u['id'] for u in pool['reused_actions']],[local['units'][1]['id']])
            self.assertEqual([u['id'] for u in pool['actions']],[local['units'][2]['id']])
            local['units'][2]['actor']='other';stated['extraction_hash']=digest(local)
            self.assertEqual(candidates(run,local,stated)[0]['actions'],[])
            future=deepcopy(local['units'][0]);future['source']=evidence(run,run['events'][-1]['id'])
            with self.assertRaisesRegex(InputError,'precede'):relation_request(run,local,future,stated['observations'][0]['check'],stated['observations'][0]['check']['facets'][0],local['units'][1])

    def test_material_is_independent_of_dispatch_role_and_keeps_negative_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,engine=fixture(directory)
            engine.transport=lambda req:choose(req,'none' if req['state']['stage']=='later_check_dispatch' else 'available')
            result=build(run,local,stated,engine.decide)
            self.assertEqual(len(result['relations']),2)
            self.assertEqual({r['type'] for r in result['relations']},{'provides_check_material'})
            self.assertTrue(all(a['facets'][0]['dispatch_choice']=='none' for a in result['observations'][0]['actions']))
            self.assertEqual(audit(run,local,stated,result,directory)['response_observations'],2)
            changed=deepcopy(result);changed['observations'][0]['actions'][0]['facets'][0]['dispatch_choice']='attempts'
            with self.assertRaisesRegex(InputError,'dependency replay'):audit(run,local,stated,changed,directory)

    def test_response_binding_and_at_dispatch_terms_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,_=fixture(directory);entry=candidates(run,local,stated)[0]
            owner=entry['owner'];check=entry['item']['check'];first,second=entry['actions'];feedback=linked_feedback(run,local)
            wrong=next(f for f in feedback if f['action']['id']==second['id'])
            with self.assertRaisesRegex(InputError,'bind'):relation_request(run,local,owner,check,check['facets'][0],first,wrong)
            response=next(f for f in feedback if f['action']['id']==first['id'])
            # Simulate a participant event arriving between dispatch and result:
            # it must not retroactively replace the target context at dispatch.
            instruction=deepcopy(next(e for e in run['events'] if 'NEW_TERMS' in e['text']))
            instruction['id']='intervening';instruction['index']=response['event']['index']-.5
            run['events'].append(instruction);run['events'].sort(key=lambda e:e['index'])
            req=relation_request(run,local,owner,check,check['facets'][0],first,response)
            self.assertNotIn('NEW_TERMS',dumps(req));self.assertIn('intervening',req['state']['omitted_context_event_ids'])

    def test_long_response_and_media_stay_unobserved_without_reappearing_in_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,_=fixture(directory);entry=candidates(run,local,stated)[0]
            owner=entry['owner'];check=entry['item']['check'];action=entry['actions'][0]
            response=next(f for f in linked_feedback(run,local) if f['action']['id']==action['id'])
            response['event']['text']='start '+('x'*5000)+'HIDDEN_MIDDLE'+('y'*5000)+' data:image/png;base64,QUJDRA== end'
            req=relation_request(run,local,owner,check,check['facets'][0],action,response)
            self.assertNotIn('HIDDEN_MIDDLE',dumps(req));self.assertNotIn('QUJDRA==',dumps(req))
            self.assertTrue(req['state']['inspected_response']['omitted_text_ranges'])
            self.assertTrue(req['state']['inspected_response']['unobserved_inline_media'])
            self.assertNotIn('text',req['state']['subject'])


if __name__=='__main__':unittest.main()
