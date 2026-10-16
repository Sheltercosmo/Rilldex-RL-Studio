"""Freeze a displayed training comparison in the existing investigation store.

No new inference, population matching, sample deduplication or statistic. The
same training projection is browsable after later arrivals and corrections.
"""
from copy import deepcopy
from urllib.parse import urlencode

from . import failure_investigations, training_lineage, training_selection, training_samples
from .schema import InputError

VERSION = 'training-investigation/1'
STAGES = {'generated', 'scored', 'admitted', 'backward', 'positive_mask_backward', 'optimizer'}
SCOPE = {'experiment', 'environment', 'monitor', 'selection'}


def source_graphs(store, snapshot):
    with store.connect() as c:
        graphs = {r['run_id']: dict(r) for r in c.execute(
            "SELECT id,run_id,source_hash FROM rollout_graphs WHERE observer='source' ORDER BY rowid")}
    return {row['run_id']: graphs[row['run_id']] for row in snapshot['samples'] if row['run_id'] in graphs}


def validate_view(snapshot, view):
    if not isinstance(view, dict) or set(view) != {'stage', 'selection'} or not isinstance(view['stage'], str) or view['stage'] not in STAGES:
        raise InputError('Choose a recorded population stage')
    selection = view['selection']
    if selection is not None:
        if not isinstance(selection, dict) or set(selection) - {'cohort', 'step', 'decision'} or 'cohort' not in selection:
            raise InputError('Invalid training case selection')
        if selection['cohort'] not in [c['cohort'] for c in snapshot['cohorts']]:
            raise InputError('Selected cohort is outside this snapshot')
        if 'step' in selection and (type(selection['step']) is not int or selection['step'] < 0):
            raise InputError('Selected coordinate must be a recorded nonnegative integer')
        if 'decision' in selection and (not snapshot['selection'] or selection['decision'] not in training_selection.STATES):
            raise InputError('Selected decision requires a named filter')
    rows = [r for r in snapshot['samples'] if r['populations'][view['stage']] and (
        selection is None or all(r.get(k) == v for k, v in selection['cohort'].items()) and
        ('step' not in selection or r.get('step') == selection['step']) and
        ('decision' not in selection or (r.get('filter_decision') or {}).get('state') == selection['decision']))]
    if not rows:
        raise InputError('The selected case population is empty')
    return [{**training_samples.identity(r), 'rollout_id': r['rollout_id'],
             'run_id': r['run_id']} for r in rows]


def save(store, raw):
    if not isinstance(raw, dict) or set(raw) - {'scope', 'snapshot_id', 'view', 'title', 'hypothesis', 'parent_id'}:
        raise InputError('Unknown training investigation fields')
    for key, limit in [('title', 120), ('hypothesis', 6000)]:
        if not isinstance(raw.get(key), str) or len(raw[key]) > limit or key == 'title' and not raw[key].strip():
            raise InputError('Invalid ' + key)
    if 'parent_id' in raw:
        if set(raw) != {'parent_id', 'view', 'title', 'hypothesis'}:
            raise InputError('A saved revision uses its pinned parent evidence only')
        if not isinstance(raw['parent_id'], str):
            raise InputError('Invalid saved parent identity')
        parent = failure_investigations.read(store, raw['parent_id'])
        if parent['schema'] != VERSION:
            raise InputError('Expected a saved training investigation')
        snapshot = deepcopy(parent['snapshot']); scope = parent['scope']; graphs = parent['source_graphs']
    else:
        if set(raw) != {'scope', 'snapshot_id', 'view', 'title', 'hypothesis'}:
            raise InputError('Training scope, displayed snapshot and case selection are required')
        scope = raw['scope']
        if not isinstance(scope, dict) or set(scope) - SCOPE or any(not isinstance(v, str) or not v for v in scope.values()):
            raise InputError('Invalid training scope')
        snapshot = training_lineage.snapshot(store, **scope)
        if snapshot['snapshot_id'] != raw['snapshot_id']:
            raise InputError('Training evidence changed. Refresh and review the comparison before saving.')
        graphs = source_graphs(store, snapshot)
    value = build_value(snapshot, scope, raw['view'], raw['title'], raw['hypothesis'], graphs)
    if 'parent_id' in raw:
        value['parent_id'] = raw['parent_id']
        for key in ('measure_comparison', 'reward_comparison', 'follow_up'):
            if key in parent: value[key] = deepcopy(parent[key])
        if 'reward_comparison' in parent: value['live_url'] = parent['live_url']
    return failure_investigations.persist(store,value)


def build_value(snapshot, scope, view, title, hypothesis, graphs):
    """Internal construction from server-owned evidence shared by entry points."""
    members = validate_view(snapshot, view)
    value = {'schema': VERSION, 'title': title.strip(), 'hypothesis': hypothesis,
        'hypothesis_status': 'Researcher hypothesis; not a verified cause', 'scope': scope,
        'live_url': '/?' + urlencode({'view': 'training', **scope}),
        'view': deepcopy(view), 'selected_samples': members, 'snapshot': snapshot, 'source_graphs': graphs,
        'inference_calls': 0,
        'limits': ['Charts retain the saved comparison scope. Case selection narrows the evidence table only.',
                   'The unit is a declared sample; repeated training uses do not add weight. Source joins can be missing.',
                   'Reopening live data creates a new comparison. This snapshot never absorbs late records or corrected observations.']}
    if snapshot['schema']=='training-population/2':
        value['limits'][1]='Training membership counts independent samples. Behavior summaries weight unique bound source rollouts within each population. Whole-rollout context is not behavior attributed to sample spans; missing mappings remain unknown.'
    return value
