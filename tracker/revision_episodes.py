"""Revision evidence chains over saved relationships, with no new classification.

Declarations, implementing dispatches and same-work results remain distinct.
The caller supplies the hierarchy's audited, cutoff-filtered graph projection.
"""
from collections import defaultdict
from .graph_sequence import Ordering
from .schema import digest

VERSION = 'revision-episodes/4'
CHANGES = {'changes_attempt_procedure': 'procedure',
           'changes_attempt_prerequisite': 'prerequisite',
           'adjustment_before_retry': 'local_adjustment', 'revises': 'revision'}
# The earlier attempt-revision export used "implements" for the same dispatch
# correspondence. It never established successful state mutation.
IMPLEMENTATIONS = {'attempts_declared_change', 'attempts_local_adjustment', 'implements_declared_change'}
SAME_WORK = {'same_action_target', 'revisits_after_error_report',
             'completed_after_failed_call', 'reconfigured_procedure', 'alternative_procedure'}


def project(graph, visible, edges, hierarchy):
    order = Ordering(graph)
    by_type = defaultdict(list)
    for edge in edges:
        by_type[edge['type']].append(edge)

    def before(a, b, agent=False):
        if a not in visible or b not in visible:
            return False
        left, right = visible[a], visible[b]
        return (not agent or left['properties'].get('actor') == right['properties'].get('actor')) and order.before(left, right) is None

    def sorted_ids(ids):
        return sorted(set(ids), key=lambda uid: order.key(visible[uid]))

    def responses(action):
        return [e for kind in ('feedback_for', 'response_to') for e in by_type[kind]
                if e['target'] == action and before(action, e['source'])]

    results = graph.get('semantic_context') or {}
    results = results.get('operation_results', {})

    def outcome(uid):
        event_id = order.event_id(visible[uid])
        row = results.get(event_id, {})
        refs = ['event:' + r['response_event_id'] for r in row.get('observations', [])]
        # Never display the full-rollout result before all of its witnesses.
        if not refs or not all(r in visible for r in refs):
            return 'not_established', []
        return row.get('outcome', 'not_established'), refs

    seeds = defaultdict(list)
    for kind in CHANGES:
        for edge in by_type[kind]:
            if before(edge['target'], edge['source'], agent=True):
                seeds[(edge['source'], edge['target'])].append(edge)
    episodes = []
    for (declaration, prior), witnesses in sorted(seeds.items()):
        implemented = {e['source']: e for kind in IMPLEMENTATIONS for e in by_type[kind]
                       if e['target'] == declaration and visible[e['source']]['properties'].get('kind') == 'action'
                       and before(declaration, e['source'], agent=True)}
        followups = set()
        links = {e['id'] for e in witnesses}
        # Local-adjustment witnesses name the exact retry and implementing action.
        for edge in witnesses:
            if edge['type'] != 'adjustment_before_retry':
                continue
            p = edge.get('properties', {})
            via, retry = p.get('via_action'), p.get('retry_unit_id')
            if before(declaration, via, agent=True) and visible[via]['properties'].get('kind') == 'action':
                implemented.setdefault(via, edge)
                if via == retry or (before(via, retry, agent=True) and visible[retry]['properties'].get('kind') == 'action'):
                    followups.add(retry)
        for kind in SAME_WORK:
            for edge in by_type[kind]:
                if edge['target'] == prior and edge['source'] in implemented:
                    followups.add(edge['source']); links.add(edge['id'])
                elif edge['target'] == prior and any(
                    before(via, edge['source'], agent=True)
                    and witness.get('properties', {}).get('cutoff', {}).get('event_id') == order.event_id(visible[edge['source']])
                    for via, witness in implemented.items()):
                    # The saved correspondence names its inspected retry in the
                    # cutoff. Require a same-work link too: recency alone cannot
                    # turn a later successful action into the revision's result.
                    followups.add(edge['source']); links.add(edge['id'])
        links.update(e['id'] for e in implemented.values())
        triggers = [e for e in responses(prior) if before(e['source'], declaration)]
        assessments = [e for e in by_type['assesses'] if e['target'] in {r['source'] for r in triggers}
                       and before(e['target'], e['source']) and
                       (e['source'] == declaration or before(e['source'], declaration, agent=True))]
        links.update(e['id'] for e in triggers + assessments)
        steps = [('Earlier work', [prior]), ('Feedback', sorted_ids(e['source'] for e in triggers)),
                 ('Reassessment', sorted_ids(e['source'] for e in assessments)),
                 ('Declared change', [declaration]), ('Implementation', sorted_ids(implemented)),
                 ('Same-work follow-up', sorted_ids(followups))]
        implementation_results = []
        for uid in sorted_ids(implemented):
            state, refs = outcome(uid)
            returned = responses(uid)
            implementation_results.append(dict(action_id=uid, outcome=state,
                response_ids=sorted_ids([r['source'] for r in returned] + refs)))
        steps.insert(5, ('Implementation result', sorted_ids(r for result in implementation_results for r in result['response_ids'])))
        result_rows = []
        for uid in sorted_ids(followups):
            returned = responses(uid)
            status, refs = outcome(uid)
            # Older graphs may retain this exact validated transition only.
            transition = next((e for e in by_type['completed_after_failed_call']
                               if e['source'] == uid and e['target'] == prior), None)
            if transition and status == 'not_established':
                refs = ['event:' + rid for rid in transition.get('properties', {}).get('current_response_ids', [])]
                if refs and all(r in visible for r in refs):
                    status = 'completed'; links.add(transition['id'])
                else:
                    refs = []
            links.update(e['id'] for e in returned)
            represented = {order.event_id(visible[e['source']]) for e in returned}
            refs = [ref for ref in refs if order.event_id(visible[ref]) not in represented]
            result_rows.append(dict(action_id=uid, outcome=status,
                response_ids=sorted_ids([e['source'] for e in returned] + refs)))
        steps.append(('Follow-up result', sorted_ids(r for row in result_rows for r in row['response_ids'])))
        prior_outcome, prior_refs = outcome(prior)
        # Preserve typed failure witnesses without reclassifying quoted feedback.
        if prior_outcome == 'not_established' and any(e['type'] == 'completed_after_failed_call' and e['target'] == prior and
               e['source'] in followups for e in edges):
            prior_outcome = 'failed'
        stage_rows = [dict(label=label, node_ids=ids) for label, ids in steps]
        members = sorted_ids([uid for _, ids in steps for uid in ids] + prior_refs)
        value = dict(kind='attempt_revision', declaration_id=declaration, previous_id=prior,
            change_kinds=sorted({CHANGES[e['type']] for e in witnesses}), stages=stage_rows,
            node_ids=members, edge_ids=sorted(links), results=result_rows,
            implementation_results=implementation_results,
            prior_outcome=prior_outcome,
            status='follow_up_observed' if followups else 'implementation_linked' if implemented else 'declared_only',
            limits='Operation outcomes describe executor completion, not task correctness or the causal effect of a revision.')
        methods = {e['type'] for e in edges if e['target'] == prior and result_rows and e['source'] == result_rows[0]['action_id']
                   and e['type'] in {'same_procedure', 'reconfigured_procedure', 'alternative_procedure'}}
        value['method_change'] = next(iter(methods)) if len(methods) == 1 else 'not_established'
        episodes.append(dict(id='revision-' + digest([graph['id'], declaration, prior]), **value))

    # Work-outline replacement is a different scale of revision. Nearby actions
    # in a decision window are context, not proof they implemented the new plan.
    outline = hierarchy.get('work_outline') or {}
    items = {n['id']: n for n in outline.get('items', [])}
    for edge in outline.get('links', []):
        if edge['type'] != 'replaces':
            continue
        new, old = items[edge['source']], items[edge['target']]
        replacement_refs = list(dict.fromkeys('event:' + ref['event_id'] for ref in edge['evidence']))
        value = dict(kind='plan_replacement', declaration_id=new['id'], previous_id=old['id'],
            change_kinds=['plan_replacement'], status='replacement_recorded', prior_outcome='not_established',
            stages=[dict(label='Earlier plan', node_ids=[old['id']]),
                    dict(label='Replacement statement', node_ids=replacement_refs),
                    dict(label='Replacement plan', node_ids=[new['id']])],
            node_ids=[old['id'], new['id'], *replacement_refs], edge_ids=[edge['id']], results=[],
            limits='An explicit replacement relationship. Inspect the branch decision history and linked actions for follow-through.')
        episodes.append(dict(id='revision-' + digest([graph['id'], edge['id']]), **value))
    def episode_order(episode):
        sources = [visible[uid] for stage in episode['stages']
                   if stage['label'] in {'Declared change', 'Replacement statement'}
                   for uid in stage['node_ids'] if uid in visible]
        return min((order.key(n) for n in sources), default=(float('inf'), 0, episode['id']))
    episodes.sort(key=episode_order)
    operation_results = {}
    for uid, node in visible.items():
        if node['properties'].get('kind') != 'action':
            continue
        status, refs = outcome(uid)
        if refs:
            operation_results[uid] = dict(outcome=status, response_ids=refs)
    from .revision_impact import enrich
    enrich(graph, visible, episodes)
    for episode in episodes:
        episode['dimensions'] = dimensions(episode)
    return dict(schema=VERSION, episodes=episodes, operation_results=operation_results,
                counts=dict(total=len(episodes), declared_only=sum(e['status']=='declared_only' for e in episodes),
                            with_follow_up=sum(bool(e['results']) for e in episodes)))


def dimensions(episode):
    """Four evidence-backed readings, not four inferred mental-state labels.

    Keep unknowns in the result. A dispatch establishes attempted follow-through;
    it does not establish that an edit took effect or that a plan was completed.
    """
    stages = {s['label']: s['node_ids'] for s in episode['stages']}
    def field(value, label, ids=(), basis='saved_relationship'):
        return dict(value=value, label=label, node_ids=list(dict.fromkeys(ids)), basis=basis)
    feedback = stages.get('Feedback', [])
    assessed = stages.get('Reassessment', [])
    trigger = field('not_established', 'Trigger not linked', basis='unmeasured')
    if feedback:
        trigger = field('assessed_feedback' if assessed else 'preceding_feedback',
            'Feedback assessed before change' if assessed else 'Earlier feedback · trigger unconfirmed',
            [*feedback, *assessed])
    targets = {'procedure': 'Procedure / settings', 'prerequisite': 'Input / prerequisite',
               'local_adjustment': 'Local adjustment', 'revision': 'Target unspecified',
               'plan_replacement': 'Plan structure'}
    kinds = episode['change_kinds']
    target = field('+'.join(kinds), ' + '.join(targets[k] for k in kinds),
                   stages.get('Declared change', stages.get('Replacement statement', [])))
    if episode.get('method_change') == 'alternative_procedure':
        target['label'] += ' · alternative method'
    elif episode.get('method_change') == 'reconfigured_procedure':
        target['label'] += ' · method adjusted'
    implemented = stages.get('Implementation', [])
    result_refs = stages.get('Follow-up result', [])
    checked = [c for c in episode['impact']['checks'] if c['status'] != 'unknown']
    follow = field('proposed', 'Proposed · execution not linked', target['node_ids'])
    if implemented:
        follow = field('attempted', 'Attempt dispatched', implemented)
    if result_refs:
        follow = field('returned', 'Follow-up result recorded', [*implemented, *result_refs])
    failed_implementation = [r for r in episode.get('implementation_results', []) if r['outcome'] == 'failed']
    if failed_implementation:
        follow = field('implementation_failed', 'Change attempt failed' + (' · later retry recorded' if result_refs else ''),
            [n for r in failed_implementation for n in [r['action_id'], *r['response_ids']]], 'operation_outcomes')
    if checked:
        follow = field('checked', 'Change rechecked on captured state', [n for c in checked for n in c['after_node_ids']], 'captured_checks')
    impact = episode['impact']
    scope = 'checks' if impact['checks'] else 'operations'
    status = impact['check_status'] if scope == 'checks' else impact['operation']['status']
    labels = {'gain': 'Improved', 'harm': 'Regressed', 'mixed': 'Improved + regressed',
              'retained': 'Still passing', 'still_failed': 'Still failing',
              'unchanged': 'No result change', 'unknown': 'Unresolved'}
    consequence = field(status, labels[status] + (' · criterion checks' if scope == 'checks' else ' · operation only'),
        [n for c in impact['checks'] for n in c['node_ids']] if scope == 'checks' else impact['operation']['node_ids'],
        'captured_checks' if scope == 'checks' else 'operation_outcomes')
    consequence['scope'] = scope
    if scope=='checks':
        missing=impact['checks_unknown']
        if missing:
            consequence['label'] += f' · {missing} unresolved'
            if checked:follow['label'] += f' · {missing} unresolved'
    return dict(trigger=trigger, target=target, follow_through=follow, consequence=consequence)
