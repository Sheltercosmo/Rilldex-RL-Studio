from copy import deepcopy
import unittest
from unittest.mock import patch

from tracker.schema import digest
from tracker.work_history import build as history
from tracker.work_paths import build as paths
from tracker.work_patterns import build, project


def fixture(word='abxab'):
    events, units, relations, reviews, first, actions = [], [], [], [], {}, []

    def add(text, kind, actor='agent', trajectory='main'):
        uid = str(len(events))
        events.append({'id': 'e' + uid, 'index': len(events), 'text': text,
                       'kind': kind, 'actor': actor, 'trajectory_id': trajectory})
        units.append({'id': uid, 'kind': kind, 'actor': actor, 'trajectory_id': trajectory,
                      'source': {'event_id': 'e' + uid, 'start': 0, 'end': len(text)},
                      'content': {'summary': {'text': text}, 'target': {'text': text}}})
        return uid

    initial = add('Original request', 'semantic', 'user')
    for i, symbol in enumerate(word):
        if i == 3:
            changed = add('Changed requested terms', 'semantic', 'user')
            add('Other participant in the interval', 'action', 'helper')
            add('Separate trajectory', 'action', trajectory='other')
        prose = add('Expressed work: ' + symbol, 'semantic')
        action = add('Work ' + symbol, 'action')
        feedback = add('Response ' + symbol, 'feedback', 'environment')
        actions.append(action)
        relations.extend([{'from': prose, 'to': action, 'type': 'recorded_with'},
                          {'from': feedback, 'to': action, 'type': 'feedback_for'}])
        if symbol in first:
            relations.append({'from': action, 'to': first[symbol], 'type': 'same_action_target'})
        else:
            first[symbol] = action
        reviews.append({'action_unit_id': action, 'status': 'linked' if first[symbol] != action else 'none_of_these'})
    before = {'id': 'request', 'version_id': 'v1', 'kind': 'work', 'status': 'requested', 'trajectory_id': 'main', 'text': 'Original request'}
    after = {**before, 'version_id': 'v2', 'text': 'Changed requested terms'}
    change = {'record_id': 'request', 'operation': 'modify', 'before': before, 'after': after}
    doc = {'units': units, 'relations': relations, 'review_notes': [], 'action_target_review': reviews,
           'requested_work': {'status': 'complete', 'steps': [
               {'unit_id': initial, 'status': 'selected_update', 'state_after': [before], 'changes': []},
               {'unit_id': changed, 'status': 'selected_update', 'state_after': [after], 'changes': [change]}]}}
    run = {'events': events}
    doc['work_paths'] = paths(run, doc)
    doc['work_history'] = history(run, doc)
    return run, doc, actions


class ReturningWorkTests(unittest.TestCase):
    def test_return_keeps_units_request_cutoffs_and_all_participants_without_other_trajectories(self):
        run, doc, actions = fixture()
        original = deepcopy(doc)
        result = build(run, doc, include_returns=True)
        self.assertEqual(doc, original)
        self.assertEqual(result['version'], 'work-sequence-patterns/2')
        self.assertEqual(result['base_map_hash'], digest(doc))
        row, = result['returns']
        self.assertEqual(row['previous']['action_unit_ids'], actions[:2])
        self.assertEqual(row['current']['action_unit_ids'], actions[3:])
        self.assertEqual(row['gap']['action_unit_ids'], actions[2:3])
        focused = [u for u in doc['units'] if u['id'] in row['context']['focus_unit_ids']]
        self.assertTrue(any(u['actor'] == 'helper' for u in focused))
        self.assertTrue(any(u['actor'] == 'user' for u in focused))
        self.assertTrue(any(u['kind'] == 'feedback' for u in focused))
        self.assertTrue(all(u['trajectory_id'] == 'main' for u in focused))
        self.assertNotIn('dispatch_comparison', row['context'])
        for pair in row['comparisons']:
            scope = pair['context']['requested_scope']
            self.assertTrue(scope['version_state_changed'])
            self.assertEqual(scope['previous']['record_versions'][0]['version_id'], 'v1')
            self.assertEqual(scope['current']['record_versions'][0]['version_id'], 'v2')
            self.assertIsNone(pair['method_observation_index'])
            self.assertTrue(pair['context']['after_current_dispatch_unit_ids'])

    def test_missing_gap_action_keeps_its_position_and_original_source(self):
        run, doc, actions = fixture()
        missing = actions[2]
        doc['units'] = [u for u in doc['units'] if u['id'] != missing]
        doc['relations'] = [r for r in doc['relations'] if missing not in (r['from'], r['to'])]
        doc['work_paths'] = paths(run, doc)
        doc['work_history'] = history(run, doc)
        row, = build(run, doc, include_returns=True)['returns']
        self.assertEqual(row['gap']['operation_positions'], 1)
        self.assertEqual(row['gap']['action_unit_ids'], [])
        self.assertEqual(row['gap']['unrepresented_action_event_ids'], ['e' + missing])
        self.assertEqual(row['gap']['unresolved_identity_positions'], [3])
        self.assertTrue(any(r['event_id'] == 'e' + missing for r in row['context']['unrepresented_source_ranges']))

    def test_method_binding_requires_both_endpoints_and_group(self):
        run, doc, actions = fixture('abxayab')
        group = next(g['id'] for s in doc['work_history']['streams'] for g in s['groups'] if g['occurrences'][0]['unit_id'] == actions[0])
        wrong = {'group_id': group, 'previous_unit_id': actions[3], 'current_unit_id': actions[5], 'comparison': 'alternative_procedure'}
        doc['method_comparison'] = {'observations': [wrong]}
        row, = build(run, doc, include_returns=True)['returns']
        self.assertIsNone(row['comparisons'][0]['method_observation_index'])
        exact = {**wrong, 'previous_unit_id': actions[0], 'comparison': 'same_procedure'}
        doc['method_comparison']['observations'].append(exact)
        row, = build(run, doc, include_returns=True)['returns']
        self.assertEqual(row['comparisons'][0]['method_observation_index'], 1)
        self.assertEqual(row['comparisons'][0]['method_observation_hash'], digest(exact))

    def test_original_projection_remains_default_and_uninspected_scope_is_explicit(self):
        run, doc, _ = fixture()
        bundle = {'available': True, 'document': doc, 'observer': {'id': 'test'}, 'export_digest': 'saved'}
        old = project(bundle, run)
        new = project(bundle, run, include_returns=True)
        self.assertEqual(old['document']['sequence_patterns']['version'], 'work-sequence-patterns/1')
        self.assertEqual(old['document']['sequence_patterns']['runs'], new['document']['sequence_patterns']['runs'])
        self.assertNotEqual(old['export_digest'], new['export_digest'])
        self.assertEqual(new['document'].pop('sequence_patterns')['source_hash'], digest(run))
        self.assertEqual(new['document'], doc)
        with patch('tracker.returning_sequences.MAX_POSITIONS', 3):
            result = build(run, doc, include_returns=True)
        self.assertEqual(result['returns'], [])
        self.assertEqual(result['counts']['return_streams_uninspected'], 1)
        self.assertEqual(result['streams'][0]['return_scan']['status'], 'requires_segment_selection')


if __name__ == '__main__':
    unittest.main()
