"""Evidence isolation for the research ablation; no semantic reference labels."""
import copy
import unittest

from tracker.activity import packet, units
from tracker.activity_context import audit, visible_prefix
from research.activity_instruction_probe import restore_instructions
from test_activity import reasoning_run


class InstructionProbeTests(unittest.TestCase):
    def fixture(self):
        trajectory = reasoning_run()
        for i in range(1, 4):
            trajectory['events'].insert(i, {'id': f'user{i}', 'index': i-.5, 'kind': 'instruction',
                'actor': 'user', 'trajectory_id': 'main', 'text': f'Context 🧭 {i}', 'source_pointer': f'/followup/{i}'})
        subject = units(trajectory)[-1]
        return trajectory, subject

    def test_restores_source_only_and_preserves_decision_problem(self):
        trajectory, subject = self.fixture()
        for eid, extras in [('future', {'index': 100}), ('other', {'trajectory_id': 'other'}),
                            ('copy', {'copied_context': True}), ('external', {'kind': 'external_tool'})]:
            event = copy.deepcopy(trajectory['events'][1]); event.update(id=eid, text='EXCLUDED', **extras)
            trajectory['events'].append(event)
        original = packet(trajectory, subject['id']); before = copy.deepcopy(original)
        revised = restore_instructions(trajectory, original)
        self.assertEqual(original, before)
        self.assertEqual(revised['questions'], original['questions'])
        changed = [k for k in revised['state'] if revised['state'][k] != original['state'][k]]
        self.assertEqual(changed, ['authorized_instructions'])
        self.assertIn('user1', [e['id'] for e in revised['state']['authorized_instructions']])
        self.assertNotIn('EXCLUDED', str(revised))
        checked = audit(visible_prefix(trajectory, subject), revised['state'], subject)
        self.assertEqual(checked['status'], 'audited')
        self.assertEqual(checked['by_source_kind']['instruction']['omitted_events'], 0)

    def test_keeps_existing_clipping_contract_and_discloses_new_clip(self):
        trajectory, subject = self.fixture()
        trajectory['events'][1]['text'] = '🧭' * 5001
        original = packet(trajectory, subject['id'])
        revised = restore_instructions(trajectory, original)
        added = next(e for e in revised['state']['authorized_instructions'] if e['id'] == 'user1')
        self.assertEqual(len(added['text']), 5000)
        self.assertIn('user1', revised['state']['missingness']['truncated_event_ids'])
        self.assertEqual(revised['state']['missingness']['required_truncated_event_ids'],
                         original['state']['missingness']['required_truncated_event_ids'])
        checked = audit(visible_prefix(trajectory, subject), revised['state'], subject)
        self.assertEqual(checked['by_source_kind']['instruction']['partial_events'], 1)
        self.assertEqual(checked['by_source_kind']['instruction']['omitted_characters'], 1)

    def test_unchanged_instruction_context_is_an_identical_request(self):
        trajectory = reasoning_run(); subject = units(trajectory)[0]
        original = packet(trajectory, subject['id'])
        self.assertEqual(restore_instructions(trajectory, original), original)


if __name__ == '__main__': unittest.main()
