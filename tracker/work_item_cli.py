import getpass
import json
import os
from pathlib import Path

from . import work_item_pass as workspace
from .semantic_extraction import read
from .schema import InputError


def configure(commands):
    parser=commands.add_parser('work-items',help='Extract readable declared work inside a complete semantic map')
    sub=parser.add_subparsers(dest='work_item_command',required=True)
    p=sub.add_parser('prepare');p.add_argument('directory');p.add_argument('--run-id',required=True);p.add_argument('--observer',required=True)
    p=sub.add_parser('run');p.add_argument('directory');p.add_argument('--prompt-key',action='store_true')
    p=sub.add_parser('history');p.add_argument('directory');p.add_argument('--prompt-key',action='store_true')
    p=sub.add_parser('actions');p.add_argument('directory');p.add_argument('--prompt-key',action='store_true')
    p=sub.add_parser('results');p.add_argument('directory');p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--protocol',choices=['legacy','operation'],default='legacy');p.add_argument('--result-directory')
    p=sub.add_parser('scope-parts');p.add_argument('directory');p.add_argument('--parts-directory',required=True);p.add_argument('--prompt-key',action='store_true')
    p=sub.add_parser('adjustments');p.add_argument('directory');p.add_argument('--adjustment-directory',required=True);p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--max-calls',type=int,default=50);p.add_argument('--audit-only',action='store_true')
    p.add_argument('--protocol',choices=['legacy','facet','effect'],default='legacy')
    p=sub.add_parser('register-adjustments');p.add_argument('directory');p.add_argument('--adjustment-directory',required=True);p.add_argument('--label',required=True);p.add_argument('--reference-directory')
    p=sub.add_parser('adjustment-references');p.add_argument('directory');p.add_argument('--adjustment-directory',required=True);p.add_argument('--reference-directory',required=True)
    p.add_argument('--prompt-key',action='store_true');p.add_argument('--max-calls',type=int,default=20);p.add_argument('--audit-only',action='store_true')
    p=sub.add_parser('audit');p.add_argument('directory')
    p=sub.add_parser('register');p.add_argument('directory');p.add_argument('--label',required=True)
    p.add_argument('--result-directory');p.add_argument('--parts-directory')


def execute(args,store):
    if args.work_item_command=='prepare':result=workspace.prepare(store,args.directory,args.run_id,args.observer)
    elif args.work_item_command=='register-adjustments':
        from .adjustment_graph import register
        result=register(store,args.directory,args.adjustment_directory,args.label,reference_directory=args.reference_directory)
    elif args.work_item_command in {'run','history','actions','results','scope-parts','adjustments','adjustment-references'}:
        from .jev import JevClient
        client=JevClient();prompted=False
        def transport(req):
            nonlocal prompted
            if args.prompt_key and not prompted:
                os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
            return client.transport(req)
        operation={'run':workspace.execute,'history':workspace.history,'actions':workspace.actions,'results':workspace.results,'scope-parts':workspace.scope_parts,'adjustments':workspace.adjustments,'adjustment-references':workspace.adjustment_references}[args.work_item_command]
        kwargs={'protocol':args.protocol,'result_directory':args.result_directory} if args.work_item_command=='results' else {'parts_directory':args.parts_directory} if args.work_item_command=='scope-parts' else {}
        if args.work_item_command=='adjustments':kwargs={'adjustment_directory':args.adjustment_directory,'max_calls':args.max_calls,'audit_only':args.audit_only,'protocol':args.protocol}
        if args.work_item_command=='adjustment-references':kwargs={'adjustment_directory':args.adjustment_directory,'reference_directory':args.reference_directory,'max_calls':args.max_calls,'audit_only':args.audit_only}
        result=operation(args.directory,transport,lambda row:print(json.dumps(row),flush=True),**kwargs)
    elif args.work_item_command=='register':result=workspace.register(store,args.directory,args.label,result_directory=args.result_directory,parts_directory=args.parts_directory)
    else:
        with workspace.exclusive(args.directory):
            config,run,doc=workspace.load(args.directory)
            path=Path(args.directory)/'latest.json'
            if not path.exists():raise InputError('Run the prepared pass before auditing its selections')
            result=workspace.audit(run,doc,read(path),args.directory)
            if (Path(args.directory)/'history.json').exists():
                from . import declared_work_history
                result['history']=declared_work_history.audit(run,doc,read(Path(args.directory)/'complete.json'),read(Path(args.directory)/'history.json'),args.directory)
                if (Path(args.directory)/'action-correspondence.json').exists():
                    from . import declared_work_actions
                    result['actions']=declared_work_actions.audit(run,doc,read(Path(args.directory)/'complete.json'),read(Path(args.directory)/'history.json'),read(Path(args.directory)/'action-correspondence.json'),args.directory)
                    if (Path(args.directory)/'work-results.json').exists():
                        from . import work_results
                        result['work_results']=work_results.audit(run,doc,read(Path(args.directory)/'action-correspondence.json'),read(Path(args.directory)/'work-results.json'),args.directory)
                    if (Path(args.directory)/'action-review.json').exists():result['action_reviews']=declared_work_actions.validate_reviews(run,read(Path(args.directory)/'action-correspondence.json'),read(Path(args.directory)/'action-review.json'))
                if (Path(args.directory)/'history-review.json').exists():
                    result['history_reviews']=declared_work_history.validate_reviews(run,doc,read(Path(args.directory)/'history.json'),read(Path(args.directory)/'history-review.json'))
    print(json.dumps(result,ensure_ascii=False,indent=2))
