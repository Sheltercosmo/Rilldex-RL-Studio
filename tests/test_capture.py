import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from tracker.capture import Outbox
from tracker.schema import InputError
from tracker.store import Store
from test_tracker import harbor


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'outbox.sqlite';self.store=Store(Path(self.tmp.name)/'server.sqlite')
        self.client=Outbox(self.path,producer='train/worker-0')

    def send(self,request,**kwargs):
        return io.BytesIO(json.dumps(self.store.ingest(json.loads(request.data))).encode())

    def log(self,**kwargs):return self.client.log('1/sample-2/0',harbor(),state='complete',metadata={'experiment':'train','training_step':1},**kwargs)

    def test_log_is_local_and_bounded_then_restart_delivers(self):
        with patch('tracker.capture.urlopen',side_effect=URLError('offline')) as network:
            a=self.log();self.assertEqual(network.call_count,0)
            self.assertEqual(self.log()['queued_id'],a['queued_id'])
            self.assertEqual(self.client.drain()['pending'],1)
        restarted=Outbox(self.path,producer='train/worker-0')
        with patch('tracker.capture.urlopen',side_effect=self.send):
            self.assertEqual(restarted.drain()['sent_now'],1)
            self.assertEqual(restarted.drain()['sent_now'],0)
        self.assertEqual(self.store.list()[0]['metadata']['training_step'],1)
        self.assertEqual(restarted.status()['pending_bytes'],0)

    def test_lost_acknowledgement_retries_exact_revision_once(self):
        self.log()
        def lost_ack(request,**kwargs):
            self.send(request);raise OSError('Connection lost after commit')
        with patch('tracker.capture.urlopen',side_effect=lost_ack):self.client.drain()
        with patch('tracker.capture.urlopen',side_effect=self.send):self.client.drain()
        self.assertEqual(len(self.store.list()),1)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM rollout_revisions').fetchone()[0],1)

    def test_each_revision_preserved_and_delivered_in_order(self):
        self.client.log('a',harbor(),state='in_progress')
        doc=harbor();doc['steps'][-1]['message']='Updated'
        self.client.log('a',doc,state='complete')
        with patch('tracker.capture.urlopen',side_effect=self.send):self.client.drain()
        row=self.store.list()[0];self.assertEqual(row['ingestion']['revision'],1)
        self.assertEqual(len(self.store.lineage(row['id'])['history']),2)

    def test_permanent_failure_blocks_only_that_rollout(self):
        self.client.log('bad',harbor(),state='in_progress')
        self.client.log('bad',harbor(),state='complete')
        self.client.log('good',harbor(),state='complete')
        seen=[]
        def transport(request,**kwargs):
            value=json.loads(request.data);seen.append((value['rollout_id'],value['revision']))
            if value['rollout_id']=='bad':raise HTTPError(request.full_url,409,'Conflict',{},io.BytesIO(b'producer conflict'))
            return self.send(request)
        with patch('tracker.capture.urlopen',side_effect=transport):result=self.client.drain()
        self.assertEqual(seen,[('bad',0),('good',0)])
        self.assertEqual((result['blocked'],result['pending'],result['sent']),(1,1,1))
        self.assertEqual(self.client.retry_blocked(),1)
        with patch('tracker.capture.urlopen',side_effect=self.send):
            self.assertEqual(self.client.drain()['sent'],3)

    def test_backpressure_keeps_pending_data_and_identity(self):
        self.log();before=self.client.status()
        self.client.max_pending_bytes=1
        with self.assertRaises(BufferError):self.client.log('another',harbor(),state='complete')
        self.assertEqual(self.client.status()['pending'],before['pending'])
        with self.assertRaises(InputError):Outbox(self.path,producer='different')

    def test_bad_metadata_rejected_before_queueing(self):
        with self.assertRaises(InputError):self.client.log('a',harbor(),state='complete',metadata={'training_step':'1'})
        self.assertEqual(self.client.status()['pending'],0)


if __name__=='__main__':unittest.main()
