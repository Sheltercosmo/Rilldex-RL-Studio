"""Researcher checks and returned evidence on immutable investigation revisions.

This is bookkeeping, not a diagnosis engine or an experiment runner. References
are resolved by the server; clients cannot supply substitute measurements.
"""
from copy import deepcopy
import json

from . import continuation_studies, failure_investigations, graph_store
from .schema import InputError, digest

VERSION = 'investigation-followups/1'
ASSESSMENTS = {'supports', 'contradicts', 'inconclusive', 'not_run'}
SCHEMAS = {'failure-investigation/1', 'training-investigation/1', 'interval-investigation/1'}


def text(value, label, limit=6000, required=True):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise InputError('Invalid ' + label)
    return value.strip()


def fields(raw, required, optional=()):
    if not isinstance(raw, dict) or set(raw) - set(required) - set(optional) or set(required) - set(raw):
        raise InputError('Unexpected or missing follow-up fields')


def evidence(store, refs):
    if not isinstance(refs, list) or len(refs) > 8:
        raise InputError('Choose up to eight evidence references')
    result = []; seen = set()
    for ref in refs:
        if not isinstance(ref, dict): raise InputError('Invalid evidence reference')
        kind = ref.get('kind')
        if kind == 'investigation':
            fields(ref, ('kind', 'id'))
            identifier = text(ref['id'], 'saved investigation', 120)
            try: doc = failure_investigations.read(store, identifier)
            except KeyError as error:
                raise InputError('Saved comparison not found. Save the comparison first, then copy its link.') from error
            if doc['schema'] not in SCHEMAS: raise InputError('Unsupported investigation evidence')
            item = {'kind': kind, 'id': identifier, 'title': doc['title'], 'schema': doc['schema'],
                    'snapshot_id': doc['snapshot']['snapshot_id'],
                    'scope': deepcopy(doc.get('scope', doc['snapshot'].get('controls', {})))}
        elif kind == 'continuation':
            fields(ref, ('kind', 'producer', 'experiment', 'study_id', 'snapshot_id'))
            for key in ('producer', 'experiment', 'study_id', 'snapshot_id'):
                text(ref[key], key, 512)
            with store.connect() as c:
                c.execute('BEGIN')
                row = c.execute('SELECT document FROM continuation_studies WHERE producer=? AND experiment=? AND study_id=?',
                                (ref['producer'], ref['experiment'], ref['study_id'])).fetchone()
                if not row: raise InputError('Recorded continuation study not found')
                projection = continuation_studies.project(c, ref['producer'], ref['experiment'], json.loads(row[0]))
            if projection['snapshot_id'] != ref['snapshot_id']:
                raise InputError('Continuation evidence changed. Reload and review before attaching.')
            item = {'kind': kind, 'id': projection['snapshot_id'], 'title': projection['design']['label'],
                    'snapshot': projection}
        elif kind == 'behavior_case':
            from .investigation_cases import resolve
            item = resolve(store, ref)
        elif kind == 'evaluation':
            from .evaluation_receipts import resolve
            item = resolve(store, ref)
        elif kind == 'training_exposure':
            from .training_exposure import resolve
            item = resolve(store, ref)
        elif kind == 'unit':
            fields(ref, ('kind', 'graph_id', 'unit_id'))
            try: graph = graph_store.read(store, text(ref['graph_id'], 'graph identity', 120))
            except KeyError as error:
                raise InputError('Pinned graph not found. Open an available behavior map and copy the selected unit link.') from error
            unit_id = text(ref['unit_id'], 'unit identity', 256)
            unit = next((n for n in graph['nodes'] if n['id'] == unit_id), None)
            if unit is None: raise InputError('Unit is outside the selected graph')
            if unit['kind'] != 'unit': raise InputError('Select an annotated unit. Source events, plan steps and unresolved references are not units.')
            item = {'kind': kind, 'id': digest(ref), 'title': 'Unit ' + unit_id,
                    'graph_id': ref['graph_id'], 'unit_id': unit_id, 'run_id': graph['run_id'],
                    'observer': graph['observer'], 'graph_digest': graph['id'].removeprefix('graph-'), 'unit': unit}
        else: raise InputError('Choose a saved comparison, behavior case, rollout unit, evaluation, training use or continuation evidence')
        identity = (kind, item['id'])
        if identity in seen: raise InputError('Duplicate evidence reference')
        seen.add(identity); result.append(item)
    return result


def save(store, raw):
    fields(raw, ('parent_id', 'action', 'check'))
    parent = failure_investigations.read(store, text(raw['parent_id'], 'parent identity', 120))
    if parent['schema'] not in SCHEMAS: raise InputError('Unsupported investigation')
    flow = deepcopy(parent.get('follow_up', {'schema': VERSION, 'root_id': parent['id'], 'checks': []}))
    if flow['schema'] != VERSION: raise InputError('Unsupported follow-up version')
    raw_check = raw['check']
    if raw['action'] == 'plan':
        fields(raw_check, ('title', 'hypothesis', 'procedure', 'expected_result'), ('controls', 'follows_check'))
        plan = {key: text(raw_check[key], key, 160 if key == 'title' else 6000)
                for key in ('title', 'hypothesis', 'procedure', 'expected_result')}
        plan['controls'] = text(raw_check.get('controls', ''), 'controls', required=False)
        follows = raw_check.get('follows_check')
        if follows is not None and (not isinstance(follows, str) or follows not in {c['id'] for c in flow['checks']}):
            raise InputError('Previous check is outside this investigation')
        plan.update(basis_id=parent['id'], follows_check=follows)
        plan['id'] = 'check-' + digest(plan)
        if len(flow['checks']) >= 32: raise InputError('At most 32 checks per investigation')
        flow['checks'].append({**plan, 'results': []})
    elif raw['action'] == 'result':
        fields(raw_check, ('id', 'assessment', 'conclusion', 'evidence'), ('limitations', 'next_action'))
        check = next((c for c in flow['checks'] if c['id'] == raw_check['id']), None)
        if check is None: raise InputError('Check is outside this investigation')
        assessment = raw_check['assessment']
        if not isinstance(assessment, str) or assessment not in ASSESSMENTS: raise InputError('Invalid assessment')
        result = {'assessment': assessment, 'conclusion': text(raw_check['conclusion'], 'conclusion'),
                  'limitations': text(raw_check.get('limitations', ''), 'limitations', required=False),
                  'next_action': text(raw_check.get('next_action', ''), 'next action', required=False),
                  'evidence': evidence(store, raw_check['evidence'])}
        if assessment in {'supports', 'contradicts'} and not result['evidence']:
            raise InputError('A supporting or contradicting finding needs linked evidence')
        if assessment == 'not_run' and result['evidence']:
            raise InputError('Use an inconclusive finding when reviewing evidence; not run has no results')
        from .evaluation_receipts import attached_comparisons
        comparisons = attached_comparisons(result['evidence'])
        if comparisons: result['evaluation_comparisons'] = comparisons
        result['id'] = 'finding-' + digest(result)
        if any(r['id'] == result['id'] for r in check['results']): return parent
        if len(check['results']) >= 32: raise InputError('At most 32 findings per check')
        check['results'].append(result)
    else: raise InputError('Choose plan or result')
    value = {k: deepcopy(v) for k, v in parent.items() if k != 'id'}
    value.update(parent_id=parent['id'], follow_up=flow)
    return failure_investigations.persist(store, value)


def revisions(store, identifier):
    failure_investigations.read(store, identifier)
    with store.connect() as c:
        rows = c.execute("SELECT id, json_extract(document,'$.title'), created_at FROM failure_investigations "
                         "WHERE json_extract(document,'$.parent_id')=? ORDER BY created_at,id LIMIT 101", (identifier,)).fetchall()
    return {'revisions': [{'id': r[0], 'title': r[1], 'created_at': r[2]} for r in rows[:100]],
            'more': len(rows) > 100}


def bundle(store, identifier):
    """Export exact stored comparisons referenced by checks, without live refresh.

    Only direct result references are traversed: those comparisons' own workflows
    are retained as stored, but recursive fetching is bounded out explicitly.
    """
    doc = failure_investigations.read(store, identifier)
    ids = sorted({e['id'] if e['kind']=='investigation' else e['investigation_id']
                  for c in doc.get('follow_up', {}).get('checks', []) for r in c['results'] for e in r['evidence']
                  if e['kind'] in {'investigation','behavior_case'}})
    if len(ids) > 128: raise InputError('Export exceeds 128 linked comparisons; export individual revisions')
    linked = [failure_investigations.read(store, i) for i in ids]
    return {'schema': 'investigation-bundle/1', 'investigation': doc, 'linked_comparisons': linked,
            'boundary': 'Original snapshot and direct linked comparisons. Nested workflows retain references; raw sources and complete graphs remain in the workspace. No live evidence was substituted.'}
