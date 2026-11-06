"""Ablate purpose interpretation on actual generated-workspace action requests.

References describe these authored controls. They are never sent to the model.
Original predictions remain recorded alongside three controlled prompt changes.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest, dumps
from tracker.semantic_extraction import read, write

BOUNDARY=(
    'For a read, query or observation, distinguish gathering previously unknown facts for a later decision '
    'from testing a specified claim, expected result or acceptance criterion. The former is Inspect; '
    'a read dispatched to test that expectation is Verify even when the tool only returns data. '
    'Use its expressed local purpose and visible context, not the tool name alone. '
    'A preceding statement merely announcing or requesting a check is not the check itself. '
    'Classify this recorded dispatch separately; neither kind establishes a successful outcome.'
)
REFERENCES={
    'simulation':{'e4':'construct','e8':'construct','e12':'verify'},
    'service':{'e4':'construct','e8':'construct','e12':'verify'},
    'software':{'e4':'verify','e8':'construct','e12':'verify'},
    'multiagent':{'e4':'coordinate','e9':'inspect'},
}


def requests(workspaces):
    for name,expected in REFERENCES.items():
        root=Path(workspaces)/name
        config=read(root/'workspace.json')
        result=read(root/'checkpoints'/f'{config["run_id"]}.json')
        for unit in result['units']:
            if unit['kind']!='action':continue
            saved=read(root/'decisions'/f'{unit["activity_request"]}.json')
            original=saved['request']
            event_id=unit['source']['event_id']
            previous=[e for e in original['state']['prefix'] if e['id']!=event_id and
                      e.get('actor')==unit['actor'] and e.get('kind') in {'message','reasoning'} and
                      e.get('text','').strip()]
            for arm in ['original','purpose_boundary','recent_expression','both']:
                request=deepcopy(original)
                if arm in {'purpose_boundary','both'}:
                    request['questions']['choice']['instructions']+=' '+BOUNDARY
                if arm in {'recent_expression','both'}:
                    request['state']['recent_expression_context']={
                        'source':deepcopy(previous[-1]) if previous else None,
                        'scope':'Most recent meaningful agent expression in the supplied visible prefix. '
                                'Use only to interpret local purpose. This is not an inferred parent, '
                                'a commitment, evidence of execution, or evidence of success.'}
                yield dict(case_id=name,event_id=event_id,arm=arm,reference=expected[event_id],
                           request_hash=digest(request),request=request,
                           original_response=saved['response'] if arm=='original' else None)


def evaluate(directory,workspaces='outputs/generated-generalization',live=False):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    client=JevClient();results=[]
    for row in requests(workspaces):
        path=root/(row['request_hash']+'.json')
        if row['arm']=='original':
            response=row['original_response']
            write(path,dict(request=row['request'],response=response))
        elif path.exists():
            saved=read(path)
            if saved['request']!=row['request']:raise ValueError('Cached request changed')
            response=saved['response']
        elif live:
            response=client.transport(row['request'])
            validate_answers(response,row['request'])
            write(path,dict(request=row['request'],response=response))
        else:
            write(root/'requests'/(row['request_hash']+'.json'),row['request']);continue
        answer=validate_answers(response,row['request'])['choice']
        prediction=answer['value'] if answer['status']=='decided' else answer['status']
        result={k:v for k,v in row.items() if k not in {'request','original_response'}}
        result.update(prediction=prediction,correct=prediction==row['reference'])
        results.append(result)
        print(row['case_id'],row['event_id'],row['arm'],prediction,flush=True)
    groups={}
    for row in results:
        group=groups.setdefault(row['arm'],dict(cases=0,correct=0,failures=[]))
        group['cases']+=1;group['correct']+=row['correct']
        if not row['correct']:group['failures'].append(row['case_id']+'/'+row['event_id'])
    report=dict(schema='generated-purpose-ablation/1',model=client.model,groups=groups,results=results,
                scope='Eleven recorded dispatches from four fresh authored scenarios; paired prompt ablations, not independent samples or population accuracy. References are not provided to the model.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='outputs/generated-purpose-ablation')
    p.add_argument('--workspaces',default='outputs/generated-generalization')
    p.add_argument('--live',action='store_true');p.add_argument('--prompt-key',action='store_true')
    args=p.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.workspaces,args.live)))
