"""Explicit run selections and atomic changes to display organization."""
import json
from datetime import datetime, timezone

from .experiment_catalog import _FACTS
from .schema import InputError


def _experiments(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 500 or
            any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in value) or
            len(set(value)) != len(value)):
        raise InputError('Select 1–500 distinct experiments')
    return value


def _rows(c, experiments, environment=None):
    marks = ','.join('?' for _ in experiments)
    return [dict(r) for r in c.execute(_FACTS + '''SELECT g.experiment,g.logs,
        coalesce(l.title,g.experiment) title,coalesce(l.project,'') project,
        coalesce(l.tags,'[]') tags,coalesce(l.pinned,0) pinned,coalesce(l.archived,0) archived
        FROM grouped g LEFT JOIN experiment_labels l ON l.experiment=g.experiment
        WHERE g.experiment IN (''' + marks + ')', [environment, environment, *experiments])]


def selection(store, *, experiments, environment=None):
    """Resolve selected runs independently of catalog search, page and archive filters."""
    _experiments(experiments)
    if environment is not None and (not isinstance(environment, str) or len(environment) > 500):
        raise InputError('Use an exact environment name')
    with store.connect() as c:
        c.execute('BEGIN')
        rows = {r['experiment']: r for r in _rows(c, experiments, environment)}
    for row in rows.values():
        row['tags'] = json.loads(row['tags'])
    return dict(rows=[rows[e] for e in experiments if e in rows],
                unavailable=[e for e in experiments if e not in rows])


def organize_many(store, *, experiments, project=None, add_tags=None, remove_tags=None,
                  pinned=None, archived=None):
    """Update exactly these runs in one transaction, preserving captured records."""
    _experiments(experiments)
    if project is not None and (not isinstance(project, str) or len(project) > 200):
        raise InputError('Project names are limited to 200 characters; use an empty name to unassign')
    if any(v is not None and type(v) is not bool for v in (pinned, archived)):
        raise InputError('Pinned and archived must be booleans')
    for tags in (add_tags, remove_tags):
        if tags is not None and (not isinstance(tags, list) or len(tags) > 20 or
                any(not isinstance(t, str) or not t.strip() or len(t) > 60 for t in tags)):
            raise InputError('Use up to 20 short tags')
    additions = list(dict.fromkeys(t.strip() for t in add_tags or []))
    removals = {t.strip() for t in remove_tags or []}
    if set(additions) & removals:
        raise InputError('A tag cannot be added and removed in the same change')
    if project is None and pinned is None and archived is None and not additions and not removals:
        raise InputError('Choose a project, tags, pin or archive change')
    now = datetime.now(timezone.utc).isoformat()
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        rows = _rows(c, experiments)
        if len(rows) != len(experiments):
            raise InputError('Some selected experiments are no longer available. Refresh the selection.')
        for row in rows:
            experiment = row['experiment']
            tags = list(dict.fromkeys(t for t in json.loads(row['tags']) if t not in removals))
            tags.extend(t for t in additions if t not in tags)
            if len(tags) > 20:
                raise InputError('A selected run would exceed 20 tags. Remove tags before adding more.')
            c.execute('INSERT OR IGNORE INTO experiment_labels(experiment,title,updated_at) VALUES(?,?,?)',
                      (experiment, experiment, now))
            changes = dict(project=project.strip() if project is not None else None,
                           pinned=pinned, archived=archived, updated_at=now)
            if additions or removals:
                changes['tags'] = json.dumps(tags, ensure_ascii=False)
            changes = {k: v for k, v in changes.items() if v is not None}
            c.execute('UPDATE experiment_labels SET ' + ','.join(k + '=?' for k in changes) +
                      ' WHERE experiment=?', [*changes.values(), experiment])
    return dict(updated=len(experiments), experiments=experiments)
