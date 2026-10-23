"""Retry counts are source-backed dispatch counts, not inferred struggle scores."""
from copy import deepcopy
import unittest

from tracker.work_hierarchy import retry_summary, attach_outline_evidence, build
import test_plan_attempt_paths as attempt_tests


def controls():
    rows = [dict(action_id=id, roles=[role]) for id, role in [('a','attempts_plan_step'),('b','attempts_plan_step'),('c','attempts_plan_step'),('check','checks_plan_step'),('prepare','prepares_plan_step')]]
    links = [dict(id=id, source=current, target=previous, type=kind) for id,current,previous,kind in [('same','b','a','same_action_target'),('error','b','a','revisits_after_error_report'),('second','c','b','same_action_target'),('older','c','a','same_action_target'),('check','check','b','same_action_target'),('prepare','prepare','b','revisits_after_error_report')]]
    comparisons = [dict(comparison=dict(current_node_id=a, previous_node_id=b, ordering='source_order'),link_ids=ids) for a,b,ids in [('b','a',['same','error']),('c','b',['second']),('c','a',['older']),('check','b',['check']),('prepare','b',['prepare'])]]
    return rows, comparisons, links


class RetrySummaryTests(unittest.TestCase):
    def test_split_later_attempt_keeps_all_witnesses_without_extra_retry(self):
        rows, comparisons, links = controls()
        rows.append(dict(action_id='b-fragment', dispatch_id='call-b', roles=['attempts_plan_step']))
        next(r for r in rows if r['action_id'] == 'b')['dispatch_id'] = 'call-b'
        links.append(dict(id='fragment-error', source='b-fragment', target='a', type='revisits_after_error_report'))
        comparisons.append(dict(comparison=dict(current_node_id='b-fragment', previous_node_id='a', ordering='source_order'),
            link_ids=['fragment-error']))
        out = retry_summary(rows, comparisons, links)
        self.assertEqual((out['attempts'], out['repeated_attempts'], out['after_reported_error']), (3, 2, 1))
        self.assertEqual(len(out['cases']), 3)  # Three annotation witnesses, two later dispatches.
        self.assertIn('fragment-error', {lid for c in out['cases'] for lid in c['link_ids']})

    def test_counts_unique_later_attempts_not_edges_checks_or_preparations(self):
        rows, comparisons, links = controls(); result=retry_summary(rows,comparisons,links)
        self.assertEqual((result['attempts'],result['repeated_attempts'],result['after_reported_error']),(3,2,1))
        self.assertEqual(result['cases'][0]['link_ids'],['error','same'])
        self.assertEqual(result['cases'][1]['previous_attempt_ids'],['a','b'])

    def test_unordered_or_missing_attempt_membership_is_excluded(self):
        rows, comparisons, links=controls(); comparisons[0]['comparison']['ordering']='unresolved'
        self.assertEqual(retry_summary(rows,comparisons,links)['after_reported_error'],0)
        rows=[r for r in rows if r['action_id']!='a']
        r=retry_summary(rows,comparisons,links);self.assertEqual(r['repeated_attempts'],1)
        self.assertEqual(r['cases'][0]['previous_attempt_ids'],['b'])

    def test_real_pdf_step_and_cutoff_preserve_unknown_recovery(self):
        graph=attempt_tests.PlanAttemptPathsTests().real(); before=deepcopy(graph)
        for cutoff,counts in [('e83',(1,0,0)),('e84',(2,1,1)),(None,(4,3,1))]:
            result=build(graph,cutoff);path=next(p for p in result['stage_paths'] if p['stage_id'].endswith(':convert'));r=path['retry_summary']
            self.assertEqual((r['attempts'],r['repeated_attempts'],r['after_reported_error']),counts)
            self.assertNotIn('success',r);self.assertEqual(r['coverage'],'saved_links_only')
        self.assertEqual(graph,before)

    def outline(self):
        return dict(items=[dict(id=id,work_kind=kind,source_node_ids=refs,state='No decision recorded') for id,kind,refs in [('root','objective',[]),('pdf','subgoal',[]),('approach','approach',['plan']),('draft','subgoal',['plan']),('convert','subgoal',['plan']),('other','subgoal',[])]],links=[dict(source=a,target=b,type='part_of') for a,b in [('pdf','root'),('approach','pdf'),('draft','approach'),('convert','approach'),('other','root')]])

    def test_outline_uses_unique_plan_binding_and_deduplicates_shared_attempt_membership(self):
        outline=self.outline(); r=retry_summary(*controls())
        rows=[dict(**row,role_link_ids=['role-'+row['action_id']],responses=[]) for row in controls()[0]]
        paths=[dict(stage_id=s,retry_summary=r,rows=rows) for s in ['stage1','stage2']]
        source={'plan':{'kind':'plan'},**{row['action_id']:{'event_index':i} for i,row in enumerate(rows)}}
        attach_outline_evidence(outline,paths,source,{'stage1':'plan','stage2':'plan'})
        items={n['id']:n for n in outline['items']}
        for id in ['root','pdf','approach']:
            self.assertEqual(items[id]['retry_summary']['repeated_attempts'],2)
            self.assertEqual(items[id]['retry_summary']['after_reported_error'],1)
            self.assertEqual(items[id]['state'],'No decision recorded')
        for id in ['draft','convert','other']:self.assertNotIn('retry_summary',items[id])

    def test_ambiguous_approach_binding_stays_unavailable_not_zero(self):
        outline=self.outline();outline['items'].append(dict(id='other-approach',work_kind='approach',source_node_ids=['plan']))
        attach_outline_evidence(outline,[dict(stage_id='stage',retry_summary=retry_summary(*controls()),rows=[])],{'plan':{'kind':'plan'}},{'stage':'plan'})
        self.assertFalse(any('retry_summary' in n for n in outline['items']))


if __name__=='__main__':unittest.main()
