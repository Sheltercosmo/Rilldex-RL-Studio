"""Controlled role-clarification ablation on saved generated-workspace plans."""
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
    'A dispatch that performs an explicitly named verification step may also inspect an earlier '
    'step\'s result when the visible source links the check to that actual product. Judge these '
    'relationships independently for each step. Performing the verification step does not consume '
    'or replace its supported inspection relationship to the earlier product. Require the specific '
    'source connection; do not propagate links from mere plan order or upstream input dependence. '
    'A check attempt does not establish a passing result or successful completion.'
)
PERFORM='performs_or_updates_step';UPSTREAM='upstream_work_only';OTHER='another_step_or_unrelated'
EXPECTED={
    'simulation':{'e4':[PERFORM,UPSTREAM],'e8':[OTHER,UPSTREAM],'e12':[OTHER,PERFORM]},
    'service':{'e4':[PERFORM,UPSTREAM],'e8':[OTHER,UPSTREAM],'e12':[OTHER,PERFORM]},
    'software':{'e4':[PERFORM,UPSTREAM,OTHER],'e8':[OTHER,PERFORM,UPSTREAM],
                'e12':[OTHER,'inspects_step_result',PERFORM]},
}


def records():
    for version,names in [('baseline',['simulation','service','software']),('refined',['service','software'])]:
        base=Path('outputs/generated-generalization'+('-refined' if version=='refined' else ''))
        for name in names:
            root=base/name;config=read(root/'workspace.json')
            selected=read(root/'results'/f'{config["run_id"]}.json')
            ids={u['id']:u['source']['event_id'] for u in selected['units']}
            roles=read(root/'plan-relation-progress.json')
            for action in roles['actions']:
                eid=ids[action['action_unit_id']]
                for page in action['pages']:
                    saved=read(root/'decisions'/f'{page["request"]}.json')
                    reference={p['question_id']:EXPECTED[name][eid][int(p['step_id'][1:])]
                               for p in action['pairs'] if p['request']==page['request']}
                    for arm in ('original','independent_roles'):
                        req=deepcopy(saved['request'])
                        if arm=='independent_roles':req['state']['comparison_rule']+=' '+RULE
                        yield dict(version=version,case_id=name,event_id=eid,arm=arm,reference=reference,
                            request=req,request_hash=digest(req),original_response=saved['response'] if arm=='original' else None)


def evaluate(directory,live=False):
    root=Path(directory);client=JevClient();rows=[]
    for row in records():
        folder=root/row['version']/row['case_id']/row['event_id']/row['arm']
        path=folder/(row['request_hash']+'.json')
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
            write(folder/'request.json',row['request']);continue
        answers=validate_answers(response,row['request'])
        scores={key:dict(expected=expected,prediction=answers[key]['value'],correct=expected==answers[key]['value'])
                for key,expected in row['reference'].items()}
        record={k:v for k,v in row.items() if k not in {'request','original_response'}}
        record.update(receipt=str(path.relative_to(root)),scores=scores)
        rows.append(record)
        print(row['version'],row['case_id'],row['event_id'],row['arm'],
              dumps({key:s['prediction'] for key,s in scores.items()}),flush=True)
    groups={}
    for row in rows:
        group=groups.setdefault(row['arm'],dict(requests=0,pairs=0,correct=0,failures=[]))
        group['requests']+=1
        for key,score in row['scores'].items():
            group['pairs']+=1;group['correct']+=score['correct']
            if not score['correct']:group['failures'].append('/'.join([row['version'],row['case_id'],row['event_id'],key]))
    report=dict(schema='generated-plan-role-ablation/1',model=client.model,results=rows,groups=groups,
        scope='Fifteen recorded request occurrences from three authored scenarios; repeated identical requests can return different model choices. References are separately specified development expectations and are not sent to the model. This is not a population accuracy estimate.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='outputs/generated-plan-role-ablation')
    p.add_argument('--live',action='store_true');p.add_argument('--prompt-key',action='store_true')
    args=p.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live)))
