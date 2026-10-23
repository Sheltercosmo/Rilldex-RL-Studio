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


def split_fixture():
    run,doc=fixture()
    for uid in ('a0','f0'):
        unit=next(u for u in doc['units'] if u['id']==uid)
        original=deepcopy(unit);mid=unit['source']['text'].index(' ')+1
        unit['source']=evidence(run,unit['source']['event_id'],start=0,end=mid)
        unit['content']['summary']={'text':unit['source']['text'],'evidence':[unit['source']]}
        original['id']=uid+'-tail'
        original['source']=evidence(run,original['source']['event_id'],start=mid,end=original['source']['end'])
        original['content']['summary']={'text':original['source']['text'],'evidence':[original['source']]}
        doc['units'].append(original)
    doc['relations'].extend([
        {'from':'a0-tail','to':'p','type':'attempts_plan_step','plan_step_id':'draft'},
        {'from':'f0-tail','to':'a0-tail','type':'feedback_for'}])
    return run,doc


class PlanExecutionTests(unittest.TestCase):
    def test_split_annotations_keep_all_witnesses_but_count_source_calls_and_responses(self):
        run,doc=split_fixture();before=deepcopy(doc)
        doc['relations'].extend([deepcopy(doc['relations'][-2]),
            {'from':'a0-tail','to':'p','type':'checks_plan_step','plan_step_id':'draft'}])
        p=pe.build(run,doc)['plans'][0];stage=p['stages'][0]
        self.assertEqual(p['counts']['bound_actions'],3)
        self.assertEqual(stage['dispatch_count'],2);self.assertEqual(stage['action_annotation_count'],3)
        self.assertEqual(stage['role_counts'],{'prepares':0,'attempts':2,'checks':1})
        self.assertEqual(stage['material_counts'],{'uninspected':2})
        self.assertEqual(stage['response_evidence'][0]['action_unit_ids'],['a0','a0-tail'])
        self.assertEqual(stage['response_evidence'][0]['response_unit_ids'],['f0','f0-tail'])
        self.assertTrue({'a0','a0-tail','f0','f0-tail'}<=set(stage['focus_unit_ids']))
        self.assertEqual(doc['units'],before['units'])
        from tracker import graph_store,work_hierarchy
        graph=graph_store.build(run,{'document':doc,'observer':{'id':'test','label':'Test'}})
        path=next(p for p in work_hierarchy.build(graph)['stage_paths'] if p['stage_id']=='p:draft')
        self.assertEqual(path['counts']['actions'],stage['dispatch_count'])
        self.assertEqual(path['counts']['attempts'],stage['role_counts']['attempts'])
        self.assertEqual(path['counts']['checks'],stage['role_counts']['checks'])

    def test_compound_dispatch_can_serve_two_stages_without_becoming_two_calls(self):
        run,doc=split_fixture()
        doc['relations'].append({'from':'a0-tail','to':'p','type':'attempts_plan_step','plan_step_id':'convert'})
        p=pe.build(run,doc)['plans'][0]
        self.assertEqual(p['counts']['bound_actions'],3)
        self.assertEqual(p['counts']['multiple_stage_actions'],1)
        self.assertEqual([s['dispatch_count'] for s in p['stages']],[2,2])
        self.assertEqual(p['counts']['stage_changes'],1)

    def test_conflicting_product_readings_stay_visible_and_do_not_count_as_contents(self):
        from tracker.rollout_metrics import semantic_record
        run,doc=split_fixture();doc['plan_relation_review']=[]
        with tempfile.TemporaryDirectory() as folder:
            engine=Pipeline(folder,None,answer)
            material=pm.execute(run,doc,engine)[0];self.assertEqual(engine.calls,3)
            self.assertEqual(len(material['observations']),4)
            self.assertEqual(pm.execute(run,doc,engine)[0],material);self.assertEqual(engine.calls,3)
        # Authored disagreement, to test aggregation independently of a model.
        for row in material['observations']:
            row['form']='contents' if row['action_unit_id']=='a0' else 'absent'
        doc['plan_stage_material']=material;p=pe.build(run,doc)['plans'][0]
        response=p['stages'][0]['response_evidence'][0]
        self.assertEqual(response['material_form'],'conflicting_observations')
        self.assertEqual(len(response['material_indices']),2);self.assertIsNone(response['material_index'])
        self.assertEqual(p['stages'][0]['material_counts'],{'conflicting_observations':1,'absent':1})
        record=semantic_record(run,{'document':doc,'observer':{'id':'test','label':'test'}})
        self.assertEqual(record['plan_projection_schema'],pe.VERSION)
        self.assertEqual(record['metrics']['plan_stage_material_coverage']['denominator'],3)
        self.assertEqual(record['metrics']['plan_stage_material_coverage']['numerator'],3)
        self.assertEqual(record['metrics']['plan_stages_with_contents_fraction']['value'],0)

    def test_partial_inspection_coverage_uses_distinct_stage_dispatch_response_pairs(self):
        from tracker.rollout_metrics import semantic_record
        run,doc=split_fixture();doc['plan_relation_review']=[]
        with tempfile.TemporaryDirectory() as folder:
            material=pm.execute(run,doc,Pipeline(folder,None,answer))[0]
        material['observations']=[r for r in material['observations'] if r['action_unit_id']=='a0']
        doc['plan_stage_material']=material
        value=semantic_record(run,{'document':doc,'observer':{'id':'test','label':'test'}})['metrics']['plan_stage_material_coverage']
        self.assertEqual(value['value'],1/3);self.assertEqual(value['numerator'],1);self.assertEqual(value['denominator'],3)

    def test_recorded_context_and_source_anchors_checked_before_material_requests(self):
        for mutation in ('context','anchor','source_actor','copied'):
            with self.subTest(mutation=mutation):
                run,doc=fixture();action=run['events'][1]
                if mutation=='context':action['context_id']='different-session'
                elif mutation=='anchor':doc['units'][1]['source']['text']='not the captured text'
                elif mutation=='source_actor':action['actor']='another-agent'
                else:action['copied_context']=True
                doc['source_hash']=digest(run)
                with self.assertRaises(InputError):pe.build(run,doc)
                with tempfile.TemporaryDirectory() as folder:
                    engine=Pipeline(folder,None,answer)
                    with self.assertRaises(InputError):pm.execute(run,doc,engine)
                    self.assertEqual(engine.calls,0)

    def test_actions_from_other_contexts_are_not_unassigned_plan_work(self):
        run,doc=fixture(gap=True)
        next(e for e in run['events'] if e.get('call_id')=='gap')['context_id']='other'
        doc['source_hash']=digest(run);p=pe.build(run,doc)['plans'][0]
        self.assertEqual(p['counts']['unassigned_actions'],0)
        self.assertEqual(p['stage_transitions'][0]['gap_action_event_ids'],[])

    def test_unknown_order_and_native_sibling_dispatches_do_not_establish_transitions(self):
        for mode in ('unknown','siblings','gap'):
            with self.subTest(mode=mode):
                run,doc=fixture(gap=mode=='gap')
                if mode=='siblings':
                    for event in run['events']:
                        if event.get('call_id') in {'c0','c1'}:event['source_message_index']=7
                else:
                    next(e for e in run['events'] if e.get('call_id')==('gap' if mode=='gap' else 'c1'))['order_known']=False
                doc['source_hash']=digest(run);p=pe.build(run,doc)['plans'][0]
                self.assertEqual(p['counts']['stage_changes'],1 if mode=='gap' else 0)
                self.assertEqual(p['stage_transitions'][0]['order_status'],'not_established')

    def test_saved_metrics_refresh_offline_without_changing_annotation_population(self):
        from tracker import rollout_metrics as metrics,observer_archive,semantic_catalog,graph_store,monitoring
        from tracker.store import Store
        from tracker.adapters import normalize
        from test_tracker import harbor
        from unittest.mock import patch
        run,doc=split_fixture();base=normalize(harbor(),'harbor',{'experiment':'plan-control','training_step':0})[0]
        base['events']=run['events'];run=base;doc['source_hash']=digest(run);doc['plan_relation_review']=[]
        for e in run['events']:e.setdefault('copied_context',False)
        # Explicitly unknown source ordering was incorrectly counted by v1.
        run['events'][3]['order_known']=False;doc['source_hash']=digest(run)
        bundle={'available':True,'document':doc,'observer':{'id':'saved-plan','label':'Saved Plan'}}
        bundle['export_digest']=digest(semantic_catalog.export_payload(bundle))
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'review.sqlite');store.add([run]);observer_archive.save(store,run,'saved-plan',bundle)
            old=metrics.semantic_record(run,bundle);old.pop('plan_projection_schema')
            old['metrics']['plan_stage_change_count']=metrics.measurement(2)
            graph=graph_store.build(run,bundle);old['graph_id']=graph['id']
            with store.connect() as c:graph_store.save(c,graph);key=metrics.save(c,old)
            monitor=monitoring.create(store,{'name':'Stage changes','kind':'metric','observer':'saved-plan','metric':'plan_stage_change_count'})
            with patch('tracker.semantic_extraction.Pipeline.decide',side_effect=AssertionError('No provider decisions during refresh')):
                report=metrics.report(store);monitoring.sync(store,[monitor['id']])
                current=[r for r in report['rows'] if r['observer']=='saved-plan']
                self.assertEqual(len(current),1);self.assertEqual(current[0]['metrics']['plan_stage_change_count']['value'],0)
                series=metrics.training_series(report,'plan_stage_change_count',observer='saved-plan')
                self.assertEqual(len(series['cohorts'][0]['points']),1)
                self.assertEqual(monitoring.values(store,monitor['id'],[run['id']])[run['id']]['value'],0)
                self.assertEqual(metrics.ensure_current(store),0)
                metrics.record_map(store,run,bundle)
            with store.connect() as c:
                import json
                self.assertEqual(json.loads(c.execute('SELECT document FROM rollout_measurements WHERE id=?',(key,)).fetchone()[0]),old)
                self.assertEqual(c.execute("SELECT count(*) FROM rollout_measurements WHERE observer='saved-plan'").fetchone()[0],2)

    def test_refresh_does_not_substitute_a_newer_annotation_for_missing_saved_evidence(self):
        from tracker import rollout_metrics as metrics
        from tracker.store import Store
        from tracker.adapters import normalize
        from test_tracker import harbor
        run=normalize(harbor(),'harbor',{'experiment':'missing-map','training_step':0})[0]
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'review.sqlite');store.add([run])
            old=metrics.source_record(run)
            old.update(observer='missing-map',observation_kind='semantic',annotation_hash='original-evidence')
            old['metrics']['plan_stage_change_count']=metrics.measurement(4)
            with store.connect() as c:key=metrics.save(c,old)
            report=metrics.report(store);current=next(r for r in report['rows'] if r['observer']=='missing-map')
            self.assertIsNone(current['metrics']['plan_stage_change_count']['value'])
            self.assertIn('original saved Plan',current['metrics']['plan_stage_change_count']['reason'])
            self.assertEqual(current['metrics']['actions'],old['metrics']['actions'])
            self.assertEqual(current['annotation_hash'],'original-evidence')
            self.assertEqual(metrics.ensure_current(store),0)
            with store.connect() as c:self.assertIsNotNone(c.execute('SELECT id FROM rollout_measurements WHERE id=?',(key,)).fetchone())

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
