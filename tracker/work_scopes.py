"""Persist expressed scope membership without inventing goals or task phases."""
from collections import Counter
from copy import deepcopy
from .schema import InputError, digest
from .semantic_extraction import checked_span
from .work_context import VERSION as OBSERVER_VERSION

VERSION = 'work-scope-graph/1'


def materialize(run, document, node, edge):
    context = document.get('work_context')
    if not context:
        return None
    if context.get('schema') != OBSERVER_VERSION or context.get('source_hash') != digest(run) or context.get('run_id') != run['id']:
        raise InputError('Work scope source or protocol mismatch')
    units = {u['id']:u for u in document['units']}
    frames = {f['id']:f for f in context['frames']}
    if len(frames) != len(context['frames']):
        raise InputError('Duplicate work scope identity')
    selected = []; observations = []; seen = set(); used = set()
    for row in context['observations']:
        uid = row['unit_id']; unit = units.get(uid)
        if uid in seen or not unit or unit.get('actor') != 'agent' or unit.get('kind') not in {'semantic','action'}:
            raise InputError('Work scope observation needs a unique agent contribution')
        seen.add(uid)
        if row.get('cutoff') != unit['source']:
            raise InputError('Work scope cutoff differs from its contribution')
        at = checked_span(run,unit['source'],unit['source'])
        ids = row['frame_ids']
        if len(ids) != len(set(ids)) or any(fid not in frames for fid in ids):
            raise InputError('Invalid work scope membership identity')
        for fid in ids:
            f = frames[fid]; origin = checked_span(run,f['source'],unit['source'])
            if origin['trajectory_id'] != at['trajectory_id']:
                raise InputError('Cross-trajectory work scope membership')
            if origin.get('copied_context') or origin.get('agent_visibility') == 'not_established' or origin['kind'].startswith('external_'):
                raise InputError('Work scope origin is not established as visible')
            if f['kind'] == 'user_contribution':
                if origin['actor'] != 'user':raise InputError('Requested scope needs user source')
            elif f['kind'] == 'organized_plan':
                plans = [units.get(i) for i in f['unit_ids']]
                if len(plans)!=1 or not plans[0] or plans[0].get('activity')!='plan' or plans[0]['source']!=f['source']:
                    raise InputError('Plan scope needs its source Plan unit')
            else:raise InputError('Unknown work scope origin kind')
        if row['status']=='selected':
            if not ids or not row.get('requests'):raise InputError('Selected scope needs membership and decision identity')
            used.update(ids);selected.append(row)
        observations.append({'unit_id':uid,'status':row['status'],
                             'scope_ids':['scope:'+fid for fid in ids] if row['status']=='selected' else [],
                             'candidate_scope_ids':['scope:'+fid for fid in ids] if row['status']!='selected' else [],
                             'requests':deepcopy(row.get('requests',[]))})
    events = {e['id']:e for e in run['events']}
    for fid in sorted(used):
        f = frames[fid]
        title = ' '.join(r['summary']['text'] for r in f.get('readings',[]) if r.get('summary',{}).get('text')) or f['text']
        sid = 'scope:'+fid
        node(sid,'work_scope',{'scope_id':fid,'scope_kind':f['kind'],'text':title,
                             'source':deepcopy(f['source']),'source_unit_ids':list(f['unit_ids']),
                             'annotation_schema':OBSERVER_VERSION},events[f['source']['event_id']])
        edge(sid,'event:'+f['source']['event_id'],'scope_source',{'basis':'exact_source_span','evidence':[deepcopy(f['source'])]})
    for row in selected:
        u = units[row['unit_id']]
        for fid in row['frame_ids']:
            edge(u['id'],'scope:'+fid,'in_work_scope',{
                'basis':'saved_scope_selection','request_ids':list(row['requests']),
                'cutoff':deepcopy(row['cutoff']),
                'evidence':[deepcopy(u['source']),deepcopy(frames[fid]['source'])],
                'explanation':'Contribution refers to this expressed request or plan. Membership does not establish authorization, active intent, fulfillment or goal drift.'})
    return {'schema':VERSION,'observer_schema':OBSERVER_VERSION,'input_hash':digest(context),
            'scope_count':len(used),'observations':observations,
            'counts':dict(Counter(r['status'] for r in observations)),
            'limit':'Shared contributions may refer to several scopes. Scope order and recurrence do not establish goal changes, task phases, completion or strategy.'}
