import copy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.jev import DEFAULT_MODEL
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,FileCandidates,generation_request,read,load_extraction
from tracker.feedback_assessments import build,candidates,assessment_request,execute,audit,INLINE_EVIDENCE,DIRECT_SET_RULE,SOURCE_LINKAGE,linked_feedback


def fixture(long=False):
    return normalize({'trajectory_format':'devai/1','trajectory':[
      {'step':0,'user_message':'Make a PDF report.','agent':{'thought':'Convert the report.','action':'convert report.md'},'environment':'Converter is missing.'},
      {'step':1,'user_message':None,'agent':{'thought':'The converter is missing. Install it.','action':'install converter'},'environment':('INSTALL LOG\n'+'x'*12000+'\nInstallation finished.') if long else 'Installation finished.'},
      {'step':2,'user_message':None,'agent':{'thought':'The converter is now installed.','action':None},'environment':None}]})[0]


class Provider(FileCandidates):
    def content(self,run,ref,activity):
        req=generation_request(run,ref,activity)
        return {'status':'ready','request_hash':digest(req),'producer':'test fixture',
                'candidates':[{'fields':{k:{'status':'expressed','text':ref['text'],'evidence':[ref]} for k in req['field_contract']}}]}


def transport(req):
    stage=req['state']['stage']
    if stage=='activity':value='construct' if req['state']['expression_form']=='recorded action dispatch' else 'orient'
    else:value={'partition':'p0','content':'c0','feedback_assessment':'f0'}[stage]
    return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','probabilities':{k:int(k==value) for k in req['questions']['choice']['criteria']}}}}


class AssessmentTests(unittest.TestCase):
    def test_native_adapter_binding_reaches_candidates_and_complete_map(self):
        from tracker import semantic_history
        from tracker.semantic_extraction import write
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'base';out=Path(d)/'native'
            run=normalize(read(Path(__file__).parent/'fixtures/harbor/hello-world-context-summarization-linear-history.trajectory.json'))[0]
            def native_transport(req):
                if req['state']['stage'].startswith('action_target'):
                    value=next(iter(req['questions']['choice']['criteria']))
                    return {'model':req['model'],'answers':{'choice':{'type':'choice','probabilities':{k:int(k==value) for k in req['questions']['choice']['criteria']}}}}
                return transport(req)
            ex=Pipeline(base,Provider(base/'c'),native_transport).run(run)
            write(base/'runs'/f'{run["id"]}.json',run)
            self.assertEqual(linked_feedback(run,ex),[])
            bound=linked_feedback(run,ex,SOURCE_LINKAGE)
            self.assertEqual([r['event']['id'] for r in bound],['e4','e7','e10'])
            semantic_history.initialize(out,base,run['id'],reference_rule=DIRECT_SET_RULE,linkage_version=SOURCE_LINKAGE)
            self.assertEqual(semantic_history.execute(out,native_transport,max_calls=30)['status'],'complete')
            view=load_extraction(run,out)
            self.assertEqual(view['validation']['source_feedback_links'],3)
            self.assertEqual(view['document']['provenance']['source_feedback_linkage'],SOURCE_LINKAGE)
            ids={u['id'] for u in view['document']['units']}
            relations=[r for r in view['document']['relations'] if r['type']=='assesses']
            self.assertTrue(relations)
            self.assertTrue(all(r['to'] in ids for r in relations))
            self.assertTrue(all(r['basis']=='single action in same step' for r in view['document']['relations'] if r['type']=='feedback_for'))
            self.assertEqual(load_extraction(run,base)['validation']['source_feedback_links'],0)

    def test_adapter_links_never_guess_ambiguous_copied_private_cross_agent_or_future_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();ex=Pipeline(d,Provider(Path(d)/'c'),transport).run(run)
            for change in ['ambiguous','copied','private','cross_agent','future']:
                altered=copy.deepcopy(run)
                reply=next(e for e in altered['events'] if e['kind']=='feedback')
                action=next(e for e in altered['events'] if e['kind']=='action')
                reply.pop('source_call_id',None);reply['related_action_ids']=[action['id']]
                if change=='ambiguous':reply['related_action_ids'] += [e['id'] for e in altered['events'] if e['kind']=='action' and e['id']!=action['id']]
                elif change=='copied':reply['copied_context']=True
                elif change=='private':reply['agent_visibility']='not_established'
                elif change=='cross_agent':reply['trajectory_id']='another-agent'
                else:reply['index']=action['index']-1
                self.assertNotIn(reply['id'],[c['event']['id'] for c in linked_feedback(altered,ex,SOURCE_LINKAGE)],change)

    def test_direct_sets_selects_joint_or_single_without_irreversible_first_stage(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            seen=[]
            def choose(req):
                seen.append(req)
                sets=req['state']['response_sets']
                return ('j0_1' if 'j0_1' in sets else 'f0'),digest(req)
            result=build(run,extraction,choose,evidence_layout=INLINE_EVIDENCE,reference_rule=DIRECT_SET_RULE)
            self.assertEqual(len(seen),2)
            self.assertTrue(all(r['state']['stage']=='feedback_assessment' for r in seen))
            self.assertEqual(set(seen[-1]['state']['response_sets']),{'f0','f1','j0_1'})
            self.assertNotIn('multiple_responses',seen[-1]['questions']['choice']['criteria'])
            self.assertEqual(len(result['relations']),3)
            self.assertTrue(result['relations'][-1]['assessment_group']['joint'])
            self.assertTrue(all('set_request' not in r for r in result['relations']))
            single=build(run,extraction,lambda req:('f1' if 'f1' in req['state']['response_sets'] else 'f0',digest(req)),reference_rule=DIRECT_SET_RULE)
            self.assertEqual(len(single['relations']),2)
            self.assertTrue(all(not r['assessment_group']['joint'] for r in single['relations']))

    def test_direct_sets_keep_unknown_missing_and_wrong_claim_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            for value in ['unresolved','none_of_these']:
                result=build(run,extraction,lambda req:(value,digest(req)),reference_rule=DIRECT_SET_RULE)
                self.assertEqual(result['relations'],[])
                self.assertEqual(result['observations'][-1]['status'],value)
            result,validation=execute(run,extraction,engine,reference_rule=DIRECT_SET_RULE)
            self.assertEqual(validation['claim_validity'],'not_judged')
            self.assertTrue(audit(run,extraction,result,d)['argmax_replayed'])
            self.assertNotIn('feedback_assessments',load_extraction(run,d)['validation'])
            with self.assertRaisesRegex(InputError,'Unknown direct'):
                build(run,extraction,lambda req:('multiple_responses',digest(req)),reference_rule=DIRECT_SET_RULE)

    def test_inline_response_options_are_visible_source_and_separately_replayable(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture(long=True);engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            result,validation=execute(run,extraction,engine,evidence_layout=INLINE_EVIDENCE,reference_rule=None)
            self.assertTrue(validation['argmax_replayed'])
            row=result['observations'][-1]
            req=read(Path(d)/'decisions'/f"{row['request']}.json")['request']
            option=req['questions']['choice']['criteria']['f0']
            self.assertIn('Installation finished.',option)
            self.assertLess(len(option),1500)
            self.assertIn('Additional visible response text',option)
            self.assertIn('Converter is missing.',req['questions']['choice']['criteria']['f1'])
            # The development layout must not replace the default map implicitly.
            view=load_extraction(run,d)
            self.assertNotIn('feedback_assessments',view['validation'])
            bad=copy.deepcopy(result);bad.pop('evidence_layout')
            with self.assertRaises((InputError,FileNotFoundError)):audit(run,extraction,bad,d)

    def test_unrelated_extraction_and_omission_counts_do_not_change_local_decision(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            last=extraction['units'][-1];pool,omitted=candidates(run,extraction,last)
            before=assessment_request(run,extraction,last,pool,omitted)
            different=copy.deepcopy(extraction);different['review_note']='Unrelated bookkeeping'
            self.assertEqual(before,assessment_request(run,different,last,pool,omitted+100))
            self.assertNotIn('extraction_hash',before['state'])
            changed=copy.deepcopy(last);changed['content']['situation']['text']='The installation failed.'
            self.assertNotEqual(before,assessment_request(run,extraction,changed,pool,omitted))
            legacy=build(run,extraction,engine.choose,dependency_scope=None)
            self.assertTrue(audit(run,extraction,legacy,d)['argmax_replayed'])

    def test_field_selection_precedes_relation_and_claim_truth_is_not_inferred(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            result,validation=execute(run,extraction,engine)
            self.assertEqual(len(result['relations']),2)
            self.assertEqual(result['observations'][0]['status'],'no_prior_selected_feedback')
            self.assertEqual(validation['claim_validity'],'not_judged')
            view=load_extraction(run,d)
            self.assertEqual(view['validation']['feedback_assessments']['selected_relations'],2)
            self.assertEqual(view['validation']['source_feedback_links'],2)
            for edge in result['relations']:
                self.assertEqual(edge['from_field'],'situation')
                self.assertIn(edge['to'],{u['id'] for u in view['document']['units']})
                saved=read(Path(d)/'decisions'/f"{edge['request']}.json")
                index=next(e['index'] for e in run['events'] if e['id']==edge['cutoff']['event_id'])
                ids={e['id'] for e in saved['request']['state']['prefix']}
                self.assertFalse(any(e['id'] in ids for e in run['events'] if e['index']>index))
            before=engine.calls;execute(run,extraction,engine);self.assertEqual(engine.calls,before)
            bad=copy.deepcopy(result);bad['relations'][0]['claim_validity']='verified'
            with self.assertRaisesRegex(InputError,'differ'):audit(run,extraction,bad,d)

    def test_omitted_log_ranges_remain_visible_and_citations_are_original_spans(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture(long=True);engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            result,_=execute(run,extraction,engine);edge=result['relations'][-1]
            self.assertTrue(edge['omitted_feedback_ranges'])
            self.assertLess(sum(len(r['text']) for r in edge['context_evidence']),5000)
            self.assertIn('Installation finished.',edge['context_evidence'][-1]['text'])

    def test_multiple_unresolved_private_and_other_actor_do_not_become_asserted_links(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            for value in ['multiple_responses','unresolved','none_of_these']:
                self.assertEqual(build(run,extraction,lambda req:('unresolved' if req['state']['stage']=='feedback_assessment_set' else value,digest(req)))['relations'],[])
            last=extraction['units'][-1]
            private=copy.deepcopy(run)
            for e in private['events']:
                if e['kind']=='feedback':e['agent_visibility']='not_established'
            self.assertEqual(candidates(private,extraction,last)[0],[])
            others=copy.deepcopy(extraction)
            for u in others['units']:
                if u['kind']=='action':u['actor']='another_agent'
            self.assertEqual(candidates(run,others,last)[0],[])
            incomplete=copy.deepcopy(extraction);incomplete['status']='needs_work'
            with self.assertRaisesRegex(InputError,'Complete local'):build(run,incomplete,engine.choose)

    def test_joint_assessment_is_one_group_with_several_evidence_edges(self):
        with tempfile.TemporaryDirectory() as d:
            run=fixture();engine=Pipeline(d,Provider(Path(d)/'c'),transport);extraction=engine.run(run)
            seen=[]
            def choose(req):
                seen.append(req)
                return ('s0' if req['state']['stage']=='feedback_assessment_set' else 'multiple_responses'),digest(req)
            result=build(run,extraction,choose)
            # First situation has no candidates; next has only one and requests
            # more candidates; the final one can identify a two-response set.
            self.assertEqual(result['observations'][1]['status'],'needs_more_feedback_candidates')
            self.assertEqual(len(result['relations']),2)
            a,b=result['relations'];self.assertEqual(a['assessment_group'],b['assessment_group'])
            self.assertTrue(a['assessment_group']['joint']);self.assertNotEqual(a['to'],b['to'])
            self.assertEqual(a['assessment_group']['response_units'],[a['to'],b['to']])
            self.assertIn('first_selection_request',seen[-1]['state'])


if __name__=='__main__':unittest.main()
