"""Consistency controls, not semantic ground-truth accuracy tests."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import graph_store, work_subjects, work_scope_audit as audit
from tracker.schema import digest
from test_work_subjects import fixture, annotation


def case(names=('A', 'A'), relation='overlapping_work_scope'):
    _, graph, units = fixture(('Look up dates for both events.', 'Look up the second event.'))
    props = dict(pair_choice=audit.TYPES[relation][0], pair_request='authored-request',
        cutoff={k: units[1]['source'][k] for k in ('event_id', 'end')},
        evidence=[deepcopy(u['source']) for u in units])
    edge = dict(source=units[1]['id'], target=units[0]['id'], type=relation, properties=props)
    edge['id'] = 'edge-'+digest(edge)
    graph['edges'].append(edge)
    graph['edges'].sort(key=lambda e:e['id'])
    graph['counts']['edges'] = len(graph['edges'])
    graph['id'] = 'graph-'+digest({k:v for k,v in graph.items() if k!='id'})
    graph = work_subjects.fork(graph, annotation(graph, units, names))
    edge = next(e for e in graph['edges'] if e['id']==edge['id'])
    return graph, edge, units


class ScopeAuditTests(unittest.TestCase):
    def test_overlap_is_not_whole_work_identity_and_inputs_are_immutable(self):
        graph, edge, _ = case(); before = deepcopy(graph)
        result = audit.project(graph)
        self.assertEqual(result['state'], 'conflicts_found')
        self.assertEqual(result['counts']['conflict'], 1)
        self.assertEqual(result['affected_subject_ids'], ['A'])
        self.assertEqual(result['conflicts'][0]['evidence'], edge['properties']['evidence'])
        self.assertEqual(result['conflicts'][0]['bindings'][0]['subject']['label'], 'Target A')
        self.assertEqual(graph, before)
        self.assertEqual(result, audit.project(graph))
        self.assertEqual(result['id'], 'scope-audit-'+digest({k:v for k,v in result.items() if k!='id'}))

    def test_distinct_work_mappings_cannot_share_a_whole_work_subject(self):
        for relation in ('different_work_same_subject', 'similar_operation_distinct_target'):
            graph, _, _ = case(relation=relation)
            self.assertEqual(audit.project(graph)['counts']['conflict'], 1)

    def test_same_work_judgment_with_separate_subjects_is_also_a_conflict(self):
        graph, _, _ = case(('A', 'B'), 'same_action_target')
        result = audit.project(graph)
        self.assertEqual(result['affected_subject_ids'], ['A', 'B'])
        self.assertTrue(result['conflicts'][0]['expected_same'])

    def test_consistent_pairs_do_not_claim_independent_accuracy(self):
        for names, relation in [(('A', 'B'), 'overlapping_work_scope'), (('A','A'), 'same_action_target')]:
            graph, _, _ = case(names, relation); result = audit.project(graph)
            self.assertEqual(result['state'], 'no_conflicts_in_checked_pairs')
            self.assertEqual(result['counts']['consistent'], 1)
            self.assertEqual(result['affected_subject_ids'], [])
            self.assertIn('independent semantic accuracy remain unknown', result['scope'])

    def test_unresolved_membership_is_not_distinct_or_consistent(self):
        graph, _, _ = case(('A', None)); result = audit.project(graph)
        self.assertEqual(result['records'][0]['status'], 'unresolved_membership')
        self.assertIsNone(result['records'][0]['membership_same'])
        self.assertEqual(result['conflicts'], [])

    def test_absence_and_different_scope_are_explicit(self):
        _, graph, _ = fixture()
        self.assertEqual(audit.project(graph)['state'], 'work_membership_unavailable')
        graph, _, _ = case()
        doc = graph['semantic_context']['work_subjects']['document']
        doc['profile'] = dict(id='whole-task', version='1')
        self.assertEqual(audit.project(graph)['state'], 'scope_not_comparable')
        doc['profile'] = deepcopy(work_subjects.DEFAULT_PROFILE)
        graph['edges'] = [e for e in graph['edges'] if e['type'] not in audit.TYPES]
        self.assertEqual(audit.project(graph)['state'], 'no_comparable_pair_evidence')

    def assert_excluded(self, graph, reason):
        result = audit.project(graph)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['excluded'][0]['reason'], reason)

    def test_missing_receipt_or_mismatched_choice_is_excluded(self):
        for key in ('pair_request', 'pair_choice'):
            graph, edge, _ = case(); edge['properties'].pop(key)
            self.assert_excluded(graph, 'typed_pair_receipt_unestablished')

    def test_cutoff_and_source_order_are_required(self):
        graph, edge, _ = case(); edge['properties']['cutoff']['end'] += 1
        self.assert_excluded(graph, 'pair_cutoff_mismatch')
        graph, edge, _ = case(); edge['source'], edge['target'] = edge['target'], edge['source']
        self.assert_excluded(graph, 'prior_order_unestablished')

    def test_invalid_extra_evidence_and_future_evidence_are_excluded(self):
        for ref in (None, {'event_id': 'not-a-source'}):
            graph, edge, _ = case(); edge['properties']['evidence'].append(ref)
            self.assert_excluded(graph, 'invalid_source_evidence')
        graph, edge, units = case()
        event = deepcopy(next(n for n in graph['nodes'] if n['kind']=='event' and n['properties']['id']==units[1]['source']['event_id']))
        event['id'] = 'event:future'; event['properties']['id'] = 'future'; event['properties']['index'] += 1
        graph['nodes'].append(event)
        ref = deepcopy(units[1]['source']); ref['event_id'] = 'future'; edge['properties']['evidence'].append(ref)
        self.assert_excluded(graph, 'future_source_evidence')

    def test_missing_endpoint_evidence_is_excluded(self):
        graph, edge, _ = case(); edge['properties']['evidence'].pop()
        self.assert_excluded(graph, 'endpoint_source_evidence_missing')

    def test_cross_context_cannot_establish_identity(self):
        graph, _, units = case()
        event = next(n['properties'] for n in graph['nodes'] if n['kind']=='event' and n['properties']['id']==units[1]['source']['event_id'])
        event['context_id'] = 'different'
        self.assert_excluded(graph, 'different_actor_or_context')

    def test_parallel_tool_dispatch_has_no_known_previous_action(self):
        for field, value in [('parent_id','shared-dispatch'), ('source_message_index',0)]:
            graph, _, units = case()
            ids = {u['source']['event_id'] for u in units}
            for node in graph['nodes']:
                p = node['properties']
                if node['kind']=='event' and p['id'] in ids:
                    p['kind']='action'; p[field]=value
                if node['kind']=='unit': p['kind']='action'
            self.assert_excluded(graph, 'parallel_dispatch_order_unestablished')

    def test_retained_real_experiment_exposes_two_conflicts_without_recalculation(self):
        path = Path(__file__).resolve().parents[1]/'research/contribution-work-mapped-2026-10-12/retrieval/graph.json'
        before = path.read_bytes(); graph = json.loads(before); graph_store.validate(graph)
        result = audit.project(graph)
        self.assertEqual(result['counts']['checked_pairs'], 2)
        self.assertEqual(result['counts']['conflict'], 2)
        self.assertEqual(len(result['affected_subject_ids']), 1)
        self.assertEqual({r['relation'] for r in result['conflicts']}, {'overlapping_work_scope'})
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__': unittest.main()
