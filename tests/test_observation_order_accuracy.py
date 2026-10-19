"""Source order evidence must survive the source analysis, not just macro maps."""
from copy import deepcopy
import unittest
from tracker import capabilities, observe, sequence
from test_evidence import swe


def fixture():
    return swe([
        {'action':'pytest', 'observation':'1 passed in 1s'},
        {'action':'edit 1:1\nchange\nend_of_edit', 'observation':'edited'},
        {'action':'pytest', 'observation':'1 passed in 1s'},
    ], {'exit_status':'submitted'})


class ObservationOrderAccuracyTests(unittest.TestCase):
    def assert_uncertain(self, run, blocked):
        original = deepcopy(run)
        out = observe.analyze(run)
        self.assertEqual(out['sequence']['summary']['observed_pairs'], 0)
        self.assertEqual(out['sequence']['summary']['possible_pairs'], 2)
        self.assertEqual(out['sequence']['summary']['excluded_order_pairs'], 2)
        self.assertEqual(out['map']['edges'], [])
        self.assertEqual(out['flow']['edges'], [])
        self.assertEqual(out['scope_flow']['edges'], [])
        tail = out['verification']['actor_tails'][0]
        self.assertEqual(tail['status'], 'unresolved')
        self.assertIsNone(tail['last_check'])
        self.assertEqual(tail['application_after_check'], [])
        self.assertTrue(set(blocked) <= set(tail['unresolved_event_ids']))
        for action in out['actions'][1:]:
            self.assertEqual(action['feedback_support']['status'], 'unresolved')
            self.assertFalse(action['feedback_opportunity'])
        self.assertEqual(out['capabilities']['measurements']['verification_closure']['status'], 'limited')
        self.assertEqual(out['capabilities']['measurements']['work_sequence']['status'], 'limited')
        self.assertEqual(len(out['verification']['checks']), 2)
        self.assertEqual(run, original)
        return out

    def test_explicit_unknown_order_is_not_replaced_by_display_index(self):
        run = fixture(); actions = [e for e in run['events'] if e['kind']=='action']
        actions[1]['order_known'] = False
        out = self.assert_uncertain(run, [actions[1]['id']])
        self.assertEqual(out['sequence']['summary']['excluded_batch_pairs'], 0)

    def test_native_message_index_without_parent_identifies_parallel_actions(self):
        run = fixture(); actions = [e for e in run['events'] if e['kind']=='action']
        for a in actions[:2]:
            a.pop('parent_id', None); a['source_message_index'] = 7
        out = self.assert_uncertain(run, [a['id'] for a in actions[:2]])
        self.assertEqual(out['sequence']['summary']['excluded_batch_pairs'], 2)

    def test_declared_incomplete_parallel_batch_is_still_unordered(self):
        run = fixture(); actions = [e for e in run['events'] if e['kind']=='action']
        actions[1]['batch_size'] = 2
        self.assert_uncertain(run, [actions[1]['id']])

    def test_unordered_feedback_cannot_establish_a_response_opportunity(self):
        run = fixture()
        next(e for e in run['events'] if e['kind']=='feedback')['order_known'] = False
        action = [e for e in run['events'] if e['kind']=='action'][1]
        support = capabilities.feedback_support(run, action)
        self.assertEqual(support['status'], 'unresolved')
        self.assertFalse(support['opportunity'])

    def test_sequence_uses_recorded_order_even_when_rows_are_reordered(self):
        out = observe.analyze(fixture())
        self.assertEqual(sequence.observe(list(reversed(out['actions']))), out['sequence'])

    def test_unknown_action_does_not_bridge_neighbors_but_later_ordered_pairs_survive(self):
        run = fixture()
        actions = [e for e in run['events'] if e['kind']=='action']
        actions[0]['order_known'] = False
        out = observe.analyze(run)
        self.assertEqual(out['sequence']['summary']['observed_pairs'], 1)
        self.assertEqual(out['sequence']['pairs'][0]['from_event_id'], actions[1]['id'])
        self.assertEqual(out['actions'][-1]['feedback_support']['status'], 'available')

    def test_native_envelopes_are_local_to_session_and_agent(self):
        run = fixture()
        actions = [e for e in run['events'] if e['kind']=='action']
        for i, a in enumerate(actions):
            a['context_id'] = str(i); a['source_message_index'] = 7
        out = observe.analyze(run)
        self.assertEqual(out['sequence']['summary']['possible_pairs'], 0)
        self.assertEqual(out['sequence']['summary']['excluded_order_pairs'], 0)
        self.assertTrue(all(t['status']!='unresolved' for t in out['verification']['actor_tails']))

    def test_long_run_preserves_checks_and_all_ordered_opportunities(self):
        commands=['cat parser.py','edit 1:1\nchange\nend_of_edit','pytest','cat parser.py']
        run=swe([{'action':commands[i%4],'observation':'1 passed in 1s' if i%4==2 else 'Recorded.'}
                 for i in range(256)],{'exit_status':'submitted'})
        actions=[e for e in run['events'] if e['kind']=='action']
        context_by_action={a['id']:str(i//64) for i,a in enumerate(actions)}
        context='0'
        for event in run['events']:
            context=context_by_action.get(event['id'],context);event['context_id']=context
        for i,a in enumerate(actions):
            if i%16==7:a['order_known']=False
        out=observe.analyze(run);s=out['sequence']['summary']
        # Four lanes, 63 potential adjacencies each; 16 interior unordered
        # actions each invalidate two distinct pairs. Other pairs remain usable.
        self.assertEqual((s['possible_pairs'],s['observed_pairs'],s['excluded_order_pairs']),(252,220,32))
        self.assertEqual(out['metrics']['feedback_opportunities'],220)
        self.assertEqual(len(out['verification']['checks']),64)
        self.assertEqual(sum(e['count'] for e in out['map']['edges']),220)
        self.assertEqual(sum(e['count'] for e in out['flow']['edges']),220)
        self.assertEqual(len(out['verification']['actor_tails']),4)


if __name__ == '__main__': unittest.main()
