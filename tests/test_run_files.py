import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rilldex import Run, Workspace, Outbox
from tracker import run_records, run_files, capture_bundle, workspace_snapshot
from tracker.schema import InputError
from tracker.store import Store


class RunFileTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.store=Store(self.root/'study.sqlite');self.ws=Workspace(self.store.path,experiment='files')

    def run_record(self,**kwargs):
        with patch('rilldex.run.runtime_context',return_value={}):
            return Run('files',experiment='files',workspace=self.store.path,capture_console=False,hardware=False,**kwargs)

    def files(self):return run_records.records(self.store,experiment='files',kind='file')['rows']

    def test_large_file_stays_external_and_streams_to_verified_copy(self):
        source=self.root/'checkpoint.bin';block=b'checkpoint data\n'*(1024*64)
        with source.open('wb') as stream:
            for _ in range(80):stream.write(block)
        run=self.run_record();run.add_reference(source,role='checkpoint',step=100)
        row=self.files()[0];p=row['record']['payload']
        self.assertEqual(p['size'],source.stat().st_size);self.assertNotIn('content_base64',p)
        self.assertEqual((p['clock'],p['step'],p['trainer_session']),('learner_update',100,run.session))
        with self.store.connect() as c:self.assertLess(len(c.execute("SELECT document FROM run_records WHERE kind='file'").fetchone()[0]),2000)
        result=self.ws.download_file(row['sequence'],self.root/'copy.bin')
        self.assertEqual((result['bytes'],result['sha256'],result['verification']),(p['size'],p['sha256'],'sha256'))
        with self.assertRaises(InputError):run_records.file_content(self.store,experiment='files',sequence=row['sequence'])
        with self.assertRaises(InputError):self.ws.download_file(row['sequence'],self.root/'copy.bin')
        self.assertEqual((self.root/'copy.bin').stat().st_size,p['size'])

    def test_changed_missing_or_interrupted_source_never_publishes_partial_download(self):
        source=self.root/'source.bin';source.write_bytes(b'old content')
        run=self.run_record();run.add_reference(source);seq=self.files()[0]['sequence']
        source.write_bytes(b'new content')
        with self.assertRaisesRegex(InputError,'checksum'):self.ws.download_file(seq,self.root/'changed.bin')
        source.unlink()
        with self.assertRaises(FileNotFoundError):self.ws.download_file(seq,self.root/'missing.bin')
        class Interrupted(io.BytesIO):
            def read(self,n=-1):raise ConnectionError('connection interrupted')
        with self.assertRaises(ConnectionError):self.ws.download_file(seq,self.root/'partial.bin',opener=lambda ref:Interrupted())
        self.assertFalse(any(self.root.glob('*.bin')));self.assertFalse(list(self.root.glob('.rilldex-download-*')))

    def test_directory_members_paths_and_limits_are_retained(self):
        directory=self.root/'checkpoint';(directory/'weights').mkdir(parents=True)
        (directory/'config.json').write_text('{}');(directory/'weights'/'part-01.bin').write_bytes(b'123');(directory/'weights'/'part-02.bin').write_bytes(b'456')
        run=self.run_record()
        with self.assertRaises(InputError):run.add_reference(directory,max_files=2)
        self.assertEqual(self.files(),[])
        result=run.add_reference(directory,role='checkpoint');rows=self.files()
        self.assertEqual(result['files'],3);self.assertEqual(len({r['record']['payload']['collection'] for r in rows}),1)
        self.assertEqual({r['record']['payload']['name'] for r in rows},{'checkpoint/config.json','checkpoint/weights/part-01.bin','checkpoint/weights/part-02.bin'})
        self.assertTrue(all(r['record']['payload']['collection_size']==3 for r in rows))

    def test_http_reference_streams_and_unverified_identity_stays_explicit(self):
        data=b'a real HTTP artifact'*200000
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers()
                for n in range(0,len(data),65536):self.wfile.write(data[n:n+65536])
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        uri=f'http://127.0.0.1:{server.server_port}/checkpoint.bin';run=self.run_record()
        with patch('tracker.run_files.urlopen',side_effect=AssertionError('Recording must not fetch remote bytes')):
            run.add_reference(uri,sha256=hashlib.sha256(data).hexdigest(),size=len(data))
            run.add_reference(uri,name='unknown.bin')
        rows=self.files()
        result=self.ws.download_file(rows[0]['sequence'],self.root/'http.bin');self.assertEqual(result['verification'],'sha256')
        result=self.ws.download_file(rows[1]['sequence'],self.root/'unknown.bin');self.assertEqual(result['verification'],'unverified')

    def test_object_versions_are_passed_to_native_storage_drivers(self):
        data=b'old checkpoint';run=self.run_record()
        for uri,version,protocol,keyword in [('s3://bucket/key','v1','s3','version_id'),('gs://bucket/key','17','gcs','generation')]:
            run.add_reference(uri,name=protocol+'.bin',version=version,size=len(data),sha256=hashlib.sha256(data).hexdigest())
            row=self.files()[-1]
            class FileSystem:
                def open(self,path,mode,**options):
                    self.options=options;self.path=path;return io.BytesIO(data)
            fs=FileSystem()
            with patch.dict('sys.modules',{'fsspec':type('FSSpec',(),{'filesystem':staticmethod(lambda p,**opts:fs)})}):
                result=self.ws.download_file(row['sequence'],self.root/(protocol+'.bin'))
            self.assertEqual(fs.options[keyword],version);self.assertEqual(result['verification'],'sha256')

    def test_outbox_transfer_and_workspace_restore_preserve_reference_not_bytes(self):
        source=self.root/'weights.bin';source.write_bytes(b'weights')
        outbox=Outbox(self.root/'outbox.sqlite',producer='worker')
        run=self.run_record(target=outbox,producer='worker');run.add_reference(source,role='checkpoint');run.close()
        archive=self.root/'capture.zip';capture_bundle.export(outbox.path,archive);capture_bundle.receive(self.store,archive)
        row=self.files()[0];self.assertEqual(row['record']['payload']['sha256'],hashlib.sha256(b'weights').hexdigest())
        snapshot=self.root/'snapshot.zip';workspace_snapshot.export(self.store,snapshot)
        restored=self.root/'restored.sqlite';workspace_snapshot.restore(snapshot,restored)
        result=Workspace(restored,experiment='files').download_file(row['sequence'],self.root/'restored-weights.bin')
        self.assertEqual(result['verification'],'sha256');self.assertLess(snapshot.stat().st_size,source.stat().st_size+1000000)

    def test_reference_validation_and_embedded_file_backward_compatibility(self):
        run=self.run_record();source=self.root/'tiny.txt';source.write_text('small');run.add_file(source)
        row=self.files()[0];self.assertEqual(self.ws.download_file(row['sequence'],self.root/'tiny-copy.txt')['verification'],'sha256')
        good=run_files.reference_payload('s3://bucket/key',name='checkpoint/key',size=10)
        for update in ({'name':'../escape'},{'sha256':'etag'},{'size':True},{'reference':{'uri':'javascript:alert(1)'}},{'reference':{'uri':'https://user:password@example.com/a'}},{'content_base64':'YQ=='},{'step':1}):
            value=copy.deepcopy(good);value.update(update)
            with self.subTest(update=update),self.assertRaises(InputError):run_files.validate_reference(value)
        self.assertEqual(self.files()[0]['record']['payload']['size'],5)

    def test_file_uri_hashes_and_detects_mutation_during_capture(self):
        run=self.run_record();source=self.root/'with spaces.bin';source.write_bytes(b'checkpoint')
        run.add_reference(source.as_uri());self.assertEqual(self.files()[0]['record']['payload']['sha256'],hashlib.sha256(b'checkpoint').hexdigest())
        original=hashlib.sha256
        class MutatingHash:
            def __init__(self):self.inner=original()
            def update(self,block):
                self.inner.update(block)
                with source.open('ab') as stream:stream.write(b'changed')
            def hexdigest(self):return self.inner.hexdigest()
        with patch('tracker.run_files.hashlib.sha256',MutatingHash),self.assertRaisesRegex(InputError,'changed'):
            run.add_reference(source)
        self.assertEqual(len(self.files()),1)

    def test_truncated_transfer_without_recorded_size_is_not_published(self):
        run=self.run_record();run.add_reference('https://example.org/model.bin')
        class ShortStream(io.BytesIO):headers={'Content-Length':'100'}
        with self.assertRaisesRegex(InputError,'ended early'):
            self.ws.download_file(self.files()[0]['sequence'],self.root/'incomplete.bin',opener=lambda ref:ShortStream(b'short'))
        self.assertFalse((self.root/'incomplete.bin').exists());self.assertFalse(list(self.root.glob('.rilldex-download-*')))


if __name__=='__main__':unittest.main()
