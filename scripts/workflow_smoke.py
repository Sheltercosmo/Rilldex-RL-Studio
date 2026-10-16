"""Installed-package, code-only workflow smoke. Run outside the source checkout."""
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import time
import urllib.request
import zipfile

import tracker
from tracker.analytics import Analysis


def run():
    assert 'site-packages' in str(Path(tracker.__file__).resolve()), tracker.__file__
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','JEV_API_KEY'}}
    env['PYTHONUTF8']='1'
    with tempfile.TemporaryDirectory(prefix='rilldex-workflow-installed-') as tmp:
        root=Path(tmp); source=root/'outputs'; source.mkdir()
        record=json.dumps({'input':'Question','output':'Answer','step':1,'score':1})
        file=source/'rollouts.jsonl'; file.write_text(record+'\n',encoding='utf-8')
        def cli(*args, code=0):
            result=subprocess.run([sys.executable,'-m','rilldex',*map(str,args)],cwd=root,env=env,capture_output=True,text=True,timeout=45)
            assert result.returncode==code,(result.returncode,result.stderr,result.stdout)
            return json.loads(result.stdout)
        project=root/'project'
        cli('workflow','init',project,'--source',source,'--mode','exports','--experiment','smoke','--producer','smoke/source')
        cli('workflow','run',project,'--check')
        first=cli('workflow','run',project)
        with file.open('a',encoding='utf-8') as f:f.write(record)
        partial=cli('workflow','run',project,code=2)
        assert partial['pending'] and partial['generation']==first['generation']
        with file.open('a',encoding='utf-8') as f:f.write('\n')
        second=cli('workflow','run',project)
        assert second['generation']!=first['generation'] and not second['pending']
        status=cli('workflow','status',project)
        assert status['publication']['generation']==second['generation'] and status['config_matches']
        data=project/'results'/second['generation']/'data.sqlite'
        assert Analysis(data).query('SELECT COUNT(*) n FROM rl_rollouts')['rows']==[{'n':2}]
        archive=root/'workflow.zip'
        cli('workflow','package',project,archive)
        extracted=root/'unpacked'
        with zipfile.ZipFile(archive) as z:
            z.extractall(extracted)
            assert 'runtime/tracker/web/connections.html' in z.namelist()
            assert 'requirements.txt' in z.namelist()
        checked=subprocess.run([sys.executable,'-I',str(extracted/'run.py'),'--check'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert checked.returncode==0,checked.stderr
        assert json.loads(checked.stdout)['database']==str(extracted/'workspace/tracker.sqlite')
        def available_port():
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
        configured=available_port()
        config=json.loads((extracted/'rilldex.json').read_text())
        config['ui_port']=configured
        (extracted/'rilldex.json').write_text(json.dumps(config),encoding='utf-8')
        # Run the actual portable launcher from another working directory. Verify
        # both the saved SSH port and an explicit per-launch override.
        for port,flags in [(configured,[]),(available_port(),['--port'])]:
            command=[sys.executable,'-I',str(extracted/'run.py'),'ui',*flags]
            if flags:command.append(str(port))
            process=subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise AssertionError(process.stderr.read().decode())
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/connections',timeout=1) as response:
                            assert b'analysis-workflow' in response.read()
                            break
                    except OSError:time.sleep(.1)
                else:raise AssertionError('Portable UI did not start on selected port')
            finally:
                process.terminate();process.communicate(timeout=10)
        return dict(installed=True,partial_tail=True,resume_without_duplicates=True,portable_runner=True,
                    durable_status=True,portable_ui_port=True,ui_port_override=True,
                    package_bytes=archive.stat().st_size,model_calls=0)


if __name__=='__main__':print(json.dumps(run(),indent=2))
