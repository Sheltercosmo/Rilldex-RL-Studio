"""Installed-package HTTP/CLI research I/O smoke test; authored data, no models."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import zipfile
import tracker
from tracker.analytics import Analysis
from tracker.analysis_mirror import FeedMirror
from tracker.portable import generation_document


def stop(process):
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    else:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def main():
    print('Package:',tracker.__file__)
    with tempfile.TemporaryDirectory(prefix='jev-analysis-smoke-') as tmp:
        root=Path(tmp);db=root/'workspace.sqlite';log_path=root/'server.log'
        with log_path.open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-u','-m','rilldex','--db',str(db),'start','--port','0'],cwd=root,stdout=log,stderr=log,env={**os.environ,'PYTHONUTF8':'1'})
            try:
                deadline=time.monotonic()+20;url=None
                while time.monotonic()<deadline:
                    content=log_path.read_text(encoding='utf-8')
                    match=re.search(r'http://127\.0\.0\.1:\d+',content)
                    if match:url=match.group();break
                    if process.poll() is not None:raise AssertionError(content)
                    time.sleep(.05)
                assert url,log_path.read_text()
                def get(path,body=None,raw=False):
                    request=Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
                    with urlopen(request,timeout=20) as response:data=response.read()
                    return data if raw else json.loads(data)
                p={'producer':'smoke','rollout_id':'one','revision':0,'state':'in_progress','format':'generation',
                   'metadata':{'experiment':'smoke'},'document':generation_document('Q','A',reward=0)}
                get('/api/ingest',p);first=get('/api/analysis/changes?feed=revisions')
                get('/api/ingest',{**p,'revision':1,'state':'complete'})
                page=get('/api/analysis/changes?'+urlencode({'feed':'revisions','cursor':json.dumps(first['next_cursor'])}))
                assert len(page['rows'])==1 and page['rows'][0]['document']['state']=='complete'
                assert len(get('/api/analysis/tables/rollouts')['rows'])==1
                assert len(get('/api/analysis/tables/revisions?history=1')['rows'])==2
                catalog=get('/api/analysis/catalog')
                assert {t['name'] for t in catalog['tables']}=={'rollouts','revisions','sources','graphs','nodes','edges',
                    'measurements','monitor_values','monitor_definitions','training_records','executions'}
                options=get('/api/analysis/options?experiment=smoke')
                assert any(e['experiment']=='smoke' for e in options['experiments']),options
                with zipfile.ZipFile(io.BytesIO(get('/api/analysis/export?experiment=smoke',raw=True))) as z:
                    manifest=json.loads(z.read('manifest.json'));assert manifest['tables']['rollouts']['rows']==1
                    assert manifest['scope']=={'experiment':'smoke','history':False}
                with zipfile.ZipFile(io.BytesIO(get('/api/analysis/export?experiment=smoke&profile=measurements&observer=source',raw=True))) as z:
                    manifest=json.loads(z.read('manifest.json'))
                    assert set(manifest['tables'])=={'rollouts','revisions','measurements','monitor_values','monitor_definitions'}
                    assert manifest['scope']=={'experiment':'smoke','history':False,'observer':'source'}
                    assert 'rollouts' in manifest['context_tables']
                assert b'data-access.js' in get('/connections',raw=True)
                assert b'analysis-data-form' in get('/data-access.js',raw=True)
                assert b'Code-first research' in get('/research-guide.md',raw=True)
                assert b'lab.evaluate' in get('/research-example.py',raw=True)
                cli=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),'analysis','table','rollouts'],cwd=root,capture_output=True,text=True)
                assert cli.returncode==0,cli.stderr
                assert json.loads(cli.stdout)['rows']==Analysis(db).table('rollouts')['rows']
                mirror=FeedMirror(Analysis(db),root/'results.sqlite')
                assert mirror.sync(feeds=['revisions'])['feeds'][0]['inserted']==2
                follow_log=root/'follow.log'
                with follow_log.open('w',encoding='utf-8') as output:
                    follow=subprocess.Popen([sys.executable,'-u','-m','rilldex','--db',str(db),'analysis','sync',str(mirror.path),
                        '--feed','revisions','--follow','--interval','0.2'],cwd=root,stdout=output,stderr=output)
                    try:
                        get('/api/ingest',{**p,'revision':2,'document':generation_document('Q','Revised answer',reward=1)})
                        deadline=time.monotonic()+10
                        while time.monotonic()<deadline:
                            if mirror.status()['feeds'][0]['receipts']==3:break
                            if follow.poll() is not None:raise AssertionError(follow_log.read_text())
                            time.sleep(.05)
                        assert mirror.status()['feeds'][0]['receipts']==3,follow_log.read_text()
                    finally:stop(follow)
                # Work arriving while the downstream consumer is stopped is retained.
                get('/api/ingest',{**p,'revision':3,'state':'complete','document':generation_document('Q','Revised answer',reward=1)})
                resumed=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),'analysis','sync',str(mirror.path),
                    '--feed','revisions'],cwd=root,capture_output=True,text=True)
                assert resumed.returncode==0,resumed.stderr
                assert json.loads(resumed.stdout)['feeds'][0]['inserted']==1
                assert mirror.status()['feeds'][0]['receipts']==4
                assert mirror.sync(feeds=['revisions'])['feeds'][0]['inserted']==0
                print('PASS: HTTP input; lifecycle receipts; scoped options and ZIP; CLI/Python parity; packaged UI; live mirror; forced stop; catch-up without duplicates')
            finally:
                stop(process)


if __name__=='__main__':main()
