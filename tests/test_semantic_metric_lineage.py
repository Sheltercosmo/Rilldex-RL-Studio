import copy
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from tracker import graph_store, monitoring, monitor_evidence, failure_investigations
from tracker.adapters import normalize
from tracker.rollout_metrics import record_map,save,source_record
from tracker.schema import digest
from tracker.store import Store
from tracker.analytics import Analysis
from test_tracker import harbor


class SemanticMetricLineageTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'study.sqlite')
        self.run=normalize(harbor(),'harbor',{'experiment':'train','training_step':0})[0]
        self.store.add([self.run]);event=next(e for e in self.run['events'] if e['actor']=='agent')
        self.bundle={'observer':{'id':'review','label':'Review'},'document':{'source_hash':digest(self.run),
            'units':[{'id':'u','kind':'semantic','actor':'agent','activity':'verify',
                'source':{'event_id':event['id'],'start':0,'end':len(event['text']),'text':event['text']}}],
            'relations':[]}}
        self.record=record_map(self.store,self.run,self.bundle)
        self.monitor=monitoring.create(self.store,{'name':'Verify share','kind':'metric','observer':'review','metric':'agent_verify_unit_share'})
        monitoring.sync(self.store,monitor_ids={self.monitor['id']})
        self.old=self.case()

    def case(self):
        return monitoring.cases(self.store,self.monitor['id'])['rows'][0]['measurement']

    def test_changed_map_without_metric_publication_is_a_gap_not_old_value(self):
        changed=copy.deepcopy(self.bundle);changed['document']['units'][0]['activity']='orient'
        with self.store.connect() as c:graph_store.save(c,graph_store.build(self.run,changed))
        self.assertIsNone(self.case()['value'])
        self.assertFalse(monitor_evidence.read(self.store,self.old['id'])['freshness']['current_measurement'])
        self.assertEqual(Analysis(self.store.path).table('measurements',observer='review')['rows'],[])
        self.assertTrue(all(r['is_current']==0 for r in Analysis(self.store.path).table('measurements',observer='review',history=True)['rows']))
        result=failure_investigations.snapshot(self.store,run=self.run['id'],observer='review')
        metric=next(m for m in result['metrics'] if m['id']=='observation:agent_verify_unit_share')
        self.assertEqual(metric['focus']['n'],0)
        monitoring.sync(self.store,monitor_ids={self.monitor['id']})
        self.assertEqual(self.case()['status'],'waiting')
        self.assertIn('map',self.case()['reason'])
        proof=monitor_evidence.read(self.store,self.old['id'])
        self.assertEqual(proof['measurement']['value'],1)
        self.assertEqual(proof['graph']['id'],self.record['graph_id'])
        self.assertFalse(proof['freshness']['current_measurement'])
        record_map(self.store,self.run,changed)
        monitoring.sync(self.store,monitor_ids={self.monitor['id']})
        self.assertEqual(self.case()['value'],0)

    def test_derived_projection_change_reuses_observation_and_receipt(self):
        changed=copy.deepcopy(self.bundle);changed['document']['sequence_patterns']={'schema':'projection/2'}
        again=record_map(self.store,self.run,changed)
        self.assertEqual(again,self.record)
        self.assertEqual(self.case()['value'],1)
        monitoring.sync(self.store,monitor_ids={self.monitor['id']})
        self.assertEqual(self.case()['id'],self.old['id'])

    def test_late_old_observation_does_not_displace_matching_current_map(self):
        changed=copy.deepcopy(self.bundle);changed['document']['units'][0]['activity']='orient'
        newer=record_map(self.store,self.run,changed)
        late=copy.deepcopy(self.record);late['scope']='An older worker completed late'
        with self.store.connect() as c:save(c,late)
        monitoring.sync(self.store,monitor_ids={self.monitor['id']})
        self.assertEqual(self.case()['value'],0)
        rows=Analysis(self.store.path).table('measurements',observer='review')['rows']
        self.assertEqual({r['measurement_id'] for r in rows},{digest(newer)})
        self.assertTrue(all(r['is_current']==1 and r['is_latest']==0 for r in rows))

    def test_independent_source_observer_does_not_borrow_a_map_dependency(self):
        independent=source_record(self.run);independent.update(observer='independent',observation_kind='diagnostics')
        with self.store.connect() as c:save(c,independent)
        monitor=monitoring.create(self.store,{'name':'Independent observation','kind':'metric','observer':'independent','metric':'actions'})
        monitoring.sync(self.store,monitor_ids={monitor['id']})
        self.assertIsNotNone(monitoring.cases(self.store,monitor['id'])['rows'][0]['measurement']['value'])

    def test_legacy_graph_without_new_header_keeps_its_exact_binding(self):
        graph=graph_store.build(self.run,self.bundle);graph.pop('metric_input_hash');graph.pop('id');graph['id']='graph-'+digest(graph)
        legacy=copy.deepcopy(self.record);legacy['graph_id']=graph['id']
        with self.store.connect() as c:graph_store.save(c,graph);save(c,legacy)
        monitoring.sync(self.store,monitor_ids={self.monitor['id']})
        self.assertEqual(self.case()['value'],1)

    def test_missing_declared_graph_is_not_current_even_with_matching_source(self):
        missing=copy.deepcopy(self.record);missing.update(observer='missing-map',graph_id='graph-missing')
        with self.store.connect() as c:save(c,missing)
        self.assertEqual(Analysis(self.store.path).table('measurements',observer='missing-map')['rows'],[])
        self.assertTrue(Analysis(self.store.path).table('measurements',observer='missing-map',history=True)['rows'])

    def test_pinned_read_keeps_matching_measurement_during_a_graph_update(self):
        changed=copy.deepcopy(self.bundle);changed['document']['units'][0]['activity']='orient'
        with Analysis(self.store.path).snapshot() as snapshot:
            with self.store.connect() as c:graph_store.save(c,graph_store.build(self.run,changed))
            rows=snapshot.table('measurements',observer='review')['rows']
            self.assertEqual({r['measurement_id'] for r in rows},{digest(self.record)})
            self.assertTrue(all(r['is_current']==1 for r in rows))
        self.assertEqual(Analysis(self.store.path).table('measurements',observer='review')['rows'],[])

    def test_export_retains_snapshot_binding_and_legacy_exports_keep_history(self):
        frozen=self.store.path.parent/'dataset.sqlite'
        Analysis(self.store.path).database(frozen)
        changed=copy.deepcopy(self.bundle);changed['document']['units'][0]['activity']='orient'
        with self.store.connect() as c:graph_store.save(c,graph_store.build(self.run,changed))
        self.assertEqual(Analysis(self.store.path).table('measurements',observer='review')['rows'],[])
        rows=Analysis(frozen).table('measurements',observer='review')['rows']
        self.assertEqual({r['measurement_id'] for r in rows},{digest(self.record)})
        with closing(sqlite3.connect(frozen)) as c:
            c.execute('ALTER TABLE rl_measurements DROP COLUMN is_current');c.commit()
        self.assertEqual(Analysis(frozen).table('measurements',observer='review')['rows'],[])
        legacy=Analysis(frozen).table('measurements',observer='review',history=True)
        self.assertEqual({r['measurement_id'] for r in legacy['rows']},{digest(self.record)})
        self.assertTrue(all(r['is_current'] is None for r in legacy['rows']))
        self.assertEqual(legacy['source_coverage']['freshness'],'unavailable')


if __name__=='__main__':unittest.main()
