from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import work_target_refinement as refine
from tracker.schema import InputError,digest
from tracker.semantic_extraction import FileCandidates,Pipeline,read,write,generation_request,audit_result,load_extraction
from tests.test_semantic_extraction import fixture,response,proposals


def choose(value):
    def transport(req):
        keys=req['questions']['choice']['criteria']
        return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'unresolved','confidence':0,
            'probabilities':{k:.8 if k==value else .2/(len(keys)-1) for k in keys}}}}
    return transport


class TargetRefinementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.parent=root/'parent';self.out=root/'refined';self.run=fixture()
        engine=Pipeline(self.parent,FileCandidates(self.parent/'candidates'),response)
        pending=engine.run(self.run);unit=pending['units'][0]
        req=generation_request(self.run,unit['source'],'orient');proposal=proposals(req)
        proposal['candidates'][0]['fields']['needed_work']={'status':'expressed',
            'text':'Add the decorator to the reproduction class.','evidence':[req['source']]}
        write(self.parent/'candidates/responses'/f'{digest(req)}.json',proposal)
        self.original=engine.run(self.run);write(self.parent/'runs'/f'{self.run["id"]}.json',self.run)
        refine.initialize(self.out,self.parent,self.run['id'])

    def test_refines_one_field_retains_activity_and_replays_without_generation(self):
        self.assertEqual(refine.prepare(self.out)['requests'],1)
        result=refine.execute(self.out,choose('c1'))
        self.assertEqual(result['status'],'complete_local_extraction')
        self.assertEqual(result['budget_used']['candidate_requests'],0)
        new=read(self.out/'results'/f'{self.run["id"]}.json');old=self.original['units'][0];unit=new['units'][0]
        self.assertEqual(unit['activity_request'],old['activity_request'])
        self.assertEqual(unit['source'],old['source'])
        self.assertEqual(unit['content']['work_target'],old['content']['needed_work'])
        self.assertEqual({k:v for k,v in unit['content'].items() if k!='work_target'},
                         {k:v for k,v in old['content'].items() if k!='work_target'})
        self.assertEqual(read(self.parent/'results'/f'{self.run["id"]}.json'),self.original)
        self.assertTrue(refine.audit(self.out)['validation']['argmax_replayed'])
        self.assertEqual(refine.execute(self.out,lambda _:self.fail('Must reuse cached decision'))['budget_used']['jev_requests'],0)
        self.assertEqual(load_extraction(self.run,self.out)['document']['relations'],[])
        from tracker.semantic_collection import protocol
        previous=protocol({'raw_extraction':self.original},self.parent)
        current=protocol({'raw_extraction':new},self.out)
        self.assertNotEqual(previous['scope'],current['scope'])
        from tracker import semantic_history
        history=self.out.parent/'history'
        semantic_history.initialize(history,self.out,self.run['id'])
        self.assertEqual(semantic_history.load(history)[2],new)

    def test_budget_and_rejection_do_not_publish_original_as_refined(self):
        stopped=refine.execute(self.out,lambda _:self.fail('Budget before transport'),max_calls=0)
        self.assertIn('budget_stop',stopped)
        self.assertEqual(refine.audit(self.out)['status'],'interrupted')
        self.assertFalse((self.out/'results'/f'{self.run["id"]}.json').exists())
        result=refine.execute(self.out,choose('no_suitable_candidate'))
        self.assertEqual(result['status'],'needs_work')
        checkpoint=read(self.out/'checkpoints'/f'{self.run["id"]}.json')
        self.assertEqual(checkpoint['units'][0]['content'],{})
        self.assertEqual(refine.audit(self.out)['status'],'needs_work')

    def test_forged_provenance_or_selected_field_fails_audit(self):
        refine.execute(self.out,choose('c1'));path=self.out/'results'/f'{self.run["id"]}.json';original=read(path)
        for mutate in ('parent','field','contract'):
            bad=deepcopy(original)
            if mutate=='parent':bad['units'][0]['target_refinement']['parent_content_request']='invalid'
            elif mutate=='field':bad['units'][0]['content']['work_target']['text']='Complete the whole task.'
            else:bad['units'][0]['target_refinement']['schema']='unversioned'
            with self.subTest(mutate=mutate),self.assertRaises(InputError):audit_result(self.run,bad,self.out)
        self.assertTrue(audit_result(self.run,self.original,self.parent)['argmax_replayed'])

    def test_candidate_projection_is_category_conditioned_and_preserves_plan(self):
        unit=deepcopy(self.original['units'][0]);unit['activity']='plan'
        unit['content']['target']={'status':'expressed','text':'Restore service in three stages.','evidence':[unit['source']]}
        unit['plan_structure']={'sentinel':'same complete structure'}
        variants,origins=refine.proposals(unit)
        self.assertEqual(origins,['original_work_target','target'])
        self.assertTrue(all(v['plan_structure']==unit['plan_structure'] for v in variants))
        unit['activity']='social';unit['content'].pop('work_target')
        self.assertEqual(refine.proposals(unit),([],[]))

    def test_source_hash_change_and_repeated_refinement_are_rejected(self):
        unit=deepcopy(self.original['units'][0]);unit['target_refinement']={'schema':refine.VERSION}
        with self.assertRaises(InputError):refine.proposals(unit)
        source=self.out/'runs'/f'{self.run["id"]}.json';wrong=deepcopy(self.run);wrong['events'][0]['text']='Changed source'
        write(source,wrong)
        with self.assertRaisesRegex(InputError,'Frozen'):refine.load(self.out)

    def test_revision_cannot_hide_unprocessed_units_or_its_protocol(self):
        refine.execute(self.out,choose('c1'))
        selected=read(self.out/'results'/f'{self.run["id"]}.json')
        bad=deepcopy(selected);bad['units']=deepcopy(self.original['units'])
        with self.assertRaisesRegex(InputError,'unrefined'):audit_result(self.run,bad,self.out)
        bad=deepcopy(selected);bad.pop('content_revision')
        with self.assertRaisesRegex(InputError,'declared'):audit_result(self.run,bad,self.out)
        from tracker import semantic_revision
        from tracker.semantic_extraction import WORK_ORGANIZATION_ACTIVITY_ROUTING
        with self.assertRaisesRegex(InputError,'original extraction'):
            semantic_revision.initialize(self.out.parent/'reclassified',self.out,self.run['id'],WORK_ORGANIZATION_ACTIVITY_ROUTING)


if __name__=='__main__':unittest.main()
