import copy
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.schema import digest,InputError
from tracker.semantic_map import evidence
from tracker import feedback_assessments as fa, feedback_opportunities as fo, graph_store, analysis_metrics, investigation_plans
from tracker.feedback_retrieval import HYBRID_VERSION


def control(texts=('The status is ready.','Proceed with the task.','Here is the result.'),choice='none_of_these'):
    """Authored mechanics control; choices are not model-accuracy evidence."""
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Complete the work.','agent':{'thought':None,'action':'Inspect status'},'environment':'Status: ready.'},
        *[{'step':i+1,'user_message':None,'agent':{'thought':text,'action':None},'environment':None} for i,text in enumerate(texts)]]})[0]
    units=[]
    for e in run['events']:
        if e['kind'] not in {'action','reasoning'}:continue
        ref=evidence(run,e['id']);field={'status':'expressed','text':ref['text'],'evidence':[ref]}
        units.append({'id':'unit-'+e['id'],'source':ref,'actor':e['actor'],'trajectory_id':e['trajectory_id'],
            'kind':'action' if e['kind']=='action' else 'semantic','status':'selected',
            'activity':'inspect' if e['kind']=='action' else 'report','content':{'summary':field}})
    extraction={'run_id':run['id'],'units':units,'status':'complete_local_extraction','whole_run':True}
    result=fa.build(run,extraction,lambda req:(choice,digest(req)),scope_version=fa.CONTRIBUTION_SCOPE,
        evidence_layout=fa.INLINE_EVIDENCE,reference_rule=fa.DIRECT_SET_RULE,linkage_version=fa.SOURCE_LINKAGE,retrieval_version=HYBRID_VERSION)
    return run,extraction,result


def graph(run,extraction,result):
    units=copy.deepcopy(extraction['units']);relations=copy.deepcopy(result['relations'])
    for c in fa.linked_feedback(run,extraction,fa.SOURCE_LINKAGE):
        e=c['event'];units.append({'id':c['unit_id'],'kind':'feedback','actor':e['actor'],
            'trajectory_id':e['trajectory_id'],'source':evidence(run,e['id']),'content':{}})
        relations.append({'from':c['unit_id'],'to':c['action']['id'],'type':'feedback_for','basis':'source_binding'})
    doc={'source_hash':digest(run),'units':units,'relations':relations,'assessment_review':result['observations'],
         'provenance':{'assessment_scope':result.get('scope_version')}}
    return graph_store.build(run,{'document':doc,'observer':{'id':'authored-control','label':'Authored contract control'}})


class ContributionScopeTests(unittest.TestCase):
    def test_all_primary_activities_can_reference_feedback_without_reclassification(self):
        run,ex,_=control(('The status is ready.',))
        for activity in ['orient','knowledge','plan','hypothesize','reason','decide','inspect','construct','verify','coordinate','report','decline','social','other']:
            with self.subTest(activity=activity):
                ex['units'][-1]['activity']=activity;before=copy.deepcopy(ex);seen=[]
                result=fa.build(run,ex,lambda req:(seen.append(req) or 'f0',digest(req)),scope_version=fa.CONTRIBUTION_SCOPE,
                    reference_rule=fa.DIRECT_SET_RULE,linkage_version=fa.SOURCE_LINKAGE,evidence_layout=fa.INLINE_EVIDENCE,retrieval_version=HYBRID_VERSION)
                self.assertEqual(ex,before);self.assertEqual(len(seen),1)
                packet=seen[0];self.assertEqual(packet['state']['selected_activity'],activity)
                self.assertEqual(packet['state']['selected_field'],'contribution')
                self.assertNotIn('selected_situation',packet['state'])
                self.assertEqual(result['relations'][0]['assessment_text'],ex['units'][-1]['source']['text'])
                self.assertEqual(result['relations'][0]['from_field'],'contribution')
                self.assertEqual(set(packet['questions']['choice']['criteria']),{'f0','none_of_these','unresolved'})

    def test_scope_excludes_dispatch_user_copied_hidden_and_unselected_units(self):
        run,ex,_=control(('The status is ready.',));unit=ex['units'][-1];e=run['events'][-1]
        self.assertIsNone(fa.subject(run,ex['units'][0],fa.CONTRIBUTION_SCOPE))
        for field,value in [('actor','user'),('copied_context',True),('agent_visibility','not_established')]:
            changed=copy.deepcopy(run);changed['events'][-1][field]=value
            self.assertIsNone(fa.subject(changed,unit,fa.CONTRIBUTION_SCOPE))
        changed=copy.deepcopy(unit);changed['status']='unresolved'
        self.assertIsNone(fa.subject(run,changed,fa.CONTRIBUTION_SCOPE))
        self.assertIsNone(fa.subject(run,unit)) # Report is outside legacy scope.
        with self.assertRaises(InputError):fa.build(run,ex,lambda _:self.fail(),scope_version=fa.CONTRIBUTION_SCOPE)

    def test_preflight_has_no_selections_or_mutations_and_excludes_encoded_media(self):
        run,ex,_=control();before=copy.deepcopy(ex)
        plan=fa.preflight(run,ex,scope_version=fa.CONTRIBUTION_SCOPE,reference_rule=fa.DIRECT_SET_RULE,
            linkage_version=fa.SOURCE_LINKAGE,evidence_layout=fa.INLINE_EVIDENCE,retrieval_version=HYBRID_VERSION)
        self.assertEqual(plan['request_count'],3);self.assertEqual(plan['provider_calls'],0)
        self.assertIsNone(plan['selected_relations']);self.assertEqual(ex,before)
        self.assertEqual(plan['total_request_bytes'],sum(r['request_bytes'] for r in plan['requests']))
        run,ex,_=control(('Look at data:image/png;base64,AAABBBCCC==',))
        self.assertIsNone(fa.subject(run,ex['units'][-1],fa.CONTRIBUTION_SCOPE))

    def test_opt_in_history_audits_raw_argmax_and_preserves_legacy_artifacts(self):
        from tests.test_feedback_assessments import fixture,Provider,transport
        from tracker.semantic_extraction import Pipeline,write,load_extraction,read
        from tracker import semantic_history
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base';out=Path(tmp)/'new';run=fixture()
            Pipeline(base,Provider(base/'c'),transport).run(run);write(base/'runs'/f'{run["id"]}.json',run)
            before=digest(read(base/'results'/f'{run["id"]}.json'))
            def choose(req):
                if req['state']['stage'].startswith('action_target'):value=next(iter(req['questions']['choice']['criteria']))
                else:return transport(req)
                return {'model':req['model'],'answers':{'choice':{'type':'choice','probabilities':{k:int(k==value) for k in req['questions']['choice']['criteria']}}}}
            semantic_history.initialize(out,base,run['id'],scope_version=fa.CONTRIBUTION_SCOPE,reference_rule=fa.DIRECT_SET_RULE,
                linkage_version=fa.SOURCE_LINKAGE,retrieval_version=HYBRID_VERSION)
            self.assertEqual(semantic_history.execute(out,choose,max_calls=10)['status'],'complete')
            audit=semantic_history.audit(out);self.assertEqual(audit['assessments']['eligible_contributions'],3)
            self.assertTrue(audit['assessments']['argmax_replayed'])
            view=load_extraction(run,out);g=graph_store.build(run,{**view,'observer':{'id':'new','label':'New'}})
            self.assertEqual(g['semantic_context']['feedback_observations']['scope_version'],fa.CONTRIBUTION_SCOPE)
            self.assertEqual(fo.project(g)['metrics']['numerator'],2)
            self.assertEqual(digest(read(base/'results'/f'{run["id"]}.json')),before)
            self.assertEqual(semantic_history.execute(out,lambda _:self.fail('Exact replay makes no calls'))['budget_used']['jev_requests'],0)


class FeedbackOpportunityTests(unittest.TestCase):
    def test_complete_negative_and_short_window_unknown_not_zero(self):
        run,ex,result=control();out=fo.project(graph(run,ex,result))
        self.assertEqual(out['metrics'],{'value':0,'numerator':0,'denominator':1,'opportunities':1,'unknown':0})
        run,ex,result=control(('No reference.',));out=fo.project(graph(run,ex,result))
        self.assertIsNone(out['metrics']['value']);self.assertIn('window_not_fully_observed',out['observations'][0]['unknown_reasons'])

    def test_positive_witness_does_not_require_complete_future_window(self):
        run,ex,result=control(('The status is ready.',),choice='f0');out=fo.project(graph(run,ex,result))
        self.assertEqual(out['metrics']['value'],1);self.assertEqual(out['observations'][0]['unknown_reasons'],[])
        self.assertEqual(len(out['observations'][0]['edge_ids']),1)

    def test_missing_reviews_candidates_text_and_segmentation_remain_unknown(self):
        run,ex,result=control()
        for mode in ['review','candidate','response_text','contribution_text','selection','split','unresolved','duplicate']:
            with self.subTest(mode=mode):
                x,r=copy.deepcopy(ex),copy.deepcopy(result)
                if mode=='review':r['observations'].pop()
                elif mode=='candidate':r['observations'][0]['offered_feedback_units']=[]
                elif mode=='response_text':r['observations'][0]['incomplete_feedback_units']=r['observations'][0]['offered_feedback_units']
                elif mode=='contribution_text':r['observations'][0]['contribution_context_complete']=False
                elif mode=='selection':x['units'][-1]['status']='unresolved'
                elif mode=='split':x['units'][-1]['source']['end']-=5;x['units'][-1]['source']['text']=x['units'][-1]['source']['text'][:-5]
                elif mode=='unresolved':r['observations'][0]['status']='unresolved'
                else:r['observations'].append(copy.deepcopy(r['observations'][0]))
                out=fo.project(graph(run,x,r));self.assertEqual(out['metrics']['unknown'],1);self.assertIsNone(out['metrics']['value'])

    def test_source_denominator_survives_missing_action_and_feedback_units(self):
        run,ex,result=control();out=fo.project(graph_store.build(run))
        self.assertEqual(out['metrics']['opportunities'],1);self.assertEqual(out['metrics']['unknown'],1)
        ex['units']=ex['units'][1:];out=fo.project(graph(run,ex,result))
        self.assertEqual(out['metrics']['opportunities'],1);self.assertEqual(out['metrics']['unknown'],1)

    def test_reference_beyond_window_or_in_another_lane_is_not_counted(self):
        run,ex,result=control(('First.','Second.','Third.','The status is ready.'),choice='f0')
        result['relations']=result['relations'][-1:]
        for row in result['observations'][:-1]:row['status']='none_of_these';row.pop('target_feedback_units',None)
        out=fo.project(graph(run,ex,result));self.assertEqual(out['metrics']['value'],0)
        run,ex,result=control(('The status is ready.',),choice='f0')
        run['events'][-1]['trajectory_id']='another';ex['units'][-1]['trajectory_id']='another'
        out=fo.project(graph(run,ex,result));self.assertIsNone(out['metrics']['value'])

    def test_future_or_altered_edge_evidence_is_not_a_positive(self):
        for mode in ['future','altered']:
            run,ex,result=control(choice='f0');result['relations']=result['relations'][:1]
            edge=result['relations'][0]
            edge['evidence']=[evidence(run,run['events'][-1]['id'])] if mode=='future' else [{**edge['evidence'][0],'text':'changed'}]
            out=fo.project(graph(run,ex,result));self.assertIsNone(out['metrics']['value'])
            self.assertEqual(out['metrics']['numerator'],0)

    def test_no_tool_response_is_not_applicable_in_reasoning(self):
        run=normalize({'trajectory_format':'generation/1','prompt':'What is 1+1?','completion':'1+1=2.'})[0]
        out=fo.project(graph_store.build(run));self.assertEqual(out['metrics']['opportunities'],0)
        self.assertIsNone(out['metrics']['value']);self.assertEqual(out['applicability'],'no_visible_bound_tool_responses')

    def test_typed_projection_cache_and_monitor_receipt_reconcile(self):
        from tracker.store import Store
        from tracker import monitoring
        run,ex,result=control(choice='f0');g=graph(run,ex,result)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            selector=analysis_metrics.validate({'measure':'feedback_reference'})
            monitor={'observer':g['observer'],'analysis':selector,'analysis_definition':analysis_metrics.definition(selector)}
            output=analysis_metrics.evaluate(store,monitor,g)
            self.assertEqual(output['value'],1)
            plan=investigation_plans.read_plan(store,output['analysis']['plan_id'])
            again=investigation_plans.execute(store,plan['definition']);self.assertEqual(again['execution']['cache_hits'],1)
            value={**output,'run_id':run['id'],'source_hash':digest(run),'input_id':g['id']}
            _,_,receipt=analysis_metrics.receipt(store,value,monitor)
            self.assertEqual(len(receipt['analysis_cases']),1)
            self.assertEqual(receipt['unknown'],0)


if __name__=='__main__':unittest.main()
