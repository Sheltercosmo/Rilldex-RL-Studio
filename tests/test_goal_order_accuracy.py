"""Known focus assignments must not turn unknown source order into returns."""
from copy import deepcopy
import unittest

from tracker import goals, observe
from tracker.adapters import normalize
from test_goals_reviews import planned_run


def fixture(pattern='ABAA'):
    run = planned_run()
    actions = [e for e in run['events'] if e['kind'] == 'action']
    a, b = [g['id'] for g in goals.catalog(run)['goals'] if g['kind'] == 'expressed_plan']
    semantics = {e['id']: {'focus_goal': {'status': 'decided', 'value': {'A': a, 'B': b}[letter]}}
                 for e, letter in zip(actions, pattern)}
    return run, actions, semantics


class GoalOrderAccuracyTests(unittest.TestCase):
    def test_unknown_order_retains_assignments_without_inventing_a_return(self):
        run, actions, semantics = fixture()
        actions[1]['order_known'] = False
        original = deepcopy(run)
        out = observe.analyze(run, semantics)
        tracking = out['goal_tracking']
        self.assertEqual(out['metrics']['goal_assignments'], 4)
        self.assertEqual(out['metrics']['goal_returns'], 0)
        self.assertEqual([t['kind'] for t in tracking['transitions']],
                         ['first_focus', 'focus_observed_order_unknown', 'focus_reobserved', 'continue'])
        self.assertEqual(sum(e['count'] for e in tracking['graph']['edges']), 1)
        self.assertEqual(tracking['coverage']['unordered_assignments'], 1)
        self.assertEqual(tracking['transitions'][2]['order_evidence']['status'], 'unresolved')
        self.assertEqual(run, original)

    def test_complete_parallel_dispatch_can_be_bracketed_but_not_sequenced(self):
        run, actions, semantics = fixture('ABBA')
        for e in actions[1:3]:
            e.pop('parent_id', None)
            e['source_message_index'] = 73
            e['batch_size'] = 2
        out = observe.analyze(run, semantics)
        self.assertEqual(out['metrics']['goal_returns'], 1)
        self.assertEqual(out['goal_tracking']['graph']['edges'], [])
        last = out['goal_tracking']['transitions'][-1]
        self.assertEqual(last['kind'], 'return')
        self.assertEqual(last['order_evidence']['status'], 'bracketed_parallel')
        self.assertEqual(set(last['order_evidence']['parallel_groups'][0]['event_ids']),
                         {e['id'] for e in actions[1:3]})

    def test_incomplete_parallel_dispatch_cannot_support_a_return(self):
        run, actions, semantics = fixture('ABBA')
        for e in actions[1:3]:
            e['parent_id'] = 'same-dispatch'
            e['batch_size'] = 3
        out = observe.analyze(run, semantics)
        self.assertEqual(out['metrics']['goal_returns'], 0)
        self.assertEqual(out['goal_tracking']['transitions'][-1]['kind'], 'focus_reobserved')

    def test_unordered_latest_focus_is_not_promoted_to_last_focus(self):
        run, actions, semantics = fixture('ABAB')
        actions[-1]['order_known'] = False
        out = observe.analyze(run, semantics)
        self.assertFalse(any(g['pursuit_status'] == 'last_observed_focus'
                             for g in out['goal_tracking']['goals']))

    def test_ordered_adjacency_survives_an_unresolved_earlier_recurrence(self):
        run, actions, semantics = fixture('ABAB')
        actions[0]['order_known'] = False
        out = observe.analyze(run, semantics)
        tracking = out['goal_tracking']
        self.assertEqual([t['kind'] for t in tracking['transitions']],
                         ['focus_observed_order_unknown', 'first_focus', 'focus_reobserved', 'return'])
        self.assertEqual(out['metrics']['goal_returns'], 1)
        self.assertEqual(sum(e['count'] for e in tracking['graph']['edges']), 2)

    def test_direct_goal_tracking_uses_source_index_not_input_list_order(self):
        run, _, semantics = fixture()
        actions = observe.analyze(run, semantics)['actions']
        self.assertEqual(goals.track(run, actions), goals.track(run, list(reversed(actions))))

    def test_target_returns_and_repeat_runs_share_source_order(self):
        run, actions, semantics = fixture()
        actions[1]['order_known'] = False
        out = observe.analyze(run, semantics)
        self.assertEqual(out['metrics']['target_returns'], 0)
        self.assertEqual(out['actions'][2]['target_visit'], 'reobserved')
        # The last two ordered calls are still an identical, consecutive pair.
        self.assertEqual(out['metrics']['consecutive_repeats'], 1)
        actions[2]['order_known'] = False
        out = observe.analyze(run, semantics)
        self.assertEqual(out['metrics']['consecutive_repeats'], 0)
        self.assertEqual(out['metrics']['longest_identical_run'], 1)
        # Equality is a source fact even when temporal recurrence is unknown.
        self.assertEqual(out['metrics']['exact_repeats'], 2)

    def test_parallel_occurrence_of_same_focus_does_not_erase_ordered_endpoint(self):
        run, actions, semantics = fixture('ABAA')
        for e in actions[1:3]:
            e['parent_id'] = 'parallel-group'
            e['batch_size'] = 2
        out = observe.analyze(run, semantics)
        last = out['goal_tracking']['transitions'][-1]
        self.assertEqual(last['kind'], 'return')
        self.assertEqual(last['order_evidence']['endpoint_unit_ids'], [actions[0]['id'], actions[-1]['id']])
        self.assertEqual(out['metrics']['target_returns'], 1)

    def test_same_target_in_separate_sessions_is_not_a_return(self):
        run, actions, _ = fixture()
        actions[-1]['context_id'] = 'separate-session'
        out = observe.analyze(run)
        self.assertEqual(out['actions'][-1]['target_visit'], 'first')
        self.assertFalse(out['actions'][-1]['exact_repeat'])
        self.assertFalse(out['actions'][-1]['consecutive_repeat'])

    def test_long_run_removes_only_returns_crossing_unknown_order(self):
        steps = [{'step_id': 0, 'source': 'user', 'message': 'Inspect the parser and its tests.'}]
        for i in range(256):
            target = 'tests' if i % 4 == 1 else 'parser'
            steps.append({'step_id': i+1, 'source': 'agent', 'message': f'I will inspect the {target}.',
                'tool_calls': [{'tool_call_id': str(i), 'function_name': 'read_file',
                                'arguments': {'path': target+'.py'}}],
                'observation': {'results': [{'source_call_id': str(i), 'content': 'Recorded.'}]}})
        run = normalize({'schema_version': 'ATIF-v1.7', 'session_id': 'long-order-control',
                         'agent': {'name': 'test'}, 'steps': steps})[0]
        actions = [e for e in run['events'] if e['kind'] == 'action']
        plans = {g['text']: g['id'] for g in goals.catalog(run)['goals'] if g['kind'] == 'expressed_plan'}
        semantics = {}
        for i, action in enumerate(actions):
            text = 'I will inspect the tests.' if i % 4 == 1 else 'I will inspect the parser.'
            semantics[action['id']] = {'focus_goal': {'status': 'decided', 'value': plans[text]}}
        baseline = observe.analyze(run, semantics)
        self.assertEqual((baseline['metrics']['goal_returns'], baseline['metrics']['target_returns']), (127, 127))
        for i, action in enumerate(actions):
            if i % 16 == 1: action['order_known'] = False
        out = observe.analyze(run, semantics)
        self.assertEqual((out['metrics']['goal_returns'], out['metrics']['target_returns']), (80, 80))
        self.assertEqual({g['text']: g['returns'] for g in out['goal_tracking']['goals'] if g['kind']=='expressed_plan'},
                         {'I will inspect the parser.': 48, 'I will inspect the tests.': 32})
        self.assertEqual(out['metrics']['goal_assignments'], 256)
        self.assertEqual(out['goal_tracking']['coverage']['unordered_assignments'], 16)
        self.assertEqual(out['goal_tracking']['coverage']['unresolved_recurrences'], 32)
        self.assertEqual(sum(e['count'] for e in out['goal_tracking']['graph']['edges']), 223)
        self.assertEqual(sum(e['count'] for e in out['map']['edges']), 223)


if __name__ == '__main__':
    unittest.main()
