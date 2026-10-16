from copy import deepcopy
from unittest import TestCase,main
from unittest.mock import patch
from tracker.schema import digest,InputError
from tracker.work_context import build,candidates,context_request,project
from research.work_purpose_trial import fixture,CASES


class WorkContextTests(TestCase):
    def test_source_preservation_and_cutoff(self):
        run,local,_=fixture(CASES[3]);before=deepcopy((run,local));requests=[]
        def choose(req):
            requests.append(req)
            return {'choice':{'value':'unresolved'}},digest(req)
        result=build(run,local,choose)
        self.assertEqual((run,local),before)
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(requests))
        self.assertNotIn('relations',result)
        self.assertEqual(len(result['observations']),2)
        first=requests[0]['state']['candidate_frames']
        self.assertEqual(len(first),1) # Later request cannot enter earlier report.

    def test_source_candidates_do_not_depend_on_requested_record_status(self):
        run,local,_=fixture(CASES[5]);action=next(u for u in local['units'] if u['kind']=='action')
        pool=candidates(run,local,action)
        self.assertEqual([p['source']['text'] for p in pool],['Delete report A.','Do not delete report A.'])

    def test_multiple_membership_has_a_separate_raw_decision(self):
        run,local,_=fixture(CASES[0]);seen=[]
        def choose(req):
            seen.append(req)
            if 'choice' in req['questions']:return {'choice':{'value':'multiple'}},digest(req)
            return {k:{'value':'included'} for k in req['questions']},digest(req)
        result=build(run,local,choose)
        self.assertEqual(result['observations'][0]['status'],'inconsistent_multiple')
        self.assertEqual(len(result['observations'][-1]['frame_ids']),2)
        self.assertEqual(len(result['observations'][-1]['requests']),2)

    def test_partial_multiple_is_not_promoted_as_complete_membership(self):
        run,local,_=fixture(CASES[0])
        def choose(req):
            if 'choice' in req['questions']:return {'choice':{'value':'multiple'}},digest(req)
            keys=list(req['questions'])
            return {k:{'value':'included' if k==keys[0] else 'unresolved'} for k in keys},digest(req)
        row=build(run,local,choose)['observations'][-1]
        self.assertEqual(row['status'],'needs_review');self.assertEqual(len(row['frame_ids']),1)

    def test_overflow_does_not_select_absence(self):
        run,local,_=fixture(CASES[0])
        with patch('tracker.work_context.LIMIT',0):
            result=build(run,local,lambda req:self.fail('Must retrieve before selection'))
        self.assertTrue(all(r['status']=='needs_frame_retrieval' for r in result['observations']))

    def test_other_trajectory_is_not_a_frame(self):
        run,local,_=fixture(CASES[0]);event=deepcopy(run['events'][0])
        event.update(id='other',trajectory_id='other');run['events'].insert(0,event)
        action=next(u for u in local['units'] if u['kind']=='action')
        self.assertNotIn('event-other',{p['id'] for p in candidates(run,local,action)})

    def test_unknown_raw_selection_is_rejected(self):
        run,local,_=fixture(CASES[0])
        with self.assertRaises(InputError):build(run,local,lambda req:({'choice':{'value':'invented'}},'x'))

    def test_invisible_or_copied_user_content_is_not_a_new_scope(self):
        for flags in [{'agent_visibility':'not_established'},{'copied_context':True},{'kind':'external_instruction'}]:
            run,local,_=fixture(CASES[0]);run['events'][0].update(flags)
            action=next(u for u in local['units'] if u['kind']=='action')
            self.assertNotIn('event-e1',{p['id'] for p in candidates(run,local,action)})

    def test_projection_counts_a_shared_unit_once_and_does_not_create_task_links(self):
        run,local,_=fixture(CASES[0])
        def choose(req):
            if len(req['state']['candidate_frames'])==1:return {'choice':{'value':req['state']['candidate_frames'][0]['id']}},digest(req)
            if 'choice' in req['questions']:return {'choice':{'value':'multiple'}},digest(req)
            return {k:{'value':'included'} for k in req['questions']},digest(req)
        result=build(run,local,choose);view=project(run,{'units':local['units']},result)
        self.assertEqual(view['selected_units'],3)
        self.assertEqual(sum(len(g['unit_ids']) for g in view['groups']),5)
        self.assertEqual({r['type'] for r in view['relations']},{'in_work_context'})
        self.assertFalse(any('requested_work_id' in r for r in view['relations']))

    def test_unannotated_source_frame_remains_a_source_reference(self):
        run,local,_=fixture(CASES[2]);local['units']=[u for u in local['units'] if u['actor']!='user']
        def choose(req):return {'choice':{'value':'event-e1'}},digest(req)
        result=build(run,local,choose);view=project(run,{'units':local['units']},result)
        self.assertEqual(view['groups'][0]['source_unit_ids'],[])
        self.assertEqual(view['relations'],[])
        self.assertEqual(view['groups'][0]['source']['text'],CASES[2]['user'])

    def test_plan_frames_include_self_but_exclude_a_later_plan(self):
        run,local,_=fixture(CASES[0])
        plans=[u for u in local['units'] if u['actor']=='agent' and u['kind']=='semantic']
        for p in plans:p.update(activity='plan',plan_structure={'steps':[]})
        first=candidates(run,local,plans[0]);later=candidates(run,local,plans[1])
        self.assertIn('plan-'+plans[0]['id'],{p['id'] for p in first})
        self.assertNotIn('plan-'+plans[1]['id'],{p['id'] for p in first})
        self.assertIn('plan-'+plans[1]['id'],{p['id'] for p in later})


if __name__=='__main__':main()
