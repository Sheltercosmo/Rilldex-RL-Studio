"""Bounded existing code-flow/artifact page regression; no trace code runs."""
import argparse
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import diagnostic_search as search, diagnostic_direct as direct
from tracker import diagnostic_code_flow as flow, diagnostic_contract as contract
from tracker.jev import JevClient, validate_answers
from tracker.schema import InputError, digest, dumps
from tracker.semantic_extraction import read, write

FIXTURE=Path(__file__).resolve().parents[1]/'outputs/diagnostic-specialized-regression/inputs.json'


def page_value(request,response):
    answers=validate_answers(response,request)
    direct_choice=answers['evaluator_bypass']['value']
    contract_rows=list(contract.observations(request['state'],answers))
    positives=(direct_choice in request['state']['candidate_fragment_ids']
               or any(flow.flags(request['state'],answers)) or any(row['flagged'] for row in contract_rows))
    unresolved=direct_choice=='unresolved' or any(row['unresolved'] for row in contract_rows)
    return 1 if positives else None if unresolved else 0


def evaluate(directory='outputs/diagnostic-specialized-regression/reviewed',*,live=False,client=None,max_calls=4,fixture_path=FIXTURE):
    fixture=read(fixture_path);root=Path(directory);client=client or JevClient();calls=0;results=[]
    requests={}
    for case in fixture['entries']:
        if digest(case['source'])!=case['source_hash']:raise InputError('Frozen source changed')
        original=next(r for r in direct.requests(case['source'],search.CONTRACT_VERSION) if r['state']['page']==case['page'])
        if original!=case['baseline_request']:raise InputError('Preserved baseline changed')
        request=next(r for r in direct.requests(case['source'],search.ATTRIBUTED_VERSION) if r['state']['page']==case['page'])
        requests[case['id']]=request
    manifest=dict(schema='diagnostic-specialized-execution/1',fixture_hash=digest(fixture),version=search.ATTRIBUTED_VERSION,
                  request_hashes={cid:digest(req) for cid,req in requests.items()})
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:raise InputError('Requests changed; use a fresh output directory')
    write(root/'inputs.json',manifest)
    for case in fixture['entries']:
        request=requests[case['id']];key=digest(request);baseline=case['baseline_receipt'];response=None;origin=None
        if digest(baseline['response'])!=baseline['response_hash']:raise InputError('Baseline response changed')
        baseline_value=page_value(case['baseline_request'],baseline['response'])
        receipt=root/'receipts'/(key+'.json');write(root/'requests'/(key+'.json'),request)
        if request==case['baseline_request']:
            response=baseline['response'];origin='exact_prior_receipt'
        elif receipt.exists():
            saved=read(receipt)
            if saved['request']!=request:raise InputError('Cached request changed')
            response=saved['response'];origin='cached'
        elif live and calls<max_calls:
            response=client.transport(request);calls+=1;origin='live'
        record=dict(id=case['id'],page=case['page'],kind=case['kind'],source_hash=case['source_hash'],
            request_hash=key,baseline_request_hash=case['baseline_request_hash'],baseline_prediction=baseline_value,
            reference=case['expected_bypass'],packet_unchanged=request==case['baseline_request'],response_origin=origin)
        if response is not None:
            if response.get('model')!=request['model']:raise InputError('Response model differs')
            prediction=page_value(request,response)
            record.update(prediction=prediction,reference_match=prediction==case['expected_bypass'],response_hash=digest(response))
            write(receipt,dict(request=request,response=response))
        results.append(record);print(dumps(record),flush=True)
        write(root/'report.json',dict(schema='diagnostic-specialized-results/1',new_calls=calls,
            completed=sum('prediction' in r for r in results),reference_matches=sum(r.get('reference_match',False) for r in results),
            results=results,scope=fixture['scope']))
    return read(root/'report.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/diagnostic-specialized-regression/reviewed')
    parser.add_argument('--fixture',type=Path,default=FIXTURE)
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=4);args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    result=evaluate(args.output,live=args.live,fixture_path=args.fixture,max_calls=args.max_calls)
    print(dumps({k:v for k,v in result.items() if k!='results'}))
