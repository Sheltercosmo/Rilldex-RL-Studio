"""Ablate result-versus-means interpretation on every saved target-scope page."""
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

RULE=(
    'First identify the immediate intended operation RESULT and the particular subject and requested '
    'task instance from the recorded source. Compare that result separately from the means used to '
    'obtain it. A changed method, route, algorithm, setting, or starting state after partial progress '
    'does not by itself change the work target when the same result for the same instance is still '
    'sought. A selected summary may include such execution details; do not mistake them for a new '
    'goal without source support. A different intended result, particular referent, or separately '
    'requested instance remains different work. Reading or checking a result is distinct from '
    'changing it. Added or removed material work remains partial overlap, not whole-target identity. '
    'A shared broad objective alone is insufficient.'
)
SAME='same_work_target';DIFFERENT='different_work_same_subject';INSTANCE='different_instance'
EXPECTED={
    'simulation':{('e4','e8'):SAME,('e4','e12'):DIFFERENT,('e8','e12'):DIFFERENT},
    'service':{('e4','e8'):INSTANCE,('e4','e12'):DIFFERENT,('e8','e12'):DIFFERENT},
    'software':{('e4','e8'):DIFFERENT,('e4','e12'):'partial_work_overlap',('e8','e12'):DIFFERENT},
    'public_airline':{('e8','e14'):DIFFERENT},
    'public_telecom':{('e8','e12'):INSTANCE},
    'multiagent':{},
}


def records(workspaces='outputs/generated-generalization-refined'):
    for name,expected in EXPECTED.items():
        root=Path(workspaces)/name;config=read(root/'workspace.json')
        selected=read(root/'results'/f'{config["run_id"]}.json')
        ids={u['id']:u['source']['event_id'] for u in selected['units']}
        targets=read(root/'action-target-progress.json')
        for action in targets['actions']:
            current=ids[action['action_unit_id']]
            for page in action['pages']:
                saved=read(root/'decisions'/f'{page["request"]}.json')
                reference={p['question_id']:expected[ids[p['prior_unit_id']],current]
                           for p in action['pairs'] if p['request']==page['request']}
                for arm in ('original','result_and_means'):
                    request=deepcopy(saved['request'])
                    if arm=='result_and_means':request['state']['comparison_rule']+=' '+RULE
                    yield dict(case_id=name,event_id=current,arm=arm,reference=reference,
                               request=request,request_hash=digest(request),
                               original_response=saved['response'] if arm=='original' else None)


def evaluate(directory,live=False,workspaces='outputs/generated-generalization-refined'):
    root=Path(directory);client=JevClient();rows=[]
    for row in records(workspaces):
        path=root/row['case_id']/row['event_id']/row['arm']/(row['request_hash']+'.json')
        if row['arm']=='original':
            response=row['original_response'];write(path,dict(request=row['request'],response=response))
        elif path.exists():
            saved=read(path)
            if saved['request']!=row['request']:raise ValueError('Cached request differs')
            response=saved['response']
        elif live:
            response=client.transport(row['request']);validate_answers(response,row['request'])
            write(path,dict(request=row['request'],response=response))
        else:
            write(path.parent/'request.json',row['request']);continue
        answers=validate_answers(response,row['request'])
        scores={key:dict(expected=expected,prediction=answers[key]['value'],correct=expected==answers[key]['value'])
                for key,expected in row['reference'].items()}
        record={k:v for k,v in row.items() if k not in {'request','original_response'}}
        record.update(receipt=str(path.relative_to(root)),scores=scores);rows.append(record)
        print(row['case_id'],row['event_id'],row['arm'],dumps({k:s['prediction'] for k,s in scores.items()}),flush=True)
    groups={}
    for row in rows:
        group=groups.setdefault(row['arm'],dict(requests=0,pairs=0,correct=0,failures=[]))
        group['requests']+=1
        for key,score in row['scores'].items():
            group['pairs']+=1;group['correct']+=score['correct']
            if not score['correct']:group['failures'].append('/'.join([row['case_id'],row['event_id'],key]))
    report=dict(schema='generated-target-scope-ablation/1',model=client.model,results=rows,groups=groups,
                scope='All eight saved target-scope pages (eleven pairs) from six extraction cases. Multiagent case has no eligible within-context predecessors. Development expectations are separate from requests; this does not measure population accuracy.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='outputs/generated-target-scope-ablation')
    p.add_argument('--workspaces',default='outputs/generated-generalization-refined')
    p.add_argument('--live',action='store_true');p.add_argument('--prompt-key',action='store_true')
    args=p.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,args.workspaces)))
