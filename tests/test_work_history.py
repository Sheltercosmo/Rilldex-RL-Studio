"""Source-order recurrence projection, with no new semantic decisions."""
from copy import deepcopy
import unittest

from tracker.schema import InputError
from tracker.work_paths import build as paths
from tracker.work_history import build
from tests.test_work_paths import fixture


def history_fixture():
    run,doc=fixture()
    # A, B, A: recurrence with a different selected group between endpoints.
    doc['relations'][0]={'from':'7','to':'1','type':'same_action_target','request':'identity-A'}
    doc['action_target_review']=[{'action_unit_id':i,'status':'linked' if i=='7' else 'none_of_these'} for i in ['1','4','7']]
    doc['work_paths']=paths(run,doc)
    return run,doc


class WorkHistoryTests(unittest.TestCase):
    def test_spaced_recurrence_is_not_a_failure_or_extra_check(self):
        run,doc=history_fixture();before=deepcopy(doc);result=build(run,doc)
        self.assertEqual(doc,before);self.assertEqual(result['counts']['operations'],3)
        self.assertEqual(result['counts']['spaced_recurrences'],1)
        self.assertEqual(result['counts']['consecutive_recurrences'],0)
        row=result['recurrences'][0]
        self.assertEqual((row['unit_id'],row['previous_group_unit_id']),('7','1'))
        self.assertEqual(row['intervening_action_unit_ids'],['4'])
        self.assertEqual(row['supporting_identity_relations'][0]['request'],'identity-A')
        self.assertNotIn('outcome',row);self.assertNotIn('failure',row)
        # Multiple checking/plan links and a shared prose contribution do not
        # create additional executed operations or alter target recurrence.
        doc['relations'] += [{'from':'7','to':'0','type':'attempts_stated_check','check_id':'a'},
                             {'from':'7','to':'0','type':'attempts_stated_check','check_id':'b'}]
        doc['work_paths']=paths(run,doc)
        self.assertEqual(build(run,doc)['counts'],result['counts'])

    def test_consecutive_groups_and_transitive_support_preserve_direct_selection(self):
        run,doc=history_fixture()
        doc['relations'][0]={'from':'4','to':'1','type':'same_action_target','request':'first'}
        doc['relations'].append({'from':'7','to':'1','type':'same_action_target','request':'second'})
        doc['work_paths']=paths(run,doc);result=build(run,doc)
        self.assertEqual(result['counts']['consecutive_recurrences'],2)
        self.assertEqual(len(result['streams'][0]['segments']),1)
        row=result['recurrences'][1]
        self.assertEqual(row['previous_group_unit_id'],'4')
        self.assertEqual(row['selected_prior_unit_id'],'1')
        self.assertEqual({r['request'] for r in row['supporting_identity_relations']},{'first','second'})

    def test_other_actors_and_trajectories_do_not_create_intervening_work(self):
        for field in ['actor','trajectory_id']:
            with self.subTest(field=field):
                run,doc=history_fixture();doc['units'][4][field]='other'
                doc['work_paths']=paths(run,doc);result=build(run,doc)
                self.assertEqual(len(result['streams']),2)
                self.assertEqual(result['counts']['consecutive_recurrences'],1)
                self.assertEqual(result['recurrences'][0]['intervening_action_unit_ids'],[])

    def test_missing_correspondence_is_not_a_new_goal_or_recurrence(self):
        run,doc=history_fixture();doc['relations']=[]
        doc['action_target_review']=[{'action_unit_id':'1','status':'no_prior_selected_action'},
                                   {'action_unit_id':'4','status':'unresolved'},
                                   {'action_unit_id':'7','status':'needs_target_candidate_retrieval'}]
        doc['work_paths']=paths(run,doc);result=build(run,doc)
        self.assertEqual(result['counts']['unresolved_or_uninspected'],2)
        self.assertEqual(result['counts']['recurring_assignments'],0)
        self.assertNotIn('new_goals',result['counts'])
        doc['work_paths']={'available':False,'paths':[]}
        self.assertFalse(build(run,doc)['available'])

    def test_graph_inconsistency_and_unproven_merges_are_rejected(self):
        for error in ['duplicate','missing','unproven_merge','future','cross_actor']:
            with self.subTest(error=error):
                run,doc=history_fixture()
                if error=='duplicate':doc['work_paths']['paths'].append(deepcopy(doc['work_paths']['paths'][0]))
                elif error=='missing':doc['work_paths']['paths'][0]['dispatch_unit_ids'].pop()
                elif error=='unproven_merge':doc['relations']=[]
                elif error=='future':doc['relations'][0].update({'from':'1','to':'7'})
                else:doc['units'][7]['actor']='other'
                with self.assertRaises(InputError):build(run,doc)

    def test_unrepresented_source_action_stays_a_gap_instead_of_false_adjacency(self):
        run,doc=history_fixture()
        run['events'][4].update(kind='action',actor='agent',trajectory_id='main',text='unannotated dispatch')
        doc['units']=[u for u in doc['units'] if u['id']!='4']
        doc['relations']=[r for r in doc['relations'] if '4' not in (r['from'],r['to'])]
        doc['action_target_review']=[r for r in doc['action_target_review'] if r['action_unit_id']!='4']
        doc['work_paths']=paths(run,doc);result=build(run,doc)
        self.assertEqual(result['counts']['operations'],2)
        self.assertEqual(result['counts']['unrepresented_operations'],1)
        self.assertEqual(result['counts']['consecutive_recurrences'],0)
        self.assertEqual(result['streams'][0]['position_count'],3)
        self.assertEqual([o['position'] for o in result['streams'][0]['groups'][0]['occurrences']],[1,3])
        self.assertEqual(result['recurrences'][0]['intervening_unrepresented_action_event_ids'],['e4'])
        self.assertEqual(result['recurrences'][0]['intervening_action_unit_ids'],[])
        self.assertEqual(len(result['streams'][0]['segments']),2)


if __name__=='__main__':unittest.main()
