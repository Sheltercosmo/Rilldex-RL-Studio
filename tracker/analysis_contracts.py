"""Discoverable meaning and evidence needs of existing analysis operations.

This is metadata for investigation_plans, not another executor or a claim of
semantic accuracy. Requirements describe useful evidence, not classifier gates.
"""
from copy import deepcopy

VERSION = 'analysis-operation-contracts/7'

# Routing metadata is deliberately outside saved measurement definitions. Changing
# setup guidance must not change old monitor IDs, result semantics or cache keys.
OBSERVER_INPUTS = {
    'source': dict(accepted=['source'], preferred='source',
        guidance='Uses recorded source evidence. No semantic observer is required.'),
    'observed': dict(accepted=['observed'], preferred='observed',
        guidance='Choose a saved observer, then check its evidence for this population. An observer name alone does not establish compatibility.'),
    'either': dict(accepted=['source', 'observed'], preferred='source',
        guidance='Recorded source is supported; a saved observer can add available relationship evidence. Check the selected population.'),
    'inspect': dict(accepted=['source', 'observed'], preferred='observed',
        guidance='Choose an observer with the required observations. Recorded source can expose missing inputs, but cannot supply semantic measurements by itself.'),
}

# Setup guidance describes the input contract, not permission to infer a missing fact.
EVIDENCE_GUIDANCE = {
    'recorded_work_structure': 'Supply a semantic Plan with action-to-step links, a producer-declared goal tree, or a source-bound work outline. Each measure uses only its named evidence basis; sources do not acquire semantic meaning from this projection.',
    'structured_plan_calls': 'Capture native write_todos or task_tracker plan calls and their structured arguments. Status fields are declarations, not proof of completion; customized tools need their own validated profile.',
    'contribution_work_bindings': 'Use an explicit contribution-work annotation profile and bind source units to named immediate work. Action identity alone does not provide this profile.',
    'work_navigation_units': 'Use source-bound contributions for the contribution-work profile, or action units for the legacy action profile.',
    'work_navigation_reviews': 'Review explicit contribution-to-work bindings. Action-only profiles still require their original action-identity reviews.',
    'native_actions': 'Capture native actions before flattening the trajectory. Text that describes an action is not execution evidence.',
    'semantic_units': 'Prepare source-bound coherent units under the selected observer; keep unresolved contributions visible.',
    'action_units': 'Bind the observer’s action units to the recorded native dispatches.',
    'linked_text_feedback': 'Capture textual tool results with native call correspondence and agent visibility. No external feedback can be not applicable, rather than a behavioral failure.',
    'work_identity_reviews': 'Review which contributions address the same work, preserving source references and unresolved identities.',
    'method_reviews': 'Review the procedure used by each exact pair of supported same-work attempts.',
    'feedback_reviews': 'Run the contribution feedback observer or review exact contribution/response pairs. Old positive links and partial reviews cannot establish complete negative coverage.',
    'software_repair_profile': 'Use an explicitly declared software-repair task profile only when that domain applies.',
}


def projection(label, question, grain, needs, limit, validation, *, observer='observed'):
    return dict(label=label, question=question, grain=grain, evidence_needs=needs,
                boundary=limit, validation=validation, input_kind='bound_source_graph',
                new_model_calls=0, upstream_observation_cost='not estimated',
                observer_input=deepcopy(OBSERVER_INPUTS[observer]))


CONTRACTS = {
    'requested_evidence': projection('Review requested terms',
        'Which requested terms were recorded before this contribution, and which earlier candidates help inspect them?',
        'saved requested clause version at a source cutoff', ['requested_history'],
        'Projects existing work, requirements, requested checks and attributed claims separately. Superseded and withdrawn versions remain history. Candidates, including the originating request, never establish fulfillment or truth.',
        'Source, version, context, cutoff and shared-budget controls; interpretation accuracy and condition satisfaction are not established.'),
    'evidence_search': {
        **projection('Earlier source evidence', 'Which earlier passages and recorded results can help inspect this contribution?',
            'source passage before an exact anchor', [],
            'Lexical candidates only, limited to visible, ordered source in the same trajectory and recorded context. Missing context boundaries are explicit. Matches and adjacent context are not semantic relationships or complete evidence. Encoded media is not inspected.',
            'Source-range, cutoff, visibility, budget and native-correspondence controls; semantic recall and diagnosis remain unestablished.', observer='source'),
        'input_kind': 'bound_source_query'},
    'work_structure': projection('Recorded work and branch effort', 'Which planned work has recorded attempts, and what work follows each explicit decision?',
        'declared work item / distinct operation or decision', ['recorded_work_structure'],
        'Native requests, semantic Plan attempts and outline decisions are separate measures. Decision windows retain exact action and feedback links until the next statement or observation cutoff. Missing visits or links do not establish abandonment. Shared effort is deduplicated globally; branch totals can overlap. Reports are not verified success.',
        'Structural and source-replay validation; independent semantic accuracy and RL performance benefit remain unestablished.', observer='either'),
    'revision_impact': projection('Revision benefits and regressions', 'What improved or regressed after a recorded change?',
        'source-linked revision and its first comparable follow-up', ['action_units'],
        'Operations and captured criterion checks remain separate. Gains and regressions share their own comparison denominator; missing or incompatible results remain unknown. Later success never replaces the first follow-up. Temporal association is not causal credit.',
        'Controlled transitions and evidence-chain validation; semantic accuracy inherits saved annotations.'),
    'declared_plans': projection('Structured plan declarations', 'Does the agent reopen work it previously reported complete?',
        'reported completed item followed by the next same-context task-list declaration', ['structured_plan_calls'],
        'Uses documented LangChain and OpenHands payload profiles. Unique native IDs with unchanged text, or unique exact text without IDs, support comparison; rename, removal, duplicate identity, invalid intervening writes and unordered calls stay unknown. Issued declarations do not prove tool acceptance or completed work.',
        'Schema, state-transition and source-encoding controls; semantic whole-work identity and task success are not inferred.',observer='source'),
    'work_return_references': {
        **projection('References during work returns', 'Does a return revise earlier work or reference intervening evidence?',
            'recorded same-subject return visit', ['work_navigation_units', 'contribution_work_bindings'],
            'Counts saved directed relationships from a supported returned visit to configured earlier work. Each return counts once. Missing links are not behavioral negatives; native relation namespaces remain explicit.',
            'Source/prefix projection controls and retained-reference replay; independent semantic validity is not established.'),
        'input_kind':'bound_graph_query'},
    'work_visits': projection(
        'Immediate-work visits', 'How often do observed work switches return to an earlier subject?',
        'collapsed same-subject visit', ['work_navigation_units', 'contribution_work_bindings'],
        'Visits require explicit contribution-work bindings. First recorded identity is not novelty; missing history cannot establish a negative return. Counts are not exploration or quality scores.',
        'Authored controls and reviewed-source replay; independent semantic validity and training benefit remain unmeasured.', observer='inspect'),
    'sequence': projection(
        'Expressed activities', 'How does the sequence of expressed activities change?',
        'ordered activity block', ['semantic_units'],
        'Activity blocks are not task phases. Unobserved spans and trajectory ambiguity remain explicit.',
        'Projection mechanics tested; independent unit/activity accuracy not established.'),
    'work_state': projection(
        'Recorded state and checks', 'Which object version was checked, changed or delivered?',
        'recorded state/check/change', ['native_actions'],
        'Actions alone do not establish state, check outcomes or complete dependency scope. Producer state/check records are needed. Delivery evidence preserves all prior same-context criterion checks; conflicting applicable outcomes and inconsistent input scopes remain unknown. Pending results cannot certify an earlier delivery.',
        'Executed authored controls across software and business encodings; not general environment validation.', observer='source'),
    'work_episodes': projection(
        'Same-work recurrence', 'Does the agent continue work or return after intervening operations?',
        'native action / supported recurrence', ['native_actions', 'action_units', 'work_identity_reviews'],
        'A return needs supported work identity. Missing review is unknown; recurrence is not exploration or objective deviation.',
        'Software, airline and retail public replay; independent relation accuracy not established.'),
    'repeated_work': projection(
        'Compare recorded attempts', 'What changed between repeated attempts at the same work?',
        'supported same-work dispatch pair', ['native_actions', 'action_units', 'work_identity_reviews'],
        'Compares native inputs or captured action text and source-bound feedback. Missing feedback and uncertain order remain unknown; matching records do not prove failed loops or unchanged environment state.',
        'Deterministic source comparisons; work identity inherits the selected observer accuracy.'),
    'work_navigation': projection(
        'Connected work visits', 'Which connected work visits explain this rollout?',
        'work visit', ['work_navigation_units', 'work_navigation_reviews'],
        'Versioned contribution-work bindings support reasoning and actions; graphs without them retain the action-only profile. No inferred goal, causal dependency or equivalence between profiles.',
        'Projection and review/import mechanics tested; independent semantic accuracy not established.'),
    'adaptation_patterns': projection(
        'Procedure changes on the same work', 'Does a retry reuse, reconfigure or replace its procedure?',
        'supported same-work recurrence', ['native_actions', 'action_units', 'work_identity_reviews', 'method_reviews'],
        'Requires an exact-pair method comparison. Changed command text is insufficient; procedure change does not establish successful recovery.',
        'Public replay and authored controls; independent method-comparison accuracy not established.', observer='inspect'),
    'feedback_opportunities': projection(
        'Explicit feedback reference', 'How often is delivered feedback described or interpreted afterwards?',
        'visible source-bound textual response', ['linked_text_feedback', 'semantic_units', 'feedback_reviews'],
        'Uses the next three nonempty same-lane agent text events. Incomplete windows/reviews stay unknown. Reference does not establish appropriate use.',
        'Source opportunity and censoring mechanics tested; expanded semantic selections not independently validated.', observer='inspect'),
    'feedback_timing': projection(
        'Timing of saved feedback assessments', 'Is feedback first referenced in the saved observations before or after other actions?',
        'visible native-bound textual response', ['linked_text_feedback', 'semantic_units', 'feedback_reviews'],
        'Counts intervening same-recipient dispatches before the earliest eligible saved assessment. Missing links and incomparable order remain unknown. The conditional fraction does not measure first actual uptake, neglect or causal use.',
        'Exact source/edge binding and ordering controls; independent semantic assessment accuracy remains unestablished.', observer='inspect'),
    'repair_phases': projection(
        'Software repair phases', 'How do localization, patching and validation patterns differ?',
        'software repair action phase', ['native_actions', 'software_repair_profile'],
        'An explicitly declared software-repair profile is required; these phases are not universal activities.',
        'Domain projection controls; not validation outside software repair.', observer='source'),
    'history_evidence': {
        **projection('Recorded history query', 'Does this action use a value supplied by a prior response?',
                     'configured history-query opportunity', ['native_actions', 'linked_text_feedback'],
                     'Only declared paths/operators are checked. Equality does not establish intention or correct reasoning.',
                     'Deterministic query and cross-format controls; scope is the supplied query.', observer='source'),
        'input_kind': 'bound_source_query'},
    'recovery_windows': {
        **projection('Comparable recovery', 'Does a relevant change precede a passing comparable retry?',
                     'failed check of a named criterion', ['native_actions'],
                     'Requires captured comparable check/state evidence from work_state. Three comparable failed follow-ups establish a negative; incomplete windows remain unknown.',
                     'Eleven executed authored controls; independent naturalistic recovery accuracy not established.', observer='either'),
        'input_kind': 'work_state_dependency_and_graph'},
    'retry_outcomes': {
        **projection('Next-check outcome by captured input change', 'What happens at the first recheck, with and without a recorded relevant input change?',
                     'visible failed check of a named criterion', ['native_actions'],
                     'Uses only the first later same-criterion check. Outcome and captured input category are independent; unknown membership remains unknown. Captured state changes are not semantic revisions or causal explanations.',
                     'Deterministic captured-state controls and retained execution replay; naturalistic semantic revision accuracy is not established.', observer='either'),
        'input_kind': 'recovery_dependency_and_graph'},
    'relation_query': {
        **projection('Recorded relationship path', 'Which contributions are connected by the specified evidence path?',
                     'source-bound anchor unit', ['semantic_units'],
                     'A bounded query over stored relations, including reasoning without tool actions. Missing edges are not negatives. Recorded-match fraction is not behavior prevalence or semantic accuracy. The query names an explicit activity and directed path.',
                     'Shared graph-query controls; validity depends on the selected observer and relation definitions.'),
        'input_kind': 'bound_graph_query'},
}

COMPARISONS = {
    'compare_sequences': 'sequence', 'compare_work': 'work_state',
    'compare_episodes': 'work_episodes', 'compare_repair_phases': 'repair_phases',
    'compare_adaptation': 'adaptation_patterns', 'compare_recovery_windows': 'recovery_windows',
}
for name, source in COMPARISONS.items():
    CONTRACTS[name] = {
        **CONTRACTS[source], 'label': 'Compare: ' + CONTRACTS[source]['label'],
        'input_kind': 'typed_comparison', 'dependency_operation': source,
        'grain': 'explicit focus/reference populations', 'evidence_needs': [],
        'boundary': 'Disjoint explicit populations; one contribution per rollout. Matching task/configuration, sampling and time windows remains a researcher decision. ' + CONTRACTS[source]['boundary'],
    }


def registered():
    """Current trusted registry metadata, including installed extensions."""
    from .analysis_operations import REGISTRY
    return REGISTRY.contracts()


def catalog(versions=None):
    from .analysis_operations import REGISTRY
    if versions is not None and set(versions) != set(REGISTRY.versions):
        raise RuntimeError('Every executable analysis operation needs a matching contract')
    result = REGISTRY.catalog(VERSION)
    if versions is not None:
        for row in result['operations']:
            row['implementation_version'] = versions[row['id']]
    return result


def inventory(run, graph):
    """Structural presence only. The operation remains the evidence validator."""
    events = [e for e in run['events'] if not e.get('copied_context')]
    event_ids = {e['id'] for e in events}
    units = [n['properties'] for n in graph['nodes'] if n['kind'] == 'unit']
    from .capabilities import links
    bound = links(run)
    visible = {e['id'] for e in events if e['kind'] == 'feedback' and e['text'].strip()
               and e.get('agent_visibility') != 'not_established'}
    ctx = graph.get('semantic_context') or {}
    work = ctx.get('work_observations') or {}
    selected = [u for u in units if u.get('source', {}).get('event_id') in event_ids]
    subjects = ctx.get('work_subjects')
    from .declared_plans import has_declaration as structured_plan_call
    return {
        'recorded_work_structure': sum(n['kind'] in {'plan_step','declared_work_node','work_outline_item'} for n in graph['nodes']),
        'structured_plan_calls': sum(structured_plan_call(e) for e in events),
        'contribution_work_bindings': sum(r['status']=='bound' for r in subjects['document']['bindings']) if subjects else 0,
        'work_navigation_units': sum(u.get('kind') in {'semantic', 'action'} for u in selected) if subjects else sum(u.get('kind') == 'action' for u in selected),
        'work_navigation_reviews': len(subjects['document']['bindings']) if subjects else len(work.get('identity_reviews', [])),
        'native_actions': sum(e['kind'] == 'action' for e in events),
        'semantic_units': sum(u.get('kind') == 'semantic' and u.get('status') == 'selected' for u in selected),
        'action_units': sum(u.get('kind') == 'action' for u in selected),
        'linked_text_feedback': len({r['feedback_id'] for r in bound['records'] if r['feedback_id'] in visible}),
        'work_identity_reviews': len(work.get('identity_reviews', [])),
        'method_reviews': len(work.get('method_observations', [])),
        'feedback_reviews': len((ctx.get('feedback_observations') or {}).get('observations', [])) + sum(
            r['type']=='assesses' for r in (ctx.get('relationship_reviews') or {}).get('document', {}).get('reviews', [])),
        'software_repair_profile': int(run['metadata'].get('task_family') == 'software_repair'),
    }
