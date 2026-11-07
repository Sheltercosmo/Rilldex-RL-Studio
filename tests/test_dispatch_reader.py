"""Bounded long-source reading through the real worker and workspace paths."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from rilldex import Workspace
from tracker.adapters import normalize
from tracker.candidate_worker import CommandCandidates
from tracker.criterion_review import selection_request, make_dispatch_request
from tracker.dispatch_reading import Reader, collect
from tracker.readable_context import resolve_quote
from tracker.schema import InputError, digest, dumps
from tracker.store import Store
from test_dispatch_context import fixture, span
from test_input_generalization import records


def long_run():
    rule = 'Freeze account A only when its current balance is zero. Exception: an active legal hold prohibits freezing.'
    messages = [
        {'role': 'system', 'content': 'Operations manual.\n' + 'Unrelated routing procedure.\n'*8000 + rule},
        {'role': 'user', 'content': 'Freeze account A.'},
        {'role': 'assistant', 'tool_calls': [{'id': 'old', 'type': 'function',
            'function': {'name': 'get_account', 'arguments': '{"id":"A"}'}}]},
        {'role': 'tool', 'tool_call_id': 'old', 'content': '{"id":"A","balance":0,"legal_hold":false}'},
        {'role': 'assistant', 'content': 'Waiting for the refreshed account record. ' + 'Background dispatch log.\n'*3000},
        {'role': 'assistant', 'tool_calls': [{'id': 'new', 'type': 'function',
            'function': {'name': 'get_account', 'arguments': '{"id":"A"}'}}]},
        {'role': 'tool', 'tool_call_id': 'new', 'content': '{"id":"A","balance":0,"legal_hold":true}'},
        {'role': 'assistant', 'tool_calls': [{'id': 'freeze', 'type': 'function',
            'function': {'name': 'freeze_account', 'arguments': '{"id":"A"}'}}]}]
    run = normalize({'messages': messages})[0]
    return run, next(e['id'] for e in run['events'] if e.get('call_id') == 'freeze'), rule


class DispatchReaderTests(unittest.TestCase):
    def test_large_prefix_is_searchable_without_clipping_the_rule_or_later_state(self):
        run, eid, rule = long_run()
        with self.assertRaisesRegex(InputError, 'byte budget'): selection_request(run, eid)
        reader = Reader(run, eid, max_bytes=12000, page_chars=512)
        for query in ['"Freeze account A"', '"legal_hold"']:
            reader.advance({'search': {'text': query}})
            request = reader.request()
            self.assertLessEqual(len(dumps(request).encode('utf8')), 12000)
            if query == '"Freeze account A"':
                term = resolve_quote(run, request['prefix'], {'event_id': 'e1', 'quote': rule})
                reader.advance({'read': {'event_id': 'e1', 'start': term['start']},
                                'retain': [{'event_id': 'e1', 'quote': rule}]})
        matches = [e for e in reader.request()['prefix'] if e['kind'] == 'feedback']
        self.assertTrue(any('"legal_hold":false' in e['text'] for e in matches))
        self.assertTrue(any('"legal_hold":true' in e['text'] for e in matches))
        reader.advance({'finish': {'selections': [{'criterion': {'event_id': 'e1', 'quote': rule},
            'context': [{'event_id': e['id'], 'quote': e['text']} for e in matches]}]}})
        self.assertEqual(reader.result['status'], 'ready_for_review')
        check = reader.result['requests'][0]
        self.assertEqual(check['state']['criterion']['text'], rule)
        self.assertEqual(len(check['state']['context']), 2)
        self.assertLess(reader.progress()['source_chars_presented'], 10000)
        self.assertNotIn('prediction', reader.result)

    def test_paged_reads_retain_adjacent_qualifiers_with_original_unicode_offsets(self):
        run = fixture(); run['events'][0]['text'] = '界🔎'*190 + 'Freeze only after approval.\nUnless a hold remains active.' + 'z'*600
        reader = Reader(run, 'e3', page_chars=400)
        reader.advance({'read': {'event_id': 'e1', 'start': 370}})
        request = reader.request()
        quote = 'Freeze only after approval.\nUnless a hold remains active.'
        bound = resolve_quote(run, request['prefix'], {'event_id': 'e1', 'quote': quote})
        self.assertEqual(bound['start'], 380)
        start = request['source_result']['next_start']
        reader.advance({'read': {'event_id': 'e1', 'start': start},
                        'retain': [{'event_id': 'e1', 'quote': quote}]})
        self.assertEqual(resolve_quote(run, reader.request()['prefix'], {'event_id': 'e1', 'quote': quote}), bound)
        self.assertTrue(all(e['text'][r['view_start']:r['view_end']] ==
            next(src for src in run['events'] if src['id'] == e['id'])['text'][r['source_start']:r['source_end']]
            for e in reader.request()['prefix'] for r in e['source_text_ranges']))

    def test_unseen_and_omitted_quotes_cannot_become_evidence(self):
        run, eid, rule = long_run(); reader = Reader(run, eid)
        original = reader.request()
        with self.assertRaisesRegex(InputError, 'omitted'):
            reader.advance({'finish': {'selections': [{'criterion': {'event_id': 'e1', 'quote': rule}, 'context': []}]}})
        self.assertEqual(reader.request(), original)
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        with self.assertRaisesRegex(InputError, 'missing or ambiguous'):
            reader.advance({'list': {'kind': 'all', 'offset': 0}, 'retain': [{'event_id': 'e1', 'quote': rule}]})
        self.assertEqual(reader.round, 1)

    def test_caller_changes_do_not_rewrite_a_reading_in_progress(self):
        run = fixture(); reader = Reader(run, 'e3'); before = deepcopy(run)
        run['events'][0]['text'] = 'Changed after reader initialization.'
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        request = reader.request()
        self.assertEqual(request['source_hash'], digest(before))
        self.assertEqual(next(e['text'] for e in request['prefix'] if e['id'] == 'e1'), before['events'][0]['text'])

    def test_no_future_hidden_reset_or_coissued_feedback_enters_prior_search(self):
        run = fixture(); run['events'][-1]['index'] = 2.5
        for field, value in [('agent_visible', False), ('agent_visibility', 'not_established'),
                             ('copied_context', True), ('context_id', 'elsewhere')]:
            other = deepcopy(run['events'][0]); other.update(id='excluded', text='EXCLUDED_SENTINEL', index=.5)
            other[field] = value; changed = {**run, 'events': [*run['events'], other]}
            reader = Reader(changed, 'e4')
            self.assertNotIn('excluded', reader.events)
            with self.assertRaisesRegex(InputError, 'outside'): reader.advance({'read': {'event_id': 'excluded', 'start': 0}})
            reader.advance({'search': {'text': 'EXCLUDED_SENTINEL source A'}})
            self.assertNotIn('source A', dumps(reader.request()['prefix']))
            self.assertNotIn('EXCLUDED_SENTINEL', dumps(reader.request()['prefix']))
            self.assertEqual(reader.dispatch['action_ids'], ['e3', 'e4'])

    def test_unestablished_current_order_cannot_treat_serialized_history_as_prior(self):
        run = fixture(); run['events'][2]['order_known'] = False
        reader = Reader(run, 'e3')
        self.assertEqual(reader.history, [])
        self.assertEqual({e['id'] for e in selection_request(run, 'e3')['prefix']}, {'e2', 'e3', 'e4'})
        with self.assertRaisesRegex(InputError, 'precede'): make_dispatch_request(run, 'e3', span(run, 'e1'))

    def test_recorded_operation_meaning_reaches_reader_and_decision_without_name_guessing(self):
        run = normalize(records()['responses-items'])[0]
        reader = Reader(run, 'e4')
        current = next(e for e in reader.request()['prefix'] if e['id'] == 'e4')
        self.assertIn('without changing it', current['tool_contract']['definition']['description'])
        term = next(e for e in run['events'] if e['kind'] == 'instruction')
        req = make_dispatch_request(run, 'e4', span(run, term['id']))
        self.assertEqual(req['state']['current_dispatch'][0]['tool_contract'], current['tool_contract'])
        action = next(e for e in run['events'] if e['id'] == 'e4')
        action['tool_contract']['definition']['image'] = 'data:image/png;base64,YQ=='
        current = next(e for e in Reader(run, 'e4').request()['prefix'] if e['id'] == 'e4')
        self.assertIn('UNOBSERVED MEDIA', current['tool_contract']['definition']['image'])
        self.assertEqual(current['unobserved_auxiliary_media'][0]['inspection'], 'not_decoded_or_visually_inspected')

    def test_search_paging_reaches_candidates_after_first_page(self):
        run = fixture()
        extra = []
        for i in range(15):
            e = deepcopy(run['events'][0]); e.update(id='history'+str(i), index=.01+i*.01,
                                                    text=f'account audit revision {i}')
            extra.append(e)
        run['events'].extend(extra)
        reader = Reader(run, 'e3')
        seen = set(); cursor = None
        for _ in range(10):
            reader.advance({'search': {'text': '"account audit"', **({'cursor': cursor} if cursor else {})}})
            seen |= {e['id'] for e in reader.request()['prefix'] if e['id'].startswith('history')}
            cursor = reader.operation['pagination']['next_cursor']
            if cursor is None: break
        self.assertEqual(seen, {'history'+str(i) for i in range(15)})

    def test_byte_budget_and_encoded_media_remain_explicit(self):
        run = fixture(); run['events'][0]['text'] = 'before data:image/png;base64,'+'YQ=='*300+' after'
        reader = Reader(run, 'e3')
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        self.assertNotIn('YQ==', dumps(reader.request()['prefix']))
        record = next(e for e in reader.request()['prefix'] if e['id'] == 'e1')
        self.assertGreater(record['omitted_text_chars'], 0)
        run = fixture(); run['events'][2]['text'] = '界'*10000
        with self.assertRaisesRegex(InputError, 'budget'): Reader(run, 'e3', max_bytes=8000)

    def test_read_page_adapts_to_utf8_bytes_without_skipping_source(self):
        run = fixture(); run['events'][0]['text'] = '🔎界\x01'*6000
        reader = Reader(run, 'e3', max_bytes=8000, page_chars=12000)
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        first = reader.operation['next_start']
        self.assertGreater(first, 0); self.assertLess(first, 12000)
        self.assertLessEqual(len(dumps(reader.request()).encode('utf8')), 8000)
        reader.advance({'read': {'event_id': 'e1', 'start': first}})
        self.assertEqual(reader.operation['start'], first)
        self.assertLessEqual(len(dumps(reader.request()).encode('utf8')), 8000)

    def test_real_worker_resume_preserves_quotes_and_does_not_repeat_generation(self):
        script = '''import json,sys
r=json.load(sys.stdin)['request']
if r['round']==0: result={'read':{'event_id':'e1','start':0}}
else:
    e=next(e for e in r['prefix'] if e['id']=='e1')
    result={'finish':{'selections':[{'criterion':{'event_id':'e1','quote':e['text']},'context':[]}]}}
print(json.dumps(result))
'''
        with TemporaryDirectory() as temporary:
            root = Path(temporary); worker = root/'worker.py'; worker.write_text(script, encoding='utf8')
            provider = CommandCandidates(root/'provider', [sys.executable, str(worker)], 'test selector/1')
            run = fixture(); kwargs = dict(provider=provider, model='local/decision')
            first = collect(run, 'e3', root/'reading', max_rounds=1, **kwargs)
            self.assertEqual(first['status'], 'round_limit'); self.assertEqual(provider.generation_calls, 1)
            final = collect(run, 'e3', root/'reading', max_rounds=2, **kwargs)
            self.assertEqual(final['status'], 'ready_for_review'); self.assertEqual(provider.generation_calls, 2)
            self.assertEqual(final['requests'][0]['model'], 'local/decision')
            self.assertEqual(collect(run, 'e3', root/'reading', max_rounds=20, **kwargs), final)
            self.assertEqual(provider.generation_calls, 2)
            # A new runner can recover worker responses saved before its own
            # progress write, without paying for identical provider requests.
            self.assertEqual(collect(run, 'e3', root/'recovered', max_rounds=20, **kwargs), final)
            self.assertEqual(provider.generation_calls, 2)
            with self.assertRaisesRegex(InputError, 'changed'):
                collect(run, 'e3', root/'reading', max_rounds=20, page_chars=500, **kwargs)

    def test_failed_worker_attempt_is_not_automatically_repeated_on_resume(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = CommandCandidates(root/'provider', [sys.executable, '-c', 'print("{}")'], 'invalid selector/1')
            with self.assertRaisesRegex(InputError, 'exactly one'):
                collect(fixture(), 'e3', root/'reading', provider=provider)
            with self.assertRaisesRegex(InputError, 'prior provider attempt'):
                collect(fixture(), 'e3', root/'reading', provider=provider)
            self.assertEqual(provider.generation_calls, 1)

    def test_workspace_file_queue_obeys_scope_and_accepts_exact_external_response(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary); store = Store(root/'workspace.sqlite'); run = fixture(); store.add([run])
            workspace = Workspace(store.path)
            first = workspace.select_dispatch_evidence(run['id'], 'e3', root/'reading')
            self.assertEqual(first['status'], 'needs_candidates')
            response = {'request_hash': first['request_hash'], 'read': {'event_id': 'e1', 'start': 0}}
            path = root/'reading/responses'/f"{first['request_hash']}.json"; path.parent.mkdir()
            path.write_text(dumps(response), encoding='utf8')
            second = workspace.select_dispatch_evidence(run['id'], 'e3', root/'reading')
            self.assertEqual(second['coverage']['rounds'], 1)
            self.assertNotEqual(first['request_hash'], second['request_hash'])
            with self.assertRaisesRegex(InputError, 'outside'):
                Workspace(store.path, experiment='not-this-run').select_dispatch_evidence(run['id'], 'e3', root/'other')
