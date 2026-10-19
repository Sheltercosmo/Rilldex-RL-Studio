"""Stored-unit chronology must agree across graph queries and distributions."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from tracker import graph_store, graph_queries, map_relationships
from tracker.graph_sequence import Ordering
from tests.test_work_episodes import example, edge


def fixture():
    run,g,actions=example(('inspect','change','continue'))
    keep={a['id'] for a in actions}
    g['nodes']=[n for n in g['nodes'] if n['kind']=='event' or n['id'] in keep]
    ids={n['id'] for n in g['nodes']};g['edges']=[e for e in g['edges'] if e['source'] in ids and e['target'] in ids]
    for i,a in enumerate(actions):
        n=next(n for n in g['nodes'] if n['id']==a['id']);n['activity']='inspect' if i==0 else 'construct'
    edge(g,actions[1],actions[0],'revises');edge(g,actions[1],actions[0],'uses_evidence')
    return run,g,actions

def events(g):return {n['properties']['id']:n['properties'] for n in g['nodes'] if n['kind']=='event'}


class GraphOrderAccuracyTests(unittest.TestCase):
    def test_captured_harbor_native_dispatches_keep_their_partial_order(self):
        data=json.loads((Path(__file__).parent/'fixtures/feature-membership/harbor-native-order.json').read_text())
        nodes=[dict(id='event:'+e['id'],kind='event',event_index=e['index'],trajectory_id=e['trajectory_id'],properties=e)
               for e in data['events']]
        order=Ordering(dict(nodes=nodes));self.assertEqual(len(nodes),245)
        grouped=[e for e in data['events'] if len(order.native.groups.get(e['id'],[]))>1]
        self.assertEqual(len(grouped),16)
        self.assertEqual(sum(order.before(a,b)=='parallel_dispatch' for a,b in zip(nodes,nodes[1:])),24)
        # Siblings have no serial order in either direction, regardless of the
        # order in which their transport records arrived.
        by_id={n['properties']['id']:n for n in nodes}
        for e in grouped:
            for sibling in order.native.groups[e['id']]:
                if sibling==e['id']:continue
                self.assertEqual(order.before(by_id[e['id']],by_id[sibling]),'parallel_dispatch')
        reversed_order=Ordering(dict(nodes=list(reversed(nodes))))
        self.assertEqual(reversed_order.native.groups,order.native.groups)

    def test_transition_matrix_is_scoped_to_recorded_sessions(self):
        _,g,a=fixture()
        for i,u in enumerate(a):events(g)[u['source']['event_id']]['context_id']='b' if i==1 else 'a'
        result=graph_store.matrices(g)
        self.assertEqual(result['transitions'],[dict(source='inspect',target='construct',count=1)])

    def test_unknown_order_does_not_become_activity_transitions(self):
        _,g,a=fixture();events(g)[a[1]['source']['event_id']]['order_known']=False
        result=graph_store.matrices(g)
        self.assertEqual(result['transitions'],[])
        self.assertEqual(result['transition_coverage']['excluded_pairs'],2)

    def test_native_parallel_envelope_cannot_become_a_revision_after_inspection(self):
        _,g,a=fixture()
        for u in a[:2]:
            event=events(g)[u['source']['event_id']];event.pop('parent_id',None);event['source_message_index']=17
        q=graph_queries.evaluate(g,graph_queries.PRESETS['revision_after_inspect'])
        self.assertEqual(q['matched_anchors'],0)
        self.assertIsNone(q['recorded_match_fraction'])
        self.assertEqual(len(q['unavailable_windows']),1)
        self.assertEqual({r['reason'] for r in map_relationships.inspect(g)['relationships']},
                         {'parallel_dispatch_reference'})

    def test_incomplete_native_batch_is_not_assumed_sequential(self):
        _,g,a=fixture();events(g)[a[1]['source']['event_id']]['batch_size']=2
        q=graph_queries.evaluate(g,graph_queries.PRESETS['revision_after_inspect'])
        self.assertEqual(q['unavailable_windows'][0]['order_blocker']['reason'],'parallel_dispatch')

    def test_copied_context_cannot_support_a_temporal_match(self):
        _,g,a=fixture();events(g)[a[1]['source']['event_id']]['copied_context']=True
        q=graph_queries.evaluate(g,graph_queries.PRESETS['revision_after_inspect'])
        self.assertEqual(q['unavailable_windows'][0]['order_blocker']['reason'],'unavailable_source')

    def test_exact_spans_retain_order_inside_an_unordered_record(self):
        _,g,a=fixture();one=next(n for n in g['nodes'] if n['id']==a[0]['id'])
        events(g)[a[0]['source']['event_id']]['order_known']=False
        two=deepcopy(one);two['id']='later-span';one['properties']['source'].update(start=0,end=5)
        two['properties']['source'].update(start=5,end=10)
        order=Ordering(g)
        self.assertIsNone(order.before(one,two))
        self.assertEqual(order.before(two,one),'overlapping_or_missing_spans')
        g['nodes'].append(two);g['edges']=[];edge(g,two,one,'revises')
        self.assertEqual(map_relationships.inspect(g)['incompatible'],0)

    def test_parallel_dispatch_does_not_erase_later_explicit_feedback_assessment(self):
        run,g,a=example(('first call','second call','review'))
        for u in a[:2]:
            e=events(g)[u['source']['event_id']];e.pop('parent_id',None);e['source_message_index']=17
        feedback=next(n for n in g['nodes'] if n['kind']=='unit' and n['event_index']==5)
        review=next(n for n in g['nodes'] if n['kind']=='unit' and n['event_index']==6)
        edge(g,feedback,a[1],'feedback_for');edge(g,review,feedback,'assesses')
        self.assertEqual(map_relationships.inspect(g)['incompatible'],0)

    def test_projection_retains_native_parallel_and_session_evidence(self):
        _,g,a=fixture()
        for u in a[:2]:
            e=events(g)[u['source']['event_id']];e.pop('parent_id',None);e['source_message_index']=17
        events(g)[a[2]['source']['event_id']]['context_id']='second'
        p=Ordering(g).projection(g)
        self.assertEqual(p['nodes'][a[0]['id']]['reason'],'parallel_dispatch')
        self.assertEqual(p['nodes'][a[2]['id']]['scope'][1],'second')

    def test_unknown_intervening_unit_does_not_supply_a_negative_query_window(self):
        _,g,a=fixture();events(g)[a[1]['source']['event_id']]['order_known']=False
        q=graph_queries.evaluate(g,graph_queries.PRESETS['revision_after_inspect'])
        self.assertEqual((q['anchors'],q['without_recorded_match']),(0,0))
        self.assertEqual(q['unavailable_windows'][0]['anchor'],a[0]['id'])

    def test_match_before_unknown_continuation_is_retained(self):
        _,g,a=fixture();events(g)[a[2]['source']['event_id']]['order_known']=False
        q=graph_queries.evaluate(g,graph_queries.PRESETS['revision_after_inspect'])
        self.assertEqual((q['anchors'],q['matched_anchors']),(1,1))
        self.assertEqual(q['cases'][0]['window_status'],'ordered_prefix')
        self.assertEqual(q['cases'][0]['inspected_window'],[a[1]['id']])

    def test_overlapping_same_record_units_are_not_arbitrarily_ordered_by_id(self):
        _,g,a=fixture();one=next(n for n in g['nodes'] if n['id']==a[0]['id'])
        two=deepcopy(one);two.update(id='overlap',activity='construct');g['nodes'].append(two)
        result=graph_store.matrices(g)
        self.assertEqual(result['transition_coverage']['reasons']['overlapping_or_missing_spans'],1)

    def test_reversed_input_list_cannot_change_transition_results(self):
        _,g,_=fixture();before=deepcopy(g)
        expected=graph_store.matrices(g);g['nodes'].reverse();g['edges'].reverse()
        self.assertEqual(graph_store.matrices(g),expected)
        self.assertEqual(before['nodes'],list(reversed(g['nodes'])))


if __name__=='__main__':unittest.main()
