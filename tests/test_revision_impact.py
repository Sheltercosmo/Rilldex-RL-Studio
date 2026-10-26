from copy import deepcopy
import unittest
from test_revision_episodes import fixture
from test_work_hierarchy import finish
from tracker.work_hierarchy import build
from tracker import revision_impact as impact


def check_graph():
    g = fixture()
    def event(eid, index, kind):
        n = deepcopy(next(n for n in g['nodes'] if n['id'] == 'event:e1'))
        n.update(id='event:' + eid, event_index=index)
        n['properties'].update(id=eid, index=index, kind=kind, text=eid,
                               actor='agent' if kind == 'action' else 'environment')
        g['nodes'].append(n)
    # A second baseline criterion passes, while the first baseline fails.
    for n in g['nodes']:
        if n.get('event_index') is not None:
            n['event_index'] += 3
    for args in [('base2',1,'action'),('base2-result',2,'feedback'),('check1',9,'action'),('check1-result',10,'feedback'),('check2',11,'action'),('check2-result',12,'feedback')]:
        event(*args)
    def check(a,r,criterion,result,snapshot):
        return dict(action_id=a,result_event_id=r,criterion_id=criterion,criterion_version='v1',
                    result=result,snapshot_id=snapshot,required_objects=['parser'],state_stable=True,binding='at_dispatch')
    g['work_state_capture'] = dict(schema='work-state-capture/1',
        snapshots=[dict(id='before',event_id='base2',environment='test',objects={'parser':'v1'}),
                   dict(id='after',event_id='e5',environment='test',objects={'parser':'v2'})],
        edits=[dict(action_id='e4',result_event_id='e5',before_snapshot_id='before',after_snapshot_id='after')],
        checks=[check('e1','e2','original','failed','before'),check('base2','base2-result','nested','passed','before'),
                check('check1','check1-result','original','passed','after'),check('check2','check2-result','nested','failed','after')])
    return finish(g)


class RevisionImpactTests(unittest.TestCase):
    def test_capture_to_monitors_receipts_and_alerts(self):
        import tempfile
        from pathlib import Path
        from revision_impact_fixture import captured_revision
        from tracker.store import Store
        from tracker import graph_store, monitoring, monitor_evidence, monitor_alerts
        run, graph = captured_revision()
        from tracker.annotation_changes import _inventory
        _inventory(graph)
        projection = impact.project(graph)
        self.assertEqual([e['impact']['check_status'] for e in projection['episodes']], ['mixed','gain'])
        pair = projection['episodes'][0]['impact']['checks'][0]
        self.assertEqual(len(pair['before_node_ids']), 2)
        self.assertEqual(len(pair['after_node_ids']), 2)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,graph)
            monitors=[monitoring.create(store,dict(name=key,kind='analysis',observer=graph['observer'],group='Behavior',
                analysis={'measure':key},alert={'operator':'gt','threshold':0,'severity':'warning'})) for key in impact.MEASURES]
            self.assertEqual(monitoring.sync(store,[m['id'] for m in monitors])['errors'],0)
            for monitor in monitors:
                value=monitoring.values(store,monitor['id'],[run['id']])[run['id']]
                receipt=monitor_evidence.read(store,value['id'])
                self.assertTrue(receipt['explanation']['analysis_cases'])
                if monitor['analysis']['measure']=='revision_check_regression':
                    self.assertEqual((value['numerator'],value['denominator']),(1,4))
                    self.assertTrue(any(c['revision_impact']['impact']['check_status']=='mixed' for c in receipt['explanation']['analysis_cases']))
            self.assertTrue(monitor_alerts.snapshot(store)['alerts'])

    def test_gain_and_harm_coexist_with_same_denominator(self):
        output = impact.project(check_graph())
        episode = output['episodes'][0]
        self.assertEqual(episode['impact']['check_status'], 'mixed')
        for key in ('revision_check_gain', 'revision_check_regression'):
            value = impact.measure(output,key)
            self.assertEqual((value['numerator'],value['denominator']),(1,2))
        self.assertTrue({'event:check1-result','event:check2-result'} <= set(episode['node_ids']))

    def test_success_before_revision_can_regress(self):
        g=fixture()
        g['semantic_context']['operation_results']['e1']['outcome']='completed'
        g['semantic_context']['operation_results']['e4']['outcome']='failed'
        result=impact.measure(impact.project(finish(g)),'revision_operation_regression')
        self.assertEqual(result['value'],1)

    def test_missing_and_partial_never_become_harm_or_gain(self):
        for state in ('not_established','partial','pending'):
            self.assertEqual(impact.transition('failed',state),'unknown')
            self.assertEqual(impact.transition('completed',state),'unknown')

    def test_first_recheck_failure_not_replaced_by_later_success(self):
        g=check_graph();checks=g['work_state_capture']['checks']
        checks[2]['result']='failed'
        checks[3].update(criterion_id='original',result='passed')
        output=impact.project(finish(g))
        original=next(r for r in output['episodes'][0]['impact']['checks'] if r['criterion']=='original')
        self.assertEqual(original['status'],'still_failed')
        self.assertNotIn('event:check2-result',original['node_ids'])

    def test_prefix_never_leaks_future_result(self):
        episode=build(check_graph(),'check1')['revision_episodes']['episodes'][0]
        rows=episode['impact']['checks']
        self.assertTrue(all(r['status']=='unknown' for r in rows))
        self.assertNotIn('event:check1-result',episode['node_ids'])

    def test_changed_evaluator_state_scope_and_context_are_unresolved(self):
        for field,value in [('criterion_version','v2'),('required_objects',['other']),('state_stable',False)]:
            g=check_graph();g['work_state_capture']['checks'][2][field]=value
            row=next(r for r in impact.project(finish(g))['episodes'][0]['impact']['checks'] if r['criterion']=='original')
            self.assertEqual(row['status'],'unknown')
        g=check_graph();next(n for n in g['nodes'] if n['id']=='event:check1')['properties']['context_id']='other'
        rows=impact.project(finish(g))['episodes'][0]['impact']['checks']
        self.assertEqual(next(r for r in rows if r['criterion']=='original')['status'],'unknown')

    def test_declared_only_is_unknown_not_failed(self):
        g=fixture();result=build(g,'e3')['revision_episodes']['episodes'][0]['impact']
        self.assertEqual(result['operation']['status'],'unknown')
        self.assertEqual(result['implementation_dispatches'],0)

    def test_empty_population_is_unavailable(self):
        self.assertIsNone(impact.measure({'episodes':[]},'revision_check_regression')['value'])

    def test_same_check_pair_in_two_revision_scopes_counts_once(self):
        output=impact.project(check_graph())
        duplicate=deepcopy(output['episodes'][0]);duplicate['id']='second-work-scope'
        for row in duplicate['impact']['checks']:row['id']+='-second-scope'
        output['episodes'].append(duplicate)
        value=impact.measure(output,'revision_check_gain')
        self.assertEqual((value['numerator'],value['denominator']),(1,2))
        self.assertEqual(set(value['cases'][0]['episode_ids']),{output['episodes'][0]['id'],duplicate['id']})

    def test_saved_v1_receipts_keep_their_original_population(self):
        output=impact.project(check_graph())
        output['schema']='revision-impact/1'
        duplicate=deepcopy(output['episodes'][0]);duplicate['id']='second-work-scope'
        output['episodes'].append(duplicate)
        # Earlier receipts stored an episode-specific ID, without a shared-pair identity.
        for episode in output['episodes']:
            for row in episode['impact']['checks']:
                row.pop('pair_id')
                row['id'] += ':' + episode['id']
        value=impact.measure(output,'revision_check_gain')
        self.assertEqual((value['numerator'],value['denominator']),(2,4))
        self.assertTrue(all('episode_ids' not in case for case in value['cases']))
        self.assertEqual(value['coverage']['check_pairs'],4)

    def test_same_named_checks_for_different_objects_keep_both_results(self):
        g=check_graph()
        checks=g['work_state_capture']['checks']
        for snapshot in g['work_state_capture']['snapshots']:
            snapshot['objects']['lexer']=snapshot['objects']['parser']
        for check in checks:check['criterion_id']='unit-suite'
        for i in (1,3):checks[i]['required_objects']=['lexer']
        output=impact.project(finish(g))
        rows=output['episodes'][0]['impact']['checks']
        self.assertEqual(len(rows),2)
        self.assertEqual({tuple(r['changed_objects']):r['status'] for r in rows},{('parser',):'gain',('lexer',):'harm'})

    def test_gain_does_not_hide_unresolved_followup(self):
        g=check_graph();g['work_state_capture']['checks'].pop()
        episode=impact.project(finish(g))['episodes'][0]
        self.assertEqual(episode['impact']['check_status'],'gain')
        self.assertEqual(episode['impact']['check_coverage'],{'measured':1,'total':2,'unknown':1})
        self.assertIn('1 unresolved',episode['dimensions']['consequence']['label'])


if __name__=='__main__':unittest.main()
