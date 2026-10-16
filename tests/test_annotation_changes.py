"""Annotation sensitivity controls; no independent semantic accuracy claims."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rilldex import Workspace
from tracker import annotation_changes as ac, graph_store, graph_queries, unit_reviews as ur
from tracker.schema import InputError
from tracker.store import Store
from test_feedback_opportunities import control, graph
from test_unit_reviews import document, unit_item
from tracker import semantic_extraction as sem


QUERY = graph_queries.PRESETS['assessment_of_inspection_feedback']


def fixture(texts=('The status is ready.', 'Proceed with the task.')):
    run, extraction, result = control(texts, choice='f0')
    g = graph(run, extraction, result)
    units = [n for n in g['nodes'] if n['kind'] == 'unit' and n['properties']['kind'] == 'semantic']
    return run, g, sorted(units, key=lambda n: n['event_index'])


class AnnotationChangesTests(unittest.TestCase):
    def test_identical_snapshot_and_id_renaming_do_not_create_annotation_drift(self):
        _, g, units = fixture(); renamed = deepcopy(g)
        names = {u['id']: 'new-'+u['id'] for u in units}
        for n in renamed['nodes']:
            if n['id'] in names:
                n['id'] = names[n['id']]; n['properties']['id'] = n['id']
        for e in renamed['edges']:
            e['source'] = names.get(e['source'], e['source'])
            e['target'] = names.get(e['target'], e['target'])
        renamed = ur.finish(renamed)
        for current in (g, renamed):
            value = ac.compare(g, current, requirements=[QUERY])
            self.assertEqual(value['units']['changed_aligned_units'], 0)
            self.assertEqual(value['units']['boundary_changes'], [])
            self.assertEqual(value['relationships']['changes'], [])
            self.assertEqual(value['measurements'][0]['changed_cases'], [])
            self.assertTrue(value['measurements'][0]['same_anchor_population'])

    def test_review_exposes_metric_sensitivity_and_dependency_invalidation_not_behavior_absence(self):
        run, g, units = fixture(('The status is ready.',))
        revised = ur.fork(run, g, document(run, g, units[0]['id'], 'orient'))
        baseline = deepcopy(g); current = deepcopy(revised)
        value = ac.compare(g, revised, requirements=[QUERY])
        self.assertEqual(value['units']['changed_aligned_units'], 1)
        self.assertEqual(value['units']['boundary_changes'], [])
        row = next(r for r in value['units']['aligned'] if r['activity_changed'])
        self.assertEqual((row['baseline']['activity'], row['current']['activity']), ('report', 'orient'))
        self.assertTrue(row['content_changes'])
        measure = value['measurements'][0]
        self.assertEqual(measure['baseline']['matched_anchors'], 1)
        self.assertEqual(measure['current']['matched_anchors'], 0)
        self.assertEqual(measure['delta']['recorded_match_fraction'], -1)
        self.assertIsNone(measure['current']['behavior_rate'])
        self.assertEqual(measure['changed_cases'][0]['change'], 'match_changed')
        self.assertTrue(value['review']['dependency_impact']['removed_edge_ids'])
        self.assertEqual(g, baseline); self.assertEqual(revised, current)

    def test_unicode_split_merge_preserves_exact_anchor_discipline(self):
        run, g, units = fixture(('Inspect 🌍 first. Then report.',))
        d = document(run, g, units[0]['id']); ref = units[0]['properties']['source']
        w = next(w for w in sem.windows(run) if w['id'] == d['window_id'])
        cut = ref['text'].index('Then')
        refs = sem.partition(run, w, [{'start': ref['start'], 'end': cut}, {'start': cut, 'end': ref['end']}])
        d['units'] = [unit_item(run, r, text=r['text']) for r in refs]
        split = ur.fork(run, g, d); value = ac.compare(g, split)
        self.assertEqual(value['units']['boundary_changes'][0]['kind'], 'split')
        self.assertEqual(len(value['units']['boundary_changes'][0]['current']), 2)
        self.assertFalse(any(r['baseline']['id'] == units[0]['id'] for r in value['units']['aligned']))
        self.assertEqual(ac.compare(split, g)['units']['boundary_changes'][0]['kind'], 'merged')

    def test_source_only_snapshot_keeps_unavailable_measures_null(self):
        run, g, _ = fixture(); empty = graph_store.build(run)
        result = ac.compare(g, empty, requirements=[QUERY]); measure = result['measurements'][0]
        self.assertIsNone(measure['current']['recorded_match_fraction'])
        self.assertIsNone(measure['delta']['recorded_match_fraction'])
        self.assertFalse(measure['same_anchor_population'])
        self.assertEqual(result['coverage']['current']['semantic_relations'], 'unavailable')
        self.assertTrue(all(r['kind'] == 'removed' for r in result['units']['boundary_changes']))

    def test_equal_anchor_counts_can_still_have_changed_populations(self):
        _, g, units = fixture(); changed = deepcopy(g)
        action = next(n for n in changed['nodes'] if n['kind'] == 'unit' and n['activity'] == 'inspect')
        action['activity'] = action['properties']['activity'] = 'construct'
        later = next(n for n in changed['nodes'] if n['id'] == units[0]['id'])
        later['activity'] = later['properties']['activity'] = 'inspect'
        changed = ur.finish(changed)
        result = ac.compare(g, changed, requirements=[QUERY])['measurements'][0]
        self.assertEqual(result['delta']['anchors'], 0)
        self.assertFalse(result['same_anchor_population'])
        self.assertEqual({r['change'] for r in result['changed_cases']}, {'anchor_added', 'anchor_removed'})

    def test_parallel_relationships_keep_multiplicity_and_evidence_changes(self):
        _, g, _ = fixture(); changed = deepcopy(g)
        old = next(e for e in changed['edges'] if e['type'] == 'assesses')
        new = deepcopy(old); new['id'] += '-second'; new['properties']['review_note'] = 'Additional independent evidence'
        changed['edges'].append(new); changed = ur.finish(changed)
        result = ac.compare(g, changed)
        self.assertEqual(sum(r['delta'] for r in result['relationships']['changes']), 1)
        self.assertTrue(result['relationships']['evidence_or_provenance_changes'])

    def test_no_transitions_between_actor_trajectories(self):
        run, ex, result = control(('One.', 'Two.'), choice='f0')
        ex['units'][-1]['trajectory_id'] = 'different-agent'
        run['events'][-1]['trajectory_id'] = 'different-agent'
        result['relations'] = []; result['observations'] = []
        g = graph(run, ex, result)
        counts = ac.compare(g, g)['observed_transitions']
        self.assertEqual(sum(r['baseline'] for r in counts), 1)

    def test_changed_source_stale_hash_wrong_attribution_and_overlap_rejected(self):
        _, g, units = fixture()
        changed = deepcopy(g); changed['source_hash'] = 'different'
        with self.assertRaisesRegex(InputError, 'same rollout'): ac.compare(g, ur.finish(changed))
        changed = deepcopy(g); changed['nodes'][0]['kind'] = 'tampered'
        with self.assertRaisesRegex(InputError, 'immutable identity'): ac.compare(g, changed)
        for field, replacement in [('text', 'wrong'), ('start', True), ('source_pointer', '/wrong')]:
            changed = deepcopy(g)
            next(n for n in changed['nodes'] if n['id'] == units[0]['id'])['properties']['source'][field] = replacement
            with self.subTest(field=field), self.assertRaises(InputError): ac.compare(g, ur.finish(changed))
        changed = deepcopy(g); dup = deepcopy(units[0]); dup['id'] += '-overlap'
        dup['properties']['source']['start'] += 1; dup['properties']['source']['text'] = dup['properties']['source']['text'][1:]
        changed['nodes'].append(dup)
        with self.assertRaisesRegex(InputError, 'Overlapping'): ac.compare(g, ur.finish(changed))
        changed = deepcopy(g)
        next(n for n in changed['nodes'] if n['id'] == units[0]['id'])['trajectory_id'] = 'other'
        with self.assertRaisesRegex(InputError, 'attribution'): ac.compare(g, ur.finish(changed))

    def test_query_limits_and_unrecognized_fields_fail_before_partial_results(self):
        _, g, _ = fixture()
        for qs in ([QUERY]*11, [{'question': 'incomplete'}], 'query'):
            with self.subTest(qs=qs), self.assertRaises(InputError): ac.compare(g, g, requirements=qs)

    def test_live_workspace_access_respects_scope_and_needs_no_exports_or_inference(self):
        run, g, units = fixture(); reviewed = ur.fork(run, g, document(run, g, units[0]['id']))
        with TemporaryDirectory() as directory:
            store = Store(Path(directory)/'workspace.sqlite'); store.add([run])
            with store.connect() as c:
                graph_store.save(c, g); graph_store.save(c, reviewed)
            with patch('tracker.jev.JevClient._post', side_effect=AssertionError('No model')):
                ws = Workspace(store.path)
                out = ws.annotation_changes(g['id'], reviewed['id'], requirements=[QUERY])
            self.assertEqual(out['new_model_calls'], 0)
            preview = ur.preview(store, document(run, g, units[0]['id']))
            self.assertEqual(preview['annotation_changes']['status'], 'available')
            self.assertTrue(preview['annotation_changes']['activities'])
            self.assertFalse(ws.results_path.exists())
            with self.assertRaises(InputError): Workspace(store.path, observer=g['observer']).annotation_changes(g['id'], reviewed['id'])
            with self.assertRaises(InputError): ws.annotation_changes(g['id'], reviewed['id'], limit=1)

    def test_legacy_overlap_does_not_block_a_valid_correction_preview(self):
        run, g, units = fixture(); broken = deepcopy(g)
        dup = deepcopy(units[0]); dup['id'] += '-duplicate'
        broken['nodes'].append(dup); broken = ur.finish(broken)
        with TemporaryDirectory() as directory:
            store = Store(Path(directory)/'workspace.sqlite'); store.add([run])
            with store.connect() as c: graph_store.save(c, broken)
            d = document(run, g, units[0]['id']); d['base_graph_id'] = broken['id']
            result = ur.preview(store, d)
            self.assertEqual(result['annotation_changes']['status'], 'unavailable')
            self.assertEqual(len(result['impact']['new_unit_ids']), 1)


if __name__ == '__main__': unittest.main()
