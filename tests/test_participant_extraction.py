from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.schema import InputError,digest
from tracker.semantic_extraction import (FileCandidates,Pipeline,windows,audit_result,
    read,write,load_extraction,episode_scope,generation_request,PARTICIPANT_SCOPE)
from tests.test_semantic_extraction import fixture,response,proposals


class CandidateFixture(FileCandidates):
    def content(self,run,ref,activity):
        req=generation_request(run,ref,activity,self.context_policy)
        value=proposals(req)
        # These are structural fixtures, not semantic reference annotations.
        write(self.directory/'responses'/f'{digest(req)}.json',value)
        return super().content(run,ref,activity)


class ParticipantTests(unittest.TestCase):
    def test_actor_scope_preserves_old_windows_and_excludes_policy_and_copies(self):
        run=fixture();old=windows(run)
        policy=deepcopy(run['events'][0]);policy.update(id='policy',actor='system',index=-1)
        copied=deepcopy(run['events'][0]);copied.update(id='copy',copied_context=True,index=100)
        hidden=deepcopy(run['events'][0]);hidden.update(id='hidden',agent_visibility='not_established',index=101)
        run['events']=[policy,*run['events'],copied,hidden]
        current=windows(run,include_user=True)
        self.assertEqual([w for w in current if w['kind']!='user_span'],old)
        self.assertEqual([w['event_id'] for w in current if w['kind']=='user_span'],['e1','e3'])
        self.assertEqual(len({w['id'] for w in current}),3)

    def test_full_and_episode_replay_keep_speaker_and_future_cutoff(self):
        run=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine=Pipeline(root,CandidateFixture(root/'c'),response)
            result=engine.run(run,include_user=True)
            audit=audit_result(run,result,root)
            self.assertEqual(result['status'],'complete_local_extraction')
            self.assertEqual(audit['contributions_by_actor'],{'agent':1,'user':2})
            self.assertEqual((audit['agent_units'],audit['user_units']),(1,2))
            self.assertEqual(result['participant_scope'],PARTICIPANT_SCOPE)
            first=result['units'][0]
            packet=read(root/'decisions'/f"{first['activity_request']}.json")['request']
            self.assertEqual(packet['state']['source_actor_context']['actor'],'user')
            self.assertEqual(packet['state']['expression_form'],'user-authored expression')
            self.assertNotIn('FUTURE',str(packet))
            bad=deepcopy(result);bad.pop('participant_scope')
            with self.assertRaisesRegex(InputError,'coverage differs'):audit_result(run,bad,root)
            bad=deepcopy(result);bad['units'][0]['actor']='agent'
            with self.assertRaisesRegex(InputError,'attribution differs'):audit_result(run,bad,root)
            view=load_extraction(run,root)
            self.assertEqual(view['document']['objective']['text'],'Restore service.')
            scope=episode_scope(run,'e1','e2',include_user=True)
            episode=engine.run(run,scope=scope,include_user=True)
            self.assertEqual(audit_result(run,episode,root)['user_units'],1)
            with self.assertRaisesRegex(InputError,'Episode selection differs'):engine.run(run,scope=scope)

    def test_system_policy_does_not_become_the_initial_user_objective(self):
        run=fixture();policy=deepcopy(run['events'][0])
        policy.update(id='policy',actor='system',index=-1,text='Governing system policy')
        run['events'].insert(0,policy)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine=Pipeline(root,CandidateFixture(root/'c'),response)
            engine.run(run)
            objective=load_extraction(run,root)['document']['objective']
            self.assertEqual(objective['text'],'Restore service.')
            self.assertEqual(objective['evidence'][0]['event_id'],'e1')


if __name__=='__main__':unittest.main()
