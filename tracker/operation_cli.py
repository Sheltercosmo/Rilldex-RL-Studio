"""Reusable operation observation commands; keys remain in process memory."""
import getpass
import json
import os
import time

from . import operation_workspace as workspace
from .schema import InputError


def configure(commands):
    parser=commands.add_parser('outcomes',help='Observe operation results across rollout snapshots with a shared protocol')
    sub=parser.add_subparsers(dest='outcome_command',required=True)
    for name in ('run','watch'):
        child=sub.add_parser(name);child.add_argument('directory')
        child.add_argument('--prompt-key',action='store_true')
        child.add_argument('--max-new-calls',type=int,default=300,help='Process-wide new decision-request budget; built-in transport does not retry internally. 0 reuses cache only')
        if name=='run':
            select=child.add_mutually_exclusive_group(required=True)
            select.add_argument('--run-id',action='append');select.add_argument('--all-latest',action='store_true')
        else:
            child.add_argument('--interval',type=float,default=5)
            child.add_argument('--once',action='store_true')
    for name in ('status','audit'):
        child=sub.add_parser(name);child.add_argument('directory')


def execute(args,store):
    if args.outcome_command in {'status','audit'}:
        result=getattr(workspace,args.outcome_command)(args.directory)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    from .jev import JevClient
    client=JevClient();prompted=False
    def transport(req):
        nonlocal prompted
        if args.prompt_key and not prompted:
            os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
        return client.transport(req)
    def progress(row):print(json.dumps(row),flush=True)
    if args.outcome_command=='run':
        ids=workspace.latest_ids(store) if args.all_latest else args.run_id
        result=workspace.execute(store,args.directory,ids,transport,max_new_calls=args.max_new_calls,progress=progress)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if not .2<=args.interval<=3600:raise InputError('Use a watch interval between 0.2 and 3,600 seconds')
    remaining=args.max_new_calls;seen=set();first=True
    try:
        while True:
            ids=[rid for rid in workspace.latest_ids(store) if rid not in seen]
            result=workspace.execute(store,args.directory,ids,transport,max_new_calls=remaining,progress=progress)
            remaining-=result['new_calls'];seen.update(r['run_id'] for r in result['completed'])
            if first or ids:
                print(json.dumps({**result,'remaining_new_calls':remaining},ensure_ascii=False),flush=True)
            first=False
            if args.once or result['pending_run_ids'] or remaining==0:break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(json.dumps({'status':'stopped','remaining_new_calls':remaining,'completed_run_ids':sorted(seen)}),flush=True)
