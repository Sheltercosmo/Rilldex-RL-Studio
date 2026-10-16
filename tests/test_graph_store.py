import copy
import tempfile
import unittest
from pathlib import Path
from tracker.store import Store
from tracker.adapters import normalize
from tracker.schema import digest, InputError
from tracker import graph_store as gs, graph_queries as gq
from test_tracker import harbor


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite')
        self.run=normalize(harbor(),'harbor',{'experiment':'graph-test','training_step':0})[0]
        self.store.add([self.run])

    def graph(self):
        events=self.run['events']; e=events[0]
        units=[]
        for i,(identity,activity) in enumerate([('old','plan'),('seek','inspect'),('change','construct'),('seek2','inspect')]):
            units.append({'id':identity,'activity':activity,'actor':'agent','kind':'semantic',
                'source':{'event_id':e['id'],'start':i*10,'end':i*10+5,'text':identity}})
        d={'source_hash':digest(self.run),'units':units,'relations':[
            {'from':'change','to':'old','type':'revises','request':'receipt'},
            {'from':'change','to':'seek','type':'uses_evidence'}]}
        return gs.build(self.run,{'document':d,'observer':{'id':'test','label':'Test'}})

    def test_import_atomically_creates_idempotent_source_graph(self):
        c=gs.catalog(self.store);self.assertEqual(c['indexed_rollouts'],1)
        self.store.add([self.run]);self.assertEqual(gs.catalog(self.store)['stored_versions'],1)
        g=gs.read(self.store,c['graphs'][0]['id'])
        self.assertEqual(len([n for n in g['nodes'] if n['kind']=='event']),len(self.run['events']))
        self.assertTrue(all(e['source'] in {n['id'] for n in g['nodes']} for e in g['edges']))

    def test_annotation_versions_and_edge_provenance_survive(self):
        a=self.graph();b=copy.deepcopy(a)
        with self.store.connect() as c:gs.save(c,a);gs.save(c,a)
        restored=gs.read(self.store,a['id'])
        self.assertEqual(sorted(restored['edges'],key=lambda e:e['id']),a['edges'])
        self.assertEqual(next(e['properties']['request'] for e in restored['edges'] if e['type']=='revises'),'receipt')
        self.assertEqual(gs.catalog(self.store)['semantic_graphs'],1)
        self.assertEqual(a,b)

    def test_relation_query_deduplicates_anchor_and_keeps_missing_edges_unknown(self):
        g=self.graph();q={**gq.PRESETS['revision_after_inspect'],'require_evidence_link':True}
        r=gq.evaluate(g,q)
        self.assertEqual((r['anchors'],r['matched_anchors'],r['without_recorded_match']),(2,1,1))
        self.assertEqual(r['recorded_match_fraction'],.5);self.assertIsNone(r['behavior_rate'])
        self.assertEqual(r['cases'][0]['matches'][0]['source'],'change')

    def test_window_evidence_link_newness_and_trajectory_boundaries(self):
        g=self.graph();q=gq.PRESETS['revision_after_new_exploration']
        r=gq.evaluate(g,q);self.assertEqual(r['anchors'],0);self.assertEqual(r['unclassified_newness'],2)
        self.assertIsNone(r['recorded_match_fraction'])
        g['edges']=[e for e in g['edges'] if e['type']!='uses_evidence']
        r=gq.evaluate(g,{**gq.PRESETS['revision_after_inspect'],'require_evidence_link':True})
        self.assertEqual(r['matched_anchors'],0)
        for n in g['nodes']:
            if n['id']=='change':n['trajectory_id']='other'
        self.assertEqual(gq.evaluate(g,gq.PRESETS['revision_after_inspect'])['matched_anchors'],0)

    def test_dangling_semantic_endpoint_is_explicit_not_fabricated_unit(self):
        d={'source_hash':digest(self.run),'units':[],'relations':[{'from':'unknown1','to':'unknown2','type':'revises'}]}
        g=gs.build(self.run,{'document':d,'observer':{'id':'partial','label':'Partial'}})
        self.assertEqual(g['counts']['unresolved_endpoints'],2)
        with self.store.connect() as c:gs.save(c,g)
        self.assertEqual(len(gs.read(self.store,g['id'])['edges']),len(g['edges']))

    def test_requirement_validation_and_persistence(self):
        q=gq.PRESETS['revision_after_inspect'];saved=gq.save(self.store,q)
        self.assertEqual(gq.save(self.store,q),saved);self.assertEqual(len(gq.saved(self.store)),1)
        for invalid in [{**q,'sql':'delete'},{**q,'within_units':True},{**q,'require_evidence_link':'true'}]:
            with self.assertRaises(InputError):gq.validate(invalid)

    def test_time_series_retains_step_zero_and_deduplicates_graph_selection(self):
        g=self.graph()
        with self.store.connect() as c:gs.save(c,g)
        r=gq.run(self.store,{'graph_ids':[g['id'],g['id']],'requirement':gq.PRESETS['revision_after_inspect']})
        self.assertEqual(len(r['results']),1)
        self.assertEqual(r['training'][0]['bins'][0]['step'],0)
        self.assertEqual(r['training'][0]['bins'][0]['denominator'],2)

    def test_graph_source_hash_and_matrix_unknown_boundaries(self):
        with self.assertRaises(InputError):gs.build(self.run,{'document':{'source_hash':'wrong'}})
        g=self.graph();mat=gs.matrices(g)
        self.assertTrue(any(x['relation']=='revises' for x in mat['relations']))
        for n in g['nodes']:
            if n['id']=='seek':n['activity']=None
        self.assertFalse(any(x['source']=='plan' and x['target']=='construct' for x in gs.matrices(g)['transitions']))

    def test_query_rejects_mixed_observers_and_duplicate_annotation_versions(self):
        g=self.graph()
        with self.store.connect() as c:gs.save(c,g)
        source=next(x for x in gs.catalog(self.store)['graphs'] if x['observer']=='source')
        with self.assertRaises(InputError):gq.run(self.store,{'graph_ids':[g['id'],source['id']],'requirement':gq.PRESETS['revision_after_inspect']})
        g2=copy.deepcopy(g);g2['annotation_hash']='alternate';g2['id']='graph-'+digest({k:v for k,v in g2.items() if k!='id'})
        with self.store.connect() as c:gs.save(c,g2)
        with self.assertRaises(InputError):gq.run(self.store,{'graph_ids':[g['id'],g2['id']],'requirement':gq.PRESETS['revision_after_inspect']})

    def test_ingestion_graphs_keep_history_and_exclude_incomplete_training(self):
        payload={'producer':'p','rollout_id':'r','revision':0,'state':'in_progress','document':harbor(),'metadata':{'experiment':'live','training_step':0}}
        first=self.store.ingest(payload)
        g=next(x for x in gs.catalog(self.store)['graphs'] if x['run_id']==first['id'])
        result=gq.run(self.store,{'graph_ids':[g['id']],'requirement':gq.PRESETS['revision_after_inspect']})
        self.assertEqual(result['incomplete_snapshots'],1);self.assertEqual(result['training'],[])
        payload.update(revision=1,state='complete');payload['document']=copy.deepcopy(payload['document']);payload['document']['steps'][-1]['message']='new snapshot'
        second=self.store.ingest(payload)
        self.assertNotEqual(first['id'],second['id'])
        self.assertNotIn(first['id'],{v['run_id'] for v in gs.catalog(self.store)['graphs']})
        self.assertEqual(gs.read(self.store,g['id'])['run_id'],first['id'])
        result=gq.run(self.store,{'graph_ids':[g['id']],'requirement':gq.PRESETS['revision_after_inspect']})
        self.assertEqual(result['historical_graphs'],1)

    def test_graph_identity_rejects_modified_properties(self):
        g=self.graph();g['nodes'][0]['properties']['unexpected']='modified'
        with self.store.connect() as c:
            with self.assertRaises(InputError):gs.save(c,g)

if __name__=='__main__':unittest.main()
