import copy
import tempfile
import unittest
from pathlib import Path

from rilldex import chat_document
from tracker.adapters import normalize
from tracker import case_comparisons as cases, investigation_workspace, graph_store, failure_investigations
from tracker.schema import InputError, digest
from tracker.store import Store


class CaseComparisonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'workspace.sqlite'); self.serial = 0

    def add(self, step, success=None, reward=None, **extra):
        self.serial += 1
        metadata = dict(experiment='case-test', task_id='parser', task_revision='v1', environment='terminal',
                        environment_version='1', split='eval', reward_definition='correctness/1',
                        checkpoint='policy-'+str(step), training_step=step, training_clock='policy', training_step_basis='generation')
        metadata.update(extra)
        run = normalize(chat_document([{'role': 'assistant', 'content': 'Attempt '+str(self.serial)}], metadata=metadata, success=success, reward=reward))[0]
        self.store.add([run]); return run

    def capture(self):
        return investigation_workspace.save(self.store, dict(experiment='case-test', baseline=[0, 0], current=[1, 1], monitor_ids=[], title='Case comparison'))

    def test_known_boolean_outcome_and_pinned_source_evidence(self):
        a = self.add(0, False, 10); b = self.add(1, True, 1); doc = self.capture()
        listing = cases.listing(self.store, doc['id'])
        self.assertEqual(listing['counts'], {'improved': 1})
        self.assertEqual(listing['source_counts'], {'baseline': 1, 'current': 1})
        pair = cases.pair(self.store, doc['id'], a['id'], b['id'])
        self.assertEqual(pair['status'], 'improved')  # Not reward direction.
        self.assertEqual(pair['missing_context'], [])
        self.assertEqual(pair['reference']['run']['outcome']['recorded_reward'], 10)
        self.assertEqual(pair['reference']['graph']['id'], graph_store.build(a)['id'])
        self.assertIn('checkpoint', [row['field'] for row in pair['configuration_changes']])

    def test_late_rollouts_and_graph_versions_never_rewrite_comparison(self):
        a = self.add(0, True); b = self.add(1, False); doc = self.capture()
        old = cases.pair(self.store, doc['id'], a['id'], b['id'])
        later = self.add(1, True)
        graph = graph_store.build(b); graph.pop('id'); graph['semantic_context'] = {'notice': 'New graph version'}
        graph = {'id': 'graph-'+digest(graph), **graph}
        with self.store.connect() as c: graph_store.save(c, graph)
        self.assertEqual(cases.pair(self.store, doc['id'], a['id'], b['id']), old)
        self.assertEqual(cases.listing(self.store, doc['id'])['source_counts']['current'], 1)
        with self.assertRaises(InputError): cases.pair(self.store, doc['id'], a['id'], later['id'])

    def test_repeated_trials_are_explicitly_selected_and_not_cartesian_improvements(self):
        a = self.add(0, True); self.add(0, False); b = self.add(1, False); self.add(1, True)
        doc = self.capture(); listing = cases.listing(self.store, doc['id'])
        self.assertEqual(listing['counts'], {'choose_rollouts': 1})
        self.assertEqual(len(listing['groups'][0]['baseline']), 2)
        self.assertEqual(cases.pair(self.store, doc['id'], a['id'], b['id'])['status'], 'regressed')
        self.assertEqual(cases.listing(self.store, doc['id'], status='improved')['filtered_contexts'], 0)

    def test_missing_context_is_visible_and_unknown_outcome_cannot_use_reward_as_success(self):
        a = self.add(0, reward=0, task_revision=None); b = self.add(1, reward=1, task_revision=None)
        doc = self.capture(); listing = cases.listing(self.store, doc['id'])
        self.assertEqual(listing['counts'], {'unresolved': 1})
        self.assertEqual(listing['context_incomplete'], 1)
        pair = cases.pair(self.store, doc['id'], a['id'], b['id'])
        self.assertIn('task_revision', pair['missing_context'])
        self.assertEqual(pair['status'], 'unresolved')

    def test_changed_task_revision_reward_or_environment_is_unmatched(self):
        for metadata in [{'task_revision': 'v2'}, {'reward_definition': 'other'}, {'environment_version': '2'}]:
            with self.subTest(metadata=metadata):
                a = self.add(0, False, task_id=str(self.serial)); b = self.add(1, True, task_id=a['metadata']['task_id'], **metadata)
                doc = self.capture()
                with self.assertRaises(InputError): cases.pair(self.store, doc['id'], a['id'], b['id'])
        listing = cases.listing(self.store, doc['id'])
        self.assertEqual(listing['counts'], {'unmatched': 6})

    def test_missing_task_ids_do_not_pair_unrelated_rollouts(self):
        a = self.add(0, True, task_id=None); b = self.add(1, False, task_id=None); doc = self.capture()
        self.assertEqual(cases.listing(self.store, doc['id'])['counts'], {'unmatched': 2})
        with self.assertRaises(InputError): cases.pair(self.store, doc['id'], a['id'], b['id'])

    def test_unknown_and_in_progress_are_unresolved_not_failures(self):
        a = self.add(0, True); b = self.add(1, False); doc = self.capture()
        changed = copy.deepcopy(doc); changed.pop('id')
        next(row for row in changed['snapshot']['source_rows'] if row['id'] == b['id'])['state'] = 'in_progress'
        changed = failure_investigations.persist(self.store, changed)
        self.assertEqual(cases.pair(self.store, changed['id'], a['id'], b['id'])['status'], 'unresolved')

    def test_old_capture_does_not_retroactively_select_current_graphs(self):
        self.add(0); self.add(1); doc = self.capture(); doc.pop('id'); doc['snapshot'].pop('case_evidence')
        old = failure_investigations.persist(self.store, doc)
        self.assertFalse(cases.listing(self.store, old['id'])['available'])

    def test_shared_semantic_observation_is_selected_from_frozen_inventory(self):
        a = self.add(0, True); b = self.add(1, True)
        for run in (a, b):
            graph = graph_store.build(run); graph.pop('id')
            graph.update(observer='test-observer', observer_label='Authored observation inventory')
            graph['coverage']['semantic_relations'] = 'partial'
            graph = {'id': 'graph-'+digest(graph), **graph}
            with self.store.connect() as c: graph_store.save(c, graph)
        doc = self.capture()
        self.assertEqual(cases.pair(self.store, doc['id'], a['id'], b['id'])['reference']['graph']['observer'], 'test-observer')
        self.assertEqual(cases.pair(self.store, doc['id'], a['id'], b['id'], observer='source')['reference']['graph']['observer'], 'source')

    def test_paging_filtering_protocol_and_direction_validation(self):
        a = self.add(0, True); b = self.add(1, True); self.add(0, task_id='only-reference'); doc = self.capture()
        first = cases.listing(self.store, doc['id'], limit=1)
        second = cases.listing(self.store, doc['id'], limit=1, offset=1)
        self.assertNotEqual(first['groups'][0]['id'], second['groups'][0]['id'])
        self.assertEqual(cases.listing(self.store, doc['id'], status='unchanged')['filtered_contexts'], 1)
        with self.assertRaises(InputError): cases.pair(self.store, doc['id'], b['id'], a['id'])
        with self.assertRaises(InputError): cases.pair(self.store, doc['id'], a['id'], b['id'], observer='not-pinned')
        for kwargs in [{'status': 'bad'}, {'offset': -1}, {'limit': 100}, {'limit': True}]:
            with self.assertRaises(InputError): cases.listing(self.store, doc['id'], **kwargs)


if __name__ == '__main__': unittest.main()
