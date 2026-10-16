import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker import graph_store as gs, behavior_sequences as seq, work_state as ws, investigation_plans as plans
from tracker.schema import InputError,digest
from tracker.store import Store


def captured():
    raw={'instance_id':'contract-test','problem_statement':'Repair the implementation and run its required test.',
         'trajectory':[{'thought':'Inspect failure','action':'pytest test_app.py','observation':'1 failed in 0.1s'},
                       {'thought':'Change implementation','action':'apply_patch','observation':'Applied'},
                       {'thought':'Check implementation','action':'pytest test_app.py','observation':'1 passed in 0.1s'},
                       {'thought':'Final edit','action':'apply_patch','observation':'Applied'},
                       {'thought':'Deliver','action':'submit','observation':'Submitted'}]}
    run=normalize(raw,'swe-agent')[0];actions=[e for e in run['events'] if e['kind']=='action'];returns=[e for e in run['events'] if e['kind']=='feedback']
    def snap(name,eid,app):return {'id':name,'event_id':eid,'environment':'env-v1','objects':{'app.py':app,'test_app.py':'test-v1','notes.txt':'n1'}}
    a,b,c,d,z=actions;ar,br,cr,dr,zr=returns
    capture={'schema':ws.CAPTURE,'snapshots':[snap('initial','e1','v1'),snap('fixed',br['id'],'v2'),snap('final',dr['id'],'v3')],
      'checks':[{'action_id':a['id'],'result_event_id':ar['id'],'snapshot_id':'initial','binding':'at_dispatch','criterion_id':'acceptance','criterion_version':'v1','required_objects':['app.py','test_app.py'],'result':'failed'},
                {'action_id':c['id'],'result_event_id':cr['id'],'snapshot_id':'fixed','binding':'at_dispatch','criterion_id':'acceptance','criterion_version':'v1','required_objects':['app.py','test_app.py'],'result':'passed'}],
      'edits':[{'action_id':b['id'],'result_event_id':br['id'],'before_snapshot_id':'initial','after_snapshot_id':'fixed'},
               {'action_id':d['id'],'result_event_id':dr['id'],'before_snapshot_id':'fixed','after_snapshot_id':'final'}],
      'deliveries':[{'event_id':z['id'],'snapshot_id':'final','requirements':[{'criterion_id':'acceptance','criterion_version':'v1','basis':'task'}]}]}
    raw['work_state']=capture
    for q in capture['checks']:q['state_stable']=True
    return normalize(raw,'swe-agent')[0]


def semantic(run,activities,skip=(),partial=False):
    events=[e for e in run['events'] if e['actor']=='agent'];units=[]
    for i,e in enumerate(events):
        if i in skip:continue
        end=len(e['text'])-1 if partial and i==0 else len(e['text'])
        units.append({'id':'u'+e['id'],'actor':'agent','kind':'semantic','activity':activities[i%len(activities)],
                      'source':{'event_id':e['id'],'text':e['text'][:end],'start':0,'end':end}})
    return gs.build(run,{'observer':{'id':'test-observer','label':'Test observer'},
                        'document':{'source_hash':digest(run),'units':units,'relations':[]}})


class WorkStateTests(unittest.TestCase):
    def test_recovery_and_later_edit_do_not_share_same_conclusion(self):
        out=ws.derive(captured());self.assertEqual(out['episodes'][0]['status'],'recovered')
        self.assertEqual(out['deliveries'][0]['status'],'changed_inputs')
        self.assertEqual(out['metrics']['recovery']['value'],1)

    def test_unrelated_edit_does_not_invalidate_scoped_check(self):
        run=captured();last=run['raw']['work_state']['snapshots'][-1];last['objects']['app.py']='v2';last['objects']['notes.txt']='n2'
        self.assertEqual(ws.derive(run)['deliveries'][0]['status'],'applicable_pass')

    def test_changed_criterion_cannot_count_as_original_recovery(self):
        run=captured();run['raw']['work_state']['checks'][1]['criterion_version']='weaker-v2'
        out=ws.derive(run);self.assertEqual(out['episodes'][0]['status'],'unknown');self.assertIsNone(out['metrics']['recovery']['value'])

    def test_unexecuted_or_unlinked_edit_is_not_an_adjustment(self):
        run=captured();run['raw']['work_state']['edits']=[]
        self.assertEqual(ws.derive(run)['episodes'][0]['status'],'unknown')
        run=captured();run['raw']['work_state']['edits'][0]['result_event_id']='e1'
        with self.assertRaises(InputError):ws.derive(run)

    def test_unknown_environment_and_missing_scope_prevent_applicability(self):
        run=captured();cap=run['raw']['work_state'];cap['edits'].pop();cap['snapshots'][-1]['environment']='env-v2'
        self.assertEqual(ws.derive(run)['deliveries'][0]['status'],'unknown')
        cap['snapshots'][-1]['environment']='env-v1';del cap['snapshots'][-1]['objects']['app.py']
        self.assertEqual(ws.derive(run)['deliveries'][0]['status'],'unknown')

    def test_future_snapshot_and_cross_lane_binding_rejected(self):
        run=captured();run['raw']['work_state']['checks'][0]['snapshot_id']='final'
        with self.assertRaisesRegex(InputError,'Future'):ws.derive(run)
        run=captured();run['events'][0]['trajectory_id']='other'
        with self.assertRaisesRegex(InputError,'Cross-trajectory'):ws.derive(run)

    def test_source_only_checks_do_not_invent_state_or_requirements(self):
        run=captured();del run['raw']['work_state'];out=ws.derive(run)
        self.assertEqual(len(out['checks']),2);self.assertEqual(out['checks'][1]['result'],'passed')
        self.assertIsNone(out['metrics']['recovery']['value']);self.assertEqual(out['deliveries'],[])
        self.assertEqual(out['metrics']['check_binding']['value'],0)

    def test_compound_commands_not_promoted_from_embedded_pytest(self):
        for command in ['false && pytest test.py','echo "1 passed"','pytest test.py; echo OK','pytest test.py | tee log']:
            self.assertNotEqual(ws.requested_operation({'text':command})['kind'],'check')

    def test_full_file_views_have_exact_line_coverage(self):
        e={'id':'e1','source_pointer':'/output','text':'[File: /a.py (2 lines total)]\n1:x = 1\n2:print(x)'}
        v=ws.full_file_view(e);self.assertEqual(v['content'],'x = 1\nprint(x)')
        e['text']='[File: /a.py (20 lines total)]\n1:x = 1\n20:print(x)';self.assertIsNone(ws.full_file_view(e))

    def test_duplicate_requirements_cannot_double_denominator(self):
        run=captured();req=run['raw']['work_state']['deliveries'][0]['requirements'];req.append(copy.deepcopy(req[0]))
        with self.assertRaisesRegex(InputError,'Duplicate'):ws.derive(run)

    def test_capture_cannot_override_contradictory_native_test_output(self):
        run=captured();run['raw']['work_state']['checks'][0]['result']='passed'
        with self.assertRaisesRegex(InputError,'contradicts'):ws.derive(run)

    def test_async_result_after_delivery_cannot_support_delivery(self):
        run=captured();cap=run['raw']['work_state'];check=cap['checks'][1];delivery=cap['deliveries'][0]
        late=next(e for e in run['events'] if e['id']==check['result_event_id']);late['index']=100
        self.assertNotEqual(ws.derive(run)['deliveries'][0]['status'],'applicable_pass')

    def test_concurrent_relevant_edit_and_unrecorded_stability_are_unknown(self):
        run=captured();run['raw']['work_state']['checks'][1].pop('state_stable')
        self.assertEqual(ws.derive(run)['episodes'][0]['status'],'unknown')
        run=captured();cap=run['raw']['work_state'];check=cap['checks'][1]
        result=next(e for e in run['events'] if e['id']==check['result_event_id']);result['index']=13
        self.assertEqual(ws.derive(run)['episodes'][0]['status'],'unknown')


class SequenceTests(unittest.TestCase):
    def test_sequence_preserves_base_activities_and_exact_unit_navigation(self):
        acts=['plan','orient','construct','report','inspect','reason','hypothesize','decide','verify','coordinate']
        graph=semantic(captured(),acts);out=seq.project(graph);blocks=out['paths'][0]['blocks']
        self.assertEqual([b['category'] for b in blocks],acts)
        self.assertEqual([m['unit_id'] for b in blocks for m in b['members']],
                         [n['id'] for n in sorted(graph['nodes'],key=lambda n:n['event_index']) if n['kind']=='unit'])
        self.assertEqual([b['position'] for b in blocks],list(range(1,11)))
        for b in blocks:
            self.assertEqual(b['members'][0]['activity'],b['category'])
            self.assertTrue(b['members'][0]['excerpt'])

    def test_equal_counts_keep_different_order(self):
        run=captured();a=seq.project(semantic(run,['inspect','inspect','construct','construct','verify','verify','report','report','plan','plan']))
        b=seq.project(semantic(run,['inspect','construct','verify','report','plan']))
        self.assertEqual(a['units'],b['units']);self.assertNotEqual(a['paths'],b['paths'])

    def test_missing_unit_is_gap_not_bridge(self):
        run=captured();out=seq.project(semantic(run,['inspect','construct'],skip=(1,)))
        self.assertEqual(out['paths'][0]['blocks'][1]['category'],'gap')
        self.assertFalse(any('ue2' in p['from_units'] for p in out['pairs']))

    def test_partial_span_is_retained_as_gap(self):
        out=seq.project(semantic(captured(),['inspect'],partial=True));self.assertGreater(out['gaps'],0)

    def test_overlapping_spans_not_double_counted(self):
        g=semantic(captured(),['inspect']);u=copy.deepcopy(next(n for n in g['nodes'] if n['kind']=='unit'));u['id']='duplicate';g['nodes'].append(u)
        out=seq.project(g);self.assertEqual(out['gaps'],1)

    def test_all_flow_columns_and_edges_preserve_population(self):
        run=captured();s=seq.project(semantic(run,['inspect','construct','verify']));out=seq.compare([s],[run['id']],[],width=3)['groups']['focus']
        for column in out['columns']:self.assertEqual(sum(c['count'] for c in column),1)
        for edges in out['links']:self.assertEqual(sum(e['count'] for e in edges),1)
        self.assertEqual(out['paths'][0]['categories'][-1],'tail')

    def test_unobserved_run_is_not_all_zero_behavior(self):
        run=captured();s=seq.project(gs.build(run));g=seq.compare([s],[run['id']],[])['groups']['focus']
        self.assertEqual(g['flow_eligible'],0);self.assertEqual(g['missing_or_multistream'],1);self.assertEqual(g['pair_rollouts'],0)

    def test_flow_stops_at_observed_end_instead_of_padding_empty_horizon(self):
        run=captured();s=seq.project(semantic(run,['orient']))
        out=seq.compare([s],[run['id']],[],width=10)
        self.assertEqual(out['width'],1)
        self.assertEqual(out['groups']['focus']['paths'][0]['categories'],['orient','end'])
        self.assertEqual(out['groups']['focus']['paths'][0]['hidden_blocks'],0)


class PlanTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.store=Store(Path(tmp.name)/'db.sqlite')
        self.run=captured();self.store.add([self.run]);self.graph=semantic(self.run,['inspect','construct','verify'])
        with self.store.connect() as c:gs.save(c,self.graph)
    def plan(self):
        p={'run_id':self.run['id'],'source_hash':digest(self.run),'graph_id':self.graph['id']}
        return {'schema':plans.VERSION,'nodes':[{'name':'s','op':'sequence','inputs':[],'params':p},
             {'name':'w','op':'work_state','inputs':[],'params':p},
             {'name':'f','op':'compare_sequences','inputs':['s'],'params':{'focus':[self.run['id']],'reference':[],'width':3}}]}
    def test_exact_replay_reuses_every_node_and_graph(self):
        a=plans.execute(self.store,self.plan());b=plans.execute(self.store,self.plan())
        self.assertEqual(a['id'],b['id']);self.assertEqual(a['outputs'],b['outputs']);self.assertEqual(b['execution']['cache_hits'],3)
        state=b['outputs']['w'];g=gs.read(self.store,state['graph_id']);self.assertTrue(any(e['type']=='checked_snapshot' for e in g['edges']))
        self.assertEqual(plans.read_output(self.store,state['id']),state)
    def test_downstream_change_reuses_upstream_nodes(self):
        p=self.plan();plans.execute(self.store,p);p['nodes'][-1]['params']['width']=7;b=plans.execute(self.store,p)
        self.assertEqual(b['execution']['cache_hits'],2);self.assertEqual(b['execution']['computed'],1)
    def test_cycles_wrong_types_and_source_mismatch_rejected(self):
        p=self.plan();p['nodes'][0]['inputs']=['f']
        with self.assertRaises(InputError):plans.execute(self.store,p)
        p=self.plan();p['nodes'][-1]['inputs']=['w']
        with self.assertRaises(InputError):plans.execute(self.store,p)
        p=self.plan();p['nodes'][0]['params']['source_hash']='wrong'
        with self.assertRaises(InputError):plans.execute(self.store,p)
    def test_corrupt_cache_does_not_silently_change_evidence(self):
        p=self.plan();r=plans.execute(self.store,p)
        with self.store.connect() as c:c.execute("UPDATE investigation_nodes SET document='{}' WHERE id=?",(r['manifest']['nodes'][0]['id'],))
        with self.assertRaisesRegex(InputError,'changed'):plans.execute(self.store,p)


if __name__=='__main__':unittest.main()
