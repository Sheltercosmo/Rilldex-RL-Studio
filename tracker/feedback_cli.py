"""Budgeted, resumable source observations; never invoked by dashboard reads."""
import getpass
import json
import os
from pathlib import Path

from . import feedback_assessment as fa
from .schema import InputError
from .semantic_extraction import read


class BudgetReached(Exception):
    pass


def configure(commands):
    p=commands.add_parser('feedback-monitor',help='Measure expressed feedback assessment directly from source calls and responses')
    p.add_argument('directory');p.add_argument('--run-id',action='append',required=True)
    p.add_argument('--max-new-calls',type=int,default=50)
    p.add_argument('--prompt-key',action='store_true');p.add_argument('--audit-only',action='store_true')


def execute(args,store):
    from .jev import JevClient
    from .diagnostic_worker import inventory,selection
    if not 0<=args.max_new_calls<=10000:raise InputError('Use a call budget from 0 to 10,000')
    # Resolve complete current revisions before any model call or publication.
    rows=inventory(store,selection(run_ids=args.run_id))
    if any(r['source_state'] not in {'complete','imported_snapshot'} for r in rows):
        raise InputError('Feedback observations require complete source snapshots')
    client=JevClient();prompted=False;calls=0;completed=[]
    def transport(req):
        nonlocal prompted,calls
        if calls>=args.max_new_calls:raise BudgetReached()
        if args.prompt_key and not prompted:
            os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
        calls+=1
        return client.transport(req)
    for row in rows:
        run=row['_run'];root=Path(args.directory)/run['id']
        if args.audit_only:result=fa.audit(run,read(root/'result.json'),root)
        else:
            try:
                observed,_=fa.execute(run,root,transport)
            except BudgetReached:
                print(json.dumps({'status':'call_budget_reached','new_calls':calls,'completed':completed,
                                  'pending_run_id':run['id'],'resume':'Repeat the same command; validated decisions are reused.'}))
                return
            result=fa.register(store,run,observed,root)
        completed.append({'run_id':run['id'],**result})
        print(json.dumps({'run_id':run['id'],'new_calls':calls,'result':result}),flush=True)
    print(json.dumps({'status':'complete','new_calls':calls,'rollouts':len(completed)}))
