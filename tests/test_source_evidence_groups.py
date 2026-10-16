"""Recorded dispatch context must survive missing prose without inventing links."""
from copy import deepcopy
import unittest

from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.schema import InputError
from tracker.source_evidence import search
from test_source_evidence import chat, records_by_id


def batched_run(commentary=''):
    return chat([
        {'role': 'assistant', 'content': commentary, 'tool_calls': [
            {'id': 'prepare', 'type': 'function', 'function': {
                'name': 'execute', 'arguments': '{"command":"construct implementation"}'}},
            {'id': 'inspect', 'type': 'function', 'function': {
                'name': 'execute', 'arguments': '{"command":"inspect quasarneedle"}'}}]},
        {'role': 'assistant', 'content': 'Review this work.'}])


def query(run, **extra):
    return dict(anchor={'event_id': run['events'][-1]['id']}, text='quasarneedle',
                strategy='source_and_calls', limit=1, **extra)


class DispatchGroupEvidenceTests(unittest.TestCase):
    def test_other_command_is_context_with_or_without_commentary(self):
        for commentary in ('', 'I will inspect this implementation.', 'Unrelated framing.'):
            with self.subTest(commentary=commentary):
                run = batched_run(commentary)
                before = deepcopy(run)
                actions = [e for e in run['events'] if e['kind'] == 'action']
                packet = search(run, query(run))
                self.assertEqual([m['event_id'] for m in packet['matches']], [actions[1]['id']])
                row = records_by_id(packet)[actions[0]['id']]
                reasons = [r for r in row['reasons'] if r['kind'] == 'recorded_dispatch_group']
                self.assertEqual(reasons, [dict(kind='recorded_dispatch_group',
                    of_event_id=actions[1]['id'], parent_event_id=actions[0]['parent_id'])])
                self.assertEqual(run, before)
                self.assertNotIn('relationship', row)
                self.assertNotIn('outcome', row)

    def test_source_search_does_not_gain_group_expansion(self):
        run = batched_run()
        packet = search(run, dict(query(run), strategy='source'))
        first = next(e for e in run['events'] if e['kind'] == 'action')
        self.assertNotIn(first['id'], records_by_id(packet))
        self.assertFalse(packet['dispatch_group_context']['enabled'])

    def test_invalid_parent_metadata_cannot_establish_group(self):
        for changes in ({'copied_context': True}, {'order_known': False},
                        {'agent_visibility': 'not_established'}, {'context_id': 'other'},
                        {'trajectory_id': 'other'}, {'actor': 'user'}, {'index': 100}):
            with self.subTest(changes=changes):
                run = batched_run()
                run['events'][0].update(changes)
                packet = search(run, query(run))
                self.assertFalse(any(reason['kind'] == 'recorded_dispatch_group'
                    for row in packet['records'] for reason in row['reasons']))

    def test_ineligible_sibling_cannot_be_reintroduced(self):
        for changes in ({'copied_context': True}, {'order_known': False},
                        {'agent_visibility': 'not_established'}, {'context_id': 'other'},
                        {'trajectory_id': 'other'}, {'index': 100}):
            with self.subTest(changes=changes):
                run = batched_run()
                first = next(e for e in run['events'] if e['kind'] == 'action')
                first.update(changes)
                packet = search(run, query(run))
                row = records_by_id(packet).get(first['id'], {})
                self.assertFalse(any(r['kind'] == 'recorded_dispatch_group' for r in row.get('reasons', [])))

    def test_selected_parallel_dispatch_does_not_observe_siblings(self):
        run = batched_run()
        actions = [e for e in run['events'] if e['kind'] == 'action']
        packet = search(run, dict(query(run), anchor={'event_id': actions[-1]['id']}, text='construct'))
        self.assertNotIn(actions[0]['id'], records_by_id(packet))
        self.assertIn(actions[0]['id'], packet['coverage']['excluded_not_visible_or_parallel'])

    def test_group_context_respects_page_budget_and_reports_omissions(self):
        run = batched_run()
        first = next(e for e in run['events'] if e['kind'] == 'action')
        first['text'] = 'Large implementation\n' + 'abcdef '*500
        packet = search(run, query(run, max_chars=2000))
        self.assertLessEqual(packet['coverage']['source_text_chars'], 2000)
        self.assertTrue(any(d['reason']['kind'] == 'recorded_dispatch_group'
                            for d in packet['coverage']['deferred']))
        for row in packet['records']:
            e = next(e for e in run['events'] if e['id'] == row['event_id'])
            for f in row['fragments']:
                self.assertEqual(f['text'], e['text'][f['start']:f['end']])

    def test_cursor_binds_empty_envelope_membership(self):
        run = batched_run()
        next(e for e in run['events'] if e['kind'] == 'action')['text'] += ' quasarneedle'
        first = search(run, query(run))
        cursor = first['pagination']['next_cursor']
        self.assertIsNotNone(cursor)
        # Empty envelope is not indexed text, but its grouping still changes
        # the context returned on a page and must invalidate continuation.
        changed = deepcopy(run)
        changed['events'][0]['copied_context'] = True
        with self.assertRaisesRegex(InputError, 'changed'):
            search(changed, dict(query(changed), cursor=cursor))

    def test_atif_multi_command_observation_stays_unattributed(self):
        run = normalize({'schema_version': 'ATIF-v1.2', 'session_id': 'recorded',
            'agent': {'name': 'terminal'}, 'steps': [
                {'step_id': 1, 'source': 'agent', 'message': '', 'tool_calls': [
                    {'tool_call_id': 'a', 'function_name': 'shell', 'arguments': {'command': 'construct implementation'}},
                    {'tool_call_id': 'b', 'function_name': 'shell', 'arguments': {'command': 'inspect quasarneedle'}}],
                 'observation': {'results': [{'content': 'Combined process output'}]}},
                {'step_id': 2, 'source': 'agent', 'message': 'Review work.'}]})[0]
        before = links(run)
        packet = search(run, query(run))
        self.assertEqual(links(run), before)
        self.assertEqual(before['records'], [])
        self.assertEqual(len(before['unlinked_ids']), 1)
        self.assertTrue(any(r['kind'] == 'recorded_dispatch_group'
                            for row in packet['records'] for r in row['reasons']))
        self.assertFalse(any(r['kind'] == 'recorded_response'
                             for row in packet['records'] for r in row['reasons']))


if __name__ == '__main__':
    unittest.main()
