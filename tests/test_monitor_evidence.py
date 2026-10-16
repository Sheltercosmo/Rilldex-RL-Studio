import copy
import json
import unittest
from tracker import monitoring as m, monitor_evidence as evidence, graph_store as gs, graph_queries as gq
from tracker.schema import digest, dumps, InputError
from tracker.rollout_metrics import source_record, save as save_record, record_map
import test_monitoring as fixtures
from tracker.adapters import normalize
from test_tracker import harbor


class MeasurementEvidenceTests(unittest.TestCase):
    setUp=fixtures.MonitoringTests.setUp
    run_fixture=fixtures.MonitoringTests.run_fixture
    monitor=fixtures.MonitoringTests.monitor
    graph=fixtures.MonitoringTests.graph

    def graph_monitor(self):
        return m.create(self.store,{'name':'Revision from inspection','kind':'graph','observer':'review',
            'requirement':{**gq.PRESETS['revision_after_inspect'],'require_evidence_link':True}})

    def latest(self,monitor,run):
        return m.values(self.store,monitor['id'],{run['id']})[run['id']]['id']

    def test_old_value_keeps_original_graph_and_numerator_after_revision(self):
        run=self.run_fixture();first=self.graph(run);monitor=self.graph_monitor();m.sync(self.store);old_id=self.latest(monitor,run)
        second=self.graph(run,extra=True);m.sync(self.store);new_id=self.latest(monitor,run)
        old=evidence.read(self.store,old_id);new=evidence.read(self.store,new_id)
        self.assertEqual(old['graph']['id'],first['id']);self.assertEqual(new['graph']['id'],second['id'])
        self.assertEqual(old['explanation']['numerator'],1);self.assertEqual(new['explanation']['numerator'],0)
        self.assertEqual(new['explanation']['not_established'],2)
        self.assertIsNone(new['explanation']['value'])
        self.assertEqual(new['explanation']['status'],'unavailable')
        # A historical graph-count receipt still explains its old structural
        # zero; changing the monitor projection cannot rewrite saved evidence.
        legacy=copy.deepcopy(new['measurement']);legacy.pop('graph_monitor_version');legacy.update(value=0,status='available')
        historical=evidence.explain(legacy,new['monitor'],new['graph'],None)
        self.assertEqual(historical['value'],0)
        self.assertIsNone(new['explanation']['behavior_negatives']);self.assertIsNone(new['explanation']['behavior_rate'])
        self.assertFalse(old['freshness']['current_measurement']);self.assertEqual(old['freshness']['latest_value_id'],new_id)
        self.assertTrue(new['freshness']['current_measurement'])

    def test_every_witness_references_the_exact_saved_edges_and_units(self):
        run=self.run_fixture();self.graph(run);monitor=self.graph_monitor();m.sync(self.store)
        proof=evidence.read(self.store,self.latest(monitor,run));match=next(c for c in proof['explanation']['cases'] if c['matches'])['matches'][0]
        self.assertEqual(set(match['node_ids']),{'old','seek','change'})
        self.assertEqual(len(match['edge_ids']),2)
        edges={e['id'] for e in proof['graph']['edges']};self.assertTrue(set(match['edge_ids'])<=edges)
        self.assertEqual(proof['explanation']['cases'][1]['status'],'not_established')

    def test_feedback_path_preserves_inspection_response_and_assessment(self):
        run=self.run_fixture();e=run['events'][0]
        units=[{'id':name,'kind':kind,'actor':actor,'activity':activity,'source':{'event_id':e['id'],'start':i*10,'end':i*10+5,'text':name}}
            for i,(name,kind,actor,activity) in enumerate([('seek','action','agent','inspect'),('feedback','feedback','environment',None),('review','semantic','agent','orient')])]
        graph=gs.build(run,{'document':{'source_hash':digest(run),'units':units,'relations':[{'from':'feedback','to':'seek','type':'feedback_for'},{'from':'review','to':'feedback','type':'assesses'}]},'observer':{'id':'review','label':'Review'}})
        with self.store.connect() as c:gs.save(c,graph)
        monitor=m.create(self.store,{'name':'Assess exact feedback','kind':'graph','observer':'review','requirement':gq.PRESETS['assessment_of_inspection_feedback']});m.sync(self.store)
        proof=evidence.read(self.store,self.latest(monitor,run));match=proof['explanation']['cases'][0]['matches'][0]
        self.assertEqual(set(match['node_ids']),{'seek','feedback','review'});self.assertEqual(len(match['edge_ids']),2)
        self.assertEqual(proof['explanation']['value'],1)

    def test_corrupt_receipt_wrong_run_and_missing_value_fail_explicitly(self):
        run=self.run_fixture();monitor=self.monitor();m.sync(self.store);vid=self.latest(monitor,run)
        with self.assertRaises(InputError):evidence.read(self.store,vid,'wrong-run')
        with self.assertRaises(KeyError):evidence.read(self.store,'unknown')
        with self.store.connect() as c:
            v=json.loads(c.execute('SELECT document FROM monitor_values WHERE id=?',(vid,)).fetchone()[0]);v['value']=999
            c.execute('UPDATE monitor_values SET document=? WHERE id=?',(dumps(v),vid))
        with self.assertRaisesRegex(InputError,'content does not match'):evidence.read(self.store,vid)

    def test_unknown_and_zero_keep_different_meanings(self):
        doc=harbor();doc['steps']=doc['steps'][:2];run=normalize(doc,'harbor')[0];self.store.add([run]);zero=self.monitor(metric='exact_dispatch_repeat_rate');unknown=self.graph_monitor();m.sync(self.store)
        z=evidence.read(self.store,self.latest(zero,run));u=evidence.read(self.store,self.latest(unknown,run))
        self.assertEqual(z['measurement']['value'],0);self.assertEqual(z['measurement']['status'],'available')
        self.assertIsNone(u['measurement']['value']);self.assertEqual(u['measurement']['status'],'waiting')
        self.assertIsNone(u['explanation']['not_established']);self.assertEqual(u['graph']['observer'],'source')

    def test_semantic_metric_uses_bound_graph_not_latest_same_observer(self):
        run=self.run_fixture();first=self.graph(run);record=source_record(run);record.update(observer='review',graph_id=first['id'])
        with self.store.connect() as c:save_record(c,record)
        monitor=self.monitor(observer='review');m.sync(self.store);original=self.latest(monitor,run)
        self.graph(run,extra=True);m.sync(self.store)
        proof=evidence.read(self.store,original);self.assertEqual(proof['graph']['id'],first['id'])
        self.assertFalse(proof['freshness']['current_measurement'])
        self.assertIsNone(m.cases(self.store,monitor['id'])['rows'][0]['measurement']['value'])

    def test_unbound_legacy_metric_does_not_borrow_a_graph(self):
        run=self.run_fixture();self.graph(run);record=source_record(run);record.update(observer='review',annotation_hash='different-version')
        with self.store.connect() as c:save_record(c,record)
        monitor=self.monitor(observer='review');m.sync(self.store)
        self.assertEqual(evidence.read(self.store,self.latest(monitor,run))['graph']['observer'],'source')

    def test_record_map_persists_exact_graph_binding(self):
        run=self.run_fixture();bundle={'document':{'source_hash':digest(run),'units':[],'relations':[]},'observer':{'id':'empty','label':'Empty'}}
        record=record_map(self.store,run,bundle)
        self.assertEqual(gs.read(self.store,record['graph_id'])['observer'],'empty')
        with self.store.connect() as c:stored=json.loads(c.execute('SELECT document FROM rollout_measurements WHERE id=?',(digest(record),)).fetchone()[0])
        self.assertEqual(stored['graph_id'],record['graph_id'])

    def test_historical_source_remains_inspectable_after_producer_update(self):
        p={'producer':'p','rollout_id':'r','revision':0,'state':'complete','document':harbor()}
        first=self.store.ingest(p);monitor=self.monitor();m.sync(self.store);vid=self.latest(monitor,first)
        p.update(revision=1);p['document']=copy.deepcopy(p['document']);p['document']['steps'][-1]['message']='Changed source';self.store.ingest(p);m.sync(self.store)
        proof=evidence.read(self.store,vid);self.assertEqual(proof['run']['id'],first['id']);self.assertFalse(proof['freshness']['current_source'])
        self.assertEqual(proof['graph']['run_id'],first['id'])

    def test_chart_and_unplaced_points_both_carry_value_identity(self):
        a=self.run_fixture();b=self.run_fixture(None);monitor=self.monitor();m.sync(self.store);snap=m.snapshot(self.store)['monitors'][0]
        self.assertEqual(snap['series'][0]['points'][0]['value_id'],self.latest(monitor,a))
        self.assertEqual(snap['unplaced_points'][0]['value_id'],self.latest(monitor,b))


if __name__=='__main__':unittest.main()
