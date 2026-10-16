from copy import deepcopy
import unittest
from unittest.mock import patch

from research.work_purpose_trial import fixture,CASES
from tracker.work_purpose import build,anchors,purpose_request,SPLIT_VERSION
from tracker.work_correspondence import state_before,candidate_records
from tracker.schema import digest


class WorkPurposeTests(unittest.TestCase):
    def decide(self,requests,mode='contextual',anchor=None):
        def choose(req):
            requests.append(req)
            source=anchor or req['state']['source_anchors'][-1]['id']
            return {k:{'value':mode if k.startswith('purpose_') else source} for k in req['questions']},'request'
        return choose

    def test_cutoff_and_requested_versions_do_not_leak_future_outcomes(self):
        run,local,work=fixture(CASES[3]);before=deepcopy((run,local,work));requests=[]
        result=build(run,local,work,self.decide(requests))
        self.assertEqual((run,local,work),before)
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(requests))
        self.assertEqual({j['record_id'] for j in result['actions'][0]['judgments']},{'balance','shipment'})
        self.assertTrue(all(j['anchor_source'] for j in result['actions'][0]['judgments']))

    def test_raw_expressed_choice_with_action_anchor_is_preserved_but_flagged(self):
        run,local,work=fixture(CASES[2]);result=build(run,local,work,self.decide([],mode='expressed'))
        self.assertTrue(all(j['choice']=='expressed' for j in result['actions'][0]['judgments']))
        self.assertTrue(all(j['status']=='needs_review' for j in result['actions'][0]['judgments']))
        self.assertNotIn('relations',result)

    def test_no_anchor_cannot_become_supported_purpose(self):
        run,local,work=fixture(CASES[2])
        for mode,status in [('contextual','needs_review'),('other_work','needs_review'),('underdetermined','selected')]:
            result=build(run,local,work,self.decide([],mode=mode,anchor='no_identifiable_anchor'))
            self.assertTrue(all(j['status']==status for j in result['actions'][0]['judgments']))

    def test_withdrawal_does_not_gate_an_expressed_purpose(self):
        run,local,work=fixture(CASES[5]);agent=next(u for u in local['units'] if u['actor']=='agent' and u['kind']=='semantic')
        result=build(run,local,work,self.decide([],mode='expressed',anchor=agent['id']))
        selected=result['actions'][0]['judgments'][0]
        self.assertEqual(selected['requested_status'],'withdrawn');self.assertEqual(selected['status'],'selected')

    def test_candidate_overflow_waits_for_retrieval_without_false_negative(self):
        run,local,work=fixture(CASES[0]);requests=[]
        with patch('tracker.work_purpose.ANCHOR_LIMIT',1):result=build(run,local,work,self.decide(requests))
        self.assertEqual(result['actions'][0]['status'],'needs_anchor_retrieval')
        self.assertEqual(result['actions'][0]['judgments'],[]);self.assertEqual(requests,[])

    def test_cross_trajectory_and_same_event_late_anchor_excluded(self):
        run,local,work=fixture(CASES[2]);action=next(u for u in local['units'] if u['kind']=='action')
        other=deepcopy(local['units'][0]);other['id']='other';other['trajectory_id']='different';local['units'].append(other)
        overlap=deepcopy(action);overlap['id']='overlap';overlap['kind']='semantic';local['units'].append(overlap)
        snapshot=state_before(run,local,{**work,'extraction_hash':digest(local)},action)
        pool=candidate_records(work,snapshot)
        self.assertFalse({'other','overlap'}&{a['id'] for a in anchors(run,local,action,pool)})

    def test_framing_and_context_remain_distinct_for_conflicting_execution(self):
        run,local,work=fixture(CASES[-1]);agent=next(u for u in local['units'] if u['actor']=='agent' and u['kind']=='semantic')
        def choose(req):
            self.assertEqual(req['state']['purpose_harness'],SPLIT_VERSION)
            return {k:{'value':'underdetermined' if k.startswith('purpose_') else agent['id']} for k in req['questions']},'request'
        result=build(run,local,work,choose,version=SPLIT_VERSION)
        self.assertEqual(result['schema'],SPLIT_VERSION)
        self.assertEqual(len(result['actions'][0]['judgments']),2)
        for j in result['actions'][0]['judgments']:
            self.assertEqual(j['choice'],'underdetermined');self.assertEqual(j['framing']['source'],agent['source'])


if __name__=='__main__':unittest.main()
