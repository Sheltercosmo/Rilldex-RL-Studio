"""Native text-mode tau-bench results, with explicit participant visibility.

Bundle projections preserve one exact simulation and its relevant task/config,
plus the original collection hash and index. No private simulator/evaluator
fields enter agent-visible events. Voice/tick streams need a separate adapter.
"""
from collections import defaultdict
import math

from .schema import InputError, digest, dumps, event

VERSION='tau-bench/1'
USER_TERMINATION_MARKERS=('###STOP###','###TRANSFER###','###OUT-OF-SCOPE###')


def text_only(message):
    if message.get('is_audio') or message.get('audio_content') or message.get('audio_path') or message.get('chunk_id') is not None:
        raise InputError('tau-bench audio/chunk messages require a dedicated adapter; transcript text is not full audio evidence')


def matches(doc):
    if doc.get('trajectory_format') and doc['trajectory_format']!=VERSION:return False
    return doc.get('trajectory_format')==VERSION or all(k in doc for k in ('info','tasks','simulations')) or all(k in doc for k in ('id','task_id','termination_reason','messages'))


def split(document):
    """Avoid copying the whole multi-rollout collection into every source row."""
    if 'simulations' not in document:return [document]
    simulations=document['simulations'];tasks=document.get('tasks');info=document.get('info')
    if not isinstance(simulations,list) or not simulations:raise InputError('tau-bench results need nonempty simulations; directory manifests and voice ticks require an explicit loader')
    if not isinstance(tasks,list) or not isinstance(info,dict):raise InputError('tau-bench results require tasks and info')
    by_task={};task_indices={}
    for index,task in enumerate(tasks):
        if not isinstance(task,dict) or not isinstance(task.get('id'),str) or task['id'] in by_task:raise InputError('tau-bench task IDs must be unique strings')
        by_task[task['id']]=task
        task_indices[task['id']]=index
    identifiers=set();result=[];collection_hash=digest(document)
    for i,sim in enumerate(simulations):
        if not isinstance(sim,dict) or not isinstance(sim.get('id'),str) or not sim['id'] or sim['id'] in identifiers:raise InputError('tau-bench simulation IDs must be unique nonempty strings')
        identifiers.add(sim['id'])
        if sim.get('task_id') not in by_task:raise InputError('tau-bench simulation references a missing task')
        result.append({'trajectory_format':VERSION,'simulation':sim,'info':info,'task':by_task[sim['task_id']],
            'source_origin':{'collection_sha256':collection_hash,'simulation_pointer':f'/simulations/{i}',
                             'task_pointer':f"/tasks/{task_indices[sim['task_id']]}",
                             'projection':'exact simulation and matching task; shared info; unrelated simulations omitted'}})
    return result


def append_events(doc,events,warnings,meta):
    envelope=doc.get('trajectory_format')==VERSION
    sim=doc.get('simulation') if envelope else doc;prefix='/simulation' if envelope else ''
    if not isinstance(sim,dict):raise InputError('tau-bench envelope needs simulation')
    for k in ('id','task_id','termination_reason'):
        if not isinstance(sim.get(k),str) or not sim[k]:raise InputError('tau-bench simulation requires '+k)
    if sim.get('ticks') or sim.get('mode') not in (None,'half_duplex'):
        raise InputError('tau-bench voice/full-duplex ticks are not text-mode conversations; use a dedicated adapter')
    messages=sim.get('messages')
    if not isinstance(messages,list) or not messages:raise InputError('tau-bench simulation requires recorded messages')
    info=doc.get('info',{}) if envelope else {}
    if not isinstance(info,dict):raise InputError('tau-bench info must be an object')
    env=info.get('environment_info') or {};agent=info.get('agent_info') or {}
    if not isinstance(env,dict) or not isinstance(agent,dict):raise InputError('tau-bench environment/agent info must be objects')
    domain=env.get('domain_name')
    if domain is not None and (not isinstance(domain,str) or not domain):raise InputError('tau-bench domain_name must be nonempty text')
    if envelope and 'task' in doc and (not isinstance(doc['task'],dict) or doc['task'].get('id')!=sim['task_id']):raise InputError('tau-bench task does not match simulation task_id')
    derived={'task_id':sim['task_id'],'sample_id':sim['id'],'environment':'tau-bench/'+domain if domain else None,
             'environment_family':'tool_and_business_workflows','environment_version':info.get('git_commit'),
             'model':agent.get('llm'),'trial':sim.get('trial'),'seed':sim.get('seed'),'source_collection':'tau-bench'}
    for key,value in derived.items():
        if value is not None:
            if key in meta and str(meta[key])!=str(value):raise InputError('Metadata conflicts with recorded tau-bench '+key)
            meta[key]=value
    meta.setdefault('environment','tau-bench/unrecorded')
    if envelope and 'task' in doc:meta.setdefault('task_record_sha256',digest(doc['task']))
    if info.get('git_commit'):meta.setdefault('task_revision',info['git_commit'])
    if info.get('git_commit'):meta.setdefault('reward_definition','tau-bench evaluator@'+info['git_commit'])
    if envelope and doc.get('source_origin'):meta['source_origin']=doc['source_origin']
    policy=env.get('policy')
    if policy is not None:
        if not isinstance(policy,str):raise InputError('tau-bench policy must be recorded text')
        event(events,kind='context',actor='context',text=policy,pointer='/info/environment_info/policy',context_kind='recorded_environment_policy')
    definitions={}
    tools=env.get('tool_defs') or []
    if not isinstance(tools,list):raise InputError('tau-bench tool_defs must be a list or null')
    for i,tool in enumerate(tools):
        if not isinstance(tool,dict) or not isinstance(tool.get('function'),dict) or not isinstance(tool['function'].get('name'),str) or not tool['function']['name']:raise InputError('Unsupported tau-bench tool definition shape')
        if tool['function']['name'] in definitions:raise InputError('Duplicate tau-bench tool definition name')
        definitions[tool['function']['name']]={'definition':tool,'source_pointer':f'/info/environment_info/tool_defs/{i}'}
    pending=defaultdict(list)

    def feedback(m,pointer,container_index):
        text_only(m)
        who=m.get('requestor','assistant');cid=m.get('id');text=m.get('content')
        if who not in {'assistant','user'} or not isinstance(cid,str) or text is not None and not isinstance(text,str):raise InputError('Malformed tau-bench tool response')
        if 'error' in m and type(m['error']) is not bool:raise InputError('tau-bench tool error flag must be boolean')
        targets=pending.get((who,cid),[]) if cid else []
        target=targets[0] if len(targets)==1 else None
        if target:pending.pop((who,cid))
        else:warnings.append('A native tool response has missing or ambiguous call identity; it remains unlinked.')
        event(events,kind='feedback' if who=='assistant' else 'external_feedback',actor='environment',text=text or '',pointer=pointer+'/content',
            source_call_id=target['call_id'] if target else None,native_call_id=cid,requestor=who,
            source_message_index=container_index,source_role='tool',reported_tool_error=m.get('error'),
            agent_visibility='recorded_agent_result' if who=='assistant' else 'not_established',feedback_origin='environment',
            link_basis='native tau-bench requestor and pending call ID')

    for i,m in enumerate(messages):
        p=f'{prefix}/messages/{i}'
        if not isinstance(m,dict):raise InputError('tau-bench messages must be objects')
        text_only(m)
        role=m.get('role')
        if role=='tool':
            if 'tool_messages' in m:
                rows=m['tool_messages']
                if not isinstance(rows,list) or any(not isinstance(r,dict) or r.get('role')!='tool' for r in rows):raise InputError('Malformed MultiToolMessage')
                for j,row in enumerate(rows):feedback(row,p+f'/tool_messages/{j}',i)
            else:feedback(m,p,i)
            continue
        if role not in {'system','assistant','user'}:raise InputError('Unsupported tau-bench role at '+p)
        text=m.get('content');calls=m.get('tool_calls') or []
        if text is not None and not isinstance(text,str) or not isinstance(calls,list):raise InputError('Unsupported tau-bench message shape')
        # Native tau2 UserSimulator.is_stop consumes these control markers. Keep
        # exact source text/pointers, but do not annotate a bare marker as work.
        # Mixed natural text remains a contribution; user tool calls and other
        # speakers do not trigger the native user-termination rule.
        markers=[marker for marker in USER_TERMINATION_MARKERS if marker in (text or '')] if role=='user' and not calls else []
        non_control_text=text or ''
        for marker in markers:non_control_text=non_control_text.replace(marker,'')
        control=bool(markers) and not non_control_text.strip()
        parent=event(events,kind='control' if control else 'external_message' if role=='user' and calls else {'system':'context','user':'instruction','assistant':'message'}[role],
            actor='agent' if role=='assistant' else role,text=text or '',pointer=p+'/content',source_message_index=i,source_role=role)
        if markers:parent.update(protocol_markers=markers,protocol_basis='native tau2 text-user termination rule')
        for j,call in enumerate(calls):
            if not isinstance(call,dict) or not isinstance(call.get('name'),str) or not call['name'] or not isinstance(call.get('arguments'),dict):raise InputError('Malformed native tau-bench tool call')
            who=call.get('requestor','assistant');cid=call.get('id','')
            if who!=role or not isinstance(cid,str):raise InputError('tau-bench call requestor conflicts with message role')
            cp=p+f'/tool_calls/{j}';identity=f'{who}:{cid}@{cp}' if cid else None
            action=event(events,kind='action' if who=='assistant' else 'external_action',actor='agent' if who=='assistant' else 'user',
                text=call['name']+'('+dumps(call['arguments'])+')',pointer=cp,tool=call['name'],arguments=call['arguments'],
                native_call_id=cid,call_id=identity,parent_id=parent['id'],requestor=who,source_message_index=i,
                agent_visibility='model_authored' if who=='assistant' else 'not_established',extraction='native-tau-tool-call')
            if cid:pending[(who,cid)].append(action)
            else:warnings.append('A native tool call lacks an ID; linkage remains unknown.')
            if call['name'] in definitions and who=='assistant':action['tool_contract']=definitions[call['name']]
    reward_info=sim.get('reward_info')
    if reward_info is not None and not isinstance(reward_info,dict):raise InputError('tau-bench reward_info must be an object or null')
    reward=(reward_info or {}).get('reward')
    if reward is not None and (isinstance(reward,bool) or not isinstance(reward,(int,float)) or not math.isfinite(reward)):raise InputError('tau-bench reward must be finite or null')
    warnings.extend(['Native text simulation: private user instructions, initial hidden state, raw provider data and evaluator judgments stay outside agent-visible evidence.',
        'Native user-side tools are external events. Their responses are not assistant knowledge; later spoken user messages are observable claims.',
        'Trial/seed/timestamps are evaluation provenance, not training steps or generating policy versions. Reward is a recorded score, not independent success.'])
    if not tools:warnings.append('No native tool definitions were supplied; names/arguments do not establish full tool semantics.')
    return {'termination':sim['termination_reason'],'recorded_reward':reward,'recorded_reward_pointer':prefix+'/reward_info/reward',
            'native_simulation_id':sim['id']}
