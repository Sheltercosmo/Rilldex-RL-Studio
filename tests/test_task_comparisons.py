import unittest
from tracker import task_comparisons as tc, attempt_chains as ac
from tracker.schema import InputError


def rows(prefix, task, successes, failures, unknown=0):
    return [dict(id=f'{prefix}/{i}',task_id=task,outcome=value)
            for i,value in enumerate(['passed']*successes+['failed']*failures+['unknown']*unknown)]


def chain(identifier, step, task, initial='failed', retry='passed'):
    attempts=[dict(position=1,result=initial,context='initial',reset='original_state')]
    if retry is not None:attempts.append(dict(position=2,result=retry,context='failure_feedback',reset='original_state'))
    return dict(producer='p',chain_id=identifier,root_step=step,task_ids=[task],budget=2,
                has_initial=True,issues=[],attempts=attempts)


class TaskComparisonTests(unittest.TestCase):
    def test_task_mix_can_reverse_the_aggregate_direction(self):
        reference=rows('re','easy',9,1)+rows('rh','hard',1,9)
        focus=rows('fe','easy',80,20)+rows('fh','hard',0,1)
        result=tc.compare(focus,reference)
        self.assertGreater(result['raw_difference'],0)
        self.assertAlmostEqual(result['equal_task_difference'],-.1)
        self.assertTrue(result['direction_reverses'])
        self.assertEqual(result['shared_tasks'],['easy','hard'])
        self.assertEqual(result['equal_task_weight']['focus']['opportunities'],101)

    def test_unknowns_keep_bounds_without_silently_dropping_a_shared_task(self):
        r=tc.compare(rows('a','a',2,0)+rows('b','b',0,0,2),rows('c','a',1,1)+rows('d','b',1,1))
        self.assertEqual(r['status'],'undecidable_tasks')
        self.assertIsNone(r['equal_task_difference'])
        self.assertEqual(r['equal_task_weight']['focus']['lower'],.5)
        self.assertEqual(r['equal_task_weight']['focus']['upper'],1)
        self.assertEqual(r['difference_lower'],0)
        self.assertEqual(r['difference_upper'],.5)

    def test_unshared_and_missing_tasks_keep_raw_outcomes_but_leave_fixed_comparison(self):
        r=tc.compare(rows('a','a',1,0)+rows('x','new',10,0)+rows('n',None,1,0),rows('b','a',0,1)+rows('y','old',0,3))
        self.assertEqual(r['shared_tasks'],['a'])
        self.assertEqual(r['equal_task_weight']['focus']['excluded_opportunities'],11)
        self.assertEqual(r['raw']['focus']['missing_task'],1)
        self.assertEqual(r['equal_task_difference'],1)

    def test_no_shared_or_no_outcomes_remains_unavailable(self):
        self.assertEqual(tc.compare(rows('a','a',1,0),rows('b','b',1,0))['status'],'no_shared_tasks')
        self.assertIsNone(tc.compare([],[])['equal_task_difference'])
        all_unknown=tc.compare(rows('a','a',0,0,1),rows('b','a',0,0,1))
        self.assertEqual((all_unknown['difference_lower'],all_unknown['difference_upper']),(-1,1))

    def test_contract_and_duplicate_opportunities_are_checked(self):
        row=rows('a','a',1,0)[0]
        with self.assertRaises(InputError):tc.compare([row,row],[])
        with self.assertRaises(InputError):tc.compare([dict(row,outcome='success')],[])
        with self.assertRaises(InputError):tc.compare([dict(row,task_id='')],[])
        self.assertEqual(tc.compare([row],[row])['shared_opportunity_ids'],['a/0'])

    def test_input_order_does_not_change_aggregate_or_task_order(self):
        a=rows('a','a',3,1)+rows('b','b',0,2);b=rows('c','a',1,1)+rows('d','b',1,2)
        x=tc.compare(a,b);y=tc.compare(list(reversed(a)),list(reversed(b)))
        self.assertEqual(x['equal_task_difference'],y['equal_task_difference'])
        self.assertEqual(x['shared_tasks'],y['shared_tasks'])

    def test_windows_use_distinct_recorded_root_steps_not_retry_or_arrival_order(self):
        cases=[chain('a',2,'a'),chain('b',100,'a'),chain('c',400,'a'),chain('d',900,'a')]
        value=ac.window_comparisons(list(reversed(cases)))
        self.assertEqual(value['default_width'],2)
        w=next(w for w in value['windows'] if w['width']==2)
        self.assertEqual(w['coordinates'],dict(focus=[400,900],reference=[2,100]))
        self.assertEqual(w['measures']['first_retry_success']['raw']['focus']['opportunities'],2)

    def test_retry_population_excludes_success_and_unknown_initials(self):
        cases=[chain('ok',1,'a','passed',None),chain('unknown',1,'a','unknown',None),
               chain('wait',1,'a','failed',None),chain('retried',2,'a','failed','passed')]
        w=ac.window_comparisons(cases)['windows'][0]
        m=w['measures']['first_retry_success']
        self.assertEqual(m['raw']['reference']['opportunities'],1)
        self.assertEqual(m['raw']['reference']['unknown'],1)
        self.assertEqual(w['retry_context']['reference'],[dict(context='retry_missing',reset='unrecorded',chains=1)])
        self.assertTrue(w['retry_context_differs'])

    def test_retry_context_change_uses_proportions_not_different_window_sizes(self):
        cases=[chain('a',1,'a'),chain('b',2,'a'),chain('c',2,'a')]
        self.assertFalse(ac.window_comparisons(cases)['windows'][0]['retry_context_differs'])
        cases[-1]['attempts'][1]['context']='fresh_retry'
        self.assertTrue(ac.window_comparisons(cases)['windows'][0]['retry_context_differs'])

    def test_missing_coordinate_or_only_one_step_does_not_invent_comparison(self):
        self.assertEqual(ac.window_comparisons([chain('a',None,'a')])['windows'],[])
        self.assertEqual(ac.window_comparisons([chain('a',1,'a')])['windows'],[])

    def test_conflicting_task_identity_is_not_matched(self):
        a=chain('a',1,'a');a['task_ids']=['a','b'];a['issues']=['task_identity_conflict']
        w=ac.window_comparisons([a,chain('b',2,'a')])['windows'][0]
        self.assertEqual(w['measures']['first_success']['raw']['reference']['missing_task'],1)
        self.assertEqual(w['measures']['first_success']['status'],'no_shared_tasks')


if __name__=='__main__':unittest.main()
