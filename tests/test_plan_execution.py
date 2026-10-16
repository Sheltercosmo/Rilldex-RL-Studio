from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import plan_execution as pe,plan_stage_material as pm
from tracker.schema import InputError,digest,event,dumps
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline


def fixture(gap=False):
    events=[];event(events,kind='reasoning',text='First write a report. Then convert it to PDF.',pointer='/plan',trajectory_id='main')
    units=[];relations=[];dispatches=[]
    for i,sid in enumerate(['draft','convert','draft']):
        if gap and i==1:event(events,kind='action',text='Unassigned work',pointer='/gap',trajectory_id='main',call_id='gap')
        a=event(events,kind='action',text='Write report' if sid=='draft' else 'Convert report',pointer=f'/a{i}',trajectory_id='main',call_id=f'c{i}')
        f=event(events,kind='feedback',text='Contents: # Report\nDescription' if sid=='draft' else 'Error: required PDF engine missing',pointer=f'/f{i}',trajectory_id='main',source_call_id=f'c{i}',actor='environment')
        dispatches.append((a,f,sid))
    event(events,kind='message',text='FUTURE_CLAIM: everything is complete',pointer='/future',trajectory_id='main')
    run={'id':'control','events':events,'metadata':{},'adapter_version':'authored'}
    ref=evidence(run,'e1')
    plan={'id':'p','kind':'semantic','activity':'plan','actor':'agent','trajectory_id':'main','source':ref,
          'content':{'summary':{'text':'Write then convert report','evidence':[ref]}},
          'plan_structure':{'schema':'local-plan-content/1','organization':'staged',
              'steps':[{'id':'draft','text':'Write report content in Markdown','target':'Markdown report','evidence':[ref]},
                       {'id':'convert','text':'Convert report to PDF','target':'PDF report','evidence':[ref]}],
              'links':[{'from':'draft','to':'convert','kind':'precedes','evidence':[ref]}],
              'completion_criterion':{'status':'not_expressed'}}}
    units.append(plan)
    for i,(a,f,sid) in enumerate(dispatches):
        for e,uid,kind in [(a,f'a{i}','action'),(f,f'f{i}','feedback')]:
            units.append({'id':uid,'kind':kind,'activity':'construct' if kind=='action' else None,'actor':e['actor'],
                'trajectory_id':'main','source':evidence(run,e['id']),
                'content':{'summary':{'text':e['text'],'evidence':[evidence(run,e['id'])]}}})
        relations.extend([{'from':f'a{i}','to':'p','type':'attempts_plan_step','plan_step_id':sid},
                          {'from':f'f{i}','to':f'a{i}','type':'feedback_for'}])
    return run,{'source_hash':digest(run),'units':units,'relations':relations,'provenance':{}}


def answer(req):
    return {'model':req['model'],'answers':{'choice':{'type':'choice','confidence':0,'choice':'absent',
        'probabilities':{k:1.0 if k=='contents' else 0.0 for k in req['questions']['choice']['criteria']}}}}


class PlanExecutionTests(unittest.TestCase):
    def test_stage_transition_uses_only_earlier_result_and_preserves_result_history(self):
        run,doc=fixture();old=pe.build(run,doc)
        self.assertNotIn('prior_stage_result_at_entry',old['plans'][0]['stage_transitions'][0])
        doc['work_results']={'observations':[
            {'scope_kind':'plan_stage','scope_unit_id':'p','plan_step_id':'draft','response_event_id':'e3','result':'fulfilled'},
            {'scope_kind':'plan_stage','scope_unit_id':'p','plan_step_id':'convert','response_event_id':'e5','result':'failed'},
            {'scope_kind':'plan_stage','scope_unit_id':'p','plan_step_id':'draft','response_event_id':'e7','result':'not_established'}]}
        p=pe.build(run,doc)['plans'][0]
        self.assertEqual(p['stage_transitions'][0]['prior_stage_result_at_entry']['result'],'fulfilled')
        self.assertEqual(p['stage_transitions'][1]['prior_stage_result_at_entry']['result'],'failed')
        self.assertEqual([r['result'] for r in p['stages'][0]['work_result_history']],['fulfilled','not_established'])
        self.assertTrue(all(s['completion']=='not_established' for s in p['stages']))
        del doc['work_results'];self.assertEqual(pe.build(run,doc),old)

    def test_stages_and_reentries_reuse_original_units_and_preserve_gaps(self):
        run,doc=fixture(gap=True);before=deepcopy(doc);result=pe.build(run,doc);p=result['plans'][0]
        self.assertEqual(doc,before);self.assertEqual(p['counts']['bound_actions'],3)
        self.assertEqual(p['counts']['unassigned_actions'],1);self.assertEqual(p['counts']['stage_changes'],2)
        self.assertEqual(p['counts']['stage_reentries'],1)
        self.assertEqual(len(p['stage_transitions'][0]['gap_action_event_ids']),1)
        self.assertEqual(p['stages'][0]['action_unit_ids'],['a0','a2'])
        self.assertEqual(p['stages'][0]['completion'],'not_established')
        self.assertEqual(p['stages'][0]['material_counts'],{'uninspected':2})
        self.assertEqual(len({s['id'] for s in p['stages']}),2)

    def test_material_replay_excludes_future_claims_and_transition_future_feedback(self):
        run,doc=fixture()
        with tempfile.TemporaryDirectory() as folder:
            engine=Pipeline(folder,None,answer);material,validation=pm.execute(run,doc,engine)
            self.assertTrue(validation['argmax_replayed']);self.assertEqual(engine.calls,3)
            for pair in pm.pairs(run,doc):self.assertNotIn('FUTURE_CLAIM',dumps(pm.request(run,doc,pair)))
            doc['plan_stage_material']=material;p=pe.build(run,doc)['plans'][0]
            self.assertEqual(p['stage_transitions'][0]['prior_stage_material_before_entry'],[0])
            self.assertNotIn(2,p['stage_transitions'][0]['prior_stage_material_before_entry'])
            self.assertEqual(p['stages'][0]['material_counts'],{'contents':2})
            self.assertTrue(all(s['completion']=='not_established' for s in p['stages']))
            altered=deepcopy(material);altered['observations'][0]['form']='absent'
            with self.assertRaisesRegex(InputError,'replay'):pm.audit(run,doc,altered,folder)
            doc['plan_stage_material']['dependencies_hash']='forged'
            with self.assertRaisesRegex(InputError,'dependencies'):pe.build(run,doc)

    def test_unestablished_execution_order_is_not_a_stage_change_measure(self):
        run,doc=fixture()
        for u in doc['units']:
            if u['id'] in {'a0','a1'}:
                e=next(e for e in run['events'] if e['id']==u['source']['event_id']);e['batch_size']=2
        doc['source_hash']=digest(run);p=pe.build(run,doc)['plans'][0]
        self.assertEqual(p['counts']['stage_changes'],0)
        self.assertTrue(all(t['order_status']=='not_established' for t in p['stage_transitions']))

    def test_invalid_future_or_cross_participant_plan_binding_is_rejected(self):
        run,doc=fixture();doc['units'][1]['actor']='other'
        with self.assertRaisesRegex(InputError,'participant'):pe.build(run,doc)
        run,doc=fixture();doc['units'][0]['source']=doc['units'][-1]['source']
        with self.assertRaisesRegex(InputError,'cutoff'):pe.build(run,doc)

    def test_preparation_does_not_enter_stage_product_judgments(self):
        run,doc=fixture();doc['relations'][0]['type']='prepares_plan_step'
        self.assertEqual(len(pm.pairs(run,doc)),2)
        p=pe.build(run,doc)['plans'][0]
        self.assertEqual(p['stages'][0]['role_counts'],{'prepares':1,'attempts':1,'checks':0})
        self.assertEqual(p['stages'][0]['material_counts'],{'uninspected':1})

    def test_rollout_metrics_count_stage_observations_without_counting_completion(self):
        from tracker.rollout_metrics import semantic_record
        run,doc=fixture();doc['plan_relation_review']=[]
        def response(req):
            value=answer(req)
            if req['state']['selected_stage']['id']=='convert':
                value['answers']['choice']['probabilities']={k:1.0 if k=='absent' else 0.0 for k in req['questions']['choice']['criteria']}
            return value
        with tempfile.TemporaryDirectory() as folder:
            doc['plan_stage_material']=pm.execute(run,doc,Pipeline(folder,None,response))[0]
        m=semantic_record(run,{'document':doc,'observer':{'id':'test','label':'test'}})['metrics']
        self.assertEqual(m['plan_stage_change_count']['value'],2)
        self.assertEqual(m['plan_stage_reentry_count']['value'],1)
        self.assertEqual(m['plan_stage_material_coverage']['value'],1)
        self.assertEqual(m['plan_stages_with_contents_fraction']['value'],.5)
        self.assertIsNone(m['plan_completion_rate']['value']);self.assertIsNone(m['recovery_rate']['value'])


if __name__=='__main__':unittest.main()
