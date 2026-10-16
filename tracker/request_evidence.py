"""Request-level reading of saved check observations, without new judgments.

Evidence sufficiency describes what a response supplies, never a passing check.
Historical clause versions and independent response judgments remain distinct.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from .graph_store import validate
from .schema import InputError

VERSION = 'request-evidence-review/1'
DISPATCH = {'attempts', 'prepares', 'none', 'unresolved'}
RESPONSE = {'sufficient', 'partial', 'no_answer', 'unresolved'}
LIMIT = ('Saved check correspondence and response sufficiency, not satisfaction, task success, '
         'communication, active intention or world truth. A negative test can supply sufficient '
         'answering evidence. Requirements and attributed claims are not evaluated by this observer. '
         'Absence of a saved relation does not establish absent behavior.')


def project(graph, cutoff_event_id=None):
    validate(graph)
    nodes = {n['id']: n for n in graph['nodes']}
    events = {n['properties']['id']: n['properties'] for n in nodes.values() if n['kind'] == 'event'}
    if cutoff_event_id is not None and cutoff_event_id not in events:
        raise InputError('Unknown request-evidence cutoff event')
    cutoff = events.get(cutoff_event_id)

    def visible(event):
        return bool(event and not event.get('copied_context') and event.get('agent_visibility') != 'not_established'
                    and not event['kind'].startswith('external_') and
                    (cutoff is None or event['trajectory_id'] == cutoff['trajectory_id'] and event['index'] <= cutoff['index']))

    def lane(event): return event['trajectory_id'], event.get('context_id')

    def unit(identifier):
        n = nodes.get(identifier, {}); p = n.get('properties', {}); ref = p.get('source', {})
        event = events.get(ref.get('event_id')); a, b = ref.get('start'), ref.get('end')
        if (n.get('kind') != 'unit' or not visible(event) or p.get('actor') != event['actor']
                or p.get('trajectory_id') != event['trajectory_id'] or type(a) is not int or type(b) is not int
                or not 0 <= a < b <= len(event['text']) or event['text'][a:b] != ref.get('text')):
            return None
        return p, event

    def record(event, node_id=None):
        return dict(event_id=event['id'], node_id=node_id or 'event:'+event['id'], index=event['index'],
                    text=event['text'][:1200], excerpt_truncated=len(event['text']) > 1200)

    clauses = {}; versions = {}; groups = defaultdict(list)
    for n in nodes.values():
        if n['kind'] not in {'requested_clause_version', 'requested_work_version'}: continue
        p = n['properties']; owner = unit(p.get('source_unit_id'))
        if not owner: continue
        if n['kind'] == 'requested_work_version':
            versions[p['version_id']] = (p, owner[1])
            groups[(*lane(owner[1]), p['id'])].append((p, owner))
        else:
            clauses[p['version_id']] = dict(clause=deepcopy(p), origin=record(owner[1], p['source_unit_id']),
                state='superseded', record_versions=[], dispatches=[], responses=[], coverage='unreviewed')
    for values in groups.values():
        ordered = sorted(values, key=lambda v:(v[1][1]['index'], v[1][0]['source']['end']))
        current = ordered[-1][0]
        for p, _ in ordered:
            for c in p.get('clauses', []):
                row = clauses.get(c['version_id'])
                if not row: continue
                row['record_versions'].append(p['version_id'])
                if p['version_id'] == current['version_id']: row['state'] = p['status']

    # Native source bindings define response opportunities, independently of any
    # model judgment about whether those responses answer a particular request.
    origins = defaultdict(set)
    for e in graph['edges']:
        if e['type'] != 'response_to': continue
        a, b = nodes.get(e['target'], {}), nodes.get(e['source'], {})
        if a.get('kind') != 'event' or b.get('kind') != 'event': continue
        action, response = a['properties'], b['properties']
        if (visible(action) and visible(response) and action['kind'] == 'action'
                and lane(action) == lane(response) and action['index'] < response['index']):
            origins[response['id']].add(action['id'])

    # Keep exact at-dispatch membership. A newer request must never relabel an
    # older attempt, and retained restrictions are not themselves checking work.
    opportunities = defaultdict(set); bindings = defaultdict(set)
    for edge in graph['edges']:
        if edge['type'] != 'request_context_at_dispatch': continue
        action = unit(edge['source']); state = nodes.get(edge['target'], {}).get('properties', {})
        if not action or action[0]['kind'] != 'action': continue
        for vid in state.get('version_ids', []):
            pair = versions.get(vid)
            if not pair or pair[0]['status'] != 'requested' or lane(pair[1]) != lane(action[1]): continue
            if pair[1]['index'] > action[1]['index']: continue
            for clause in pair[0].get('clauses', []):
                if clause['kind'] == 'requested_check' and clause['version_id'] in clauses:
                    opportunities[clause['version_id']].add(edge['source'])
                    bindings[(clause['version_id'],edge['source'])].add(vid)

    saved = (graph.get('semantic_context') or {}).get('requested_check_observations')
    excluded = []; dispatch_seen = {}; response_seen = {}

    def add(cid, aid, choice, request_ids, response_id=None, response_node=None, legacy=False, record_version=None):
        row = clauses.get(cid); action = unit(aid)
        if not row or row['clause']['kind'] != 'requested_check' or not action: return
        origin = events[row['origin']['event_id']]
        if (action[0]['kind'] != 'action' or action[0]['actor'] != 'agent' or lane(origin) != lane(action[1])
                or origin['index'] > action[1]['index'] or aid not in opportunities[cid]
                or bindings[(cid,aid)]!={record_version}):
            excluded.append(dict(clause_version_id=cid, action_unit_id=aid, reason='incompatible request or action context')); return
        if response_id is not None:
            event = events.get(response_id)
            if not visible(event): return
            if origins[response_id] != {action[1]['id']}:
                excluded.append(dict(clause_version_id=cid, event_id=response_id, reason='response not uniquely bound to action')); return
            allowed = RESPONSE; key = (cid, aid, response_id); seen = response_seen
        else:
            event = action[1]; allowed = DISPATCH; key = (cid, aid); seen = dispatch_seen
        if choice not in allowed or not request_ids:
            excluded.append(dict(clause_version_id=cid, action_unit_id=aid, reason='missing or invalid saved decision')); return
        if key in seen:
            if seen[key]['choice'] != choice:
                seen[key]['choice'] = 'unresolved'; seen[key]['conflicting_saved_choices'] = True
            return
        value = dict(action_unit_id=aid, action=record(action[1], aid), choice=choice,
                     record_version_id=record_version, decision_refs=list(request_ids),
                     provenance='positive relation only' if legacy else 'saved observation')
        if response_id is not None:
            response_unit = unit(response_node)
            value['response'] = record(event, response_node if response_unit and response_unit[1]['id'] == response_id else None)
            row['responses'].append(value)
        else: row['dispatches'].append(value)
        seen[key] = value

    if saved:
        if saved.get('source_hash') != graph['source_hash']:
            raise InputError('Requested-check observations belong to another source')
        for action in saved.get('actions', []):
            aid = action['action_unit_id']
            candidates={c['clause']['version_id']:c['record_version_id'] for c in action.get('candidates',[])}
            for cid, choice in action.get('dispatch_choices', {}).items():
                add(cid, aid, choice, action.get('dispatch_requests', []),record_version=candidates.get(cid))
            for response in action.get('responses', []):
                for cid, choice in response.get('choices', {}).items():
                    add(cid, aid, choice, response.get('requests', []), response.get('event_id'), response.get('feedback_unit_id'),record_version=candidates.get(cid))
    else:
        kinds = {'attempts_requested_check':'attempts', 'prepares_requested_check':'prepares',
                 'supplies_requested_evidence':'sufficient', 'partly_supplies_requested_evidence':'partial'}
        for edge in graph['edges']:
            choice = kinds.get(edge['type'])
            if not choice: continue
            p = edge['properties']; response_id = None
            if choice in RESPONSE:
                refs = p.get('evidence', [])
                response_id = refs[0].get('event_id') if refs else None
                if response_id is None: continue
            add(p.get('check_clause_version_id'), p.get('action_unit_id', edge['source']), choice,
                [p['request_hash']] if p.get('request_hash') else [], response_id, edge['source'], True,p.get('requested_work_version_id'))

    responses_by_action=defaultdict(set)
    for eid, owners in origins.items():
        if len(owners)==1:responses_by_action[next(iter(owners))].add(eid)
    for cid, row in clauses.items():
        actions = opportunities[cid]
        response_keys = {(aid, eid) for aid in actions for eid in responses_by_action[unit(aid)[1]['id']]}
        row['dispatches'].sort(key=lambda x:x['action']['index'])
        row['responses'].sort(key=lambda x:(x['response']['index'], x['action_unit_id']))
        dc = Counter(r['choice'] for r in row['dispatches']); rc = Counter(r['choice'] for r in row['responses'])
        row['counts'] = dict(dispatch_opportunities=len(actions), dispatch_reviewed=len(row['dispatches']),
            dispatch_unreviewed=len(actions)-len(row['dispatches']), response_opportunities=len(response_keys),
            response_reviewed=len(row['responses']), response_unreviewed=len(response_keys)-len(row['responses']),
            dispatch_choices=dict(dc), response_choices=dict(rc))
        row['excluded'] = [e for e in excluded if e['clause_version_id'] == cid]
        row['coverage'] = ('outside_check_observer' if row['clause']['kind'] != 'requested_check' else
            'positive_links_only' if not saved and (dc or rc) else 'unreviewed' if not saved else
            'no_recorded_dispatch_opportunity' if not actions else
            'complete_saved_review' if not row['excluded'] and len(actions)==len(row['dispatches']) and len(response_keys)==len(row['responses']) else 'partial_saved_review')
        row['evidence'] = ('sufficient_recorded_response' if rc['sufficient'] else 'partial_recorded_response' if rc['partial'] else
            'unresolved' if rc['unresolved'] else 'no_answer_in_reviewed_responses' if rc['no_answer'] else 'not_reviewed')
        row['latest_response_choice']=row['responses'][-1]['choice'] if row['responses'] else None
        row['attempts_without_recorded_response'] = sum(not any(aid==a for a,_ in response_keys)
            for aid in {r['action_unit_id'] for r in row['dispatches'] if r['choice']=='attempts'})
    rows = sorted(clauses.values(), key=lambda r:(r['origin']['index'], r['clause']['id'], r['clause']['version_id']))
    native_actions={e['id'] for e in events.values() if visible(e) and e['actor']=='agent' and e['kind']=='action'}
    represented_actions={v[1]['id'] for n in nodes.values() if (v:=unit(n['id'])) and v[0]['kind']=='action'}
    return dict(schema=VERSION, graph_id=graph['id'], run_id=graph['run_id'], source_hash=graph['source_hash'],
        cutoff_event_id=cutoff_event_id, rows=rows, excluded=excluded,
        counts=dict(clause_versions=len(rows), current_clauses=sum(r['state']=='requested' for r in rows),
            requested_check_versions=sum(r['clause']['kind']=='requested_check' for r in rows),
            native_actions=len(native_actions), represented_actions=len(represented_actions),
            unrepresented_actions=len(native_actions-represented_actions)),
        observation_schema=saved.get('schema') if saved else None, new_model_calls=0, boundary=LIMIT)
