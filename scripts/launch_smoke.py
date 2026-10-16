"""Installed launch file: pretraining check, staged input, live attach and restart."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import tracker
from tracker.analytics import Analysis
from tracker.deployment_setup import plan


def stop(process):
    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    else:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def main():
    print('Package:',tracker.__file__)
    with tempfile.TemporaryDirectory(prefix='jev-launch-smoke-') as tmp:
        job=Path(tmp)/"job's space";job.mkdir();other=Path(tmp)/'elsewhere';other.mkdir()
        profile=job/'job.rilldex.json';db=job/'workspace/tracker.sqlite';outputs=job/'outputs'
        config=plan({'case':'local','stage':'before','mode':'exports','port':0})['launch_file']
        config['source']['interval']=.2
        profile.write_text(json.dumps(config),encoding='utf-8-sig')
        def cli(*args,expected=0):
            r=subprocess.run([sys.executable,'-m','rilldex','launch',str(profile),*args],cwd=other,capture_output=True,text=True,timeout=30)
            assert r.returncode==expected,(r.stdout,r.stderr)
            return r.stdout
        check=json.loads(cli('--check'));assert check['ready'] and check['waiting_for_output']
        assert not outputs.exists() and not db.exists()
        cli('--once');assert outputs.is_dir()
        path=outputs/'worker.jsonl';row=json.dumps({'input':'Q','output':'A','score':1,'step':0})
        path.write_text(row+'\n'+row,encoding='utf-8')
        cli('--once',expected=1)
        assert len(Analysis(db).table('rollouts')['rows'])==1
        log_path=job/'server.log'
        with log_path.open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-u','-m','rilldex','launch',str(profile)],cwd=other,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+20;url=None
                while time.monotonic()<deadline:
                    match=re.search(r'http://127\.0\.0\.1:\d+',log_path.read_text(encoding='utf-8'))
                    if match:url=match.group();break
                    if process.poll() is not None:raise AssertionError(log_path.read_text())
                    time.sleep(.05)
                assert url,log_path.read_text()
                def get(route):
                    with urlopen(url+route,timeout=5) as response:return json.load(response)
                with path.open('a',encoding='utf-8') as file:file.write('\n')
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    if len(get('/api/runs')['runs'])==2:break
                    time.sleep(.1)
                assert len(get('/api/runs')['runs'])==2
                assert len(get('/api/connections')['connections'])==1
                # The generated HTTP setup can be downloaded and rerun unchanged.
                assert get('/api/analysis/tables/rollouts')['rows']
            finally:stop(process)
        with path.open('a',encoding='utf-8') as file:file.write(row+'\n')
        cli('--once');cli('--once')
        assert len(Analysis(db).table('revisions',history=True)['rows'])==3
        assert not (other/'workspace').exists()
        assert path.read_text(encoding='utf-8')==(row+'\n')*3
        print('PASS: downloaded-plan shape; BOM/space/apostrophe paths; no-write check; pretraining directory; partial batch; live attach from another cwd; forced stop; catch-up; three unique receipts; unchanged source')


if __name__=='__main__':main()
