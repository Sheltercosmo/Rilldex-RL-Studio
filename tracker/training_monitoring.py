"""Question-led RL monitoring priorities, independent of stored metric definitions."""

VERSION = 'rl-monitoring-plan/3'
FRAMEWORKS = {'trl':'TRL', 'verl':'verl', 'areal':'AReaL', 'nemo_rl':'NeMo RL',
              'openrlhf':'OpenRLHF', 'slime':'slime', 'verl_agent':'verl-agent'}
GROUPS = (
    ('outcomes', 'Is task performance improving?', ['reward'], 'Compare reward with independent task outcomes.', 'health'),
    ('selection', 'Which samples reach training?', ['use', 'selection', 'truncation', 'turn_continuity'], 'Inspect rejection, reuse and loss masks against the generated population.', 'training'),
    ('credit', 'Where does the learning signal come from?', ['group_contrast', 'critic_credit', 'batch_baseline', 'return_credit', 'reward_components', 'decoupled_gae', 'episode_baseline', 'state_groups', 'advantage_components', 'cached_baseline'], 'Use the baseline and credit unit actually selected by the trainer.', 'health'),
    ('updates', 'How are policy updates weighted?', ['objective_exposure', 'unclipped_update', 'sequence_ratio', 'moment_constraint', 'sampling_support', 'regression'], 'Inspect the native policy objective and its correction terms.', 'health'),
    ('freshness', 'Is sampling aligned with training?', ['policy_lag', 'policy_segments', 'policy_mismatch', 'actor_critic_schedule'], 'Inspect policy versions, sampler probabilities and update boundaries.', 'training'),
)


def recommend(report):
    monitors = {m['id']: m for m in report['monitors']}
    groups = []
    for key, title, ids, why, view in GROUPS:
        selected = [monitors[i] for i in ids if i in monitors]
        if selected:
            groups.append({'id':key, 'title':title, 'why':why, 'monitors':selected,
                           'href':'/?view=' + view,
                           'basis':'Recognized settings' if report['status'] == 'ready' else 'Provisional: settings need review'})
    result = {'schema':VERSION, 'framework':FRAMEWORKS.get(report['framework'], report['framework']),
            'status':report['status'], 'groups':groups,
            'time_axes':[
                {'id':'generation', 'label':'Rollout generation', 'meaning':'Behavior and outcome of each generated rollout.'},
                {'id':'optimizer', 'label':'Training update', 'meaning':'The update that used the sample; a sample may be used more than once.'},
                {'id':'evaluation', 'label':'Evaluation policy', 'meaning':'Independent task results for a recorded policy under fixed evaluation conditions.'}],
            'boundary':'Recommendations do not create metrics or establish data coverage. Missing records stay missing; versioned native observations determine what can be measured.'}
    if report['framework'] == 'verl_agent':
        result['time_axes'].insert(0, {'id':'episode_turn', 'label':'Turn within an episode',
            'meaning':'Native ordered turns for behavior and recovery. A training dump row or its logged iteration does not establish episode order.'})
    return result


def for_context(context):
    """Recommend from the exact retained config, never from a neighboring run.

    This is a current, versioned presentation projection. It does not rewrite the
    historical recipe, metrics or evidence. Hand-authored recipes keep their
    existing capability display rather than guessing a native configuration.
    """
    setup = (context.get('manifest') or {}).get('setup')
    if not setup: return None
    from .training_setup import inspect, SUPPORTED_VERSIONS
    from .schema import InputError
    if setup.get('schema') == 'trl-a2po-setup/1':
        from .trl_a2po_setup import inspect as inspect_a2po
        return inspect_a2po({'config':setup['settings'],'version':setup['version'],'resolved':True})['monitoring_plan']
    if setup.get('schema') not in SUPPORTED_VERSIONS: return None
    config = dict(setup['settings'])
    if 'critic.enabled' in config:
        config['critic'] = {} if config.pop('critic.enabled') else None
    try:
        report = inspect({'framework':setup['framework'], 'version':setup['version'],
                          'resolved':True, 'config':config})
    except InputError:
        return None
    plan = report['monitoring_plan']
    plan['source_setup_schema'] = setup['schema']
    plan['reader_schema'] = report['schema']
    return plan
