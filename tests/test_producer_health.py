from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tracker.capture import Outbox
from tracker import producer_health as health
from tracker.store import Store,ReviewConflict
from tracker.schema import InputError
from tracker.portable import generation_document


class ProducerHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'server.sqlite')
        self.out=Outbox(self.root/'out.sqlite',producer='job/worker-0',timeout=.3)

    def report(self,**changes):
        return {'schema':health.VERSION,'producer':'job/worker-0','outbox_id':'a'*32,'sequence':1,
            'phase':'running','interval_seconds':5,'pending':1,'blocked':0,'sent':0,
            'pending_bytes':234,'max_pending_bytes':1048576,'oldest_pending_seconds':3,**changes}

    def transport(self,request,**kw):
        value=json.loads(request.data)
        result=health.receive(self.store,value) if request.full_url.endswith('/report') else self.store.ingest(value)
        return io.BytesIO(json.dumps(result).encode())

    def test_delayed_or_retried_report_cannot_refresh_stale_status(self):
        with patch('tracker.producer_health.time.time',return_value=100):health.receive(self.store,self.report(sequence=2))
        with patch('tracker.producer_health.time.time',return_value=140):
            self.assertFalse(health.receive(self.store,self.report(sequence=1))['accepted'])
            self.assertFalse(health.receive(self.store,self.report(sequence=2))['accepted'])
            row=health.snapshot(self.store)[0]
            self.assertEqual(row['report_age_seconds'],40);self.assertEqual(row['status'],'stale')
        with self.assertRaises(ReviewConflict):health.receive(self.store,self.report(sequence=2,pending=0))

    def test_outbox_replacement_cannot_overwrite_an_existing_producer(self):
        health.receive(self.store,self.report())
        with self.assertRaises(ReviewConflict):health.receive(self.store,self.report(outbox_id='b'*32,sequence=2))
        self.assertEqual(health.snapshot(self.store)[0]['report']['outbox_id'],'a'*32)

    def test_worker_counts_and_server_receipts_are_separate(self):
        self.out.log('r',generation_document('q','a'),state='complete')
        with self.out.connect() as c:payload=json.loads(c.execute('SELECT payload FROM queue').fetchone()[0])
        self.store.ingest(payload)  # Simulates committed source with lost acknowledgment.
        with patch('tracker.capture.urlopen',side_effect=self.transport):self.out.report_status()
        row=health.snapshot(self.store)[0]
        self.assertEqual((row['received_revisions'],row['received_rollouts']),(1,1))
        self.assertEqual((row['report']['sent'],row['report']['pending']),(0,1))
        self.assertEqual(row['status'],'pending')

    def test_unreported_worker_is_unknown_and_lifecycle_is_not_training_health(self):
        self.store.ingest({'producer':'external','rollout_id':'r','revision':0,'state':'complete','document':generation_document('q','a')})
        row=health.snapshot(self.store)[0];self.assertEqual(row['status'],'unreported');self.assertIsNone(row['report'])
        for sequence,changes,state in [(1,{'blocked':1},'blocked'),(2,{'phase':'stopped'},'stopped'),(3,{'pending':0,'pending_bytes':0,'oldest_pending_seconds':None},'current')]:
            health.receive(self.store,self.report(sequence=sequence,**changes))
            self.assertEqual(health.snapshot(self.store)[1]['status'],state)

    def test_report_validation_rejects_bad_counters_and_payload_extras(self):
        for changes in [{'pending':True},{'sent':-1},{'sequence':0},{'phase':'training'}, {'outbox_id':'invalid'},
                        {'interval_seconds':float('nan')},{'oldest_pending_seconds':float('inf')},
                        {'max_pending_bytes':0},{'prompt':'not allowed'}]:
            with self.assertRaises(InputError):health.receive(self.store,self.report(**changes))
        self.assertEqual(health.snapshot(self.store),[])

    def test_old_outbox_migrates_without_changing_queued_identity_or_revisions(self):
        path=self.root/'legacy.sqlite'
        with closing(sqlite3.connect(path)) as c:
            c.execute('CREATE TABLE identity(producer TEXT NOT NULL)');c.execute("INSERT INTO identity VALUES ('legacy')");c.commit()
        old=Outbox(path,producer='legacy');old.log('r',generation_document('q','a'),state='complete')
        captured=[]
        def transport(request,**kw):
            report=json.loads(request.data);captured.append(report)
            return io.BytesIO(json.dumps(health.receive(self.store,report)).encode())
        with patch('tracker.capture.urlopen',side_effect=transport):
            old.report_status();restarted=Outbox(path,producer='legacy');restarted.report_status()
        self.assertEqual(captured[0]['outbox_id'],captured[1]['outbox_id'])
        self.assertEqual([r['sequence'] for r in captured],[1,2])
        self.assertEqual(restarted.status()['pending'],1)
        with restarted.connect() as c:self.assertEqual(c.execute('SELECT revision FROM queue').fetchone()[0],0)

    def test_reporting_failure_never_blocks_source_delivery(self):
        self.out.log('r',generation_document('q','a'),state='complete')
        with patch('tracker.capture.urlopen',side_effect=OSError('offline')):
            self.assertIn('error',self.out.report_status())
        self.assertEqual(self.out.status()['blocked'],0)
        with patch('tracker.capture.urlopen',side_effect=self.transport):
            self.assertEqual(self.out.drain()['sent_now'],1);self.out.report_status()
        self.assertIsNone(self.out.status()['delivery_report_error'])

    def test_malformed_receiver_json_keeps_data_pending_and_sender_recoverable(self):
        self.out.log('r',generation_document('q','a'),state='complete')
        with patch('tracker.capture.urlopen',side_effect=lambda *a,**kw:io.BytesIO(b'[]')):
            self.assertEqual(self.out.drain()['pending'],1)
            self.assertIn('Invalid delivery report receipt',self.out.report_status()['error'])
        with patch('tracker.capture.urlopen',side_effect=self.transport):self.assertEqual(self.out.drain()['sent_now'],1)

    def test_reports_do_not_wait_for_a_slow_ingestion_request(self):
        self.out.log('r',generation_document('q','a'),state='complete')
        receiving=threading.Event();reported=threading.Event();release=threading.Event();phases=[]
        def transport(request,**kw):
            if request.full_url.endswith('/report'):
                phases.append(json.loads(request.data)['phase'])
                result=self.transport(request,**kw);reported.set();return result
            else:receiving.set();release.wait(5)
            return self.transport(request,**kw)
        with patch('tracker.capture.urlopen',side_effect=transport):
            try:
                self.out.start(report_status=True,report_interval=.2)
                self.assertTrue(receiving.wait(3));self.assertTrue(reported.wait(3))
                self.assertEqual(health.snapshot(self.store)[0]['report']['pending'],1)
            finally:release.set();self.out.close()
        self.assertEqual(phases[-1],'stopped');self.assertEqual(self.out.status()['sent'],1)
        self.assertEqual(health.snapshot(self.store)[0]['status'],'stopped')

    def test_successful_batches_continue_without_an_artificial_idle_pause(self):
        self.out.log_many([{'rollout_id':str(i),'document':generation_document('q','a'),'state':'complete'} for i in range(110)])
        idle=threading.Event();at_wait=[];original_wait=self.out.changed.wait
        def wait_idle(timeout):
            at_wait.append(self.out.status()['pending'])
            if not at_wait[-1]:idle.set()
            return original_wait(.01)
        with patch('tracker.capture.urlopen',side_effect=self.transport),patch.object(self.out.changed,'wait',side_effect=wait_idle):
            try:self.out.start();self.assertTrue(idle.wait(10))
            finally:self.out.close()
        self.assertTrue(at_wait);self.assertTrue(all(n==0 for n in at_wait))
        self.assertEqual(self.out.status()['sent'],110)

    def test_new_captures_do_not_cancel_transient_retry_backoff(self):
        self.out.log('first',generation_document('q','a'),state='complete')
        sleeping=threading.Event();original_wait=self.out.stop.wait;attempts=[]
        def backoff(timeout):sleeping.set();return original_wait(.5)
        def offline(*a,**kw):attempts.append(time.monotonic());raise OSError('collector throttled or offline')
        with patch('tracker.capture.urlopen',side_effect=offline),patch.object(self.out.stop,'wait',side_effect=backoff):
            try:
                self.out.start();self.assertTrue(sleeping.wait(3))
                self.out.log('second',generation_document('q','a'),state='complete')
                time.sleep(.05);self.assertEqual(len(attempts),1)
            finally:self.out.close()
        self.assertEqual(self.out.status()['pending'],2)


if __name__=='__main__':unittest.main()
