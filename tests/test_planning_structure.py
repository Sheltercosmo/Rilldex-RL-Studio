import copy
import unittest

from tracker.planning_structure import packet, HARNESS, SCOPES
from tracker.relation_contracts import source_plan_packet
from tracker.jev import validate_answers
from tracker.schema import InputError
from test_relation_contracts import evidence


class PlanningStructureTests(unittest.TestCase):
    def test_source_scope_stays_exact_and_old_plan_is_not_reused(self):
        records, source, _ = evidence(); before = copy.deepcopy(records)
        baseline = source_plan_packet(records, source)
        records[0].update(prior_plan='present', confidence=1, reward=1)
        request = packet(records, source)
        for field in ('source', 'prefix', 'cutoff_event_id', 'cutoff_codepoint', 'missingness'):
            self.assertEqual(request['state'][field], baseline['state'][field])
        self.assertNotIn('The total is 42', str(request['state']))
        self.assertNotIn('prior_plan', str(request))
        self.assertEqual(request['state']['harness'], HARNESS)
        self.assertEqual(set(request['questions']), {'own_intended_work', 'organizes_work', 'organization_scope'})
        self.assertEqual(records[0]['text'], before[0]['text'])

    def test_intent_does_not_force_structure_or_scope_and_confidence_is_ignored(self):
        records, source, _ = evidence(); request = packet(records, source)
        raw = {'answers': {
            'own_intended_work': {'type': 'choice', 'confidence': 0, 'choice': 'absent',
                                  'probabilities': {'present': .34, 'absent': .33, 'unresolved': .33}},
            'organizes_work': {'type': 'choice', 'confidence': 1, 'choice': 'present',
                              'probabilities': {'present': .33, 'absent': .34, 'unresolved': .33}},
            'organization_scope': {'type': 'choice', 'confidence': 0,
                                   'probabilities': {k: (1 if k == 'not_applicable' else 0) for k in SCOPES}}}}
        result = validate_answers(raw, request)
        self.assertEqual(result['own_intended_work']['value'], 'present')
        self.assertEqual(result['organizes_work']['value'], 'absent')
        self.assertEqual(result['organization_scope']['value'], 'not_applicable')
        # Even an inconsistent scope remains its selected answer for review.
        raw['answers']['organization_scope']['probabilities'] = {k: (1 if k == 'overall_task' else 0) for k in SCOPES}
        result = validate_answers(raw, request)
        self.assertEqual(result['organizes_work']['value'], 'absent')
        self.assertEqual(result['organization_scope']['value'], 'overall_task')

    def test_dispatch_wrong_actor_and_changed_source_are_rejected(self):
        records, source, _ = evidence()
        with self.assertRaises(InputError): packet([{**records[0], 'kind': 'action'}], source)
        with self.assertRaises(InputError): packet(records, {**source, 'actor_id': 'different'})
        with self.assertRaises(InputError): packet(records, {**source, 'text': 'x' * len(source['text'])})


if __name__ == '__main__': unittest.main()
