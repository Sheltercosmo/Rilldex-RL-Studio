"""Current macro maps must use the exact current reading, without losing history."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import jev
from tracker.adapters import normalize
from tracker.observe import HARNESS_VERSION
from tracker.schema import dumps
from tracker.store import Store
from tests.test_tracker import harbor, response_for


class MacroRefreshTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'study.sqlite')
        self.run = normalize(harbor())[0]
        self.store.add([self.run])
        self.action = next(e['id'] for e in self.run['events'] if e['kind'] == 'action')
        self.client = jev.JevClient(transport=response_for)

    def save(self, value):
        p = value['_provenance']
        self.store.record(self.run['id'], self.action, p['harness'], p['model'], p['packet_hash'], value)

    def reading(self):
        return self.client.evaluate(self.run, self.action)

    def selected(self):
        analysis = self.store.get(self.run['id'])['analysis']
        return analysis, next(a for a in analysis['actions'] if a['event_id'] == self.action)

    def test_changed_context_request_invalidates_all_model_fields_without_calls(self):
        original = self.reading()
        self.save(original)
        self.store.refresh(self.run['id'])
        self.assertEqual(self.selected()[1]['mode'], 'explore')
        question = deepcopy(jev.QUESTIONS['mode'])
        question['instructions'] += ' New context-reading contract.'
        with patch.dict(jev.QUESTIONS, mode=question), patch.object(jev.JevClient, '_post', side_effect=AssertionError('No model calls on read')):
            self.store.refresh(self.run['id'])
            analysis, action = self.selected()
            self.assertEqual(action['mode'], 'unresolved')
            self.assertEqual(action['macro']['goal_scope']['value'], 'unresolved')
            self.assertEqual(analysis['semantic_coverage'], 0)
            self.assertEqual(analysis['metrics']['outdated_actions'], 1)
            self.assertNotEqual(analysis['inspector_signature'], 'heuristic')
            self.assertEqual(self.store.get(self.run['id'], raw=True)['model_observations'][self.action], original)

    def test_old_materialized_maps_and_list_refresh_on_upgrade(self):
        old = self.reading()
        old['_provenance']['harness'] = 'macro-semantics/old'
        self.save(old)
        with self.store.connect() as connection:
            row = connection.execute('SELECT analysis FROM runs WHERE id=?', (self.run['id'],)).fetchone()
            analysis = json.loads(row[0])
            analysis['harness_version'] = 'macro/0.11.0'
            connection.execute('UPDATE runs SET analysis=? WHERE id=?', (dumps(analysis), self.run['id']))
        with patch.object(jev.JevClient, '_post', side_effect=AssertionError('No model calls on read')):
            listing = Store(self.store.path).list()[0]
            self.assertEqual(listing['harness_version'], HARNESS_VERSION)
            self.assertEqual(listing['metrics']['outdated_actions'], 1)
            self.assertEqual(self.selected()[1]['mode'], 'unresolved')

    def test_newer_incompatible_record_does_not_displace_exact_saved_reading(self):
        current = self.reading()
        self.save(current)
        stale = deepcopy(current)
        stale['_provenance']['packet_hash'] = 'different-context'
        stale['mode']['value'] = 'apply'
        self.save(stale)
        self.store.refresh(self.run['id'])
        analysis, action = self.selected()
        self.assertEqual(action['mode'], 'explore')
        self.assertEqual(action['semantic']['mode'], current['mode'])
        self.assertEqual(analysis['semantic_coverage'], 1)
        self.assertEqual(analysis['metrics']['outdated_actions'], 0)

    def test_review_survives_reader_change_but_clearing_it_does_not_restore_stale_prediction(self):
        original = self.reading()
        original['_provenance']['packet_hash'] = 'old-request'
        self.save(original)
        payload = dict(event_id=self.action, field='mode', value='apply', reviewer='Fixture reviewer',
                       expected_revision=0, note='Authored control')
        review = self.store.review(self.run['id'], payload)
        analysis, action = self.selected()
        self.assertEqual(action['mode'], 'apply')
        self.assertEqual(action['semantic']['mode']['model_observation'], original['mode'])
        self.assertEqual(analysis['semantic_coverage'], 0)
        self.store.review(self.run['id'], {**payload, 'value': None, 'expected_revision': review['review_revision']})
        self.assertEqual(self.selected()[1]['mode'], 'unresolved')

    def test_fresh_reading_replaces_pending_state_and_keeps_both_receipts(self):
        old = self.reading()
        old['_provenance']['packet_hash'] = 'old-request'
        self.save(old)
        self.store.refresh(self.run['id'])
        self.assertEqual(self.selected()[1]['mode'], 'unresolved')
        fresh = self.reading()
        self.save(fresh)
        self.store.refresh(self.run['id'])
        analysis, action = self.selected()
        self.assertEqual(action['mode'], 'explore')
        self.assertEqual(analysis['metrics']['outdated_actions'], 0)
        with self.store.connect() as connection:
            records = [json.loads(r[0]) for r in connection.execute('SELECT result FROM observations WHERE run_id=?', (self.run['id'],))]
        self.assertCountEqual(records, [old, fresh])

    def test_incomplete_obsolete_reading_does_not_fall_back_to_tool_name_purpose(self):
        old = self.reading()
        old.pop('mode')
        old['_provenance']['harness'] = 'macro-semantics/old'
        self.save(old)
        self.store.refresh(self.run['id'])
        analysis, action = self.selected()
        self.assertEqual(action['mode'], 'unresolved')
        self.assertEqual(action['observation_status'], 'outdated')


if __name__ == '__main__':
    unittest.main()
