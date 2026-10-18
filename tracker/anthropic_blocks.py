"""Recorded Anthropic content blocks within the shared messages adapter."""
from .schema import InputError, content_text, dumps, event

VERSION = 'chat-messages/anthropic-1'
NATIVE_TYPES = {'tool_use', 'tool_result', 'thinking', 'redacted_thinking'}


def native(messages):
    if not isinstance(messages, list): return False
    return any(isinstance(m, dict) and isinstance(m.get('content'), list) and
               any(isinstance(p, dict) and p.get('type') in NATIVE_TYPES for p in m['content'])
               for m in messages)


def append(message, events, warnings, pointer, common, seen_calls, definitions):
    """Separate visible text, thoughts, dispatches and returned tool results.

    A user message can carry a tool result and an instruction in separate blocks.
    Nested tool-looking text inside that result is never parsed into an action.
    """
    role = message['role']
    parts = message['content']
    if role not in {'user', 'assistant'}:
        raise InputError('Native tool/thinking blocks require an assistant or user message')
    if message.get('tool_calls') is not None and message['tool_calls'] != []:
        raise InputError('A message cannot combine native content calls with OpenAI tool_calls')
    parent = None
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or not isinstance(part.get('type'), str):
            raise InputError('Native content blocks require an explicit type')
        kind = part['type']; origin = f'{pointer}/content/{index}'
        if kind == 'tool_use':
            if role != 'assistant': raise InputError('A native tool_use requires assistant attribution')
            cid, name, raw = part.get('id'), part.get('name'), part.get('input')
            if not isinstance(name, str) or not name.strip(): raise InputError('A native tool_use requires a tool name')
            if cid is not None and (not isinstance(cid, str) or not cid or cid in seen_calls):
                raise InputError('Native tool call identifiers must be nonempty and unique')
            if cid is None: warnings.append('A tool call has no native ID; its result linkage is unestablished.')
            else: seen_calls[cid] = 'assistant'
            valid = isinstance(raw, dict)
            caller = part.get('caller')
            visibility = 'model_authored' if caller is None or isinstance(caller,dict) and caller.get('type')=='direct' else 'recorded_programmatic_call'
            action = event(events, kind='action', actor='agent', text=name + '(' + dumps(raw) + ')',
                pointer=origin, call_id=cid, native_call_id=cid, tool=name,
                arguments=raw if valid else {'unparsed_arguments': raw}, raw_arguments=raw,
                argument_status='json_object' if valid else 'invalid_json_object',
                parent_id=parent['id'] if parent else None, extraction='recorded-native-tool-use',
                agent_visibility=visibility, **common)
            for field in ('caller','toolset_name'):
                if field in part: action['native_'+field] = part[field]
            if not valid: warnings.append('A native tool call has invalid object arguments; its attempted payload is preserved.')
            if name in definitions: action['tool_contract'] = definitions[name]
        elif kind == 'tool_result':
            if role != 'user': raise InputError('A native tool_result requires user-message transport attribution')
            cid = part.get('tool_use_id')
            if cid is not None and (not isinstance(cid, str) or not cid): raise InputError('Invalid native tool result identifier')
            text, media = content_text(part.get('content'))
            linked = cid in seen_calls if cid is not None else False
            if not linked: warnings.append('A tool result has no preceding source call; it remains unlinked.')
            if 'is_error' in part and type(part['is_error']) is not bool: raise InputError('tool_result.is_error must be boolean')
            event(events, kind='feedback', actor='environment', text=text, media=media,
                pointer=origin + '/content', source_call_id=cid, native_call_id=cid,
                feedback_origin='environment', requestor='assistant',
                agent_visibility='recorded_agent_result',
                **({'is_error': part['is_error']} if 'is_error' in part else {}), **common)
            if media: warnings.append('Media references are preserved; image/audio contents have not been inspected.')
        elif kind == 'thinking':
            if role != 'assistant' or not isinstance(part.get('thinking'), str):
                raise InputError('Recorded thinking requires assistant text')
            event(events, kind='reasoning', actor='agent', text=part['thinking'], pointer=origin + '/thinking', **common)
        elif kind == 'text':
            if not isinstance(part.get('text'), str): raise InputError('Text blocks require text')
            if part['text']:
                parent = event(events, kind='message' if role == 'assistant' else 'instruction',
                    actor='agent' if role == 'assistant' else 'user', text=part['text'], pointer=origin + '/text', **common)
        else:
            # Unknown/redacted/media blocks stay visible as uninspected source.
            event(events, kind='context', actor='agent' if role == 'assistant' else 'user', text='',
                  pointer=origin, media=[part], context_kind='uninspected_content_block', **common)
            warnings.append('Non-text or redacted content is preserved without inferring its contents.')
