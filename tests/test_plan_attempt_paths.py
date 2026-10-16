"""Evidence-path invariants, including real saved software observations."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker.work_hierarchy import build
from test_work_hierarchy import graph, finish


class PlanAttemptPathsTests(unittest.TestCase):
    def test_assessment_is_bound_to_exact_feedback_not_next_comment(self):
        g=graph();out=build(g);path=out['stage_paths'][0]
        self.assertEqual(path['counts']['with_assessment'],1)
        self.assertEqual(path['rows'][0]['responses'][0]['assessments'][0]['node_id'],'review')
        g['edges']=[e for e in g['edges'] if e['type']!='assesses']
        self.assertEqual(build(finish(g))['stage_paths'][0]['counts']['with_assessment'],0)

    def test_multiple_roles_and_response_edges_do_not_duplicate_dispatches(self):
        g=graph();g['edges'].extend([
            dict(id='prepare',source='action',target='plan',type='prepares_plan_step',properties={'plan_step_id':'a'}),
            dict(id='response2',source='feedback',target='action',type='response_to',properties={})])
        p=build(finish(g))['stage_paths'][0]
        self.assertEqual(p['counts']['actions'],1);self.assertEqual(p['counts']['attempts'],1)
        self.assertEqual(p['counts']['preparations'],1)
        self.assertEqual(len(p['rows'][0]['responses']),1)
        self.assertEqual(len(p['rows'][0]['responses'][0]['link_ids']),2)

    def test_cutoff_removes_feedback_and_later_assessment(self):
        g=graph();early=build(g,'e1')['stage_paths'][0];later=build(g,'e2')['stage_paths'][0]
        self.assertEqual(early['counts']['with_feedback'],0)
        self.assertEqual(later['counts']['with_feedback'],1)
        self.assertEqual(later['counts']['with_assessment'],0)

    def test_foreign_actor_assessment_is_not_the_acting_agents_response(self):
        g=graph();next(n for n in g['nodes'] if n['id']=='review')['properties']['actor']='other'
        self.assertEqual(build(finish(g))['stage_paths'][0]['counts']['with_assessment'],0)

    def test_unlinked_stage_does_not_borrow_another_steps_actions(self):
        p=build(graph())['stage_paths'][1]
        self.assertEqual(p['rows'],[]);self.assertEqual(p['return_link_ids'],[])
        self.assertEqual(p['counts']['attempts'],0)

    def real(self):
        raw=json.loads(Path('research/work-hierarchy-2026-10-13/software-evidence.json').read_text(encoding='utf8'))
        return raw.get('graph',raw)

    def test_public_report_attempts_preserve_exact_recurrence_and_assessment(self):
        g=self.real();before=deepcopy(g);out=build(g);nodes={n['id']:n for n in out['nodes']}
        p=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        self.assertEqual(p['counts'],dict(actions=10,attempts=4,preparations=5,checks=1,with_feedback=10,with_assessment=9,returns=3))
        self.assertEqual([nodes[r['action_id']]['event_index']+1 for r in p['rows'] if 'attempts_plan_step' in r['roles']],[78,84,90,96])
        returns=[e for e in out['links'] if e['id'] in p['return_link_ids']]
        error=[e for e in returns if e['type']=='revisits_after_error_report']
        self.assertEqual([(nodes[e['source']]['event_index']+1,nodes[e['target']]['event_index']+1) for e in error],[(84,78)])
        self.assertEqual(len(returns),4) # 3 identity pairs, one supported error-return witness
        self.assertFalse(any(e['type']=='completed_after_failed_call' for e in returns))
        self.assertEqual(g,before)

    def test_return_relation_requires_both_current_step_memberships(self):
        g=self.real();g['edges']=[e for e in g['edges'] if not(e['type']=='attempts_plan_step' and e['source']=='s29aef5aea063e57134cc')]
        out=build(finish(g));p=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        self.assertEqual(p['counts']['returns'],2)
        self.assertNotIn('s29aef5aea063e57134cc',[r['action_id'] for r in p['rows']])
        self.assertIn('s29aef5aea063e57134cc',p['other_action_ids'])

    def test_return_evidence_cannot_leak_through_earlier_source_cutoff(self):
        g=self.real();out=build(g,'e83');p=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        self.assertEqual(p['counts']['attempts'],1);self.assertEqual(p['counts']['returns'],0)
        out=build(g,'e84');p=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        self.assertEqual(p['counts']['attempts'],2);self.assertEqual(p['counts']['returns'],1)
        self.assertEqual(p['rows'][-1]['responses'],[])


if __name__=='__main__':unittest.main()
