import getpass
import json
import os
from pathlib import Path

from . import diagnostic_monitors as monitors
from .semantic_extraction import read


def configure(commands):
    p=commands.add_parser('monitors',help='Experimental source-trace diagnostic metrics with exact Jev replay')
    p.add_argument('directory');p.add_argument('--run-id');p.add_argument('--input',help='Explicit diagnostic-input/1 JSON')
    p.add_argument('--prompt-key',action='store_true');p.add_argument('--audit-only',action='store_true')
    p.add_argument('--protocol',choices=('source','chains','search','requirements'),default='source',help='requirements compares task instructions with source pages; search scans long traces for behavior flags')


def execute(args,store):
    from .jev import JevClient
    from .schema import InputError
    if bool(args.run_id)==bool(args.input):raise InputError('Choose exactly one of --run-id or --input')
    run=store.get(args.run_id,raw=True)['run'] if args.run_id else None
    from .diagnostic_worker import implementation as resolve
    implementation=resolve(args.protocol)
    frozen=implementation.workspace_protocol(args.directory) if args.protocol=='search' else None
    source=(implementation.source_from_run(run, frozen['schema'] if frozen else implementation.DEFAULT_VERSION)
            if run and args.protocol=='search' else monitors.from_run(run) if run else read(args.input))
    if args.audit_only:
        result=implementation.audit(source,read(Path(args.directory)/'result.json'),args.directory)
    else:
        client=JevClient();prompted=False
        def transport(req):
            nonlocal prompted
            if args.prompt_key and not prompted:
                os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
            return client.transport(req)
        observed=implementation.execute(source,args.directory,transport)
        result=implementation.register(store,run,source,observed,args.directory) if run else getattr(implementation,'summarize',monitors.summarize)([observed])
    print(json.dumps(result,ensure_ascii=False,indent=2))
