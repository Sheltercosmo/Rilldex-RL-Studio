"""Native dispatch structure and source-bound criteria across capture formats."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tracker.action_context import native_dispatch
from tracker.adapters import normalize
from tracker.criterion_review import make_dispatch_request, resolve_dispatch, selection_request, bind_selections
from tracker.candidate_worker import CommandCandidates
from tracker.schema import InputError, digest
from test_input_generalization import records


def fixture():
    return normalize({'messages': [
        {'role': 'user', 'content': 'Inspect both sources, then tell me the result.'},
        {'role': 'assistant', 'content': 'Inspecting both sources.', 'tool_calls': [
            {'id': 'a', 'type': 'function', 'function': {'name': 'read_a', 'arguments': '{}'}},
            {'id': 'b', 'type': 'function', 'function': {'name': 'read_b', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'a', 'content': 'source A'}]})[0]


def span(run, eid, start=0, end=None):
    e = next(e for e in run['events'] if e['id'] == eid)
    end = len(e['text']) if end is None else end
    return {'event_id': eid, 'start': start, 'end': end, 'text': e['text'][start:end],
            'source_pointer': e['source_pointer']}


class DispatchContextTests(unittest.TestCase):
    def test_native_siblings_and_parent_remain_coissued_from_either_call(self):
        run = fixture(); before = deepcopy(run)
        for selected in ('e3', 'e4'):
            dispatch = native_dispatch(run, selected)
            self.assertEqual(dispatch['action_ids'], ['e3', 'e4'])
            self.assertEqual(dispatch['message_with_text_ids'], ['e2'])
            request = make_dispatch_request(run, selected, span(run, 'e1'), context=[span(run, 'e4'), span(run, 'e2')])
            self.assertEqual([x['timing'] for x in request['state']['context']], ['co-issued', 'co-issued'])
            self.assertEqual(request['state']['coissued_messages'][0]['id'], 'e2')
            self.assertEqual(request['state']['current_dispatch'][0]['parent_id'], 'e2')
            self.assertEqual(request['state']['cutoff_event_id'], 'e4')
            self.assertNotIn('source A', str(request))
        self.assertEqual(run, before)

    def test_nearby_results_never_become_prior_evidence_for_a_dispatch_sibling(self):
        run = fixture()
        # An exporter interleaves a result between serialized co-issued calls.
        run['events'][-1]['index'] = 2.5
        with self.assertRaisesRegex(InputError, 'precede the native message'):
            make_dispatch_request(run, 'e4', span(run, 'e1'), context=[span(run, 'e5')])

    def test_visibility_and_native_lane_keep_equal_ids_from_joining_contexts(self):
        for field, value in [('context_id', 'another'), ('trajectory_id', 'another'),
                             ('copied_context', True), ('agent_visible', False),
                             ('agent_visibility', 'not_established')]:
            run = fixture(); run['events'][3][field] = value
            self.assertEqual(native_dispatch(run, 'e3')['action_ids'], ['e3'])
            with self.assertRaises(InputError):
                make_dispatch_request(run, 'e3', span(run, 'e1'), context=[span(run, 'e4')])

    def test_missing_members_and_empty_parent_are_preserved_without_invented_calls(self):
        run = fixture(); run['events'][1]['text'] = ''; run['events'][2]['batch_size'] = 3
        dispatch = native_dispatch(run, 'e3')
        self.assertEqual(dispatch['declared_members_missing'], 1)
        self.assertEqual(dispatch['message_ids'], ['e2'])
        self.assertEqual(dispatch['message_with_text_ids'], [])
        request = make_dispatch_request(run, 'e3', span(run, 'e1'))
        self.assertEqual(request['state']['coissued_messages'][0]['text'], '')
        self.assertEqual(request['state']['missingness']['declared_dispatch_members_missing'], 1)

    def test_source_metadata_and_excerpt_coverage_cannot_be_generated(self):
        run = fixture(); term = span(run, 'e1')
        request = make_dispatch_request(run, 'e3', term, context=[span(run, 'e1', 0, 12)])
        self.assertEqual(request['state']['criterion']['excerpt'], 'whole recorded event')
        self.assertEqual(request['state']['context'][0]['excerpt'], 'selected range')
        self.assertEqual(request['state']['context'][0]['timing'], 'prior')
        for ref in [dict(term, text='guessed'), dict(term, source_pointer='/invented')]:
            with self.assertRaises(InputError): make_dispatch_request(run, 'e3', ref)
        with self.assertRaisesRegex(InputError, 'recorded instruction'):
            make_dispatch_request(run, 'e3', span(run, 'e2'))
        with self.assertRaisesRegex(InputError, 'Duplicate'):
            make_dispatch_request(run, 'e3', term, context=[term, term])
        with patch('tracker.criterion_review.MAX_BYTES', 10), self.assertRaisesRegex(InputError, 'byte budget'):
            make_dispatch_request(run, 'e3', term)

    def test_local_or_api_decisions_use_the_same_supplied_choices_and_argmax(self):
        request = make_dispatch_request(fixture(), 'e3', span(fixture(), 'e1'), model='local/custom-choice-model')
        response = {'model': request['model'], 'answers': {'alignment': {'type': 'choice', 'choice': 'consistent',
            'probabilities': {'consistent': .1, 'conflict': .1, 'not_applicable': .1, 'unresolved': .7}}}}
        result = resolve_dispatch(request, response)
        self.assertEqual(result['reading']['value'], 'unresolved')
        self.assertEqual(result['request_hash'], digest(request))
        with self.assertRaises(InputError): resolve_dispatch(request, dict(response, model='wrong'))

    def test_shared_capture_formats_expose_only_recorded_action_groups(self):
        covered = set()
        for name, document in records().items():
            run = normalize(document)[0]
            events = {e['id']: e for e in run['events']}
            for action in events.values():
                if action['kind'] != 'action' or action['actor'] != 'agent' or action.get('copied_context'):
                    continue
                dispatch = native_dispatch(run, action['id']); covered.add(name)
                for eid in dispatch['action_ids']:
                    self.assertEqual(events[eid]['kind'], 'action')
                    self.assertEqual(events[eid]['trajectory_id'], action['trajectory_id'])
                    self.assertEqual(events[eid].get('context_id'), action.get('context_id'))
                self.assertTrue(all(events[eid]['kind'] == 'message' for eid in dispatch['message_ids']))
        self.assertTrue({'conversation', 'episode', 'airline-public', 'responses-items'} <= covered)

    def test_existing_local_or_api_candidate_worker_binds_exact_quotes_before_decisions(self):
        run = fixture(); req = selection_request(run, 'e3')
        self.assertNotIn('source A', str(req))
        script = '''import json,sys,os
assert 'JEV_API_KEY' not in os.environ
r=json.load(sys.stdin)['request']
term=next(e for e in r['prefix'] if e['kind']=='instruction')
print(json.dumps({'selections':[{'criterion':{'event_id':term['id'],'quote':term['text']},'context':[]}]}))
'''
        with TemporaryDirectory() as directory:
            path = Path(directory)/'select.py'; path.write_text(script, encoding='utf8')
            provider = CommandCandidates(Path(directory)/'worker', [sys.executable, str(path)], 'test local selector',
                                         citation_format='source-quotes/1')
            with patch.dict('os.environ', {'JEV_API_KEY': 'not-for-generator'}):
                response = provider.generate(run, req, validator=lambda body: bind_selections(run, req, body))
            checks = bind_selections(run, req, response, model='custom/decision')
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]['model'], 'custom/decision')
            self.assertEqual(checks[0]['state']['criterion']['text'], run['events'][0]['text'])
            receipt = json.loads(next((Path(directory)/'worker/receipts').glob('*.json')).read_text(encoding='utf8'))
            self.assertEqual(receipt['status'], 'candidate_ready')
        with self.assertRaisesRegex(InputError, 'byte budget'):
            selection_request(run, 'e3', max_bytes=10)
        with self.assertRaisesRegex(InputError, 'without generated verdicts'):
            bind_selections(run, req, {'selections': [], 'verdict': 'conflict'})
        corrupt = deepcopy(response); corrupt['selections'][0]['criterion']['quote'] = 'invented'
        with self.assertRaises(InputError): bind_selections(run, req, corrupt)
