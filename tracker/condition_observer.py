"""Run the experimental condition observer with immutable inputs and a bounded budget."""
from pathlib import Path
import time
from . import condition_grounding as cg
from .metered_jev import BoundedTransport,BudgetExhausted,UnknownAttempt
from .semantic_extraction import Pipeline,FileCandidates,read,write
from .schema import InputError,digest,dumps

VERSION='condition-observer-execution/1'


def _freeze(path,value):
    try:
        with path.open('x',encoding='utf-8') as stream:stream.write(dumps(value))
    except FileExistsError:
        if read(path)!=value:raise InputError('Workspace is bound to different source, protocol or selection; use another workspace')


def execute(run,document,workspace,*,pair_ids=None,protocol=cg.SHARED_CONTRACT_VERSION,maximum=0,send=None):
    root=Path(workspace);pool=cg.candidates(run,document)
    if protocol not in cg.PROTOCOLS:raise InputError('Unknown grounding protocol')
    if pair_ids is not None and (len(pair_ids)!=len(set(pair_ids)) or set(pair_ids)-{p['id'] for p in pool}):
        raise InputError('Unknown or duplicate condition pair')
    transport=BoundedTransport(root,maximum,send)
    binding={'schema':VERSION,'source_hash':digest(run),'document_hash':digest(document),'protocol':protocol,
             'selection':None if pair_ids is None else sorted(pair_ids)}
    frozen={'run':run,'document':document};root.mkdir(parents=True,exist_ok=True)
    binding_path=root/'observer-input.json'
    if binding_path.exists() and read(binding_path)!=binding:
        raise InputError('Workspace is bound to different source, protocol or selection; use another workspace')
    _freeze(root/'input.json',frozen);_freeze(binding_path,binding)
    engine=Pipeline(root,FileCandidates(root/'unused'),transport);started=time.time_ns();result=None
    receipt={'schema':VERSION,'binding_hash':digest(binding),'status':'interrupted','protocol':protocol,
             'maximum_total_http_attempts':maximum,'requested_pairs':len(pool) if pair_ids is None else len(pair_ids)}
    def decide(req):
        try:return engine.decide(req)
        except (BudgetExhausted,UnknownAttempt):
            receipt['pending_request']=digest(req);write(root/'pending_requests'/f'{digest(req)}.json',req)
            raise
    try:
        result=cg.build(run,document,decide,pair_ids,protocol)
        validation=cg.audit(run,document,result,root)
        write(root/'result.json',result)
        receipt.update(status='complete',result_hash=digest(result),validation=validation)
    except BudgetExhausted:receipt['status']='needs_budget'
    except UnknownAttempt:receipt['status']='needs_attempt_review'
    finally:
        receipt.update(new_http_attempts=transport.calls,usage=dict(transport.usage),luna_calls=0)
        write(root/'executions'/f'{started}.json',receipt);write(root/'execution-status.json',receipt)
    return result,receipt


def main():
    import argparse,getpass,os
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path);parser.add_argument('--workspace',type=Path)
    parser.add_argument('--protocol',choices=sorted(cg.PROTOCOLS),default=cg.SHARED_CONTRACT_VERSION)
    parser.add_argument('--pair-id',action='append');parser.add_argument('--list-pairs',action='store_true')
    parser.add_argument('--max-total-http-attempts',type=int,default=0);parser.add_argument('--prompt-key',action='store_true')
    args=parser.parse_args();value=read(args.input);run,doc=value['run'],value['document']
    if args.list_pairs:
        for pair in cg.candidates(run,doc):print(dumps({'id':pair['id'],'event_id':pair['action']['source']['event_id'],
            'record':pair['record_id'],'clause':pair['clause']['text'],'action':pair['action'].get('content',{}).get('summary',{}).get('text')}))
        return
    if args.workspace is None:parser.error('--workspace is required unless listing pairs')
    if args.max_total_http_attempts<0:parser.error('Budget must be nonnegative')
    if args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
    _,receipt=execute(run,doc,args.workspace,pair_ids=args.pair_id,protocol=args.protocol,maximum=args.max_total_http_attempts)
    print(dumps(receipt))
    if receipt['status']!='complete':raise SystemExit(2)


if __name__=='__main__':main()
