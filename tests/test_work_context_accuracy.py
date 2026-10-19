"""Recorded sessions and order must survive macro projection and its metrics."""
from copy import deepcopy
import unittest

from tracker import work_episodes, work_navigation, work_subjects, investigation_cases
from tracker.schema import digest
from tests.test_work_episodes import example, edge, unit_at
from tests.test_work_subjects import annotation
from tests.test_parallel_work_returns import fixture as parallel_fixture, graph as parallel_graph
from tracker import work_order


def events(graph):
    return {n['properties']['id']:n['properties'] for n in graph['nodes'] if n['kind']=='event'}


def contexts(graph, names):
    for event in events(graph).values():
        event['context_id']=names[event['index']//3]


class WorkContextAccuracyTests(unittest.TestCase):
    def test_cross_session_identity_does_not_merge_cards_or_count_recurrence(self):
        _,g,a=example(('A','A'));contexts(g,['first','second'])
        edge(g,a[1],a[0],'same_action_target')
        before=deepcopy(g);out=work_navigation.project(g)
        self.assertEqual(len(out['paths']),2)
        self.assertEqual(out['counts']['collapsed_consecutive_actions'],0)
        self.assertEqual(out['counts']['continued'],0)
        self.assertEqual(out['episodes'],[])
        self.assertFalse(out['links'])
        self.assertEqual(g,before)

    def test_other_sessions_do_not_create_intervening_work_in_same_session(self):
        _,g,a=example(('A','B','A'));contexts(g,['first',None,'first'])
        edge(g,a[2],a[0],'same_action_target')
        out=work_navigation.project(g)
        self.assertEqual(out['counts']['continued'],1)
        self.assertEqual(out['counts']['returned'],0)
        self.assertEqual(len(out['paths']),2)
        lookup={v['id']:v['context_id'] for v in out['visits']}
        self.assertTrue(all(lookup[e['source']]==lookup[e['target']] for e in out['links']))

    def test_reused_envelope_ids_across_sessions_are_not_a_parallel_batch(self):
        _,g,a=example(('A','B'));contexts(g,['first','second'])
        for action in a:
            events(g)[action['source']['event_id']].update(parent_id='reused',source_message_index=0)
        out=work_navigation.project(g)
        self.assertTrue(all(v['order_known'] for v in out['visits']))

    def test_message_index_identifies_parallel_dispatches_without_a_parent(self):
        _,g,a=example(('A','A'));contexts(g,['first','first'])
        for action in a:
            e=events(g)[action['source']['event_id']];e.pop('parent_id',None);e['source_message_index']=7
        edge(g,a[1],a[0],'same_action_target')
        out=work_navigation.project(g)
        self.assertTrue(all(not v['order_known'] for v in out['visits']))
        self.assertEqual(out['episodes'],[])

    def test_unknown_source_order_cannot_be_replaced_by_display_index(self):
        _,g,a=example(('A','A'));edge(g,a[1],a[0],'same_action_target')
        events(g)[a[1]['source']['event_id']]['order_known']=False
        out=work_navigation.project(g)
        self.assertEqual(out['episodes'],[])
        self.assertFalse(out['visits'][1]['order_known'])
        self.assertTrue(all(not e['order_known'] for e in out['links'] if e['type']=='recorded_next'))

    def test_complete_parallel_batch_cannot_override_explicitly_unknown_source_order(self):
        run,units=parallel_fixture()
        next(e for e in run['events'] if e['kind']=='action')['order_known']=False
        out=work_navigation.project(parallel_graph(run,units),recurrence_order=work_order.VERSION)
        self.assertEqual(out['counts']['returned'],0)
        self.assertEqual(out['counts']['interrupted'],1)
        proof=out['episodes'][0]['ordering']
        self.assertTrue(proof['parallel_groups'][0]['fully_bracketed'])
        self.assertIn('Source order is explicitly unestablished.',proof['blockers'])

    def test_foreign_evidence_cannot_support_a_local_identity(self):
        run,g,a=example();contexts(g,['first','second','first'])
        edge(g,a[2],a[0],'same_action_target',evidence=[a[1]['source']])
        self.assertEqual(work_episodes.project(g)['episodes'],[])

    def test_feedback_from_another_session_is_not_a_recovery_witness(self):
        run,g,a=example();contexts(g,['first','first','first'])
        edge(g,a[2],a[0],'same_action_target')
        returned=unit_at(g,run['events'][2]['id'])
        events(g)[returned['source']['event_id']]['context_id']='another'
        edge(g,returned,a[0],'feedback_for')
        out=work_episodes.project(g)
        self.assertEqual(len(out['episodes']),1)
        self.assertEqual(out['counts']['recurrences_with_feedback'],0)

    def test_foreign_plan_scope_does_not_attach_to_a_visit(self):
        run,g,a=example(('A','B'));contexts(g,['first','second'])
        origin=unit_at(g,run['events'][0]['id'])
        g['nodes'].append(dict(id='scope:foreign',kind='work_scope',properties=dict(source=origin['source'])))
        edge(g,a[1],'scope:foreign','in_work_scope')
        self.assertEqual(work_navigation.project(g)['visits'][1]['scope_ids'],[])

    def test_contribution_map_keeps_reused_session_envelopes_ordered(self):
        _,g,a=example(('A','B'));contexts(g,['first','second'])
        for action in a:events(g)[action['source']['event_id']]['parent_id']='reused'
        units=[]
        for node in g['nodes']:
            if node['kind']=='unit' and node['properties']['actor']=='agent':
                u=node['properties'];u.update(kind='action' if u['kind']=='action' else 'semantic',status='selected');units.append(u)
        g.pop('id');g['id']='graph-'+digest(g)
        names=['first' if events(g)[u['source']['event_id']]['context_id']=='first' else 'second' for u in units]
        out=work_subjects.project(work_subjects.fork(g,annotation(g,units,names)))
        self.assertEqual(len(out['visits']),2)
        self.assertTrue(all(v['order_known'] for v in out['visits']))

    def test_saved_legacy_cases_remain_frozen_and_readable(self):
        run,g,a=example(('A','A'));edge(g,a[1],a[0],'same_action_target')
        record=work_episodes.project(g);record['schema']='work-episodes/3'
        wrapper=work_episodes.compare([record],[run['id']],[]);wrapper['schema']='work-episodes/3'
        doc=dict(schema='failure-investigation/1',snapshot=dict(rows=[dict(id=run['id'],focus=True)],
                  process=dict(episodes=wrapper)))
        frozen=deepcopy(doc)
        rows,coverage,status,_=investigation_cases.material(doc,'recurrence')
        self.assertEqual(status,'available');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['projection_schema'],'work-episodes/3')
        self.assertEqual(coverage['projected_rollouts'],1);self.assertEqual(doc,frozen)


if __name__=='__main__':unittest.main()
