import copy
from pathlib import Path
import tempfile
import unittest

from tracker import semantic_revision as revision
from tracker.schema import InputError,digest
from tracker.semantic_extraction import (FileCandidates,Pipeline,generation_request,read,write,
    WORK_ORGANIZATION_ACTIVITY_ROUTING,ACTIVITY_ROUTING,audit_result,load_extraction)
from tests.test_semantic_extraction import fixture,response,proposals


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.parent=self.root/'parent';self.out=self.root/'revised';self.run=fixture()
        provider=FileCandidates(self.parent/'candidates');engine=Pipeline(self.parent,provider,response)
        pending=engine.run(self.run);unit=pending['units'][0]
        req=generation_request(self.run,unit['source'],'orient')
        write(self.parent/'candidates/responses'/f'{digest(req)}.json',proposals(req))
        self.original=engine.run(self.run)
        write(self.parent/'runs'/f'{self.run["id"]}.json',self.run)
        revision.initialize(self.out,self.parent,self.run['id'],WORK_ORGANIZATION_ACTIVITY_ROUTING)

    def test_unchanged_content_reuses_exact_decision_but_reclassifies_and_resumes(self):
        self.assertEqual(revision.prepare(self.out)['units'],1)
        output=revision.execute(self.out,response)
        self.assertEqual(output['status'],'complete_local_extraction')
        self.assertEqual(output['reused_content'],1)
        self.assertEqual(output['budget_used']['jev_requests'],1)
        revised=read(self.out/'results'/f'{self.run["id"]}.json')
        self.assertNotEqual(revised['units'][0]['activity_request'],self.original['units'][0]['activity_request'])
        self.assertEqual(revised['units'][0]['content_request'],self.original['units'][0]['content_request'])
        self.assertEqual(revision.audit(self.out)['changes'],[])
        resumed=revision.execute(self.out,lambda _:self.fail('Saved decisions must replay'),max_calls=0)
        self.assertEqual(resumed['budget_used']['jev_requests'],0)
        self.assertEqual(read(self.parent/'results'/f'{self.run["id"]}.json'),self.original)

    def test_changed_activity_cannot_inherit_old_content_or_relations(self):
        # A test-only selector; this tests state transitions, not label accuracy.
        def select(req):
            packet=response(req)
            if req['state']['stage']=='activity':
                labels=req['questions']['choice']['criteria']
                packet['answers']['choice']['probabilities']={k:0.9 if k=='reason' else 0.1/(len(labels)-1) for k in labels}
            return packet
        write(self.parent/'plan_relations/should-not-copy.json',{'sentinel':'old relations'})
        output=revision.execute(self.out,select)
        self.assertEqual(output['status'],'needs_work')
        self.assertEqual(output['changes'][0]['to'],'reason')
        self.assertFalse((self.out/'results'/f'{self.run["id"]}.json').exists())
        self.assertFalse((self.out/'plan_relations').exists())
        pending=read(self.out/'checkpoints'/f'{self.run["id"]}.json');unit=pending['units'][0]
        self.assertEqual(unit['content'],{});self.assertNotIn('content_request',unit)
        req=read(self.out/'candidates/requests'/f'{unit["candidate_request"]}.json')
        write(self.out/'candidates/responses'/f'{digest(req)}.json',proposals(req))
        finished=revision.execute(self.out,select)
        self.assertEqual(finished['status'],'complete_local_extraction')
        self.assertEqual(finished['budget_used']['jev_requests'],1)
        self.assertEqual(revision.audit(self.out)['changes'][0]['to'],'reason')
        self.assertEqual(load_extraction(self.run,self.out)['document']['relations'],[])

    def test_budget_stop_preserves_parent_and_resumes(self):
        stopped=revision.execute(self.out,lambda _:self.fail('Budget must prevent transport'),max_calls=0)
        self.assertEqual(stopped['status'],'budget_reached')
        self.assertFalse((self.out/'results'/f'{self.run["id"]}.json').exists())
        self.assertEqual(revision.execute(self.out,response)['status'],'complete_local_extraction')
        self.assertEqual(revision.audit(self.out)['units'],1)

    def test_plan_links_rebuild_only_from_a_complete_revision(self):
        revision.execute(self.out,response)
        receipt=revision.rebuild_plan_links(self.out,lambda _:self.fail('No Plans imply no comparison calls'),max_calls=0)
        self.assertEqual(receipt['status'],'complete')
        self.assertEqual(receipt['relations'],0)
        self.assertEqual(receipt['budget_used']['jev_requests'],0)
        from tracker import plan_relations
        result=read(self.out/'results'/f'{self.run["id"]}.json')
        self.assertTrue(plan_relations.path_for(self.out,result).exists())

    def test_changed_configuration_or_frozen_parent_is_rejected(self):
        with self.assertRaisesRegex(InputError,'configuration changed'):
            revision.initialize(self.out,self.parent,self.run['id'],ACTIVITY_ROUTING)
        parent=read(self.out/'parent.json');parent['note']='changed'
        write(self.out/'parent.json',parent)
        with self.assertRaisesRegex(InputError,'parent changed'):revision.prepare(self.out)

    def test_wrong_provider_response_is_retained_without_publishing(self):
        with self.assertRaisesRegex(InputError,'model mismatch'):
            revision.execute(self.out,lambda _:{'model':'wrong','answers':{}})
        self.assertEqual(read(self.out/'last-revision.json')['status'],'interrupted')
        self.assertEqual(len(list((self.out/'wire').rglob('*.json'))),1)
        self.assertFalse((self.out/'results'/f'{self.run["id"]}.json').exists())

    def test_map_loading_also_checks_revision_lineage(self):
        revision.execute(self.out,response)
        path=self.out/'results'/f'{self.run["id"]}.json';result=read(path)
        result['revision']['parent_hash']='wrong';write(path,result)
        with self.assertRaisesRegex(InputError,'Revision result configuration'):
            load_extraction(self.run,self.out)

    def test_native_mini_feedback_and_user_followup_survive_revision(self):
        from tests.test_mini_native import source,assistant,action,result
        from tracker.adapters import normalize
        run=normalize(source([assistant([action('echo ok','call-1')]),result('call-1'),
                              {'role':'user','content':'Also check the second case.'}]))[0]
        class SourceProvider(FileCandidates):
            def content(self,run,ref,activity):
                req=generation_request(run,ref,activity)
                return {'status':'ready','request_hash':digest(req),'producer':'test source provider',
                        'candidates':[{'fields':{k:{'status':'expressed','text':ref['text'],'evidence':[ref]} for k in req['field_contract']}}]}
        parent=self.root/'native-parent';out=self.root/'native-revision'
        prior=Pipeline(parent,SourceProvider(parent/'candidates'),response).run(run,include_user=True)
        write(parent/'runs'/f'{run["id"]}.json',run)
        revision.initialize(out,parent,run['id'],WORK_ORGANIZATION_ACTIVITY_ROUTING)
        self.assertEqual(revision.execute(out,response)['status'],'complete_local_extraction')
        view=load_extraction(run,out)
        self.assertEqual(view['validation']['user_units'],2)
        self.assertEqual(view['validation']['actions'],1)
        self.assertEqual(view['validation']['source_feedback_links'],1)
        self.assertEqual([u['source'] for u in prior['units']],[u['source'] for u in view['raw_extraction']['units']])


if __name__=='__main__':unittest.main()
