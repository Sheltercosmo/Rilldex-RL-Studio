"""Offline Weave call exports: native nesting and model outputs, without replay.

One (project_id, trace_id) is one imported snapshot. Input messages are copied
context, not fresh actions. Instrumented calls are not agent tool requests.
"""
from collections import defaultdict
from datetime import datetime
import json
from urllib.parse import quote

from .schema import SCHEMA_VERSION, InputError, digest, dumps, event, metadata

VERSION = 'weave-calls/1'
MAX_CALLS = 50_000


def import_revision(connection, run):
    """Plan a native trace revision inside the caller's write transaction."""
    producer = 'weave-import/' + digest(run['metadata']['source_project_id'])[:24]
    rollout = run['metadata']['source_trace_id']
    previous = connection.execute('''SELECT r.*,s.document FROM rollout_revisions r
        JOIN runs s ON s.id=r.run_id WHERE producer=? AND rollout_id=?
        ORDER BY revision DESC LIMIT 1''', (producer,rollout)).fetchone()
    known = connection.execute('SELECT run_id FROM rollout_revisions WHERE producer=? AND rollout_id=? AND run_id=?',
                               (producer,rollout,run['id'])).fetchone()
    if known:
        return {'reuse':known['run_id']}
    if previous:
        old = {c['id']:c for c in json.loads(previous['document'])['raw']['calls']}
        new = {c['id']:c for c in run['raw']['calls']}
        if new.keys() < old.keys() and all(old[k] == v for k,v in new.items()):
            return {'reuse':previous['run_id']}
        if not old.keys() <= new.keys():
            raise InputError('This Weave export omits previously imported calls. Export the full trace to update it; no rollout was replaced.')
        for identifier, call in old.items():
            current = new[identifier]
            fields = ['project_id','trace_id','parent_id','op_name','started_at','inputs']
            if call.get('ended_at'):
                fields += ['ended_at','output','exception']
            if any(call.get(k) != current.get(k) for k in fields):
                raise InputError('This Weave export changes previously recorded call inputs or a finished result. Use an explicitly versioned ingestion envelope for source corrections.')
    calls = run['raw']['calls']
    capture = run['metadata']['weave_capture']
    roots = [c for c in calls if not c.get('parent_id')]
    complete = len(roots)==1 and roots[0].get('ended_at') and not capture['unfinished_calls'] and not capture['missing_parent_ids']
    return {'producer':producer, 'rollout_id':rollout, 'revision':previous['revision']+1 if previous else 0,
            'state':('failed' if roots[0].get('exception') else 'complete') if complete else 'in_progress'}


def is_call(value):
    return isinstance(value, dict) and all(k in value for k in
        ('id', 'project_id', 'trace_id', 'op_name', 'started_at', 'inputs'))


def matches(value):
    if isinstance(value, list):
        return bool(value) and is_call(value[0])
    return isinstance(value, dict) and (is_call(value) or
        value.get('trajectory_format') == VERSION or
        isinstance(value.get('calls'), list) and bool(value['calls']) and is_call(value['calls'][0]))


def _stamp(value, path):
    if not isinstance(value, str):
        raise InputError(f'{path} must be an ISO timestamp with a timezone')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError('missing timezone')
        return parsed
    except ValueError as exc:
        raise InputError(f'{path} must be an ISO timestamp with a timezone') from exc


def _validate(call):
    if not isinstance(call, dict):
        raise InputError('Each Weave call must be an object')
    for key in ('id', 'project_id', 'trace_id', 'op_name'):
        if not isinstance(call.get(key), str) or not call[key].strip():
            raise InputError(f'Weave call requires {key}')
    for key in ('parent_id', 'thread_id', 'turn_id', 'wb_run_id', 'exception'):
        if call.get(key) is not None and not isinstance(call[key], str):
            raise InputError(f'Weave {key} must be text or null')
    for key in ('inputs', 'attributes'):
        if not isinstance(call.get(key), dict):
            raise InputError(f'Weave {key} must be an object; export full call records')
    for key in ('wb_run_step', 'wb_run_step_end'):
        if call.get(key) is not None and (type(call[key]) is not int or call[key] < 0):
            raise InputError(f'Weave {key} must be a nonnegative integer or null')
    start = _stamp(call.get('started_at'), 'started_at')
    if call.get('ended_at') is not None and _stamp(call['ended_at'], 'ended_at') < start:
        raise InputError('Weave call ended_at precedes started_at')
    digest(call)  # Reject non-finite numbers before any database write.


def _url(project, call_id):
    parts = project.split('/')
    if len(parts) != 2 or not all(parts):
        return None
    return 'https://wandb.ai/' + '/'.join(quote(p, safe='') for p in parts) + '/weave/calls/' + quote(call_id, safe='')


def _check_tree(calls):
    parents = {c['id']: c.get('parent_id') for c in calls}
    done = set()
    for identifier in parents:
        path = set()
        current = identifier
        while current in parents and current not in done:
            if current in path:
                raise InputError('Weave parent_id links contain a cycle')
            path.add(current)
            current = parents[current]
        done.update(path)


def _kind(call):
    weave = call.get('attributes', {}).get('weave')
    return weave.get('kind') if isinstance(weave, dict) else None


def _model_call(call):
    name = call['op_name'].rsplit('/op/', 1)[-1].split(':', 1)[0]
    return _kind(call) == 'llm' or name in {
        'openai.chat.completions.create', 'openai.chat.completions.parse',
        'anthropic.Messages.create', 'anthropic.AsyncMessages.create',
        'anthropic.Messages.stream', 'anthropic.AsyncMessages.stream'}


def normalize(document, meta=None, sources=None):
    if isinstance(document, list):
        calls, supplied = document, {}
    elif is_call(document):
        calls, supplied = [document], {}
    elif isinstance(document, dict):
        if document.get('trajectory_format') not in (None, VERSION):
            raise InputError('Unsupported Weave export version')
        calls, supplied = document.get('calls'), document.get('metadata', {})
    else:
        raise InputError('Supply a Weave call, calls array, or calls export object')
    if not isinstance(supplied, dict):
        raise InputError('Weave export metadata must be an object')
    if not isinstance(calls, list) or not calls or len(calls) > MAX_CALLS:
        raise InputError(f'Weave export needs 1–{MAX_CALLS:,} calls')
    unique, groups = {}, defaultdict(list)
    for call in calls:
        _validate(call)
        key = call['project_id'], call['id']
        if key in unique:
            if unique[key] != call:
                raise InputError('Conflicting Weave records share a call ID; export one current snapshot per call')
            continue
        unique[key] = call
        groups[call['project_id'], call['trace_id']].append(call)
    # Validate all groups before returning anything to the ingest transaction.
    for calls in groups.values():
        _check_tree(calls)
        for call in calls:
            parent = unique.get((call['project_id'], call.get('parent_id')))
            if parent and parent['trace_id'] != call['trace_id']:
                raise InputError('Weave parent call belongs to another trace')
    from .context import attach
    return [attach(_trace(sorted(calls, key=lambda c: (_stamp(c['started_at'], 'started_at'), c['id'])),
                          metadata({**supplied, **(meta or {})})), sources)
            for _, calls in sorted(groups.items())]


def _messages(messages, pointer, events, warnings, common, *, copied, tools=None):
    """Reuse chat decoding while rebasing every retained pointer into the export."""
    from .chat_messages import append_messages
    pending, notices = [], []
    try:
        append_messages({'messages': messages, 'tools': tools or []}, pending, notices, portable=True)
    except (InputError, TypeError, KeyError, ValueError) as exc:
        warnings.append(f'A message payload remains a source record: {exc}')
        return False
    ids = {e['id']: f'e{len(events)+i+1}' for i, e in enumerate(pending)}
    for item in pending:
        item = dict(item)
        item['id'] = ids[item['id']]
        item['index'] = len(events)
        if item.get('parent_id'):
            item['parent_id'] = ids[item['parent_id']]
        item['source_pointer'] = pointer + item['source_pointer'].removeprefix('/messages')
        # Tool declarations refer to the same native inputs, not this temporary document.
        if item.get('tool_contract'):
            item['tool_contract'] = {**item['tool_contract'], 'source_pointer': common['call_pointer'] + '/inputs' + item['tool_contract']['source_pointer']}
        item.update(common, copied_context=copied, weave_record_role='input' if copied else 'output')
        events.append(item)
    warnings.extend(notices)
    return True


def _trace(calls, meta):
    first = calls[0]
    project, trace_id = first['project_id'], first['trace_id']
    identifiers = {c['id'] for c in calls}
    roots = [c for c in calls if not c.get('parent_id')]
    missing = sorted({c['parent_id'] for c in calls if c.get('parent_id') not in identifiers and c.get('parent_id')})
    warnings = ['Weave export completeness is unverified; filtered or sampled calls may be absent.',
                'Input histories are retained as copied context. Separate model calls and choices remain separate trajectories; nesting is not semantic causality.']
    if missing:
        warnings.append(f'{len(missing)} parent calls are absent from this export.')
    if len(roots) != 1:
        warnings.append(f'This export contains {len(roots)} root calls; whole-rollout boundaries are unestablished.')
    meta = dict(meta)
    meta.update(source_collection='Weave', source_project_id=project, source_trace_id=trace_id,
                source_record_id=project + ':' + trace_id)
    meta.setdefault('source_uri', _url(project, roots[0]['id'] if len(roots) == 1 else first['id']))
    run_ids = sorted({c['wb_run_id'] for c in calls if c.get('wb_run_id')})
    steps = sorted({c['wb_run_step'] for c in calls if c.get('wb_run_step') is not None})
    meta['weave_wb_run_ids'] = run_ids
    meta['weave_wb_run_steps'] = steps
    if len(run_ids) == 1:
        meta.setdefault('experiment', run_ids[0])
        meta['wb_run_id'] = run_ids[0]
        # A call's logging step is a plotting coordinate, not optimizer-use evidence.
        if len(steps) == 1 and meta.get('training_step') is None:
            meta.update(training_step=steps[0], training_step_basis='weave_wb_run_step')
    if len(run_ids) > 1 or len(steps) > 1:
        warnings.append('Calls contain multiple W&B run/step values; per-call context is preserved without choosing one training coordinate.')
    events, spans, recognized = [], {}, 0
    by_id = {c['id']:c for c in calls}
    scorer_cache = {}
    def is_scorer(call):
        path = []
        current = call
        while current and current['id'] not in scorer_cache:
            path.append(current['id'])
            if _kind(current) == 'scorer':
                scorer_cache[current['id']] = True
                break
            current = by_id.get(current.get('parent_id'))
        result = bool(current and scorer_cache.get(current['id']))
        scorer_cache.update({identifier:result for identifier in path})
        return result
    for i, call in enumerate(calls):
        base = f'/calls/{i}'
        span = event(events, kind='call', actor='harness', text=call.get('display_name') or call['op_name'],
                     pointer=base + ('/display_name' if call.get('display_name') else '/op_name'),
                     trajectory_id='weave:'+call['id']+':span', order_known=False,
                     native_call_id=call['id'], native_parent_id=call.get('parent_id'),
                     source_uri=_url(project, call['id']),
                     started_at=call['started_at'], ended_at=call.get('ended_at'),
                     call_status='deleted' if call.get('deleted_at') else 'exception' if call.get('exception') else 'finished' if call.get('ended_at') else 'in_progress',
                     source_pointer_base=base)
        span['instrumentation_kind'] = _kind(call)
        span['behavior_scope'] = 'scorer' if is_scorer(call) else 'recorded_model_call' if _model_call(call) else 'instrumented_function'
        spans[call['id']] = span
        span['display_label'] = call.get('display_name') or call['op_name'].rsplit('/op/', 1)[-1].split(':', 1)[0]
        span.update({k:call[k] for k in ('wb_run_id','wb_run_step','wb_run_step_end') if call.get(k) is not None})
    for i, call in enumerate(calls):
        base, span = f'/calls/{i}', spans[call['id']]
        if call.get('parent_id') in spans:
            span['native_parent_event_id'] = spans[call['parent_id']]['id']
        common = {'trajectory_id': 'weave:'+call['id'], 'call_event_id': span['id'], 'call_pointer': base,
                  'native_call_id': call['id'], 'source_uri': span['source_uri'],
                  **{k: call[k] for k in ('thread_id','turn_id','wb_run_id','wb_run_step','wb_run_step_end') if call.get(k) is not None}}
        inputs, output = call['inputs'], call.get('output')
        messages = inputs.get('messages')
        if not (isinstance(messages, list) and messages and
                _messages(messages, base+'/inputs/messages', events, warnings, common, copied=True, tools=inputs.get('tools'))):
            event(events, kind='context', actor='harness', text=dumps(inputs), pointer=base+'/inputs',
                  copied_context=True, weave_record_role='input', **common)
        emitted = False
        if not call.get('deleted_at') and _model_call(call) and not is_scorer(call) and isinstance(output, dict):
            choices = output.get('choices')
            if isinstance(choices, list) and choices:
                for j, choice in enumerate(choices):
                    message = choice.get('message') if isinstance(choice, dict) else None
                    scope = common if j == 0 else {**common, 'trajectory_id':common['trajectory_id']+f':choice:{j}'}
                    if j and isinstance(messages, list) and messages:
                        _messages(messages, base+'/inputs/messages', events, warnings, scope, copied=True, tools=inputs.get('tools'))
                    if isinstance(message, dict) and message.get('role') == 'assistant':
                        before = len(events)
                        ok = _messages([message], base+f'/output/choices/{j}/message', events, warnings,
                                       scope, copied=False, tools=inputs.get('tools'))
                        for item in events[before:]:
                            item['source_pointer'] = item['source_pointer'].replace(f'/choices/{j}/message/0/', f'/choices/{j}/message/', 1)
                        emitted = ok or emitted
                    else:
                        warnings.append('An unsupported model output choice is retained in the source record.')
                    if not isinstance(message, dict) or message.get('role') != 'assistant' or not ok:
                        event(events, kind='source_output', actor='harness', text=dumps(choice),
                              pointer=base+f'/output/choices/{j}', weave_record_role='output', **scope)
            elif output.get('role') == 'assistant' and 'content' in output:
                before = len(events)
                emitted = _messages([output], base+'/output', events, warnings, common, copied=False, tools=inputs.get('tools'))
                for item in events[before:]:
                    item['source_pointer'] = item['source_pointer'].replace('/output/0/', '/output/', 1)
        recognized += bool(emitted)
        if output is not None and not emitted:
            event(events, kind='source_output', actor='harness', text=output if isinstance(output, str) else dumps(output),
                  pointer=base+'/output', weave_record_role='output', **common)
        if call.get('exception'):
            event(events, kind='source_exception', actor='harness', text=call['exception'], pointer=base+'/exception',
                  weave_record_role='exception', **common)
    if len(events) > 100_000:
        raise InputError('Weave trace exceeds 100,000 events; export a smaller trace')
    if not meta.get('task_id'):
        warnings.append('Task identity missing: excluded from paired checkpoint comparisons.')
    if not meta.get('checkpoint') and not meta.get('policy_version'):
        warnings.append('Policy version missing; W&B logging steps do not establish the generating policy.')
    for item in events:
        item.setdefault('copied_context', False)
        item['content_hash'] = digest({'kind':item['kind'], 'text':item['text']})
    meta['weave_capture'] = {'calls':len(calls), 'root_calls':len(roots), 'missing_parent_ids':missing,
        'unfinished_calls':sum(not c.get('ended_at') and not c.get('deleted_at') for c in calls),
        'model_output_calls':recognized, 'completeness':'unverified', 'input_histories':'copied_context'}
    # Rebuilt container retains exact native call values. Canonical sorting makes
    # repeated JSON/JSONL exports independent of file order and filename.
    raw = {'trajectory_format':VERSION, 'calls':calls}
    run = {'schema':SCHEMA_VERSION, 'adapter':'weave', 'adapter_version':VERSION, 'metadata':metadata(meta),
           'events':events, 'outcome':{}, 'warnings':list(dict.fromkeys(warnings)), 'raw':raw}
    run['id'] = digest({'raw':raw, 'metadata':run['metadata'], 'adapter':VERSION})[:24]
    return run
