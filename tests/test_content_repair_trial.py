from copy import deepcopy
import unittest

from research.content_repair_trial import bind_redundant_subjects
from tracker.schema import InputError


class SubjectImportTests(unittest.TestCase):
    def setUp(self):
        self.request = {'source': {'event_id': 'e1', 'source_pointer': '/messages/0'}}
        self.body = {'candidates': [{'fields': {'summary': {'text': 'Original meaning', 'evidence': [
            {'subject': True, 'event_id': 'e1', 'source_pointer': '/messages/0'}]}}}]}

    def test_exact_redundant_identity_is_bound_and_input_is_preserved(self):
        before = deepcopy(self.body)
        adapted, changes = bind_redundant_subjects(self.body, self.request)
        self.assertEqual(self.body, before)
        self.assertEqual(adapted['candidates'][0]['fields']['summary'],
                         {'text': 'Original meaning', 'evidence': [{'subject': True}]})
        self.assertEqual(len(changes), 1)

    def test_conflicts_and_other_nonstandard_shapes_are_not_repaired(self):
        for key, value in [('event_id', 'e2'), ('source_pointer', '/messages/1'), ('subject', False), ('quote', 'guess')]:
            body = deepcopy(self.body)
            body['candidates'][0]['fields']['summary']['evidence'][0][key] = value
            with self.subTest(key=key), self.assertRaises(InputError):
                bind_redundant_subjects(body, self.request)


if __name__ == '__main__':
    unittest.main()
