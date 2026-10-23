"""Actual s3fs/botocore transport against a controlled versioned S3 HTTP endpoint."""
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from rilldex import Run,Workspace


@unittest.skipUnless(importlib.util.find_spec('s3fs'),'requires optional s3fs')
class S3ReferenceTests(unittest.TestCase):
    def test_versioned_native_driver_reads_ranges_and_missing_versions_leave_no_file(self):
        data=b'old-policy-weights'*180000;requests=[]
        class Handler(BaseHTTPRequestHandler):
            def serve(self,head):
                parsed=urlsplit(self.path);version=parse_qs(parsed.query).get('versionId',['latest'])[0]
                requests.append((self.command,parsed.path,version,self.headers.get('Range')))
                if parsed.path!='/checkpoints/policy.bin' or version=='missing':
                    self.send_response(404);self.send_header('Content-Length','0');self.end_headers();return
                body=data if version=='v1' else b'x'*len(data);size=len(body)
                start,end=0,size-1;range_header=self.headers.get('Range')
                if range_header:
                    first,last=range_header.removeprefix('bytes=').split('-');start=int(first);end=min(size-1,int(last)) if last else size-1
                self.send_response(206 if range_header else 200)
                self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Type','application/octet-stream')
                self.send_header('ETag','"'+hashlib.md5(body).hexdigest()+'"');self.send_header('Last-Modified','Thu, 22 Oct 2026 10:00:00 GMT')
                self.send_header('x-amz-version-id',version);self.send_header('Accept-Ranges','bytes')
                if range_header:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.end_headers()
                if not head:self.wfile.write(body[start:end+1])
            def do_HEAD(self):self.serve(True)
            def do_GET(self):self.serve(False)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=root/'study.sqlite'
            with patch('rilldex.run.runtime_context',return_value={}):run=Run('s3',workspace=db,experiment='s3',capture_console=False,hardware=False)
            run.add_reference('s3://checkpoints/policy.bin',version='v1',size=len(data),sha256=hashlib.sha256(data).hexdigest())
            run.add_reference('s3://checkpoints/policy.bin?versionId=v1',size=len(data),sha256=hashlib.sha256(data).hexdigest())
            run.add_reference('s3://checkpoints/policy.bin',version='missing')
            ws=Workspace(db,experiment='s3');rows=ws.run_records(kind='file')['rows']
            options={'anon':True,'skip_instance_cache':True,'client_kwargs':{'endpoint_url':f'http://127.0.0.1:{server.server_port}','region_name':'us-east-1'}}
            for index in (0,1):
                result=ws.download_file(rows[index]['sequence'],root/f'policy-{index}.bin',storage_options=options)
                self.assertEqual(result['verification'],'sha256');self.assertEqual(result['sha256'],hashlib.sha256(data).hexdigest())
            self.assertTrue(all(version=='v1' for _,_,version,_ in requests));self.assertGreaterEqual(sum(method=='GET' and ranges is not None for method,_,_,ranges in requests),6)
            with self.assertRaises(FileNotFoundError):ws.download_file(rows[2]['sequence'],root/'missing.bin',storage_options=options)
            self.assertFalse((root/'missing.bin').exists());self.assertFalse(list(root.glob('.rilldex-download-*')))


if __name__=='__main__':unittest.main()
