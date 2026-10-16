import unittest

from tracker.comparison_lineage import capture
from tracker.schema import InputError


def sample(run_id, sample_id, *, join='matched', records=None, step=900, experiment='exp'):
    return {
        'experiment': experiment, 'producer': 'learner', 'rollout_id': sample_id,
        'sample_id': sample_id, 'sample_identity_schema': 'training-records/2',
        'run_id': run_id, 'join_status': join, 'step': step,
        'populations': {'generated': True},
        'records': records or [{'kind': 'sample', 'id': 'sample/' + sample_id, 'revision': 0,
                                'data': {'source': {'producer': 'source', 'rollout_id': sample_id,
                                                    'revision': 0}}}],
    }


def fact(kind, record_id, **data):
    return {'kind': kind, 'id': record_id, 'revision': 0, 'record_producer': 'learner',
            'evidence': {'basis': 'test evidence'}, 'data': data}


class ComparisonLineageTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            'snapshot_id': 'training-population-pinned', 'revision': 'lineage-r7',
            'samples': [
                sample('base-run', 'base-1', records=[fact('sample', 'decl/base-1'),
                    fact('score', 'score/base-1', status='scored', value=1),
                    fact('selection', 'select/base-1', decision='admitted'),
                    fact('use', 'use/base-1', stage='backward_completed')]),
                sample('base-run', 'base-2', records=[fact('sample', 'decl/base-2'),
                    fact('score', 'score/base-2', status='scored', value=0),
                    fact('selection', 'select/base-2', decision='rejected')]),
                sample('current-run', 'current-1', records=[fact('sample', 'decl/current-1'),
                    fact('score', 'score/current-1', status='unavailable', value=None),
                    fact('selection', 'select/current-1', decision='unknown')]),
                # Same step and sample name are not a substitute for an exact source join.
                sample(None, 'unjoined', join='source_revision_not_declared'),
                sample('other-run', 'other', experiment='other-exp'),
            ],
        }

    def test_exact_run_join_preserves_facts_and_counts_unique_rollouts(self):
        got = capture({'baseline': ['base-run'], 'current': ['current-run', 'no-sample-run']}, self.snapshot)
        baseline = got['windows']['baseline']
        self.assertEqual(baseline['source_rollouts'], 1)
        self.assertEqual(baseline['joined_source_rollouts'], 1)
        self.assertEqual(baseline['sample_count'], 2)
        self.assertEqual(baseline['stages']['scored']['member_rollouts'], 1)
        self.assertEqual(baseline['stages']['scored']['member_samples'], 2)
        self.assertEqual(baseline['stages']['admitted']['member_rollouts'], 1)
        self.assertEqual(baseline['stages']['admitted']['explicit_nonmember_samples'], 1)
        self.assertEqual(baseline['stages']['backward']['member_rollouts'], 1)
        self.assertEqual(baseline['stages']['optimizer']['unknown_rollouts'], 1)
        self.assertEqual([s['id'] for s in baseline['rollouts'][0]['samples'][0]['records']],
                         ['decl/base-1', 'score/base-1', 'select/base-1', 'use/base-1'])

    def test_missing_and_unavailable_facts_remain_unknown_or_explicit(self):
        got = capture({'baseline': [], 'current': ['current-run', 'no-sample-run']}, self.snapshot)
        current = got['windows']['current']
        self.assertEqual(current['source_rollouts_without_joined_samples'], ['no-sample-run'])
        self.assertEqual(current['stages']['scored']['no_observed_membership_rollouts'], 1)
        self.assertEqual(current['stages']['admitted']['unknown_rollouts'], 2)
        self.assertEqual(current['stages']['backward']['unknown_rollouts'], 2)
        self.assertEqual(current['stages']['optimizer']['unknown_rollouts'], 2)
        self.assertNotIn('unjoined', str(current))
        self.assertNotIn('other-run', str(current))

    def test_does_not_filter_by_training_step_and_rejects_window_overlap(self):
        got = capture({'baseline': ['base-run'], 'current': ['current-run']}, self.snapshot)
        self.assertEqual(got['windows']['baseline']['sample_count'], 2)
        with self.assertRaises(InputError):
            capture({'baseline': ['same'], 'current': ['same']}, self.snapshot)

    def test_invalid_selection_shape_fails_clearly(self):
        with self.assertRaises(InputError):
            capture({'baseline': ['base-run']}, self.snapshot)


if __name__ == '__main__':
    unittest.main()
