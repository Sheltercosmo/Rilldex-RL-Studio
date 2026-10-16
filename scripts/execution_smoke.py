"""Parallel HTTP reporting with unequal authored workloads; no inference servers.

Measures collector mechanics only. Backend/environment names are fixture labels.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

import tracker
from tracker.analytics import Analysis
from tracker.capture import Outbox
from tracker.schema import dumps
from analysis_smoke import stop


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--attempts',type=int,default=80)
    args=parser.parse_args()
    if not 1<=args.workers<=64 or not 1<=args.attempts<=1000:parser.error('Use 1–64 workers and 1–1000 attempts each')
    print('Package:',tracker.__file__)
    with tempfile.TemporaryDirectory(prefix='jev-execution-') as tmp:
        root=Path(tmp);db=root/'workspace.sqlite';log_path=root/'server.log'
        with log_path.open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-u','-m','rilldex','--db',str(db),'start','--port','0'],cwd=root,stdout=log,stderr=log,env={**os.environ,'PYTHONUTF8':'1'})
            try:
                deadline=time.monotonic()+20;url=None
                while time.monotonic()<deadline:
                    match=re.search(r'http://127\.0\.0\.1:\d+',log_path.read_text(encoding='utf-8'))
                    if match:url=match.group();break
                    if process.poll() is not None:raise AssertionError(log_path.read_text())
                    time.sleep(.05)
                assert url,log_path.read_text()
                def report(index):
                    producer=f'job/worker-{index}';rows=[]
                    for n in range(args.attempts):
                        context=dict(environment='terminal' if n%2 else 'browser',environment_version='fixture-v1',
                            backend=('vllm','sglang','external-api')[index%3],server=f'instance-{index}',
                            model='policy-a' if index%2 else 'policy-b',model_role='actor',worker=producer)
                        common=dict(id=f'call-{n}',kind='inference',rollout=dict(producer=producer,id=f'episode-{n}'),
                            context=context,evidence='Authored concurrency smoke, not native engine capture')
                        if n%5:
                            rows.append(dict(common,revision=2,state='completed',metrics=dict(duration_ms=10 if n%2 else 1000,queue_ms=index)))
                        else:
                            rows.append(dict(common,revision=1,state='suspended',metrics=dict(elapsed_ms=2000)))
                    packet=dict(schema='execution-records/1',producer=producer,experiment='mixed-async',records=rows)
                    def post(packet):
                        with urlopen(Request(url+'/api/execution-records',data=dumps(packet).encode(),headers={'Content-Type':'application/json'}),timeout=30) as response:
                            return json.load(response)
                    first=post(packet);assert first['inserted']==args.attempts
                    assert post(packet)['inserted']==0
                    # Reports created before the terminal state arrive afterward.
                    earlier=[dict(r,revision=0,state='queued',metrics={}) for r in rows]
                    assert post(dict(packet,records=earlier))['inserted']==args.attempts
                    return first['inserted']
                started=time.monotonic()
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    assert sum(pool.map(report,range(args.workers)))==args.workers*args.attempts
                elapsed=time.monotonic()-started
                data=Analysis(db)
                summary=data.execution_summary(experiment='mixed-async',kind='inference',group_by=['environment','backend','model'])
                expected=args.workers*args.attempts
                assert summary['observed_attempts']==expected
                unfinished=args.workers*((args.attempts+4)//5)
                assert sum(g['unfinished'] for g in summary['groups'])==unfinished
                with urlopen(url+'/api/analysis/tables/executions?experiment=mixed-async&limit=1') as response:
                    preview=json.load(response)
                assert preview['available'] and preview['truncated']
                # SDK queue survives sender replacement and uses the same endpoint.
                box=Outbox(root/'worker-outbox.sqlite',producer='durable',endpoint=url)
                event=dict(id='long-rollout',revision=0,kind='rollout',rollout=dict(producer='durable',id='long-rollout'),
                    state='running',context=dict(environment='terminal'),evidence='Authored local SDK capture')
                box.log_execution('sdk',[event]);assert box.status()['pending']==1
                restored=Outbox(box.path,producer='durable',endpoint=url)
                assert restored.drain()['sent_now']==1
                assert data.execution_summary(experiment='sdk')['groups'][0]['unfinished']==1
                cli=subprocess.run([sys.executable,'-m','rilldex','--db',str(db),'analysis','execution-summary',
                    '--experiment','mixed-async','--kind','inference','--group-by','backend'],cwd=root,capture_output=True,text=True,timeout=30)
                assert cli.returncode==0,cli.stderr
                assert json.loads(cli.stdout)['observed_attempts']==expected
                cursor=None;receipts=0
                while True:
                    page=data.changes('executions',cursor=cursor,limit=10000)
                    receipts+=len(page['rows']);cursor=page['next_cursor']
                    if not page['has_more']:break
                assert receipts==expected*2+1
                print(json.dumps(dict(workers=args.workers,observed_attempts=expected,unique_revisions=expected*2,
                    duplicate_reports=expected,unfinished=unfinished,groups=len(summary['groups']),
                    delivery_seconds=round(elapsed,3),fixture_backend_names=['vllm','sglang','external-api'],
                    validation='Concurrent local HTTP clients and SQLite collector only; no GPU/backend/cluster claim'),indent=2))
            finally:stop(process)
    print('PASS: parallel HTTP, out-of-order revisions, duplicate delivery, incomplete population, SDK restart, SQL/CLI/HTTP parity')


if __name__=='__main__':main()
