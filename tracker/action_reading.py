"""Expose existing action readings inside the rollout inspector."""
import json
from collections import Counter, defaultdict

from .jev import JevClient, JEV_HARNESS
from .observe import analyze
from .schema import InputError, digest
from .store import current_macro_observations
from .work_order import Evidence


def _snapshot(store, run_id, event_id=None):
    with store.read_snapshot() as snapshot, snapshot.connect() as connection:
        row = connection.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = json.loads(row[0])
        event = next((e for e in run['events'] if e['id'] == event_id), None) if event_id is not None else None
        if event_id is not None and (not event or event['kind'] != 'action' or event.get('copied_context') or event['actor'] != 'agent'):
            raise InputError('Select an original agent action in this rollout')
        clause = ' AND event_id=?' if event_id is not None else ''
        history = [dict(r) for r in connection.execute(
            'SELECT * FROM observations WHERE run_id=?' + clause + ' ORDER BY created_at,rowid',
            (run_id, event_id) if event_id is not None else (run_id,))]
        reviews = [{**json.loads(r['payload']), 'id': r['id'], 'created_at': r['created_at']}
                   for r in connection.execute('SELECT * FROM reviews WHERE run_id=? ORDER BY id', (run_id,))]
    return run, event, history, reviews


def _status(reading, fields, has_history):
    if reading.get('_provenance') and not reading.get('_outdated_observation'):
        return 'current'
    if any(v.get('source') == 'review' for v in fields.values()):
        return 'reviewed'
    return 'outdated' if has_history else 'uninspected'


def flow(store, run_id, *, client=None, profile=None, limit=100, graph=None, recurrence_order=None):
    """Saved semantic purposes in source order; no inference or heuristic labels."""
    client = client or JevClient()
    with store.read_snapshot() as snapshot:
        run, _, history, reviews = _snapshot(snapshot, run_id)
        with snapshot.connect() as connection:
            job = connection.execute('SELECT id,status,progress,total,error FROM jobs WHERE run_id=? AND inspector_profile=? ORDER BY id DESC LIMIT 1',
                                     (run_id, profile)).fetchone() if profile else None
            active = connection.execute("SELECT id,inspector_profile FROM jobs WHERE run_id=? AND status IN ('running','queued') ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
    work = None
    if graph is not None:
        if graph['run_id'] != run_id or graph['source_hash'] != digest(run):
            raise InputError('Work overview must use the same rollout source snapshot')
        from .work_overview import project
        work = project(graph, recurrence_order=recurrence_order)
    elif recurrence_order is not None:
        raise InputError('Work ordering requires a saved graph')
    observed = current_macro_observations(run, history, reviews)
    by_event = defaultdict(list)
    for record in history:
        by_event[record['event_id']].append(record)
    events = {e['id']: e for e in run['events'] if not e.get('copied_context')}
    order = Evidence(events)
    lanes, rows, purposes, coverage = {}, [], Counter(), Counter()
    for action in analyze(run, observed)['actions']:
        if action.get('actor') != 'agent':
            continue
        eid = action['event_id']
        fields = {k: v for k, v in action['semantic'].items() if not k.startswith('_')}
        status = _status(observed.get(eid, {}), fields, bool(by_event[eid]))
        mode = fields.get('mode', {})
        purpose = mode.get('value') if mode.get('status') == 'decided' and mode.get('value') in {'explore','apply','verify','coordinate','report','mixed'} else 'unresolved'
        reusable = any(_matches(client, row, run, eid) for row in by_event[eid])
        coverage[status] += 1
        coverage['pending'] += not reusable
        purposes[purpose] += 1
        key = (action['trajectory_id'], action.get('context_id'), action.get('actor'))
        if key not in lanes:
            lanes[key] = {'id': 'lane-' + digest(key), 'trajectory_id': key[0], 'context_id': key[1], 'actor': key[2], 'action_ids': []}
        lanes[key]['action_ids'].append(eid)
        row = {'event_id': eid, 'number': len(rows) + 1, 'source_index': action['index'],
               'lane_id': lanes[key]['id'], 'title': action.get('tool') or action['text'][:100] or 'Agent action',
               'purpose': purpose, 'status': status, 'reviewed': any(v.get('source') == 'review' for v in fields.values()),
               'fields': {k: {name: v[name] for name in ('status','value','source','basis') if name in v}
                          for k, v in fields.items() if k in {'mode','feedback_response','goal_relation'}},
               'order_known': order.is_ordered(eid), 'dispatch_group': order.groups.get(eid, [eid]),
               'same_dispatch_as': action['previous_occurrence'], 'scope': action['macro']['goal_scope']['value']}
        row['work_returns'] = [e['id'] for e in (work or {}).get('episodes', [])
                               if e['state'] == 'returned' and e['current']['event_id'] == eid]
        rows.append(row)
    from .action_distributions import comparison_url
    return {'schema': 'action-flow/1', 'run_id': run_id, 'source_hash': digest(run), 'comparison_url':comparison_url(run),
            'actions': rows, 'lanes': list(lanes.values()), 'purposes': dict(purposes), 'work': work,
            'coverage': {**{k: coverage[k] for k in ('current','reviewed','outdated','uninspected','pending')},
                         'total': len(rows), 'purpose_decided': len(rows) - purposes['unresolved']},
            'model': client.model, 'harness': JEV_HARNESS, 'batch_limit': limit,
            'job': dict(job) if job else None, 'other_job_active': bool(active and active['inspector_profile'] != profile)}


def _matches(client, row, run, event_id):
    result = json.loads(row['result'])
    provenance = result.get('_provenance', {})
    return all(provenance.get(key) == row[key] for key in ('harness', 'model', 'packet_hash')) and client.cache_matches(result, run, event_id)


def inspect(store, run_id, event_id, *, client=None):
    if not isinstance(event_id, str) or not event_id:
        raise InputError('Select one action to read')
    client = client or JevClient()
    run, event, history, reviews = _snapshot(store, run_id, event_id)
    observed = current_macro_observations(run, history, reviews)
    action = next(a for a in analyze(run, observed)['actions'] if a['event_id'] == event_id)
    # Expose semantic choices only. Tool-name heuristics are not model readings.
    reading = observed.get(event_id, {})
    request = client.request(run, event_id)
    previous = request['state']['prior_actions'][-1:]
    fields = {k: v for k, v in action['semantic'].items() if not k.startswith('_')}
    reviewed = any(value.get('source') == 'review' for value in fields.values())
    reusable = any(_matches(client, row, run, event_id) for row in history)
    return {'schema': 'action-reading/1', 'run_id': run_id, 'source_hash': digest(run),
            'event_id': event_id, 'source_pointer': event['source_pointer'],
            'status': _status(reading, fields, bool(history)),
            'fields': fields, 'provenance': reading.get('_provenance'), 'reviewed': reviewed,
            'model': (reading.get('_provenance') or {}).get('model', client.model),
            'requested_model': client.model, 'reusable': reusable,
            'harness': JEV_HARNESS, 'history_count': len(history),
            'previous_action': previous[0]['action']['event_id'] if previous else None,
            'previous_feedback': [f['event_id'] for f in previous[0]['feedback']] if previous else [],
            'feedback_support': action['feedback_support'],
            'scope': 'Immediate action purpose and its response to preceding feedback. A method change does not establish improvement or successful recovery.'}


def read(store, run_id, event_id, *, client=None):
    """One selected action; exact saved requests are reused without inference."""
    if not isinstance(event_id, str) or not event_id:
        raise InputError('Select one action to read')
    client = client or JevClient()
    run, event, history, _ = _snapshot(store, run_id, event_id)
    cached = any(_matches(client, row, run, event_id) for row in history)
    if not cached:
        result = client.evaluate(run, event['id'])
        p = result['_provenance']
        store.record(run_id, event_id, p['harness'], p['model'], p['packet_hash'], result)
        store.refresh(run_id)
    return {**inspect(store, run_id, event_id, client=client), 'reused': cached}
