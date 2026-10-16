"""Correct coherent units before rebuilding semantic relationships.

Reviews bind one complete eligible source window. They never rewrite source,
replay a Jev judgment, or transfer a relation to a replacement unit by position.
"""
from copy import deepcopy
import json

from . import base_standard, graph_store, relation_reviews, semantic_extraction as sem, work_subjects
from .schema import InputError, digest

VERSION = 'unit-review/1'
DEPENDENCY_POLICY = 'unit-review-dependencies/2'
KINDS = {'event', 'unit', 'plan_step', 'work_scope', 'work_subject', 'unresolved_reference'}
LIMIT = ('Named annotations validate source binding and structure, not semantic correctness. '
         'Changed units get new identities. Their relationships and work bindings need review; '
         'untracked scope, work-identity/method and feedback-coverage observations are invalidated. '
         'Prior graph versions and measurement receipts remain unchanged.')


def source(store, graph):
    graph_store.validate(graph)
    if any(n['kind'] not in KINDS for n in graph['nodes']):
        raise InputError('Review the original observation graph, not a derived state or recovery graph')
    with store.connect() as c:
        row = c.execute('SELECT document FROM runs WHERE id=?', (graph['run_id'],)).fetchone()
    if not row or digest(json.loads(row[0])) != graph['source_hash']:
        raise InputError('Review source differs from its immutable graph')
    return json.loads(row[0])


def window(run, identifier):
    found = next((w for w in sem.windows(run) if w['id'] == identifier), None)
    if not found: raise InputError('Choose an eligible complete agent source window')
    return found


def in_window(graph, w):
    found = []
    for n in graph['nodes']:
        if n['kind'] != 'unit': continue
        s = n['properties'].get('source', {})
        if s.get('event_id') != w['event_id']: continue
        if not isinstance(s.get('start'), int) or not isinstance(s.get('end'), int):
            raise InputError('Existing unit has invalid boundaries; repair its source binding first')
        if s['start'] < w['end'] and s['end'] > w['start']:
            if s['start'] < w['start'] or s['end'] > w['end']:
                raise InputError('Existing unit crosses excluded source content; repair its source binding first')
            found.append(n)
    return sorted(found, key=lambda n:(n['properties']['source']['start'], n['id']))


def editable(run, unit):
    """Normalize legacy content for the editor, without changing retained nodes."""
    ref = unit['source']; activity = unit.get('activity', 'unresolved')
    if activity not in sem.ACTIVITIES: activity = 'unresolved'
    result = dict(start=ref['start'], end=ref['end'], activity=activity, fields={})
    if activity in {'other', 'unresolved'}: return result
    contract = sem.generation_request(run, ref, activity)['field_contract']
    content = unit.get('content', {})
    for field in contract:
        value = deepcopy(content.get(field, content.get('target') if field == 'work_target' else None))
        if isinstance(value, dict) and value.get('text') and value.get('evidence'):
            result['fields'][field] = dict(status='expressed', text=value['text'], evidence=value['evidence'])
        else:
            result['fields'][field] = {'status':'not_expressed'}
    if activity == 'plan': result['plan_structure'] = deepcopy(unit.get('plan_structure'))
    return result


def template(store, graph_id, focus, window_id=None):
    graph = graph_store.read(store, graph_id); run = source(store, graph)
    node = next((n for n in graph['nodes'] if n['id'] == focus), None)
    if not node or node['kind'] not in {'unit', 'event'}:
        raise InputError('Choose a source event or contribution to review')
    event_id = node['properties']['id'] if node['kind'] == 'event' else node['properties']['source']['event_id']
    all_choices = [w for w in sem.windows(run) if w['event_id'] == event_id]
    choices = all_choices
    if window_id:
        choices = [w for w in choices if w['id'] == window_id]
    elif node['kind'] == 'unit':
        ref = node['properties']['source']
        choices = [w for w in choices if w['start'] <= ref['start'] < ref['end'] <= w['end']]
    if not choices: raise InputError('This source has no eligible agent contribution window')
    w = choices[0]; original = in_window(graph, w)
    units = [editable(run, n['properties']) for n in original]
    issue = None
    try:
        refs = sem.partition(run, w, units)
        if any(not r['text'].strip() for r in refs): raise InputError('Blank unit')
    except InputError:
        units = [dict(start=w['start'], end=w['end'], activity='unresolved', fields={})]
        issue = 'Existing segmentation is incomplete or overlapping. Review this whole source window before classifying it.'
    return dict(schema=VERSION, document=dict(schema=VERSION, base_graph_id=graph_id,
        window_id=w['id'], revision={'author':'', 'note':''}, units=units), window=w,
        windows=all_choices, original_units=original, issue=issue, activities=sem.ACTIVITIES,
        fields={a: {'summary':'Faithful summary', **sem.FIELDS.get(a, {}),
                   **({} if a == 'social' else {'work_target':'Immediate work or question, in natural language'})}
                for a in sem.ACTIVITIES if a not in {'other','unresolved'}},
        activity_standard=base_standard.VERSION, limit=LIMIT)


def finish(g):
    g.pop('id', None)
    g['nodes'].sort(key=lambda n:n['id']); g['edges'].sort(key=lambda e:e['id'])
    g['counts'] = dict(nodes=len(g['nodes']), edges=len(g['edges']),
        unresolved_endpoints=sum(n['kind']=='unresolved_reference' for n in g['nodes']))
    return {'id':'graph-'+digest(g), **g}


def edge(a, b, kind, properties):
    e = dict(source=a, target=b, type=kind, properties=properties)
    return dict(id='edge-'+digest(e), **e)


def references(value, invalid, key=''):
    """Explicit graph IDs in nested proof records, never free-text similarity."""
    if isinstance(value,dict):return any(references(v,invalid,k) for k,v in value.items())
    if isinstance(value,list):return any(references(v,invalid,key) for v in value)
    return (isinstance(value,str) and value in invalid and
            (key.endswith(('_id','_ids')) or key in {'from','to','source','target','via_action'}))


def fork(run, graph, document):
    graph_store.validate(graph)
    if digest(run) != graph['source_hash'] or any(n['kind'] not in KINDS for n in graph['nodes']):
        raise InputError('Use the original source-bound observation graph')
    d = deepcopy(document)
    if (not isinstance(d, dict) or set(d) != {'schema','base_graph_id','window_id','revision','units'}
            or d['schema'] != VERSION or d['base_graph_id'] != graph['id']
            or not relation_reviews.named(d['revision']) or not isinstance(d['units'], list)
            or not 1 <= len(d['units']) <= 100):
        raise InputError('Unit review needs an exact graph/window, named rationale and 1–100 units')
    w = window(run, d['window_id']); event = sem.checked_span(run, w)
    for u in d['units']:
        if (not isinstance(u, dict) or not {'start','end','activity','fields'} <= set(u)
                or set(u) - {'start','end','activity','fields','plan_structure'}
                or not isinstance(u['activity'], str) or u['activity'] not in sem.ACTIVITIES
                or not isinstance(u['fields'], dict)):
            raise InputError('Each contribution needs boundaries, one base activity and its content fields')
    if w['kind'] == 'action_dispatch' and (len(d['units']) != 1 or
            d['units'][0].get('start') != w['start'] or d['units'][0].get('end') != w['end']):
        raise InputError('A native action dispatch is indivisible')
    refs = sem.partition(run, w, d['units'])
    originals = in_window(graph, w); preserved = set(); additions = []
    for item, ref in zip(d['units'], refs):
        if not ref['text'].strip(): raise InputError('Empty contribution is not a semantic unit')
        matches = [n for n in originals if item == editable(run, n['properties'])]
        if len(matches) == 1:
            preserved.add(matches[0]['id']); continue
        activity = item['activity']
        if activity in {'unresolved','other'}:
            if item['fields'] or 'plan_structure' in item:
                raise InputError('Unresolved/other units must not assert category-specific content')
        else:
            req = sem.generation_request(run, ref, activity)
            candidate = {'fields':item['fields']}
            if 'plan_structure' in item: candidate['plan_structure'] = item['plan_structure']
            try:
                sem.validate_proposals(run, req, dict(request_hash=digest(req), producer=VERSION, candidates=[candidate]))
                def check_context(value):
                    if isinstance(value, dict):
                        if 'event_id' in value:
                            cited = sem.checked_span(run, value, ref)
                            if cited.get('copied_context') or cited.get('context_id') != event.get('context_id'):
                                raise InputError('Evidence is outside this contribution context')
                        for part in value.values(): check_context(part)
                    elif isinstance(value, list):
                        for part in value: check_context(part)
                check_context(candidate)
            except (KeyError, TypeError, AttributeError) as exc:
                raise InputError('Malformed source-bound content') from exc
        unit = dict(source=ref, actor=event['actor'], trajectory_id=event['trajectory_id'],
            kind='action' if w['kind']=='action_dispatch' else 'semantic', activity=activity,
            content=deepcopy(item['fields']), status='needs_activity_review' if activity in {'other','unresolved'} else 'selected',
            boundary_origin=VERSION, boundary_reason=d['revision']['note'],
            provenance={'kind':'named_review', 'schema':VERSION, **d['revision']})
        if 'plan_structure' in item: unit['plan_structure'] = deepcopy(item['plan_structure'])
        unit['id'] = 'review-unit-'+digest([graph['source_hash'], unit])[:24]
        additions.append(dict(id=unit['id'], kind='unit', activity=activity,
            trajectory_id=event['trajectory_id'], event_index=event['index'], properties=unit))
    removed = {n['id'] for n in originals} - preserved
    if not removed and not additions: raise InputError('No unit boundary, activity or content changed')
    oldctx = graph.get('semantic_context') or {}
    # These observations do not declare complete dependency identities. Invalidate
    # the layers rather than retain stale negative coverage or candidate decisions.
    ctx = deepcopy(oldctx)
    cleared = {k:ctx.pop(k) for k in ('work_scopes','work_observations','feedback_observations','contribution_scope','procedure_reviews','requested_check_observations') if k in ctx}
    if 'contribution_scope' in cleared:
        ctx['review_notes'] = [n for n in ctx.get('review_notes', []) if n.get('basis') != 'contribution-scope-graph/1']
    work = ctx.pop('work_subjects', None); relations = ctx.pop('relationship_reviews', None)
    if relations: relation_reviews.checked(graph)
    derived = {n['id'] for n in graph['nodes'] if n['kind'] in {'work_scope','work_subject'}}
    derived.update(e['target'] for e in graph['edges'] if e['type']=='contains_plan_step' and e['source'] in removed)
    invalid = removed | derived
    edges = {e['id']:e for e in graph['edges'] if e['properties'].get('basis') != relation_reviews.VERSION}
    if relations: edges.update({e['id']:e for e in relations.get('suppressed_edges', [])})
    dropped = [e for e in edges.values() if e['source'] in invalid or e['target'] in invalid
               or e['type'] in {'same_action_target','different_work_same_subject'}
               or e['properties'].get('scope_layer') == 'contribution-scope-graph/1']
    dropped_ids = {e['id'] for e in dropped}
    # A response/request edge can depend on a changed action even when neither
    # endpoint changes. Follow explicit proof dependencies through derived edges.
    while True:
        more={e['id'] for e in edges.values() if e['id'] not in dropped_ids
              and references(e.get('properties',{}),invalid|dropped_ids)}
        if not more:break
        dropped_ids.update(more)
    g = deepcopy(graph); g['nodes'] = [n for n in g['nodes'] if n['id'] not in invalid] + additions
    g['edges'] = [e for e in edges.values() if e['id'] not in dropped_ids]
    for n in additions:
        g['edges'].append(edge(n['id'], 'event:'+event['id'], 'grounded_in', {'basis':'source_span','source':n['properties']['source']}))
        for step in (n['properties'].get('plan_structure') or {}).get('steps', []):
            sid = n['id']+':'+step['id']
            g['nodes'].append(dict(id=sid, kind='plan_step', activity=None, trajectory_id=event['trajectory_id'], event_index=event['index'], properties=step))
            g['edges'].append(edge(n['id'], sid, 'contains_plan_step', {'basis':VERSION}))
    # Reconstruct only native action/result correspondence, never semantic links.
    if w['kind']=='action_dispatch' and len(additions)==1:
        for e in graph['edges']:
            if e['type']!='response_to' or e['target']!='event:'+event['id']: continue
            feedback = [n for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='feedback'
                        and 'event:'+n['properties'].get('source',{}).get('event_id','') == e['source']]
            if len(feedback)==1:
                g['edges'].append(edge(feedback[0]['id'], additions[0]['id'], 'feedback_for', {'basis':'native_response_to','native_edge_id':e['id']}))
    previous = ctx.get('unit_reviews', {})
    base_observer = previous.get('base_observer') or (work or {}).get('base_observer') or (relations or {}).get('base_observer') or graph['observer']
    base_label = previous.get('base_label', graph['observer_label'])
    g['observer'] = 'unit-review-'+digest([VERSION,base_observer])[:20]
    g['observer_label'] = 'Reviewed units · '+base_label
    impact = dict(dependency_policy=DEPENDENCY_POLICY,replaced_unit_ids=sorted(removed), new_unit_ids=[n['id'] for n in additions],
        removed_edge_ids=sorted(dropped_ids), invalidated_layers=sorted(cleared),
        removed_work_subject_ids=[], removed_work_bindings=[], removed_relationship_reviews=[])
    ctx['unit_reviews'] = dict(schema=VERSION, base_observer=base_observer, base_label=base_label,
        root_graph_id=previous.get('root_graph_id', graph['id']), previous_graph_id=graph['id'],
        document=d, impact=impact, limit=LIMIT)
    g['semantic_context'] = ctx
    g['annotation_hash'] = digest([graph['annotation_hash'], d])
    g['coverage'] = {**g['coverage'], 'semantic_relations':'partial', 'unit_reviews':'partial'}
    g = finish(g)
    if work:
        wd = deepcopy(work['document'])
        if wd['schema'] in {work_subjects.SELECTED_VERSION, work_subjects.DERIVED_VERSION}:
            # Later membership requests depend on earlier contents and choices.
            # Any base-unit repair invalidates the automatic layer, including
            # negative/unresolved decisions. Keep independent named reviews only.
            impact['invalidated_layers'].append('automatic_work_membership')
            automatic = {r['unit_id'] for r in wd['bindings'] if r['provenance']['kind'] in {'jev_raw_argmax','unavailable','pair_derivation'}}
            removed_work = removed | automatic
            wd['schema'] = work_subjects.VERSION; wd.pop('selection', None); wd.pop('derivation', None)
        else: removed_work = removed
        gone = {s['id'] for s in wd['subjects'] if s['origin_unit_id'] in removed_work}
        impact['removed_work_subject_ids'] = sorted(gone)
        impact['removed_work_bindings'] = [r['unit_id'] for r in wd['bindings'] if r['unit_id'] in removed_work or r['subject_id'] in gone]
        wd['subjects'] = [s for s in wd['subjects'] if s['id'] not in gone]
        wd['bindings'] = [r for r in wd['bindings'] if r['unit_id'] not in impact['removed_work_bindings']]
        g['semantic_context']['unit_reviews']['impact'] = deepcopy(impact); g = finish(g)
        wd['base_graph_id'] = g['id']; g = work_subjects.fork(g, wd)
    if relations:
        rd = deepcopy(relations['document']); keep=[]
        for row in rd['reviews']:
            try: relation_reviews.endpoints(g,row)
            except InputError: impact['removed_relationship_reviews'].append(row)
            else: keep.append(row)
        g['semantic_context']['unit_reviews']['impact'] = deepcopy(impact); g = finish(g)
        rd['reviews'] = keep; rd['base_graph_id'] = g['id']; g = relation_reviews.fork(g,rd)
    # Some work-subject edges were rebuilt unchanged; only report connections
    # actually absent from the resulting graph, including removed manual edges.
    impact['removed_edge_ids'] = sorted({e['id'] for e in graph['edges']} - {e['id'] for e in g['edges']})
    g['semantic_context']['unit_reviews']['impact'] = deepcopy(impact)
    return finish(g)


def preview(store, document):
    if not isinstance(document, dict) or not isinstance(document.get('base_graph_id'), str):
        raise InputError('Missing unit review base graph')
    graph = graph_store.read(store, document['base_graph_id'])
    result = fork(source(store, graph), graph, document)
    from . import annotation_changes
    try:
        changes = annotation_changes.summary(annotation_changes.compare(graph, result))
    except InputError:
        # A legacy overlapping annotation can still be corrected. Do not invent
        # a comparable baseline or block its repair because alignment is unsafe.
        changes = {'status':'unavailable', 'reason':'The original graph cannot be aligned exactly; the correction remains available.'}
    return dict(graph_id=result['id'], observer=result['observer'], run_id=result['run_id'],
        base_graph_id=graph['id'], impact=result['semantic_context']['unit_reviews']['impact'],
        annotation_changes=changes, new_model_calls=0, limit=LIMIT)


def receive(store, document):
    expected = preview(store, document)
    graph = graph_store.read(store, document['base_graph_id'])
    result = fork(source(store, graph), graph, document)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        exists = c.execute('SELECT 1 FROM rollout_graphs WHERE id=?',(result['id'],)).fetchone()
        latest = c.execute('SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? ORDER BY rowid DESC LIMIT 1',
                           (result['run_id'],result['observer'])).fetchone()
        if not exists and latest and latest[0] != graph['id']:
            raise InputError('Unit review changed; open the latest reviewed graph before editing')
        graph_store.save(c,result)
    return expected


def continue_monitor(store, graph_id, monitor_id):
    """Keep the same measure/population while opting into a reviewed observer."""
    from . import monitoring
    graph = graph_store.read(store, graph_id)
    if not (graph.get('semantic_context') or {}).get('unit_reviews'):
        raise InputError('Choose a graph with a saved unit review')
    with store.connect() as c:
        row = c.execute('SELECT document FROM monitors WHERE id=?',(monitor_id,)).fetchone()
    if not row: raise InputError('Original monitor is unavailable')
    definition = json.loads(row[0])
    if definition['kind'] not in {'analysis','graph'}:
        raise InputError('Unit correction continues graph or analysis measurements')
    definition['observer'] = graph['observer']
    definition['name'] = 'Reviewed · '+definition['name'].removeprefix('Reviewed · ')[:189]
    return dict(monitor=monitoring.create(store,definition), original_monitor_id=monitor_id,
                graph_id=graph_id, new_model_calls=0)
