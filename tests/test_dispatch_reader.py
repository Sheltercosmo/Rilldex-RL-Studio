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
from tracker.dispatch_reading import Reader, collect, VERSION, PREVIEW_VERSION
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
        run, eid, rule = long_run()
        run['events'][0]['text'] = 'Other procedure. '*1000 + rule + 'Appendix. '*1000
        reader = Reader(run, eid)
        original = reader.request()
        with self.assertRaisesRegex(InputError, 'omitted|missing or ambiguous'):
            reader.advance({'finish': {'selections': [{'criterion': {'event_id': 'e1', 'quote': rule}, 'context': []}]}})
        self.assertEqual(reader.request(), original)
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        with self.assertRaisesRegex(InputError, 'missing or ambiguous'):
            reader.advance({'list': {'kind': 'all', 'offset': 0}, 'retain': [{'event_id': 'e1', 'quote': rule}]})
        self.assertEqual(reader.round, 1)

    def test_catalog_previews_expose_short_user_constraints_and_exact_long_record_gaps(self):
        messages = [{'role': 'system', 'content': 'Policy beginning. ' + '中🔎'*2000 + ' Policy ending.'}]
        messages += [{'role': 'user', 'content': f'Constraint {i}: do not change option {i}.'} for i in range(12)]
        messages += [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'type': 'function',
                     'function': {'name': 'dispatch', 'arguments': '{}'}}]}]
        run = normalize({'messages': messages})[0]
        eid = next(e['id'] for e in run['events'] if e.get('call_id') == 'a')
        reader = Reader(run, eid, max_bytes=16000)
        seen = set(); offset = 0
        while offset is not None:
            reader.advance({'list': {'kind': 'instructions', 'offset': offset}})
            request = reader.request()
            self.assertEqual(request['schema'], PREVIEW_VERSION)
            self.assertLessEqual(len(dumps(request).encode('utf8')), 16000)
            for event in request['prefix']:
                original = next(e for e in run['events'] if e['id'] == event['id'])
                for r in event['source_text_ranges']:
                    self.assertEqual(event['text'][r['view_start']:r['view_end']], original['text'][r['source_start']:r['source_end']])
                if original['actor'] == 'user':
                    self.assertEqual(event['text'], original['text']); seen.add(event['id'])
                if original['actor'] == 'system':
                    self.assertGreater(event['omitted_text_chars'], 0)
                    self.assertIn('Policy beginning.', event['text']); self.assertIn('Policy ending.', event['text'])
            offset = request['source_result']['next_offset']
        self.assertEqual(len(seen), 12)

    def test_catalog_preview_byte_fitting_does_not_read_embedded_media(self):
        run = fixture()
        run['events'][0]['text'] = 'Head.' + '界🔎'*1000 + 'data:image/png;base64,YQ==' + 'Tail.'
        reader = Reader(run, 'e3', max_bytes=8000)
        self.assertLessEqual(len(dumps(reader.request()).encode('utf8')), 8000)
        self.assertNotIn('YQ==', dumps(reader.request()['prefix']))
        event = next(e for e in reader.request()['prefix'] if e['id'] == 'e1')
        self.assertGreater(event['omitted_text_chars'], 0)
        reader.advance({'list': {'kind': 'all', 'offset': 0}, 'retain': [{'event_id': 'e1', 'quote': 'Head.'}]})
        self.assertLessEqual(len(dumps(reader.request()).encode('utf8')), 8000)

    def test_preview_offsets_and_native_meaning_survive_different_capture_routes(self):
        covered = set()
        for name, document in records().items():
            run = normalize(document)[0]
            actions = [e for e in run['events'] if e['kind']=='action' and e['actor']=='agent']
            if not actions: continue
            reader = Reader(run, actions[-1]['id'], max_bytes=32000)
            reader.advance({'list': {'kind': 'all', 'offset': 0}})
            events = {e['id']: e for e in run['events']}
            for e in reader.request()['prefix']:
                for r in e['source_text_ranges']:
                    self.assertEqual(events[e['id']]['text'][r['source_start']:r['source_end']],
                                     e['text'][r['view_start']:r['view_end']])
                if 'tool_contract' in events[e['id']]:
                    self.assertEqual(e['tool_contract'], events[e['id']]['tool_contract'])
            covered.add(name)
        self.assertEqual(covered, {'conversation','episode','airline-public','responses-items'})

    def test_real_coding_search_fits_native_definitions_and_exposes_deferred_records(self):
        fixtures = Path(__file__).parent/'fixtures'
        case = json.loads((fixtures/'dispatch_reader_budget_case.json').read_text(encoding='utf8'))
        run = normalize(json.loads((fixtures/case['source']['path']).read_text(encoding='utf8')))[0]
        self.assertEqual(digest(run), case['source_hash'])
        reader = Reader(run, case['event_id'], **case['settings'])
        larger = Reader(run, case['event_id'], **{**case['settings'], 'max_bytes':64000})
        for turn in case['turns']:
            self.assertEqual(digest(reader.request()), turn['request_hash'])
            reader.advance(turn['response']); larger.advance(turn['response'])
        request = reader.request()
        self.assertEqual(digest(request), case['fixed_request_hash'])
        self.assertLessEqual(len(dumps(request).encode('utf8')), 16000)
        self.assertGreater(len(dumps(larger.request()).encode('utf8')), 16000)
        deferred = request['source_result']['budget_deferred_ranges']
        self.assertTrue(deferred)
        key = lambda ref: (ref['event_id'],ref['start'],ref['end'])
        self.assertEqual({key(r) for r in [*reader.view,*deferred]}, {key(r) for r in larger.view})
        # A deferred hit remains readable; its definition is never clipped away.
        target = next(r for r in deferred if r['event_id']=='e106')
        reader.advance({'read': {'event_id':target['event_id'],'start':target['start']}, 'retain':[]})
        record = next(e for e in reader.request()['prefix'] if e['id']==target['event_id'])
        original = next(e for e in run['events'] if e['id']==target['event_id'])
        self.assertEqual(record['tool_contract'], original['tool_contract'])
        self.assertLessEqual(len(dumps(reader.request()).encode('utf8')), 16000)

    def test_caller_changes_do_not_rewrite_a_reading_in_progress(self):
        run = fixture(); reader = Reader(run, 'e3'); before = deepcopy(run)
        run['events'][0]['text'] = 'Changed after reader initialization.'
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        request = reader.request()
        self.assertEqual(request['source_hash'], digest(before))
        self.assertEqual(next(e['text'] for e in request['prefix'] if e['id'] == 'e1'), before['events'][0]['text'])

    def test_real_page_budget_failure_preserves_evidence_and_accepts_a_smaller_working_set(self):
        fixtures = Path(__file__).parent/'fixtures'
        case = json.loads((fixtures/'dispatch_reader_budget_case.json').read_text(encoding='utf8'))
        run = normalize(json.loads((fixtures/case['source']['path']).read_text(encoding='utf8')))[0]
        reader = Reader(run, case['event_id'], **case['settings'])
        turns = [*case['turns'], *case['page_budget_recovery']['turns']]
        for turn in turns[:-1]:
            self.assertEqual(digest(reader.request()), turn['request_hash'])
            reader.consume(turn['response'])
        failed = turns[-1]['response']; before = reader.request(); progress = reader.progress()
        self.assertEqual(digest(before), turns[-1]['request_hash'])
        with self.assertRaisesRegex(InputError, 'no room for a source page'):
            reader.advance(failed)
        reader.consume(failed, validate_only=True)
        self.assertEqual(reader.request(), before)
        self.assertEqual(reader.progress(), progress)
        reader.consume(failed)
        feedback = reader.request()
        self.assertEqual(digest(feedback), case['page_budget_recovery']['feedback_request_hash'])
        self.assertEqual(feedback['source_result']['operation_error']['arguments'], failed['read'])
        self.assertEqual(feedback['retained_quotes'], before['retained_quotes'])
        self.assertEqual(reader.round, len(turns))
        # Only the previously supplied page counts as read; the failed page does not.
        ranges = reader.progress()['source_ranges_presented']['e136']
        self.assertLessEqual(max(r['end'] for r in ranges), failed['read']['start'])
        reader.consume({'read': failed['read'], 'retain': failed['retain'][:1]})
        recovered = reader.request()
        self.assertNotIn('operation_error', recovered['source_result'])
        self.assertEqual(recovered['source_result']['start'], failed['read']['start'])
        self.assertGreater(recovered['source_result']['end'], failed['read']['start'])
        self.assertLessEqual(len(dumps(recovered).encode('utf8')), case['settings']['max_bytes'])
        source = next(e for e in run['events'] if e['id']=='e136')['text']
        record = next(e for e in recovered['prefix'] if e['id']=='e136')
        for r in record['source_text_ranges']:
            self.assertEqual(record['text'][r['view_start']:r['view_end']], source[r['source_start']:r['source_end']])

    def test_budget_feedback_obeys_worker_round_limit_and_replays_without_new_calls(self):
        fixtures = Path(__file__).parent/'fixtures'
        case = json.loads((fixtures/'dispatch_reader_budget_case.json').read_text(encoding='utf8'))
        run = normalize(json.loads((fixtures/case['source']['path']).read_text(encoding='utf8')))[0]
        turns = [*case['turns'], *case['page_budget_recovery']['turns']]
        responses = [turn['response'] for turn in turns]
        responses.append({'read': responses[-1]['read'], 'retain': responses[-1]['retain'][:1]})
        script = '''import json,sys
from pathlib import Path
request=json.load(sys.stdin)['request']
responses=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
print(json.dumps(responses[request['round']]))
'''
        with TemporaryDirectory() as temporary:
            root = Path(temporary); worker = root/'worker.py'; worker.write_text(script, encoding='utf8')
            proposals = root/'responses.json'; proposals.write_text(dumps(responses), encoding='utf8')
            provider = CommandCandidates(root/'provider', [sys.executable, str(worker), str(proposals)], 'scripted budget replay/1')
            settings = {**case['settings'], 'provider':provider}
            limited = collect(run, case['event_id'], root/'reading', max_rounds=6, **settings)
            self.assertEqual(limited['status'], 'round_limit')
            self.assertIn('operation_error', limited['request']['source_result'])
            self.assertEqual(provider.generation_calls, 6)
            self.assertEqual(collect(run, case['event_id'], root/'reading', max_rounds=6, **settings), limited)
            self.assertEqual(provider.generation_calls, 6)
            resumed = collect(run, case['event_id'], root/'reading', max_rounds=7, **settings)
            self.assertEqual(resumed['coverage']['rounds'], 7)
            self.assertNotIn('operation_error', resumed['request']['source_result'])
            self.assertEqual(resumed['request']['source_result']['start'], responses[-1]['read']['start'])
            self.assertEqual(provider.generation_calls, 7)
            self.assertEqual(collect(run, case['event_id'], root/'recovered', max_rounds=7, **settings), resumed)
            self.assertEqual(provider.generation_calls, 7)

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
            self.assertEqual(final['requests'][0]['state']['harness'], 'criterion-dispatch-review/2')
            self.assertEqual(final['requests'][0]['state']['source_context']['records'][0]['id'], 'e1')
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
            provider = CommandCandidates(root/'provider', [sys.executable, '-c', 'import sys; sys.stdin.read(); print("{}")'], 'invalid selector/1')
            with self.assertRaisesRegex(InputError, 'exactly one'):
                collect(fixture(), 'e3', root/'reading', provider=provider)
            with self.assertRaisesRegex(InputError, 'prior provider attempt'):
                collect(fixture(), 'e3', root/'reading', provider=provider)
            self.assertEqual(provider.generation_calls, 1)

    def test_existing_quote_only_sessions_resume_under_their_original_protocol(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary); run = fixture()
            first = collect(run, 'e3', root, record_context=False, protocol=VERSION)
            resumed = collect(run, 'e3', root)
            self.assertEqual(first, resumed)
            with self.assertRaisesRegex(InputError, 'changed'):
                collect(run, 'e3', root, record_context=True)
            collect(run, 'e3', root/'new')
            self.assertEqual(json.loads((root/'new/dispatch-reader.json').read_text(encoding='utf8'))['record_context'],
                             'criterion-dispatch-review/2')

    def test_smaller_decision_model_budget_is_respected_independently_of_reader_budget(self):
        run = fixture(); run['events'][0]['text'] = 'Inspect both sources. ' + 'Extra policy detail. '*1800
        reader = Reader(run, 'e3', max_bytes=12000, review_max_bytes=8000, page_chars=256)
        reader.advance({'read': {'event_id': 'e1', 'start': 0}})
        self.assertEqual(reader.request()['limits']['review_request_bytes'], 8000)
        reader.advance({'finish': {'selections': [{'criterion': {'event_id': 'e1', 'quote': 'Inspect both sources.'},
                                                  'context': []}]}})
        final = reader.result['requests'][0]
        self.assertLessEqual(len(dumps(final).encode('utf8')), 8000)
        self.assertEqual(final['state']['criterion']['text'], 'Inspect both sources.')
        self.assertEqual(final['state']['source_context']['not_included'][0]['event_id'], 'e1')

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
