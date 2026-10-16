"""Installed code-first workflow, forced interruption and independent SQLite use."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

import tracker
from tracker.research import Analysis, Analyzer, Research, Results
from tracker.portable import generation_document
from tracker.store import Store


SQL = 'SELECT run_id,metadata_json FROM rl_rollouts WHERE is_latest=1 ORDER BY run_id'


def main():
    print('Package:',tracker.__file__)
    with tempfile.TemporaryDirectory(prefix='jev-research-') as tmp:
        root=Path(tmp);db=root/'workspace.sqlite';results=root/'custom results.sqlite';store=Store(db)
        def add(key,revision=0):
            return store.ingest(dict(producer='smoke',rollout_id=key,revision=revision,state='complete',
                format='generation',metadata=dict(experiment='smoke',generation_step=revision),
                document=generation_document('Q',key+str(revision))))['id']
        first=add('one');add('two')
        data=Analysis(db);graph=data.query('SELECT graph_id FROM rl_graphs WHERE run_id=?',[first])['rows'][0]['graph_id']
        def cli(*args):
            p=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),'analysis',*args],cwd=root,capture_output=True,text=True,timeout=30)
            assert p.returncode==0,p.stderr
            return json.loads(p.stdout)
        assert cli('operations')['operations']
        assert cli('run','retry_outcomes','--run-id',first,'--graph-id',graph,'--check')['new_model_calls']==0
        projection=cli('run','retry_outcomes','--run-id',first,'--graph-id',graph)
        assert cli('saved',projection['id'])['outputs']==projection['outputs']
        assert Analyzer(db).run('retry_outcomes',first,graph_id=graph)['execution']['computed']==0
        marker=root/'waiting';child_code='''
import json,sys,time
from pathlib import Path
from tracker.research import Research
lab=Research(sys.argv[1],sys.argv[2]);counter=0
def analyze(row,config):
    global counter
    counter+=1
    if counter==2:
        Path(sys.argv[3]).write_text('ready')
        time.sleep(60)
    return {'value':1,'evidence':row['run_id']}
lab.evaluate('smoke','1',sys.argv[4],analyze,key_columns=['run_id'])
'''
        process=subprocess.Popen([sys.executable,'-c',child_code,str(db),str(results),str(marker),SQL],cwd=root,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+15
            while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            assert marker.exists(),process.communicate(timeout=1)
        finally:
            process.kill();process.communicate(timeout=5)
        retained=Results(results);original=retained.batches()['rows'][0]
        assert original['status']=='running'  # abrupt kill leaves the recorded state
        original_rows=retained.results(original['id'])['rows']
        add('one',revision=1)  # current selection changes before recovery
        offline=root/'offline-workspace.sqlite';db.rename(offline)
        assert cli('results',str(results),'batches')['rows'][0]['id']==original['id']
        assert cli('results',str(results),'batch',original['id'])['counts']['pending']==1
        page=cli('results',str(results),'rows',original['id'],'--limit','1')
        assert page['next_after']==0 and page['truncated']
        assert len(cli('results',str(results),'rows',original['id'],'--after','0')['rows'])==1
        assert cli('results',str(results),'sql','--query','SELECT count(*) n FROM research_results')['rows']==[{'n':1}]
        recovered=retained.resume(original['id'],lambda r,c:dict(value=1,evidence=r['run_id']),version='1')
        assert (recovered['computed'],recovered['reused'])==(1,1),recovered
        assert recovered['id']==original['id']
        assert [r['input_json'] for r in retained.results(original['id'])['rows']]==[r['input_json'] for r in original_rows]
        exported=cli('results',str(results),'export',original['id'],str(root/'findings.zip'))
        assert exported['files']['results.jsonl']['rows']==2
        with zipfile.ZipFile(root/'findings.zip') as archive:
            assert len(archive.read('results.jsonl').splitlines())==2
        assert not db.exists()  # result-only commands must not initialize a workspace
        offline.rename(db);lab=Research(data,results)
        revised=lab.evaluate('smoke','1',SQL,lambda r,c:dict(value=1,evidence=r['run_id']),key_columns=['run_id'])
        assert (revised['selected'],revised['computed'],revised['reused'])==(2,1,1),revised
        unchanged=lab.evaluate('smoke','1',SQL,lambda r,c:dict(value=1,evidence=r['run_id']),key_columns=['run_id'],skip_unchanged=True)
        assert unchanged['id']==revised['id'] and unchanged['unchanged'] and unchanged['computed']==0
        assert len(lab.batches()['rows'])==2
        assert len(lab.results(recovered['id'])['rows'])==2
        example=Path(tracker.__file__).parent/'web'/'research-example.py'
        example_results=root/'example-results.sqlite'
        p=subprocess.run([sys.executable,str(example),'run',str(db),str(example_results),'no-recorded-monitor'],cwd=root,capture_output=True,text=True,timeout=20)
        assert p.returncode==0,p.stderr
        empty=json.loads(p.stdout);assert empty['selected']==0
        db.rename(offline)
        p=subprocess.run([sys.executable,str(example),'resume',str(example_results),empty['id']],cwd=root,capture_output=True,text=True,timeout=20)
        assert p.returncode==0,p.stderr
        assert json.loads(p.stdout)['unchanged'];assert not db.exists()
        offline.rename(db)
        dataset=root/'share.sqlite';export=cli('database',str(dataset),'--experiment','smoke','--history','--include-sources')
        assert export['tables']['rollouts']['rows']==3
        independent='''
import sqlite3,sys,json
c=sqlite3.connect(sys.argv[1])
assert c.execute('SELECT count(*) FROM rl_rollouts').fetchone()[0]==3
assert c.execute('SELECT count(*) FROM rl_sources').fetchone()[0]==3
assert c.execute('SELECT count(*) FROM rl_edges e LEFT JOIN rl_nodes n ON n.graph_id=e.graph_id AND n.node_id=e.source WHERE n.node_id IS NULL').fetchone()[0]==0
assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
c.close();print('Independent SQLite: PASS')
'''
        p=subprocess.run([sys.executable,'-I','-c',independent,str(dataset)],cwd=root,capture_output=True,text=True,timeout=20)
        assert p.returncode==0,p.stderr;print(p.stdout.strip())
        frozen=Analysis(dataset)
        assert frozen.catalog()['frozen']
        assert len(frozen.table('rollouts')['rows'])==2
        print(json.dumps(dict(builtin_cached=True,recovered=recovered,revised=revised,
                             snapshot_rows=export['tables']['rollouts']['rows']),indent=2))
    print('PASS: built-in CLI/SDK, exact offline crash recovery, result paging/export, unchanged polls, bundled example, revisions, independent database')


if __name__=='__main__':main()
