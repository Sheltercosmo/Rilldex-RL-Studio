from copy import deepcopy
import unittest

from test_work_syntax_evidence import recorded, structural_case
from tracker import work_content_bindings as scoped, work_scope_interpretations as readings
from tracker import work_syntax_evidence as syntax
from tracker.schema import InputError


class SyntaxScopeCandidateTests(unittest.TestCase):
    def test_missing_group_is_proposed_without_reference_or_feature_scope(self):
        case, stored = recorded()
        p, b = case['packet'], case['bound']
        body = deepcopy(b['raw_response'])
        body['features'][0]['scopes'] = [['publish']]
        b = scoped.bind(p, scoped.request(p, b['unit_id']), body, 'omitted group control')
        groups = syntax.candidate_groups(p, b, stored['syntax'])
        self.assertEqual([g['content_ids'] for g in groups['groups']], [['inspect', 'validate']])
        self.assertFalse(groups['coverage']['all_multi_content_scopes'])
        base = readings.request(p, b, 'attachment')
        augmented = readings.request(p, b, 'attachment', syntax=stored['syntax'])
        self.assertFalse(any(r['content_ids'] == ['inspect', 'validate'] for r in base['state']['readings']))
        added = [r for r in augmented['state']['readings'] if r['content_ids'] == ['inspect', 'validate']]
        self.assertEqual({r['application'] for r in added}, {'individual', 'joint'})
        self.assertTrue({r['id'] for r in base['state']['readings']} <= {r['id'] for r in augmented['state']['readings']})

    def test_sentence_separation_does_not_prune_supplied_candidates(self):
        case, stored = recorded('shared-negation')
        p, b = case['packet'], case['bound']
        groups = syntax.candidate_groups(p, b, stored['syntax'])
        self.assertFalse(any('list' in g['content_ids'] for g in groups['groups']))
        body = deepcopy(b['raw_response']); body['features'][0]['scopes'] = [['delete', 'list']]
        b = scoped.bind(p, scoped.request(p, b['unit_id']), body, 'cross sentence supplied option')
        req = readings.request(p, b, 'attachment', syntax=stored['syntax'])
        self.assertTrue(any(r['content_ids'] == ['delete', 'list'] for r in req['state']['readings']))

    def test_partial_token_and_sentence_spanning_anchors_are_not_repaired(self):
        p, b, parsed = structural_case()
        body = deepcopy(b['raw_response']); body['contents'][0]['expression'] = {'text': 'Alpha'}
        b = scoped.bind(p, scoped.request(p, 'unit'), body, 'partial token')
        record = syntax.bind(p, b, parsed)
        groups = syntax.candidate_groups(p, b, record)
        self.assertEqual(groups['anchors']['alpha']['status'], 'unaligned_token_boundary')
        self.assertEqual(groups['groups'], [])
        body['contents'][0]['expression'] = {'text': 'Alpha. Beta.'}
        b = scoped.bind(p, scoped.request(p, 'unit'), body, 'multiple sentences')
        parsed['tokens'][-1].update(sentence=1, head=2, relation='ROOT')
        groups = syntax.candidate_groups(p, b, syntax.bind(p, b, parsed))
        self.assertEqual(groups['anchors']['alpha']['status'], 'multiple_sentence_span')

    def test_nested_groups_retain_smallest_tree_witness_without_flattening(self):
        p, b, parsed = structural_case()
        body = deepcopy(b['raw_response'])
        body['contents'].append(dict(id='symbol', kind='state', mode='asserted', expression=dict(text='🔬')))
        b = scoped.bind(p, scoped.request(p, 'unit'), body, 'structural nesting control')
        parsed['tokens'][2]['head'] = 1
        groups = syntax.candidate_groups(p, b, syntax.bind(p, b, parsed))['groups']
        self.assertEqual([(g['content_ids'], g['root_token_id']) for g in groups],
                         [(['alpha', 'beta'], 1), (['alpha', 'beta', 'symbol'], 0)])
        # The structural result says nothing about application, polarity or
        # which group the feature actually governs.
        self.assertTrue(all('application' not in g for g in groups))

    def test_syntax_receipt_is_required_for_augmented_decision_and_projection(self):
        case, stored = recorded(); p, b = case['packet'], case['bound']; record = stored['syntax']
        before = deepcopy((p, b, record))
        req = readings.request(p, b, 'attachment', syntax=record)
        chosen = next(r['id'] for r in req['state']['readings'] if r['content_ids'] == ['inspect', 'validate'] and r['application'] == 'individual')
        response = dict(model=req['model'], answers=dict(reading=dict(type='choice',
            probabilities={k:float(k == chosen) for k in req['questions']['reading']['criteria']})))
        decision = readings.resolve(p, b, 'attachment', response, syntax=record)
        view = readings.project(p, b, 'attachment', decision, syntax=record)
        self.assertEqual(len(view['individual_applications']), 2)
        self.assertEqual(view['publication'], 'review_only')
        with self.assertRaises(InputError): readings.project(p, b, 'attachment', decision)
        changed = deepcopy(record); changed['parsed']['parser']['model_version'] = 'different'
        with self.assertRaises(InputError): readings.request(p, b, 'attachment', syntax=changed)
        rebuilt = syntax.bind(p, b, changed['parsed'])
        with self.assertRaises(InputError): readings.project(p, b, 'attachment', decision, syntax=rebuilt)
        self.assertEqual((p, b, record), before)

    def test_reordering_contents_does_not_change_syntax_group_proposals(self):
        case, stored = recorded(); p, b = case['packet'], case['bound']; record = stored['syntax']
        body = deepcopy(b['raw_response']); body['contents'].reverse()
        other = scoped.bind(p, scoped.request(p, b['unit_id']), body, 'reordered')
        self.assertEqual(syntax.candidate_groups(p, b, record), syntax.candidate_groups(p, other, record))
        self.assertEqual(readings.request(p, b, 'attachment', syntax=record),
                         readings.request(p, other, 'attachment', syntax=record))


if __name__ == '__main__': unittest.main()
