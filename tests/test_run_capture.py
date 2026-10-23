import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from rilldex import Run, Outbox, Workspace
from tracker import run_records as rr, capture_bundle, workspace_snapshot
from tracker.experiment_catalog import catalog
from tracker.schema import InputError
from tracker.store import Store
import test_generation_cohort_transport as transport


class RunCaptureTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name); self.db=self.root/'study.sqlite'; self.store=Store(self.db)

    def recorder(self,**kwargs):
        return Run('trial',project='project',workspace=self.db,hardware=False,**kwargs)

    def test_python_capture_restart_files_and_project_isolation(self):
        source=self.root/'config.json';source.write_text('{"lr":0.01}',encoding='utf-8')
        stdout=io.StringIO();stderr=io.StringIO()
        with patch('sys.stdout',stdout),patch('sys.stderr',stderr):
            with self.recorder(config={'lr':0.01}) as r:
                print('loss = 1.0');print('warning',file=sys.stderr)
                r.log({'train/loss':1.0},step=0);r.add_file(source)
                source.write_text('{"lr":0.02}',encoding='utf-8');r.add_file(source)
            self.assertIs(sys.stdout,stdout);self.assertIs(sys.stderr,stderr)
        with self.recorder(capture_console=False) as restarted: restarted.console('restart')
        with Run('trial',project='second',workspace=self.db,hardware=False,capture_console=False): pass
        self.assertNotEqual(r.session,restarted.session)
        records=rr.records(self.store,experiment=r.experiment)
        self.assertEqual(records['counts'],{'manifest':2,'lifecycle':4,'console':3,'file':2})
        files=rr.records(self.store,experiment=r.experiment,kind='file')['rows']
        source.unlink()
        self.assertNotEqual(files[0]['record']['payload']['sha256'],files[1]['record']['payload']['sha256'])
        self.assertNotIn('content_base64',files[0]['record']['payload'])
        self.assertEqual(rr.file_content(self.store,experiment=r.experiment,sequence=files[0]['sequence'])[1],b'{"lr":0.01}')
        self.assertEqual(catalog(self.store)['total'],2)
        self.assertEqual(Workspace(self.db,experiment=r.experiment).run_records(kind='console')['total'],3)
        from tracker.analytics import Analysis
        values=Analysis(self.db).table('run_capture',experiment=r.experiment)
        self.assertEqual(len(values['rows']),11)
        self.assertNotIn('content_base64',json.dumps(values))

    def test_paging_worker_search_and_late_arrivals(self):
        r=self.recorder(capture_console=False,producer='worker-a')
        for i in range(5):r.console('line '+str(i))
        other=self.recorder(capture_console=False,producer='worker-b');other.console('another')
        page=rr.records(self.store,experiment=r.experiment,kind='console',limit=2,producer='worker-a')
        self.assertTrue(page['more']);r.console('late')
        following=rr.records(self.store,experiment=r.experiment,kind='console',after=page['next_cursor'],producer='worker-a')
        self.assertEqual(len(following['rows']),4)
        tail=rr.records(self.store,experiment=r.experiment,kind='console',tail=True,limit=2)
        self.assertEqual(tail['rows'][-1]['record']['payload']['text'],'late')
        self.assertEqual(rr.records(self.store,experiment=r.experiment,kind='console',q='line 3')['total'],1)
        r.close();other.close()

    def test_transport_atomic_conflicts_file_validation_and_immutable_download(self):
        r=self.recorder(capture_console=False);r.console('hello');r.close()
        with self.store.connect() as c:record=json.loads(c.execute("SELECT document FROM run_records WHERE kind='console'").fetchone()[0])
        packet=dict(schema=rr.VERSION,producer=r.producer,experiment=r.experiment,records=[record])
        self.assertEqual(rr.receive(self.store,packet)['inserted'],0)
        new=copy.deepcopy(record);new['id']='new';changed=copy.deepcopy(record);changed['payload']['text']='different'
        packet['records']=[new,changed]
        with self.assertRaises(InputError):rr.receive(self.store,packet)
        self.assertEqual(rr.records(self.store,experiment=r.experiment,kind='console')['total'],1)
        source=self.root/'file.txt';source.write_text('hello',encoding='utf-8')
        r=self.recorder(capture_console=False)
        with self.assertRaises(InputError):r.add_file(source,name='../escape')
        source.write_bytes(b'a'*(rr.MAX_FILE+1))
        with self.assertRaises(InputError):r.add_file(source)
        with self.assertRaises(InputError):r._record('hardware',{'host':'x','cpu_percent':float('nan')})
        r.close()

    def test_offline_bundle_restart_ack_and_workspace_snapshot(self):
        path=self.root/'outbox.sqlite';box=Outbox(path,producer='worker')
        with Run('trial',project='project',target=box,hardware=False,capture_console=False) as r:r.console('offline')
        box=Outbox(path,producer='worker');self.assertEqual(box.status()['pending'],4)
        bundle=self.root/'capture.zip';capture_bundle.export(path,bundle)
        result=capture_bundle.receive(self.store,bundle,with_receipts=True);self.assertTrue(result['complete'])
        self.assertEqual(capture_bundle.receive(self.store,bundle)['already_present'],4)
        ack=self.root/'ack.json';ack.write_text(json.dumps({'schema':'jev-capture-receipts/1','acknowledgments':result['acknowledgments']}),encoding='utf-8')
        self.assertEqual(capture_bundle.acknowledge(path,ack)['acknowledged'],4)
        rr.organize(self.store,experiment=r.experiment,project='research',title='Trial A',tags=['baseline'],pinned=True)
        rr.save_selection(self.store,name='baseline',experiments=[r.experiment])
        snapshot=self.root/'workspace.zip';workspace_snapshot.export(self.store,snapshot)
        restored=self.root/'restored.sqlite';workspace_snapshot.restore(snapshot,restored)
        result=catalog(Store(restored));self.assertEqual(result['rows'][0]['title'],'Trial A');self.assertEqual(result['selections'][0]['name'],'baseline')
        self.assertEqual(rr.records(Store(restored),experiment=r.experiment,kind='console')['total'],1)

    def test_organization_filters_and_restart_does_not_rename(self):
        with self.recorder(capture_console=False) as r: pass
        rr.organize(self.store,experiment=r.experiment,title='Friendly run',project='team',tags=['focus'],archived=True,pinned=True)
        with self.recorder(capture_console=False):pass
        self.assertEqual(catalog(self.store)['total'],0)
        result=catalog(self.store,state='archived',project='team',q='focus')
        self.assertEqual(result['rows'][0]['title'],'Friendly run')
        rr.organize(self.store,experiment=r.experiment,archived=False)
        self.assertEqual(catalog(self.store,state='pinned')['total'],1)
        self.assertEqual(catalog(self.store,project='other')['total'],0)

    def test_cli_captures_unicode_stderr_and_failure_exit(self):
        code="import sys; print('training λ',flush=True); print('failure',file=sys.stderr); sys.exit(7)"
        command=[sys.executable,'-X','utf8','-m','tracker','--db',str(self.db),'record','--name','CLI','--no-hardware','--',sys.executable,'-X','utf8','-c',code]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=dict(os.environ,PYTHONUTF8='1'),timeout=30)
        self.assertEqual(result.returncode,7,result.stderr);self.assertIn('training λ',result.stdout)
        rows=rr.records(self.store,experiment='default/CLI')['rows']
        self.assertEqual(rows[-1]['record']['payload']['exit_code'],7)
        self.assertTrue(any(r['record']['payload'].get('stream')=='stderr' for r in rows))

    def test_sensor_absence_is_not_zero_and_worker_identity_is_recorded(self):
        from rilldex.run import hardware_sample
        with patch.dict(sys.modules,{'psutil':None}),patch('rilldex.run._command',side_effect=FileNotFoundError):sample=hardware_sample()
        self.assertIsNone(sample['cpu_percent']);self.assertEqual(sample['gpus'],[]);self.assertEqual(len(sample['unavailable']),2)
        with patch.dict(sys.modules,{'psutil':None}),patch('rilldex.run._command',return_value='GPU-1, H100, 92, 1024, 81920, 60, 200'):
            sample=hardware_sample()
        self.assertEqual(sample['gpus'][0]['memory_used_bytes'],1073741824)

    def test_http_durable_delivery_and_file_download(self):
        endpoint=transport.GenerationCohortTransportTests.start_server(self)
        path=self.root/'outbox.sqlite';box=Outbox(path,producer='remote',endpoint=endpoint)
        source=self.root/'config.txt';source.write_text('config content',encoding='utf-8')
        with Run('remote',target=box,hardware=False,capture_console=False) as r:r.console('live');r.add_file(source)
        self.assertEqual(box.drain()['sent_now'],5)
        query=urlencode({'experiment':r.experiment,'kind':'file'})
        with urlopen(endpoint+'/api/run-records?'+query) as response:result=json.load(response)
        sequence=result['rows'][0]['sequence']
        with urlopen(endpoint+'/api/run-file?'+urlencode({'experiment':r.experiment,'sequence':sequence})) as response:self.assertEqual(response.read(),b'config content')
        request=Request(endpoint+'/api/experiment-labels',data=json.dumps({'experiment':r.experiment,'title':'Remote run','project':'cluster'}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request) as response:self.assertEqual(json.load(response)['project'],'cluster')
        with urlopen(endpoint+'/api/monitoring') as response:
            experiments=json.load(response)['experiments']
            self.assertEqual(next(e for e in experiments if e['id']==r.experiment)['label'],'Remote run')
        with urlopen(endpoint+'/run-capture.js') as response:self.assertIn(b'RunCapture',response.read())
        for route in ('experiment-labels','experiment-selections'):
            request=Request(endpoint+'/api/'+route,data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(error.exception.code,400)

    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_cli_disconnected_queue_and_non_utf8_console(self):
        path=self.root/'offline.sqlite'
        result=subprocess.run([sys.executable,'-X','utf8','-m','tracker','record','--name','offline','--offline',
            '--outbox',str(path),'--producer','worker','--no-hardware','--encoding','cp1252','--',
            sys.executable,'-c',"import sys; sys.stdout.buffer.write('café'.encode('cp1252'))"],
            capture_output=True,text=True,encoding='utf-8',timeout=30,env=dict(os.environ,PYTHONUTF8='1'))
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,'café')
        box=Outbox(path,producer='worker');self.assertEqual(box.status()['pending'],4)
        with box.connect() as c: payloads=[json.loads(row[0]) for row in c.execute('SELECT payload FROM queue')]
        text=[r['payload']['text'] for packet in payloads for r in packet['run_records']['records'] if r['kind']=='console']
        self.assertEqual(text,['café'])


if __name__=='__main__':unittest.main()
