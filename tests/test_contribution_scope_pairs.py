from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import contribution_scope_pairs as pairs, contribution_work as cw
from tracker.readable_context import contains, source_fragments
from tracker.schema import InputError, digest
from tracker.semantic_extraction import Pipeline
from test_contribution_work import source


def response(req):
    return {'model': req['model'], 'answers': {q: {'type': 'choice', 'choice': 'unresolved', 'confidence': 0,
        'probabilities': {k: .75 if k == 'partial_work_overlap' else .05 for k in spec['criteria']}}
        for q, spec in req['questions'].items()}}


class ContributionScopePairTests(unittest.TestCase):
    def test_all_pair_choices_are_retained_using_raw_argmax_and_exact_replay(self):
        run, _, units = source()
        with tempfile.TemporaryDirectory() as d:
            engine = Pipeline(d, None, response)
            result = pairs.compare(run, units[-1], units[:2], engine.decide)
            self.assertEqual(len(result['pairs']), 2)
            self.assertTrue(all(p['choice'] == 'partial_work_overlap' for p in result['pairs']))
            self.assertNotIn('bindings', result)
            other = Pipeline(d, None, lambda _: self.fail('No unchanged paid request'))
            self.assertEqual(pairs.compare(run, units[-1], units[:2], other.decide), result)

    def test_same_batch_future_cross_actor_and_missing_targets_are_rejected(self):
        run, _, units = source()
        with self.assertRaises(InputError): pairs.request(run, units[0], [units[-1]])
        with self.assertRaises(InputError): pairs.request(run, units[-1], [units[0], units[0]])
        with self.assertRaises(InputError): pairs.request(run, units[-1], [])
        bad = deepcopy(units[-1]); bad['content'].pop('work_target')
        with self.assertRaises(InputError): pairs.request(run, bad, [units[0]])
        # Real source-bound sibling dispatches in the retained public retrieval trace.
        r, _, us = cw.load('research/contribution-work-mapped-2026-10-12/retrieval')
        by_event = {u['source']['event_id']: u for u in us}
        with self.assertRaises(InputError): pairs.request(r, by_event['e8'], [by_event['e7']])
        rr = deepcopy(r)
        next(e for e in rr['events'] if e['id'] == 'e4')['actor'] = 'another-agent'
        with self.assertRaises(InputError): pairs.request(rr, by_event['e7'], [by_event['e4']])

    def test_real_packet_preserves_required_evidence_without_future_or_duplicate_field_text(self):
        run, _, units = cw.load('research/contribution-work-mapped-2026-10-12/retrieval')
        by_event = {u['source']['event_id']: u for u in units}
        current = by_event['e7']; priors = pairs.ordered_pool(run, units, current)
        before = deepcopy([current, *priors])
        req = pairs.request(run, current, priors)
        prefix = {e['id']: e for e in req['state']['prefix']}
        self.assertNotIn('e8', prefix); self.assertNotIn('e11', prefix)
        self.assertNotIn('text', req['state']['subject'])
        for unit in [current, *priors]:
            for ref in [unit['source'], *[r for f in unit['content'].values() for r in f.get('evidence', [])]]:
                event = prefix[ref['event_id']]
                self.assertTrue(contains(event, ref))
                self.assertTrue(any(s <= ref['start'] and ref['end'] <= s+len(t) and
                    t[ref['start']-s:ref['end']-s] == ref['text'] for s, t in source_fragments(event)))
        self.assertEqual([current, *priors], before)
        self.assertIn('operation', req['state']['current_contribution']['content'])
        self.assertIn('derivation', req['state']['prior_contributions'][0]['content'])

    def test_changed_source_content_or_criteria_requires_a_different_request(self):
        run, _, units = source()
        original = pairs.request(run, units[-1], units[:2])
        changed = deepcopy(units); changed[-1]['content']['work_target']['text'] = 'A different particular task'
        self.assertNotEqual(digest(original), digest(pairs.request(run, changed[-1], changed[:2])))
        with self.assertRaises(InputError): pairs.compare(run, units[-1], units[:2], lambda req: ({}, digest(req)))
        with self.assertRaises(InputError): pairs.compare(run, units[-1], units[:2],
            lambda req: ({q: {'value': 'made-up'} for q in req['questions']}, digest(req)))

    def test_target_revision_keeps_source_units_options_and_evidence_unchanged(self):
        run, _, units = source()
        old = pairs.request(run, units[-1], units[:2])
        new = pairs.request(run, units[-1], units[:2], version=pairs.TARGET_VERSION)
        for field in ('prefix', 'current_contribution', 'prior_contributions', 'context_policy', 'cutoff_codepoint'):
            self.assertEqual(old['state'][field], new['state'][field])
        self.assertNotEqual(digest(old), digest(new))
        for q in new['questions']:
            self.assertEqual(list(old['questions'][q]['criteria']), list(new['questions'][q]['criteria']))
        self.assertIn('Keep two axes separate', new['state']['comparison_rule'])
        with tempfile.TemporaryDirectory() as d:
            result = pairs.compare(run, units[-1], units[:2], Pipeline(d,None,response).decide,version=pairs.TARGET_VERSION)
            self.assertEqual(result['schema'], pairs.TARGET_VERSION)


if __name__ == '__main__': unittest.main()
