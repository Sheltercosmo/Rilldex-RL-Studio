"""Run with an installed wheel, outside the checkout. No server or model needed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import tracker
from tracker.capture import Outbox
from tracker.deployment_setup import plan
from tracker.portable import generation_document
from tracker.store import Store


def main():
    print('Package:', tracker.__file__)
    with tempfile.TemporaryDirectory(prefix='jev-offline-') as tmp:
        root=Path(tmp); db=root/'review.sqlite'
        def cli(*args, ok=True):
            p=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),*map(str,args)],cwd=root,capture_output=True,text=True)
            assert (p.returncode==0)==ok,(p.stdout,p.stderr)
            return json.loads(p.stdout)
        def log(out,name,state='complete'):
            return out.log(name,generation_document('Authored question','Authored answer'),state=state,
                           metadata={'experiment':'offline-control','training_step':3,'training_step_basis':'authored generation'})
        workers=[Outbox(root/f'worker-{i}.sqlite',producer=f'offline-control/worker-{i}') for i in range(2)]
        for i,out in enumerate(workers):
            log(out,'sample',state='in_progress');log(out,'sample')
            source=root/f'worker-{i}.zip';receipt=root/f'worker-{i}.receipts.json'
            assert cli('capture','export',out.path,source)['packets']==2
            assert cli('capture','inspect',source)['validated']
            assert cli('capture','import',source,'--receipt',receipt)['bundles'][0]['accepted']==2
            assert cli('capture','import',source)['bundles'][0]['already_present']==2
            assert cli('capture','acknowledge',out.path,receipt)['acknowledged']==2
            assert out.status()['pending_bytes']==0
            assert log(out,'sample',state='failed')['revision']==2
            later=root/f'worker-{i}-later.zip';cli('capture','export',out.path,later)
            assert cli('capture','import',later)['bundles'][0]['accepted']==1
        with Store(db).connect() as c:
            assert c.execute('SELECT count(*) FROM rollout_revisions').fetchone()[0]==6
        print('PASS: two workers, three revisions each, export/inspect/import/replay/acknowledge/restart')
        outputs=root/"output's space";outputs.mkdir()
        options={'root':str(outputs),'database':str(root/'commands.sqlite'),'stage':'after','mode':'exports'}
        if os.name=='nt':
            env=dict(os.environ);env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH','')
            p=plan({**options,'shell':'powershell'})
            for step in p['steps'][:2]:
                r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',step['code']],cwd=root,env=env,capture_output=True,text=True)
                assert r.returncode==0,(r.stdout,r.stderr)
            print('PASS: generated PowerShell check/replay commands executed, including apostrophe/space path')
        for case in ('local','remote','docker','cloud','notebook','offline'):
            opts={'case':case}
            if case=='docker':opts['root']='/jobs/outputs'
            assert plan(opts)['steps']
        print('PASS: all six setup plans render; this is not six environment deployment validation')


if __name__=='__main__':main()
