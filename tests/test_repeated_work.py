"""Source comparison controls, persistence and navigation receipts; no model calls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import repeated_work as rw, graph_store, monitoring, monitor_evidence, analysis_metrics, investigation_plans
from tracker.schema import digest
from tracker.store import Store
from test_work_episodes import example, edge


def fixture(names=('run tests', 'install dependency', 'run tests')):
    run, graph, actions = example(names)
    edge(graph, actions[-1], actions[0], 'same_action_target')
    return run, graph, actions


def event(graph, action):
    return next(n for n in graph['nodes'] if n['id'] == 'event:'+action['source']['event_id'])['properties']


def output_events(graph):
    return [n for n in graph['nodes'] if n['kind']=='event' and n['properties']['kind']=='feedback']


def freeze(graph):
    value = {k:v for k,v in graph.items() if k!='id'}
    for key in ('nodes','edges'):value[key]=sorted(value[key],key=lambda row:row['id'])
    return dict(id='graph-'+digest(value), **value)


class RepeatedWorkTests(unittest.TestCase):
    def test_same_call_and_feedback_keep_prerequisite_and_identity_evidence(self):
        _, graph, actions = fixture(); before=deepcopy(graph)
        result=rw.project(graph); row=result['rows'][0]
        self.assertEqual(row['inputs_changed'],False)
        self.assertEqual(row['inputs_and_feedback_match'],True)
        self.assertEqual(row['episode']['intervening'][0]['unit_id'],actions[1]['id'])
        self.assertEqual(result['coverage']['pairs'],1)
        self.assertEqual(rw.measure(result,'inputs_and_feedback_match')['value'],1)
        self.assertEqual(graph,before)
        self.assertNotIn('recovered',row);self.assertNotIn('failed_loop',row)

    def test_full_native_arguments_take_priority_over_equal_display_text(self):
        _, graph, actions = fixture()
        for action, args in [(actions[0],{'cmd':'run', 'limit':True}), (actions[-1],{'cmd':'run','limit':1})]:
            event(graph,action).update(tool='shell',arguments=args,raw_arguments=args,argument_status='json_object')
        row=rw.project(graph)['rows'][0]
        self.assertTrue(row['inputs_changed']);self.assertFalse(row['inputs_and_feedback_match'])
        self.assertEqual(row['dispatch']['basis'],'recorded_fields')
        self.assertEqual(row['dispatch']['changes'][0]['path'],'/arguments/limit')

    def test_text_export_uses_full_text_beyond_preview(self):
        _, graph, actions=fixture(('x'*900+'old','install dependency','x'*900+'new'))
        for action in (actions[0], actions[-1]):event(graph,action).update(arguments_available=False)
        row=rw.project(graph)['rows'][0]
        self.assertTrue(row['inputs_changed']);self.assertEqual(row['dispatch']['basis'],'recorded_text')
        self.assertEqual(row['dispatch']['changes'][0]['text_span']['before_start'],900)

    def test_source_feedback_can_differ_outside_annotation_or_preview(self):
        _,graph,_=fixture();feedback=output_events(graph)
        for i,n in enumerate((feedback[0],feedback[-1])):n['properties']['text']='same visible prefix\n'*100+str(i)
        result=rw.project(graph)
        self.assertFalse(result['rows'][0]['inputs_and_feedback_match'])
        self.assertEqual(result['rows'][0]['feedback']['status'],'changed')

    def test_missing_empty_metadata_shared_and_late_feedback_are_unknown(self):
        for mode in ('missing','empty','metadata','shared','late','context','hidden'):
            with self.subTest(mode=mode):
                _,graph,actions=fixture();f=output_events(graph)
                if mode=='missing':graph['edges']=[e for e in graph['edges'] if e['source']!=f[-1]['id']]
                if mode=='empty':f[-1]['properties']['text']=''
                if mode=='metadata':f[-1]['properties']['text']='[Jupyter current working directory: /workspace]'
                if mode=='shared':edge(graph,f[-1]['id'],'event:'+actions[1]['source']['event_id'],'response_to')
                if mode=='late':f[0]['event_index']=f[-1]['event_index']+1
                if mode=='context':f[-1]['properties']['context_id']='different'
                if mode=='hidden':f[-1]['properties']['agent_visibility']='not_established'
                result=rw.project(graph);m=rw.measure(result,'inputs_and_feedback_match')
                self.assertIsNone(m['value']);self.assertEqual((m['opportunities'],m['denominator'],m['unknown']),(1,0,1))
                self.assertIsNotNone(rw.measure(result,'inputs_changed')['value'])

    def test_disputed_cross_context_and_parallel_identity_never_establish_repeat(self):
        for mode in ('no_identity','different_context','parallel','disputed'):
            with self.subTest(mode=mode):
                _,graph,actions=fixture()
                if mode=='no_identity':graph['edges']=[e for e in graph['edges'] if e['type']!='same_action_target']
                if mode=='different_context':event(graph,actions[-1])['context_id']='another'
                if mode=='parallel':event(graph,actions[-1])['batch_size']=2
                if mode=='disputed':
                    from test_work_episodes import method
                    method(graph,actions[-1],actions[0],comparison='different_work')
                result=rw.project(graph)
                self.assertEqual(result['rows'],[])
                self.assertIsNone(rw.measure(result,'inputs_changed')['value'])

    def test_partial_or_duplicate_annotations_leave_gaps_without_multiplying_counts(self):
        for mode in ('split_endpoint','split_intervening','missing_intervening'):
            _,graph,actions=fixture()
            target=actions[-1] if mode=='split_endpoint' else actions[1]
            node=next(n for n in graph['nodes'] if n['id']==target['id'])
            if mode=='missing_intervening':graph['nodes'].remove(node)
            else:
                split=deepcopy(node);split['id']='second-annotation';graph['nodes'].append(split)
            result=rw.project(graph);m=rw.measure(result,'inputs_changed')
            self.assertIsNone(m['value'])
            self.assertLessEqual(m['opportunities'],1)
            if mode!='split_endpoint':self.assertEqual(m['unknown'],1)

    def test_feedback_sequence_order_and_count_are_part_of_comparison(self):
        _,graph,actions=fixture();f=output_events(graph)
        for original,action in ((f[0],actions[0]),(f[-1],actions[-1])):
            other=deepcopy(original);other['id']=original['id']+'-extra';other['properties']['id']+='-extra'
            other['properties']['text']='other result';other['event_index']+=0.1;graph['nodes'].append(other)
            edge(graph,other['id'],'event:'+action['source']['event_id'],'response_to')
        self.assertTrue(rw.project(graph)['rows'][0]['inputs_and_feedback_match'])
        graph['nodes'][-1]['event_index']=f[-1]['event_index']-0.1
        self.assertFalse(rw.project(graph)['rows'][0]['inputs_and_feedback_match'])

    def test_zero_pairs_are_unavailable_not_zero_frequency(self):
        _,graph,_=example(('inspect','edit','verify'))
        result=rw.project(graph);m=rw.measure(result,'inputs_changed')
        self.assertIsNone(m['value']);self.assertEqual(m['opportunities'],0)
        self.assertEqual(m['coverage']['recorded_actions'],3)

    def test_monitor_and_python_share_frozen_source_evidence_after_restart(self):
        from rilldex import Workspace
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'study.sqlite');run,graph,_=fixture();graph=freeze(graph)
            store.add([run])
            with store.connect() as c:graph_store.save(c,graph)
            m=monitoring.create(store,dict(name='Matching attempts',kind='analysis',observer=graph['observer'],
                analysis=dict(measure='revisit_exact_repeat_fraction')))
            self.assertEqual(monitoring.sync(store,[m['id']])['errors'],0)
            value=monitoring.values(store,m['id'],[run['id']])[run['id']]
            self.assertEqual((value['value'],value['denominator'],value['unknown']),(1,1,0))
            receipt=monitor_evidence.read(store,value['id'])
            self.assertEqual(receipt['explanation']['analysis_cases'][0]['repeated_work']['dispatch']['status'],'unchanged')
            self.assertEqual(Workspace(store.path).repeated_work(graph['id']),rw.project(graph))
            monitoring.enabled(store,m['id'],False)
            with patch.object(investigation_plans,'execute',side_effect=AssertionError('Read saved receipt, no recomputation')):
                reopened=monitor_evidence.read(Store(store.path),value['id'])
                for key in ('graph','explanation','measurement'):self.assertEqual(reopened[key],receipt[key])
            self.assertEqual(monitoring.sync(store,[m['id']])['inserted'],0)

    def test_all_registered_measures_use_one_projection_and_exact_case_denominators(self):
        _,graph,_=fixture()
        for key in rw.MEASURES:
            spec=analysis_metrics.definition(dict(measure=key))
            self.assertEqual(spec['operation'],'repeated_work')
            measured=analysis_metrics.measure(rw.project(graph),spec)
            self.assertEqual(measured['denominator'],len([c for c in measured['cases'] if c['taken'] is not None]))


if __name__=='__main__':unittest.main()
