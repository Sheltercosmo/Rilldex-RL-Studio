from copy import deepcopy
import unittest

from tracker.schema import digest
from tracker.work_history import build as history
from tracker.work_paths import build as paths
from tracker.work_patterns import build, project
from tests.test_work_paths import fixture


class WorkPatternTests(unittest.TestCase):
    def test_target_repeat_retains_intervening_prose_feedback_and_original_map(self):
        run, doc = fixture()
        doc['work_paths'] = paths(run, doc)
        doc['work_history'] = history(run, doc)
        before = deepcopy(doc)
        result = build(run, doc)
        self.assertEqual(doc, before)
        self.assertEqual(result['base_map_hash'], digest(doc))
        row = result['runs'][0]
        self.assertEqual(row['action_unit_ids'], ['1', '4'])
        self.assertEqual(row['copies'], [['1'], ['4']])
        self.assertTrue({'0', '1', '2', '3', '4', '5'} <= set(row['context']['focus_unit_ids']))
        self.assertEqual(result['counts']['repeated_operation_positions'], 1)

    def test_missing_operation_or_disputed_identity_never_forms_a_repeat(self):
        for issue in ['gap', 'identity', 'method']:
            run, doc = fixture()
            if issue == 'gap':
                run['events'][3].update(kind='action', actor='agent', trajectory_id='main', text='unselected action')
            if issue == 'identity':
                doc['review_notes'] = [{'kind': 'relation_review', 'unit_ids': ['4']}]
            if issue == 'method':
                doc['method_comparison'] = {'observations': [{'group_id': 'path-1', 'comparison': 'different_work'}]}
            doc['work_paths'] = paths(run, doc)
            doc['work_history'] = history(run, doc)
            self.assertEqual(build(run, doc)['runs'], [], issue)

    def test_projection_is_opt_in_and_preserves_observation_identity(self):
        run, doc = fixture()
        doc['work_paths'] = paths(run, doc)
        doc['work_history'] = history(run, doc)
        bundle = {'available': True, 'document': doc, 'observer': {'id': 'test'},
                  'raw_extraction': {'source_hash': digest(run)}, 'export_digest': 'original'}
        original = deepcopy(bundle)
        enriched = project(bundle, run)
        self.assertEqual(bundle, original)
        self.assertNotEqual(enriched['export_digest'], 'original')
        self.assertEqual(enriched['raw_extraction'], bundle['raw_extraction'])
        enriched['document'].pop('sequence_patterns')
        self.assertEqual(enriched['document'], doc)


if __name__ == '__main__':
    unittest.main()
