import copy
import unittest

from tracker.relation_candidates import retrieve,previous_units,retrieve_budgeted
from tracker.schema import InputError


def unit(index,text='A statement.',**updates):
    return {'id':'u'+str(index),'trace_id':'trace','actor_id':'main','event_index':index,
            'source_pointer':'/messages/'+str(index),'start':0,'end':len(text),'text':text,'role':'model',**updates}


class RelationCandidateTests(unittest.TestCase):
    def test_past_only_and_label_blind(self):
        prior=[unit(i) for i in range(20)];subject=unit(20,'Check the total.')
        expected=retrieve(prior,subject)
        enriched=copy.deepcopy(prior)
        for u in enriched:u.update(label='secret reference',confidence=1,final_reward=0)
        self.assertEqual(expected,retrieve(enriched+[unit(21,'Check the total.'),unit(19,trace_id='other'),unit(18,actor_id='other')],subject))
        self.assertFalse(any('label' in c['unit'] for c in expected['candidates']))

    def test_overlap_and_other_source_in_same_event_are_excluded(self):
        s=unit(2,'later',start=8,end=13)
        units=[unit(0),unit(2,'earlier',id='before',start=0,end=7),
               unit(2,'overlap',id='overlap',start=6,end=13),unit(2,'other',id='other',source_pointer='/other')]
        self.assertEqual([u['id'] for u in previous_units(units,s)],['u0','before'])

    def test_long_distance_lexical_target_and_bounded_size(self):
        prior=[unit(0,'The invoice total is 731.')]+[unit(i,'Continue unrelated work.') for i in range(1,20)]
        s=unit(20,'Check invoice total 731.')
        self.assertNotIn('u0',[c['unit']['id'] for c in retrieve(prior,s,'recent12')['candidates']])
        actual=retrieve(prior,s,'hybrid12')['candidates']
        self.assertIn('u0',[c['unit']['id'] for c in actual]);self.assertEqual(len(actual),12)

    def test_qualified_duplicate_and_malformed_span_fail(self):
        with self.assertRaises(InputError):retrieve([unit(1),unit(1)],unit(2))
        with self.assertRaises(InputError):retrieve([unit(1,end=100)],unit(2))
        with self.assertRaises(InputError):retrieve([unit(2,'A different subject.')],unit(2))

    def test_adding_future_vocabulary_cannot_change_idf_or_hash(self):
        prior=[unit(i,'Numbers '+str(i)) for i in range(20)];s=unit(20,'Numbers 0')
        future=[unit(i,'Numbers 0 0 0 0') for i in range(21,60)]
        self.assertEqual(retrieve(prior,s),retrieve(prior+future,s))

    def test_explicit_budget_preserves_legacy_candidates_and_never_reads_future(self):
        prior=[unit(i,'Claim '+str(i)) for i in range(60)];s=unit(60,'Check claim 2')
        old=retrieve(prior,s);new=retrieve_budgeted(prior,s,candidate_limit=12,recent_limit=6)
        self.assertEqual(old['candidates'],new['candidates']);self.assertEqual(old['candidate_set_hash'],new['candidate_set_hash'])
        large=retrieve_budgeted(prior,s,candidate_limit=24,recent_limit=12)
        self.assertEqual(len(large['candidates']),24)
        self.assertEqual(large,retrieve_budgeted(prior+[unit(61,'Check claim 2')],s,candidate_limit=24,recent_limit=12))

    def test_zero_recent_does_not_select_the_entire_prefix_and_limits_validate(self):
        prior=[unit(i,'Target '+str(i)) for i in range(20)];s=unit(20,'Target 0')
        got=retrieve_budgeted(prior,s,candidate_limit=1,recent_limit=0)
        self.assertEqual(len(got['candidates']),1);self.assertEqual(got['candidates'][0]['unit']['id'],'u0')
        for size,recent in [(0,0),(65,12),(12,13),(12,-1),(True,0),(12,True)]:
            with self.subTest(size=size,recent=recent),self.assertRaises(InputError):
                retrieve_budgeted(prior,s,candidate_limit=size,recent_limit=recent)


if __name__=='__main__':unittest.main()
