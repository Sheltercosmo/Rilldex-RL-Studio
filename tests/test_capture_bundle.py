import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tracker import capture_bundle as bundle
from tracker.capture import Outbox
from tracker.schema import InputError
from tracker.store import Store
from test_tracker import harbor
from test_training_lineage import record
from test_continuation_studies import example
from test_training_recipes import manifest


class OfflineCaptureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = Outbox(self.root/'worker.sqlite', producer='worker')
        self.store = Store(self.root/'review.sqlite')

    def log(self, name='a', state='complete'):
        return self.out.log(name, harbor(), state=state, metadata={'experiment':'exp'})

    def export(self, name='capture.zip'):
        path=self.root/name; bundle.export(self.out.path,path); return path

    def send(self, req, **kwargs):
        return io.BytesIO(json.dumps(self.store.ingest(json.loads(req.data))).encode())

    def test_no_server_multi_revision_transfer_and_http_replay_keep_identity(self):
        self.log(state='in_progress'); self.log()
        with patch('tracker.capture.urlopen', side_effect=AssertionError('No network expected')):
            path=self.export(); self.assertEqual(bundle.inspect(path)['packets'],2)
            result=bundle.receive(self.store,path)
        self.assertEqual(result['accepted'],2)
        self.assertEqual(self.out.status()['pending'],2)  # copy is not an acknowledgment
        self.assertEqual(bundle.receive(self.store,path)['already_present'],2)
        with patch('tracker.capture.urlopen',side_effect=self.send):
            self.assertEqual(self.out.drain()['sent_now'],2)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM rollout_revisions').fetchone()[0],2)

    def test_distinct_workers_and_later_exports_merge_without_collisions(self):
        self.log(); first=self.export(); bundle.receive(self.store,first)
        self.log('b'); second=self.export('later.zip')
        self.assertEqual(bundle.receive(self.store,second)['accepted'],1)
        other=Outbox(self.root/'second.sqlite',producer='worker-1')
        other.log('a',harbor(),state='complete')
        bundle.export(other.path,self.root/'other.zip')
        self.assertEqual(bundle.receive(self.store,self.root/'other.zip')['accepted'],1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM rollout_revisions').fetchone()[0],3)

    def test_all_training_packet_types_survive_offline_transfer(self):
        self.out.log_training('exp',[record('sample')])
        self.out.log_recipes('exp',[manifest()])
        # Use a validated study fixture and its original producer on a second worker.
        study,records=example(1)
        other=Outbox(self.root/'study.sqlite',producer=study['producer'])
        other.log_continuation_studies(study['experiment'],study['studies'])
        other.log_training(records['experiment'],records['records'],schema=records['schema'])
        one=self.export(); two=self.root/'study.zip'; bundle.export(other.path,two)
        self.assertTrue(bundle.receive(self.store,one)['complete'])
        self.assertEqual(bundle.receive(self.store,two)['accepted'],2)
        self.assertEqual(bundle.receive(self.store,one)['already_present'],2)
        self.assertEqual(bundle.receive(self.store,two)['already_present'],2)

    def test_corrupt_late_packet_is_rejected_before_any_import(self):
        self.log('a'); self.log('b'); original=self.export(); bad=self.root/'bad.zip'
        with zipfile.ZipFile(original) as src,zipfile.ZipFile(bad,'w') as dst:
            for name in src.namelist():
                raw=src.read(name)
                if name=='packets/000001.json': raw=raw.replace(b'complete',b'failed')
                dst.writestr(name,raw)
        with self.assertRaises(InputError): bundle.receive(self.store,bad)
        self.assertEqual(self.store.list(),[])

    def test_missing_predecessor_reports_failure_but_other_worker_rollout_continues(self):
        self.log(state='in_progress')
        with patch('tracker.capture.urlopen',side_effect=self.send): self.out.drain()
        self.log(); self.log('independent')
        path=self.export()
        target=Store(self.root/'fresh.sqlite')
        result=bundle.receive(target,path)
        self.assertEqual((result['accepted'],result['failed'],result['complete']),(1,1,False))
        self.assertIn('Expected revision 0',result['errors'][0]['error'])
        self.assertEqual(bundle.receive(self.store,path)['accepted'],2)

    def test_missing_outbox_existing_destination_and_wrong_archive_are_safe(self):
        absent=self.root/'missing.sqlite'
        with self.assertRaises(InputError): bundle.export(absent,self.root/'none.zip')
        self.assertFalse(absent.exists())
        self.log(); path=self.export(); before=path.read_bytes()
        with self.assertRaises(FileExistsError): bundle.export(self.out.path,path)
        self.assertEqual(path.read_bytes(),before)
        with zipfile.ZipFile(self.root/'unsafe.zip','w') as z:
            z.writestr('manifest.json',json.dumps({'schema':bundle.VERSION,'producer':'worker','entries':[]}))
            z.writestr('../escape','bad')
        with self.assertRaises(InputError): bundle.receive(self.store,self.root/'unsafe.zip')
        self.assertFalse((self.root.parent/'escape').exists())

    def test_cli_receives_without_server_and_replays_idempotently(self):
        self.log(); path=self.export()
        args=[sys.executable,'-m','rilldex','--db',str(self.root/'cli.sqlite'),'capture','import',str(path)]
        a=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(a.returncode,0,a.stderr)
        b=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(json.loads(b.stdout)['bundles'][0]['already_present'],1)

    def test_returned_receipts_free_exact_payloads_and_preserve_future_revisions(self):
        self.log(state='in_progress'); self.log()
        result=bundle.receive(self.store,self.export(),with_receipts=True)
        receipt=self.root/'receipts.json'
        receipt.write_text(json.dumps({'schema':'jev-capture-receipts/1','acknowledgments':result['acknowledgments']}))
        self.log('later')
        self.assertEqual(bundle.acknowledge(self.out.path,receipt)['acknowledged'],2)
        self.assertEqual(self.out.status()['pending'],1)
        self.assertEqual(bundle.acknowledge(self.out.path,receipt)['already_acknowledged'],2)
        self.assertEqual(self.out.log('a',harbor(),state='failed',metadata={'experiment':'exp'})['revision'],2)
        self.assertEqual(bundle.receive(self.store,self.export('next.zip'))['accepted'],2)

    def test_wrong_receipt_is_atomic_and_never_clears_original_queue(self):
        self.log('a'); self.log('b')
        result=bundle.receive(self.store,self.export(),with_receipts=True)
        result['acknowledgments'][-1]['receipt']['id']='wrong'
        receipt=self.root/'receipts.json'
        receipt.write_text(json.dumps({'schema':'jev-capture-receipts/1','acknowledgments':result['acknowledgments']}))
        with self.assertRaises(InputError): bundle.acknowledge(self.out.path,receipt)
        self.assertEqual(self.out.status()['pending'],2)
        other=Outbox(self.root/'other.sqlite',producer='worker');other.log('a',harbor(),state='complete')
        with self.assertRaises(InputError): bundle.acknowledge(other.path,receipt)
        self.assertEqual(other.status()['pending'],1)

    def test_export_is_a_consistent_snapshot_while_worker_appends(self):
        self.log('a'); original=bundle.validate; appended=False
        def during_export(payload, producer):
            nonlocal appended
            if not appended:
                appended=True;self.log('later')
            return original(payload,producer)
        with patch('tracker.capture_bundle.validate',side_effect=during_export): path=self.export()
        self.assertEqual(bundle.inspect(path)['packets'],1)
        self.assertEqual(self.out.status()['pending'],2)
        self.assertEqual(bundle.inspect(self.export('next.zip'))['packets'],2)


if __name__=='__main__': unittest.main()
