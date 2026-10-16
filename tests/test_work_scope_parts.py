from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.test_work_declarations import fixture as source_fixture
from tracker import work_scope_parts as scope
from tracker.schema import InputError, digest
from tracker.semantic_extraction import Pipeline


def fixture(texts, works=None):
    run, doc = source_fixture(texts)
    local = {'schema': 'declared-work-pass/1', 'status': 'complete', 'source_hash': digest(run),
             'base_map_hash': digest(doc), 'observations': [
                 {'unit_id': u['id'], 'status': 'selected', 'items': [
                     {'id': 'w1', 'work': (works or texts)[i], 'declaration': 'commits', 'evidence': [u['source']]}]}
                 for i, u in enumerate(doc['units'])]}
    return run, doc, local


def selected(req):
    return {q: {'value': 'faithful' if q == 'faithfulness' else 'usable' if q == 'partition' else 'work'}
            for q in req['questions']}, digest(req)


class WorkScopePartTests(unittest.TestCase):
    def test_exact_coverage_and_unicode_offsets_are_work_wording_not_source(self):
        text = 'Create café data with synthetic rows to test the implementation.'
        parts = scope.fragments(text)
        self.assertEqual(''.join(p['text'] for p in parts), text)
        self.assertEqual(parts[0]['start'], 0)
        self.assertEqual(parts[-1]['end'], len(text))
        for p in parts:
            self.assertEqual(text[p['start']:p['end']], p['text'])
        run, doc, local = fixture(['I will make sample rows to test it.'], [text])
        result = scope.build(run, doc, local, selected)
        self.assertIn('not a verbatim source quote', result['observations'][0]['fragment_origin'])

    def test_repeated_item_ids_across_units_do_not_collide_or_change_units(self):
        run, doc, local = fixture(['Create report A.', 'Create report B.'])
        before = deepcopy(doc)
        result = scope.build(run, doc, local, selected)
        self.assertEqual([(r['unit_id'], r['item_id']) for r in result['observations']], [('u0', 'w1'), ('u1', 'w1')])
        self.assertEqual(result['coverage'], {'work_items': 2, 'selected': 2, 'needs_review': 0})
        self.assertEqual(doc, before)
        self.assertEqual(len(result['observations'][0]['groups']), 1)

    def test_cutoff_and_mutated_source_bindings(self):
        run, doc, local = fixture(['Create data to test it.', 'FUTURE_WORK_NOT_VISIBLE'])
        unit, item = scope.entries(run, doc, local)[0]
        req = scope.make_request(run, doc, local, unit, item)
        self.assertNotIn('FUTURE_', str(req))
        for variant in ('hash', 'duplicate', 'future', 'coverage'):
            bad = deepcopy(local)
            if variant == 'hash': bad['base_map_hash'] = 'wrong'
            if variant == 'duplicate': bad['observations'][0]['items'] *= 2
            if variant == 'future': bad['observations'][0]['items'][0]['evidence'] = [doc['units'][1]['source']]
            if variant == 'coverage': bad['observations'].reverse()
            with self.subTest(variant=variant), self.assertRaises(InputError): scope.build(run, doc, bad, selected)

    def test_unresolved_or_unfaithful_is_review_not_a_new_success_metric(self):
        run, doc, local = fixture(['Create data to test it.'])
        for override in ({'partition': 'needs_refinement'}, {'faithfulness': 'needs_revision'},
                         {'role_p1': 'unresolved'}, {'role_p0': 'purpose', 'role_p1': 'purpose'}):
            def decide(req):
                answers, key = selected(req)
                for q, value in override.items(): answers[q]['value'] = value
                return answers, key
            result = scope.build(run, doc, local, decide)
            self.assertEqual(result['coverage']['needs_review'], 1)
            self.assertNotIn('completed', str(result))

    def test_argmax_and_replay_ignore_top_level_confidence_and_choice(self):
        run, doc, local = fixture(['Create data to test it.'])
        def wire(req):
            winners, _ = selected(req); winners['role_p1']['value'] = 'purpose'
            return {'model': req['model'], 'answers': {
                q: {'type': 'choice', 'confidence': 0, 'choice': 'wrong',
                    'probabilities': {c: .51 if c == winners[q]['value'] else .49 / (len(s['criteria']) - 1)
                                      for c in s['criteria']}}
                for q, s in req['questions'].items()}}
        with TemporaryDirectory() as root:
            engine = Pipeline(Path(root), None, wire)
            result = scope.build(run, doc, local, engine.decide)
            self.assertEqual(result['observations'][0]['groups'][1]['role'], 'purpose')
            self.assertTrue(scope.audit(run, doc, local, result, root)['argmax_replayed'])
            replay = Pipeline(Path(root), None, lambda _: self.fail('No new API calls during replay'))
            self.assertEqual(scope.build(run, doc, local, replay.decide), result)
            bad = deepcopy(result); bad['observations'][0]['parts'][1]['role'] = 'work'
            with self.assertRaisesRegex(InputError, 'replay'): scope.audit(run, doc, local, bad, root)


if __name__ == '__main__': unittest.main()
