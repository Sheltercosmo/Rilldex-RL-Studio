"""Source evidence retrieval stays bounded to an exact earlier visible prefix."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from rilldex import Workspace
from tracker import analysis_operations, graph_store, investigation_plans
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError, digest
from tracker.source_evidence import search
from tracker.store import Store


def chat(messages):
    return normalize(chat_document(messages))[0]


def basic_run():
    return normalize({'trajectory_format': 'devai/1', 'trajectory': [
        {'step': 0, 'user_message': 'Earlier note: quasarneedle was observed.',
         'agent': {'thought': 'I will inspect quasarneedle.', 'action': 'search quasarneedle'},
         'environment': 'quasarneedle result'},
        {'step': 1, 'user_message': 'Continue the task.',
         'agent': {'thought': 'The selected action is quasarneedle.', 'action': 'open quasarneedle'},
         'environment': 'opened quasarneedle'}]})[0]


def anchor(run, event_id='e7', **extra):
    return {'anchor': {'event_id': event_id, **extra}}


def records_by_id(result):
    return {r['event_id']: r for r in result['records']}


class SourceEvidenceTests(unittest.TestCase):
    def test_two_distant_matches_in_one_record_keep_both_original_passages(self):
        text = '🔎 checksum mismatch: primary shard.\n' + ('unrelated logging\n' * 550) + 'checksum mismatch: replica shard.'
        run = chat([{'role': 'assistant', 'content': text},
                    {'role': 'assistant', 'content': 'Inspect the earlier record.'}])
        event = run['events'][0]
        result = search(run, {**anchor(run, run['events'][-1]['id']), 'text': 'checksum mismatch', 'limit': 1})
        record = records_by_id(result)[event['id']]
        excerpts = '\n'.join(f['text'] for f in record['fragments'])
        self.assertIn('primary shard', excerpts)
        self.assertIn('replica shard', excerpts)
        self.assertGreater(len(record['fragments']), 1)
        self.assertLessEqual(sum(len(f['text']) for f in record['fragments']), 2400)
        for fragment in record['fragments']:
            self.assertEqual(fragment['text'], text[fragment['start']:fragment['end']])
        self.assertIn('matching_record_context', [r['kind'] for r in record['reasons']])

    def test_linked_long_response_keeps_end_after_setup_logs_without_calling_it_success(self):
        run = chat([
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': 'build-1', 'type': 'function',
                 'function': {'name': 'build_quasar', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'build-1',
             'content': 'Startup log\n' + 'setup detail\n' * 1500 + '\nCompilation failed: missing dependency.'},
            {'role': 'assistant', 'content': 'Review the build.'},
        ])
        result = search(run, {**anchor(run, run['events'][-1]['id']), 'text': 'build quasar', 'limit': 1})
        response = next(e for e in run['events'] if e['kind'] == 'feedback')
        record = records_by_id(result)[response['id']]
        excerpt = '\n'.join(f['text'] for f in record['fragments'])
        self.assertIn('Startup log', excerpt)
        self.assertIn('Compilation failed: missing dependency.', excerpt)
        self.assertEqual({r['kind'] for r in record['reasons']}, {'recorded_response'})
        self.assertNotIn('outcome', record)
        self.assertLessEqual(result['coverage']['source_text_chars'], 16000)

    def test_code_identifiers_are_searchable_without_rewriting_the_original_quote(self):
        run = chat([{'role': 'assistant', 'content': 'raise HTTPChecksumMismatchError(payload)'},
                    {'role': 'assistant', 'content': 'Inspect the earlier failure.'}])
        result = search(run, {**anchor(run, run['events'][-1]['id']), 'text': 'checksum mismatch'})
        self.assertEqual(result['matches'][0]['event_id'], run['events'][0]['id'])
        fragment = result['records'][0]['fragments'][0]
        self.assertEqual(fragment['text'], 'raise HTTPChecksumMismatchError(payload)')
        literal = search(run, {**anchor(run, run['events'][-1]['id']), 'text': 'httpchecksummismatcherror'})
        self.assertEqual(literal['matches'][0]['event_id'], run['events'][0]['id'])

    def test_media_only_request_does_not_create_an_empty_evidence_card(self):
        run = basic_run()
        run['events'][0]['text'] = 'data:image/png;base64,QUJD'
        result = search(run, {**anchor(run), 'text': 'quasarneedle'})
        self.assertNotIn(run['events'][0]['id'], records_by_id(result))
        self.assertTrue(all(record['fragments'] for record in result['records']))
        self.assertIn(run['events'][0]['id'], result['coverage']['omitted_request_event_ids'])

    def test_only_earlier_same_trajectory_events_can_match_or_change_rank(self):
        run = basic_run()
        baseline = search(run, {**anchor(run), 'text': 'quasarneedle'})
        eligible_hit_ids = {hit['event_id'] for hit in baseline['matches']}
        self.assertIn('e1', eligible_hit_ids)
        self.assertTrue(all(run_event['index'] < 6 for run_event in run['events']
                            if run_event['id'] in eligible_hit_ids))

        contaminated = deepcopy(run)
        future = deepcopy(run['events'][0])
        future.update(id='future-match', index=100, trajectory_id='main',
                      source_pointer='/future', text='quasarneedle future duplicate')
        other = deepcopy(run['events'][0])
        other.update(id='other-match', index=101, trajectory_id='parallel',
                     source_pointer='/parallel', text='quasarneedle other trajectory')
        contaminated['events'].extend([future, other])
        changed = search(contaminated, {**anchor(contaminated), 'text': 'quasarneedle'})
        self.assertEqual([(m['event_id'], m['rank']) for m in changed['matches']],
                         [(m['event_id'], m['rank']) for m in baseline['matches']])
        self.assertNotIn('future-match', records_by_id(changed))
        self.assertNotIn('other-match', records_by_id(changed))

    def test_same_event_anchor_searches_only_before_selected_start(self):
        run = basic_run()
        selected = 'selectedneedle'
        event = run['events'][-1]
        event['text'] = 'prefixneedle then ' + selected
        start = event['text'].index(selected)
        found = search(run, {'anchor': {'event_id': event['id'], 'start': start,
                                         'end': start + len(selected)}, 'text': 'prefixneedle'})
        own = next(m for m in found['matches'] if m['event_id'] == event['id'])
        self.assertLessEqual(own['end'], start)
        absent = search(run, {'anchor': {'event_id': event['id'], 'start': start,
                                          'end': start + len(selected)}, 'text': selected})
        self.assertNotIn(event['id'], {m['event_id'] for m in absent['matches']})

    def test_not_visible_and_parallel_sibling_calls_are_excluded(self):
        run = basic_run()
        anchor_event = run['events'][-2]  # selected action e7
        run['events'][0]['agent_visibility'] = 'not_established'
        sibling = deepcopy(anchor_event)
        sibling.update(id='parallel-sibling', index=5.5, text='quasarneedle sibling',
                       parent_id=anchor_event['parent_id'], source_pointer='/sibling')
        run['events'].append(sibling)
        result = search(run, {**anchor(run, anchor_event['id']), 'text': 'quasarneedle'})
        self.assertIn('e1', result['coverage']['excluded_not_visible_or_parallel'])
        self.assertIn('parallel-sibling', result['coverage']['excluded_not_visible_or_parallel'])
        self.assertNotIn('e1', records_by_id(result))
        self.assertNotIn('parallel-sibling', records_by_id(result))

    def test_empty_and_nonmatching_queries_do_not_create_lexical_hits(self):
        run = normalize({'trajectory_format': 'devai/1', 'trajectory': [
            {'step': 0, 'agent': {'thought': 'Earlier source text.', 'action': 'advance'},
             'environment': 'A recorded response.'},
            {'step': 1, 'agent': {'thought': 'Anchor text.', 'action': 'finish'}}]})[0]
        for text in ('the and is', 'neverpresentquasar'):
            result = search(run, {**anchor(run, 'e5'), 'text': text})
            self.assertEqual(result['matches'], [])
            self.assertEqual(result['coverage']['retained_matches'], 0)

    def test_encoded_media_is_excluded_and_offsets_remain_original(self):
        run = basic_run()
        event = run['events'][0]
        media = 'data:image/png;base64,QUJDREVGRw=='
        event['text'] = 'beforetoken ' + media + ' aftertoken'
        expected_start = event['text'].index('aftertoken')
        result = search(run, {**anchor(run), 'text': 'aftertoken'})
        record = records_by_id(result)[event['id']]
        fragment = next(f for f in record['fragments'] if 'aftertoken' in f['text'])
        # Retained chunks begin at the first readable offset after the media;
        # whitespace following the URI is therefore part of that source span.
        self.assertEqual(fragment['start'], event['text'].index(media) + len(media))
        self.assertEqual(fragment['text'].lstrip(), 'aftertoken')
        self.assertNotIn('data:image', str(result['records']))

    def test_text_budget_reports_deferred_matches(self):
        messages = []
        for i in range(3):
            messages.extend([
                {'role': 'assistant', 'content': 'quasarbudget ' + ('x' * 1150)},
                {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'id': f'call-{i}', 'type': 'function',
                     'function': {'name': 'read', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': f'call-{i}', 'content': 'response'}])
        messages.append({'role': 'assistant', 'content': 'Anchor now.'})
        run = chat(messages)
        result = search(run, {**anchor(run, run['events'][-1]['id']),
                              'text': 'quasarbudget', 'max_chars': 2000})
        self.assertGreaterEqual(len(result['matches']), 1)
        self.assertTrue(result['coverage']['deferred'])
        self.assertTrue(all(d['cause'] == 'text_budget' for d in result['coverage']['deferred']))
        self.assertLessEqual(result['coverage']['source_text_chars'], 2000)

    def test_anchor_and_query_validation(self):
        run = basic_run()
        bad_queries = [
            {}, {'anchor': {'event_id': ''}}, {'anchor': {'event_id': 'e7', 'start': -1}},
            {'anchor': {'event_id': 'e7', 'start': True}}, {'anchor': {'event_id': 'e7'}, 'extra': 1},
            {'anchor': {'event_id': 'missing'}}, {'anchor': {'event_id': 'e7', 'start': 4, 'end': 4}},
            {'anchor': {'event_id': 'e7'}, 'text': '   '},
            {'anchor': {'event_id': 'e7'}, 'limit': True},
            {'anchor': {'event_id': 'e7'}, 'max_chars': 1999},
        ]
        for query in bad_queries:
            with self.subTest(query=query), self.assertRaises(InputError):
                search(run, query)
        media_run = deepcopy(run)
        media_run['events'][-2]['text'] = 'data:image/png;base64,QUJD'
        with self.assertRaises(InputError):
            search(media_run, anchor(media_run, media_run['events'][-2]['id']))

    def test_native_call_response_and_adjacent_prose_are_context_not_semantics(self):
        run = chat([
            {'role': 'assistant', 'content': 'I will inspect nebula evidence.'},
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': 'lookup-1', 'type': 'function',
                 'function': {'name': 'lookup', 'arguments': '{"q":"nebula"}'}}]},
            {'role': 'tool', 'tool_call_id': 'lookup-1', 'content': 'nebula result: found.'},
            {'role': 'assistant', 'content': 'Finished.'},
        ])
        # The empty assistant envelope has no useful text and is not needed to
        # establish the exact native action/response correspondence.
        run['events'] = [e for e in run['events'] if e['text'] or e['kind'] != 'message']
        for index, event in enumerate(run['events']): event['index'] = index
        before = deepcopy(run)
        result = search(run, {**anchor(run, run['events'][-1]['id']), 'text': 'nebula'})
        by_id = records_by_id(result)
        action = next(e for e in run['events'] if e['kind'] == 'action')
        response = next(e for e in run['events'] if e['kind'] == 'feedback')
        prose = next(e for e in run['events'] if e['kind'] == 'message' and e['text'])
        self.assertIn('recorded_dispatch', [r['kind'] for r in by_id[action['id']]['reasons']])
        self.assertIn('recorded_response', [r['kind'] for r in by_id[response['id']]['reasons']])
        self.assertIn('preceding_source_record', [r['kind'] for r in by_id[prose['id']]['reasons']])
        self.assertNotIn('semantic_relation', result)
        self.assertNotIn('causal_claim', result)
        self.assertIn('not a semantic relationship', result['boundary'])
        self.assertEqual(run, before)

        contaminated = deepcopy(run)
        future_response = deepcopy(response)
        future_response.update(id='future-response', index=100, text='nebula future response',
                               source_pointer='/future', trajectory_id='main')
        cross_trajectory = deepcopy(response)
        cross_trajectory.update(id='cross-response', index=101, text='nebula cross response',
                                source_pointer='/cross', trajectory_id='other')
        contaminated['events'].extend([future_response, cross_trajectory])
        changed = search(contaminated, {**anchor(contaminated, contaminated['events'][-3]['id']),
                                        'text': 'nebula'})
        self.assertEqual([(m['event_id'], m['rank']) for m in changed['matches']],
                         [(m['event_id'], m['rank']) for m in result['matches']])
        self.assertEqual({r['event_id']: r['reasons'] for r in changed['records']},
                         {r['event_id']: r['reasons'] for r in result['records']})
        self.assertNotIn('future-response', records_by_id(changed))
        self.assertNotIn('cross-response', records_by_id(changed))

    def test_repeated_prose_cannot_crowd_all_matching_actions_and_results_out(self):
        messages = [
            {'role': 'assistant', 'content': f'Needle summary {i}: recorded repeated explanation.'}
            for i in range(12)
        ]
        for i in range(4):
            messages.extend([
                {'role': 'assistant', 'content': '', 'tool_calls': [{
                    'id': f'needle-call-{i}', 'type': 'function',
                    'function': {'name': 'needle_action', 'arguments': '{"query":"needle"}'},
                }]},
                {'role': 'tool', 'tool_call_id': f'needle-call-{i}',
                 'content': f'Needle result {i}: recorded response.'},
            ])
        messages.append({'role': 'assistant', 'content': 'Anchor after the needle evidence.'})
        run = chat(messages)
        result = search(run, {**anchor(run, run['events'][-1]['id']), 'text': 'needle'})
        lexical_ids = {match['event_id'] for match in result['matches']}
        matching_actions = {event['id'] for event in run['events']
                            if event['kind'] == 'action' and 'needle' in event['text'].lower()}
        matching_feedback = {event['id'] for event in run['events']
                             if event['kind'] == 'feedback' and 'needle' in event['text'].lower()}
        self.assertGreaterEqual(len(lexical_ids & matching_actions), 2)
        self.assertGreaterEqual(len(lexical_ids & matching_feedback), 2)
        self.assertLessEqual(len(result['matches']), 8)

    def test_workspace_search_is_live_and_respects_rollout_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'live.sqlite')
            run = basic_run()
            run['metadata'] = {'experiment': 'scoped'}
            store.add([run])
            workspace = Workspace(store.path, experiment='scoped')
            result = workspace.search_evidence(run['id'], anchor={'event_id': 'e7'}, text='quasarneedle')
            self.assertTrue(result['matches'])
            grouped = workspace.search_evidence(run['id'], anchor={'event_id': 'e7'}, questions=[
                dict(id='receipt', text='quasarneedle', source_types=['feedback'])])
            self.assertEqual(grouped['questions'][0]['status'], 'candidates_retained')
            with self.assertRaises(InputError):
                Workspace(store.path, experiment='other').search_evidence(
                    run['id'], anchor={'event_id': 'e7'}, text='quasarneedle')

    def test_registry_plan_replay_preserves_source_graph_and_creates_no_semantic_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'live.sqlite')
            run = basic_run()
            store.add([run])
            graph = graph_store.build(run)
            with store.connect() as c:
                graph_store.save(c, graph)
                before_graphs = c.execute('SELECT id,document FROM rollout_graphs ORDER BY id').fetchall()
            plan = analysis_operations.REGISTRY.projection_plan('evidence_search', {
                'run_id': run['id'], 'source_hash': digest(run),
                'query': {'anchor': {'event_id': 'e7'}, 'text': 'quasarneedle'},
            }, schema=investigation_plans.VERSION)
            result = investigation_plans.execute(store, plan)
            self.assertIn('matches', result['outputs']['observation'])
            with store.connect() as c:
                after_graphs = c.execute('SELECT id,document FROM rollout_graphs ORDER BY id').fetchall()
                self.assertEqual(before_graphs, after_graphs)
                self.assertEqual(c.execute('SELECT count(*) FROM graph_edges').fetchone()[0], len(graph['edges']))


if __name__ == '__main__':
    unittest.main()
