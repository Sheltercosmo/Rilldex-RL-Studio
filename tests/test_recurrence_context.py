from copy import deepcopy
import unittest

from tracker.recurrence_context import build
from tracker.schema import InputError
from tests.test_work_paths import fixture


def context_fixture():
    run, doc = fixture()
    for event in run['events']:
        event.update(trajectory_id='main', text='0123456789', source_pointer='/'+event['id'],
                     tool='execute', argument_status='json_object', arguments={'command':'train'})
    return run, doc


class RecurrenceContextTests(unittest.TestCase):
    def test_identical_call_keeps_intervening_meanings_and_selected_assessments(self):
        run, doc = context_fixture(); original = deepcopy(doc)
        doc['units'][3]['actor'] = 'user'
        result = build(run, doc, '1', '7')
        self.assertEqual(result['dispatch_comparison']['status'], 'identical')
        self.assertEqual(result['between_unit_ids'], ['2','3','4','5','6'])
        self.assertEqual(result['previous']['recorded_expression_unit_ids'], ['0'])
        self.assertEqual(result['current']['recorded_expression_unit_ids'], ['6'])
        self.assertEqual(result['assessment_relation_indices'], [3,6])
        self.assertEqual(result['unrepresented_source_ranges'], [])
        self.assertNotIn('strategy', result)
        doc['units'][3]['actor'] = original['units'][3]['actor']
        self.assertEqual(doc, original)
        result['dispatch_comparison']['after_arguments']['command']='changed'
        self.assertEqual(run['events'][7]['arguments']['command'], 'train')

    def test_late_responses_and_late_associations_stay_outside_decision_cutoff(self):
        run, doc = context_fixture()
        for index, kind in [(8,'feedback'),(9,'semantic')]:
            event={'id':'e'+str(index),'index':index,'trajectory_id':'main','text':'0123456789'}
            run['events'].append(event)
            doc['units'].append({'id':str(index),'kind':kind,'actor':'environment' if kind=='feedback' else 'agent',
                'trajectory_id':'main','source':{'event_id':event['id'],'start':0,'end':10}})
        doc['relations'] += [{'from':'8','to':'7','type':'feedback_for'},
                             {'from':'9','to':'7','type':'recorded_with'}]
        result=build(run,doc,'1','7')
        self.assertEqual(result['after_current_dispatch_unit_ids'], ['8','9'])
        self.assertNotIn('8', result['available_at_current_dispatch_unit_ids'])
        self.assertEqual(result['current']['expression_timing']['9'], 'after_dispatch')
        self.assertEqual(result['current']['response_unit_ids'], ['8'])
        # An earlier action's delayed response must also stay after the cutoff.
        doc['relations'][-2]['to']='1'
        result=build(run,doc,'1','7')
        self.assertIn('8', result['after_current_dispatch_unit_ids'])

    def test_unrepresented_text_and_other_trajectories_are_not_silently_included(self):
        run, doc=context_fixture()
        doc['units'][4]['source'].update(start=2,end=6)
        doc['units'][3]['trajectory_id']='other';run['events'][3]['trajectory_id']='other'
        result=build(run,doc,'1','7')
        self.assertNotIn('3',result['between_unit_ids'])
        self.assertEqual([(r['event_id'],r['start'],r['end']) for r in result['unrepresented_source_ranges']],
                         [('e4',0,2),('e4',6,10)])
        run['events'][5]['text']='';doc['units'][5]['source']['end']=0
        self.assertIn('e5',build(run,doc,'1','7')['events_without_text'])

    def test_dispatch_comparison_retains_json_types_and_missingness(self):
        run,doc=context_fixture()
        run['events'][1]['arguments']={'flag':True,'ordered':[1,2]}
        run['events'][7]['arguments']={'flag':1,'ordered':[2,1]}
        comparison=build(run,doc,'1','7')['dispatch_comparison']
        self.assertEqual(comparison['status'],'changed')
        self.assertEqual(comparison['changed_top_level_arguments'],['flag','ordered'])
        run['events'][7]['arguments']={'ordered':[1,2],'flag':True}
        self.assertEqual(build(run,doc,'1','7')['dispatch_comparison']['status'],'identical')
        del run['events'][7]['arguments']
        self.assertEqual(build(run,doc,'1','7')['dispatch_comparison']['status'],'not_comparable')
        self.assertEqual(build(run,doc,'1','7')['dispatch_comparison']['source_text_status'],'identical')
        # Equal publisher descriptions never upgrade missing native arguments.
        run['events'][7]['arguments']={};run['events'][7].pop('argument_status')
        self.assertEqual(build(run,doc,'1','7')['dispatch_comparison']['status'],'not_comparable')

    def test_no_assessment_is_inferred_from_adjacency(self):
        run,doc=context_fixture();doc['relations']=[r for r in doc['relations'] if r['type']!='assesses']
        self.assertEqual(build(run,doc,'1','7')['assessment_relation_indices'],[])

    def test_bad_endpoints_or_native_bindings_are_rejected(self):
        for kind in ['reverse','actor','trajectory','feedback','cross_response']:
            with self.subTest(kind=kind):
                run,doc=context_fixture();previous,current='1','7'
                if kind=='reverse':previous,current=current,previous
                elif kind=='actor':doc['units'][7]['actor']='other'
                elif kind=='trajectory':doc['units'][7]['trajectory_id']='other'
                elif kind=='feedback':doc['relations'][2]['from']='0'
                else:doc['units'][2]['trajectory_id']='other'
                with self.assertRaises(InputError):build(run,doc,previous,current)


if __name__=='__main__':unittest.main()
