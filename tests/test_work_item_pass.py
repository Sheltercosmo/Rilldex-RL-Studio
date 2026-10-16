from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from tracker import work_item_pass as workspace,declared_work_items as items,semantic_catalog
from tracker.schema import InputError,digest
from tracker.semantic_extraction import read,write
from tracker.store import Store
from tests.test_work_declarations import fixture


def answer(req):
    return {'model':req['model'],'answers':{k:{'type':'choice','choice':'c1','confidence':0,
        'probabilities':{c:float(c==('same_whole_work' if 'same_whole_work' in q['criteria'] else 'c0')) for c in q['criteria']}} for k,q in req['questions'].items()}}


class WorkItemPassTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'pass'
        self.run,self.doc=fixture(['I will produce report A.','Report A is done.'])
        self.bundle={'available':True,'document':self.doc,'validation':{}}
        self.store=Store(Path(self.temp.name)/'store.sqlite');self.store.add([self.run])
        self.profile=patch.dict(semantic_catalog.PROFILES,{'test-parent':{'kind':'extraction','directory':self.root/'parent','label':'Test parent'}})
        self.profile.start();self.addCleanup(self.profile.stop)
        self.loader=patch.object(semantic_catalog,'load_extraction',side_effect=lambda *a,**k:deepcopy(self.bundle))
        self.loader.start();self.addCleanup(self.loader.stop)
        workspace.prepare(self.store,self.root,self.run['id'],'test-parent')

    def candidates(self,count=2):
        for index,u in enumerate(self.doc['units'][:count]):
            proposal=items.proposal_request(self.run,self.doc,u,version=items.DESCRIBED_VERSION)
            write(self.root/'candidates/responses'/f'{digest(proposal)}.json',{
                'request_hash':digest(proposal),'producer':'synthetic-test',
                'candidates':[{'reading':'Expresses an undertaking or achieved-work claim.','items':[
                    {'id':'a','work':'Produce report A.','declaration':'commits' if index==0 else 'reports_finished','evidence':[u['source']]}]}]})

    def test_missing_candidates_and_partial_pass_do_not_become_complete(self):
        self.candidates(1);partial=workspace.execute(self.root,answer)
        self.assertEqual(partial['coverage'],{'eligible_units':2,'selected_units':1})
        self.assertEqual(partial['status'],'incomplete');self.assertFalse((self.root/'complete.json').exists())
        self.candidates();done=workspace.execute(self.root,answer)
        self.assertEqual(done['new_calls'],1);self.assertEqual(done['status'],'complete')
        repeated=workspace.execute(self.root,lambda _:self.fail('Must reuse decisions'))
        self.assertEqual(repeated['new_calls'],0)
        result=read(self.root/'complete.json');workspace.audit(self.run,self.doc,result,self.root)
        result['observations'].pop()
        with self.assertRaisesRegex(InputError,'every eligible'):workspace.audit(self.run,self.doc,result,self.root)

    def test_registered_projection_keeps_units_and_rejects_changed_observation(self):
        self.candidates();workspace.execute(self.root,answer);workspace.history(self.root,answer)
        history=read(self.root/'history.json')
        reviews={'origin':'implementation-assistant-source-review','source_hash':digest(self.run),'history_hash':digest(history),
                 'notes':[{'record_ids':[history['records'][0]['id']],'unit_ids':['u0'],'text':'Check scope.'}]}
        write(self.root/'history-review.json',reviews)
        original=deepcopy(self.doc);saved=workspace.register(self.store,self.root,'Declarations')
        bundle=semantic_catalog.load(self.run,saved['observer'],self.store)
        self.assertEqual(bundle['document']['units'],original['units'])
        self.assertEqual(bundle['document']['relations'][:-1],original['relations'])
        self.assertEqual(bundle['document']['relations'][-1]['type'],'declares_same_work_as')
        self.assertEqual(len(bundle['document']['declared_work_history']['records']),1)
        self.assertEqual(bundle['document']['declared_work_history']['review_notes'],reviews['notes'])
        self.assertEqual(len(bundle['document']['declared_work_items']['observations']),2)
        self.assertNotIn('declared_work_items',semantic_catalog.load(self.run,'test-parent',self.store)['document'])
        with patch.dict(semantic_catalog.PROFILES,{},clear=True):
            catalog=semantic_catalog.catalog(self.store)
        self.assertEqual([r['observer'] for r in catalog['maps']],[saved['observer']])
        self.assertEqual(catalog['unavailable'],[])
        changed=deepcopy(reviews);changed['notes'][0]['text']='Changed';write(self.root/'history-review.json',changed)
        with self.assertRaisesRegex(InputError,'review changed'):semantic_catalog.load(self.run,saved['observer'],self.store)
        with patch.dict(semantic_catalog.PROFILES,{},clear=True):
            catalog=semantic_catalog.catalog(self.store)
        self.assertEqual(catalog['maps'],[])
        self.assertEqual(catalog['unavailable'][0]['observer'],saved['observer'])
        write(self.root/'history-review.json',reviews)
        result=read(self.root/'complete.json');result['observations'][0]['items'][0]['work']='Different work';write(self.root/'complete.json',result)
        with self.assertRaisesRegex(InputError,'changed'):semantic_catalog.load(self.run,saved['observer'],self.store)

    def test_scope_parts_are_additive_replayable_and_registration_pins_them(self):
        self.candidates();workspace.execute(self.root,answer)
        earlier=workspace.register(self.store,self.root,'Before scope parts')
        old=semantic_catalog.load(self.run,earlier['observer'],self.store)['document']
        def scopes(req):
            winners={q:('faithful' if q=='faithfulness' else 'usable' if q=='partition' else 'work') for q in req['questions']}
            return {'model':req['model'],'answers':{q:{'type':'choice','probabilities':{c:float(c==winners[q]) for c in spec['criteria']}} for q,spec in req['questions'].items()}}
        dest=self.root/'scope-parts'
        with self.assertRaisesRegex(InputError,'separate directory'):workspace.scope_parts(self.root,scopes,parts_directory=self.root)
        result=workspace.scope_parts(self.root,scopes,parts_directory=dest)
        self.assertEqual(result['new_calls'],2)
        replay=workspace.scope_parts(self.root,lambda _:self.fail('Replay should not call Jev'),parts_directory=dest)
        self.assertEqual(replay['new_calls'],0)
        saved=workspace.register(self.store,self.root,'With scope parts',parts_directory=dest)
        current=semantic_catalog.load(self.run,saved['observer'],self.store)['document']
        self.assertEqual(current['units'],old['units']);self.assertEqual(current['relations'],old['relations'])
        self.assertEqual(len(current['work_scope_parts']['observations']),2)
        changed=read(dest/'work-scope-parts.json');changed['observations'][0]['groups'][0]['role']='purpose';write(dest/'work-scope-parts.json',changed)
        with self.assertRaisesRegex(InputError,'scope parts changed'):semantic_catalog.load(self.run,saved['observer'],self.store)
        self.assertEqual(semantic_catalog.load(self.run,earlier['observer'],self.store)['document'],old)

    def test_changed_source_or_candidates_cannot_replay_as_same_pass(self):
        self.candidates();workspace.execute(self.root,answer)
        original=read(self.root/'source.json');changed=deepcopy(original);changed['events'][0]['text']='Changed';write(self.root/'source.json',changed)
        with self.assertRaisesRegex(InputError,'changed'):workspace.load(self.root)
        write(self.root/'source.json',original)
        p=next((self.root/'candidates/responses').glob('*.json'));value=read(p);value['candidates'][0]['items'][0]['work']='Changed';write(p,value)
        with self.assertRaises((InputError,FileNotFoundError)):workspace.audit(self.run,self.doc,read(self.root/'complete.json'),self.root)

    def test_rejected_model_response_is_retained_before_publication(self):
        self.candidates()
        with self.assertRaisesRegex(InputError,'model mismatch'):workspace.execute(self.root,lambda _: {'model':'wrong','answers':{}})
        self.assertEqual(len(list((self.root/'wire').glob('*/*.json'))),1)
        self.assertFalse((self.root/'complete.json').exists())
        workspace.execute(self.root,answer)
        self.assertEqual(len(list((self.root/'wire').glob('*/*.json'))),3)

    def test_action_observer_is_additive_and_pins_correspondence_and_review(self):
        from tests.test_declared_work_actions import setup
        self.run,self.doc,_,_=setup();self.bundle={'available':True,'document':self.doc,'validation':{}}
        self.root=Path(self.temp.name)/'actions';self.store.add([self.run])
        workspace.prepare(self.store,self.root,self.run['id'],'test-parent');self.candidates()
        workspace.execute(self.root,answer);workspace.history(self.root,answer)
        earlier=workspace.register(self.store,self.root,'Statements')
        def roles(req):return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{c:float(c=='attempts') for c in q['criteria']}} for k,q in req['questions'].items()}}
        workspace.actions(self.root,roles);observed=read(self.root/'action-correspondence.json')
        relation=observed['relations'][0]
        review={'origin':'implementation-assistant-source-review','source_hash':digest(self.run),'observation_hash':digest(observed),'limitations':'Known development limitation.',
            'notes':[{'kind':'relation_review','text':'Check this relation.', 'relation_ref':{k:relation[k] for k in ('from','to','type','declared_work_id')}}]}
        write(self.root/'action-review.json',review);saved=workspace.register(self.store,self.root,'Statements and actions')
        self.assertNotIn('declared_work_actions',semantic_catalog.load(self.run,earlier['observer'],self.store)['document'])
        current=semantic_catalog.load(self.run,saved['observer'],self.store)['document']
        self.assertEqual(current['units'],self.doc['units']);self.assertEqual(len(current['declared_work_actions']['relations']),2)
        self.assertEqual(current['review_notes'][0]['evidence'],relation['evidence'])
        def results(req):return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{c:float(c==('not_established' if k=='result' else 'not_reported')) for c in q['criteria']}} for k,q in req['questions'].items()}}
        workspace.results(self.root,results);with_results=workspace.register(self.store,self.root,'Work with result evidence')
        self.assertEqual(semantic_catalog.load(self.run,saved['observer'],self.store)['document'],current)
        result_doc=semantic_catalog.load(self.run,with_results['observer'],self.store)['document']
        self.assertEqual(result_doc['units'],current['units']);self.assertEqual(len(result_doc['work_results']['observations']),2)
        def staged(req):
            winners={'mechanism':'change','error':'not_reported','warning':'not_reported','outcome':'not_established_change',
                     'material':'invocation_echo_only','result':'not_established','unmet_condition':'not_reported'}
            return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{c:float(c==winners[k]) for c in q['criteria']}} for k,q in req['questions'].items()}}
        target=self.root/'result-variant'
        with self.assertRaisesRegex(InputError,'separate result directory'):workspace.results(self.root,staged,protocol='operation')
        workspace.results(self.root,staged,result_directory=target,protocol='operation')
        variant=workspace.register(self.store,self.root,'Operation-supported results',result_directory=target)
        variant_doc=semantic_catalog.load(self.run,variant['observer'],self.store)['document']
        self.assertEqual(variant_doc['work_results']['schema'],'work-result-evidence/7')
        self.assertEqual(variant_doc['units'],result_doc['units'])
        self.assertEqual(semantic_catalog.load(self.run,with_results['observer'],self.store)['document'],result_doc)
        broken=read(target/'work-results.json');broken['observations'][0]['result']='fulfilled';write(target/'work-results.json',broken)
        with self.assertRaisesRegex(InputError,'work results changed'):semantic_catalog.load(self.run,variant['observer'],self.store)
        self.assertEqual(semantic_catalog.load(self.run,with_results['observer'],self.store)['document'],result_doc)
        outcomes=read(self.root/'work-results.json');changed=deepcopy(outcomes);changed['observations'][0]['result']='fulfilled';write(self.root/'work-results.json',changed)
        with self.assertRaisesRegex(InputError,'work results changed'):semantic_catalog.load(self.run,with_results['observer'],self.store)
        self.assertEqual(semantic_catalog.load(self.run,saved['observer'],self.store)['document'],current)
        write(self.root/'work-results.json',outcomes)
        review['limitations']='Changed';write(self.root/'action-review.json',review)
        with self.assertRaisesRegex(InputError,'review changed'):semantic_catalog.load(self.run,saved['observer'],self.store)


if __name__=='__main__':unittest.main()
