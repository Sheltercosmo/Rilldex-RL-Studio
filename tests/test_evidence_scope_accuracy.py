"""Recorded sessions must agree across maps, retrieval and metric witnesses."""
from copy import deepcopy
import unittest

from tracker import capabilities, graph_store, history_evidence, feedback_assessment, observe, rollout_metrics
from test_history_evidence import body, query, source


class RecordedScopeAccuracyTests(unittest.TestCase):
    def test_reused_call_ids_in_separate_sessions_keep_both_native_links(self):
        run = source([('lookup', {'account': 'A'}, body()),
                      ('lookup', {'account': 'A'}, body(False))])
        for index, event in enumerate(run['events']):
            event['context_id'] = 'session-' + str(index // 2)
            event['call_id' if event['kind'] == 'action' else 'source_call_id'] = 'call-1'
        linked = capabilities.links(run)
        self.assertEqual([(r['action_id'], r['feedback_id']) for r in linked['records']],
                         [('e1', 'e2'), ('e3', 'e4')])
        graph = graph_store.build(run)
        self.assertEqual({(e['source'], e['target']) for e in graph['edges'] if e['type'] == 'response_to'},
                         {('event:e2', 'event:e1'), ('event:e4', 'event:e3')})

    def test_foreign_session_feedback_never_becomes_a_native_response(self):
        for by_call_id in (True, False):
            run = source([('lookup', {'account': 'A'}, body())])
            run['events'][0]['context_id'] = 'first'
            run['events'][1]['context_id'] = 'second'
            if not by_call_id:
                run['events'][1].pop('source_call_id')
                run['events'][1]['related_action_ids'] = ['e1']
            self.assertEqual(capabilities.links(run)['records'], [])

    def test_prior_action_and_batch_counts_use_recorded_session(self):
        run = source([('lookup', {'account': 'A'}, body()),
                      ('use', {'account': 'A', 'ids': ['x']}, None)])
        for event in run['events']:
            event['context_id'] = 'second' if event['id'] == 'e3' else 'first'
        support = capabilities.feedback_support(run, run['events'][-1])
        self.assertEqual(support['status'], 'not_applicable')
        self.assertIsNone(support['prior_action_id'])

    def test_history_cannot_verify_a_dispatch_from_another_session(self):
        run = source([('lookup', {'account': 'A'}, body()),
                      ('use', {'account': 'A', 'ids': ['x']}, None)])
        for event in run['events']:
            event['context_id'] = 'second' if event['id'] == 'e3' else 'first'
        result = history_evidence.evaluate(run, query())
        self.assertIsNone(result['observations'][0]['value'])
        self.assertEqual(result['metrics']['denominator'], 0)

    def test_foreign_session_revocation_does_not_invalidate_local_lookup(self):
        run = source([('lookup', {'account': 'A'}, body()),
                      ('revoke', {'account': 'A'}, None),
                      ('use', {'account': 'A', 'ids': ['x']}, None)])
        for event in run['events']:
            event['context_id'] = 'foreign' if event.get('tool') == 'revoke' else 'local'
        result = history_evidence.evaluate(run, query())
        self.assertIs(result['observations'][0]['value'], True)

    def test_feedback_predecessor_uses_recorded_order_not_storage_order(self):
        run = source([('lookup', {'account': 'A'}, body()),
                      ('use', {'account': 'A', 'ids': ['x']}, None)])
        expected = capabilities.feedback_support(run, run['events'][-1])
        reordered = deepcopy(run)
        reordered['events'] = list(reversed(reordered['events']))
        actual = capabilities.feedback_support(reordered, run['events'][-1])
        self.assertEqual(actual, expected)

    def test_feedback_assessment_does_not_borrow_another_sessions_reaction(self):
        from test_feedback_assessment import fixture
        run = fixture()
        for event in run['events']:
            event['context_id'] = 'first' if event['index'] < 2 else 'second'
        window = feedback_assessment.windows(run)[0]
        self.assertEqual(window['expressions'], [])
        self.assertFalse(window['closed'])
        self.assertIsNone(window['boundary'])

    def test_parent_ids_are_not_parallel_batches_across_sessions(self):
        run = source([('lookup', {'account': 'A'}, body()),
                      ('lookup', {'account': 'A'}, body())])
        for i, event in enumerate(run['events']):
            event['context_id'] = 'session-' + str(i // 2)
            if event['kind'] == 'action':
                event['parent_id'] = 'message-1'
        linked = capabilities.links(run)
        self.assertEqual(list(linked['batch_sizes'].values()), [1, 1])
        self.assertTrue(all(w['structural_unknown'] is None for w in feedback_assessment.windows(run)))
        for event in run['events']:
            event['context_id'] = 'same'
        self.assertTrue(all(w['structural_unknown'] is not None for w in feedback_assessment.windows(run)))

    def two_session_run(self, tools):
        from test_source_evidence import chat
        messages = []
        for i, tool in enumerate(tools):
            messages.extend([
                {'role':'assistant','content':'', 'tool_calls':[{'id':str(i),'type':'function',
                  'function':{'name':tool,'arguments':'{"path":"item.txt"}'}}]},
                {'role':'tool','tool_call_id':str(i),'content':'Recorded.'}])
        run=chat(messages)
        for event in run['events']:
            event['context_id']='first' if event['index'] < 3 else 'second'
            if event['kind']=='action': event['parent_id']='message-1'
        return run

    def test_metrics_do_not_turn_independent_sessions_into_retry_or_transition(self):
        run=self.two_session_run(['write_file','write_file'])
        analysis=observe.analyze(run)
        self.assertEqual(analysis['metrics']['exact_repeats'],0)
        self.assertEqual(analysis['metrics']['consecutive_repeats'],0)
        self.assertEqual(analysis['sequence']['summary']['possible_pairs'],0)
        self.assertEqual(len(analysis['episodes']),2)
        self.assertEqual(analysis['map']['edges'],[])
        self.assertEqual(len(analysis['map']['nodes']),2)
        metric=rollout_metrics.source_record(run)['metrics']['exact_dispatch_repeat_rate']
        self.assertEqual((metric['numerator'],metric['denominator']),(0,2))

    def test_a_check_in_another_session_does_not_close_prior_unchecked_work(self):
        run=self.two_session_run(['write_file','run_tests'])
        tails=observe.analyze(run)['verification']['actor_tails']
        self.assertEqual([(t['context_id'],t['status']) for t in tails],
                         [('first','no_check_observed'),('second','no_later_application_observed')])
        self.assertTrue(all(not t['unresolved_event_ids'] for t in tails))

    def test_goals_and_model_input_use_the_current_sessions_objective(self):
        from tracker import goals, jev
        from test_source_evidence import chat
        messages=[]
        for i, task in enumerate(['First session secret objective.', 'Current session objective.']):
            messages.extend([
                dict(role='user',content=task),
                dict(role='assistant',content='We will inspect the record.',tool_calls=[
                    dict(id=str(i),type='function',function=dict(name='read_file',arguments='{}'))]),
                dict(role='tool',tool_call_id=str(i),content='Recorded feedback.')])
        run=chat(messages)
        for event in run['events']:
            event['context_id']='first' if event['index'] < 4 else 'second'
        action=next(e for e in reversed(run['events']) if e['kind']=='action')
        packet=jev.packet(run,action['id'])
        from tracker.schema import dumps
        self.assertNotIn('First session secret objective',dumps(packet))
        self.assertIn('Current session objective',dumps(packet))
        self.assertEqual(packet['state']['prior_actions'],[])
        candidates=goals.focus_candidates(run,action)
        self.assertTrue(all(g['context_id']=='second' for g in candidates['candidates']))
        self.assertEqual(len(goals.catalog(run)['context_roots']),2)
        self.assertEqual(observe.analyze(run)['actions'][-1]['goal_id'],candidates['root_id'])

    def test_a_future_instruction_cannot_supply_the_current_root(self):
        from tracker import goals, jev
        from test_source_evidence import chat
        run=chat([dict(role='assistant',content='',tool_calls=[
            dict(id='a',type='function',function=dict(name='read_file',arguments='{}'))]),
            dict(role='user',content='FUTURE OBJECTIVE')])
        action=next(e for e in run['events'] if e['kind']=='action')
        self.assertIsNone(goals.focus_candidates(run,action)['root_id'])
        self.assertTrue(jev.packet(run,action['id'])['state']['missingness']['objective_missing'])

    def test_saved_summary_refreshes_on_read_without_model_calls_or_source_edits(self):
        import tempfile
        import json
        from pathlib import Path
        from tracker.store import Store
        from tracker.schema import dumps
        for entry in ('get','list'):
            with tempfile.TemporaryDirectory() as folder:
                store=Store(Path(folder)/'workspace.sqlite')
                run=self.two_session_run(['write_file','write_file'])
                store.add([run])
                old=observe.analyze(run);old['harness_version']='macro/0.8.0'
                old['metrics']['exact_repeats']=1
                with store.connect() as c:
                    c.execute('UPDATE runs SET analysis=? WHERE id=?',(dumps(old),run['id']))
                if entry=='get': store.get(run['id'])
                else: store.list()
                with store.connect() as c:
                    row=c.execute('SELECT document,analysis FROM runs WHERE id=?',(run['id'],)).fetchone()
                    self.assertEqual(json.loads(row['document']),run)
                    self.assertEqual(json.loads(row['analysis'])['metrics']['exact_repeats'],0)
                    self.assertEqual(json.loads(row['analysis'])['harness_version'],observe.HARNESS_VERSION)
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM observations').fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
