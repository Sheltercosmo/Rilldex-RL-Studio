"""Saved-graph projection controls; these do not measure detector accuracy."""
from copy import deepcopy
import unittest
from test_work_hierarchy import graph, finish
from tracker.work_hierarchy import build


def fixture():
    g = graph()
    for i, uid, kind in [(4, 'implementation', 'action'), (5, 'result', 'feedback')]:
        event = deepcopy(next(n for n in g['nodes'] if n['id'] == 'event:e1'))
        event.update(id='event:e'+str(i), event_index=i)
        event['properties'].update(id='e'+str(i), text='source '+str(i), kind=kind,
                                   actor='environment' if kind == 'feedback' else 'agent')
        g['nodes'].append(event)
        unit = deepcopy(next(n for n in g['nodes'] if n['id'] == 'action'))
        unit.update(id=uid, event_index=i)
        unit['properties'].update(kind=kind, actor=event['properties']['actor'],
            source=dict(event_id='e'+str(i), start=0, end=8, text='source '+str(i)))
        g['nodes'].append(unit)
        g['edges'].append(dict(id='ground-'+uid, source=uid, target=event['id'], type='grounded_in', properties={}))
    for uid, a, b, kind in [
        ('change', 'review', 'action', 'changes_attempt_procedure'),
        ('enact', 'implementation', 'review', 'attempts_declared_change'),
        ('same', 'implementation', 'action', 'same_action_target'),
        ('result-link', 'result', 'implementation', 'feedback_for')]:
        g['edges'].append(dict(id=uid, source=a, target=b, type=kind, properties={}))
    g['semantic_context'] = {'operation_results': {
        'e1': {'outcome':'failed', 'observations':[{'response_event_id':'e2'}]},
        'e4': {'outcome':'completed', 'observations':[{'response_event_id':'e5'}]}}}
    return finish(g)


class RevisionEpisodeTests(unittest.TestCase):
    def test_plan_replacement_keeps_its_later_decision_witness(self):
        from test_work_outline import fixture as outline_fixture
        from tracker import work_outline
        run,g,document,refs=outline_fixture()
        document['links'].append(dict(**{'from':'analytic','to':'numeric'},type='replaces',evidence=refs[6]))
        derived=work_outline.fork(g,document)
        self.assertEqual(build(derived,refs[5]['event_id'])['revision_episodes']['episodes'],[])
        result=build(derived);episode=result['revision_episodes']['episodes'][0]
        self.assertEqual(episode['kind'],'plan_replacement')
        self.assertEqual(episode['status'],'replacement_recorded')
        self.assertEqual(episode['results'],[])
        self.assertIn('event:'+refs[6]['event_id'],episode['node_ids'])

    def test_validated_operation_outcomes_survive_graph_storage(self):
        from test_operation_outcomes import sample
        from tracker.graph_store import build as graph_build
        run,bundle,outcomes=sample()
        bundle['document']['operation_outcomes']=outcomes
        bundle['observer']={'id':'test','label':'Test'}
        graph=graph_build(run,bundle)
        self.assertEqual(graph['semantic_context']['operation_results']['e4']['outcome'],'completed')
        self.assertEqual(build(graph,'e4')['revision_episodes']['operation_results'].get('b'),None)
        self.assertEqual(build(graph,'e5')['revision_episodes']['operation_results']['b']['outcome'],'completed')

    def test_full_chain_and_source_nodes(self):
        result=build(fixture()); episode=result['revision_episodes']['episodes'][0]
        self.assertEqual(episode['prior_outcome'], 'failed')
        self.assertEqual(episode['status'], 'follow_up_observed')
        self.assertEqual(episode['results'][0]['outcome'], 'completed')
        self.assertTrue({'review','action','implementation','result'} <= set(episode['node_ids']))
        self.assertTrue(set(episode['node_ids']) <= {n['id'] for n in result['nodes']})
        self.assertIn('not task correctness', episode['limits'])

    def test_legacy_transition_does_not_overwrite_captured_operation_result(self):
        g=fixture()
        g['semantic_context']['operation_results']['e1']['outcome']='completed'
        g['edges'].append(dict(id='legacy-recovery',source='implementation',target='action',
                               type='completed_after_failed_call',properties={}))
        episode=build(finish(g))['revision_episodes']['episodes'][0]
        self.assertEqual(episode['prior_outcome'],'completed')
        self.assertEqual(episode['impact']['operation']['status'],'retained')

    def test_cutoff_preserves_proposed_attempted_unknown_and_known(self):
        g=fixture()
        self.assertEqual(build(g,'e2')['revision_episodes']['episodes'], [])
        proposed=build(g,'e3')['revision_episodes']['episodes'][0]
        self.assertEqual(proposed['status'], 'declared_only')
        attempted=build(g,'e4')['revision_episodes']['episodes'][0]
        self.assertEqual(attempted['results'][0]['outcome'], 'not_established')
        self.assertNotIn('result',attempted['node_ids'])
        self.assertEqual(build(g,'e5')['revision_episodes']['episodes'][0]['results'][0]['outcome'], 'completed')
        self.assertEqual(proposed['id'],attempted['id'])

    def test_duplicate_witness_does_not_duplicate_episode(self):
        g=fixture(); e=deepcopy(next(e for e in g['edges'] if e['id']=='change'));e['id']='change2';g['edges'].append(e)
        result=build(finish(g))['revision_episodes']
        self.assertEqual(result['counts']['total'],1)
        self.assertTrue({'change','change2'} <= set(result['episodes'][0]['edge_ids']))

    def test_legacy_implementation_name_retains_dispatch_not_success(self):
        g=fixture()
        next(e for e in g['edges'] if e['id']=='enact')['type']='implements_declared_change'
        g['semantic_context']['operation_results']['e4']['outcome']='failed'
        e=build(finish(g))['revision_episodes']['episodes'][0]
        self.assertEqual(e['status'],'follow_up_observed')
        self.assertEqual(e['dimensions']['follow_through']['value'],'implementation_failed')
        self.assertEqual(e['dimensions']['consequence']['value'],'still_failed')
        self.assertEqual(set(e['dimensions']),{'trigger','target','follow_through','consequence'})

    def test_prerequisite_retry_needs_explicit_same_work_and_saved_cutoff(self):
        g=fixture()
        # The failed operation is revised by a distinct edit; the retry is the
        # later same-work action explicitly named by the saved correspondence.
        for suffix,index in [('retry',6),('returned',7)]:
            unit_id,event_id=('implementation','event:e4') if suffix=='retry' else ('result','event:e5')
            template=deepcopy(next(n for n in g['nodes'] if n['id']==unit_id))
            event=deepcopy(next(n for n in g['nodes'] if n['id']==event_id))
            event.update(id='event:e'+str(index),event_index=index);event['properties']['id']='e'+str(index)
            template.update(id=suffix,event_index=index);template['properties']['source']['event_id']='e'+str(index)
            g['nodes'] += [event,template]
            g['edges'].append(dict(id='ground-'+suffix,source=suffix,target=event['id'],type='grounded_in',properties={}))
        g['edges']=[e for e in g['edges'] if e['id']!='same']
        g['edges'].append(dict(id='retry-same',source='retry',target='action',type='same_action_target',properties={}))
        g['semantic_context']['operation_results']['e6']={'outcome':'completed','observations':[{'response_event_id':'e7'}]}
        self.assertEqual(build(finish(g))['revision_episodes']['episodes'][0]['results'],[])
        next(e for e in g['edges'] if e['id']=='enact')['properties']['cutoff']={'event_id':'e6'}
        e=build(finish(g))['revision_episodes']['episodes'][0]
        self.assertEqual([r['action_id'] for r in e['results']],['retry'])
        self.assertEqual(e['impact']['operation']['status'],'gain')
        self.assertEqual(build(finish(g),'e5')['revision_episodes']['episodes'][0]['results'],[])

    def test_assessment_or_unchanged_retry_is_not_a_revision(self):
        g=fixture();g['edges']=[e for e in g['edges'] if e['id']!='change']
        self.assertEqual(build(finish(g))['revision_episodes']['episodes'],[])

    def test_implementation_is_not_same_work_without_link(self):
        g=fixture();g['edges']=[e for e in g['edges'] if e['id']!='same']
        episode=build(finish(g))['revision_episodes']['episodes'][0]
        self.assertEqual(episode['status'],'implementation_linked')
        self.assertEqual(episode['results'],[])

    def test_cross_context_or_unknown_order_cannot_join(self):
        for field,value in [('context_id','other'),('order_known',False)]:
            g=fixture();next(n for n in g['nodes'] if n['id']=='event:e4')['properties'][field]=value
            episode=build(finish(g))['revision_episodes']['episodes'][0]
            self.assertEqual(episode['status'],'declared_only')

    def test_later_relation_witness_is_not_visible_early(self):
        g=fixture();next(e for e in g['edges'] if e['id']=='enact')['properties']['cutoff']={'event_id':'e5'}
        episode=build(finish(g),'e4')['revision_episodes']['episodes'][0]
        self.assertEqual(episode['status'],'declared_only')

    def test_prerequisite_action_links_exact_named_retry(self):
        g=fixture();e=next(e for e in g['edges'] if e['id']=='change');e['type']='adjustment_before_retry'
        e['properties'].update(via_action='implementation',retry_unit_id='implementation')
        g['edges']=[e for e in g['edges'] if e['id'] not in {'same','enact'}]
        episode=build(finish(g))['revision_episodes']['episodes'][0]
        self.assertEqual(episode['status'],'follow_up_observed')
        self.assertEqual(episode['change_kinds'],['local_adjustment'])


if __name__ == '__main__': unittest.main()
