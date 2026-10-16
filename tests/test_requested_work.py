from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline,FileCandidates as LocalCandidates,write
from tracker.requested_work import (apply_edits,build,FileCandidates,audit)
from tracker.jev import DEFAULT_MODEL


def fixture():
    run=normalize({'schema_version':'ATIF-v1.7','session_id':'requested-work-test','agent':{'name':'test','version':'1'},
        'steps':[{'step_id':1,'source':'user','message':'Exchange the first and second kettles.'},
                 {'step_id':2,'source':'user','message':'Drop the second exchange. Keep the first.'},
                 {'step_id':3,'source':'user','message':'Only the first exchange, as agreed.'}]})[0]
    units=[{'id':'unit-'+e['id'],'actor':'user','trajectory_id':e['trajectory_id'],'kind':'semantic',
            'status':'selected','source':evidence(run,e['id']),'content':{}} for e in run['events']]
    return run,{'status':'complete_local_extraction','run_id':run['id'],'units':units}


def edit(unit,op,rid,text):
    return {'op':op,'record_id':rid,'text':text,'evidence':[unit['source']],
            **({'kind':'work'} if op=='introduce' else {})}


class RequestedWorkTests(unittest.TestCase):
    def test_partial_withdrawal_preserves_other_record_and_prior_versions(self):
        run,x=fixture();a,b,c=x['units']
        state,first=apply_edits(run,a,[],[edit(a,'introduce','first','Exchange first kettle.'),
                                         edit(a,'introduce','second','Exchange second kettle.')])
        original=deepcopy(state)
        after,changes=apply_edits(run,b,state,[edit(b,'withdraw','second','Keep original second kettle.')])
        self.assertEqual(state,original)
        self.assertEqual(after[0],state[0])
        self.assertEqual(after[1]['status'],'withdrawn')
        self.assertEqual(changes[0]['before'],state[1])
        self.assertNotEqual(changes[0]['after']['version_id'],state[1]['version_id'])
        with self.assertRaisesRegex(InputError,'inactive'):apply_edits(run,c,after,[edit(c,'withdraw','second','Withdraw again.')])
        with self.assertRaisesRegex(InputError,'Identical'):apply_edits(run,c,after,[edit(c,'revise','first','Exchange first kettle.')])
        bad=edit(a,'introduce','third','New third work.');bad['evidence']=[c['source']]
        with self.assertRaisesRegex(InputError,'Future evidence'):apply_edits(run,a,[],[bad])

    def test_repeated_confirmation_keeps_state_without_another_change(self):
        run,x=fixture();a,b,c=x['units']
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            class Provider(FileCandidates):
                def get(self,run,req,unit):
                    edits=([edit(a,'introduce','first','Exchange first kettle.'),edit(a,'introduce','second','Exchange second kettle.')]
                           if unit['id']==a['id'] else [edit(b,'withdraw','second','Keep original second kettle.')]
                           if unit['id']==b['id'] else [])
                    value={'request_hash':digest(req),'producer':'structural fixture','candidates':[{'edits':edits}] if edits else []}
                    write(self.directory/'responses'/f'{digest(req)}.json',value)
                    return super().get(run,req,unit)
            def response(req):
                choices=req['questions']['choice']['criteria'];winner='c0' if 'c0' in choices else 'unchanged'
                return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','choice':'unresolved','confidence':0,
                    'probabilities':{k:0.8 if k==winner else 0.2/(len(choices)-1) for k in choices}}}}
            engine=Pipeline(root,LocalCandidates(root/'c'),response)
            result=build(run,x,Provider(root/'work_candidates'),engine.choose)
            self.assertEqual(result['status'],'complete')
            self.assertEqual(len(result['changes']),3)
            self.assertEqual(result['steps'][-1]['status'],'unchanged')
            self.assertEqual(result['steps'][-1]['state_after'],result['steps'][-2]['state_after'])
            self.assertTrue(audit(run,x,result,root)['argmax_replayed'])
            bad=deepcopy(result);bad['records'][0]['status']='completed'
            with self.assertRaisesRegex(InputError,'source replay'):audit(run,x,bad,root)

    def test_missing_candidate_stops_dependent_history_without_claiming_completion(self):
        run,x=fixture()
        with tempfile.TemporaryDirectory() as d:
            result=build(run,x,FileCandidates(d),lambda q:self.fail('No ready candidate request'))
            self.assertEqual(result['status'],'needs_work')
            self.assertEqual(len(result['steps']),1)
            self.assertEqual(result['records'],[])


if __name__=='__main__':unittest.main()
