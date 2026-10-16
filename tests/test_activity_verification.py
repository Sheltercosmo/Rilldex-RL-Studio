"""Request isolation and source integrity, not semantic accuracy tests."""
import copy
import unittest

from tracker.activity import packet, units, HARNESS as LIVE_HARNESS
from tracker.activity_verification import refine_verification, refine_verification_question, isolated_verification_request, HARNESS
from tracker.jev import observation_hash
from test_activity import reasoning_run


class VerificationContractTests(unittest.TestCase):
    def test_changes_contract_without_changing_evidence_options_or_other_questions(self):
        run = reasoning_run(); subject = units(run)[0]
        original = packet(run, subject['id']); frozen = copy.deepcopy(original)
        refined = refine_verification(original)
        self.assertEqual(original, frozen)
        self.assertEqual(refined['state']['harness'], HARNESS)
        for k in original['state']:
            if k not in {'harness', 'activity_definitions', 'annotation_boundaries'}:
                self.assertEqual(refined['state'][k], original['state'][k], k)
        self.assertEqual(set(refined['questions']), set(original['questions']))
        for k in original['questions']:
            if k != 'verify': self.assertEqual(refined['questions'][k], original['questions'][k], k)
            self.assertEqual(refined['questions'][k]['criteria'], original['questions'][k]['criteria'])
        if LIVE_HARNESS != HARNESS: self.assertNotEqual(observation_hash(refined), observation_hash(original))

    def test_refinement_is_idempotent_and_never_adds_future_evidence(self):
        run = reasoning_run();subject = units(run)[0]
        run['outcome']['secret'] = 'FUTURE_OUTCOME_NOT_VISIBLE'
        refined = refine_verification(packet(run, subject['id']))
        self.assertEqual(refine_verification(refined), refined)
        self.assertNotIn('FUTURE_OUTCOME_NOT_VISIBLE', str(refined))
        self.assertNotIn('Perhaps both roots', str(refined))
        self.assertEqual(refined['state']['cutoff_codepoint'], subject['end'])

    def test_question_scoped_variant_keeps_shared_definitions_and_all_other_questions(self):
        run=reasoning_run();original=packet(run,units(run)[0]['id']);before=copy.deepcopy(original)
        revised=refine_verification_question(original)
        self.assertEqual(original,before)
        self.assertEqual({k:v for k,v in revised['state'].items() if k!='harness'},
                         {k:v for k,v in original['state'].items() if k!='harness'})
        self.assertEqual({k:v for k,v in revised['questions'].items() if k!='verify'},
                         {k:v for k,v in original['questions'].items() if k!='verify'})
        self.assertEqual(revised['questions']['verify']['criteria'],original['questions']['verify']['criteria'])
        self.assertEqual(refine_verification_question(revised),revised)

    def test_isolated_request_preserves_evidence_but_cannot_claim_other_fields(self):
        run=reasoning_run();original=packet(run,units(run)[0]['id'])
        isolated=isolated_verification_request(original)
        self.assertEqual(set(isolated['questions']),{'verify'})
        self.assertEqual(isolated['questions']['verify']['criteria'],original['questions']['verify']['criteria'])
        self.assertEqual({k:v for k,v in isolated['state'].items() if k!='harness'},
                         {k:v for k,v in original['state'].items() if k!='harness'})
        self.assertNotEqual(observation_hash(isolated),observation_hash(original))
        self.assertEqual(set(original['questions'])-set(isolated['questions']),set(original['questions'])-{'verify'})


if __name__ == '__main__': unittest.main()
