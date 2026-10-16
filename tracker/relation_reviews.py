"""Named, source-bound corrections to semantic relationships, never source edits.

The same review envelope handles feedback references, evidence use and revisions.
It records an annotation, not independent ground truth or a Jev selection.
"""
from copy import deepcopy
import json

from . import graph_store, work_subjects
from .schema import InputError, digest

VERSION = 'relationship-review/1'
RELATIONS = {
    'assesses': 'Explicitly describes or interprets this returned feedback. Does not establish correctness or causal use.',
    'uses_evidence': 'Uses the earlier contribution as evidence for the expressed work. Mention alone is insufficient.',
    'revises': 'Changes the referenced earlier claim, proposal or method. Changed wording alone is insufficient.',
}
LIMIT = ('Named source-bound annotations, not independent semantic validation. Absent/unresolved applies only '
         'to this contribution and referent. Unreviewed pairs retain their original observation or missingness. '
         'A complete negative feedback window still requires all contributions and source coverage.')


def index(graph):
    events, eligible, _, _ = work_subjects.evidence_index(graph)
    nodes = {n['id']: n for n in graph['nodes'] if n['kind'] == 'unit'}
    sources = {uid: u for uid, u in eligible.items()
               if u['kind'] == 'semantic' and u.get('status') == 'selected'}
    return events, nodes, sources


def endpoints(graph, row, lookup=None):
    events, nodes, sources = lookup or index(graph)
    a = sources.get(row['from']); node = nodes.get(row['to'])
    if not a or not node or row['from'] == row['to']:
        raise InputError('Choose a selected coherent contribution and an earlier source-bound referent')
    b = node['properties']; sa, sb = a['source'], b.get('source', {})
    ea, eb = events[sa['event_id']], events.get(sb.get('event_id'))
    lo, hi = sb.get('start'), sb.get('end')
    if (not eb or eb.get('copied_context') or eb.get('agent_visibility') == 'not_established'
            or eb['kind'].startswith('external_') or type(lo) is not int or type(hi) is not int
            or not 0 <= lo < hi <= len(eb['text']) or not eb['text'][lo:hi].strip()
            or eb['text'][lo:hi] != sb.get('text')
            or ea['trajectory_id'] != eb['trajectory_id'] or ea.get('context_id') != eb.get('context_id')
            or not (eb['index'] < ea['index'] or eb['index'] == ea['index'] and hi <= sa['start'])):
        raise InputError('Relationship evidence must be exact, visible and earlier in the same context')
    if row['type'] == 'assesses':
        # Reviewing absence must cover the whole recorded response, not one
        # conveniently selected fragment. Native correspondence supplies recipient.
        if b.get('kind') != 'feedback' or eb['kind'] != 'feedback' or eb['text'][:lo].strip() or eb['text'][hi:].strip():
            raise InputError('Feedback review requires a unit covering the whole returned response')
        origins = [e['target'] for e in graph['edges'] if e['type'] == 'feedback_for' and e['source'] == row['to']]
        if len(origins) != 1 or origins[0] not in nodes:
            raise InputError('Feedback review requires a unique native originating action')
        action = nodes[origins[0]]['properties']; event = events.get(action.get('source', {}).get('event_id'))
        native = any(e['type'] == 'response_to' and e['source'] == 'event:'+eb['id']
                     and event and e['target'] == 'event:'+event['id'] for e in graph['edges'])
        if (not event or not native or action.get('kind') != 'action' or event['actor'] != ea['actor']
                or event['trajectory_id'] != ea['trajectory_id'] or event.get('context_id') != ea.get('context_id')
                or event['index'] >= eb['index']):
            raise InputError('Feedback recipient and native action correspondence are not established')
        siblings = [u for u in nodes.values() if u['properties'].get('kind') == 'feedback'
                    and u['properties'].get('source', {}).get('event_id') == eb['id']]
        if len(siblings) != 1:
            raise InputError('Resolve duplicate or split feedback units before reviewing this response')
    elif row['to'] not in sources or b.get('actor') != a.get('actor'):
        raise InputError('Evidence/revision review requires an earlier selected contribution from the same actor')
    return a, b


def named(value):
    return (isinstance(value, dict) and set(value) == {'author', 'note'}
            and all(isinstance(value[k], str) and value[k].strip()
                    and len(value[k]) <= (240 if k == 'author' else 2400) for k in value))


def key(row):
    return row['from'], row['to'], row['type']


def validate(graph, document):
    if (not isinstance(document, dict) or set(document) != {'schema', 'base_graph_id', 'revision', 'reviews'}
            or document['schema'] != VERSION or document['base_graph_id'] != graph['id']
            or not named(document['revision']) or not isinstance(document['reviews'], list)
            or len(document['reviews']) > 10000):
        raise InputError('Relationship review requires the exact graph, named revision and bounded review records')
    seen = set(); lookup = index(graph)
    for row in document['reviews']:
        if (not isinstance(row, dict) or set(row) != {'from', 'to', 'type', 'status', 'provenance'}
                or any(not isinstance(row[k], str) for k in ('from', 'to', 'type', 'status'))
                or row['type'] not in RELATIONS or row['status'] not in {'present', 'absent', 'unresolved'}
                or not named(row['provenance']) or key(row) in seen):
            raise InputError('Each unique relationship needs a supported type, explicit status and named rationale')
        endpoints(graph, row, lookup); seen.add(key(row))
    return deepcopy(document)


def edge(graph, row, lookup=None):
    a, b = endpoints(graph, row, lookup)
    props = dict(basis=VERSION, review_status='present', provenance=deepcopy(row['provenance']),
                 evidence=[deepcopy(a['source'])], context_evidence=[deepcopy(b['source'])],
                 cutoff=deepcopy(a['source']), explanation=row['provenance']['note'])
    item = dict(source=row['from'], target=row['to'], type=row['type'], properties=props)
    return dict(id='edge-'+digest(item), **item)


def apply_observer(graph, base_observer=None):
    info = graph['semantic_context']['relationship_reviews']
    if base_observer is not None: info['base_observer'] = base_observer
    graph['observer'] = 'relationship-review-'+digest([VERSION, info['base_observer']])[:20]
    graph['observer_label'] = 'Reviewed relationships · '+info['base_label']


def fork(graph, document):
    graph_store.validate(graph); d = validate(graph, document)
    g = deepcopy(graph); g.pop('id')
    ctx = g.setdefault('semantic_context', {}) or {}; g['semantic_context'] = ctx
    old = ctx.get('relationship_reviews', {})
    # Restore originals before applying the complete new overlay. Removing a
    # review therefore restores the original fact instead of inventing absence.
    edges = {e['id']: e for e in g['edges'] if e['properties'].get('basis') != VERSION}
    edges.update({e['id']: e for e in old.get('suppressed_edges', [])})
    reviewed = {key(r): r for r in d['reviews']}
    suppressed = [e for e in edges.values() if (e['source'], e['target'], e['type']) in reviewed]
    for e in suppressed: edges.pop(e['id'])
    lookup = index(graph)
    for r in d['reviews']:
        if r['status'] == 'present':
            e = edge(graph, r, lookup); edges[e['id']] = e
    g['edges'] = sorted(edges.values(), key=lambda e:e['id'])
    ctx['relationship_reviews'] = dict(document=d, suppressed_edges=suppressed,
        root_graph_id=old.get('root_graph_id', graph['id']),
        base_observer=old.get('base_observer', graph['observer']),
        base_label=old.get('base_label', graph['observer_label']), limit=LIMIT)
    apply_observer(g)
    g['annotation_hash'] = digest([graph['annotation_hash'], d])
    g['coverage'] = {**g['coverage'], 'semantic_relations': 'partial', 'relationship_reviews': 'partial'}
    g['counts'] = {**g['counts'], 'edges': len(g['edges'])}
    g['nodes'].sort(key=lambda n:n['id'])
    return {'id':'graph-'+digest(g), **g}


def checked(graph):
    """Validate the annotation-to-edge mapping before it supplies measurement evidence."""
    info = (graph.get('semantic_context') or {}).get('relationship_reviews')
    if not info: return {}
    d = deepcopy(info['document']); d['base_graph_id'] = graph['id']; validate(graph, d)
    result = {key(r): r for r in d['reviews']}
    lookup = index(graph)
    expected = {e['id']:e for r in d['reviews'] if r['status'] == 'present' for e in [edge(graph, r, lookup)]}
    actual = {e['id']:e for e in graph['edges'] if e['properties'].get('basis') == VERSION}
    if expected != actual: raise InputError('Reviewed relationships differ from their source-bound records')
    for e in graph['edges']:
        k = e['source'], e['target'], e['type']
        if k in result and e['properties'].get('basis') != VERSION:
            raise InputError('Original relationship was not superseded by its review')
    return result


def template(graph, focus):
    lookup = index(graph); _, nodes, sources = lookup
    if focus not in sources: raise InputError('Review a selected coherent semantic contribution')
    old = (graph.get('semantic_context') or {}).get('relationship_reviews', {})
    d = deepcopy(old.get('document') or dict(schema=VERSION, reviews=[], revision={'author':'', 'note':''}))
    d['base_graph_id'] = graph['id']; candidates = []
    for uid, n in nodes.items():
        types = []
        for relation in RELATIONS:
            try: endpoints(graph, {'from':focus, 'to':uid, 'type':relation}, lookup)
            except InputError: continue
            types.append(relation)
        if types: candidates.append(dict(id=uid, types=types, source=n['properties']['source'], activity=n.get('activity')))
    candidates.sort(key=lambda n:(nodes[n['id']]['event_index'], n['source']['start']))
    return dict(document=d, subject=sources[focus], candidates=candidates, relations=RELATIONS,
                new_model_calls=0, limit=LIMIT)


def receive(store, document):
    if not isinstance(document, dict) or not isinstance(document.get('base_graph_id'), str):
        raise InputError('Missing review base graph')
    base = graph_store.read(store, document['base_graph_id']); result = fork(base, document)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        source = c.execute('SELECT document FROM runs WHERE id=?', (base['run_id'],)).fetchone()
        if not source or digest(json.loads(source[0])) != base['source_hash']:
            raise InputError('Review source no longer matches its graph')
        exists = c.execute('SELECT 1 FROM rollout_graphs WHERE id=?', (result['id'],)).fetchone()
        latest = c.execute('SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? ORDER BY rowid DESC LIMIT 1',
                           (base['run_id'], result['observer'])).fetchone()
        if not exists and latest and latest[0] != base['id']:
            raise InputError('Relationship review changed; open the latest reviewed graph before editing')
        graph_store.save(c, result)
    return dict(graph_id=result['id'], observer=result['observer'], run_id=result['run_id'],
                base_graph_id=base['id'], new_model_calls=0)
