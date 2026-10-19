"""Saved coverage, live checkpoints and cache-only resume; no paid model calls."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import unittest

from tracker import diagnostic_worker as worker, scan_progress
from tracker.adapters import normalize
from tracker.schema import digest
from tracker.store import Store
from test_tracker import harbor
from test_diagnostic_direct import wire
from test_requirement_diagnostics import transport as requirement_wire
import test_generation_cohort_transport as transport


class ScanProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'db');self.work=self.root/'scan'

    def add(self,step=0,long=False):
        run=normalize(harbor(),'harbor',{'experiment':'scan-test','training_step':step})[0]
        if long:run['events'][-1]['text']='ordinary unrelated output\n'*12000
        self.store.add([run]);return run

    def execute(self,**kw):
        return worker.execute(self.store,self.work,kw.pop('transport',wire),selector=worker.selection(experiment='scan-test'),protocol_name='search',**kw)

    def test_page_receipt_visible_before_next_request_and_bounded_storage(self):
        run=self.add(long=True);seen=[]
        def observe(req):
            if seen:
                live=scan_progress.snapshot(self.store)['workers'][0]['rows'][0]
                self.assertEqual(live['last_state'],'running')
                self.assertEqual(live['pages_scanned'],len(seen))
                self.assertEqual(live['new_calls'],len(seen)+1)
                self.assertEqual(live['provider_responses'],len(seen))
            seen.append(req);return wire(req)
        result=self.execute(transport=observe,max_new_calls=100)
        self.assertGreater(len(seen),2);self.assertEqual(result['coverage']['counts'],{'complete':1})
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM diagnostic_attempts').fetchone()[0],3)
        snapshot=scan_progress.snapshot(self.store)['workers'][0]
        self.assertEqual(snapshot['workspace_path'],str(self.work.resolve()))
        self.assertEqual(snapshot['rows'][0]['pages_scanned'],snapshot['rows'][0]['pages_total'])
        self.assertEqual(snapshot['counts'],{'complete':1})

    def test_partial_and_unscanned_are_separate_and_resume_reuses_calls(self):
        first=self.add(long=True);self.add(step=1,long=True)
        result=self.execute(max_new_calls=1)
        snap=scan_progress.snapshot(self.store)['workers'][0]
        self.assertEqual(snap['counts'],{'partial':1,'not_scanned':1})
        self.assertEqual(snap['rows'][0]['pages_scanned'],1)
        self.assertTrue(all(r['measurement_id'] is None for r in snap['rows']))
        self.execute(transport=lambda _:self.fail('Zero budget must only replay'),max_new_calls=0)
        self.assertEqual(scan_progress.snapshot(self.store)['workers'][0]['counts'],snap['counts'])
        result=self.execute(max_new_calls=100)
        self.assertEqual(result['coverage']['counts'],{'complete':2})
        self.execute(transport=lambda _:self.fail('Complete results are cached'),max_new_calls=0)
        self.assertEqual(scan_progress.snapshot(self.store)['workers'][0]['counts'],{'complete':2})

    def test_resume_does_not_make_saved_page_coverage_move_backwards(self):
        self.add(long=True);self.execute(max_new_calls=3);observed=[]
        def observe(_):
            observed.append(scan_progress.snapshot(self.store)['workers'][0]['rows'][0]['pages_scanned'])
        self.execute(max_new_calls=100,progress=observe)
        self.assertTrue(observed)
        self.assertTrue(all(n is not None and n>=3 for n in observed),observed)

    def test_new_imports_filters_and_legacy_workspace(self):
        self.add();self.execute(max_new_calls=0);self.add(step=2)
        snap=scan_progress.snapshot(self.store)['workers'][0]
        self.assertEqual(snap['awaiting_inventory'],1)
        self.assertEqual(snap['counts'],{'not_scanned':1})
        self.assertEqual(scan_progress.snapshot(self.store,experiment='different')['workers'],[])
        with self.store.connect() as c:
            r=c.execute('SELECT id,document FROM diagnostic_workers').fetchone()
            d=json.loads(r['document']);d.pop('workspace_path');d['population'][0].pop('experiment')
            c.execute('UPDATE diagnostic_workers SET document=? WHERE id=?',(json.dumps(d),r['id']))
        self.assertIsNone(scan_progress.snapshot(self.store,experiment='scan-test')['workers'][0]['workspace_path'])

    def test_requirement_receipt_uses_scan_requests_and_keeps_partial_finding(self):
        run=self.add();self.execute(max_new_calls=0)
        with self.store.connect() as c:
            worker_id=c.execute('SELECT id FROM diagnostic_workers').fetchone()[0]
            worker._save_attempt(c,worker_id,dict(run_id=run['id'],source_hash=digest(run),attempt_id='legacy',status='pending',
                inspection_progress={'scan_complete':False,'scan_requests':3,'requests':4},measurement_id='partial-result'))
        row=scan_progress.snapshot(self.store)['workers'][0]['rows'][0]
        self.assertEqual(row['status'],'partial');self.assertEqual(row['requests_completed'],4)

    def test_superseded_source_is_not_reported_as_scanned(self):
        payload=dict(producer='trainer',rollout_id='one',revision=0,state='complete',format='harbor',document=harbor(),metadata={'experiment':'scan-test'})
        old=self.store.ingest(payload);self.execute(max_new_calls=100)
        payload['revision']=1;payload['document']['steps'][-1]['message']='New source content'
        self.store.ingest(payload)
        snapshot=scan_progress.snapshot(self.store)['workers'][0]
        self.assertEqual(snapshot['counts'],{});self.assertEqual(snapshot['superseded'],1)
        self.assertEqual(snapshot['awaiting_inventory'],1)

    def test_unchanged_latest_revision_keeps_completed_coverage(self):
        payload=dict(producer='trainer',rollout_id='one',revision=0,state='complete',format='harbor',document=harbor(),metadata={'experiment':'scan-test'})
        original=self.store.ingest(payload);self.execute(max_new_calls=100)
        payload['revision']=1
        self.assertEqual(self.store.ingest(payload)['id'],original['id'])
        for refresh in (False,True):
            with self.subTest(worker_refreshed=refresh):
                if refresh:self.execute(transport=lambda _:self.fail('Unchanged source must be reused'),max_new_calls=0)
                snap=scan_progress.snapshot(self.store)['workers'][0]
                self.assertEqual(snap['counts'],{'complete':1})
                self.assertEqual(snap['superseded'],0)
                self.assertEqual(snap['awaiting_inventory'],0)

    def test_state_only_completion_waits_for_inventory_without_losing_source(self):
        payload=dict(producer='trainer',rollout_id='one',revision=0,state='in_progress',format='harbor',document=harbor(),metadata={'experiment':'scan-test'})
        first=self.store.ingest(payload);self.execute(max_new_calls=0)
        payload.update(revision=1,state='complete')
        self.assertEqual(self.store.ingest(payload)['id'],first['id'])
        snap=scan_progress.snapshot(self.store)['workers'][0]
        self.assertEqual(snap['counts'],{'not_scanned':1})
        self.assertEqual(snap['awaiting_inventory'],1)
        self.assertEqual(snap['superseded'],0)
        self.execute(max_new_calls=100)
        self.assertEqual(scan_progress.snapshot(self.store)['workers'][0]['counts'],{'complete':1})
        payload.update(revision=2,state='in_progress');self.store.ingest(payload)
        self.assertEqual(scan_progress.snapshot(self.store)['workers'][0]['counts'],{'waiting':1})

    def test_requirement_selection_progress_survives_a_budget_pause(self):
        doc=harbor()
        doc['steps'][0]['message']='\n\n'.join(f'Preserve output field {i} in exported records.' for i in range(70))
        run=normalize(doc,'harbor',{'experiment':'scan-test'})[0];self.store.add([run])
        seen=[];snapshots=[]
        def observe(req):
            if seen:
                snapshots.append(scan_progress.snapshot(self.store)['workers'][0]['rows'][0])
            seen.append(req);return requirement_wire(req)
        worker.execute(self.store,self.work,observe,selector=worker.selection(experiment='scan-test'),protocol_name='requirements',max_new_calls=2)
        self.assertEqual(len(snapshots),1)
        self.assertEqual(snapshots[0]['status'],'partial')
        self.assertEqual(snapshots[0]['stage'],'requirement_extraction')
        self.assertEqual(snapshots[0]['requests_completed'],1)
        row=scan_progress.snapshot(self.store)['workers'][0]['rows'][0]
        self.assertEqual(row['requests_completed'],2)
        self.assertEqual(row['status'],'partial')
        self.assertIsNone(row['measurement_id'])


class ScanHttpTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_read_only_http_and_client_delivery(self):
        base=self.start_server()
        with urlopen(base+'/api/monitoring/scans') as response:self.assertEqual(json.load(response)['workers'],[])
        with urlopen(base+'/reward-scan-progress.js') as response:self.assertIn(b'RewardScanProgress',response.read())


if __name__=='__main__':unittest.main()
