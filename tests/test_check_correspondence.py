"""Check scope, source binding and replay integrity; not semantic accuracy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline,FileCandidates
from tracker.requested_work import apply_edits,CLAUSE_VERSION
from tracker.work_correspondence import state_before
from tracker.feedback_assessments import linked_feedback
from tracker.check_correspondence import candidate_checks,selection_request,build,audit,path_for,BATCH_SIZE,ISOLATED_VERSION


def fixture():
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Verify card A balance. I say it has $15. Do not charge it.',
         'agent':{'thought':None,'action':'Get card A balance'},'environment':'CARD_A_RESPONSE: balance $15'},
        {'step':1,'user_message':'FUTURE_CHANGE: use card B and verify its balance instead.',
         'agent':{'thought':None,'action':'Get card B balance'},'environment':'CARD_B_RESPONSE: balance $9'}]})[0]
    units=[]
    for e in run['events']:
        if e['actor']=='user' or e['kind']=='action':
            units.append({'id':'u-'+e['id'],'actor':e['actor'],'trajectory_id':e['trajectory_id'],
                'kind':'action' if e['kind']=='action' else 'semantic','status':'selected',
                'activity':'inspect' if e['kind']=='action' else 'coordinate','source':evidence(run,e['id']),
                'content':{'summary':{'status':'expressed','text':e['text'],'evidence':[evidence(run,e['id'])]}}})
    local={'run_id':run['id'],'source_hash':digest(run),'status':'complete_local_extraction','units':units}
    users=[u for u in units if u['actor']=='user'];actions=[u for u in units if u['kind']=='action']
    records=[];steps=[];changes=[]
    for i,u in enumerate(users):
        clauses=[{'id':'balance','kind':'requested_check','text':'Verify card '+('A' if i==0 else 'B')+' balance.','evidence':[u['source']]}]
        if i==0:clauses.extend([{'id':'guard','kind':'requirement','text':'Do not charge card A.','evidence':[u['source']]},
                               {'id':'claim','kind':'attributed_claim','text':'User says card A has $15.','evidence':[u['source']]}])
        else:clauses.extend(deepcopy(records[0]['clauses'][1:]))
        edit={'op':'introduce' if i==0 else 'revise','record_id':'payment','text':'Card '+('A' if i==0 else 'B')+' checking terms.',
              'evidence':[u['source']],'clauses':clauses,**({'kind':'condition'} if i==0 else {})}
        records,delta=apply_edits(run,u,records,[edit],CLAUSE_VERSION);changes.extend(delta)
        steps.append({'unit_id':u['id'],'state_after':deepcopy(records)})
    work={'schema':CLAUSE_VERSION,'status':'complete','source_hash':digest(run),'extraction_hash':digest(local),
          'records':records,'steps':steps,'changes':changes}
    return run,local,work,users,actions


class CheckCorrespondenceTests(unittest.TestCase):
    def test_isolated_response_excludes_selected_action_interpretation(self):
        run,x,w,users,actions=fixture();snap=state_before(run,x,w,actions[0]);pool=candidate_checks(snap)
        actions[0]['content']['summary']['text']='UNRELATED_INTERPRETATION: the action will definitely succeed.'
        req=selection_request(run,x,w,actions[0],snap,pool,linked_feedback(run,x)[0],version=ISOLATED_VERSION)
        self.assertNotIn('UNRELATED_INTERPRETATION',str(req))
        self.assertNotIn('action_content',req['state'])
        self.assertIn('CARD_A_RESPONSE',str(req));self.assertIn('Verify card A balance.',str(req))

    def test_dispatch_and_response_have_separate_cutoffs_and_keep_old_check_version(self):
        run,x,w,users,actions=fixture();snap=state_before(run,x,w,actions[0]);pool=candidate_checks(snap)
        self.assertEqual(len(pool),1);self.assertEqual(pool[0]['clause']['kind'],'requested_check')
        dispatch=selection_request(run,x,w,actions[0],snap,pool)
        response=selection_request(run,x,w,actions[0],snap,pool,linked_feedback(run,x)[0])
        self.assertNotIn('CARD_A_RESPONSE',str(dispatch));self.assertNotIn('FUTURE_CHANGE',str(dispatch))
        self.assertIn('CARD_A_RESPONSE',str(response));self.assertNotIn('FUTURE_CHANGE',str(response))
        self.assertNotEqual(pool[0]['clause']['version_id'],w['records'][0]['clauses'][0]['version_id'])
        self.assertEqual(set(response['questions']),{pool[0]['clause']['version_id']})
        withdrawn=deepcopy(snap);withdrawn['records'][0]['status']='withdrawn';self.assertEqual(candidate_checks(withdrawn),[])

    def test_response_binding_and_readable_context_cannot_be_bypassed_by_subject(self):
        run,x,w,users,actions=fixture();snap=state_before(run,x,w,actions[0]);pool=candidate_checks(snap)
        response=linked_feedback(run,x)[0];bad=deepcopy(response);bad['event']['source_call_id']='different'
        with self.assertRaisesRegex(InputError,'bind'):selection_request(run,x,w,actions[0],snap,pool,bad)
        response['event']['text']='A'*8000+'OMITTED_MIDDLE_MARKER'+'Z'*8000
        req=selection_request(run,x,w,actions[0],snap,pool,response)
        self.assertNotIn('text',req['state']['subject'])
        self.assertTrue(req['state']['inspected_response']['omitted_text_ranges'])
        self.assertNotIn('OMITTED_MIDDLE_MARKER',str(req))

    def test_argmax_replay_keeps_independent_dispatch_and_response_choices(self):
        run,x,w,users,actions=fixture()
        with tempfile.TemporaryDirectory() as directory:
            def transport(req):
                role='attempts' if req['state']['stage']=='requested_check_dispatch' else 'partial'
                return {'model':req['model'],'answers':{k:{'type':'choice','choice':'unresolved','confidence':0,
                    'probabilities':{r:.7 if r==role else .1 for r in q['criteria']}} for k,q in req['questions'].items()}}
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),transport)
            result=build(run,x,w,engine.decide);self.assertEqual(engine.calls,4)
            self.assertEqual({r['type'] for r in result['relations']},{'attempts_requested_check','partly_supplies_requested_evidence'})
            self.assertTrue(audit(run,x,w,result,directory)['argmax_replayed'])
            build(run,x,w,engine.decide);self.assertEqual(engine.calls,4)
            bad=deepcopy(result);bad['relations'][0]['check_clause_version_id']='later'
            with self.assertRaisesRegex(InputError,'dependency replay'):audit(run,x,w,bad,directory)
            changed=deepcopy(w);changed['note']='different upstream pass'
            self.assertNotEqual(path_for(directory,x,w),path_for(directory,x,changed))

    def test_no_response_remains_missing_and_large_candidate_sets_are_batched(self):
        run,x,w,users,actions=fixture()
        for event in run['events']:
            if event['kind']=='feedback':event['agent_visibility']='not_established'
        w['source_hash']=digest(run)
        base=w['steps'][0]['state_after'][0]['clauses'][0]
        w['steps'][0]['state_after'][0]['clauses']=[{**deepcopy(base),'id':f'c{i}','version_id':f'cv{i}'} for i in range(BATCH_SIZE+1)]
        calls=[]
        def choose(req):
            calls.append(req)
            return {k:{'value':'none'} for k in req['questions']},digest(req)
        result=build(run,x,w,choose)
        self.assertEqual(len(result['actions'][0]['dispatch_requests']),2)
        self.assertEqual(len(result['actions'][0]['dispatch_choices']),BATCH_SIZE+1)
        self.assertEqual(result['actions'][0]['response_status'],'no_linked_recorded_response')
        self.assertEqual(result['actions'][0]['responses'],[])
        self.assertEqual(result['relations'],[])


if __name__=='__main__':unittest.main()
