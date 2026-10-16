"""Lift saved, source-bound relationships onto contribution work visits.

This is a lossless view projection, not a new semantic observer. It never changes
visit membership, the recurrence denominator or the source graph. Connections
retain the contributing units; a relation inside one visit is not a transition.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from .schema import digest
from . import work_subjects

VERSION = 'work-route-context/3'
TARGET_RELATIONS = {
    'same_work_target': ('target', 'Same question or outcome'),
    'overlapping_work_scope': ('target', 'Partly shared work'),
    'different_work_same_subject': ('target', 'Different work on the same subject'),
    'similar_operation_distinct_target': ('target', 'Different task instance'),
}
STAGES = {'attempts_plan_step', 'prepares_plan_step', 'checks_plan_step'}
DECLARED = {'attempts_declared_work', 'prepares_declared_work', 'checks_declared_work'}
DECLARATIONS = {'commits':'Undertaking', 'proposes':'Proposal', 'defers':'Deferred work',
                'withdraws':'Withdrawn work', 'reports_finished':'Completion claim',
                'reports_blocked':'Reported blockage'}
RELATIONS = {
    'in_work_scope': ('scope', 'Refers to expressed scope'),
    'attempts_plan_step': ('scope', 'Attempts plan step'),
    'prepares_plan_step': ('scope', 'Prepares plan step'),
    'checks_plan_step': ('scope', 'Checks plan step'),
    'attempts_requested_work': ('scope', 'Attempts requested work'),
    'prepares_requested_work': ('scope', 'Prepares requested work'),
    'attempts_declared_work': ('scope', 'Attempts stated work'),
    'prepares_declared_work': ('scope', 'Prepares stated work'),
    'checks_declared_work': ('scope', 'Checks stated work'),
    'assesses': ('feedback', 'Assesses'),
    'uses_evidence': ('feedback', 'Uses evidence'),
    'responds_to': ('feedback', 'Responds to'),
    'revises': ('revision', 'Revises'),
    'attempts_local_adjustment': ('revision', 'Attempts stated adjustment'),
    'prepares_stated_check': ('revision', 'Prepares stated check'),
    'attempts_stated_check': ('revision', 'Attempts stated check'),
}
LIMIT = ('Connections preserve saved relation types and exact source endpoints. Scope references do not '
         'establish authorization or goal deviation; attempts/checks do not establish completion. '
         'Assessment of a response is not proof of appropriate feedback use. Native reasoning labels '
         'retain their namespace. Missing or rejected relationships remain unestablished. Membership '
         'and plan-stage badges apply only to the named contributions within a visit.')


def enrich(graph, route, *, only_declared=False, target_relations=False):
    out = deepcopy(route)
    from . import map_relationships
    rejected={r['edge_id']:r for r in map_relationships.inspect(graph)['relationships'] if r['status']=='incompatible'}
    nodes = {n['id']: n for n in graph['nodes']}
    events, eligible_units, _, _ = work_subjects.evidence_index(graph)
    unit_visit = {uid: v['id'] for v in out['visits'] for uid in v['unit_ids']}
    visits = {v['id']: v for v in out['visits']}
    edges = graph['edges']; anchors = {}; contexts = {}; issues = []; connections = []
    scope_rows = defaultdict(list); stage_rows = defaultdict(list)
    relations = {**RELATIONS, **(TARGET_RELATIONS if target_relations else {})}

    def span(ref):
        if not isinstance(ref, dict): return None
        event = events.get(ref.get('event_id')); a, b = ref.get('start'), ref.get('end')
        if (not event or event.get('copied_context') or event.get('agent_visibility') == 'not_established'
                or event['kind'].startswith('external_') or type(a) is not int or type(b) is not int
                or not 0 <= a < b <= len(event['text']) or not event['text'][a:b].strip()
                or 'text' in ref and event['text'][a:b] != ref['text']): return None
        return event

    def source(nid): return nodes.get(nid, {}).get('properties', {}).get('source', {})

    def valid(nid):
        n = nodes.get(nid, {}); e = span(source(nid))
        if not e or n.get('kind') not in {'unit', 'work_scope'}: return False
        if n['kind'] == 'unit' and n['properties'].get('actor') == 'agent':
            return nid in eligible_units
        return True

    def same_context(a, b):
        return a['trajectory_id'] == b['trajectory_id'] and a.get('context_id') == b.get('context_id')

    def before(a, b, *, equal=False):
        ea, eb = span(source(a)), span(source(b))
        if not ea or not eb or not same_context(ea, eb): return False
        if equal and source(a) == source(b): return True
        # A renderer's order for simultaneous dispatch siblings is not causality.
        if (ea['kind'] == eb['kind'] == 'action' and ea.get('parent_id') and
                ea.get('parent_id') == eb.get('parent_id')): return False
        sa, sb = source(a), source(b)
        return ea['index'] < eb['index'] or ea['index'] == eb['index'] and sa['end'] <= sb['start']

    def available(edge, at):
        p = edge['properties']; cutoff = p.get('cutoff'); refs = []
        if cutoff is not None:
            if not isinstance(cutoff, dict): return False
            refs.append({**cutoff, 'start': cutoff.get('start', 0)})
        inspector = p.get('inspector_context') or {}
        if not isinstance(inspector, dict): return False
        for values in [p.get('evidence', []), p.get('context_evidence', []), inspector.get('source_ranges', [])]:
            if not isinstance(values, list): return False
            refs += values
        end = source(at); target_event = span(end)
        for ref in refs:
            e = span(ref)
            if not e or not same_context(e, target_event) or (e['index'], ref['end']) > (target_event['index'], end['end']):
                return False
        return True

    def anchor(nid):
        """A visible request is context, never an extra activity/visit."""
        s = source(nid); e = span(s); n = nodes[nid]; p = n['properties']
        if e['actor'] not in {'user', 'context'}: return None
        # Native flat reasoning exports can record the prompt as context, with
        # several reference spans. Group its origin record for display only;
        # retain the exact referenced spans and original actor separately.
        aid = 'work-context-' + digest([s['event_id']])
        if aid not in anchors:
            anchors[aid] = dict(id=aid, kind='request' if e['actor']=='user' else 'source_context', label=s['text'],
                source=deepcopy(s), source_spans=[], source_actor=e['actor'], source_node_ids=[], trajectory_id=e['trajectory_id'],
                context_id=e.get('context_id'), event_index=e['index'])
        if s not in anchors[aid]['source_spans']: anchors[aid]['source_spans'].append(deepcopy(s))
        if nid not in anchors[aid]['source_node_ids']: anchors[aid]['source_node_ids'].append(nid)
        return aid

    def endpoint(nid):
        if nid in unit_visit: return unit_visit[nid]
        n = nodes[nid]
        if n['kind'] == 'work_scope' and n['properties'].get('scope_kind') == 'organized_plan':
            origins = [u for u in n['properties'].get('source_unit_ids', [])
                       if u in unit_visit and source(u) == source(nid) and eligible_units[u].get('activity') == 'plan']
            return unit_visit[origins[0]] if len(origins) == 1 else None
        return anchor(nid)

    feedback = defaultdict(list)
    for e in edges:
        if (e['type'] == 'feedback_for' and valid(e['source']) and e['target'] in unit_visit
                and eligible_units[e['target']].get('kind') == 'action'
                and nodes[e['source']]['properties'].get('kind') == 'feedback'
                and before(e['target'], e['source']) and available(e, e['source'])):
            feedback[e['source']].append(e)

    for e in edges:
        kind = e['type']; native = kind.startswith('reasoningflow:backref:')
        if only_declared and kind not in DECLARED: continue
        if kind not in relations and not native: continue
        if e['id'] in rejected:
            issues.append(dict(edge_id=e['id'],reason=rejected[e['id']]['reason']));continue
        a, b = e['source'], e['target']; properties = e['properties']
        if kind in TARGET_RELATIONS and (properties.get('protocol') != 'contribution-scope-pairs/2' or
                properties.get('scope_layer') != 'contribution-scope-graph/1'): continue
        if a not in unit_visit or not valid(b) or not before(b, a, equal=kind == 'in_work_scope') or not available(e, a):
            issues.append(dict(edge_id=e['id'], reason='Relationship endpoints, visible context or prefix evidence are unsupported'))
            continue
        family, label = ('native', 'Native reference · ' + kind.removeprefix('reasoningflow:backref:')) if native else relations[kind]
        witnesses = [a, b]; edge_ids = [e['id']]; step = None; stated_work = None
        source_form = 'recorded_dispatch' if eligible_units[a]['kind'] == 'action' else 'agent_prose'
        if native and (source_form != 'agent_prose' or nodes[b]['properties'].get('kind') == 'action'):
            issues.append(dict(edge_id=e['id'], reason='Native reasoning reference requires text endpoints, not a dispatched action'))
            continue
        if kind in DECLARED:
            # This contract is specifically dispatch-to-statement correspondence.
            # A matching prose unit or a completion claim cannot supply dispatch.
            if (source_form != 'recorded_dispatch' or b not in eligible_units or
                    eligible_units[b]['kind'] != 'semantic' or
                    properties.get('declaration_at_dispatch') not in DECLARATIONS or
                    any(not isinstance(properties.get(k), str) or not properties[k].strip()
                        for k in ('declared_work_id', 'to_item_id', 'work_text'))):
                issues.append(dict(edge_id=e['id'], reason='Stated-work link needs a recorded dispatch and an attributed work item'))
                continue
            stated_work = dict(record_id=properties['declared_work_id'], item_id=properties['to_item_id'],
                text=properties['work_text'], declaration=properties['declaration_at_dispatch'],
                declaration_label=DECLARATIONS[properties['declaration_at_dispatch']],
                declaration_unit_id=b, action_unit_id=a)
        if kind in STAGES:
            p = nodes[b]['properties']; candidates = [s for s in (p.get('plan_structure') or {}).get('steps', []) if s.get('id') == properties.get('plan_step_id')]
            if p.get('activity') != 'plan' or len(candidates) != 1:
                issues.append(dict(edge_id=e['id'], reason='Selected plan step is missing or not a Plan unit')); continue
            step = deepcopy(candidates[0])
            if not step.get('evidence') or not available({'properties': {'evidence': step['evidence']}}, b):
                issues.append(dict(edge_id=e['id'], reason='Plan step lacks source-bound evidence at its declaration')); continue
        target = endpoint(b)
        if not target and stated_work:
            # Action-only routes still need an inspectable statement origin.
            # This is a source context card, not another action or inferred visit.
            s = source(b); event = span(s)
            target = 'work-declaration-' + digest([b, stated_work['record_id'], stated_work['item_id']])
            origin = dict(id=target, kind='stated_work', label=stated_work['text'],
                declaration=stated_work['declaration'], declaration_label=stated_work['declaration_label'],
                source=deepcopy(s), source_spans=[deepcopy(s)], source_actor=event['actor'],
                source_node_ids=[b], trajectory_id=event['trajectory_id'], context_id=event.get('context_id'),
                event_index=event['index'])
            if target in anchors and anchors[target] != origin:
                issues.append(dict(edge_id=e['id'], reason='Stated-work identity has conflicting text or attribution'))
                continue
            anchors[target] = origin
        if nodes[b]['properties'].get('kind') == 'feedback':
            origins = feedback[b]
            if len(origins) != 1:
                issues.append(dict(edge_id=e['id'], reason='Feedback has no unique supported originating action')); continue
            origin = origins[0]
            if not available(origin, a):
                issues.append(dict(edge_id=e['id'], reason='Feedback bridge uses unavailable evidence')); continue
            target = unit_visit[origin['target']]; edge_ids.append(origin['id']); witnesses.append(origin['target'])
            label += ' feedback from'
        if not target:
            issues.append(dict(edge_id=e['id'], reason='Relationship target has no visit or supported context origin')); continue
        value = dict(type='work_relation', relation_type=kind, family=family, label=label,
            source=unit_visit[a], target=target, source_unit_id=a, target_node_id=b,
            node_ids=list(dict.fromkeys(witnesses)), edge_ids=edge_ids, step=step,
            explanation=properties.get('explanation'), within_visit=unit_visit[a] == target,
            source_form=source_form, stated_work=stated_work)
        if native:
            value['interpretation_note'] = ('Publisher-defined relationship between text contributions. '
                'A native execute label does not establish a tool dispatch, environment effect or successful check.')
        elif stated_work:
            value['interpretation_note'] = ('Saved correspondence between this recorded dispatch and this attributed statement. '
                'The statement may be a proposal, withdrawal or completion claim; correspondence does not establish current adoption, authorization or success.')
        else:
            value['interpretation_note'] = ('The referring evidence is '+('a recorded dispatch' if source_form == 'recorded_dispatch' else 'an agent text contribution')+
                '. The saved relationship is an interpretation of that evidence, not proof of an environment effect or successful outcome.')
        link = dict(id='work-link-' + digest(value), **value); connections.append(link)
        if kind == 'in_work_scope':
            contexts[b] = deepcopy(nodes[b])
            scope_rows[a].append(dict(unit_id=a, scope_id=b, edge_id=e['id'], connection_id=link['id']))
        if step:
            stage_rows[a].append(dict(unit_id=a, plan_unit_id=b, step_id=step['id'], text=step['text'],
                target=step.get('target'), role=kind, edge_id=e['id'], connection_id=link['id']))

    for v in out['visits']:
        if not only_declared:
            v['scope_memberships'] = [r for uid in v['unit_ids'] for r in scope_rows[uid]]
            v['scope_ids'] = sorted({r['scope_id'] for r in v['scope_memberships']})
            v['plan_stages'] = [r for uid in v['unit_ids'] for r in stage_rows[uid]]
        v['connection_ids'] = [r['id'] for r in connections if v['id'] in (r['source'], r['target'])]
    out['links'].extend(connections)
    if not only_declared: out['scopes'] = [contexts[k] for k in sorted(contexts)]
    used = {c['target'] for c in connections}
    out['context_nodes'] = sorted((a for a in anchors.values() if a['id'] in used), key=lambda a:(a['event_index'], a['id']))
    for a in out['context_nodes']:
        a['source_spans'].sort(key=lambda s:(s['start'],s['end']))
        if a['kind'] != 'stated_work': a['label'] = ' … '.join(s['text'].strip() for s in a['source_spans'])
    out['context'] = dict(schema=VERSION+('|target-pairs/2' if target_relations else ''), limit=LIMIT, issues=issues,
        counts=dict(Counter(c['family'] for c in connections)), relations=len(connections),
        within_visit=sum(c['within_visit'] for c in connections), unprojected=len(issues))
    # The caller supplies its operation version and recalculates the route ID.
    return out
