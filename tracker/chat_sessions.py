"""Several recorded agent contexts in one rollout, with local call identities.

Session array order is storage order, not a cross-agent execution timeline.
Each entry contains one explicit, agent-visible conversation and its own tools.
"""
from copy import deepcopy

from .chat_messages import append_messages
from .schema import InputError, content_text, event

VERSION = 'chat-messages/2'


def identifier(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise InputError(field + ' must be a nonempty string of at most 500 characters')
    return value


def append_sessions(document, events, warnings):
    sessions = document.get('sessions')
    if not isinstance(sessions, list) or not sessions or len(sessions) > 1000:
        raise InputError('chat-messages/2 requires 1–1000 sessions')
    if any(k in document for k in ('messages', 'tools', 'system')):
        raise InputError('Put messages, tools and system inside their recorded session')
    seen = set()
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise InputError('Each chat session must be an object')
        scope = {field: identifier(session.get(field), field) for field in ('trajectory_id', 'context_id')}
        key = tuple(scope.values())
        if key in seen:
            raise InputError('Duplicate agent/context pair; combine its messages into one session')
        seen.add(key)
        local = []
        if 'system' in session:
            text, media = content_text(session['system'])
            if text or media:
                event(local, kind='context', actor='system', text=text, media=media,
                      pointer='/system', context_kind='recorded_system_message')
        if session.get('trajectory_format') == 'responses-items/1':
            from .responses_items import append_items
            append_items(session,local,warnings)
        elif session.get('trajectory_format') not in (None,'chat-messages/1'):
            raise InputError('Unsupported session trajectory_format')
        else:
            if 'items' in session:raise InputError('Responses sessions require trajectory_format responses-items/1')
            append_messages(session, local, warnings, portable=True)
        base = f'/sessions/{index}'
        ids = {e['id']: f'e{len(events) + i + 1}' for i,e in enumerate(local)}
        for e in local:
            row = deepcopy(e)
            row.update(id=ids[e['id']], index=len(events), source_pointer=base + e['source_pointer'], **scope)
            if e.get('parent_id') is not None:
                row['parent_id'] = ids[e['parent_id']]
            if e.get('tool_contract'):
                row['tool_contract']['source_pointer'] = base + e['tool_contract']['source_pointer']
            for part in row.get('source_text_parts',[]):part['source_pointer']=base+part['source_pointer']
            events.append(row)
    warnings.append('Agent/context pairs have separate histories and tool definitions. Session order does not establish global execution order or communication between agents. Shared information must be recorded in each receiving context.')


def document(sessions, *, metadata=None, reward=None, success=None):
    """Bundle explicit conversations; no framework objects or implicit sharing."""
    return deepcopy({'trajectory_format': VERSION, 'sessions': sessions,
                     'metadata': metadata or {}, 'outcome': {'reward': reward, 'success': success}})
