"""Versioned, source-bound immediate-work membership for any agent contribution.

Review/import establishes membership; projection never derives it from labels,
activity, native span nesting, or text equality. No model inference occurs here.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import json

from .schema import InputError, digest
from . import graph_store
from .semantic_extraction import windows

LEGACY_VERSION = 'work-subject-bindings/1'
VERSION = 'work-subject-bindings/2'
SELECTED_VERSION = 'work-subject-bindings/3'
DERIVED_VERSION = 'work-subject-bindings/4'
NAV_VERSION = 'contribution-work-navigation/2'
DEFAULT_PROFILE = {'id': 'immediate-work', 'version': '1', 'label': 'Immediate work targets',
                   'definition': 'One immediate question, result or artifact target per coherent contribution. '
                   'Broader requests and plans stay separate. Identity requires an explicit supported binding; '
                   'matching words or tools alone are insufficient. Unresolved membership stays unbound.'}
LIMIT = ('One immediate-work subject per coherent contribution. Subjects are explicit annotations, '
         'not inferred from matching text or tool names. Returns mean recurrence of an annotated subject; '
         'they do not establish exploration, deviation, progress or successful recovery. Unannotated '
         'source, unresolved membership and unordered dispatches interrupt the observed route. '
         'Request/plan membership is a separate, broader scale.')


def evidence_index(graph):
    events = {n['properties']['id']: n['properties'] for n in graph['nodes'] if n['kind'] == 'event'}
    units = {}; issues = []; by_event = defaultdict(list)
    eligible = defaultdict(list)
    for w in windows({'events': list(events.values())}):
        e = events[w['event_id']]
        if e.get('actor') == 'agent' and e.get('agent_visibility') != 'not_established':
            eligible[e['id']].append(w)
    for n in graph['nodes']:
        u = n['properties']; s = u.get('source', {}); e = events.get(s.get('event_id'))
        if n['kind'] != 'unit' or u.get('actor') != 'agent' or u.get('kind') not in {'semantic', 'action'}:
            continue
        a, b = s.get('start'), s.get('end')
        if (not e or e['id'] not in eligible or type(a) is not int or type(b) is not int or
                not 0 <= a < b <= len(e['text']) or e['text'][a:b] != s.get('text') or
                not s['text'].strip() or (u['kind'] == 'action') != (e['kind'] == 'action')):
            issues.append({'unit_id': n['id'], 'reason': 'Invalid or ineligible source contribution'}); continue
        # Whitespace padding is harmless; a unit cannot swallow excluded payloads.
        left = a + len(s['text']) - len(s['text'].lstrip())
        right = b - len(s['text']) + len(s['text'].rstrip())
        if not any(w['start'] <= left < right <= w['end'] for w in eligible[e['id']]):
            issues.append({'unit_id': n['id'], 'reason': 'Contribution crosses eligible source regions'}); continue
        units[n['id']] = u; by_event[e['id']].append(n['id'])
    bad = set()
    for ids in by_event.values():
        ids.sort(key=lambda uid: units[uid]['source']['start'])
        for i, uid in enumerate(ids):
            for other in ids[i+1:]:
                if units[other]['source']['start'] >= units[uid]['source']['end']: break
                bad.update((uid, other))
    for uid in sorted(bad):
        issues.append({'unit_id': uid, 'reason': 'Overlapping contributions require boundary review'}); units.pop(uid)
    return events, units, eligible, issues


def position(unit, events):
    s = unit['source']; return events[s['event_id']]['index'], s['start'], s['end']


def lane(unit, events):
    e = events[unit['source']['event_id']]
    return e['trajectory_id'], e.get('actor'), e.get('context_id')


def validate(graph, document):
    if not isinstance(document, dict): raise InputError('Work bindings need a document')
    fields = {'schema', 'base_graph_id', 'subjects', 'bindings'}
    if document.get('schema') in {VERSION, SELECTED_VERSION, DERIVED_VERSION}: fields.add('profile')
    if document.get('schema') == SELECTED_VERSION: fields.add('selection')
    if document.get('schema') == DERIVED_VERSION: fields.add('derivation')
    if (set(document) != fields or document['schema'] not in {VERSION, LEGACY_VERSION, SELECTED_VERSION, DERIVED_VERSION} or document['base_graph_id'] != graph['id'] or
            not isinstance(document['subjects'], list) or not isinstance(document['bindings'], list)):
        raise InputError('Work subjects require a versioned document bound to the exact base graph')
    if document['schema'] in {VERSION, SELECTED_VERSION, DERIVED_VERSION}:
        p = document['profile']
        if (not isinstance(p, dict) or set(p) != set(DEFAULT_PROFILE) or
                any(not isinstance(v, str) or not v.strip() or len(v) > (2400 if k=='definition' else 240) for k,v in p.items())):
            raise InputError('A shared work profile needs an identity, version, label and definition')
    events, units, _, _ = evidence_index(graph)
    subjects = {}; rows = {}
    for s in document['subjects']:
        if (not isinstance(s, dict) or set(s) != {'id', 'label', 'origin_unit_id'} or
                any(not isinstance(s[k], str) or not s[k].strip() for k in s) or
                len(s['label']) > 1200 or len(s['id']) > 160 or s['id'] in subjects or s['origin_unit_id'] not in units):
            raise InputError('A work subject needs a unique identity, natural-language target and eligible origin unit')
        subjects[s['id']] = s
    for r in document['bindings']:
        if (not isinstance(r, dict) or set(r) != {'unit_id', 'status', 'subject_id', 'note', 'provenance'} or
                not isinstance(r['unit_id'], str) or r['unit_id'] not in units or r['unit_id'] in rows or
                not isinstance(r['status'], str) or r['status'] not in {'bound', 'unresolved', 'not_applicable'} or
                not isinstance(r['note'], str) or not r['note'].strip() or len(r['note']) > 2400):
            raise InputError('Work binding needs a unique eligible unit, status and review rationale')
        p = r['provenance']
        allowed = {'review', 'producer_annotation'}
        if document['schema'] == SELECTED_VERSION: allowed |= {'jev_raw_argmax', 'unavailable'}
        if document['schema'] == DERIVED_VERSION: allowed |= {'pair_derivation'}
        if (not isinstance(p, dict) or set(p) != {'kind', 'author', 'protocol'} or
                not isinstance(p['kind'], str) or p['kind'] not in allowed or
                any(not isinstance(p[k], str) or not p[k].strip() or len(p[k]) > 240 for k in p)):
            raise InputError('Work binding needs supported provenance; this is not a Jev selection without replayable v3 receipts')
        if p['kind']=='unavailable' and r['status']!='unresolved':
            raise InputError('Unavailable work selection must stay unresolved')
        if r['status'] == 'bound':
            if not isinstance(r['subject_id'], str) or r['subject_id'] not in subjects:
                raise InputError('Bound work subject is missing')
            origin = units[subjects[r['subject_id']]['origin_unit_id']]; current = units[r['unit_id']]
            a, b = position(origin, events), position(current, events)
            if lane(origin, events) != lane(current, events) or (origin is not current and not (a[0] < b[0] or a[0] == b[0] and a[2] <= b[1])):
                raise InputError('Work identity cannot cross actor/context lanes or use a future origin')
        elif r['subject_id'] is not None:
            raise InputError('Unresolved or not-applicable membership cannot select a subject')
        rows[r['unit_id']] = r
    for s in subjects.values():
        r = rows.get(s['origin_unit_id'], {})
        if r.get('status') != 'bound' or r.get('subject_id') != s['id']:
            raise InputError('Each subject origin must itself be explicitly bound to that subject')
    if document['schema'] == SELECTED_VERSION:
        from .contribution_work import validate_selection
        validate_selection(graph, document)
    if document['schema'] == DERIVED_VERSION:
        from .scope_membership import validate as validate_derivation
        validate_derivation(graph, document)
    return deepcopy(document)


def fork(graph, document):
    graph_store.validate(graph); d = validate(graph, document)
    g = deepcopy(graph); g.pop('id')
    old = {n['id'] for n in g['nodes'] if n['kind'] == 'work_subject'}
    g['nodes'] = [n for n in g['nodes'] if n['id'] not in old]
    g['edges'] = [e for e in g['edges'] if e['source'] not in old and e['target'] not in old]
    events, units, _, _ = evidence_index(graph)
    previous = (g.get('semantic_context') or {}).get('work_subjects', {})
    origin_graph = previous.get('root_graph_id', graph['id'])
    def edge(a, b, kind, properties):
        e = dict(source=a, target=b, type=kind, properties=properties)
        g['edges'].append(dict(id='edge-'+digest(e), **e))
    subjects = {s['id']: s for s in d['subjects']}
    for s in d['subjects']:
        unit = units[s['origin_unit_id']]; ev = events[unit['source']['event_id']]
        g['nodes'].append(dict(id='work-subject:'+s['id'], kind='work_subject', activity=None,
            trajectory_id=ev['trajectory_id'], event_index=ev['index'],
            properties={**s, 'source': deepcopy(unit['source']), 'schema': VERSION}))
        edge('work-subject:'+s['id'], s['origin_unit_id'], 'work_subject_origin', {'basis': VERSION})
    for r in d['bindings']:
        if r['status'] != 'bound': continue
        origin = units[subjects[r['subject_id']]['origin_unit_id']]; current = units[r['unit_id']]
        edge(r['unit_id'], 'work-subject:'+r['subject_id'], 'about_work_subject',
            {**r, 'basis': VERSION, 'cutoff': deepcopy(current['source']),
             'evidence': [deepcopy(origin['source']), deepcopy(current['source'])]})
    g['semantic_context'] = g.get('semantic_context') or {}
    reviewed = g['semantic_context'].get('relationship_reviews')
    base_observer = previous.get('base_observer', reviewed['base_observer'] if reviewed else graph['observer'])
    g['semantic_context']['work_subjects'] = dict(document=d, root_graph_id=origin_graph, base_observer=base_observer, limit=LIMIT)
    g['observer'] = ('work-subjects-'+digest([d['schema'], d['profile'], base_observer])[:20] if d['schema'] in {VERSION, SELECTED_VERSION, DERIVED_VERSION}
                     else 'work-review-'+digest(origin_graph)[:20])
    g['observer_label'] = d['profile']['label'] if d['schema'] in {VERSION, SELECTED_VERSION, DERIVED_VERSION} else 'Reviewed work subjects'
    if reviewed:
        from .relation_reviews import apply_observer
        reviewed['base_label'] = g['observer_label']
        apply_observer(g, g['observer'])
    g['annotation_hash'] = digest([graph['annotation_hash'], d])
    g['coverage'] = {**g['coverage'], 'work_subjects': 'partial', 'semantic_relations': 'partial'}
    g['counts'] = {**g['counts'], 'nodes': len(g['nodes']), 'edges': len(g['edges'])}
    g['nodes'].sort(key=lambda n: n['id']); g['edges'].sort(key=lambda e: e['id'])
    return {'id': 'graph-'+digest(g), **g}


def template(graph):
    events, units, _, issues = evidence_index(graph)
    existing = (graph.get('semantic_context') or {}).get('work_subjects', {}).get('document')
    d = deepcopy(existing) if existing else dict(schema=VERSION, profile=deepcopy(DEFAULT_PROFILE), subjects=[], bindings=[])
    d['base_graph_id'] = graph['id']
    return {'document': d, 'units': [dict(id=uid, source=u['source'], activity=u.get('activity'),
        kind=u['kind'], lane=list(lane(u, events)), position=list(position(u, events)))
        for uid, u in sorted(units.items(), key=lambda item: position(item[1], events))],
        'issues': issues, 'new_model_calls': 0, 'limit': LIMIT}


def receive(store, document):
    if not isinstance(document, dict) or not isinstance(document.get('base_graph_id'), str):
        raise InputError('Missing base graph')
    base = graph_store.read(store, document['base_graph_id'])
    with store.connect() as c:
        row = c.execute('SELECT document FROM runs WHERE id=?', (base['run_id'],)).fetchone()
    if not row or digest(json.loads(row[0])) != base['source_hash']:
        raise InputError('Work review source no longer matches its graph')
    result = fork(base, document)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        exists = c.execute('SELECT 1 FROM rollout_graphs WHERE id=?', (result['id'],)).fetchone()
        latest = c.execute('SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? ORDER BY rowid DESC LIMIT 1',
                           (base['run_id'], result['observer'])).fetchone()
        if not exists and latest and latest[0] != base['id']:
            raise InputError('Work review changed since this graph. Open the latest reviewed graph before editing.')
        graph_store.save(c, result)
    return dict(graph_id=result['id'], observer=result['observer'], run_id=result['run_id'],
                base_graph_id=base['id'], new_model_calls=0)


def project(graph, *, recurrence_order=None):
    from . import work_order
    if recurrence_order is not None: work_order.validate(recurrence_order)
    info = (graph.get('semantic_context') or {}).get('work_subjects')
    if not info: raise InputError('No contribution work bindings in this graph')
    d = deepcopy(info['document']); d['base_graph_id'] = graph['id']; validate(graph, d)
    events, units, eligible, issues = evidence_index(graph)
    ordering = work_order.Evidence(events) if recurrence_order else None
    rows = {r['unit_id']: r for r in d['bindings']}; subjects = {s['id']: s for s in d['subjects']}
    binding_edges = {}
    for e in graph['edges']:
        if e['type'] != 'about_work_subject': continue
        r = rows.get(e['source'])
        if (not r or r['status'] != 'bound' or e['target'] != 'work-subject:'+r['subject_id'] or
                any(e['properties'].get(k) != v for k, v in r.items()) or e['source'] in binding_edges):
            raise InputError('Work binding edge disagrees with its annotation')
        binding_edges[e['source']] = e['id']
    if set(binding_edges) != {r['unit_id'] for r in rows.values() if r['status'] == 'bound'}:
        raise InputError('Work binding edge is missing')
    streams = defaultdict(list); by_event = defaultdict(list)
    for uid, u in units.items(): by_event[u['source']['event_id']].append(uid)
    batches = Counter((e['trajectory_id'], e.get('parent_id')) for e in events.values()
                      if e['kind'] == 'action' and e.get('parent_id'))
    for eid, regions in eligible.items():
        e = events[eid]; key = (e['trajectory_id'], e.get('actor'), e.get('context_id'))
        ordered = not (e.get('batch_size', 0) > 1 or e.get('parent_id') and batches[(e['trajectory_id'], e['parent_id'])] > 1)
        if ordering and len(ordering.groups.get(eid, [])) > 1: ordered = False
        for w in regions:
            ids = sorted((uid for uid in by_event[eid] if units[uid]['source']['start'] < w['end'] and
                          units[uid]['source']['end'] > w['start']), key=lambda uid: units[uid]['source']['start'])
            cursor = w['start']
            def append(uid, a, b):
                if not e['text'][a:b].strip(): return
                r = rows.get(uid, {}); sid = r.get('subject_id') if r.get('status') == 'bound' else None
                local_target = None
                if d['schema'] == DERIVED_VERSION and uid and not sid:
                    from .contribution_work import immediate_target, GRAPH_INPUT
                    local_target = immediate_target(units[uid], GRAPH_INPUT).get('text')
                streams[key].append(dict(unit_id=uid, event_id=eid, source=dict(event_id=eid,
                    start=a, end=b, text=e['text'][a:b], source_pointer=e['source_pointer']),
                    group_id=sid, identity_status=r.get('status', 'unreviewed' if uid else 'source_gap'),
                    target=subjects[sid]['label'] if sid else local_target or ('No immediate work target' if r.get('status') == 'not_applicable' else 'Work target unresolved' if uid else 'Unannotated source'),
                    order_known=bool(ordered), activity=units[uid].get('activity') if uid else None))
            for uid in ids:
                s = units[uid]['source']; append(None, cursor, max(cursor, s['start']))
                append(uid, max(w['start'], s['start']), min(w['end'], s['end'])); cursor = s['end']
            append(None, cursor, w['end'])
    paths = []; visits = []; links = []; episodes = []; categories = Counter(); positions = []
    for key, route in sorted(streams.items(), key=lambda item: str(item[0])):
        route.sort(key=lambda p: (events[p['event_id']]['index'], p['source']['start']))
        lane_visits = []; prior = {}; seen_positions = []
        for i, p in enumerate(route):
            sid = p['group_id']; previous = prior.get(sid) if sid else None
            p.update(category='first_or_unresolved', episode_id=None, plan_stages=[])
            if previous is not None:
                between = route[previous+1:i]
                gap = any(not x['order_known'] or x['identity_status'] in {'source_gap', 'unreviewed', 'unresolved'} for x in route[previous:i+1])
                category = 'interrupted' if gap else 'returned' if any(x['group_id'] and x['group_id'] != sid for x in between) else 'resumed' if between else 'continued'
                proof = None
                if ordering: category, proof = ordering.classify(route, previous, i)
                old = route[previous]; ids = [binding_edges[old['unit_id']], binding_edges[p['unit_id']]]
                episode = dict(id='work-episode-'+digest([graph['id'], old['unit_id'], p['unit_id']]),
                    category=category, target=p['target'], previous_unit_id=old['unit_id'], current_unit_id=p['unit_id'],
                    edge_ids=list(dict.fromkeys(ids)), cards=[dict(unit_id=x['unit_id'], role=role, label=x['source']['text'])
                        for x, role in [(old, 'Earlier contribution'), (p, 'Later contribution')]])
                if proof:
                    episode['id'] = 'work-episode-'+digest([graph['id'],old['unit_id'],p['unit_id'],recurrence_order])
                    episode['ordering'] = proof
                    if category == 'returned':
                        episode['cards'][1:1] = [dict(unit_id=x['unit_id'],role='Intervening work',label=x['source']['text'])
                            for x in between if x['unit_id']]
                        episode['edge_ids'] = list(dict.fromkeys(ids+[binding_edges[x['unit_id']] for x in between if x['unit_id'] in binding_edges]))
                episodes.append(episode); p.update(category=category, episode_id=episode['id']); categories[category] += 1
            current = lane_visits[-1] if lane_visits else None
            if not (current and sid and current['group_id'] == sid and p['category'] == 'continued'):
                current = dict(id='work-visit-'+digest([graph['id'], key, i]), trajectory_id=key[0], actor=key[1],
                    context_id=key[2], group_id=sid, target=p['target'], scope_ids=[], plan_stages=[],
                    unit_ids=[], event_ids=[], positions=[], occurrences=[], episode_ids=[], order_known=p['order_known'])
                lane_visits.append(current); visits.append(current)
            current['positions'].append(i+1); current['event_ids'].append(p['event_id']); current['occurrences'].append(p)
            if p['unit_id']: current['unit_ids'].append(p['unit_id'])
            if p['episode_id']:
                current['episode_ids'].append(p['episode_id'])
                links.append(dict(type='same_work_return', source=current['id'], target=seen_positions[previous],
                    episode_id=p['episode_id'], category=p['category'], edge_ids=episodes[-1]['edge_ids']))
            seen_positions.append(current['id'])
            if sid: prior[sid] = i
            positions.append(p)
        for a, b in zip(lane_visits, lane_visits[1:]):
            links.append(dict(type='recorded_next', source=a['id'], target=b['id'],
                              order_known=a['order_known'] and b['order_known'], edge_ids=[]))
        paths.append(dict(trajectory_id=key[0], actor=key[1], context_id=key[2], visit_ids=[v['id'] for v in lane_visits]))
    for link in links: link['id'] = 'work-link-'+digest(link)
    counts = dict(Counter(p['identity_status'] for p in positions))
    counts.update({k: categories[k] for k in ('continued', 'returned', 'interrupted', 'resumed')})
    counts.update(positions=len(positions), contributions=sum(bool(p['unit_id']) for p in positions),
                  source_gaps=sum(p['unit_id'] is None for p in positions), subjects=len(subjects), visits=len(visits))
    value = dict(schema=NAV_VERSION, run_id=graph['run_id'], source_hash=graph['source_hash'], graph_id=graph['id'],
        observer=graph['observer'], axis='contributions', paths=paths, visits=visits, links=links, scopes=[],
        episodes=episodes, counts=counts, issues=issues, available=bool(positions), limit=LIMIT)
    if recurrence_order:
        value['recurrence_order'] = recurrence_order
        value['limit'] = (LIMIT.replace('Unannotated source, unresolved membership and unordered dispatches interrupt the observed route.',
            'Missing work coverage and unordered endpoints interrupt recurrence. Complete parallel dispatch groups may sit between ordered endpoints; their internal order stays unknown.'))
    return {'id': 'work-navigation-'+digest(value), **value}
