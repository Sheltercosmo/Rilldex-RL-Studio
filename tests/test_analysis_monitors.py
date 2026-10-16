import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import analysis_metrics as am, monitoring as m, monitor_evidence as evidence, graph_store as gs
from tracker import work_state, failure_investigations as investigations
from tracker.schema import InputError, digest, dumps
from tracker.store import Store
from test_work_episodes import example, edge
from test_investigation_process import captured


class AnalysisMonitorTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.store=Store(Path(tmp.name)/'db.sqlite')

    def monitor(self,measure='returns',observer='test',**kw):
        return m.create(self.store,{'name':measure,'kind':'analysis','observer':observer,'analysis':{'measure':measure},'group':'Behavior',**kw})

    def semantic(self,step=None,linked=True):
        run,g,actions=example();run['metadata'].update(experiment='analysis-test',training_step=step)
        run['id']=digest(run)[:24];g.update(run_id=run['id'],source_hash=digest(run),metadata=run['metadata'])
        g['semantic_context']['work_observations']['identity_reviews']=[{'action_unit_id':a['id'],'status':'selected' if i==2 and linked else 'none_of_these'} for i,a in enumerate(actions)]
        if linked:edge(g,actions[2],actions[0],'same_action_target')
        self.store.add([run]);self.save_graph(g);return run,g

    def save_graph(self,g):
        g.pop('id',None);g['edges'].sort(key=lambda e:e['id']);g['nodes'].sort(key=lambda n:n['id']);g['id']='graph-'+digest(g)
        with self.store.connect() as c:gs.save(c,g)

    def value(self,monitor,rid):return m.values(self.store,monitor['id'],{rid})[rid]

    def test_selector_pins_recipe_and_validates_source_contract(self):
        d=self.monitor();self.assertEqual(d['analysis']['version'],am.catalog()['returns']['version'])
        for measure,observer in [('returns','source'),('criterion_recovery','test'),('unrecognized','test')]:
            with self.assertRaises(InputError):self.monitor(measure,observer)
        with self.assertRaises(InputError):self.monitor(analysis={'measure':'returns','version':'invented'})

    def test_two_measures_reuse_one_projection_and_incremental_sync(self):
        run,g=self.semantic(1);a=self.monitor();b=self.monitor('adjusted_recurrences')
        m.sync(self.store);self.assertEqual(self.value(a,run['id'])['value'],1);self.assertEqual(self.value(b,run['id'])['value'],0)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0],1)
        self.assertEqual(m.sync(self.store)['inserted'],0)
        self.semantic(2);m.sync(self.store)
        points=m.snapshot(self.store)['monitors'][0]['series'][0]['points'];self.assertEqual([p['step'] for p in points],[1,2])

    def test_absent_semantic_observer_is_unavailable_not_zero(self):
        run,_=self.semantic(1);a=self.monitor(observer='missing');m.sync(self.store)
        v=self.value(a,run['id']);self.assertIsNone(v['value']);self.assertEqual(v['status'],'waiting')
        r=evidence.read(self.store,v['id']);self.assertEqual(r['explanation']['analysis_cases'],[])

    def test_historical_value_opens_original_graph_after_reannotation(self):
        run,g=self.semantic(1);a=self.monitor();m.sync(self.store);old=self.value(a,run['id'])
        g['edges']=[e for e in g['edges'] if e['type']!='same_action_target'];self.save_graph(g);m.sync(self.store)
        self.assertEqual(self.value(a,run['id'])['value'],0)
        r=evidence.read(self.store,old['id']);self.assertEqual(r['explanation']['value'],1)
        self.assertEqual(len(r['explanation']['analysis_cases']),1);self.assertFalse(r['freshness']['current_measurement'])
        self.assertEqual(r['graph']['id'],old['graph_id'])

    def test_old_extraction_version_cannot_classify_new_rollout(self):
        run,_=self.semantic(1);a=self.monitor();m.sync(self.store);old=self.value(a,run['id'])
        from tracker import work_episodes
        with patch.object(work_episodes,'VERSION','future-test-version'):
            later,_=self.semantic(2);m.sync(self.store);new=self.value(a,later['id'])
            self.assertIsNone(new['value']);self.assertEqual(new['status'],'error')
            self.assertEqual(evidence.read(self.store,old['id'])['explanation']['value'],1)

    def test_state_rates_have_bound_evidence_and_no_false_semantic_map_count(self):
        run=captured();self.store.add([run]);recovery=self.monitor('criterion_recovery','source');verification=self.monitor('delivery_verification','source')
        m.sync(self.store)
        a=self.value(recovery,run['id']);self.assertEqual((a['numerator'],a['denominator'],a['unknown']),(1,1,0))
        b=self.value(verification,run['id']);self.assertEqual((b['value'],b['denominator']),(0,1))
        receipt=evidence.read(self.store,a['id']);self.assertEqual(receipt['explanation']['analysis_cases'][0]['status'],'recovered')
        self.assertEqual(receipt['graph']['observer'],work_state.VERSION)
        self.assertEqual(m.snapshot(self.store)['runs'][0]['semantic_graphs'],0)

    def test_unknown_check_result_does_not_become_failed_delivery_verification(self):
        run=captured();capture=work_state.capture(run)
        # Bind delivery to the check's inputs, with the recorded result unresolved.
        capture['snapshots'][-1]['objects']['app.py']='v2';capture['checks'][-1]['result']='unknown'
        output=work_state.derive(run);v=output['metrics']['applicable_verification']
        self.assertEqual((v['value'],v['opportunities'],v['unknown']),(None,1,1))

    def test_opportunity_bins_pool_counts_and_keep_unresolved_opportunities(self):
        a=self.monitor('criterion_recovery','source')
        runs=[{'id':k,'metadata':{'experiment':'test','training_step':1}} for k in ('a','b','c')]
        rows={'a':{'value':1,'numerator':1,'denominator':1,'status':'available','opportunities':2,'unknown':1},
              'b':{'value':0,'numerator':0,'denominator':9,'status':'available','opportunities':9,'unknown':0},
              'c':{'value':None,'numerator':0,'denominator':0,'status':'unavailable','opportunities':3,'unknown':3}}
        result=m.chart(a,runs,rows);b=result['series'][0]['bins'][0]
        self.assertEqual((b['value'],b['opportunities'],b['unknown_opportunities']),(.1,14,4))

    def test_unplaced_observation_is_not_assigned_a_training_step(self):
        run,_=self.semantic();a=self.monitor();m.sync(self.store);result=m.snapshot(self.store)['monitors'][0]
        self.assertEqual(result['series'],[]);self.assertEqual(result['unplaced_points'][0]['run_id'],run['id'])

    def test_measurement_and_projection_must_reconcile(self):
        run,_=self.semantic(1);a=self.monitor();m.sync(self.store);v=self.value(a,run['id'])
        with self.assertRaises(InputError):evidence.read(self.store,v['id'],'wrong-run')
        altered={k:x for k,x in v.items() if k!='id'};altered['value']=4
        with self.assertRaisesRegex(InputError,'arithmetic'):am.receipt(self.store,altered,a)

    def test_analysis_measure_is_selectable_in_investigations(self):
        run,_=self.semantic(1);a=self.monitor();m.sync(self.store)
        result=investigations.snapshot(self.store,run=run['id'],observer='test',signal='monitor:'+a['id'],operator='ge',threshold=1)
        self.assertEqual(result['signal_positive'],1)

    def test_service_materializes_new_observation_without_browser_request(self):
        run,g=self.semantic(1);a=self.monitor();service=m.Service(self.store);self.addCleanup(service.close)
        end=time.monotonic()+8
        while time.monotonic()<end and not m.values(self.store,a['id'],{run['id']}):time.sleep(.05)
        self.assertEqual(self.value(a,run['id'])['value'],1)
        g['edges']=[e for e in g['edges'] if e['type']!='same_action_target'];self.save_graph(g)
        end=time.monotonic()+8
        while time.monotonic()<end and self.value(a,run['id'])['value']!=0:time.sleep(.1)
        self.assertEqual(self.value(a,run['id'])['value'],0);self.assertIsNone(service.status()['error'])

    def test_read_overlapping_materialization_requires_another_refresh(self):
        from unittest.mock import Mock
        service=Mock()
        for before,after in [({'revision':'a','updating':False},{'revision':'b','updating':False}),
                             ({'revision':'b','updating':True},{'revision':'b','updating':False})]:
            service.status.side_effect=[before,after]
            with patch.object(m,'snapshot',return_value={'monitors':[]}):result=m.live_snapshot(self.store,service)
            self.assertTrue(result['service']['snapshot_stale'])
        service.status.side_effect=[{'revision':'b','updating':False}]*2
        with patch.object(m,'snapshot',return_value={'monitors':[]}):self.assertFalse(m.live_snapshot(self.store,service)['service']['snapshot_stale'])


if __name__=='__main__':unittest.main()
