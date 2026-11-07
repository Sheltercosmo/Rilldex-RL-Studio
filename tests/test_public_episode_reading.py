"""Public-source receipt replay and failure diagnosis, not semantic accuracy proof."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.evaluate_public_episodes import evaluate, load_evidence, requests, score
from tracker import action_distributions, action_reading, behavior_distributions
from tracker.action_context import visible_before
from tracker.adapters import normalize
from tracker.jev import JevClient, QUESTIONS, validate_answers
from tracker.schema import InputError, digest
from tracker.store import Store
from receipt_replay import recorded_sqlite_metadata


class PublicEpisodeReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = load_evidence()
        cls.enterClassContext(recorded_sqlite_metadata(cls.evidence))
        cls.references = {r['id']: r for r in cls.evidence['review']['rows']}
        cls.baseline = {r['id']: r for r in cls.evidence['phases']['production']}

    def test_complete_episode_selection_and_reference_cutoffs(self):
        self.assertEqual(len(self.evidence['sources']), 6)
        self.assertEqual(len(self.references), 30)
        self.assertEqual(self.evidence['selection']['commit'], '4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699')
        for source in self.evidence['sources']:
            run = normalize(source['document'])[0]
            self.assertEqual(digest(run), source['source_hash'])
            origin = source['document']['source_origin']
            self.assertEqual(origin['collection_sha256'], source['source_sha256'])
            self.assertIn(source['simulation_index'], (7, 16, 32))
            actions = [e for e in run['events'] if e['kind'] == 'action']
            self.assertEqual(len(actions), source['actions'])
            for action in actions:
                ref = self.references[source['id'] + '-' + action['id']]
                prefix = {e['id'] for e in run['events'] if visible_before(e, action)} | {action['id']}
                for field, label in ref['fields'].items():
                    self.assertIn(label['value'], QUESTIONS[field]['criteria'])
                    self.assertTrue(set(label['alternatives']) <= set(QUESTIONS[field]['criteria']))
                    self.assertTrue(set(label['evidence_ids']) <= prefix)
                    self.assertTrue(label['reason'])

    def test_current_requests_match_all_public_receipts_without_reference_leakage(self):
        rows = list(requests(self.evidence, JevClient()))
        self.assertEqual(len(rows), 30)
        for row in rows:
            baseline = self.baseline[row['id']]
            receipt = self.evidence['receipts'][baseline['request_hash']]
            self.assertEqual(row['request'], receipt['request'])
            self.assertEqual(row['source_hash'], baseline['source_hash'])
            self.assertNotIn('reference', row['request'])
            self.assertNotIn('reward_info', row['request']['state'])
            self.assertNotIn('evaluation_criteria', row['request']['state'])
            score(receipt['response'], row['request'], self.references[row['id']])

    def test_replay_keeps_disagreements_ambiguities_and_scope_notes(self):
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', side_effect=AssertionError('Offline replay')):
            report = evaluate(directory, evidence=self.evidence)
        self.assertEqual((report['new_calls'], report['cached_responses'], report['pending']), (0, 30, 0))
        for field, expected in [('mode', (29, 29, 1)), ('goal_relation', (18, 27, 3)), ('feedback_response', (22, 26, 4))]:
            group = report['groups'][field]
            self.assertEqual((group['unambiguous_matches'], group['unambiguous'], group['ambiguous']), expected)
        self.assertEqual(report['groups']['feedback_response']['unresolved_without_inference'], 5)
        self.assertEqual(report['groups']['feedback_response']['not_applicable_without_inference'], 6)
        self.assertIn('telecom-16-e33', report['groups']['goal_relation']['unambiguous_disagreements'])
        self.assertEqual(report['review_scope_notes'], self.evidence['review_scope_notes'])
        # Another model has no matching receipts; an unread episode cannot score as correct.
        with tempfile.TemporaryDirectory() as directory:
            pending = evaluate(directory, evidence=self.evidence, client=JevClient(model='unmeasured-reader',
                transport=lambda request: self.fail('Offline evaluation must not call a model')))
        self.assertEqual((pending['pending'], pending['cached_responses']), (30, 0))
        self.assertTrue(all(g['reviewed'] == 0 for g in pending['groups'].values()))

    def test_policy_diagnostics_preserve_failed_trials_and_counterfactuals(self):
        receipts = self.evidence['receipts']
        for key, receipt in receipts.items():
            self.assertEqual(digest(receipt['request']), key)
            self.assertEqual(receipt['request']['model'], receipt['response']['model'])
            validate_answers(receipt['response'], receipt['request'])
        rows = {r['arm']: r for r in self.evidence['phases']['minimal-probes']}
        values = {arm: validate_answers(receipts[r['request_hash']]['response'],
            receipts[r['request_hash']]['request'])['goal_relation']['value'] for arm, r in rows.items()}
        self.assertEqual(values['minimal_exact'], 'direct')
        self.assertEqual(values['minimal_missing_counterfactual'], 'direct')
        self.assertEqual(values['exact_clause_full'], 'supported')
        self.assertEqual(values['exact_clause_minimal'], 'conflicting')
        exact = deepcopy(receipts[rows['minimal_exact']['request_hash']]['request'])
        future = deepcopy(receipts[rows['minimal_future_counterfactual']['request_hash']]['request'])
        before = exact['state']['recorded_prior_results'][0].pop('text')
        after = future['state']['recorded_prior_results'][0].pop('text')
        self.assertEqual(exact, future)
        self.assertEqual(after, before.replace('"contract_end_date": "2025-01-31"', '"contract_end_date": "2026-01-31"'))

    def test_offline_cli_replay_uses_recorded_packets_across_runtime_versions(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('sqlite3.sqlite_version', 'different-host-runtime'), \
                patch.object(JevClient, 'request', side_effect=AssertionError('Must replay saved packets')), \
                patch('urllib.request.urlopen', side_effect=AssertionError('Offline replay')):
            report = evaluate(directory, evidence=self.evidence)
        self.assertEqual(report['request_source'], 'recorded packets')
        self.assertEqual((report['cached_responses'], report['pending']), (30, 0))
        damaged = deepcopy(self.evidence)
        key = damaged['phases']['production'][0]['request_hash']
        damaged['receipts'][key]['request']['state']['cutoff_event_id'] = 'changed'
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            evaluate(directory, evidence=damaged)

    def test_all_30_recorded_readings_reach_maps_and_saved_distributions(self):
        # Tests propagation of actual saved decisions, including their known errors.
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', side_effect=AssertionError('Offline replay')):
            store = Store(Path(directory) / 'public.sqlite')
            receipts = self.evidence['receipts']; calls = []
            def replay(request):
                key = digest(request); calls.append(key)
                self.assertEqual(receipts[key]['request'], request)
                return deepcopy(receipts[key]['response'])
            client = JevClient(transport=replay)
            expected = {}
            for source in self.evidence['sources']:
                run = normalize(source['document'])[0]; store.add([run])
                actions = [e for e in run['events'] if e['kind'] == 'action']
                for action in actions:
                    result = action_reading.read(store, run['id'], action['id'], client=client)
                    self.assertEqual(result['status'], 'current')
                    expected[(run['id'], action['id'])] = result['fields']
                flow = action_reading.flow(store, run['id'], client=client)
                self.assertEqual(flow['coverage']['total'], len(actions))
                self.assertEqual(flow['coverage']['current'], len(actions))
                self.assertEqual(flow['coverage']['pending'], 0)
                self.assertEqual(sum(flow['purposes'].values()), len(actions))
                cached = action_reading.read(store, run['id'], actions[-1]['id'], client=client)
                self.assertTrue(cached['reused'])
            self.assertEqual(len(calls), 30)
            for lens, field in [('action_purpose', 'mode'), ('task_connection', 'goal_relation')]:
                documents = action_distributions.inputs(store, lens)
                self.assertEqual(len(documents), 6)
                self.assertEqual(sum(len(d['records']) for d in documents), 30)
                for document in documents:
                    for row in document['records']:
                        self.assertEqual(row['reading']['value'], expected[(document['run_id'], row['event_id'])][field]['value'])
                saved = behavior_distributions.save_comparison(store, {'controls': {'lens': lens}})
                self.assertEqual(behavior_distributions.read_comparison(store, saved['id']), saved)
                self.assertEqual(saved['snapshot']['inference_calls'], 0)


if __name__ == '__main__':
    unittest.main()
