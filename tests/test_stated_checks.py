"""Evidence boundaries and provenance for agent checking contents."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError,digest,dumps
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline,FileCandidates
from tracker.feedback_assessments import linked_feedback
from tracker.stated_checks import VERSION,FOCUSED_VERSION,MATERIAL_VERSION,INTENT_VERSION,ROUTED_VERSION,validate_candidates,content_request,evidence_request,build,audit,derive_candidates,specification_request,execute,path_for,role_request


def fixture():
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Create the report.',
         'agent':{'thought':'The report is generated. Check its existence and contents.','action':'ls results/'},
         'environment':'report.pdf'},
        {'step':1,'agent':{'thought':'FUTURE_CLAIM: everything passed.','action':'finish'},'environment':'done'}]})[0]
    units=[]
    for event in run['events']:
        if event['actor']!='agent':continue
        units.append({'id':'u-'+event['id'],'actor':'agent','trajectory_id':event['trajectory_id'],'status':'selected',
                      'kind':'action' if event['kind']=='action' else 'semantic','activity':'inspect' if event['kind']=='action' else 'orient',
                      'source':evidence(run,event['id']),
                      'content':{'summary':{'status':'expressed','text':event['text'],'evidence':[evidence(run,event['id'])]}}})
    local={'run_id':run['id'],'source_hash':digest(run),'status':'complete_local_extraction','units':units}
    owner=next(u for u in units if u['kind']=='semantic');action=next(u for u in units if u['kind']=='action')
    check={'text':'Check report existence and contents.','evidence':[owner['source']],
           'facets':[{'id':key,'text':text,'evidence':[owner['source']]} for key,text in [('existence','Check report presence.'),('contents','Inspect report contents.')]]}
    proposals={'schema':VERSION,'source_hash':digest(run),'extraction_hash':digest(local),'producer':'authored-test',
               'units':[{'unit_id':owner['id'],'candidates':[check]}]}
    return run,local,owner,action,check,proposals


class StatedChecksTests(unittest.TestCase):
    def test_applicability_keeps_report_and_decision_choices_without_running_content_or_evidence(self):
        run,local,u,a,c,p=fixture()
        self.assertNotIn('FUTURE_CLAIM',dumps(role_request(run,local,u)))
        for winner in ['report_only','decision_only','other','unresolved']:
            with self.subTest(winner=winner),tempfile.TemporaryDirectory() as directory:
                def transport(req):
                    self.assertEqual(req['state']['stage'],'checking_applicability')
                    keys=req['questions']['choice']['criteria']
                    return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'checking_work',
                        'probabilities':{k:.6 if k==winner else .4/(len(keys)-1) for k in keys}}}}
                engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),transport)
                result=build(run,local,p,engine.decide,ROUTED_VERSION)
                item=result['observations'][0]
                self.assertEqual(item['applicability']['choice'],winner)
                self.assertEqual(item['selection'],'route:'+winner)
                self.assertEqual(item['content_selection'],'not_run');self.assertEqual(result['relations'],[])
                self.assertEqual(audit(run,local,p,result,directory)['content_selections'],0)
                self.assertEqual(engine.calls,1)

    def test_checking_applicability_does_not_force_acceptance_of_an_unfaithful_bundle(self):
        run,local,u,a,c,p=fixture();stages=[]
        with tempfile.TemporaryDirectory() as directory:
            def transport(req):
                stage=req['state']['stage'];stages.append(stage)
                winner='checking_work' if stage=='checking_applicability' else 'no_suitable_candidate'
                keys=req['questions']['choice']['criteria']
                return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':winner,
                    'probabilities':{k:.8 if k==winner else .2/(len(keys)-1) for k in keys}}}}
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),transport)
            result=build(run,local,p,engine.decide,ROUTED_VERSION)
            self.assertEqual(stages,['checking_applicability','stated_check_contents'])
            self.assertEqual(result['observations'][0]['selection'],'no_suitable_candidate')
            self.assertEqual(audit(run,local,p,result,directory)['content_selections'],1)
            self.assertEqual(result['relations'],[])

    def test_new_content_contract_preserves_none_and_candidate_gap_as_raw_decisions(self):
        run,local,u,a,c,p=fixture();original=deepcopy(local)
        for winner in ['none','no_suitable_candidate','unresolved']:
            with self.subTest(winner=winner),tempfile.TemporaryDirectory() as directory:
                def transport(req):
                    self.assertEqual(req['state']['stage'],'stated_check_contents')
                    keys=req['questions']['choice']['criteria']
                    return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'c0',
                        'probabilities':{k:.51 if k==winner else .49/(len(keys)-1) for k in keys}}}}
                engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),transport)
                result=build(run,local,p,engine.decide,INTENT_VERSION)
                self.assertEqual(engine.calls,1);self.assertEqual(result['relations'],[])
                self.assertEqual(result['observations'][0]['selection'],winner)
                self.assertNotIn('specifications',result['observations'][0]);self.assertEqual(local,original)
                self.assertTrue(audit(run,local,p,result,directory)['argmax_replayed'])

    def test_new_content_version_keeps_material_choices_and_refuses_to_replace_old_pass(self):
        run,local,u,a,c,p=fixture();c['id']='check-test'
        self.assertNotEqual(content_request(run,local,u,p['units'][0],p,MATERIAL_VERSION),content_request(run,local,u,p['units'][0],p,INTENT_VERSION))
        old=evidence_request(run,local,u,c,c['facets'][0],a,linked_feedback(run,local)[0],MATERIAL_VERSION)
        new=evidence_request(run,local,u,c,c['facets'][0],a,linked_feedback(run,local)[0],INTENT_VERSION)
        self.assertEqual(old['questions'],new['questions'])
        with tempfile.TemporaryDirectory() as directory:
            from tracker.semantic_extraction import write
            write(path_for(directory,local),{'schema':MATERIAL_VERSION})
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),lambda r:self.fail('Must stop before inference'))
            with self.assertRaisesRegex(InputError,'preserve the previous'):execute(run,local,p,engine,INTENT_VERSION)

    def test_derived_pool_covers_every_contribution_without_inferring_check_labels(self):
        run,local,u,a,c,p=fixture()
        other=next(v for v in local['units'] if v['kind']=='semantic' and v['id']!=u['id'])
        other['content']['work_target']={'status':'expressed','text':'Deliver the report.','evidence':[other['source']]}
        p['extraction_hash']=digest(local)
        proposals=derive_candidates(run,local,p)
        self.assertEqual(len(proposals['units']),2)
        self.assertEqual(proposals['units'][0]['candidates'],p['units'][0]['candidates'])
        self.assertEqual(proposals['units'][1]['candidates'][0]['text'],'Deliver the report.')
        self.assertEqual(proposals['units'][1]['origin']['kind'],'selected_local_contents')
        self.assertNotIn('selection',proposals['units'][1])

    def test_material_and_specification_questions_have_distinct_scopes_and_cutoffs(self):
        run,local,u,a,c,p=fixture();c['id']='check-test'
        specification=specification_request(run,local,u,c,c['facets'][1])
        self.assertNotIn('report.pdf',dumps(specification));self.assertNotIn('FUTURE_CLAIM',dumps(specification))
        response=evidence_request(run,local,u,c,c['facets'][1],a,linked_feedback(run,local)[0],MATERIAL_VERSION)
        self.assertEqual(set(response['questions']['choice']['criteria']),{'available','partial','absent','unobserved','unresolved'})
        self.assertNotIn('specifications',response['state'])
        self.assertIn('No acceptance criterion is needed',response['questions']['choice']['instructions'])
        self.assertNotEqual(specification['state']['cutoff_event_id'],response['state']['cutoff_event_id'])

    def test_unrelated_candidate_rows_do_not_change_local_content_decision(self):
        run,local,u,a,c,p=fixture();row=p['units'][0]
        before=content_request(run,local,u,row,p,MATERIAL_VERSION)
        changed=deepcopy(p);changed['units'].append({'unit_id':'unrelated','candidates':[]})
        self.assertEqual(before,content_request(run,local,u,row,changed,MATERIAL_VERSION))
        self.assertNotEqual(content_request(run,local,u,row,p),content_request(run,local,u,row,changed))

    def test_material_choice_does_not_depend_on_whether_test_is_defined(self):
        run,local,u,a,c,p=fixture()
        with tempfile.TemporaryDirectory() as directory:
            def transport(req):
                stage=req['state']['stage']
                winner={'stated_check_contents':'c0','check_specification':'observation_only',
                        'stated_check_dispatch':'prepares','stated_check_response':'absent'}[stage]
                keys=req['questions']['choice']['criteria'];rest=.3/(len(keys)-1)
                return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'unresolved',
                        'probabilities':{k:.7 if k==winner else rest for k in keys}}}}
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),transport)
            result=build(run,local,p,engine.decide,MATERIAL_VERSION);item=result['observations'][0]
            self.assertEqual(engine.calls,7)
            self.assertEqual({s['choice'] for s in item['specifications']},{'observation_only'})
            self.assertEqual({r['choice'] for a in item['actions'] for f in a['facets'] for r in f['responses']},{'absent'})
            self.assertTrue(audit(run,local,p,result,directory)['argmax_replayed'])

    def test_focused_question_names_only_its_facet_and_keeps_source_context(self):
        run,local,u,a,c,p=fixture();c['id']='check-test'
        req=evidence_request(run,local,u,c,c['facets'][0],a,linked_feedback(run,local)[0],FOCUSED_VERSION)
        self.assertNotIn('check',req['state'])
        self.assertEqual(req['state']['parent_check_id'],'check-test')
        self.assertEqual(req['state']['facet']['id'],'existence')
        self.assertTrue(req['questions']['choice']['instructions'].startswith('Evaluate ONLY this checking target: Check report presence.'))
        self.assertIn('Check its existence and contents.',dumps(req['state']['prefix']))
        self.assertNotIn('FUTURE_CLAIM',dumps(req))

    def test_sources_precede_their_own_dispatch_and_do_not_inherit_future_claims(self):
        run,local,u,a,c,p=fixture()
        req=evidence_request(run,local,u,c,c['facets'][0],a)
        self.assertNotIn('FUTURE_CLAIM',dumps(req));self.assertNotIn('report.pdf',dumps(req))
        self.assertEqual(req['state']['origin_activity'],'orient')
        self.assertEqual(req['state']['origin_actor'],'agent')
        wrong=deepcopy(u);wrong['trajectory_id']='another'
        with self.assertRaisesRegex(InputError,'same-actor'):evidence_request(run,local,wrong,c,c['facets'][0],a)
        bad=deepcopy(p);bad['units'][0]['candidates'][0]['facets'][0]['evidence']=[local['units'][-1]['source']]
        with self.assertRaises(InputError):validate_candidates(run,local,bad)

    def test_response_is_bound_and_uninspected_pixels_are_retained_as_missing_evidence(self):
        run,local,u,a,c,p=fixture();response=linked_feedback(run,local)[0]
        response['event']['text']='Displayed image data:image/png;base64,AAAAQUJDRA== end'
        req=evidence_request(run,local,u,c,c['facets'][1],a,response)
        self.assertNotIn('AAAAQUJDRA',dumps(req));self.assertNotIn('text',req['state']['subject'])
        self.assertTrue(req['state']['inspected_response']['unobserved_inline_media'])
        bad=deepcopy(response);bad['event']['source_call_id']='other'
        with self.assertRaisesRegex(InputError,'bind'):evidence_request(run,local,u,c,c['facets'][0],a,bad)
        response['event']['text']='A'*8000+'OMITTED_RESPONSE_MIDDLE'+'Z'*8000
        req=evidence_request(run,local,u,c,c['facets'][1],a,response)
        self.assertNotIn('OMITTED_RESPONSE_MIDDLE',dumps(req))
        self.assertTrue(req['state']['inspected_response']['omitted_text_ranges'])

    def test_argmax_replay_keeps_facets_inside_original_unit_with_separate_evidence(self):
        run,local,u,a,c,p=fixture();original=deepcopy(local)
        with tempfile.TemporaryDirectory() as directory:
            def transport(req):
                stage=req['state']['stage']
                choice='c0' if stage=='stated_check_contents' else ('attempts' if stage=='stated_check_dispatch' else 'no_answer')
                keys=list(req['questions']['choice']['criteria']);remainder=.3/(len(keys)-1)
                return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'unresolved','confidence':0,
                    'probabilities':{k:.7 if k==choice else remainder for k in keys}}}}
            engine=Pipeline(directory,FileCandidates(Path(directory)/'candidates'),transport)
            result=build(run,local,p,engine.decide)
            self.assertEqual(local,original);self.assertEqual(engine.calls,5)
            self.assertEqual(len(result['observations'][0]['actions']),1)
            self.assertEqual(len(result['observations'][0]['actions'][0]['facets']),2)
            self.assertEqual(len(result['uninspected_unit_ids']),1)
            self.assertEqual({r['to'] for r in result['relations']},{u['id']})
            self.assertTrue(audit(run,local,p,result,directory)['argmax_replayed'])
            build(run,local,p,engine.decide);self.assertEqual(engine.calls,5)
            focused=build(run,local,p,engine.decide,FOCUSED_VERSION)
            self.assertEqual(engine.calls,9)
            self.assertTrue(audit(run,local,p,focused,directory)['argmax_replayed'])
            changed=deepcopy(result);changed['relations'][0]['facet_id']='different'
            with self.assertRaisesRegex(InputError,'replay'):audit(run,local,p,changed,directory)

    def test_missing_source_pair_is_not_replaced_with_adjacency(self):
        run,local,u,a,c,p=fixture()
        for event in run['events']:
            if event['kind']=='action':event.pop('parent_id',None)
        p['source_hash']=digest(run)
        def decide(req):return {'choice':{'value':'c0'}},digest(req)
        result=build(run,local,p,decide)
        self.assertEqual(result['observations'][0]['actions'],[])
        self.assertEqual(result['relations'],[])


if __name__=='__main__':unittest.main()
