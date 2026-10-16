import copy
import json
import unittest

import test_training_lineage as fixtures
from test_training_lineage import record
from tracker import failure_investigations, monitoring, training_investigations, training_lineage
from tracker.schema import InputError, digest, dumps


class TrainingInvestigationTests(unittest.TestCase):
    setUp = fixtures.TrainingLineageTests.setUp
    packet = fixtures.TrainingLineageTests.packet
    add = fixtures.TrainingLineageTests.add
    source = fixtures.TrainingLineageTests.source

    def setup_comparison(self):
        for name, text, decision in [('a', 'short', 'admitted'), ('b', 'a longer response', 'rejected')]:
            self.source(name, text)
            self.add(record('sample', name), record('selection', name, decision=decision))
        self.add(record('sample', 'missing'), record('selection', 'missing', decision='admitted'))
        m = monitoring.create(self.store, {'name': 'Response length', 'kind': 'metric',
            'observer': 'source', 'metric': 'agent_text_chars'})
        monitoring.sync(self.store)
        selection = training_lineage.snapshot(self.store)['selection_options'][0]['id']
        scope = {'experiment': 'exp', 'monitor': m['id'], 'selection': selection}
        snapshot = training_lineage.snapshot(self.store, **scope)
        return {'scope': scope, 'snapshot_id': snapshot['snapshot_id'], 'title': 'Selected behavior', 'hypothesis': '',
            'view': {'stage': 'generated', 'selection': {'cohort': snapshot['cohorts'][0]['cohort'],
                                                       'step': 0, 'decision': 'admitted'}}}, snapshot

    def test_frozen_projection_and_cases_survive_late_records_sources_and_measurements(self):
        request, before = self.setup_comparison()
        saved = training_investigations.save(self.store, request)
        self.assertEqual(saved['snapshot'], before)
        self.assertEqual(before['snapshot_id'], 'training-population-' + digest({k:v for k,v in before.items() if k!='snapshot_id'}))
        self.assertEqual([s['rollout_id'] for s in saved['selected_samples']], ['a', 'missing'])
        self.assertIsNone(saved['selected_samples'][1]['run_id'])
        self.assertEqual(len(saved['source_graphs']), 2)
        self.assertEqual(saved['inference_calls'], 0)
        original = dumps(saved)
        self.add(record('selection', 'a', revision=1, decision='rejected'))
        self.source('missing', 'late joined source'); self.source('a', 'later source revision', revision=1)
        monitoring.sync(self.store)
        self.assertNotEqual(training_lineage.snapshot(self.store, **request['scope'])['snapshot_id'], before['snapshot_id'])
        self.assertEqual(dumps(failure_investigations.read(self.store, saved['id'])), original)
        self.assertIn(saved['id'], [r['id'] for r in failure_investigations.saved(self.store)])

    def test_changed_evidence_cannot_be_saved_under_old_display_identity(self):
        request, _ = self.setup_comparison()
        self.add(record('selection', 'a', revision=1, decision='rejected'))
        with self.assertRaisesRegex(InputError, 'Refresh and review'):
            training_investigations.save(self.store, request)
        self.assertEqual(failure_investigations.saved(self.store), [])

    def test_missing_measurement_materialization_changes_snapshot_without_training_arrival(self):
        self.source('a'); self.add(record('sample'))
        m = monitoring.create(self.store, {'name': 'Length', 'kind': 'metric', 'observer': 'source', 'metric': 'agent_text_chars'})
        before = training_lineage.snapshot(self.store, monitor=m['id'])
        monitoring.sync(self.store)
        after = training_lineage.snapshot(self.store, monitor=m['id'])
        self.assertEqual(before['revision'], after['revision'])
        self.assertNotEqual(before['snapshot_id'], after['snapshot_id'])

    def test_new_hypothesis_revision_uses_parent_not_current_training_evidence(self):
        request, before = self.setup_comparison(); saved = training_investigations.save(self.store, request)
        self.add(record('selection', 'a', revision=1, decision='rejected'))
        view = copy.deepcopy(request['view']); view['selection']['decision'] = 'rejected'
        child = training_investigations.save(self.store, {'parent_id': saved['id'], 'view': view,
            'title': 'A competing explanation', 'hypothesis': 'Hold tasks fixed and compare filters.'})
        self.assertEqual(child['snapshot'], before)
        self.assertEqual(child['source_graphs'], saved['source_graphs'])
        self.assertEqual(child['parent_id'], saved['id'])
        self.assertEqual([s['rollout_id'] for s in child['selected_samples']], ['b'])
        self.assertEqual(failure_investigations.read(self.store, saved['id']), saved)

    def test_scope_selection_and_stage_validation_precedes_persistence(self):
        request, _ = self.setup_comparison()
        changes = [({'scope': {'unknown': 'x'}}), {'snapshot_id': 'forged'}, {'view': {}},
            {'view': {'stage': [], 'selection': None}}, {'view': {'stage': 'optimizer', 'selection': None}},
            {'view': {'stage': 'generated', 'selection': {'cohort': {}}}},
            {'view': {'stage': 'generated', 'selection': {**request['view']['selection'], 'step': True}}},
            {'view': {'stage': 'generated', 'selection': {**request['view']['selection'], 'decision': 'success'}}},
            {'view': {'stage': 'generated', 'selection': {**request['view']['selection'], 'step': 999}}},
            {'extra': 'not allowed'}, {'title': ''}]
        for fields in changes:
            with self.subTest(fields=fields), self.assertRaises(InputError):
                training_investigations.save(self.store, {**request, **fields})
        self.assertEqual(failure_investigations.saved(self.store), [])

    def test_repeat_save_is_idempotent_and_tampered_saved_evidence_is_rejected(self):
        request, _ = self.setup_comparison(); saved = training_investigations.save(self.store, request)
        self.assertEqual(training_investigations.save(self.store, request)['id'], saved['id'])
        self.assertEqual(len(failure_investigations.saved(self.store)), 1)
        with self.store.connect() as c:
            document=json.loads(c.execute('SELECT document FROM failure_investigations WHERE id=?',(saved['id'],)).fetchone()[0])
            document['snapshot']['samples'][0]['measurement']['value']=999
            c.execute('UPDATE failure_investigations SET document=? WHERE id=?',(dumps(document),saved['id']))
        with self.assertRaisesRegex(InputError, 'identity mismatch'):
            failure_investigations.read(self.store, saved['id'])


if __name__ == '__main__': unittest.main()
