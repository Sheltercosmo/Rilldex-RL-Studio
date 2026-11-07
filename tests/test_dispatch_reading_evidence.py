"""Exact public source binding and saved model decisions, not population accuracy."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.evaluate_dispatch_reading import FIXTURE, evaluate
from scripts.evaluate_public_episodes import load_evidence
from tracker.adapters import normalize
from tracker.criterion_review import selection_request, bind_selections, resolve_dispatch
from tracker.schema import digest


class DispatchReadingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(FIXTURE.read_text(encoding='utf8'))
        cls.sources = load_evidence()
        cls.runs = {s['id']: normalize(s['document'])[0] for s in cls.sources['sources']}

    def test_all_generated_quotes_bind_through_the_model_neutral_production_path(self):
        recorded = {r['id']: r for r in self.evidence['phases']['native_context']}
        seen = []
        for row in self.evidence['selections']['rows']:
            episode, eid = row['id'].rsplit('-', 1); run = self.runs[episode]
            request = selection_request(run, eid)
            checks = bind_selections(run, request, {'selections': row['selections']})
            for index, check in enumerate(checks):
                key = row['id']+'/'+str(index); seen.append(key)
                receipt = self.evidence['receipts'][recorded[key]['request_hash']]
                self.assertEqual(check, receipt['request'])
                self.assertEqual(digest(check), recorded[key]['request_hash'])
                result = resolve_dispatch(check, receipt['response'])
                self.assertEqual(result['source_hash'], digest(run))
                self.assertEqual(result['selected_action_id'], eid)
                self.assertNotIn('reference', check)
                self.assertNotIn('evaluation_criteria', check['state'])
        self.assertEqual(len(seen), 25)
        self.assertEqual(set(seen), set(recorded))

    def test_original_results_are_preserved_after_independent_harness_adjudication(self):
        before = deepcopy(self.evidence); report = evaluate(self.evidence)
        for arm in ('state_only', 'literal_question'):
            self.assertEqual(report['phases'][arm]['original']['unambiguous_matches'], 17)
            self.assertEqual(report['phases'][arm]['original']['unambiguous'], 19)
        native = report['phases']['native_context']
        self.assertEqual(native['original']['unambiguous_matches'], 18)
        self.assertEqual(native['original']['disagreements'], ['telecom-16-e71/0'])
        self.assertEqual(native['adjudicated']['unambiguous'], 18)
        self.assertEqual(native['adjudicated']['ambiguous'], 7)
        original = next(r for r in self.evidence['reference']['rows'] if r['id'] == 'telecom-16-e71/0')
        changed = next(r for r in self.evidence['adjudication']['adjudications'] if r['id'] == original['id'])
        self.assertEqual(original['value'], 'conflict')
        self.assertFalse(original['ambiguous'])
        self.assertEqual(changed['value'], 'unresolved')
        self.assertTrue(changed['ambiguous'])
        self.assertEqual(self.evidence, before)

    def test_harness_revision_is_distinct_from_historical_execution_version(self):
        provenance = self.evidence['adjudication']['provenance']
        for source in self.sources['sources']:
            domain = source['id'].split('-')[0]
            actual = source['document']['info']['git_commit']
            self.assertEqual(actual, provenance['recorded_runtime_commits'][domain])
            self.assertNotEqual(actual, provenance['pinned_repository_commit'])
        self.assertTrue(all(s['expected_sha256'] == s['actual_sha256'] for s in provenance['hash_verified_sources']))

    def test_initial_invalid_packet_is_retained_and_excluded_instead_of_retried_as_evidence(self):
        self.assertEqual(len(self.evidence['receipts']), 75)
        self.assertEqual(len(self.evidence['excluded_trials']), 1)
        failed = self.evidence['excluded_trials'][0]
        self.assertEqual(failed['request_hash'], digest(failed['receipt']['request']))
        self.assertNotIn('cutoff_event_id', failed['receipt']['request']['state'])
        self.assertFalse(failed['included_in_paired_trial'])
        self.assertNotIn(failed['request_hash'], self.evidence['receipts'])
