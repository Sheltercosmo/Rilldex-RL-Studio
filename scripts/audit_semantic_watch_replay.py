"""Real retained traces through the worker and loopback Jev HTTP transport.

Responses are historical model outputs, matched by full request digest. This
is deliberately not fresh inference, independent accuracy, or a live RL run.
"""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from unittest.mock import patch

if not sys.flags.isolated:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker import jev, semantic_watch as watch, semantic_workspace, semantic_catalog, monitoring
from tracker.schema import digest, dumps
from tracker.semantic_extraction import read, write, load_extraction
from tracker.store import Store


def run(root, output, *, candidate_responses=None):
    package_path=Path(jev.__file__).resolve()
    if sys.flags.isolated and 'site-packages' not in package_path.parts:
        raise ValueError('Isolated audit must use an ordinarily installed Rilldex package')
    output.mkdir(parents=True, exist_ok=True)
    database=output/'workspace.sqlite'
    if database.exists():raise ValueError('Use a fresh output directory')
    retained=root/'work-phases-routed'; sample=read(root/'sample.json'); batch=read(retained/'batch.json')
    sources=[]; expected={}; responses={}
    for row in sample['runs']:
        source=read(root/'sources'/f'{row["id"]}.json')
        if digest(source)!=row['source_hash']:raise ValueError('Retained source changed')
        expected[source['id']]=load_extraction(source,retained)['raw_extraction']
        sources.append(source)
    for path in (retained/'decisions').glob('*.json'):
        saved=read(path)
        if path.stem!=digest(saved['request']):raise ValueError('Saved request digest changed')
        responses[path.stem]=saved
    requests=[]; mismatch=[]; injected=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            key=digest(request); requests.append(key)
            if not injected:
                injected.append('HTTP 429 before the first recorded response')
                self.send_response(429);self.end_headers();return
            saved=responses.get(key)
            if saved is None or saved['request']!=request:
                mismatch.append(key);self.send_response(422);self.end_headers();return
            payload=dumps(saved['response']).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    store=Store(database); directory=output/'observer'
    options={k:batch[k] for k in ('context_policy','activity_routing','include_user','partition_standard')}
    watch.initialize(store,directory,experiment=sources[0]['metadata']['experiment'],label='Retained real outputs · HTTP replay',
                     workspace_options=options,allowance={'jev_requests':200,'candidate_requests':0,'input_bytes':20_000_000})
    # File proposals exercise the candidate handoff without regenerating them.
    # Request hashes, citations and complete results are checked by the pipeline.
    for source in sources:
        job=directory/'runs'/source['id']
        semantic_workspace.initialize(job,source,**options)
        shutil.copytree(candidate_responses or retained/'candidates/responses',job/'candidates/responses')
    snapshots=[]
    try:
        # No real key or endpoint can be used in this audit.
        with patch.object(jev,'ENDPOINT',f'http://127.0.0.1:{server.server_address[1]}/v1/systemone'),patch.dict(os.environ,{'JEV_API_KEY':'loopback-replay-only'}):
            client=jev.JevClient()
            for offset in (0,8):
                store.add(sources[offset:offset+8])
                for _ in range(2):
                    current=watch.run_once(store,directory,client.transport,max_rollouts=4)
                    if current['paused_for_review'] and len(requests)==1:
                        # A retry is a new reserved invocation, never hidden in
                        # one budget entry. Poll/restart alone cannot resend it.
                        assert current['used']['jev_requests']==1
                        failed=next(j['run_id'] for j in current['jobs'] if j['status']=='failed')
                        store=Store(database)
                        paused=watch.run_once(store,directory,client.transport,max_rollouts=4)
                        assert len(requests)==1 and paused['used']==current['used']
                        current=watch.run_once(store,directory,client.transport,max_rollouts=4,retry_runs=[failed])
                    snapshots.append({k:current[k] for k in ('current_sources','current_published','job_counts','used')})
                    if current['paused_for_review']:raise AssertionError(dumps(current))
                # Reopen the same database: stable identity, budget and job state.
                store=Store(database)
            before=len(requests)
            final=watch.run_once(store,directory,lambda _: (_ for _ in ()).throw(AssertionError('Repeated provider call')))
            assert len(requests)==before and final['current_published']==16
            assert final['used']['jev_requests']==len(requests)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    activities=Counter()
    for source in sources:
        actual=semantic_catalog.load(source,final['observer'],store)['raw_extraction']
        # Compare substantive units, not bookkeeping generated by a different
        # runner. Includes activities, source spans, contents, and request keys.
        assert actual['units']==expected[source['id']]['units'],source['id']
        activities.update(u['activity'] for u in actual['units'])
    monitor=monitoring.create(store,dict(name='Expressed verification share',kind='metric',metric='activity_verify_share',observer=final['observer']))
    relationship=monitoring.create(store,dict(name='Feedback links remain unmeasured',kind='graph',observer=final['observer'],
        requirement=monitoring.graph_queries.PRESETS['assessment_of_inspection_feedback']))
    monitoring.sync(store)
    monitors=monitoring.snapshot(store)['monitors']
    measured=next(m for m in monitors if m['id']==monitor['id'])
    unavailable=next(m for m in monitors if m['id']==relationship['id'])
    assert measured['coverage']['available']==16 and unavailable['coverage']['available']==0
    report={'schema':'semantic-watch-real-replay/1','status':'passed','sources':len(sources),
            'selected_units':sum(activities.values()),'activities':dict(activities),'observer':final['observer'],
            'http_requests':len(requests),'unique_requests':len(set(requests)),'unmatched_requests':mismatch,
            'faults':injected,'snapshots':snapshots,'worker':final,
            'runtime':{'isolated':bool(sys.flags.isolated),'package_path':str(package_path),
                       'jev_transport_policy':jev.TRANSPORT_POLICY},
            'monitor_points':measured['coverage']['available'],'relationship_points':unavailable['coverage']['available'],
            'validation_scope':{'source':'Retained real training outputs; one exposed development task, 16 rollouts at steps 50 and 140',
                'transport':'Actual Jev HTTP client to a loopback replay endpoint, with HTTP 429 injected',
                'candidate_generation':'Historical model proposals supplied through file handoff; no fresh candidate model',
                'selection':'Exact historical real model responses; strict request matching and normal argmax/audit path',
                'new_external_model_calls':0,'independent_semantic_accuracy':'Not measured',
                'training':'No optimizer, inference server, or environment executed',
                'covered':'Batch arrivals, database reopening, one reserved attempt per HTTP POST including explicit retry, persistent budget, stable observer, immutable graphs and metrics, no duplicate extraction'}}
    write(output/'report.json',report)
    return {k:report[k] for k in ('status','sources','selected_units','http_requests','unique_requests','monitor_points','validation_scope')}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('research/training-semantic-pilot-2026-10-08'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.source,args.output),indent=2))
