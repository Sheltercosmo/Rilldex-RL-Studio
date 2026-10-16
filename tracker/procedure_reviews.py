"""Named procedure comparisons for exact, source-bound recurring action pairs.

This is a review overlay, never a Jev result or inferred success. Source, unit,
work-identity and previously saved graph versions remain intact.
"""
from copy import deepcopy
import json

from . import graph_store, work_episodes
from .method_comparison import DISPATCH_CHOICES
from .relation_reviews import named
from .schema import InputError, digest

VERSION = 'procedure-review/1'
CHOICES = {k: DISPATCH_CHOICES[k] for k in
           ('same_procedure', 'reconfigured_procedure', 'alternative_procedure', 'unresolved')}
LIMIT = ('Named comparison of an exact pair of recorded dispatches. Changes to a stored artifact or '
         'environment are separate context, not a changed dispatch. Same procedure is not a blind retry; '
         'different procedure is not proof of exploration. Outcome, causal improvement and independent '
         'semantic accuracy are not established.')


def restore(graph):
    value = deepcopy(graph)
    ctx = value.get('semantic_context') or {}
    old = ctx.pop('procedure_reviews', None)
    if old:
        obs = ctx.setdefault('work_observations', {})
        obs['method_observations'] = deepcopy(old['original_observations'])
        if old['original_schema'] is None: obs.pop('method_schema', None)
        else: obs['method_schema'] = old['original_schema']
    return value


def eligible(graph):
    base = restore(graph)
    events = {n['properties']['id']: n['properties'] for n in base['nodes'] if n['kind'] == 'event'}
    units = {n['id']: n['properties'] for n in base['nodes'] if n['kind'] == 'unit'}
    result = {}
    for episode in work_episodes.project(base)['episodes']:
        key = episode['previous_unit_id'], episode['current_unit_id']
        a, b = (units[k] for k in key)
        ea, eb = (events[u['source']['event_id']] for u in (a, b))
        # A reviewer compares complete, visible and ordered dispatches in one
        # context. Parallel siblings and context resets are not ordered retries.
        if (episode['category'] == 'interrupted' or ea.get('actor') != eb.get('actor')
                or ea.get('context_id') != eb.get('context_id')
                or any(e.get('agent_visibility') == 'not_established' for e in (ea, eb))):
            continue
        result[key] = episode
    return result


def validate(graph, document):
    if (not isinstance(document, dict) or set(document) != {'schema', 'base_graph_id', 'reviews', 'revision'}
            or document['schema'] != VERSION or document['base_graph_id'] != graph['id']
            or not named(document['revision'])):
        raise InputError('A procedure review requires a pinned graph and a named revision with a note')
    rows = document['reviews']
    if not isinstance(rows, list) or len(rows) > 256: raise InputError('At most 256 procedure reviews per graph')
    pairs = eligible(graph); seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'previous_unit_id', 'current_unit_id', 'comparison', 'review'}
                or not named(row['review']) or not isinstance(row['comparison'], str) or row['comparison'] not in CHOICES
                or not all(isinstance(row[k], str) for k in ('previous_unit_id', 'current_unit_id'))):
            raise InputError('Each procedure comparison needs two units, a supported choice and a named source review')
        key = row['previous_unit_id'], row['current_unit_id']
        if key in seen or key not in pairs: raise InputError('Review a unique, supported, ordered same-work recurrence')
        seen.add(key)
    return pairs


def observation(graph, row):
    units = {n['id']: n['properties'] for n in graph['nodes'] if n['kind'] == 'unit'}
    a, b = (units[row[k]] for k in ('previous_unit_id', 'current_unit_id'))
    return dict(previous_unit_id=row['previous_unit_id'], current_unit_id=row['current_unit_id'],
                comparison=row['comparison'], work_instance='same_work_instance', status='reviewed',
                cutoff=deepcopy(b['source']), basis=VERSION, review=deepcopy(row['review']),
                inspector_context={'source_ranges': [deepcopy(a['source']), deepcopy(b['source'])]})


def expected(graph, rows, originals):
    pairs = {(r['previous_unit_id'], r['current_unit_id']) for r in rows}
    kept = [deepcopy(o) for o in originals if (o.get('previous_unit_id'), o.get('current_unit_id')) not in pairs]
    return kept + [observation(graph, row) for row in rows]


def checked(graph):
    info = (graph.get('semantic_context') or {}).get('procedure_reviews')
    if not info:
        observations = (graph.get('semantic_context') or {}).get('work_observations', {}).get('method_observations', [])
        if any(o.get('basis') == VERSION for o in observations):
            raise InputError('Procedure review observations have no source-bound review document')
        return
    document = deepcopy(info['document']); document['base_graph_id'] = graph['id']
    validate(graph, document)
    wanted = expected(graph, document['reviews'], info['original_observations'])
    actual = graph['semantic_context']['work_observations']['method_observations']
    if actual != wanted: raise InputError('Procedure observations differ from their source-bound reviews')


def fork(graph, document):
    graph_store.validate(graph)
    checked(graph); validate(graph, document)
    old = (graph.get('semantic_context') or {}).get('procedure_reviews', {})
    if old and {k:v for k,v in old['document'].items() if k != 'base_graph_id'} == {k:v for k,v in document.items() if k != 'base_graph_id'}:
        return deepcopy(graph)
    g = deepcopy(graph); g.pop('id'); ctx = g.setdefault('semantic_context', {})
    if ctx is None: ctx = {}; g['semantic_context'] = ctx
    obs = ctx.setdefault('work_observations', {})
    originals = old.get('original_observations', obs.get('method_observations', []))
    root = old.get('root_graph_id', graph['id'])
    ctx['procedure_reviews'] = dict(document=deepcopy(document), root_graph_id=root,
        original_observations=deepcopy(originals), original_schema=old.get('original_schema', obs.get('method_schema')),
        base_observer=old.get('base_observer', graph['observer']),
        base_label=old.get('base_label', graph['observer_label']), limit=LIMIT)
    obs.update(method_observations=expected(graph, document['reviews'], originals), method_schema=VERSION)
    g['observer'] = 'procedure-review-' + digest([VERSION, ctx['procedure_reviews']['base_observer']])[:20]
    g['observer_label'] = 'Reviewed procedures · ' + ctx['procedure_reviews']['base_label']
    g['annotation_hash'] = digest([graph['annotation_hash'], document])
    g['nodes'].sort(key=lambda n:n['id']); g['edges'].sort(key=lambda e:e['id'])
    return {'id': 'graph-' + digest(g), **g}


def template(graph, previous, current):
    checked(graph)
    pair = eligible(graph).get((previous, current))
    if pair is None: raise InputError('Choose a supported ordered recurrence to compare procedures')
    old = (graph.get('semantic_context') or {}).get('procedure_reviews', {})
    document = deepcopy(old.get('document') or dict(schema=VERSION, reviews=[], revision={'author':'','note':''}))
    document['base_graph_id'] = graph['id']
    return dict(document=document, episode=pair, choices=CHOICES, new_model_calls=0, limit=LIMIT)


def receive(store, document):
    if not isinstance(document, dict) or not isinstance(document.get('base_graph_id'), str):
        raise InputError('Missing procedure review base graph')
    base = graph_store.read(store, document['base_graph_id']); graph = fork(base, document)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        source = c.execute('SELECT document FROM runs WHERE id=?', (base['run_id'],)).fetchone()
        if not source or digest(json.loads(source[0])) != base['source_hash']:
            raise InputError('Procedure review source no longer matches its graph')
        exists = c.execute('SELECT 1 FROM rollout_graphs WHERE id=?', (graph['id'],)).fetchone()
        latest = c.execute('SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? ORDER BY rowid DESC LIMIT 1',
                           (base['run_id'], graph['observer'])).fetchone()
        if not exists and latest and latest[0] != base['id']:
            raise InputError('Procedure review changed; open the latest reviewed graph before editing')
        graph_store.save(c, graph)
    # Publish this graph to the existing activity/observer inventory immediately.
    # No model inference or rescanning of unrelated graph contents is needed.
    from . import behavior_distributions
    behavior_distributions.sync(store, graph_ids=[graph['id']])
    return dict(graph_id=graph['id'], observer=graph['observer'], run_id=graph['run_id'],
                base_graph_id=base['id'], new_model_calls=0)
