"""Projection correctness: no invented inference or duplicated unit counts."""
import copy
import unittest
from tracker.schema import InputError
from tracker.work_paths import build


def fixture():
    kinds=['semantic','action','feedback','semantic','action','feedback','semantic','action']
    units=[{'id':str(i),'kind':k,'actor':'agent' if k!='feedback' else 'environment','trajectory_id':'main',
      'source':{'event_id':'e'+str(i),'start':0,'end':10},'content':{'target':{'text':'Install dependencies.'}}}
      for i,k in enumerate(kinds)]
    units[0]['plan_structure']={'steps':[{'id':'prepare'}]}
    relations=[{'from':'4','to':'1','type':'same_action_target'},
      {'from':'0','to':'1','type':'recorded_with'},
      {'from':'2','to':'1','type':'feedback_for'},
      {'from':'3','to':'2','type':'assesses'},
      {'from':'3','to':'4','type':'recorded_with'},
      {'from':'5','to':'4','type':'feedback_for'},
      {'from':'6','to':'5','type':'assesses'},
      {'from':'6','to':'7','type':'recorded_with'},
      {'from':'4','to':'0','type':'attempts_plan_step','plan_step_id':'prepare','plan_step_text':'Prepare tools','plan_step_target':'Tools'}]
    run={'events':[{'id':'e'+str(i),'index':i} for i in range(8)]}
    doc={'units':units,'relations':relations,'review_notes':[],
         'action_target_review':[{'action_unit_id':str(i),'status':'linked' if i==4 else 'none_of_these'} for i in [1,4,7]]}
    return run,doc


class WorkPathTests(unittest.TestCase):
    def test_shared_prose_is_one_unit_per_path_and_actions_are_not_double_counted(self):
        run,doc=fixture();before=copy.deepcopy(doc);result=build(run,doc)
        self.assertEqual(doc,before);self.assertEqual(len(result['paths']),2)
        first,second=result['paths'];self.assertEqual(first['dispatch_unit_ids'],['1','4'])
        self.assertEqual([n['unit_id'] for n in first['timeline']],['0','1','2','3','4','5','6'])
        self.assertEqual(first['timeline'][3]['roles'],['recorded_expression','response_assessment'])
        self.assertEqual(first['counts']['prose_contributions'],3)
        self.assertIn('6',[n['unit_id'] for n in second['timeline']])
        self.assertEqual(result['dispatch_coverage']['actions_in_paths'],3)
        self.assertEqual(first['plan_stages'][0]['action_roles'][0]['relation'],'attempts_plan_step')
        self.assertNotIn('completed',str(result))

    def test_different_work_same_subject_does_not_merge_paths(self):
        for relation in ['different_work_same_subject','overlapping_work_scope','similar_operation_distinct_target']:
            with self.subTest(relation=relation):
                run,doc=fixture();doc['relations'][0]['type']=relation
                result=build(run,doc);self.assertEqual(len(result['paths']),3)

    def test_uninspected_correspondence_is_not_a_set_of_established_new_targets(self):
        run,doc=fixture();doc.pop('action_target_review')
        self.assertFalse(build(run,doc)['available']);self.assertEqual(build(run,doc)['paths'],[])

    def test_temporal_actor_and_stage_integrity(self):
        for change in ['future','actor','trajectory','stage']:
            with self.subTest(change=change):
                run,doc=fixture()
                if change=='future':doc['relations'][0].update({'from':'1','to':'4'})
                elif change=='actor':doc['units'][4]['actor']='someone_else'
                elif change=='trajectory':doc['units'][4]['trajectory_id']='other'
                else:doc['relations'][-1]['plan_step_id']='invented'
                with self.assertRaises(InputError):build(run,doc)

    def test_disputed_selection_remains_visible(self):
        run,doc=fixture();doc['review_notes']=[{'kind':'relation_review','unit_ids':['4']}]
        result=build(run,doc);self.assertTrue(result['paths'][0]['disputed_identity'])
        self.assertFalse(result['paths'][1]['disputed_identity'])

    def test_review_of_work_correspondence_does_not_dispute_target_identity(self):
        run,doc=fixture();doc['review_notes']=[{'kind':'relation_review','unit_ids':['4','0'],
            'relation_ref':{'from':'4','to':'0','type':'attempts_requested_work','requested_work_version_id':'work-1'}}]
        self.assertFalse(any(p['disputed_identity'] for p in build(run,doc)['paths']))
        doc['review_notes'][0]['relation_ref']={'from':'4','to':'1','type':'same_action_target'}
        self.assertTrue(build(run,doc)['paths'][0]['disputed_identity'])
