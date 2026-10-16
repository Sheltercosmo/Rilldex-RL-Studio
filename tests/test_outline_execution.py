"""Exact evidence aggregation, not independently validated semantic judgments."""
from copy import deepcopy
import unittest
from tracker.work_hierarchy import attach_outline_evidence, build, retry_summary
from test_work_hierarchy import graph, finish
import test_work_retries as retry_tests


def project(g=None, cutoff=None, outline=None):
    hierarchy = build(g or graph(), cutoff)
    outline = outline or retry_tests.RetrySummaryTests().outline()
    items = {n['id']: n for n in hierarchy['nodes']}
    attach_outline_evidence(outline, hierarchy['stage_paths'], items,
        {'plan:a': 'plan', 'plan:b': 'plan'})
    return {n['id']: n for n in outline['items']}, hierarchy


class OutlineExecutionTests(unittest.TestCase):
    def test_direct_vs_inherited_evidence_never_changes_reports_or_decisions(self):
        nodes, hierarchy = project()
        for id, scope in [('approach', 'direct'), ('pdf', 'descendants'), ('root', 'descendants')]:
            evidence = nodes[id]['execution_summary']
            self.assertEqual(evidence['scope'], scope)
            self.assertEqual(evidence['counts'], dict(actions=1, attempts=1,
                preparations=0, checks=0, with_feedback=1, with_assessment=1))
            self.assertEqual(nodes[id]['state'], 'No decision recorded')
            row = evidence['rows'][0]
            self.assertEqual(row['memberships'][0]['stage_id'], 'plan:a')
            self.assertIn(row['memberships'][0]['role_link_ids'][0], {e['id'] for e in hierarchy['links']})
            self.assertEqual(row['responses'][0]['assessments'][0]['node_id'], 'review')
        for id in ['draft', 'convert', 'other']:
            self.assertNotIn('execution_summary', nodes[id])

    def test_temporal_cutoff_distinguishes_no_linked_actions_from_unmapped(self):
        expected = [('e0', 0, 0, 0), ('e1', 1, 0, 0), ('e2', 1, 1, 0), ('e3', 1, 1, 1)]
        for cutoff, actions, feedback, assessed in expected:
            with self.subTest(cutoff=cutoff):
                nodes, _ = project(cutoff=cutoff)
                c = nodes['approach']['execution_summary']['counts']
                self.assertEqual((c['actions'], c['with_feedback'], c['with_assessment']), (actions, feedback, assessed))
                self.assertNotIn('execution_summary', nodes['other'])

    def test_multi_stage_role_overlap_does_not_duplicate_action_or_feedback(self):
        g = graph()
        g['edges'].append(dict(id='check', source='action', target='plan', type='checks_plan_step', properties={'plan_step_id':'b'}))
        g['edges'].append(dict(id='response2', source='feedback', target='action', type='response_to', properties={}))
        nodes, _ = project(finish(g)); e = nodes['root']['execution_summary']
        self.assertEqual(e['counts']['actions'], 1)
        self.assertEqual((e['counts']['attempts'], e['counts']['checks']), (1, 1))
        self.assertEqual(e['counts']['with_feedback'], 1)
        self.assertEqual(e['counts']['with_assessment'], 1)
        self.assertEqual(len(e['rows'][0]['memberships']), 2)
        self.assertEqual(len(e['rows'][0]['responses']), 1)
        self.assertEqual(len(e['rows'][0]['responses'][0]['link_ids']), 2)
        self.assertEqual(len(e['rows'][0]['responses'][0]['assessments']), 1)

    def test_multiple_responses_partial_assessment_counts_one_action(self):
        h = build(graph()); path = h['stage_paths'][0]
        path['rows'][0]['responses'].append(dict(node_id='other-feedback', link_ids=['rf2'], assessments=[]))
        outline = retry_tests.RetrySummaryTests().outline()
        items = {n['id']: n for n in h['nodes']}; items['other-feedback'] = {'event_index':2}
        attach_outline_evidence(outline, h['stage_paths'], items, {'plan:a':'plan','plan:b':'plan'})
        e = outline['items'][0]['execution_summary']
        self.assertEqual(e['counts']['with_assessment'], 1)
        self.assertEqual(len(e['rows'][0]['responses']), 2)
        self.assertEqual(e['rows'][0]['responses'][1]['assessments'], [])

    def test_ambiguous_binding_is_unavailable_and_does_not_leak_to_parent(self):
        outline = retry_tests.RetrySummaryTests().outline()
        outline['items'].append(dict(id='other-owner', work_kind='approach', source_node_ids=['plan']))
        nodes, _ = project(outline=outline)
        self.assertFalse(any('execution_summary' in n for n in nodes.values()))

    def test_diamond_parentage_deduplicates_and_mixed_scope_remains_explicit(self):
        outline = retry_tests.RetrySummaryTests().outline()
        outline['links'].append(dict(source='approach', target='other', type='part_of'))
        nodes, _ = project(outline=outline)
        self.assertEqual(nodes['root']['execution_summary']['counts']['actions'], 1)
        self.assertEqual(nodes['other']['execution_summary']['scope'], 'descendants')
        h = build(graph()); items = {n['id']:n for n in h['nodes']}
        items['second-plan'] = dict(kind='plan')
        outline = retry_tests.RetrySummaryTests().outline()
        outline['items'].append(dict(id='child-approach', work_kind='approach', source_node_ids=['second-plan']))
        outline['links'].append(dict(source='child-approach', target='approach', type='part_of'))
        second = deepcopy(h['stage_paths'][0]); second['stage_id'] = 'second:a'
        attach_outline_evidence(outline, [*h['stage_paths'], second], items,
            {'plan:a':'plan','plan:b':'plan','second:a':'second-plan'})
        e = next(n for n in outline['items'] if n['id']=='approach')['execution_summary']
        self.assertEqual(e['scope'], 'mixed'); self.assertEqual(e['counts']['actions'], 1)
        self.assertEqual(len(e['rows'][0]['memberships']), 2)

    def test_repeatable_immutable_projection_and_foreign_assessment_exclusion(self):
        g = graph(); before = deepcopy(g)
        a, _ = project(g); b, _ = project(g)
        self.assertEqual(g, before); self.assertEqual(a, b)
        next(n for n in g['nodes'] if n['id']=='review')['properties']['actor'] = 'other'
        nodes, _ = project(finish(g))
        self.assertEqual(nodes['approach']['execution_summary']['counts']['with_assessment'], 0)


if __name__ == '__main__': unittest.main()
