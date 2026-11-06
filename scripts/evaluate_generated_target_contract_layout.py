"""Separate repeated declarations from interpretation-rule effects."""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest,dumps
from tracker.semantic_extraction import read,write

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/generated-generalization-target-interval-production.json'
ARMS=('endpoint_only','catalog_only','declarations_only')


def records(*,repeat_original=False):
    frozen=read(FIXTURE)
    for row in frozen['rows']:
        if not ((row['case_id']=='service' and row['event_id']=='e12') or row['case_id'].startswith(('declared_','undeclared_'))):continue
        original=frozen['requests'][row['request_hash']]
        arms=[*ARMS]
        if repeat_original and row['case_id']=='service':arms.append('repeat_original')
        for arm in arms:
            request=deepcopy(original)
            if arm=='endpoint_only':
                request['state'].pop('tool_catalog',None);request['state'].pop('environment_encoding',None)
            elif arm=='catalog_only':request['state'].pop('recorded_endpoint_contracts',None)
            elif arm=='declarations_only':request['state'].pop('interpretation_rule',None)
            yield {k:deepcopy(row[k]) for k in ('case_id','event_id','packet_id','reference','origin')} | dict(
                arm=arm,request=request,request_hash=digest(request),original_request_hash=row['request_hash'],
                reusable_response=row['response'] if request==original and arm!='repeat_original' else None)


def evaluate(directory,live=False,repeat_original=False):
    root=Path(directory);client=JevClient();rows=[];manifest=[]
    for row in records(repeat_original=repeat_original):
        path=root/row['case_id']/row['event_id']/row['packet_id']/row['arm']/(row['request_hash']+'.json')
        record={k:v for k,v in row.items() if k not in {'request','reusable_response'}}
        manifest.append(record);write(root/'manifest.json',manifest)
        if path.exists():
            receipt=read(path)
            if receipt['request']!=row['request']:raise ValueError('Receipt differs')
            response=receipt['response']
        elif row['reusable_response'] is not None:
            response=row['reusable_response'];write(path,dict(request=row['request'],response=response))
        elif live:
            response=client.transport(row['request']);validate_answers(response,row['request'])
            write(path,dict(request=row['request'],response=response))
        else:write(path.parent/'request.json',row['request']);continue
        answers=validate_answers(response,row['request'])
        record.update(receipt=str(path.relative_to(root)),scores={k:dict(expected=v,prediction=answers[k]['value'],correct=v==answers[k]['value'])
            for k,v in row['reference'].items()})
        rows.append(record);write(root/'partial-results.json',rows)
        print(row['case_id'],row['packet_id'],row['arm'],dumps(record['scores']),flush=True)
    report=dict(schema='target-contract-layout-diagnostic/1',results=rows,
        scope='Only source declaration layout or its existing interpretation rule changes; source intervals, local meanings, native inputs and six labels/questions remain fixed. Service source subtype reference is under review; preserve actual outputs.')
    write(root/'report.json',report)
    return dict(invocations=len(rows),**{k:v for k,v in report.items() if k!='results'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/generated-target-contract-layout')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--repeat-original',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,args.repeat_original)))
