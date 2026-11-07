import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.evaluate_feedback_reading import cases
from tracker import action_reading
from tracker.adapters import normalize
from tracker.jev import JevClient
from tracker.schema import InputError, dumps
from test_generation_cohort_transport import GenerationCohortTransportTests
from receipt_replay import recorded_sqlite_metadata


class ActionReadingTests(unittest.TestCase):
    start_server = GenerationCohortTransportTests.start_server
    stop_server = staticmethod(GenerationCohortTransportTests.stop_server)

    def setUp(self):
        GenerationCohortTransportTests.setUp(self)
        self.case = next(c for c in cases() if c['id'] == 'service-immediate' and c['format'] == 'chat')
        self.run = normalize(self.case['document'])[0]
        self.store.add([self.run])
        self.action = [e for e in self.run['events'] if e['kind'] == 'action'][-1]['id']
        evidence = json.loads((Path(__file__).parent / 'fixtures/feedback_reading_evidence.json').read_text(encoding='utf8'))
        row = next(r for r in evidence['phases']['purpose-combined']['results']
                   if r['id'] == self.case['id'] and r['format'] == self.case['format'])
        self.receipt = evidence['receipts'][row['request_hash']]
        self.enterContext(recorded_sqlite_metadata(self.receipt))
        self.calls = 0

        def replay(request):
            self.assertEqual(request, self.receipt['request'])
            self.calls += 1
            return deepcopy(self.receipt['response'])
        self.client = JevClient(transport=replay)

    def test_source_only_map_can_read_one_action_and_reuse_the_exact_saved_reading(self):
        before = action_reading.inspect(self.store, self.run['id'], self.action, client=self.client)
        self.assertEqual(before['status'], 'uninspected')
        self.assertNotIn('mode', before['fields'])
        self.assertEqual(self.calls, 0)
        result = action_reading.read(self.store, self.run['id'], self.action, client=self.client)
        self.assertFalse(result['reused'])
        self.assertEqual(result['fields']['mode']['value'], 'apply')
        self.assertEqual(result['fields']['feedback_response']['value'], 'method_change')
        self.assertEqual(result['previous_feedback'], [e['id'] for e in self.run['events'] if e['kind'] == 'feedback'])
        again = action_reading.read(self.store, self.run['id'], self.action, client=self.client)
        self.assertTrue(again['reused'])
        self.assertEqual(self.calls, 1)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 1)
            self.assertEqual(json.loads(c.execute('SELECT document FROM runs').fetchone()[0]), self.run)

    def test_stale_readings_remain_unresolved_and_reviewed_choices_survive_refresh(self):
        result = self.client.evaluate(self.run, self.action)
        result['_provenance']['harness'] = 'old-reader'
        p = result['_provenance']
        self.store.record(self.run['id'], self.action, p['harness'], p['model'], p['packet_hash'], result)
        stale = action_reading.inspect(self.store, self.run['id'], self.action, client=self.client)
        self.assertEqual(stale['status'], 'outdated')
        self.assertEqual(stale['fields']['mode']['value'], 'unresolved')
        with self.store.connect() as c:
            review = dict(event_id=self.action, field='mode', value='verify', reviewer='Reader', note='Reviewed local purpose', evidence_ids=[self.action])
            c.execute('INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)', (self.run['id'], dumps(review), '2026-11-07T00:00:00Z'))
        refreshed = action_reading.read(self.store, self.run['id'], self.action, client=self.client)
        self.assertTrue(refreshed['reviewed'])
        self.assertEqual(refreshed['fields']['mode']['value'], 'verify')
        self.assertEqual(refreshed['fields']['mode']['source'], 'review')
        self.assertEqual(refreshed['history_count'], 2)

    def test_non_action_records_are_rejected_before_inference(self):
        for event in self.run['events']:
            if event['kind'] == 'action':
                continue
            with self.assertRaises(InputError):
                action_reading.read(self.store, self.run['id'], event['id'], client=self.client)
        self.assertEqual(self.calls, 0)

    def test_failed_provider_call_does_not_save_a_negative_reading(self):
        with patch.object(self.client, 'transport', side_effect=InputError('Provider unavailable')):
            with self.assertRaisesRegex(InputError, 'Provider unavailable'):
                action_reading.read(self.store, self.run['id'], self.action, client=self.client)
        self.assertEqual(action_reading.inspect(self.store, self.run['id'], self.action)['status'], 'uninspected')

    def test_http_serves_saved_choices_without_keys_and_only_reads_selected_action(self):
        action_reading.read(self.store, self.run['id'], self.action, client=self.client)
        endpoint = self.start_server()
        path = '/api/action-reading?run=' + self.run['id'] + '&event=' + self.action
        with urlopen(endpoint + path, timeout=10) as response:
            result = json.load(response)
        self.assertEqual(result['status'], 'current')
        self.assertEqual(result['fields']['feedback_response']['value'], 'method_change')
        request = Request(endpoint + '/api/action-reading', data=dumps({'run': self.run['id'], 'event': self.action}).encode(), headers={'Content-Type':'application/json'})
        with urlopen(request, timeout=10) as response:
            self.assertTrue(json.load(response)['reused'])
        with urlopen(endpoint + '/api/action-reading/flow?run=' + self.run['id'], timeout=10) as response:
            flow = json.load(response)
        self.assertEqual(flow['coverage']['current'], 1)
        self.assertEqual(flow['coverage']['uninspected'], 1)
        self.assertEqual(flow['actions'][-1]['fields']['feedback_response']['value'], 'method_change')
        for path in ['/action-reading.js', '/action-reading.css', '/action-flow.js', '/action-flow.css']:
            with urlopen(endpoint + path, timeout=10) as response:
                self.assertEqual(response.status, 200)
        invalid = Request(endpoint + '/api/action-reading', data=dumps({'run':self.run['id'],'event':self.action,'all':True}).encode(), headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:
            urlopen(invalid, timeout=10)
        self.assertEqual(error.exception.code, 400)
