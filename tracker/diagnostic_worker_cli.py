"""Explicit stream-monitor process; no keys are persisted in workspaces."""
import getpass
import json
import os
import time

from . import diagnostic_worker as worker
from .schema import InputError,digest


def configure(commands):
    parser=commands.add_parser('monitor-rollouts',help='Run/resume diagnostic monitoring across completed rollout imports')
    sub=parser.add_subparsers(dest='monitor_command',required=True)
    for name in ('run','watch','plan'):
        p=sub.add_parser(name);p.add_argument('directory')
        p.add_argument('--protocol',choices=('source','chains','search','requirements'),default='chains',help='requirements finds task-conflict candidates; search scans long traces for behavior flags')
        if name!='plan':
            p.add_argument('--prompt-key',action='store_true');p.add_argument('--max-new-calls',type=int,default=100)
            p.add_argument('--retry-failed',action='store_true',help='Explicitly retry failed sources once in this process')
        p.add_argument('--experiment');p.add_argument('--adapter',action='append')
        if name in {'run','plan'}:
            choose=p.add_mutually_exclusive_group(required=True)
            choose.add_argument('--run-id',action='append');choose.add_argument('--all-latest',action='store_true')
        else:
            p.add_argument('--interval',type=float,default=5);p.add_argument('--once',action='store_true')
    for name in ('status','audit'):
        p=sub.add_parser(name);p.add_argument('directory')


def execute(args,store):
    if args.monitor_command in {'status','audit'}:
        print(json.dumps(getattr(worker,args.monitor_command)(store,args.directory),ensure_ascii=False,indent=2));return
    if args.monitor_command=='plan':
        print(json.dumps(worker.plan(store,worker.selection(args.run_id,args.experiment,args.adapter),args.protocol),ensure_ascii=False,indent=2));return
    from .jev import JevClient
    client=JevClient();prompted=False;used=0
    def transport(req):
        nonlocal prompted,used
        used+=1
        if args.prompt_key and not prompted:
            os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
        return client.transport(req)
    selector=worker.selection(getattr(args,'run_id',None),args.experiment,args.adapter)
    if args.monitor_command=='watch' and not .2<=args.interval<=60:raise InputError('Use a poll interval between 0.2 and 60 seconds')
    remaining=args.max_new_calls;prior=None;retry=args.retry_failed
    def progress(row):print(json.dumps(row),flush=True)
    try:
        while True:
            result=worker.execute(store,args.directory,transport,selector=selector,protocol_name=args.protocol,
                max_new_calls=remaining,retry_failed=retry,progress=progress)
            retry=False;remaining=args.max_new_calls-used
            summary={k:v for k,v in result.items() if k not in {'completed','coverage','protocol'}}
            summary['coverage']={k:v for k,v in result['coverage'].items() if k!='rows'}
            summary.update(observer=result['protocol']['id'],remaining_new_calls=remaining)
            fingerprint=digest(summary)
            if fingerprint!=prior:print(json.dumps(summary,ensure_ascii=False),flush=True)
            prior=fingerprint
            if args.monitor_command=='run' or args.once or remaining==0 or result['pending_run_ids']:break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(json.dumps({'status':'stopped','remaining_new_calls':max(0,args.max_new_calls-used)}),flush=True)
