"""Separate question batching, candidate batching and generated-summary bias."""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_generated_plan_roles import records as plan_records
from scripts.evaluate_generated_target_scope import records as target_records
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest,dumps
from tracker.semantic_extraction import read,write


FOCUS={('target','refined','simulation','e8','a0'),
       ('target','refined','service','e8','a0'),
       ('target','refined','software','e12','a0'),
       ('plan','refined','software','e12','s0'),
       ('plan','refined','software','e12','s1'),
       ('plan','refined','software','e12','s2'),
       ('plan','refined','service','e12','s1')}
ARMS=('original','single_question','single_candidate','source_only')


def requests(*,focused=False,arms=None,kinds=None):
    for kind,rows in [('plan',plan_records()),('target',target_records())]:
        if kinds is not None and kind not in kinds:continue
        for row in rows:
            if row['arm']!='original':continue
            for question,reference in row['reference'].items():
                identity=(kind,row.get('version','refined'),row['case_id'],row['event_id'],question)
                if focused and identity not in FOCUS:continue
                original=row['request']
                for arm in arms or ARMS:
                    q=deepcopy(original)
                    if arm!='original':q['questions']={question:q['questions'][question]}
                    if arm in {'single_candidate','source_only'}:
                        field='plan_stage_candidates' if kind=='plan' else 'prior_actions'
                        q['state'][field]=[c for c in q['state'][field] if c['id']==question]
                    if arm=='source_only':
                        state=q['state']
                        if kind=='plan':
                            state.pop('action_content',None);state.pop('action_activity',None)
                            for c in state['plan_stage_candidates']:
                                c.pop('plan_content',None)
                                c['step'].pop('text',None);c['step'].pop('target',None)
                            q['questions'][question]['instructions']=(
                                'Select the direct role of CURRENT dispatch for the specific plan stage '
                                'identified by the exact source evidence in candidate '+question+'. '
                                'Interpret roles for that stage, not the plan as a whole. Follow comparison_rule.')
                        else:
                            state.pop('current_meaning',None)
                            for c in [state['current_action'],*state['prior_actions']]:
                                c.pop('content',None);c.pop('activity',None)
                    # Full readable prefix, all native contracts and cutoffs are
                    # deliberately identical in every controlled arm.
                    assert q['state']['prefix']==original['state']['prefix']
                    yield dict(kind=kind,version=row.get('version','refined'),case_id=row['case_id'],
                        event_id=row['event_id'],question_id=question,reference=reference,arm=arm,
                        request=q,request_hash=digest(q),
                        original_response=row['original_response'] if arm=='original' else None)


def evaluate(directory,live=False,*,focused=False,arms=None,kinds=None):
    root=Path(directory);client=JevClient();rows=[]
    for row in requests(focused=focused,arms=arms,kinds=kinds):
        folder=root/row['kind']/row['version']/row['case_id']/row['event_id']/row['question_id']/row['arm']
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
        answer=validate_answers(response,row['request'])[row['question_id']]
        prediction=answer['value'] if answer['status']=='decided' else answer['status']
        result={k:v for k,v in row.items() if k not in {'request','original_response'}}
        result.update(prediction=prediction,correct=prediction==row['reference'],receipt=str(path.relative_to(root)))
        rows.append(result)
        print(row['kind'],row['version'],row['case_id'],row['event_id'],row['question_id'],row['arm'],prediction,flush=True)
        write(root/'partial-results.json',rows)
    groups={}
    for row in rows:
        group=groups.setdefault(row['kind']+'/'+row['arm'],dict(pairs=0,correct=0,failures=[]))
        group['pairs']+=1;group['correct']+=row['correct']
        if not row['correct']:group['failures'].append('/'.join([row['version'],row['case_id'],row['event_id'],row['question_id']]))
    report=dict(schema='generated-pair-attention-ablation/1',model=client.model,groups=groups,results=rows,
        selection='focused_seven_pairs' if focused else 'all_recorded_pairs',
        scope='Question-only, candidate-only and source-only ablations with identical readable source and cutoffs. Baseline/refined duplicate requests remain separate recorded invocations. Development expectations are never sent as answers.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


def freeze(directories, destination):
    """Retain duplicate live invocations separately while deduplicating requests."""
    requests_by_hash={};sets={}
    for label,directory in directories.items():
        root=Path(directory);report=read(root/'report.json');rows=[]
        for row in report['results']:
            saved=read(root/row['receipt']);key=digest(saved['request'])
            if key!=row['request_hash']:raise ValueError('Saved request hash differs')
            if key in requests_by_hash and requests_by_hash[key]!=saved['request']:
                raise ValueError('Request collision')
            requests_by_hash[key]=saved['request']
            rows.append({**{k:v for k,v in row.items() if k!='receipt'},'response':saved['response']})
        sets[label]=dict(groups=report['groups'],selection=report['selection'],rows=rows)
    write(Path(destination),dict(schema='generated-pair-attention-evidence/1',requests=requests_by_hash,sets=sets,
        scope='Actual source-preserving question/candidate ablations. Small development source review; not a general semantic accuracy estimate. Duplicate request invocations retain their individual responses.'))
    return dict(requests=len(requests_by_hash),invocations=sum(len(s['rows']) for s in sets.values()))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='outputs/generated-pair-attention-ablation')
    p.add_argument('--live',action='store_true');p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--focused',action='store_true',help='Seven diagnostic pairs; 21 new calls with all three arms')
    p.add_argument('--arms',nargs='+',choices=ARMS,help='Only run selected arms when broadening a promising result')
    p.add_argument('--kinds',nargs='+',choices=('plan','target'),help='Only evaluate selected relationship layers')
    args=p.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,focused=args.focused,arms=args.arms,kinds=args.kinds)))
