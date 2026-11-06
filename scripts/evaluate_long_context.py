"""Live controlled tests of distant revisions and previously drafted outputs."""
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker.activity import ActivityClient, units
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest, dumps, InputError
from tracker.semantic_extraction import request, activity_choices, WORK_ORGANIZATION_ACTIVITY_ROUTING
from tracker.semantic_workspace import DEFAULT_CONTEXT
from tracker.semantic_map import evidence


def cases():
    for name,first,last in [
        ('navigation','I will deliver package B7 by the direct road.',
         'I withdraw my earlier direct-road plan for package B7. I will deliver it by ferry instead.'),
        ('analysis','I conclude that sensor R4 is defective because its reading is zero.',
         'I retract my earlier conclusion that sensor R4 is defective. Its zero reading was a missing-value code.'),
        ('writing','I propose the title Quiet Rivers for the essay.',
         'I replace my earlier proposed title Quiet Rivers with River Memory.')]:
        yield name,'revision',first,last
    for name,text in [('query','SELECT region, SUM(sales) FROM orders GROUP BY region;'),
                      ('copy','Discover quiet paths. Travel lightly.'),
                      ('config','{"retry_limit": 3, "timeout_seconds": 20}')]:
        yield name,'delivery','Here is the completed draft to deliver later:\n'+text,text


def records():
    for name,kind,first,last in cases():
        messages=[{'role':'user','content':'Complete the task, then deliver the final result.'},
                  {'role':'assistant','content':first}]
        for i in range(12):
            messages += [{'role':'assistant','content':f'Read station S{i}.','tool_calls':[
                {'id':f'c{i}','type':'function','function':{'name':'sensor','arguments':dumps({'station':f'S{i}'})}}]},
                {'role':'tool','tool_call_id':f'c{i}','content':f'Temperature {17+i} degrees.'}]
        messages.append({'role':'assistant','content':last})
        run=normalize({'messages':messages,'tools':[{'type':'function','function':{
            'name':'sensor','description':'Read a weather station without changing anything.','parameters':{'type':'object'}}}]})[0]
        subject=run['events'][-1];ref=evidence(run,subject['id'])
        for arm in ('current','complete_prefix'):
            if kind=='revision':
                us=units(run);u=next(u for u in us if u['event_id']==subject['id'])
                req=ActivityClient().request(run,u['id'])
                target=next(u for u in us if u['event_id']==run['events'][1]['id'])
                reference=target['id'];key='revision_target'
                req['questions']={key:req['questions'][key]}
                if arm=='complete_prefix':
                    req['state']['earlier_units']=[deepcopy(u) for u in us if u['event_index']<subject['index']]
                    req['questions'][key]['criteria'].update({u['id']:u['text'] for u in req['state']['earlier_units']})
            else:
                req=request(run,ref,'activity','Choose exactly one activity for this established contribution. Classify what this unit itself does.',
                    activity_choices(WORK_ORGANIZATION_ACTIVITY_ROUTING),
                    context_policy=None if arm=='complete_prefix' else DEFAULT_CONTEXT,
                    expression_form='model-authored expression',activity_routing=WORK_ORGANIZATION_ACTIVITY_ROUTING)
                reference='report';key='choice'
            yield {'case_id':name,'kind':kind,'arm':arm,'reference':reference,'answer_key':key,
                   'request_hash':digest(req),'request':req}


def evaluate(output,live=False):
    root=Path(output);root.mkdir(parents=True,exist_ok=True);client=JevClient();results=[]
    rows=list(records());(root/'requests.json').write_text(dumps(rows),encoding='utf8')
    for row in rows:
        record={k:v for k,v in row.items() if k!='request'}
        if live:
            path=root/(row['request_hash']+'.json')
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf8'))
                if saved['request']!=row['request']:raise InputError('Cached request differs')
                response=saved['response']
            else:
                response=client.transport(row['request'])
                path.write_text(dumps({'request':row['request'],'response':response}),encoding='utf8')
            if response.get('model')!=client.model:raise InputError('Provider model differs')
            answer=validate_answers(response,row['request'])[row['answer_key']]
            value=answer['value'] if answer['status']=='decided' else answer['status']
            record.update(prediction=value,correct=value==row['reference'])
            print(row['case_id'],row['arm'],value,flush=True)
        results.append(record)
    groups={}
    for r in results:
        if 'correct' not in r:continue
        g=groups.setdefault(r['kind']+'/'+r['arm'],{'correct':0,'cases':0})
        g['cases']+=1;g['correct']+=r['correct']
    report={'groups':groups,'results':results,'scope':'Six authored context-retrieval controls. Same source and task; full prefix diagnoses missing evidence. Not independent generalization accuracy.'}
    (root/'report.json').write_text(dumps(report),encoding='utf8');return groups


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--prompt-key',action='store_true');args=p.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    try:print(dumps(evaluate(args.output,args.live)))
    except InputError as exc:p.exit(2,str(exc)+'\n')
