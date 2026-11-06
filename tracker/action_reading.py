"""Expose existing action readings inside the rollout inspector."""
import json

from .jev import JevClient, JEV_HARNESS
from .observe import analyze
from .schema import InputError, digest
from .store import current_macro_observations


def _load(store, run_id, event_id):
    with store.connect() as connection:
        row = connection.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = json.loads(row[0])
        event = next((e for e in run['events'] if e['id'] == event_id), None)
        if not event or event['kind'] != 'action' or event.get('copied_context') or event['actor'] != 'agent':
            raise InputError('Select an original agent action in this rollout')
        history = [dict(r) for r in connection.execute(
            'SELECT * FROM observations WHERE run_id=? AND event_id=? ORDER BY created_at,rowid', (run_id, event_id))]
        reviews = [{**json.loads(r['payload']), 'id': r['id'], 'created_at': r['created_at']}
                   for r in connection.execute('SELECT * FROM reviews WHERE run_id=? ORDER BY id', (run_id,))]
    return run, event, history, reviews


def _matches(client, row, run, event_id):
    result = json.loads(row['result'])
    provenance = result.get('_provenance', {})
    return all(provenance.get(key) == row[key] for key in ('harness', 'model', 'packet_hash')) and client.cache_matches(result, run, event_id)


def inspect(store, run_id, event_id, *, client=None):
    client = client or JevClient()
    run, event, history, reviews = _load(store, run_id, event_id)
    observed = current_macro_observations(run, history, reviews)
    action = next(a for a in analyze(run, observed)['actions'] if a['event_id'] == event_id)
    # Expose semantic choices only. Tool-name heuristics are not model readings.
    reading = observed.get(event_id, {})
    request = client.request(run, event_id)
    previous = request['state']['prior_actions'][-1:]
    fields = {k: v for k, v in action['semantic'].items() if not k.startswith('_')}
    reviewed = any(value.get('source') == 'review' for value in fields.values())
    reusable = any(_matches(client, row, run, event_id) for row in history)
    current = bool(reading.get('_provenance')) and not reading.get('_outdated_observation')
    return {'schema': 'action-reading/1', 'run_id': run_id, 'source_hash': digest(run),
            'event_id': event_id, 'source_pointer': event['source_pointer'],
            'status': 'current' if current else 'reviewed' if reviewed else 'outdated' if history else 'uninspected',
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
    client = client or JevClient()
    run, event, history, _ = _load(store, run_id, event_id)
    cached = any(_matches(client, row, run, event_id) for row in history)
    if not cached:
        result = client.evaluate(run, event['id'])
        p = result['_provenance']
        store.record(run_id, event_id, p['harness'], p['model'], p['packet_hash'], result)
        store.refresh(run_id)
    return {**inspect(store, run_id, event_id, client=client), 'reused': cached}
