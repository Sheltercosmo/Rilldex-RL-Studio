from pathlib import Path
import tempfile
import unittest

from tracker import generation_cohorts as cohorts
from tracker.portable import generation_document
from tracker.store import ReviewConflict, Store


def member(rollout_id, *, producer='generator', state='admitted', context=None):
    return {'producer': producer, 'rollout_id': rollout_id,
        'generation_state': state, 'context': context or {}}


def cohort(revision=0, *, members=None, sealed=False, index=4, context=None, identifier='batch-a'):
    return {'id': identifier, 'revision': revision, 'label': 'scheduled batch',
        'coordinate': {'clock': 'generation', 'basis': 'scheduler batch', 'index': index},
        'context': context or {}, 'sealed': sealed,
        'members': members or [], 'evidence': 'scheduler manifest'}


class GenerationCohortTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = Store(self.root / 'workspace.sqlite')

    def packet(self, *rows):
        return {'schema': cohorts.VERSION, 'producer': 'scheduler', 'experiment': 'exp',
            'cohorts': list(rows)}

    def add(self, *rows):
        return cohorts.receive(self.store, self.packet(*rows))

    def source(self, rollout_id, *, environment='terminal', metadata=None, state='complete'):
        values = {'experiment': 'exp', 'environment': environment, 'environment_version': 'v1',
            'training_clock': 'generation', 'training_step_basis': 'scheduler batch', 'training_step': 4}
        if metadata is not None:
            values = metadata
        return self.store.ingest({'producer': 'generator', 'rollout_id': rollout_id,
            'revision': 0, 'state': state,
            'document': generation_document('question', 'answer', metadata=values)})

    def test_receive_is_idempotent_and_accepts_out_of_order_compatible_revisions(self):
        final = cohort(2, members=[member('a', state='completed'), member('b')], sealed=True)
        self.assertEqual(self.add(final)['inserted'], 1)
        self.assertEqual(self.add(cohort())['inserted'], 1)
        self.assertEqual(self.add(cohort(1, members=[member('a', state='completed')]))['inserted'], 1)
        self.assertEqual(self.add(final)['inserted'], 0)
        with self.store.connect() as c:
            rows = c.execute('SELECT revision FROM generation_cohorts ORDER BY revision').fetchall()
        self.assertEqual([r[0] for r in rows], [0, 1, 2])

    def test_incompatible_late_revision_is_rejected_without_partial_packet_write(self):
        self.add(cohort(2, members=[member('a')]))
        with self.assertRaises(ReviewConflict):
            self.add(cohort(1, members=[member('a', state='failed')]), cohort(3, members=[member('a')]))
        with self.store.connect() as c:
            revisions = [r[0] for r in c.execute('SELECT revision FROM generation_cohorts ORDER BY revision')]
        self.assertEqual(revisions, [2])

    def test_sealed_membership_cannot_grow_or_reopen(self):
        self.add(cohort(1, members=[member('a')], sealed=True))
        with self.assertRaises(ReviewConflict):
            self.add(cohort(2, members=[member('a'), member('b')], sealed=True))
        with self.assertRaises(ReviewConflict):
            self.add(cohort(2, members=[member('a')], sealed=False))

    def test_generation_state_is_not_task_outcome_and_missing_delivery_stays_declared(self):
        self.source('done')
        self.add(cohort(1, members=[member('done', state='completed'),
            member('failed', state='failed'), member('cancelled', state='cancelled')], sealed=True))
        result = cohorts.snapshot(self.store, experiment='exp', include_members=True)
        row = result['cohorts'][0]
        self.assertEqual(row['declared'], 3)
        self.assertEqual(row['delivered'], 1)
        self.assertEqual(row['generation_states'], {'admitted': 0, 'completed': 1, 'failed': 1, 'cancelled': 1})
        self.assertEqual(row['generation_settled'], True)
        self.assertEqual({m['source_status'] for m in row['members']}, {'delivered', 'not_delivered'})
        self.assertTrue(all('verified_success' in m['outcome'] for m in row['members']))
        self.assertIsNone(next(m for m in row['members'] if m['rollout_id'] == 'failed')['outcome']['verified_success'])

    def test_retry_attempts_remain_attempts_and_do_not_expand_declared_population(self):
        from tracker import execution_records
        self.add(cohort(1, members=[member('a', state='completed')], sealed=True))
        def attempt(identifier, retry=None):
            row = {'id': identifier, 'revision': 0, 'kind': 'rollout',
                'rollout': {'producer': 'generator', 'id': 'a'}, 'state': 'completed',
                'context': {}, 'evidence': 'execution scheduler'}
            if retry: row['retry_of'] = {'producer': 'worker', 'id': retry}
            return row
        execution_records.receive(self.store, {'schema': execution_records.VERSION, 'producer': 'worker',
            'experiment': 'exp', 'records': [attempt('try-1'), attempt('try-2', 'try-1')]})
        row = cohorts.snapshot(self.store, experiment='exp', include_members=True)['cohorts'][0]
        self.assertEqual(row['declared'], 1)
        self.assertEqual(row['execution_attempts'], 2)
        self.assertEqual(len(row['members'][0]['attempts']), 2)

    def test_source_context_and_clock_conflicts_are_reported_unknown_metadata_is_not_inferred(self):
        self.source('wrong-clock', metadata={'experiment': 'exp', 'environment': 'terminal',
            'training_clock': 'learner', 'training_step_basis': 'optimizer', 'training_step': 4})
        self.source('unknown-clock', metadata={'experiment': 'exp', 'environment': 'terminal'})
        self.add(cohort(1, members=[member('wrong-clock'), member('unknown-clock')], sealed=True))
        row = cohorts.snapshot(self.store, experiment='exp', include_members=True)['cohorts'][0]
        by_id = {m['rollout_id']: m for m in row['members']}
        self.assertEqual(by_id['wrong-clock']['source_status'], 'delivered')
        self.assertEqual(by_id['wrong-clock']['coordinate_alignment'], 'different_clock')
        self.assertEqual(by_id['unknown-clock']['coordinate_alignment'], 'unrecorded')

    def test_environment_filter_is_an_explicit_subset_of_declared_members(self):
        self.add(cohort(1, members=[member('a', context={'environment': 'terminal'}),
            member('b', context={'environment': 'browser'})], sealed=True))
        result = cohorts.snapshot(self.store, experiment='exp', environment='terminal', include_members=True)
        self.assertEqual(result['cohorts'][0]['membership_scope'], 'environment subset')
        self.assertEqual(result['cohorts'][0]['declared'], 1)
        self.assertEqual([m['rollout_id'] for m in result['cohorts'][0]['members']], ['a'])

    def test_trace_only_sources_do_not_create_a_declared_population(self):
        self.source('trace-only')
        result = cohorts.snapshot(self.store, experiment='exp')
        self.assertFalse(result['available'])
        self.assertEqual(result['cohorts'], [])


if __name__ == '__main__':
    unittest.main()
