"""Installed-package, live database + HTTP parity check; no export or model calls."""
import json
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import rilldex
from rilldex import Workspace
from tracker.portable import generation_document
from tracker.store import Store


def run(with_dataframes=False):
    assert 'site-packages' in str(Path(rilldex.__file__).resolve())
    with tempfile.TemporaryDirectory(prefix='rilldex-live-analysis-') as tmp:
        root=Path(tmp);database=root/'study.sqlite';store=Store(database)
        def ingest(name):
            return store.ingest(dict(producer='worker',rollout_id=name,revision=0,state='complete',format='generation',
                metadata={'experiment':'smoke'},document=generation_document('Q',name,reward=0)))['id']
        ingest('first');ws=Workspace(database,experiment='smoke',observer='source')
        assert len(ws.rollouts().rows)==1
        ingest('second');assert len(ws.rollouts().rows)==2
        if with_dataframes:
            assert len(ws.rollouts().to_pandas())==2
            assert ws.rollouts().to_polars().height==2
        graph=ws.graph(ws.graphs().rows[0]['graph_id'])
        # A consumer may attach another typed relation without collapsing the original.
        original=graph.edges[0]
        graph.edges.append({**original,'id':'consumer-evidence','type':'consumer_review','properties':{'review':'kept'}})
        if with_dataframes:
            network=graph.to_networkx()
            assert network.is_multigraph() and network.is_directed()
            assert network.number_of_edges()==len(graph.edges)
            assert network[original['source']][original['target']]['consumer-evidence']['properties']['review']=='kept'
        calls=[]
        def measure(row,config):
            calls.append(row['run_id']);return {'experiment':row['metadata']['experiment'],'verified':row['verified_success']}
        batch=ws.evaluate('smoke_measure',measure,version='1')
        assert ws.evaluate('smoke_measure',measure,version='1')['id']==batch['id'] and len(calls)==2
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','JEV_API_KEY')}
        proc=subprocess.Popen([sys.executable,'-I','-m','rilldex','--db',str(database),'serve','--port',str(port)],
            cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def get(path):
            with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=5) as response:return json.load(response)
        try:
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if proc.poll() is not None:raise AssertionError(proc.stderr.read().decode())
                try:get('/api/health');break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Server did not become ready')
            http=get('/api/analysis/compute?function=metric_availability&experiment=smoke&observer=source')
            assert http['rows']==ws.metric_availability().rows
            assert len(get('/api/analysis/functions')['functions'])==4
            assert get('/api/analysis/custom')['rows'][0]['id']==batch['id']
            assert len(get('/api/analysis/custom/'+batch['id'])['rows'])==2
            ingest('third')
            assert get('/api/analysis/compute?function=recorded_outcomes&experiment=smoke')['rows'][0]['snapshots']==3
            try:get('/api/analysis/compute?function=execute_python')
            except urllib.error.HTTPError as e:assert e.code==400
            else:raise AssertionError('Unknown function was accepted')
        finally:proc.terminate();proc.communicate(timeout=10)
        assert not list(root.glob('*.zip')) and not (root/'results').exists()
        return dict(live_reads=True,python_http_parity=True,managed_python_results=True,cache_reuse=True,
                    pandas='passed' if with_dataframes else 'not_requested',
                    polars='passed' if with_dataframes else 'not_requested',
                    networkx='passed' if with_dataframes else 'not_requested',export_required=False,model_calls=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-dataframes',action='store_true',help='Require and test pandas, Polars and NetworkX integrations')
    print(json.dumps(run(parser.parse_args().with_dataframes),indent=2))
