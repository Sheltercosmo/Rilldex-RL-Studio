"""Compare actual macro and semantic-unit readings across equivalent captures.

These are authored development controls. Provider serialization is varied while
the operation, task and definitions remain fixed; no model generates references.
"""
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_environment_reading import cases
from tracker.adapters import normalize
from tracker.jev import JevClient, validate_answers
from tracker.portable import responses_document
from tracker.schema import digest, dumps, InputError
from tracker.semantic_extraction import request as semantic_request, activity_choices, WORK_ORGANIZATION_ACTIVITY_ROUTING
from tracker.semantic_map import evidence
from tracker.semantic_workspace import DEFAULT_CONTEXT
from scripts.evaluate_reading_context import cases as context_cases


def evaluation_cases():
    for case in cases():
        if 'messages' in case['document']:yield {**case,'origin':'authored'}
    for case in context_cases():
        if case['kind']!='public_trace':continue
        run=normalize(case['document'])[0]
        focal=next(e for e in run['events'] if e['id']==case['action_id'])
        messages=[]
        # Serialize only the assistant-visible source prefix. User-side tools,
        # hidden evaluator state and raw provider metadata are not conversations.
        for e in run['events']:
            if e['index']>focal['index']:break
            if e['kind'].startswith('external_') or e.get('agent_visibility')=='not_established':continue
            if e['kind']=='action':
                messages.append({'role':'assistant','content':'','tool_calls':[{'id':e['call_id'],'type':'function',
                    'function':{'name':e['tool'],'arguments':dumps(e['arguments'])}}]})
            elif e['kind']=='feedback':
                messages.append({'role':'tool','tool_call_id':e['source_call_id'],'content':e['text']})
            elif e['kind']=='context' and e.get('context_kind')=='recorded_environment_policy':
                # This is the recorded governing environment policy, not prose
                # authored by the agent. Keep its attribution in every format.
                messages.append({'role':'system','content':e['text']})
            else:
                if e['actor'] not in {'system','developer','user','agent'}:
                    raise InputError('Public source context needs an explicit role-preserving projection')
                role=e['actor'] if e['actor'] in {'system','developer','user'} else 'assistant'
                messages.append({'role':role,'content':e['text']})
        yield {'id':case['id'],'origin':'public_trace','document':{'messages':messages},
               'reference':case['reference']['mode'],'call_id':focal['call_id']}


def representations(document):
    yield 'chat',deepcopy(document)
    messages=[];items=[]
    for message in document['messages']:
        role=message['role'];text=message.get('content') or ''
        if role=='tool':
            messages.append({'role':'user','content':[{'type':'tool_result','tool_use_id':message['tool_call_id'],'content':text}]})
            items.append({'type':'function_call_output','call_id':message['tool_call_id'],'output':text})
            continue
        blocks=[{'type':'text','text':text}] if text else []
        if text:items.append({'type':'message','role':role,'content':text})
        for call in message.get('tool_calls',[]):
            f=call['function']
            blocks.append({'type':'tool_use','id':call['id'],'name':f['name'],'input':json.loads(f['arguments'])})
            items.append({'type':'function_call','call_id':call['id'],'name':f['name'],'arguments':f['arguments']})
        messages.append({'role':role,'content':blocks or text})
    functions=[t['function'] for t in document.get('tools',[])]
    yield 'anthropic',{'messages':messages,'tools':[{'name':f['name'],'description':f.get('description',''),
                         'input_schema':f.get('parameters',{})} for f in functions]}
    yield 'responses',responses_document(items,tools=[{'type':'function',**f} for f in functions])


def requests():
    client=JevClient()
    base={'explore':'inspect','apply':'construct','verify':'verify','coordinate':'coordinate','report':'report','unresolved':'unresolved'}
    for case in evaluation_cases():
        for format_name,doc in representations(case['document']):
            run=normalize(doc)[0];action=next(e for e in run['events'] if e['kind']=='action' and
                ('call_id' not in case or e.get('call_id')==case['call_id']))
            macro=client.request(run,action['id']);macro['questions']={'mode':macro['questions']['mode']}
            semantic=semantic_request(run,evidence(run,action['id']),'activity',
                'Choose exactly one activity for this established contribution. Classify what this unit itself does; requesting another actor to check something is Coordinate, not this agent performing Verify.',
                activity_choices(WORK_ORGANIZATION_ACTIVITY_ROUTING),context_policy=DEFAULT_CONTEXT,
                expression_form='recorded action dispatch',activity_routing=WORK_ORGANIZATION_ACTIVITY_ROUTING)
            for layer,req,reference,key in [('macro',macro,case['reference'],'mode'),('unit_activity',semantic,base[case['reference']],'choice')]:
                yield {'case_id':case['id'],'origin':case['origin'],'format':format_name,'layer':layer,'reference':reference,'answer_key':key,
                       'source_hash':digest(run),'request_hash':digest(req),'request':req}


def evaluate(directory,live=False):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    rows=list(requests());(root/'requests.json').write_text(dumps(rows),encoding='utf8')
    client=JevClient();results=[]
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
                if response.get('model')!=client.model:raise InputError('Provider model differs')
                validate_answers(response,row['request'])
                path.write_text(dumps({'request':row['request'],'response':response}),encoding='utf8')
            answer=validate_answers(response,row['request'])[row['answer_key']]
            prediction=answer['value'] if answer['status']=='decided' else answer['status']
            record.update(prediction=prediction,correct=prediction==row['reference'])
            print(row['case_id'],row['format'],row['layer'],prediction,flush=True)
        results.append(record)
    groups={}
    for row in results:
        if 'correct' not in row:continue
        group=groups.setdefault(row['origin']+'/'+row['format']+'/'+row['layer'],{'cases':0,'correct':0,'failures':[]})
        group['cases']+=1;group['correct']+=row['correct']
        if not row['correct']:group['failures'].append(row['case_id'])
    report={'status':'evaluated' if live else 'requests_only','model':client.model,'groups':groups,'results':results,
        'scope':'Authored controls and selected public tau-bench actions, separately reported across three serializations. Public prefixes preserve visible text and calls but omit hidden evaluator/user-tool records. Source dispatch is one unit; prose boundaries, generated content, relations and whole-rollout accuracy are not measured by this test.'}
    (root/'report.json').write_text(dumps(report),encoding='utf8')
    return {k:v for k,v in report.items() if k!='results'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='outputs/harness-generalization')
    p.add_argument('--live',action='store_true');p.add_argument('--prompt-key',action='store_true');args=p.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    try:print(dumps(evaluate(args.output,args.live)))
    except InputError as exc:p.exit(2,str(exc)+'\n')
