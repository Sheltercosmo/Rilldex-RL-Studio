"""Frozen model-driven source reads across two public cases and a long control."""
import json
import unittest

from scripts.evaluate_dispatch_reader import FIXTURE, replay
from scripts.evaluate_public_episodes import load_evidence
from tracker.adapters import normalize
from tracker.criterion_review import selection_request
from tracker.schema import InputError, digest


class DispatchReaderEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(FIXTURE.read_text(encoding='utf8'))
        public = {r['id']: r['document'] for r in load_evidence()['sources']}
        cls.runs = {c['id']: normalize(public[c['source']['id']])[0] if c['source']['kind'] == 'public_episode'
                    else c['source']['run'] for c in cls.evidence['cases']}

    def test_all_recorded_requests_and_comparisons_replay_within_the_actual_budget(self):
        report = replay(self.evidence)
        self.assertEqual(sum(r['rounds'] for r in report['cases']), 32)
        self.assertEqual(sum(r['comparisons'] for r in report['cases']), 9)
        self.assertEqual(sum(r['rejected_attempts'] for r in report['cases']), 2)
        for row in report['cases']:
            self.assertEqual(row['status'], 'ready_for_review')
            self.assertLessEqual(row['max_request_bytes'], row['request_byte_limit'])
            self.assertNotIn('accuracy', row)

    def test_whole_prefix_does_not_fit_the_same_budget_for_any_trial_case(self):
        for case in self.evidence['cases']:
            with self.subTest(case=case['id']), self.assertRaisesRegex(InputError, 'byte budget'):
                selection_request(self.runs[case['id']], case['event_id'], max_bytes=case['settings']['max_bytes'])

    def test_independent_reference_quotes_match_original_source_without_relabeling(self):
        count = 0
        bindings = {(r['case_id'], r['reference_hash']): r for r in self.evidence['reference_bindings']}
        def check(value, events):
            nonlocal count
            if isinstance(value, dict):
                if {'id', 'quote', 'char_start', 'char_end', 'source_pointer'} <= set(value):
                    event = events[value['id']]
                    bound = bindings[(case['id'], digest(value))]
                    self.assertEqual(event['text'][bound['start']:bound['end']], value['quote'])
                    self.assertEqual(event['text'].encode('utf-16-le')[value['char_start']*2:value['char_end']*2].decode('utf-16-le'), value['quote'])
                    self.assertEqual(event['source_pointer'], value['source_pointer']); count += 1
                for child in value.values(): check(child, events)
            elif isinstance(value, list):
                for child in value: check(child, events)
        for case in self.evidence['reference_review']['cases']:
            check(case, {e['id']: e for e in self.runs[case['id']]['events']})
        self.assertEqual(count, 54)
        self.assertEqual(sum(r['start'] != r['original_start'] for r in bindings.values()), 2)

    def test_long_control_retains_opposing_states_and_complete_exception(self):
        case = next(c for c in self.evidence['cases'] if c['id'] == 'account-state-control')
        final = case['turns'][-1]['response']['finish']['selections'][0]
        self.assertIn('Exception: an active legal hold prohibits freezing.', final['criterion']['quote'])
        context = [r['quote'] for r in final['context']]
        self.assertTrue(any('"legal_hold":false' in q for q in context))
        self.assertTrue(any('"legal_hold":true' in q for q in context))
