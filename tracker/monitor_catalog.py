"""Curated, searchable monitor starters built from registered measures.

This is presentation/setup metadata only. It never starts an observer or
analysis. Every definition points at an existing metric or analysis measure;
unavailable evidence remains unavailable under the underlying measurement.
"""
from copy import deepcopy

from . import analysis_metrics
from .rollout_metrics import DEFINITIONS as METRICS


# Keep recipe metadata independent of a particular run or observer ID. Source
# recipes can be used immediately; semantic recipes need the user to select an
# observer that has actually produced compatible evidence.
_RECIPES = [
    {
        'id': 'response-size', 'name': 'Response length · characters',
        'question': 'How much agent text is recorded per rollout?',
        'use': 'Compare captured response size; characters are not generated tokens or compute.',
        'kind': 'metric', 'metric': 'agent_text_chars', 'group': 'Training',
        'evidence_requirement': 'Recorded non-copied agent prose. Token usage requires trainer or inference-server telemetry.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'action-count', 'name': 'Actions per rollout',
        'question': 'How many actions does the agent dispatch per rollout?',
        'use': 'Compare interaction length alongside outcomes, retries and task composition.',
        'kind': 'metric', 'metric': 'actions', 'group': 'Training',
        'evidence_requirement': 'Recorded non-copied agent action events; actions are not tokens or environment transitions.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'logged-reward', 'name': 'Logged reward',
        'question': 'How does the producer-reported reward vary across rollouts?',
        'use': 'Track the reward signal used by the experiment while retaining its source-defined scale.',
        'kind': 'metric', 'metric': 'recorded_reward', 'group': 'Training',
        'evidence_requirement': 'A finite explicit rollout reward in the normalized source or a recognized reward source.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'explicit-task-success', 'name': 'Explicit task success',
        'question': 'What fraction of rollouts with an explicit outcome succeeded?',
        'use': 'Follow producer- or evaluator-recorded task success without inferring it from response text.',
        'kind': 'metric', 'metric': 'recorded_success', 'group': 'Training',
        'evidence_requirement': 'An explicit boolean verified_success outcome; absent outcomes stay unavailable.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'episode-return', 'name': 'Recorded episode return',
        'question': 'How does the fully recorded environment episode return vary?',
        'use': 'Inspect undiscounted step reward totals for supported environment episode captures.',
        'kind': 'metric', 'metric': 'environment_episode_return', 'group': 'Training',
        'evidence_requirement': 'A recorded reset, episode ending, and finite reward for every step under the environment-episode contract.',
        'observer_requirement': 'source', 'default': False,
    },
    {
        'id': 'tool-error-reports', 'name': 'Reported tool errors',
        'question': 'How often do source-linked agent responses explicitly report a tool error?',
        'use': 'Track explicit executor error flags and keep unflagged or missing responses distinct.',
        'kind': 'metric', 'metric': 'environment_tool_error_fraction', 'group': 'Training',
        'evidence_requirement': 'Source-linked agent responses with an explicit boolean reported_tool_error flag.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'dispatch-repeat', 'name': 'Repeated dispatches',
        'question': 'What share of agent actions repeats an earlier exact dispatch?',
        'use': 'Monitor exact tool, argument, and text repetition within the same recorded actor trajectory.',
        'kind': 'metric', 'metric': 'exact_dispatch_repeat_rate', 'group': 'Behavior',
        'evidence_requirement': 'Recorded non-copied agent action events with comparable dispatch fields.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'response-link-coverage', 'name': 'Action response coverage',
        'question': 'What share of agent actions have a recorded response?',
        'use': 'Check whether the trace contains linked visible feedback for dispatched actions.',
        'kind': 'metric', 'metric': 'feedback_link_rate', 'group': 'Behavior',
        'evidence_requirement': 'Recorded agent actions and source-linked responses; no actions means no rate.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'next-check-after-failure', 'name': 'First recheck after failure',
        'question': 'How often does the first comparable recheck pass after a visible failure?',
        'use': 'Track first-check outcomes while retaining unresolved comparability and captured-input evidence.',
        'kind': 'analysis', 'measure': 'next_check_success', 'group': 'Training',
        'evidence_requirement': 'Source-bound native actions, a named criterion, a visible failed check, and a comparable first later check.',
        'observer_requirement': 'source', 'default': True,
    },
    {
        'id': 'environment-length', 'name': 'Recorded environment steps',
        'question': 'How many explicit environment transitions are recorded per rollout?',
        'use': 'Inspect captured episode length where the producer supplied transition records.',
        'kind': 'metric', 'metric': 'environment_steps', 'group': 'Training',
        'evidence_requirement': 'An environment-episode transition capture; other adapter types remain unavailable.',
        'observer_requirement': 'source', 'default': False,
    },
    {
        'id': 'verify-activity-share', 'name': 'Verify activity share',
        'question': 'What share of selected labeled agent units are classified as Verify?',
        'use': 'Compare recorded verification activity across rollouts with annotation coverage in view.',
        'kind': 'metric', 'metric': 'agent_verify_unit_share', 'group': 'Behavior',
        'evidence_requirement': 'A selected semantic observation with labeled agent prose or action units; this is unit frequency, not passing checks.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'failed-operation-share', 'name': 'Failed operation share',
        'question': 'What fraction of fully classified operations have a failed outcome?',
        'use': 'Monitor selected operation outcomes while keeping incomplete or inconsistent outcomes unknown.',
        'kind': 'metric', 'metric': 'operation_failed_fraction', 'group': 'Training',
        'evidence_requirement': 'A selected semantic observation with complete, consistent source-bound response outcomes.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'same-work-returns', 'name': 'Returns after intervening operations',
        'question': 'How many recorded same-work recurrences happen after intervening operations?',
        'use': 'Inspect recurrence after other work while keeping recurrence separate from failure or recovery.',
        'kind': 'analysis', 'measure': 'returns', 'group': 'Behavior',
        'evidence_requirement': 'Native action units, supported work identity, and saved recurrence links; missing review remains unknown.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'revisit-inputs', 'name': 'Changed inputs on work revisits',
        'question': 'Which repeated attempts changed their recorded inputs?',
        'use': 'Open the earlier attempt, changed fields, intervening operations and later feedback from a behavior curve.',
        'kind': 'analysis', 'measure': 'revisit_input_change_fraction', 'group': 'Behavior',
        'evidence_requirement': 'Saved same-work identities and comparable native inputs or full recorded action text.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'revisit-matching-feedback', 'name': 'Repeated inputs and feedback',
        'question': 'Which same-work pairs repeat both inputs and captured feedback?',
        'use': 'Inspect matching records alongside intervening work. Missing feedback stays outside the rate.',
        'kind': 'analysis', 'measure': 'revisit_exact_repeat_fraction', 'group': 'Behavior',
        'evidence_requirement': 'Saved same-work identities with ordered, source-bound, nonempty feedback for both attempts.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'feedback-reference', 'name': 'Explicit feedback reference',
        'question': 'How often is visible tool feedback explicitly referenced in the next three agent text events?',
        'use': 'Track saved feedback references while exposing unknown inspection windows and coverage.',
        'kind': 'analysis', 'measure': 'feedback_reference', 'group': 'Behavior',
        'evidence_requirement': 'Visible source-bound textual responses, selected semantic units, and reviewed feedback opportunities.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'return-to-earlier-work', 'name': 'Returns to earlier work',
        'question': 'How many observed work visits return to an earlier subject?',
        'use': 'Inspect explicit work returns without treating recurrence as exploration, failure, or waste.',
        'kind': 'analysis', 'measure': 'work_return_visits_parallel', 'group': 'Behavior',
        'evidence_requirement': 'Saved work identity and contribution bindings with enough history to establish observed visits.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id': 'procedure-change', 'name': 'Procedure change on recurrence',
        'question': 'What share of comparable same-work recurrences use a changed procedure?',
        'use': 'Inspect exact-pair procedure comparisons while leaving unresolved comparisons outside the decidable denominator.',
        'kind': 'analysis', 'measure': 'procedure_change_fraction', 'group': 'Behavior',
        'evidence_requirement': 'Saved recurrence links and a supported exact-pair procedure comparison; a procedure change does not establish success.',
        'observer_requirement': 'explicit_observer', 'default': False,
    },
    {
        'id':'error-report-repeat','name':'Errors on repeated work',
        'question':'Do execution errors persist on the next attempt at the same work?',
        'use':'Open each pair to compare the approach, stated reason and both executor responses.',
        'kind':'analysis','measure':'error_report_repeat_fraction','group':'Behavior',
        'evidence_requirement':'Saved same-work links and source-bound executor-report inspections. Missing inspections stay unknown; no reported error does not establish recovery.',
        'observer_requirement':'explicit_observer','default':False,
    },
]


def _definition(recipe, observer):
    result = {key: recipe[key] for key in ('name', 'kind', 'group')}
    result['observer'] = observer
    if recipe['kind'] == 'metric':
        result['metric'] = recipe['metric']
    else:
        result['analysis'] = {'measure': recipe['measure']}
    return result


def catalog(query=None):
    """Return searchable recipe metadata, optionally filtered by query text.

    Search is case-insensitive across names, questions, use guidance, evidence
    requirements, groups and registered measure IDs.
    """
    rows = []
    for recipe in _RECIPES:
        row = deepcopy(recipe)
        row['definition'] = _definition(recipe, 'source' if recipe['observer_requirement'] == 'source' else None)
        rows.append(row)
    if query is None or not str(query).strip():
        return rows
    terms = str(query).casefold().split()
    fields = ('id','name','question','use','evidence_requirement','group','metric','measure')
    return [row for row in rows if all(term in ' '.join(str(row.get(k,'')) for k in fields).casefold() for term in terms)]


def default_definitions(observer=None):
    """Build validated monitor inputs for source defaults and opt-in recipes.

    Without an observer, return only source-backed starters. Supplying an
    observer explicitly adds semantic starters using that selected observer;
    callers should first confirm it has compatible saved observations.
    """
    selected = [recipe for recipe in _RECIPES if recipe['observer_requirement'] == 'source' and recipe['default']]
    if observer is not None:
        if not isinstance(observer, str) or not observer.strip() or observer == 'source':
            raise ValueError('Select a non-source observer to include semantic recipes')
        selected += [recipe for recipe in _RECIPES if recipe['observer_requirement'] == 'explicit_observer']
    return [_definition(recipe, 'source' if recipe['observer_requirement'] == 'source' else observer)
            for recipe in selected]


def validate_catalog():
    """Return any catalog entries that no longer resolve to current measures."""
    missing = []
    for recipe in _RECIPES:
        if recipe['kind'] == 'metric' and recipe['metric'] not in METRICS:
            missing.append(recipe['id'])
        if recipe['kind'] == 'analysis' and recipe['measure'] not in analysis_metrics.catalog():
            missing.append(recipe['id'])
    return missing
