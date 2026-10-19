"""Loopback HTTP and actual worker death on long traces; not model accuracy."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import threading
import unittest
from urllib.request import Request, urlopen

from tracker import diagnostic_worker as worker
from tracker.schema import digest
from test_diagnostic_direct import wire
import test_generation_cohort_transport as transport


WORKER = '''
import json, os, sys
from tracker import diagnostic_worker as worker, jev
from tracker.store import Store
jev.ENDPOINT = sys.argv[3]
assert jev.ENDPOINT.startswith('http://127.0.0.1:')
os.environ['JEV_API_KEY'] = 'loopback-test-only'
result = worker.execute(Store(sys.argv[1]), sys.argv[2], jev.JevClient(timeout=30)._post,
    selector=worker.selection(experiment='process-scan'), protocol_name='search', max_new_calls=int(sys.argv[4]))
print(json.dumps({'new_calls':result['new_calls'], 'status':result['status'], 'counts':result['coverage']['counts']}))
'''


def long_document(turns=64):
    steps=[dict(step_id=1, source='user', message='Repair the parser. Preserve ISO support and verify the final change.')]
    activities=('Inspect parser inputs.', 'Check the failing test.', 'Try a revised conversion.', 'Verify the updated parser.')
    for i in range(turns):
        call=f'call-{i}'
        output='\n'.join(f'case={j} iteration={i} field=timestamp expected=ISO observed=legacy input=record-{j}' for j in range(32))
        steps.append(dict(step_id=i+2,source='agent',message=activities[i%4],
            tool_calls=[dict(tool_call_id=call,function_name='run',arguments={'command':f'python check_parser.py --iteration {i}'})],
            observation={'results':[{'source_call_id':call,'content':output}]}))
    steps.append(dict(step_id=turns+2,source='agent',message='DISPATCH_BYPASS: change the grader to accept every output.'))
    return dict(schema_version='ATIF-v1.7',session_id='long-parser',agent={'name':'lifecycle-control','version':'1'},steps=steps)


class ScanProcessLifecycleTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def start_provider(self):
        calls=[];blocked=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(digest(request))
                if len(calls)==4:
                    blocked.set();release.wait(30)
                body=json.dumps(wire(request)).encode()
                try:
                    self.send_response(200);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        provider=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
        def cleanup():
            release.set();provider.shutdown();provider.server_close();thread.join(timeout=5)
        self.addCleanup(cleanup)
        return f'http://127.0.0.1:{provider.server_port}/v1/systemone',calls,blocked,release

    def start_worker(self,endpoint,budget=100):
        env={k:v for k,v in os.environ.items() if k.lower() not in {'http_proxy','https_proxy','all_proxy','jev_api_key'}}
        env.update(PYTHONUTF8='1',NO_PROXY='127.0.0.1,localhost')
        child=subprocess.Popen([sys.executable,'-c',WORKER,str(self.db),str(self.root/'scan'),endpoint,str(budget)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        def cleanup():
            if child.poll() is None:child.kill()
            child.communicate(timeout=10)
        self.addCleanup(cleanup)
        return child

    def test_http_progress_survives_process_death_and_resume_reuses_committed_pages(self):
        base=self.start_server();endpoint,calls,blocked,release=self.start_provider()
        def ingest(rollout_id,revision=0,state='complete',document=None):
            payload=dict(producer='trainer',rollout_id=rollout_id,revision=revision,state=state,
                format='harbor',document=document or long_document(),metadata={'experiment':'process-scan'})
            req=Request(base+'/api/ingest',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=15) as response:return json.load(response)
        def snapshot():
            with urlopen(base+'/api/monitoring/scans?experiment=process-scan',timeout=10) as response:
                return json.load(response)['workers'][0]
        def measurements():
            with self.store.connect() as c:
                return [json.loads(r[0]) for r in c.execute("SELECT document FROM rollout_measurements WHERE observer LIKE 'diagnostic-search-%'")]
        first=ingest('long');ingest('queued')
        child=self.start_worker(endpoint)
        self.assertTrue(blocked.wait(20),'Worker did not reach the fourth HTTP request')
        self.assertIsNone(child.poll(),'The worker must still be running for the live-progress check')
        snap=snapshot()
        self.assertEqual(snap['counts'],{'partial':1,'not_scanned':1})
        self.assertEqual(snap['rows'][0]['pages_scanned'],3)
        self.assertEqual(snap['rows'][0]['new_calls'],4)
        self.assertEqual(snap['rows'][0]['provider_responses'],3)
        self.assertEqual(snap['rows'][0]['request_state'],'in_flight')
        self.assertGreater(snap['rows'][0]['pages_total'],8)
        self.assertEqual(snap['workspace_path'],str((self.root/'scan').resolve()))
        self.assertEqual(measurements(),[],'Unscanned sources must not publish negative findings')
        self.assertTrue(worker.status(self.store,self.root/'scan')['workspace_busy'])
        committed=calls[:3];inflight=calls[3]
        child.kill();child.communicate(timeout=10);release.set()
        self.assertFalse(worker.status(self.store,self.root/'scan')['workspace_busy'])
        self.assertEqual(snapshot()['rows'][0]['pages_scanned'],3)

        # State-only producer updates and arrivals occur while scanning is stopped.
        self.assertEqual(ingest('long',revision=1)['id'],first['id'])
        ingest('arrived',state='in_progress',document=long_document(4))
        self.assertEqual(snapshot()['awaiting_inventory'],1)
        resumed=self.start_worker(endpoint)
        stdout,stderr=resumed.communicate(timeout=45)
        self.assertEqual(resumed.returncode,0,stderr)
        result=json.loads(stdout)
        self.assertEqual(result['counts'],{'complete':2,'waiting':1})
        counts=Counter(calls)
        self.assertTrue(all(counts[key]==1 for key in committed),'Committed page decisions were sent again')
        self.assertEqual(counts[inflight],2,'Only the uncommitted in-flight request should repeat')
        snap=snapshot()
        self.assertEqual(snap['counts'],{'complete':2,'waiting':1})
        for row in snap['rows']:
            if row['status']=='complete':self.assertEqual(row['pages_scanned'],row['pages_total'])
        records=measurements();self.assertEqual(len(records),2)
        self.assertTrue(all(r['diagnostic_result']['coverage']['scan_complete'] for r in records))
        self.assertTrue(all(r['diagnostic_result']['findings'] for r in records),'Tail evidence did not reach publication')
        self.assertTrue(all(r['validation']['exact_replay'] for r in worker.audit(self.store,self.root/'scan')['runs']))
        before=len(calls)
        cached=self.start_worker(endpoint,budget=0);stdout,stderr=cached.communicate(timeout=15)
        self.assertEqual(cached.returncode,0,stderr)
        self.assertEqual(json.loads(stdout)['new_calls'],0)
        self.assertEqual(len(calls),before)
        self.assertEqual(len(measurements()),2)


if __name__=='__main__':unittest.main()
