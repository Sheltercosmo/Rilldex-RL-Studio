"""Plan/attempt structure from saved graphs; no new semantic classification.

The same graph identities back overview, units and source inspection. A cutoff
limits visible evidence; it does not assert that retrospective annotations were
produced online. Source order is never promoted into dependency or completion.
"""
from collections import defaultdict
from copy import deepcopy

from .schema import InputError, digest
from .graph_store import validate
from . import work_dispatches

VERSION = 'work-hierarchy/13'
ROLES = {'prepares_plan_step': 'Preparation', 'attempts_plan_step': 'Attempt',
         'checks_plan_step': 'Check'}
RELATIONS = {'assesses': 'Assesses feedback', 'uses_evidence': 'Uses evidence',
    'responds_to': 'Responds to', 'revises': 'Revises',
    'same_action_target': 'Same immediate work target',
    'revisits_after_error_report': 'Returns after error report',
    'completed_after_failed_call': 'Completed call after failed call'}
STATUS = {'pending': 'Reported pending', 'in_progress': 'Reported in progress', 'active': 'Reported in progress',
          'completed': 'Reported complete'}


def text(value):
    return value if isinstance(value, str) else (value or {}).get('text', '')


def build(graph, cutoff_event_id=None):
    validate(graph)
    source = {n['id']: n for n in graph['nodes']}
    events = {n['properties']['id']: n for n in graph['nodes'] if n['kind'] == 'event'}
    if cutoff_event_id is not None and cutoff_event_id not in events:
        raise InputError('Hierarchy cutoff must identify a recorded source event')
    cutoff = events[cutoff_event_id]['event_index'] if cutoff_event_id else max(
        (n['event_index'] for n in events.values()), default=-1)
    visible = {k: n for k, n in source.items() if n.get('event_index') is not None and n['event_index'] <= cutoff}
    items = {}; links = []; roots = []; issues = []; assigned = set()
    from .map_foundation import content_sources
    content_audit=content_sources(graph)
    for row in content_audit['issues']:
        if row['unit_id'] in visible:issues.append(dict(type='invalid_local_content_source',**row))
    excluded=set(content_audit['excluded_unit_ids'])
    excluded.update(e['target'] for e in graph['edges'] if e['type']=='contains_plan_step' and e['source'] in excluded)
    visible={k:n for k,n in visible.items() if k not in excluded}

    def context(n):
        # Semantic units inherit their source context; it need not be copied
        # onto every derived node. A trajectory may contain several contexts.
        event = events.get(n['properties'].get('source', {}).get('event_id'), n)
        return event['properties'].get('context_id')

    def ready(edge):
        if edge['source'] not in visible or edge['target'] not in visible:
            return False
        p = edge.get('properties', {})
        refs = [*p.get('evidence', []), *p.get('context_evidence', [])]
        if p.get('cutoff'): refs.append(p['cutoff'])
        for ref in refs:
            if not isinstance(ref, dict) or 'event_id' not in ref: continue
            if ref['event_id'] not in events or events[ref['event_id']]['event_index'] > cutoff:
                return False
        return True

    from .map_relationships import inspect as inspect_relationships
    relation_audit=inspect_relationships(graph)
    incompatible={r['edge_id']:r for r in relation_audit['relationships'] if r['status']=='incompatible'}
    eligible=[]
    for e in graph['edges']:
        if not ready(e):continue
        if e['id'] in incompatible:
            row=incompatible[e['id']]
            issues.append({**row,'relationship_type':row['type'],'type':'incompatible_relationship'})
        else:eligible.append(e)
    def add(n, kind=None, label=None, state=None):
        p = n['properties']; content = p.get('content', {})
        if n['id'] not in items:
            items[n['id']] = dict(id=n['id'], kind=kind or n['kind'],
                label=label or text(content.get('operation')) or text(content.get('target')) or text(content.get('summary')) or text(p.get('text')) or text(p.get('label')) or n['id'],
                state=state, actor=p.get('actor'), trajectory_id=n.get('trajectory_id'),
                context_id=context(n),
                activity=n.get('activity'), target=text(content.get('target')),
                summary=text(content.get('summary')),
                operation=text(content.get('operation')) or text(content.get('change')),
                event_index=n.get('event_index'), source_node_ids=[n['id']],
                evidence=deepcopy(p.get('evidence') or ([p['source']] if p.get('source') else [])),
                source_text=text(p.get('source', {}).get('text')) or text(p.get('text')),
                history=[])
        return items[n['id']]

    def connect(a, b, kind, label, edge_ids=(), evidence=()):
        row = dict(source=a, target=b, type=kind, label=label,
                   edge_ids=list(edge_ids), evidence=deepcopy(list(evidence)))
        row['id'] = 'hierarchy-edge-' + digest(row)
        if not any(e['id'] == row['id'] for e in links): links.append(row)

    plans = [n for n in visible.values() if n['kind'] == 'unit' and n.get('activity') == 'plan'
             and n['properties'].get('plan_structure')]
    stage_parents = {}
    for plan in sorted(plans, key=lambda n: (n['event_index'], n['id'])):
        row = add(plan, 'plan', state='Expressed plan'); roots.append(row['id'])
        row['criterion'] = deepcopy(plan['properties']['plan_structure']['completion_criterion'])
        for step in plan['properties']['plan_structure']['steps']:
            sid = plan['id'] + ':' + step['id']
            if sid not in visible:
                issues.append(dict(type='missing_plan_step', plan=plan['id'], step=step['id'])); continue
            stage = add(visible[sid], 'plan_step', step['text'], 'No linked attempt observed')
            stage['target'] = step['target']; stage_parents[sid] = plan['id']
            edges = [e['id'] for e in eligible if e['type'] == 'contains_plan_step' and
                     e['source'] == plan['id'] and e['target'] == sid]
            if not edges:
                items.pop(sid); stage_parents.pop(sid)
                issues.append(dict(type='missing_containment', plan=plan['id'], step=sid)); continue
            connect(plan['id'], sid, 'contains', 'Declared step', edges, step['evidence'])
        for org in plan['properties']['plan_structure'].get('links', []):
            a, b = plan['id'] + ':' + org['from'], plan['id'] + ':' + org['to']
            if a in items and b in items:
                connect(a, b, org['kind'], 'Stated order' if org['kind'] == 'precedes' else 'Requires', evidence=org['evidence'])

    actions = {n['id']: n for n in visible.values() if n['properties'].get('kind') == 'action'}
    from .action_comparison import source_resolver
    resolve_action = source_resolver(graph)
    dispatch_ids = {aid: (resolve_action(aid) or {}).get('node_id', aid) for aid in actions}
    role_counts = defaultdict(lambda: defaultdict(set))
    for e in eligible:
        if e['type'] not in ROLES: continue
        target = e['target'] if e['target'] in stage_parents else e['target'] + ':' + str(e['properties'].get('plan_step_id', ''))
        a = actions.get(e['source']); parent = source.get(stage_parents.get(target))
        if not a or not parent: continue
        if (a.get('trajectory_id'), a['properties'].get('actor')) != (parent.get('trajectory_id'), parent['properties'].get('actor')):
            issues.append(dict(type='incompatible_plan_actor_or_trajectory', edge_id=e['id'])); continue
        if context(a) != context(parent):
            issues.append(dict(type='cross_context_plan_action', edge_id=e['id'])); continue
        if (a['event_index'], a['properties'].get('source', {}).get('start', 0)) < (
                parent['event_index'], parent['properties'].get('source', {}).get('end', 0)):
            issues.append(dict(type='action_precedes_plan', edge_id=e['id'])); continue
        add(a, 'action', state='Dispatch recorded')['dispatch_id'] = dispatch_ids[a['id']]
        assigned.add(a['id']); role_counts[target][e['type']].add(dispatch_ids[a['id']])
        connect(target, a['id'], e['type'], ROLES[e['type']], [e['id']], e['properties'].get('evidence', []))
    for sid, roles in role_counts.items():
        counts = {role: len(ids) for role, ids in roles.items()}
        items[sid]['roles'] = dict(counts)
        items[sid]['state'] = ' · '.join(f'{count} {ROLES[k].lower()}{"s" if count != 1 else ""}' for k, count in counts.items())

    for e in eligible:
        if e['type'] not in {'feedback_for', 'response_to'} or e['target'] not in assigned: continue
        response = visible[e['source']]; action = visible[e['target']]
        if response['trajectory_id'] != action['trajectory_id']:
            issues.append(dict(type='cross_trajectory_response', edge_id=e['id'])); continue
        if context(response) != context(action) or response['event_index'] < action['event_index']:
            issues.append(dict(type='incompatible_response_context_or_position', edge_id=e['id'])); continue
        add(response, 'feedback', state='Response recorded')
        connect(action['id'], response['id'], 'response', 'Returned feedback', [e['id']], e['properties'].get('evidence', []))
    # Related commentary is kept as evidence, not silently made into a new plan.
    for e in eligible:
        if e['type'] in {'assesses', 'uses_evidence', 'responds_to'} and e['target'] in items:
            add(visible[e['source']], 'contribution', state='Saved ' + RELATIONS[e['type']].lower())
    for e in eligible:
        if e['type'] in RELATIONS and e['source'] in items and e['target'] in items:
            connect(e['source'], e['target'], e['type'], RELATIONS[e['type']], [e['id']], e['properties'].get('evidence', []))

    native_lists(graph, visible, eligible, items, links, roots)
    from .declared_work_tree import project
    native_tree = project(visible, eligible, items, links, roots)
    # Count the visible agent actions once, preferring annotated units over events.
    covered = {e['target'] for e in eligible if e['type'] == 'grounded_in' and e['source'] in actions}
    all_actions = [n for n in actions.values() if n['id'] not in covered]
    assigned_dispatches = {dispatch_ids[aid] for aid in assigned}
    unassigned = [n['id'] for n in all_actions if dispatch_ids[n['id']] not in assigned_dispatches]
    result = dict(schema=VERSION, graph_id=graph['id'], run_id=graph['run_id'], source_hash=graph['source_hash'],
        cutoff_event_id=cutoff_event_id, cutoff_event_index=cutoff, roots=roots,
        nodes=sorted(items.values(), key=lambda n: (n.get('event_index') or 0, n['id'])), links=links,
        unassigned_action_ids=unassigned, issues=issues,
        records=[dict(id=n['properties']['id'], index=n['event_index'], label=f"Record {n['event_index'] + 1}") for n in sorted(events.values(), key=lambda n:n['event_index'])],
        counts=dict(plans=len(plans), roots=len(roots), plan_steps=len(stage_parents),
                    linked_actions=len(assigned_dispatches), visible_actions=len({dispatch_ids[n['id']] for n in all_actions}),
                    unassigned_actions=len({dispatch_ids[aid] for aid in unassigned})),
        available=bool(roots),
        limits='Plans and links are saved observations, not verified intent, adoption or completion. Unassigned work is not deviation. Native list states are reported by the agent. Cutoff filters recorded evidence; it does not attest online annotation or causal execution order.')
    if native_tree:
        result['declared_tree'] = native_tree
        result['limits'] += ' Hierarchical parentage and record scope come from the named producer. Native control flow is declared structure, not inferred strategy. Child reports are not propagated into verified parent completion.'
    result['stage_paths'] = stage_paths(items, links, stage_parents, all_actions, graph)
    if (graph.get('semantic_context') or {}).get('work_outline'):
        from .work_outline import project as outline
        result['work_outline'] = outline(graph, cutoff)
        attach_outline_evidence(result['work_outline'], result['stage_paths'], items, stage_parents)
        from .decision_followthrough import attach
        attach(graph, result['work_outline'])
        result['nodes'].extend(result['work_outline']['items'])
        result['roots'].extend(result['work_outline']['roots'])
        result['counts']['roots'] += len(result['work_outline']['roots'])
        result['available'] = bool(result['roots'])
    from .work_structure_metrics import summarize
    result['work_measures'] = summarize(graph, result)
    return {'id': 'work-hierarchy-' + digest(result), **result}


def stage_paths(items, links, stages, all_actions, graph):
    """Readable paths over exact saved edges, never inferred repair episodes.

    One dispatch can have several roles or belong to multiple stages. Neither
    duplication nor source ordering establishes extra execution or causation.
    """
    from . import action_comparison
    out = []
    by_source = defaultdict(list)
    by_target = defaultdict(list)
    for link in links:
        by_source[link['source']].append(link)
        by_target[link['target']].append(link)
    for sid in stages:
        membership = defaultdict(list)
        for link in by_source[sid]:
            if link['type'] in ROLES:
                membership[link['target']].append(link)
        ordered = sorted(membership, key=lambda k: (items[k]['event_index'], k))
        rows = []
        for aid in ordered:
            action = items[aid]
            responses = defaultdict(list)
            for link in by_source[aid]:
                if link['type'] == 'response':
                    responses[link['target']].append(link['id'])
            feedback = []
            for rid, witnesses in sorted(responses.items(), key=lambda v: (items[v[0]]['event_index'], v[0])):
                assessments = []
                for link in by_target[rid]:
                    if link['type'] != 'assesses': continue
                    review = items[link['source']]
                    if ((review['actor'], review['trajectory_id'], review.get('context_id')) != (action['actor'], action['trajectory_id'], action.get('context_id'))
                            or review['event_index'] < items[rid]['event_index']): continue
                    assessments.append(dict(node_id=review['id'], link_id=link['id']))
                feedback.append(dict(node_id=rid, link_ids=sorted(witnesses),
                    assessments=sorted(assessments, key=lambda v: (items[v['node_id']]['event_index'], v['node_id']))))
            rows.append(dict(action_id=aid, dispatch_id=action.get('dispatch_id', aid), role_link_ids=sorted(e['id'] for e in membership[aid]),
                roles=sorted({e['type'] for e in membership[aid]}), responses=feedback))
        returns = []
        for aid in ordered:
            for link in by_source[aid]:
                if link['type'] not in {'same_action_target', 'revisits_after_error_report', 'completed_after_failed_call'}: continue
                if link['target'] not in membership: continue
                a, b = items[aid], items[link['target']]
                if ((a['actor'], a['trajectory_id']) != (b['actor'], b['trajectory_id'])
                        or a['event_index'] <= b['event_index']): continue
                returns.append(link['id'])
        # This is a count of visible source records, not missing plan annotations.
        outside = []
        if ordered:
            first, last = items[ordered[0]], items[ordered[-1]]
            outside = [n['id'] for n in all_actions if n['id'] not in membership and
                (n['trajectory_id'], n['properties'].get('actor')) == (first['trajectory_id'], first['actor']) and
                first['event_index'] <= n['event_index'] <= last['event_index']]
        pairs=defaultdict(list)
        for link in links:
            if link['id'] in returns:pairs[(link['target'],link['source'])].append(link['id'])
        comparisons=[]
        for (previous,current),witnesses in sorted(pairs.items()):
            comparison=action_comparison.compare(graph,previous,current)
            a,b=items[previous],items[current]
            origin=action_comparison.source(graph,previous)
            context=[]
            for n in all_actions:
                if (comparison['ordering']!='source_order'
                        or (n['trajectory_id'],n['properties'].get('actor'))!=(a['trajectory_id'],a['actor'])
                        or not a['event_index']<n['event_index']<b['event_index']):continue
                captured=action_comparison.source(graph,n['id'])
                if not captured or captured.get('context_id')!=origin.get('context_id'):continue
                p=n['properties'];content=p.get('content',{})
                context.append(dict(id=n['id'],label=text(content.get('target')) or text(content.get('summary')) or text(p.get('text')) or n['id'],
                    event_index=n['event_index'],linked_to_step=n['id'] in membership,
                    source_node_ids=[n['id']],source_text=text(p.get('source',{}).get('text')) or text(p.get('text')),
                    roles=sorted({e['type'] for e in membership.get(n['id'],[]) })))
            comparisons.append(dict(comparison=comparison,link_ids=sorted(witnesses),
                intervening=sorted(context,key=lambda n:(n['event_index'],n['id']))))
        out.append(dict(stage_id=sid, rows=rows, return_link_ids=sorted(returns), return_comparisons=comparisons,
            retry_summary=retry_summary(rows, comparisons, links),
            other_action_ids=sorted(outside), counts=dict(**work_dispatches.counts(rows),
                returns=len({items[e['source']].get('dispatch_id', e['source']) for e in links if e['id'] in returns}))))
    return out


def retry_summary(rows, comparisons, links):
    """Count later attempts once, not pair edges, checks, or failure statements."""
    attempts = {r['action_id'] for r in rows if 'attempts_plan_step' in r['roles']}
    dispatches = {r['action_id']: work_dispatches.identity(r) for r in rows}
    by_link = {e['id']: e for e in links}
    cases = {}
    for record in comparisons:
        c = record['comparison']; current, previous = c['current_node_id'], c['previous_node_id']
        if (c['ordering'] != 'source_order' or current not in attempts or previous not in attempts
                or dispatches[current] == dispatches[previous]):
            continue
        witnesses = [by_link[k] for k in record['link_ids'] if k in by_link]
        if not witnesses: continue
        case = cases.setdefault(current, dict(action_id=current, dispatch_id=dispatches[current], previous_attempt_ids=[], link_ids=[], after_reported_error=False))
        case['previous_attempt_ids'] = sorted(set(case['previous_attempt_ids']) | {previous})
        case['link_ids'] = sorted(set(case['link_ids']) | {e['id'] for e in witnesses})
        case['after_reported_error'] |= any(e['type'] in {'revisits_after_error_report','completed_after_failed_call'} for e in witnesses)
    return dict(attempts=len({dispatches[aid] for aid in attempts}), attempt_ids=sorted(attempts),
                attempt_dispatch_ids=sorted({dispatches[aid] for aid in attempts}),
                **work_dispatches.retry_counts(cases.values()), cases=list(cases.values()),
                coverage='saved_links_only')


def attach_outline_evidence(outline, paths, items, stage_parents):
    """Aggregate unique dispatch IDs along reviewed parentage, never states.

    Version 2 uses reviewed plan/step scope bindings only. Legacy outlines keep
    their unique containing-plan association; a shared quote is not a step match.
    """
    bindings = defaultdict(list)
    if outline.get('binding_mode')=='reviewed_scopes':
        for binding in outline['bindings']:
            bindings[binding['scope_node_id']].append((binding['item_id'],binding['id']))
    else:
        candidates = defaultdict(list)
        for item in outline['items']:
            if item['work_kind'] != 'approach': continue
            for source_id in item['source_node_ids']:
                if items.get(source_id, {}).get('kind') == 'plan': candidates[source_id].append(item['id'])
        for plan,owners in candidates.items():
            if len(owners)==1:bindings[plan].append((owners[0],None))
    parents = defaultdict(set)
    for link in outline['links']:
        if link['type'] == 'part_of': parents[link['source']].add(link['target'])
    by_item = defaultdict(list)
    for path in paths:
        plan = stage_parents[path['stage_id']]
        owners=defaultdict(set)
        for owner,bid in [*bindings[plan],*bindings[path['stage_id']]]:
            if bid:owners[owner].add(bid)
            else:owners[owner]
        for owner,bids in owners.items():
            bound_path={**path,'outline_binding_ids':sorted(bids),
                'binding_basis':'reviewed_scope' if bids else 'containing_plan_citation'}
            seen = set(); queue = [owner]
            while queue:
                item_id = queue.pop()
                if item_id in seen: continue
                seen.add(item_id); by_item[item_id].append((plan,owner,bound_path)); queue.extend(parents[item_id])
    for item in outline['items']:
        paths_here = by_item[item['id']]
        if not paths_here: continue
        cases = {}; attempts = set()
        for plan, owner, path in paths_here:
            attempts.update(path['retry_summary'].get('attempt_dispatch_ids', path['retry_summary']['attempt_ids']))
            for case in path['retry_summary']['cases']:
                current = cases.setdefault(case['action_id'], dict(action_id=case['action_id'], dispatch_id=work_dispatches.identity(case), previous_attempt_ids=set(), link_ids=set(), after_reported_error=False, stage_ids=set()))
                for key in ('previous_attempt_ids', 'link_ids'): current[key].update(case[key])
                current['after_reported_error'] |= case['after_reported_error']; current['stage_ids'].add(path['stage_id'])
        for case in cases.values():
            for key in ('previous_attempt_ids','link_ids','stage_ids'): case[key] = sorted(case[key])
        item['retry_summary'] = dict(attempts=len(attempts), **work_dispatches.retry_counts(cases.values()), cases=list(cases.values()),
            bound_plan_ids=sorted({p for p, _, _ in paths_here}),
            bound_work_ids=sorted({owner for _, owner, _ in paths_here}),
            stage_ids=sorted({p['stage_id'] for _, _, p in paths_here}), coverage='saved_links_only')
        item['execution_summary'] = outline_execution(item['id'], paths_here, items)


def outline_execution(item_id, paths, items):
    """Deduplicate linked dispatches, preserving role and feedback witnesses.

    Parentage scopes a union of evidence; it never changes a decision/report
    into execution or completion. Role counts overlap when one dispatch has
    multiple saved roles. Assessments count actions with at least one assessed
    response, not complete review of all feedback or successful verification.
    """
    actions = {}
    for plan, owner, path in paths:
        for row in path['rows']:
            action = actions.setdefault(row['action_id'], dict(action_id=row['action_id'],
                dispatch_id=work_dispatches.identity(row), roles=set(), memberships=[], responses={}))
            action['roles'].update(row['roles'])
            membership = dict(plan_id=plan, work_id=owner, stage_id=path['stage_id'],
                roles=list(row['roles']), role_link_ids=list(row['role_link_ids']),
                binding_ids=list(path.get('outline_binding_ids',[])),binding_basis=path.get('binding_basis','containing_plan_citation'))
            if membership not in action['memberships']: action['memberships'].append(membership)
            for response in row['responses']:
                target = action['responses'].setdefault(response['node_id'], dict(
                    node_id=response['node_id'], link_ids=set(), assessments={}))
                target['link_ids'].update(response['link_ids'])
                for assessment in response['assessments']:
                    target['assessments'][(assessment['node_id'], assessment['link_id'])] = deepcopy(assessment)
    order = lambda nid: (items[nid]['event_index'], nid)
    rows = []
    for aid in sorted(actions, key=order):
        action = actions[aid]
        action['roles'] = sorted(action['roles'])
        action['memberships'].sort(key=lambda m: (m['plan_id'], m['stage_id'], m['work_id']))
        responses = []
        for rid in sorted(action['responses'], key=order):
            response = action['responses'][rid]
            response['link_ids'] = sorted(response['link_ids'])
            response['assessments'] = sorted(response['assessments'].values(),
                key=lambda a: (order(a['node_id']), a['link_id']))
            responses.append(response)
        action['responses'] = responses
        rows.append(action)
    owners = sorted({owner for _, owner, _ in paths})
    scope = ('mixed' if len(owners) > 1 else 'direct') if item_id in owners else 'descendants'
    return dict(scope=scope, coverage='saved_links_only', grain='source_dispatch_or_action_id',
        bound_plan_ids=sorted({plan for plan, _, _ in paths}), bound_work_ids=owners,
        binding_ids=sorted({bid for _,_,p in paths for bid in p.get('outline_binding_ids',[])}),
        binding_basis='reviewed_scopes' if all(p.get('binding_basis')=='reviewed_scope' for _,_,p in paths) else 'containing_plan_citation',
        stage_ids=sorted({p['stage_id'] for _, _, p in paths}), rows=rows,
        counts=work_dispatches.counts(rows))


def native_lists(graph, visible, eligible, items, links, roots):
    """Persistent list-item identity only through comparable native retention edges."""
    snapshots = [n for n in visible.values() if n['kind'] == 'declared_plan_snapshot']
    lanes = defaultdict(list)
    item_lanes = {}
    for n in snapshots:
        p=n['properties']; lane=(n['trajectory_id'], p.get('context_id'), p.get('actor'), p.get('profile'));lanes[lane].append(n)
        for item in p['items']:item_lanes[item['id']]=lane
    parent = {n['id']: n['id'] for n in visible.values() if n['kind'] == 'declared_plan_item'}
    def find(k):
        while parent[k] != k: k=parent[k]
        return k
    for e in sorted(eligible, key=lambda e:visible[e['source']]['event_index']):
        if e['type'] not in {'retains_declared_plan_id', 'retains_declared_plan_text'} or e['properties'].get('comparable') is not True: continue
        if e['source'] in parent and e['target'] in parent and item_lanes.get(e['source']) == item_lanes.get(e['target']):
            parent[find(e['source'])]=find(e['target'])
    for lane, values in lanes.items():
        values.sort(key=lambda n:(n['event_index'],n['id'])); latest=values[-1]; lp=latest['properties']
        rid='task-list-'+digest([graph['run_id'],lane,values[0]['id']]);roots.append(rid)
        items[rid]=dict(id=rid,kind='task_list',label='Recorded task list',state=f'{len(values)} captured declarations'+(' · order unresolved' if not lp['order_known'] else ''),
            actor=lp.get('actor'),trajectory_id=lane[0],event_index=latest['event_index'],source_node_ids=[n['id'] for n in values],
            evidence=[],source_text='',history=[],criterion={'status':'not_expressed'})
        current_ids={find(i['id']) for i in lp['items'] if i['id'] in parent}
        groups=defaultdict(list)
        for snapshot in values:
            for item in snapshot['properties']['items']:
                if item['id'] in parent:groups[find(item['id'])].append((snapshot,item))
        for gid,history in groups.items():
            snapshot,item=history[-1]; present=gid in current_ids; nid='list-item:'+gid
            # An omitted entry is neither an abandoned objective nor completed work.
            state=STATUS.get(item['status'],'Reported state unknown') if present else 'Not in latest declaration'
            items[nid]=dict(id=nid,kind='declared_item',label=item['text'],state=state,
                actor=lp.get('actor'),trajectory_id=lane[0],event_index=snapshot['event_index'],
                source_node_ids=[i['id'] for _,i in history],evidence=[],source_text='',
                native_id=item.get('native_id'),present=present,
                history=[dict(event_id=s['properties']['event_id'],event_index=s['event_index'],text=i['text'],
                    status=i['status'],label=STATUS.get(i['status'],'Reported state unknown'),argument_pointer=i['argument_pointer'],
                    source_node_id=i['id'],order_known=s['properties']['order_known']) for s,i in history])
            witness=[e['id'] for e in eligible if e['type']=='contains_declared_plan_item' and e['target'] in items[nid]['source_node_ids']]
            row=dict(source=rid,target=nid,type='contains',label='Listed item' if present else 'Previously listed item',edge_ids=witness,evidence=[])
            links.append({'id':'hierarchy-edge-'+digest(row),**row})
