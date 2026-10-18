"""Readable, source-bound context for diagnostic selections.

Only native JSON structure supplies roles. Strings containing JSON/role markers
are not promoted to messages. This view complements, never rewrites, citations.
"""
import json

from .schema import dumps

VERSION = 'diagnostic-context/1'
TASK_LIMIT = 10000
RECORD_LIMIT = 12000
TEXT_FIELDS = ('text', 'content', 'msg')
ACTORS = {'agent', 'assistant', 'user', 'system', 'developer', 'tool', 'environment'}
WRAPPERS = {'inputs', 'output', 'messages', 'events', 'choices', 'message'}


def records(source):
    """Locate native message objects with exact serialized offsets and scope."""
    text = source['trace']
    try: parsed = json.loads(text)
    except (ValueError, TypeError): return []
    if not isinstance(parsed, list): return []
    decoder = json.JSONDecoder(); result = []

    def skip(pos):
        while pos < len(text) and (text[pos].isspace() or text[pos] in ',:'): pos += 1
        return pos

    def walk(value, start, end, path, scope):
        if isinstance(value, dict):
            actor = value.get('actor', value.get('role', value.get('src')))
            if actor in ACTORS:
                content = value.get('content')
                native_result = (isinstance(content, list) and any(isinstance(p, dict) and p.get('type') == 'tool_result' for p in content))
                kind = value.get('kind') or ('feedback' if native_result or actor in {'tool', 'environment'} else 'message')
                # The outer src=agent object may include feedback, but its msg
                # and tools stay an agent record and obs stays returned data.
                result.append(dict(id=f'record:{start}:{end}', start=start, end=end,
                    path=list(path), scope=list(scope), actor=actor, kind=kind,
                    event_id=value.get('id', value.get('step')), value=value))
                return
            cursor = skip(start + 1)
            while cursor < end - 1:
                key, cursor = decoder.raw_decode(text, cursor); cursor = skip(cursor)
                child, stop = decoder.raw_decode(text, cursor)
                if key in WRAPPERS:
                    child_scope = (*path, key) if key == 'inputs' else scope
                    # Inference-call output belongs with the inputs of that
                    # same envelope, never with a neighboring inference call.
                    if key == 'output' and 'inputs' in value: child_scope = (*path, 'inputs')
                    walk(child, cursor, stop, (*path, key), child_scope)
                cursor = skip(stop)
        elif isinstance(value, list):
            cursor = skip(start + 1)
            for i, child in enumerate(value):
                _, stop = decoder.raw_decode(text, cursor)
                walk(child, cursor, stop, (*path, i), scope); cursor = skip(stop)
    try: walk(parsed, text.index('['), len(text.rstrip()), (), ())
    except (ValueError, TypeError, IndexError): return []
    return result


def readable(record):
    value = record['value']; body = {}
    for key in TEXT_FIELDS:
        if key not in value: continue
        # A native content-block array retains tool_use/tool_result structure.
        # We do not reinterpret its embedded text as another conversation.
        if isinstance(value[key], (str, list)): body[key] = value[key]
    for key in ('tool', 'arguments', 'tool_calls', 'tools', 'obs', 'call_id', 'source_call_id', 'tool_call_id'):
        if key in value: body[key] = value[key]
    return dict(id=record['id'], actor=record['actor'], kind=record['kind'],
        source=dict(origin='trace', start=record['start'], end=record['end'], path=record['path']), **body)


def packet(source, fragments, *, indexed=None):
    """Attach coherent task text and complete records within fixed budgets.

    Later user messages in role-only transcripts are ambiguous (often tool
    feedback). Only initial user messages or explicit instruction-kind events
    enter task context. Conversation/call envelopes remain separate.
    """
    indexed = records(source) if indexed is None else indexed
    trace = [f for f in fragments if f['origin'] == 'trace']
    overlaps = [r for r in indexed if any(r['start'] < f['end'] and r['end'] > f['start'] for f in trace)]
    scopes = {tuple(r['scope']) for r in overlaps}
    cutoff = max((r['end'] for r in overlaps), default=0)
    first_agent = {}
    for r in indexed:
        if r['actor'] in {'assistant', 'agent'}: first_agent.setdefault(tuple(r['scope']), r['start'])
    instructions = []
    for r in indexed:
        scope = tuple(r['scope'])
        if scope not in scopes or r['start'] > cutoff or r['kind'] in {'feedback', 'tool_result'}: continue
        if r['actor'] not in {'user', 'system', 'developer'}: continue
        if r['actor'] == 'user' and r['kind'] != 'instruction' and r['start'] >= first_agent.get(scope, float('inf')): continue
        instructions.append(r)
    # Prioritize the actual user task over a long generic system/tool manual.
    instructions.sort(key=lambda r:(r['actor'] != 'user', r['start']))
    task, selected, omitted, used = [], [], [], 0
    for r in instructions:
        view = readable(r); cost = len(dumps(view))
        if used + cost > TASK_LIMIT:
            omitted.append(r['id']); continue
        task.append(view); used += cost
    # Preserve complete enclosing records for selected partial source ranges.
    # This establishes where the action was dispatched without treating another
    # record's operation as belonging to the selected fragment.
    incomplete, used = [], 0
    for r in overlaps:
        view = readable(r)
        view['selected_fragment_ids'] = [f['id'] for f in trace if r['start'] < f['end'] and r['end'] > f['start']]
        cost = len(dumps(view))
        if used + cost > RECORD_LIMIT:
            incomplete.append(r['id']); continue
        selected.append(view); used += cost
    return dict(schema=VERSION, task_context=task, enclosing_records=selected,
        omitted_instruction_records=omitted, omitted_enclosing_records=incomplete,
        scope='Native structure and decoded fields only. No inferred permissions, purposes or hidden outcomes.')


def task(source, fragments, *, indexed=None):
    """Return the complete recorded user instructions for one native scope.

    The caller adds this readable field without merging returned tool text or
    other conversations into instructions. Unsupported/oversized instructions
    remain in the original source; we never call a truncated prefix complete.
    """
    indexed = records(source) if indexed is None else indexed
    trace = [f for f in fragments if f['origin'] == 'trace']
    overlaps = [r for r in indexed if any(r['start'] < f['end'] and r['end'] > f['start'] for f in trace)]
    scopes = {tuple(r['scope']) for r in overlaps}
    if len(scopes) != 1: return None
    anchors = [r for r in overlaps if r['actor'] in {'agent','assistant'}]
    if not anchors: return None
    cutoff = min(r['start'] for r in anchors)
    # The shared task field must already apply to the earliest selectable agent
    # record. Later instructions remain visible in their source positions.
    view = packet(source, fragments, indexed=indexed)
    task_records = [r for r in view['task_context'] if r['actor'] == 'user' and r['source']['end'] <= cutoff]
    if not task_records: return None
    # If even one applicable user instruction was omitted, this cannot be
    # represented as a complete task, regardless of other instructions fitting.
    omitted = set(view['omitted_instruction_records'])
    if any(r['id'] in omitted and r['actor'] == 'user' and r['end'] <= cutoff for r in indexed): return None
    texts = []
    for r in task_records:
        value = next((r[k] for k in TEXT_FIELDS if isinstance(r.get(k), str)), None)
        if value is None:
            blocks = r.get('content')
            if not isinstance(blocks,list) or not blocks or not all(isinstance(b,dict) and b.get('type')=='text' and isinstance(b.get('text'),str) for b in blocks): return None
            value = '\n'.join(b['text'] for b in blocks)
        texts.append(value)
    if len(task_records) == 1:
        return dict(text=texts[0], source=task_records[0]['source'])
    return dict(text='\n\n'.join(f'Recorded user instruction {i+1}:\n{text}' for i,text in enumerate(texts)),
                sources=[r['source'] for r in task_records])
