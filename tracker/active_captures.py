"""Bounded summaries of latest in-progress source prefixes.

These are live source-prefix facts, not completed-rollout measurements. No
success, reward, stall, duration, or semantic behavior is inferred here.
"""
import json

from .schema import InputError


VERSION = 'active-capture-prefix/2'
MAX_ROWS = 12
TEXT_LIMIT = 300


def _scope_value(value, name):
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise InputError(name + ' must be nonempty text or omitted')


def _excerpt(text):
    text = ' '.join(text.split())
    if len(text) <= TEXT_LIMIT:
        return text
    return text[:TEXT_LIMIT - 1] + '…'


def _prefix(run, receipt):
    events = run.get('events') if isinstance(run.get('events'), list) else []
    source_events = [e for e in events if isinstance(e, dict) and not e.get('copied_context')]
    prose = [e for e in source_events if e.get('actor') == 'agent'
             and e.get('kind') in {'reasoning', 'message'} and isinstance(e.get('text'), str)]
    latest_text = next((e for e in reversed(prose) if e.get('text', '').strip()), None)
    return {
        'run_id': receipt['run_id'],
        'producer': receipt['producer'],
        'rollout_id': receipt['rollout_id'],
        'revision': receipt['revision'],
        'received_at': receipt['received_at'],
        'task_id': receipt['task_id'],
        'environment': receipt['environment'],
        'event_count': len(source_events),
        'action_count': sum(e.get('actor') == 'agent' and e.get('kind') == 'action' for e in source_events),
        'feedback_count': sum(e.get('kind') == 'feedback' for e in source_events),
        'agent_text_chars': sum(len(e['text']) for e in prose),
        'last_agent_event_id': latest_text.get('id') if latest_text else None,
        'last_agent_text': _excerpt(latest_text['text']) if latest_text else '',
    }


def semantic_observations(c, run_ids):
    """Bounded current-snapshot worker status, never an older prefix's map."""
    if not run_ids or not c.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_watch_jobs'").fetchone():
        return {}
    marks=','.join('?' for _ in run_ids)
    rows=c.execute(f'''SELECT * FROM (
        SELECT j.run_id,j.worker_id,j.status,j.document,
          json_extract(w.document,'$.label') label,
          row_number() OVER(PARTITION BY j.run_id ORDER BY j.updated_at DESC,j.worker_id) position,
          count(*) OVER(PARTITION BY j.run_id) total
        FROM semantic_watch_jobs j JOIN semantic_watchers w ON w.id=j.worker_id
        WHERE j.run_id IN ({marks})) WHERE position<=3''',run_ids).fetchall()
    result={}
    for row in rows:
        group=result.setdefault(row['run_id'],{'total':row['total'],'rows':[]})
        item={'observer':row['worker_id'],'label':row['label'],'status':row['status']}
        detail=json.loads(row['document'])
        if row['status']=='published':
            item.update(unit_count=detail.get('unit_count'),graph_id=detail.get('graph_id'))
        elif isinstance(detail.get('coverage'),dict):
            # Expose progress in source annotation, not inferred task progress.
            # This bounded projection does not decode candidate files on a poll.
            coverage=detail['coverage']
            item['annotation_progress']={key:coverage[key] for key in
                ('selected_units','selected_source_bytes','eligible_source_bytes') if key in coverage}
        pending=detail.get('waiting_candidates',{}).get('missing_responses')
        if row['status']=='needs_candidates' and type(pending) is int and pending>=0:
            item['pending_proposals']=pending
        group['rows'].append(item)
    return result


def snapshot(store, *, experiment=None, environment=None, limit=MAX_ROWS):
    """Return a bounded current prefix view for latest in-progress revisions.

    Logical identities are (producer, rollout_id). A newer complete or failed
    revision removes that identity from the active set. The total count is
    computed in SQL; only the limited newest run documents are decoded in
    Python.
    """
    _scope_value(experiment, 'experiment')
    _scope_value(environment, 'environment')
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise InputError('limit must be an integer from 1 through 12')

    # Select latest logical revisions first. Metadata predicates operate in
    # SQLite; the full run document is fetched only for the bounded ID list.
    latest = '''
        SELECT v.producer,v.rollout_id,v.revision,v.run_id,v.created_at
        FROM rollout_revisions v
        WHERE v.revision=(SELECT max(n.revision) FROM rollout_revisions n
                          WHERE n.producer=v.producer AND n.rollout_id=v.rollout_id)
          AND v.state='in_progress'
    '''
    # Monitoring treats absent, null, and empty experiment values as the
    # selectable __unassigned__ bucket. Keep that same meaning here.
    experiment_value = "coalesce(nullif(json_extract(r.document,'$.metadata.experiment'),''),'__unassigned__')"
    filters = f'''
        AND (? IS NULL OR {experiment_value}=?)
        AND (? IS NULL OR json_extract(r.document,'$.metadata.environment')=?)
    '''
    with store.read_snapshot() as saved:
        c = saved.connection
        total = c.execute('''SELECT count(*) FROM (''' + latest + ''') active
            JOIN runs r ON r.id=active.run_id WHERE 1=1 ''' + filters,
            (experiment, experiment, environment, environment)).fetchone()[0]
        receipts = [dict(row) for row in c.execute('''SELECT active.producer,active.rollout_id,
                active.revision,active.run_id,active.created_at received_at,
                json_extract(r.document,'$.metadata.task_id') task_id,
                json_extract(r.document,'$.metadata.environment') environment
            FROM (''' + latest + ''') active JOIN runs r ON r.id=active.run_id
            WHERE 1=1 ''' + filters + '''
            ORDER BY active.created_at DESC,active.producer,active.rollout_id LIMIT ?''',
            (experiment, experiment, environment, environment, limit)).fetchall()]
        runs = {}
        if receipts:
            placeholders = ','.join('?' for _ in receipts)
            runs = {row['id']: json.loads(row['document']) for row in c.execute(
                f'SELECT id,document FROM runs WHERE id IN ({placeholders})',
                [row['run_id'] for row in receipts]).fetchall()}
        observations=semantic_observations(c,list(runs))

    rows = [_prefix(runs[receipt['run_id']], receipt) for receipt in receipts]
    for row in rows:row['semantic_observations']=observations.get(row['run_id'],{'total':0,'rows':[]})
    return {
        'schema': VERSION,
        'total': total,
        'limit': limit,
        'truncated': total > len(rows),
        'rows': rows,
        'boundary': 'Each row is the current source prefix for one latest in-progress (producer, rollout_id) identity. Prefix counts are not completed-rollout metrics. Semantic status links only observations of this exact snapshot; absent or older observations are not ready. No success, reward, duration or stall is inferred.',
    }
