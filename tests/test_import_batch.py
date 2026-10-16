import base64
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker.cli import main
from tracker.import_batch import read_bytes,read_request,read_path,preflight
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker.store import Store
from tracker.verl_generation import read_jsonl
from test_tau_bench import bundle


class ImportBatchTests(unittest.TestCase):
    def setUp(self):
        self.row={'input':'Question','output':'Answer','step':7,'score':0}
        self.raw=b'\xef\xbb\xbf'+(json.dumps(self.row)+'\r\n\r\n'+json.dumps(self.row)+'\r\n').encode()
        self.meta={'experiment':'test-batch'}

    def test_ui_cli_and_legacy_verl_reader_preserve_exact_byte_and_line_identity(self):
        body={'file':{'name':'sample.jsonl','base64':base64.b64encode(self.raw).decode()},'metadata':self.meta}
        browser=read_request(body)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sample.jsonl';p.write_bytes(self.raw)
            self.assertEqual(browser,read_path(p,meta=self.meta))
            self.assertEqual(browser,read_jsonl(p,self.meta))
        self.assertEqual([r['metadata']['source_line'] for r in browser],[1,3])
        self.assertEqual(len({r['id'] for r in browser}),2)
        self.assertTrue(all(r['metadata']['source_file_sha256']==hashlib.sha256(self.raw).hexdigest() for r in browser))

    def test_fully_validated_jsonl_is_atomic_before_database_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            with self.assertRaisesRegex(InputError,'line 4'):
                store.add(read_bytes(self.raw+b'{invalid',name='batch.jsonl',meta=self.meta))
            self.assertEqual(store.list(),[])

    def test_native_bundle_validation_is_atomic_too(self):
        doc=bundle();doc['simulations'][1]['messages'][0]['tool_calls'][0]['arguments']=None
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            with self.assertRaises(InputError):store.add(read_bytes(json.dumps(doc).encode()))
            self.assertEqual(store.list(),[])

    def test_preflight_bounds_details_but_validates_and_counts_whole_batch(self):
        raw=('\n'.join(json.dumps(dict(self.row,step=i)) for i in range(12))).encode()
        runs=read_bytes(raw,name='batch.jsonl',meta=self.meta);check=preflight(runs)
        self.assertEqual(check['total_rollouts'],12);self.assertEqual(len(check['runs']),5)
        self.assertEqual(check['metric_coverage']['recorded_reward'],{'available':12,'missing':0})
        self.assertEqual(check['metric_coverage']['actions'],{'available':0,'missing':12})
        self.assertEqual(check['declared_training_coordinates'],12)
        self.assertFalse(check['persisted'])

    def test_jsonl_accepts_portable_contracts_without_inventing_training_steps(self):
        doc=generation_document('P','C',reward=0)
        runs=read_bytes((json.dumps(doc)+'\n'+json.dumps(doc)).encode(),name='flat.jsonl',meta=self.meta)
        self.assertEqual(len({r['id'] for r in runs}),2)
        self.assertEqual(preflight(runs)['declared_training_coordinates'],0)

    def test_non_json_and_missing_identity_fail_with_actionable_error(self):
        for raw,name,meta,pattern in [(self.raw,'b.jsonl',None,'experiment'),(b'[]','b.jsonl',self.meta,'object'),
                (b'\n\n','b.jsonl',self.meta,'no records'),(b'\xff','b.json',None,'UTF-8'),
                (json.dumps(bundle()).encode(),'b.jsonl',self.meta,'one rollout')]:
            with self.assertRaisesRegex(InputError,pattern):read_bytes(raw,name=name,meta=meta)
        with self.assertRaisesRegex(InputError,'size limit'):read_bytes(self.raw,max_bytes=4)
        with self.assertRaisesRegex(InputError,'metadata'):read_bytes(b'{}',meta=[])
        with self.assertRaisesRegex(InputError,'base64'):read_request({'file':{'name':'x.json','base64':'$invalid'}})

    def test_batch_preflight_cli_never_opens_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'results.json';p.write_text(json.dumps(bundle()))
            out=io.StringIO()
            with patch('sys.argv',['tracker','check',str(p)]),patch('tracker.cli.Store',side_effect=AssertionError('Database opened')),redirect_stdout(out):main()
            self.assertEqual(json.loads(out.getvalue())['total_rollouts'],2)


if __name__=='__main__':unittest.main()
