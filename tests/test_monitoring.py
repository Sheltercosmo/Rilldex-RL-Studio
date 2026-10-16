import copy
import tempfile
import time
import unittest
from pathlib import Path
from tracker.store import Store
from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker import monitoring as m, graph_store as gs, graph_queries as gq
from tracker.rollout_metrics import source_record, save as save_measurement
from test_tracker import harbor


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite')

    def run_fixture(self,step=0,**metadata):
        run=normalize(harbor(),'harbor',{'experiment':'monitor-test','training_step':step,**metadata})[0]
        self.store.add([run]);return run

    def monitor(self,**changes):
        return m.create(self.store,{'name':'Actions','kind':'metric','metric':'actions','observer':'source',**changes})

    def result(self,monitor):
        return next(x for x in m.snapshot(self.store)['monitors'] if x['id']==monitor['id'])

    def graph(self,run,observer='review',extra=False):
        e=run['events'][0]
        spec=[('old','orient'),('seek','inspect'),('change','construct'),('seek2','inspect')]
        units=[{'id':i,'activity':a,'kind':'semantic','actor':'agent','source':{'event_id':e['id'],'start':j*10,'end':j*10+5,'text':i}} for j,(i,a) in enumerate(spec)]
        relations=[{'from':'change','to':'old','type':'revises'},{'from':'change','to':'seek','type':'uses_evidence'}]
        if extra:relations=[]
        graph=gs.build(run,{'document':{'source_hash':digest(run),'units':units,'relations':relations},'observer':{'id':observer,'label':'Review'}})
        with self.store.connect() as c:gs.save(c,graph)
        return graph

    def test_new_rollouts_materialize_once_with_null_coverage(self):
        run=self.run_fixture();monitor=self.monitor();unknown=self.monitor(name='Unknown',metric='recovery_rate')
        first=m.sync(self.store);self.assertEqual(first['inserted'],2)
        second=m.sync(self.store);self.assertEqual(second['inserted'],0);self.assertEqual(second['reused'],2)
        self.assertEqual(self.result(monitor)['coverage']['available'],1)
        self.assertEqual(self.result(unknown)['coverage']['unknown'],1)
        self.assertIsNone(self.result(unknown)['series'][0]['points'][0]['value'])
        self.run_fixture(1);m.sync(self.store)
        self.assertEqual(self.result(monitor)['coverage']['available'],2)
        self.assertEqual([p['step'] for p in self.result(monitor)['series'][0]['points']],[0,1])
        self.assertEqual(len(m.cases(self.store,monitor['id'])['rows']),2)

    def test_workspace_inventory_stays_separate_from_selected_population(self):
        self.run_fixture(experiment='source-only')
        rich=self.run_fixture(step=1,experiment='annotated')
        self.graph(rich)
        result=m.snapshot(self.store,experiment='source-only')
        self.assertEqual(result['population'],1)
        self.assertEqual(result['runs'][0]['semantic_graphs'],0)
        self.assertEqual(result['workspace']['rollouts'],2)
        self.assertEqual(result['workspace']['semantic_rollouts'],1)
        self.assertEqual(result['workspace']['database'],str(self.store.path))

    def test_monitor_sync_upgrades_saved_measurements_without_opening_legacy_report(self):
        import json
        from tracker.rollout_metrics import VERSION, measurement
        run=self.run_fixture();source=self.monitor()
        semantic=self.monitor(name='Saved feedback',observer='saved-review',metric='feedback_assessment_fraction')
        old=source_record(run);old['schema']='rollout-behavior/12'
        original_graph=self.graph(run,observer='saved-review')
        reviewed=copy.deepcopy(old);reviewed.update(observer='saved-review',annotation_hash='original-annotation',graph_id=original_graph['id'])
        reviewed['metrics']['feedback_assessment_fraction']=measurement(numerator=2,denominator=3,evidence=['response-1','response-2'])
        invalid=copy.deepcopy(reviewed);invalid.update(observer='stale-source',source_hash='different-source')
        self.monitor(name='Stale source',observer='stale-source',metric='feedback_assessment_fraction')
        with self.store.connect() as c:
            c.execute('DELETE FROM rollout_measurements WHERE run_id=?',(run['id'],))
            for record in (old,reviewed,invalid):save_measurement(c,record)
        m.sync(self.store)
        self.assertEqual(self.result(source)['coverage']['available'],1)
        point=self.result(semantic)['series'][0]['points'][0]
        self.assertEqual((point['numerator'],point['denominator']),(2,3))
        with self.store.connect() as c:
            records=[json.loads(row[0]) for row in c.execute('SELECT document FROM rollout_measurements')]
            current=next(r for r in records if r['observer']=='saved-review' and r['schema']==VERSION)
            self.assertEqual((current['annotation_hash'],current['graph_id']),('original-annotation',original_graph['id']))
            self.assertIn(reviewed,records)
            self.assertFalse(any(r['observer']=='stale-source' and r['schema']==VERSION for r in records))
            count=len(records)
        self.assertEqual(m.sync(self.store)['inserted'],0)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM rollout_measurements').fetchone()[0],count)

    def test_compatible_upgrade_does_not_replace_a_newer_metric_observation(self):
        from tracker.rollout_metrics import measurement
        from datetime import datetime, timezone
        from unittest.mock import patch
        run=self.run_fixture();monitor=self.monitor(name='Feedback',observer='review',metric='feedback_assessment_fraction')
        old=source_record(run);old.update(observer='review',schema='rollout-behavior/12')
        old['metrics']['feedback_assessment_fraction']=measurement(numerator=2,denominator=3)
        current=source_record(run);current['observer']='review'
        current['metrics']['feedback_assessment_fraction']=measurement(numerator=1,denominator=3)
        # Reproduce equal-resolution wall-clock readings deterministically.
        with patch('tracker.rollout_metrics.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,10,8,tzinfo=timezone.utc)
            with self.store.connect() as c:
                save_measurement(c,old);save_measurement(c,current)
                stamps=[r[0] for r in c.execute('SELECT created_at FROM rollout_measurements WHERE observer=? ORDER BY rowid',('review',))]
                self.assertLess(stamps[0],stamps[1])
        m.sync(self.store)
        self.assertEqual(self.result(monitor)['series'][0]['points'][0]['numerator'],1)

    def test_graph_versions_recompute_values_but_preserve_history(self):
        run=self.run_fixture();self.graph(run)
        monitor=m.create(self.store,{'name':'Revision after inspection','kind':'graph','observer':'review','requirement':{**gq.PRESETS['revision_after_inspect'],'require_evidence_link':True}})
        m.sync(self.store);row=self.result(monitor)
        self.assertEqual(row['series'][0]['bins'][0]['value'],.5)
        value=m.cases(self.store,monitor['id'])['rows'][0]['measurement'];self.assertEqual((value['numerator'],value['denominator']),(1,2))
        self.assertIsNone(value['query']['behavior_rate'])
        self.graph(run,extra=True);m.sync(self.store)
        self.assertIsNone(self.result(monitor)['series'][0]['bins'][0]['value'])
        current=m.cases(self.store,monitor['id'])['rows'][0]['measurement']
        self.assertEqual(current['query']['recorded_match_fraction'],0)
        self.assertEqual(current['status'],'unavailable')
        self.assertIn('coverage is not established',current['reason'])
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM monitor_values').fetchone()[0],2)
        self.assertEqual(m.sync(self.store)['inserted'],0)

    def test_tagged_inspections_do_not_imply_assessment_relationships_were_measured(self):
        run=self.run_fixture();self.graph(run,extra=True)
        monitor=m.create(self.store,{'name':'Assessment of feedback','kind':'graph','observer':'review',
            'requirement':gq.PRESETS['assessment_of_inspection_feedback']})
        m.sync(self.store);result=self.result(monitor)
        self.assertEqual(result['coverage']['available'],0)
        self.assertEqual(result['coverage']['unknown'],1)
        value=m.cases(self.store,monitor['id'])['rows'][0]['measurement']
        self.assertEqual((value['query']['matched_anchors'],value['query']['anchors']),(0,2))
        self.assertIsNone(value['value'])

    def test_wrong_observer_or_source_never_substitutes_an_observation(self):
        run=self.run_fixture();self.graph(run)
        record=source_record(run);record['source_hash']='different';record['observer']='bad-source'
        with self.store.connect() as c:save_measurement(c,record)
        metric=self.monitor(observer='bad-source');graph=m.create(self.store,{'name':'Missing','kind':'graph','observer':'missing','requirement':gq.PRESETS['assessment_of_inspection_feedback']})
        m.sync(self.store)
        for monitor in (metric,graph):
            self.assertEqual(self.result(monitor)['coverage']['available'],0)
            self.assertIsNone(self.result(monitor)['series'][0]['points'][0]['value'])

    def test_definition_edit_creates_a_new_version_and_pause_preserves_values(self):
        self.run_fixture();a=self.monitor();m.sync(self.store)
        b=m.create(self.store,{'name':'Response characters','kind':'metric','metric':'agent_text_chars','observer':'source'},replace=a['id'])
        self.assertFalse(next(d for d in m.definitions(self.store) if d['id']==a['id'])['enabled'])
        self.assertEqual(len(m.cases(self.store,a['id'])['rows']),1)
        m.sync(self.store);self.assertEqual(self.result(b)['coverage']['available'],1)
        m.enabled(self.store,a['id'],True);self.assertEqual(m.sync(self.store)['inserted'],0)
        with self.assertRaises(InputError):m.enabled(self.store,a['id'],'false')
        with self.assertRaises(InputError):self.monitor(sql='select 1')

    def test_incomplete_and_superseded_rollouts_do_not_enter_live_statistics(self):
        monitor=self.monitor();p={'producer':'live','rollout_id':'r1','revision':0,'state':'in_progress','document':harbor(),'metadata':{'experiment':'train','training_step':1}}
        first=self.store.ingest(p);before=m.fingerprint(self.store);m.sync(self.store)
        self.assertEqual(self.result(monitor)['coverage']['available'],0)
        p.update(revision=1,state='complete');p['document']=copy.deepcopy(p['document']);p['document']['steps'][-1]['message']='Complete'
        last=self.store.ingest(p);self.assertNotEqual(before,m.fingerprint(self.store));m.sync(self.store)
        r=self.result(monitor);self.assertEqual(r['coverage']['population'],1);self.assertEqual(r['coverage']['available'],1)
        self.assertEqual(r['series'][0]['points'][0]['run_id'],last['id']);self.assertNotEqual(first['id'],last['id'])

    def test_scope_and_cohorts_do_not_fabricate_training_coordinates(self):
        self.run_fixture(0,split='train');self.run_fixture(0,split='eval');self.run_fixture(None,experiment='offline')
        monitor=self.monitor();m.sync(self.store);r=self.result(monitor)
        self.assertEqual(len(r['series']),2);self.assertEqual(len(r['unplaced_points']),1)
        self.assertEqual(r['coverage']['missing_training_coordinates'],1)
        scoped=m.snapshot(self.store,experiment='offline');self.assertEqual(scoped['population'],1);self.assertEqual(scoped['monitors'][0]['series'],[])
        self.assertEqual(len(m.cases(self.store,monitor['id'],experiment='offline')['rows']),1)

    def test_graph_bin_pools_anchors_instead_of_averaging_ratios(self):
        runs=[{'id':'a','metadata':{'experiment':'x','training_step':1}},{'id':'b','metadata':{'experiment':'x','training_step':1}}]
        rows={'a':{'value':1,'numerator':1,'denominator':1,'status':'available'},'b':{'value':0,'numerator':0,'denominator':9,'status':'available'}}
        c=m.chart({'kind':'graph'},runs,rows);self.assertEqual(c['series'][0]['bins'][0]['value'],.1)
        self.assertEqual(c['series'][0]['bins'][0]['denominator'],10)

    def test_background_service_updates_without_browser_requests(self):
        self.run_fixture();monitor=self.monitor();service=m.Service(self.store);self.addCleanup(service.close)
        end=time.monotonic()+10
        while time.monotonic()<end and not service.status()['revision']:time.sleep(.05)
        self.assertTrue(service.status()['running']);self.assertIsNone(service.status()['error'])
        self.assertEqual(self.result(monitor)['coverage']['available'],1)
        self.run_fixture(2)
        end=time.monotonic()+8
        while time.monotonic()<end and self.result(monitor)['coverage']['available']!=2:time.sleep(.1)
        self.assertEqual(self.result(monitor)['coverage']['available'],2)
        service.close();self.assertFalse(service.status()['running'])

    def test_map_fallback_is_honest_and_includes_all_nodes(self):
        run=self.run_fixture();source=m.rollout(self.store,run['id'])
        self.assertEqual(source['graph']['observer'],'source')
        graph=self.graph(run);observed=m.rollout(self.store,run['id'],'nonexistent')
        self.assertEqual(observed['graph']['id'],graph['id'])
        self.assertEqual(observed['graph']['nodes'],gs.read(self.store,graph['id'])['nodes'])

    def test_explicit_historical_map_survives_new_source_revision(self):
        document=harbor();prefix=copy.deepcopy(document);prefix['steps']=prefix['steps'][:2]
        packet={'producer':'live-worker','rollout_id':'same-rollout','revision':0,
                'state':'in_progress','format':'harbor','metadata':{'experiment':'history'},'document':prefix}
        old=self.store.ingest(packet)['id'];run=self.store.get(old,raw=True)['run']
        graph=self.graph(run,observer='selected-semantic')
        new=self.store.ingest({**packet,'revision':1,'document':document})['id']
        self.assertNotEqual(old,new)
        self.assertNotIn(old,{g['run_id'] for g in gs.catalog(self.store)['graphs']})
        historical=m.rollout(self.store,old,'selected-semantic')
        self.assertEqual(historical['graph']['id'],graph['id'])
        self.assertEqual(historical['run']['id'],old)
        self.assertEqual({g['run_id'] for g in historical['graphs']},{old})
        self.assertEqual(m.rollout(self.store,new)['graph']['observer'],'source')


if __name__=='__main__':unittest.main()
