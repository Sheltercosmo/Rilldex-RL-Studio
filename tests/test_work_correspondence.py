"""Temporal/version identity and replay contracts, not semantic accuracy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline,FileCandidates
from tracker.requested_work import apply_edits
from tracker.work_correspondence import (state_before,candidate_records,relation_request,build,audit,path_for,BATCH_SIZE)


def fixture():
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Write reports A and B.','agent':{'thought':None,'action':'Read shared notes'},'environment':'Shared notes'},
        {'step':1,'user_message':'Withdraw B; write only A using the draft address.','agent':{'thought':None,'action':'Write A'},'environment':'FUTURE_RESPONSE'},
        {'step':2,'user_message':'FUTURE_APPROVAL: use the final address now.','agent':{'thought':None,'action':'Read A'},'environment':'Final read'}]})[0]
    units=[]
    for e in run['events']:
        if e['actor']=='user' or e['kind']=='action':
            units.append({'id':'unit-'+e['id'],'actor':e['actor'],'trajectory_id':e['trajectory_id'],
                'kind':'action' if e['kind']=='action' else 'semantic','status':'selected',
                'activity':'construct' if e['kind']=='action' else 'coordinate','source':evidence(run,e['id']),
                'content':{'summary':{'status':'expressed','text':e['text'],'evidence':[evidence(run,e['id'])]}}})
    x={'run_id':run['id'],'source_hash':digest(run),'status':'complete_local_extraction','units':units}
    users=[u for u in units if u['actor']=='user'];actions=[u for u in units if u['kind']=='action']
    records=[];steps=[];changes=[]
    specs=[ [('introduce','a','Write report A.'),('introduce','b','Write report B.')],
            [('withdraw','b','Report B withdrawn.'),('introduce','address','Use the draft address.')],
            [('revise','address','FUTURE_APPROVAL: use final address.')]]
    for u,edits in zip(users,specs):
        values=[{'op':op,'record_id':rid,'text':text,'evidence':[u['source']],
                 **({'kind':'condition' if rid=='address' else 'work'} if op=='introduce' else {})} for op,rid,text in edits]
        records,delta=apply_edits(run,u,records,values);changes.extend(delta)
        steps.append({'unit_id':u['id'],'state_after':deepcopy(records)})
    work={'status':'complete','source_hash':digest(run),'extraction_hash':digest(x),
          'records':records,'steps':steps,'changes':changes}
    return run,x,work,users,actions


class WorkCorrespondenceTests(unittest.TestCase):
    def test_snapshot_and_packet_exclude_later_approval_and_dispatch_response(self):
        run,x,w,users,actions=fixture();snap=state_before(run,x,w,actions[1])
        self.assertEqual(snap['source_unit_id'],users[1]['id'])
        self.assertEqual([r['text'] for r in snap['records']],['Write report A.','Report B withdrawn.','Use the draft address.'])
        pool=candidate_records(w,snap)
        self.assertEqual(len(pool),2)
        self.assertEqual(pool[1]['requested_before_withdrawal']['text'],'Write report B.')
        req=relation_request(run,x,w,actions[1],snap,pool)
        self.assertNotIn('FUTURE_APPROVAL',str(req))
        self.assertNotIn('FUTURE_RESPONSE',str(req))
        self.assertIn('Use the draft address.',str(req))
        self.assertEqual(set(req['questions']),{r['version_id'] for r in pool})
        bad=deepcopy(w);bad['steps'][1]['state_after'][0]['evidence']=[users[2]['source']]
        with self.assertRaisesRegex(InputError,'Future evidence'):state_before(run,x,bad,actions[1])
        bad=deepcopy(w);bad['steps'][1]['state_after'][0]['trajectory_id']='another-task'
        with self.assertRaisesRegex(InputError,'Cross-trajectory'):state_before(run,x,bad,actions[1])

    def test_multiple_correspondences_replay_argmax_and_retain_exact_versions(self):
        run,x,w,users,actions=fixture()
        with tempfile.TemporaryDirectory() as directory:
            def transport(req):
                return {'model':req['model'],'answers':{key:{'type':'choice','choice':'unresolved','confidence':0,
                    'probabilities':{r:.8 if r=='prepares' else .05 for r in q['criteria']}}
                    for key,q in req['questions'].items()}}
            engine=Pipeline(directory,FileCandidates(Path(directory)/'c'),transport)
            result=build(run,x,w,engine.decide)
            self.assertEqual(len(result['relations']),6)
            self.assertEqual(engine.calls,3)
            self.assertTrue(audit(run,x,w,result,directory)['argmax_replayed'])
            links=[r for r in result['relations'] if r['from']==actions[1]['id']]
            self.assertEqual({r['requested_status_at_dispatch'] for r in links},{'requested','withdrawn'})
            self.assertEqual(links[1]['requested_work_version_id'],w['steps'][1]['state_after'][1]['version_id'])
            self.assertEqual(links[1]['requested_before_withdrawal'],'Write report B.')
            build(run,x,w,engine.decide);self.assertEqual(engine.calls,3)
            bad=deepcopy(result);bad['relations'][0]['requested_work_version_id']='future'
            with self.assertRaisesRegex(InputError,'dependency replay'):audit(run,x,w,bad,directory)
            changed=deepcopy(w);changed['note']='new work pass'
            self.assertNotEqual(path_for(directory,x,w),path_for(directory,x,changed))

    def test_empty_pool_and_batching_do_not_silently_drop_work(self):
        run,x,w,users,actions=fixture();empty=deepcopy(w);empty.update(steps=[],changes=[],records=[])
        result=build(run,x,empty,lambda r:self.fail('No candidate should trigger no model call'))
        self.assertEqual(result['relations'],[])
        self.assertTrue(all(a['status']=='no_prior_selected_requested_work' for a in result['actions']))
        for i in range(BATCH_SIZE):
            value=deepcopy(w['steps'][0]['state_after'][0]);value.update(id='extra'+str(i),version_id='extra-v'+str(i))
            w['steps'][0]['state_after'].append(value)
        packets=[]
        def select(req):
            packets.append(req)
            return {key:{'value':'none'} for key in req['questions']},digest(req)
        result=build(run,x,w,select)
        self.assertEqual(len(result['actions'][0]['choices']),BATCH_SIZE+2)
        self.assertEqual(len(result['actions'][0]['requests']),2)
        self.assertTrue(all(len(p['questions'])<=BATCH_SIZE for p in packets))
        self.assertEqual(result['relations'],[])


if __name__=='__main__':unittest.main()
