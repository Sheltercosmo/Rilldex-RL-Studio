import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker.connections import Service, create, definitions, preview, set_enabled
from tracker.store import Store
from tracker.schema import InputError
from tracker.watch import DirectoryWatcher
from test_tracker import harbor


class MonitorStub:
    def __init__(self):self.wakes=0
    def wake(self):self.wakes+=1
    def status(self):return {'revision':'test','updating':False,'running':True}


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'job';self.root.mkdir()
        self.store=Store(Path(self.tmp.name)/'db.sqlite')
        self.config={'root':str(self.root),'producer':'job-a','interval':0.2}
        self.path=self.root/'trial'/'agent'/'trajectory.json';self.path.parent.mkdir(parents=True)

    def write(self,value):self.path.write_text(json.dumps(value),encoding='utf-8')

    def wait(self,predicate):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.05)
        self.fail('Timed out waiting for managed collection')

    def test_empty_preview_and_persistent_config_are_idempotent(self):
        self.assertEqual(preview(self.store,self.config)['files'],0)
        a=create(self.store,self.config);b=create(self.store,self.config)
        self.assertEqual(a['id'],b['id']);self.assertFalse(b['created'])
        self.assertEqual(len(definitions(Store(self.store.path))),1)
        with self.assertRaises(InputError):create(self.store,{**self.config,'interval':1})

    def test_managed_restart_pause_and_partial_recovery(self):
        cid=create(self.store,self.config)['id'];monitor=MonitorStub();service=Service(self.store,monitor)
        try:
            self.path.write_text('{"steps":',encoding='utf-8')
            self.wait(lambda:definitions(self.store)[0]['status'].get('deferred')==1)
            self.assertEqual(self.store.list(),[])
            self.write(harbor());self.wait(lambda:len(self.store.list())==1)
            first=self.store.list()[0]
            self.assertTrue(monitor.wakes)
            set_enabled(self.store,cid,False)
            self.wait(lambda:cid not in service.collectors)
            doc=harbor();doc['steps'][-1]['message']='A later source revision.';self.write(doc)
            time.sleep(.3);self.assertEqual(self.store.list()[0]['id'],first['id'])
        finally:service.close()
        set_enabled(self.store,cid,True)
        restarted=Service(Store(self.store.path),monitor)
        try:
            self.wait(lambda:self.store.list()[0]['ingestion']['revision']==1)
            self.assertEqual(len(self.store.list()),1)
            self.assertNotEqual(restarted.snapshot()['source_revision'],None)
        finally:restarted.close()

    def test_stat_cache_includes_absent_sidecars_and_partial_update(self):
        self.write(harbor());w=DirectoryWatcher(self.store,self.root,producer='p')
        self.assertEqual(w.poll()['ingested'],1)
        with patch.object(w,'_read',side_effect=AssertionError('Unchanged files should not be parsed')):
            self.assertEqual(w.poll()['ingested'],0)
        result=self.path.parent.parent/'result.json'
        result.write_text(json.dumps({'finished_at':'2026-10-09T00:00:00Z','verifier_result':{'rewards':{'reward':1}}}))
        self.assertEqual(w.poll()['ingested'],1)
        self.assertEqual(self.store.list()[0]['ingestion']['state'],'complete')
        from tracker.rollout_metrics import source_record
        run=self.store.get(self.store.list()[0]['id'],raw=True)['run']
        reward=source_record(run)['metrics']['recorded_reward']
        self.assertEqual(reward['value'],1)
        self.assertEqual(reward['source_refs'][0]['pointer'],'/verifier_result/rewards/reward')
        self.path.write_text('{')
        self.assertEqual(w.poll()['deferred'],1)
        self.assertEqual(self.store.list()[0]['ingestion']['revision'],1)
        self.write(harbor());self.assertEqual(w.poll()['ingested'],0)

    def test_reward_selection_and_legacy_backfill_keep_provenance(self):
        from tracker.rollout_metrics import source_record,ensure_current,save,VERSION
        self.write(harbor())
        result=self.path.parent.parent/'result.json'
        result.write_text(json.dumps({'finished_at':'2026-10-09T00:00:00Z','verifier_result':{'rewards':{'quality':.7,'safety':0}}}))
        w=DirectoryWatcher(self.store,self.root,producer='p');w.poll()
        run=self.store.get(self.store.list()[0]['id'],raw=True)['run']
        self.assertIsNone(source_record(run)['metrics']['recorded_reward']['value'])
        (self.path.parent.parent/'tracking.json').write_text(json.dumps({'reward_key':'quality'}));w.poll()
        run=self.store.get(self.store.list()[0]['id'],raw=True)['run']
        self.assertEqual(source_record(run)['metrics']['recorded_reward']['value'],.7)
        legacy=source_record(run);legacy['schema']='rollout-behavior/14';legacy['metrics']['recorded_reward']['value']=None
        with self.store.connect() as c:
            c.execute("DELETE FROM rollout_measurements WHERE run_id=?",(run['id'],))
            save(c,legacy)
        ensure_current(self.store)
        with self.store.connect() as c:
            current=c.execute("SELECT document FROM rollout_measurements WHERE run_id=? AND json_extract(document,'$.schema')=?",(run['id'],VERSION)).fetchone()
            old=c.execute("SELECT document FROM rollout_measurements WHERE run_id=? AND json_extract(document,'$.schema')='rollout-behavior/14'",(run['id'],)).fetchone()
        self.assertEqual(json.loads(current[0])['metrics']['recorded_reward']['value'],.7)
        self.assertIsNone(json.loads(old[0])['metrics']['recorded_reward']['value'])

    def test_missing_mount_recovers_without_disabling_connection(self):
        create(self.store,self.config);self.path.parent.rmdir();self.path.parent.parent.rmdir();self.root.rmdir()
        service=Service(self.store,MonitorStub())
        try:
            self.wait(lambda:definitions(self.store)[0]['status'].get('phase')=='error')
            self.path.parent.mkdir(parents=True);self.write(harbor())
            self.wait(lambda:len(self.store.list())==1)
            self.assertTrue(definitions(self.store)[0]['enabled'])
        finally:service.close()

    def test_config_errors_fail_before_persisting(self):
        for extra in [{'interval':float('nan')},{'max_files':True},{'metadata':[]},{'root':''},{'producer':None}]:
            with self.subTest(extra=extra),self.assertRaises(InputError):create(self.store,{**self.config,**extra})
        self.assertEqual(definitions(self.store),[])

    def test_connection_totals_include_history_and_other_delivery_routes(self):
        self.write(harbor())
        DirectoryWatcher(self.store,self.root,producer='job-a').poll()
        cid=create(self.store,self.config)['id']
        service=Service(self.store,MonitorStub())
        try:
            first=service.snapshot()['connections'][0]['received']
            self.assertEqual((first['received_revisions'],first['received_rollouts']),(1,1))
            self.assertIsNotNone(first['last_receipt_at'])
            payload=dict(producer='job-a',rollout_id='delivered',revision=0,state='in_progress',
                         document={'trajectory_format':'generation/1','prompt':'Q','completion':'A'})
            self.store.ingest(payload)
            self.store.ingest({**payload,'revision':1,'state':'complete'})
            second=service.snapshot()['connections'][0]['received']
            self.assertEqual((second['received_revisions'],second['received_rollouts']),(3,2))
            self.assertEqual(first['received_revisions'],1)
        finally:service.close()

    def test_semantic_job_status_changes_snapshot_revision_without_source_change(self):
        from tracker.semantic_watch import initialize_tables
        from tracker.schema import dumps
        payload=dict(producer='job-a',rollout_id='semantic-status',revision=0,state='in_progress',
                     document={'trajectory_format':'generation/1','prompt':'Q','completion':'A'})
        receipt=self.store.ingest(payload)
        with self.store.connect() as c:
            initialize_tables(c)
            c.execute('INSERT INTO semantic_watchers VALUES (?,?,?,?)',
                ('observer',dumps({'label':'fixture observer'}),'{}','[]'))
            c.execute('INSERT INTO semantic_watch_jobs VALUES (?,?,?,?,?,?,?)',
                ('observer',receipt['id'],'source-hash','queued','{}',
                 '2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'))
        service=Service(self.store,MonitorStub())
        try:
            queued=service.snapshot()
            with self.store.connect() as c:
                c.execute("UPDATE semantic_watch_jobs SET status='running',document=?,updated_at=? WHERE worker_id=? AND run_id=?",
                    (dumps({'directory':'/fixture'}),'2026-01-01T00:00:01+00:00','observer',receipt['id']))
            running=service.snapshot()
            self.assertEqual(queued['source_revision'],running['source_revision'])
            self.assertNotEqual(queued['semantic_revision'],running['semantic_revision'])
        finally:service.close()


if __name__=='__main__':unittest.main()
