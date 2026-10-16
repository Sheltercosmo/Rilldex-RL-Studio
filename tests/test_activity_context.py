"""Text coverage contracts, not semantic-sufficiency or accuracy references."""
import copy
import unittest

from tracker.activity import ActivityClient, analyze, packet, units
from tracker.activity_context import audit, merge_ranges, visible_prefix
from test_activity import reasoning_run, response


class ContextCoverageTests(unittest.TestCase):
    def setUp(self):
        self.run=reasoning_run();self.subject=units(self.run)[0]

    def check(self,run=None,subject=None,state=None):
        run=run or self.run;subject=subject or self.subject
        state=state if state is not None else packet(run,subject['id'])['state']
        return audit(visible_prefix(run,subject),state,subject)

    def test_exact_unicode_subject_and_overlap_are_counted_once(self):
        self.run['events'][1]['text']='Check 🧭 first. Then continue.'
        subject=units(self.run)[0];state=packet(self.run,subject['id'])['state']
        state['earlier_units']=[copy.deepcopy(state['subject'])]
        result=self.check(subject=subject,state=state)
        self.assertEqual(result['status'],'audited')
        row=next(e for e in result['events'] if e['event_id']==subject['event_id'])
        self.assertEqual(row['supplied_characters'],len(subject['text']))
        self.assertEqual(row['supplied_ranges'],[[0,subject['end']]])
        self.assertEqual(len(row['packet_locations']),2)
        self.assertEqual(merge_ranges([[4,7],[0,2],[1,5],[7,7]]),[[0,7]])

    def test_omitted_instruction_is_exposed_without_changing_packet_or_decision(self):
        for i in range(1,4):
            self.run['events'].insert(i,{'id':f'user{i}','index':i-.5,'kind':'instruction','actor':'user','trajectory_id':'main','text':f'Follow-up {i}','source_pointer':f'/followup/{i}'})
        subject=units(self.run)[-1];request=packet(self.run,subject['id']);before=copy.deepcopy(request)
        result=self.check(subject=subject,state=request['state'])
        omitted=[e for e in result['events'] if e['source_kind']=='instruction' and e['status']=='omitted']
        self.assertEqual([e['event_id'] for e in omitted],['user1'])
        self.assertEqual(omitted[0]['omitted_ranges'],[[0,len('Follow-up 1')]])
        self.assertEqual(request,before)
        saved=ActivityClient(transport=lambda r:response(r,{'plan':'present'})).evaluate(self.run,subject['id'])
        state=copy.deepcopy(saved)
        u=next(u for u in analyze(self.run,{subject['id']:saved})['units'] if u['id']==subject['id'])
        self.assertEqual(u['context_coverage']['status'],'audited')
        self.assertEqual(u['observation'],state)
        self.assertIn('plan',u['activities'])

    def test_clipping_preserves_codepoint_ranges_and_accounting_identity(self):
        self.run['events'][0]['text']='🧭'*5001
        result=self.check();row=next(e for e in result['events'] if e['source_kind']=='instruction')
        self.assertEqual(row['status'],'partial')
        self.assertEqual(row['supplied_ranges'],[[0,5000]])
        self.assertEqual(row['omitted_ranges'],[[5000,5001]])
        for totals in [result['summary'],*result['by_source_kind'].values()]:
            self.assertEqual(totals['available_characters'],totals['supplied_characters']+totals['omitted_characters'])

    def test_prefix_excludes_future_tail_external_state_and_other_trajectory(self):
        for eid,kind,trajectory in [('outside','external_tool','main'),('other','feedback','other-agent')]:
            self.run['events'].insert(0,{'id':eid,'index':-1,'kind':kind,'actor':'other','trajectory_id':trajectory,'text':'NOT_VISIBLE','source_pointer':'/hidden'})
        prefix=visible_prefix(self.run,self.subject)
        self.assertFalse(any(e['text']=='NOT_VISIBLE' for e in prefix))
        self.assertNotIn('Perhaps both roots are positive.',str(prefix))
        state=packet(self.run,self.subject['id'])['state'];bad=copy.deepcopy(state)
        bad['earlier_units'].append({'id':'outside','text':'NOT_VISIBLE'})
        result=self.check(state=bad)
        self.assertEqual(result['status'],'binding_issues')
        self.assertEqual(len(result['binding_issues']),1)

    def test_corrupt_text_actor_pointer_and_boundaries_do_not_count_as_supplied(self):
        original=packet(self.run,self.subject['id'])['state']
        for change in ({'text':'different'},{'actor':'someone-else'},{'source_pointer':'/wrong'},{'start':-1},{'end':99999}):
            state=copy.deepcopy(original);state['subject'].update(change)
            result=self.check(state=state)
            self.assertEqual(result['status'],'binding_issues')
            row=next(e for e in result['events'] if e['event_id']==self.subject['event_id'])
            self.assertEqual(row['supplied_characters'],0)
        state=copy.deepcopy(original);state['cutoff_codepoint']+=1
        self.assertEqual(self.check(state=state)['status'],'unavailable')

    def test_copied_context_and_unsupported_or_absent_packets_remain_explicit(self):
        copy_event=copy.deepcopy(self.run['events'][0]);copy_event.update(id='copy',index=-1,copied_context=True)
        self.run['events'].insert(0,copy_event)
        result=self.check()
        self.assertEqual(result['excluded_copied_context_event_ids'],['copy'])
        self.assertNotIn('copy',[e['event_id'] for e in result['events']])
        state=packet(self.run,self.subject['id'])['state'];state['harness']='unknown-future-version'
        self.assertEqual(self.check(state=state)['status'],'unavailable')
        self.assertEqual(audit([],None,self.subject)['status'],'unavailable')


if __name__=='__main__':unittest.main()
