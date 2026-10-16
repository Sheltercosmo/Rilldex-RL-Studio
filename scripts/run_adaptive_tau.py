"""Fresh file-handoff policies -> installed tau2 tools -> installed Rilldex.

The policy transport is an explicit agent-assisted experiment, not an upstream
tau2 agent implementation. Private customer instructions never enter the service
agent packet. No historical policy messages or tool answers are replayed.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)


def visible_messages(messages,role):
    if role=='assistant':return deepcopy(messages)
    # Customer has no access to assistant tool calls or environment feedback.
    return [{'role':m['role'],'content':m['content']} for m in messages
        if m['role'] in {'assistant','user'} and m.get('content')]


def validate_response(packet,response):
    if not isinstance(response,dict) or set(response)!={'request_hash','message'}:
        raise ValueError('Expected request_hash and message')
    if response['request_hash']!=digest(packet):raise ValueError('Response belongs to a different request')
    message=response['message']
    if not isinstance(message,dict) or set(message)-{'content','tool_calls'}:
        raise ValueError('Unexpected message fields')
    content=message.get('content');calls=message.get('tool_calls',[])
    if content is not None and not isinstance(content,str):raise ValueError('Content must be text or null')
    if not isinstance(calls,list) or len(calls)>1:raise ValueError('One native tool call per turn')
    if packet['role']=='user' and calls:raise ValueError('Airline customer has no tools')
    if bool(content and content.strip())==bool(calls):raise ValueError('Supply text or a tool call, exclusively')
    for call in calls:
        if not isinstance(call,dict) or set(call)!={'name','arguments'} or not isinstance(call['name'],str) or not isinstance(call['arguments'],dict):
            raise ValueError('Tool call needs name and object arguments')
    return {'content':content,'tool_calls':calls}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--task',default='2')
    parser.add_argument('--max-turns',type=int,default=32)
    parser.add_argument('--wait-seconds',type=int,default=1200)
    args=parser.parse_args();root=args.root.resolve();repository=args.repository.resolve()
    if root.exists():raise ValueError('Use a new directory; retain every previous attempt')
    if not 1<=args.max_turns<=64:raise ValueError('Use a bounded turn count, 1–64')
    (root/'outputs').mkdir(parents=True)
    os.environ.update(TAU2_DATA_DIR=str(repository/'data'),PYTHON_DOTENV_DISABLED='1',LITELLM_LOCAL_MODEL_COST_MAP='True')
    from loguru import logger
    logger.remove()
    import rilldex,tau2
    from tau2.domains.airline.environment import get_environment,get_tasks
    from tau2.data_model.message import UserMessage,AssistantMessage,ToolCall
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator
    from tau2.evaluator.evaluator_communicate import CommunicateEvaluator
    from tau2.evaluator.evaluator_action import ActionEvaluator
    from rilldex import Outbox,Workspace
    assert 'site-packages' in str(rilldex.__file__) and 'site-packages' in str(tau2.__file__)
    project=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('lifecycle',project/'scripts/rl_lifecycle_simulation.py')
    lifecycle=importlib.util.module_from_spec(spec);spec.loader.exec_module(lifecycle)
    task=next(t for t in get_tasks(None) if t.id==args.task)
    environment=get_environment();initial=task.initial_state
    environment.set_state(initialization_data=initial.initialization_data if initial else None,
        initialization_actions=initial.initialization_actions if initial else None,message_history=[])
    if initial and initial.message_history:raise ValueError('This experiment requires a task without recorded initial messages')
    tools=[t.openai_schema for t in environment.get_tools()]
    experiment='adaptive-native-tau-'+root.name
    server=lifecycle.Server(root,experiment);server.start()
    outbox=Outbox(root/'outbox.sqlite',endpoint=server.url,producer='fresh-tau-policy',timeout=3)
    identity='fresh-airline-'+args.task;messages=[];native_messages=[];calls=[];requests=[];prefixes=[]
    started=datetime.now(timezone.utc).isoformat();terminal=None
    info={'git_commit':'4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699',
        'environment_info':{'domain_name':'airline','policy':environment.get_policy(),'tool_defs':tools},
        'agent_info':{'llm':'gpt-6-luna','interface':'Codex subagent file handoff; exact provider usage unavailable'}}
    origin={'policy':'fresh Luna service agent and customer subagents','execution':'native installed tau2 environment',
        'transport':'agent-assisted file handoff','task_selection':'Published airline task 2: objective change and customer-claim verification',
        'scope':'Development experiment; not the upstream agent/user orchestrator or a benchmark score'}
    write(root/'manifest.json',{'task_id':task.id,'task_hash':digest(task.model_dump(mode='json')),
        'info':info,'origin':origin,'max_turns':args.max_turns,'started':started,
        'runtime':{'tau2':tau2.__file__,'rilldex':rilldex.__file__}})
    def document(reason='in_progress',reward=None):
        return {'trajectory_format':'tau-bench/1','info':info,'task':task.model_dump(mode='json'),'source_origin':origin,
            'simulation':{'id':identity,'task_id':task.id,'start_time':started,'termination_reason':reason,
                'messages':deepcopy(messages),'reward_info':reward}}
    def publish(state='in_progress',reason='in_progress',reward=None):
        doc=document(reason,reward);outbox.log(identity,doc,state=state,format='tau-bench',metadata={'experiment':experiment})
        status=outbox.drain(limit=1000)
        assert status['pending']==0 and status['blocked']==0,status
        with outbox.connect() as c:
            receipt=json.loads(c.execute('SELECT receipt FROM queue WHERE rollout=? ORDER BY revision DESC LIMIT 1',(identity,)).fetchone()[0])
        run=server.request('/api/runs/'+receipt['id']+'?raw=1')['run']
        assert run['raw']['simulation']['messages']==messages
        if state=='in_progress':assert run['outcome']['recorded_reward'] is None
        prefixes.append({'run_id':run['id'],'messages':len(messages),'state':state})
        write(root/'latest-document.json',doc)
        return run
    role='user'
    try:
        for turn in range(args.max_turns):
            prompt=(environment.get_policy() if role=='assistant' else
                'Simulate the customer described below. Follow the scenario, and answer only as the customer. '
                'Do not invent identifiers or unknown facts. Reveal information naturally when relevant. '
                'When the conversation is finished, respond with ###STOP###. If transferred, use ###TRANSFER###.\n\n'+str(task.user_scenario))
            packet={'schema':'adaptive-policy-handoff/1','turn':turn,'role':role,'system':prompt,
                'messages':visible_messages(messages,role),'tools':tools if role=='assistant' else [],
                'response_contract':{'request_hash':'SHA-256 of this packet using the provided digest helper',
                    'message':{'content':'text or null','tool_calls':'optional [{name, arguments}]; at most one'}},
                'limits':'No hidden state, evaluator information, previous recordings or future messages are supplied.'}
            request=root/role/'requests'/f'{turn:03}.json';response=root/role/'responses'/f'{turn:03}.json'
            write(request,packet);key=digest(packet)
            write(request.with_suffix('.receipt.json'),{'request_hash':key,'response_path':str(response)})
            write(root/'status.json',{'status':'waiting_for_policy','role':role,'turn':turn,'request':str(request),
                'response':str(response),'request_hash':key,'server':server.url,'messages':len(messages)})
            print(json.dumps({'status':'waiting_for_policy','role':role,'turn':turn}),flush=True)
            deadline=time.monotonic()+args.wait_seconds
            while not response.exists():
                if time.monotonic()>deadline:raise TimeoutError('Policy handoff deadline; no automatic restart')
                time.sleep(.2)
            value=validate_response(packet,json.loads(response.read_text(encoding='utf-8')))
            requests.append({'role':role,'turn':turn,'request_hash':key,'response_hash':digest(value)})
            native=(UserMessage if role=='user' else AssistantMessage)(role=role,content=value['content'],
                **({'tool_calls':[ToolCall(id=f'call-{turn}',requestor=role,**c) for c in value['tool_calls']]} if value['tool_calls'] else {}))
            native_messages.append(native);messages.append(native.model_dump(mode='json'));publish()
            if role=='user':
                markers={'###STOP###':'user_stop','###TRANSFER###':'user_transfer','###OUT-OF-SCOPE###':'user_out_of_scope'}
                terminal=next((v for k,v in markers.items() if k in (value['content'] or '')),None)
                if terminal:break
                role='assistant';continue
            if value['tool_calls']:
                call=native.tool_calls[0];before=environment.get_db_hash();at=time.monotonic()
                actual=environment.get_response(call)
                calls.append({'turn':turn,'request':call.model_dump(mode='json'),'response':actual.model_dump(mode='json'),
                    'before':before,'after':environment.get_db_hash(),'elapsed_seconds':time.monotonic()-at})
                native_messages.append(actual);messages.append(actual.model_dump(mode='json'));publish()
                write(root/'executed-calls.json',calls)
            else:role='user'
        evaluation={};reward=None
        if terminal:
            for name,cls in [('environment',EnvironmentEvaluator),('communication',CommunicateEvaluator),('action',ActionEvaluator)]:
                result=cls.calculate_reward(get_environment,task,native_messages) if name=='environment' else cls.calculate_reward(task,native_messages)
                evaluation[name]=result.model_dump(mode='json')
            basis=task.evaluation_criteria.model_dump(mode='json')['reward_basis'];breakdown={}
            reward={'reward_basis':basis,'reward_breakdown':breakdown,'info':{'scope':'Native deterministic components; NL evaluator not executed; not a benchmark score'}}
            for part in evaluation.values():
                breakdown.update(part.get('reward_breakdown') or {})
                for field in ('db_check','env_assertions','communicate_checks','action_checks'):
                    if part.get(field) is not None:reward[field]=part[field]
            assert all(k in breakdown for k in basis)
            reward['reward']=math.prod(breakdown[k] for k in basis)
        run=publish('complete' if terminal else 'failed',terminal or 'turn_limit',reward)
        data=Workspace(server.db,experiment=experiment,observer='source')
        assert len(data.rollouts().rows)==1
        graph=data.graphs().rows
        result={'status':'completed' if terminal else 'turn_limit','run_id':run['id'],'experiment':experiment,
            'termination':terminal or 'turn_limit','requests':requests,'calls':calls,'prefixes':prefixes,
            'native_evaluation':evaluation,'reward':reward,'graphs':graph,
            'limits':origin,'usage':'Subagent usage counters unavailable. No claim of zero model cost.',
            'server':server.url,'database':str(server.db)}
        write(root/'report.json',result);write(root/'status.json',{'status':result['status'],'run_id':run['id']})
        print(json.dumps({'status':result['status'],'turns':len(requests),'tools':len(calls),'run_id':run['id']}),flush=True)
    except BaseException as exc:
        write(root/'status.json',{'status':'failed','error_type':type(exc).__name__,'messages':len(messages)})
        raise
    finally:server.stop()


if __name__=='__main__':main()
