"""mini-SWE-agent v2 saved messages: parsed actions, native outputs and exits.

No command execution. Parsed action lists are requests, not proof that every
action ran: submission can interrupt a batch before its later actions execute.
"""
from .schema import InputError, content_text, event

VERSION = 'mini-swe-agent/3'


def is_v2(doc):
    version = str((doc.get('info') or {}).get('mini_version', ''))
    for i, message in enumerate(doc.get('messages', [])):
        if not isinstance(message.get('extra') or {}, dict): raise InputError(f'/messages/{i}/extra must be an object')
    return version.split('.')[0].isdigit() and int(version.split('.')[0]) >= 2 or any(
        isinstance(m, dict) and ('actions' in (m.get('extra') or {}) or m.get('role') in {'tool', 'exit'}
                                or m.get('object') == 'response' or m.get('type') == 'function_call_output')
        for m in doc.get('messages', []))


def _content(value):
    # Native Responses API text parts have input_text/output_text names.
    if isinstance(value, list):
        value = [dict(p, type='text') if isinstance(p, dict) and p.get('type') in {'input_text', 'output_text'} else p for p in value]
    return content_text(value)


def append_events(doc, events, warnings):
    pending = []; native = {}; consumed = set()
    for i, row in enumerate(doc.get('messages', [])):
        p = f'/messages/{i}'; extra = row.get('extra') or {}
        if not isinstance(extra, dict): raise InputError(p + '/extra must be an object')
        role = row.get('role'); response = row.get('object') == 'response'
        if response:
            items = row.get('output')
            if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
                raise InputError(p + '/output must contain response items')
            parts = [part for item in items if item.get('type') == 'message' for part in item.get('content', [])]
            text, media = _content(parts); pointer = p + '/output'
        else:
            key = 'output' if row.get('type') == 'function_call_output' else 'content'
            text, media = _content(row.get(key)); pointer = p + '/' + key
        if role == 'assistant' or response:
            pending = []
            parent = event(events, kind='message', text=text, pointer=pointer, media=media,
                           native_message_extra=extra)
            actions = extra.get('actions', [])
            if not isinstance(actions, list) or any(not isinstance(a, dict) or not isinstance(a.get('command'), str) for a in actions):
                raise InputError(p + '/extra/actions must contain parsed command objects')
            if not actions and (row.get('tool_calls') or response and any(x.get('type') == 'function_call' for x in items)):
                warnings.append('Native tool requests without parsed extra.actions remain unbound; dispatch is not guessed.')
            for j, action in enumerate(actions):
                cid = f'mini:{i}:{j}'; native_id = action.get('tool_call_id')
                if native_id is not None:
                    if not isinstance(native_id, str) or not native_id or native_id in native:
                        raise InputError('Native tool call identities must be unique nonempty strings')
                    native[native_id] = cid
                pending.append(cid)
                event(events, kind='action', text=action['command'], pointer=p+f'/extra/actions/{j}',
                      call_id=cid, native_call_id=native_id, tool='shell', parent_id=parent['id'],
                      arguments={k: v for k, v in action.items() if k != 'tool_call_id'},
                      extraction='native-parsed-action', execution='not_established')
        elif role == 'tool' or row.get('type') == 'function_call_output' or role == 'user' and ('raw_output' in extra or 'returncode' in extra):
            native_id = row.get('tool_call_id') if role == 'tool' else row.get('call_id')
            # Positional binding is the native text formatter's ordered output contract.
            # Interrupt/format-error messages are not output records and never consume it.
            if native_id is not None:
                cid = native.get(native_id) if isinstance(native_id, str) else None
                if cid not in pending: cid = None
            else:
                cid = next((key for key in pending if key not in consumed), None) if role == 'user' else None
            if cid in consumed: raise InputError('Duplicate native tool result')
            if cid: consumed.add(cid)
            else: warnings.append('Native output has no unambiguous current action; result remains unlinked.')
            event(events, kind='feedback', text=text, pointer=pointer, actor='environment', media=media,
                  source_call_id=cid, native_call_id=native_id, returncode=extra.get('returncode'),
                  exception_info=extra.get('exception_info'), native_result=extra,
                  execution='not_executed' if extra.get('exception_info') == 'action was not executed' else 'result_recorded')
        elif role == 'exit':
            submitted = extra.get('exit_status') == 'Submitted'
            event(events, kind='message' if submitted else 'context', text=text, pointer=pointer,
                  actor='agent' if submitted else 'environment', media=media, termination=extra)
            pending = []
        elif extra.get('interrupt_type'):
            event(events, kind='feedback', text=text, pointer=pointer, actor='environment', media=media,
                  source_call_id=None, interruption=extra)
            pending = []
        elif role in {'system', 'user'}:
            event(events, kind='instruction', text=text, pointer=pointer, actor=role, media=media)
            pending = []
        else:
            raise InputError(p + ': unsupported native message kind; preserve the source and add an explicit adapter')
