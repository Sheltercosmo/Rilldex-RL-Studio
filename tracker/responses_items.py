"""Recorded Responses items, read without executing tools or fetching history."""
from copy import deepcopy
import json

from .schema import InputError, event

VERSION = 'responses-items/1'
CALLS = {'function_call', 'custom_tool_call'}
OUTPUTS = {'function_call_output': 'function_call', 'custom_tool_call_output': 'custom_tool_call'}


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip():raise InputError(field+' must be nonempty text')
    return value


def content(value, pointer, *, summary=False):
    if isinstance(value, str):return value, [], [{'source_pointer':pointer,'start':0,'end':len(value)}]
    if not isinstance(value, list):raise InputError(pointer+' must be text or content parts')
    texts, media, spans, offset = [], [], [], 0
    for i, part in enumerate(value):
        if not isinstance(part, dict) or not isinstance(part.get('type'),str):
            raise InputError(pointer+' contains an invalid content part')
        kind=part['type'];field='refusal' if kind=='refusal' else 'text'
        if kind in ({'summary_text'} if summary else {'input_text','output_text','text','refusal','reasoning_text'}):
            text=part.get(field)
            if not isinstance(text,str):raise InputError(pointer+f'/{i}/{field} must be text')
            if texts:offset+=1
            texts.append(text)
            spans.append({'source_pointer':pointer+f'/{i}/{field}','start':offset,'end':offset+len(text)})
            offset+=len(text)
        else:media.append(deepcopy(part))
    return '\n'.join(texts),media,spans


def definitions(document):
    tools=document.get('tools',[])
    if not isinstance(tools,list) or any(not isinstance(t,dict) for t in tools):
        raise InputError('tools must be a list of objects')
    result={}
    for i,tool in enumerate(tools):
        if tool.get('type') not in {'function','custom'}:continue
        name=nonempty(tool.get('name'),'tool name')
        if tool.get('namespace') is not None:nonempty(tool['namespace'],'tool namespace')
        # Namespaces distinguish tools with identical local names.
        key=(tool.get('namespace'),name)
        if key in result:raise InputError('Duplicate Responses tool definition')
        result[key]={'source_pointer':f'/tools/{i}','definition':deepcopy(tool),'source_format':VERSION}
    return result


def append_items(document, events, warnings):
    items=document.get('items')
    if not isinstance(items,list) or not items or any(not isinstance(i,dict) for i in items):
        raise InputError('responses-items/1 requires a nonempty items array')
    if any(k in document for k in ('messages','system','input','output')):
        raise InputError('Capture accumulated Responses items; put instructions in explicit system/developer items')
    declared=definitions(document);seen={};item_ids=set();call_group=None
    for i,item in enumerate(items):
        pointer=f'/items/{i}';kind=item.get('type','message' if 'role' in item else None)
        if not isinstance(kind,str):raise InputError(pointer+' requires a type or message role')
        native_id=item.get('id')
        if native_id is not None:
            nonempty(native_id,pointer+'/id')
            if native_id in item_ids:raise InputError('Duplicate Responses item ID in one recorded history')
            item_ids.add(native_id)
        common={'source_item_index':i,'source_item_type':kind}
        for field in ('id','status','namespace','caller'):
            if field in item:common['source_item_'+field]=deepcopy(item[field])
        if kind not in CALLS:call_group=None
        if kind=='message':
            role=item.get('role')
            if role not in {'user','assistant','system','developer'}:raise InputError('Unsupported Responses message role')
            text,media,spans=content(item.get('content'),pointer+'/content')
            row=event(events,kind={'user':'instruction','assistant':'message','system':'context','developer':'context'}[role],
                actor='agent' if role=='assistant' else role,text=text,pointer=pointer+'/content',
                source_role=role,source_text_parts=spans,media=media,**common)
            if role in {'system','developer'}:row['context_kind']='recorded_'+role+'_message'
        elif kind=='reasoning':
            # Summaries are recorded summaries, not reconstructed hidden thought.
            text,media,spans=content(item.get('summary',[]),pointer+'/summary',summary=True)
            if text or media:
                event(events,kind='message',actor='agent',text=text,pointer=pointer+'/summary',
                    channel='reasoning_summary',context_kind='recorded_reasoning_summary',
                    source_text_parts=spans,media=media,**common)
            if item.get('content'):
                text,media,spans=content(item['content'],pointer+'/content')
                event(events,kind='reasoning',actor='agent',text=text,pointer=pointer+'/content',
                    channel='recorded_reasoning',source_text_parts=spans,media=media,**common)
            if not text and not item.get('content'):
                event(events,kind='context',actor='context',text='',pointer=pointer,
                    context_kind='unobserved_reasoning',agent_visibility='not_established',**common)
            if item.get('encrypted_content'):
                warnings.append('Encrypted reasoning is retained in raw source and is not decoded or treated as readable thought.')
        elif kind in CALLS:
            cid=nonempty(item.get('call_id'),pointer+'/call_id');name=nonempty(item.get('name'),pointer+'/name')
            if item.get('namespace') is not None:nonempty(item['namespace'],pointer+'/namespace')
            if cid in seen:raise InputError('Duplicate Responses call ID in one recorded history')
            raw=item.get('arguments' if kind=='function_call' else 'input')
            if not isinstance(raw,str):raise InputError('Responses call arguments/input must be recorded text')
            if kind=='custom_tool_call':
                args={'input':raw};status='custom_text'
            else:
                try:
                    def invalid(value):raise ValueError(value)
                    args=json.loads(raw,parse_constant=invalid)
                    if not isinstance(args,dict):raise ValueError('not an object')
                    status='json_object'
                except ValueError:
                    args={'unparsed_arguments':raw};status='invalid_json_object'
                    warnings.append('Invalid generated arguments remain recorded attempts; their payload is preserved.')
            if call_group is None:call_group=i
            row=event(events,kind='action',actor='agent',text=f'{name}({raw})',pointer=pointer,
                tool=name,call_id=cid,arguments=args,raw_arguments=raw,argument_status=status,
                extraction='recorded-function-call' if kind=='function_call' else 'recorded-custom-tool-call',
                agent_visibility='model_authored',source_message_index=call_group,
                dispatch_group_basis='uninterrupted_recorded_call_items',**common)
            contract=declared.get((item.get('namespace'),name))
            if contract:row['tool_contract']=contract
            else:warnings.append('A called tool has no matching supplied definition.')
            seen[cid]=kind
        elif kind in OUTPUTS:
            cid=nonempty(item.get('call_id'),pointer+'/call_id')
            if cid in seen and seen[cid]!=OUTPUTS[kind]:raise InputError('Call/result types disagree for the same call ID')
            text,media,spans=content(item.get('output'),pointer+'/output')
            event(events,kind='feedback',actor='environment',text=text,pointer=pointer+'/output',
                source_call_id=cid,feedback_origin='environment',agent_visibility='recorded_agent_result',
                link_basis='Responses call_id',media=media,source_text_parts=spans,**common)
            if cid not in seen:warnings.append('A Responses output has no preceding captured call; it remains unlinked.')
        else:
            # Missing references/hosted tool internals are coverage gaps, never
            # made-up calls or messages containing encrypted provider payloads.
            event(events,kind='context',actor='context',text='',pointer=pointer,
                context_kind='uninterpreted_response_item',agent_visibility='not_established',
                action_extraction='no_structured_actions',**common)
            warnings.append(f'Responses item {kind} is preserved in raw source but not interpreted. Materialize referenced history or capture its native operation separately.')
    warnings.append('Responses array order records source order, not execution order among adjacent call requests. Message/call parentage is not inferred from proximity. API completion status is not task success.')
    if any(e.get('media') for e in events):warnings.append('Image/audio/file references are preserved; their contents have not been inspected.')


def document(items, *, tools=None, metadata=None, reward=None, success=None):
    return deepcopy({'trajectory_format':VERSION,'items':items,'tools':tools or [],
                     'metadata':metadata or {},'outcome':{'reward':reward,'success':success}})
