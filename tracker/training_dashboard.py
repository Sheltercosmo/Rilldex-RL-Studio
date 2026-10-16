"""Choose useful RL views from a single, already scoped evidence snapshot.

This is presentation policy, not a detector or trainer configuration. Generation
and use recipes are deliberately independent; no adjacent recipe can fill a gap.
"""

VERSION = 'training-dashboard/4'


def monitors(value):
    plan = value.get('monitoring_plan') or {}
    # An unverified revision may suggest checks, but must not select a method's
    # default view as if its field interpretation had been verified.
    if plan.get('status') != 'ready':
        return set()
    return {m['id'] for g in plan['groups'] for m in g['monitors']}


def stream_priority(stream):
    values = stream.get('value_observation') or {}
    if any(s.get('eligible_positions', 0) for s in values.get('series', [])):
        return 4, 'Recorded value predictions and return targets support masked error and variation checks at each training use.'
    regression = stream.get('regression') or {}
    if regression.get('compatible_definitions') and regression.get('eligible_uses',0):
        return 4, 'Recorded predictions and targets make the regression objective measurable at each training use.'
    gradient = stream.get('policy_gradient') or {}
    if (gradient.get('compatible_definitions') and gradient.get('eligible_tokens', 0)
            and gradient.get('observed_uses', 0) > gradient.get('unbound_uses', 0)):
        return 4, 'Recorded policy-loss gradients connect the objective to the tokens used for training.'
    if any(c.get('known_tokens', 0) for c in (stream.get('policy_age') or {}).get('clocks', [])):
        return 3, 'Recorded policy versions make policy age at training measurable.'
    ids = monitors(stream)
    if ids & {'critic_credit', 'actor_critic_schedule'}:
        return 2, 'These training-use settings include a value model. Inspect training use and the available credit evidence.'
    if ids & {'policy_lag', 'policy_segments', 'policy_mismatch'}:
        return 2, 'These training-use settings need sampling-policy checks. Missing policy history remains visible.'
    if ids & {'return_credit', 'batch_baseline', 'state_groups', 'episode_baseline', 'cached_baseline'}:
        return 2, 'These training-use settings need return, batch or episode credit. Prompt-group reward variation cannot substitute.'
    return 0, 'Training-use records are available; sampling settings are not substituted for the learner settings.'


def project(cohort, *, has_monitor=False):
    choices = []

    def add(identifier, mode, label, reason, *, priority=0, **extra):
        choices.append({'id': identifier, 'mode': mode, 'label': label, 'reason': reason,
                        'priority': priority, **extra})

    if has_monitor:
        add('behavior', 'behavior', 'Behavior across training',
            'Your selected behavior measure is joined to generation and training use, with coverage shown separately.', priority=100)
    if cohort.get('attempt_chains'):
        add('attempts', 'attempts', 'Recovery after failure',
            'Explicit attempt links and verifier outcomes support a recovery comparison.', priority=90)
    if cohort.get('rewards'):
        group = next((c for c in cohort.get('capabilities', []) if c['id'] == 'group_contrast'), {})
        why = ('The recorded sampling settings use a prompt-group baseline. Compare rewards and complete-group variation.'
               if group.get('applicability') == 'applicable' else
               'Compare recorded reward components. Group-baseline diagnostics require their own settings and membership evidence.')
        add('reward', 'reward', 'Rewards', why, priority=40,
            records=sum(sum(r['states'].values()) - r['states'].get('missing', 0) for r in cohort['rewards']))
    retained=(cohort.get('retained_rl_signals') or {}).get('series',[])
    relationships = cohort.get('reward_relationships') or {}
    if len(relationships.get('components', [])) > 1:
        add('reward_relationships', 'reward_relationships', 'Reward relationships',
            'Multiple reward components can be compared on the same samples, with complete prompt groups separated from overall task differences.',
            priority=(55 if 'reward_components' in monitors(cohort) else 46)
            if relationships.get('matched_samples', 0) >= 2 else 15)
    if retained:
        eligible=any(f['count'] for s in retained for f in s['fields'].values())
        add('retained','retained','Retained batch signals',
            'Native batch exports include aligned learning-signal fields. Inspect their masks and rollout-batch trends separately from confirmed training use.',
            priority=45 if eligible else 20)
    # Stable identity breaks ties. Arrival order and incomparable learner steps
    # must not decide which method a population appears to use.
    for stream in sorted(cohort.get('uses', []), key=lambda s: s['id']):
        rank, reason = stream_priority(stream)
        values = stream.get('value_observation') or {}
        label = ('Value predictions and returns' if any(s.get('eligible_positions', 0) for s in values.get('series', []))
                 else 'Policy-loss signal' if (stream.get('policy_gradient') or {}).get('eligible_tokens', 0)
                 else 'Prediction and target' if (stream.get('regression') or {}).get('eligible_uses', 0)
                 else 'Training use')
        add('use:' + stream['id'], 'use', label, reason,
            priority=50 + rank if rank else 30, use_id=stream['id'],
            records=stream.get('receipts', 0), stage=stream['stage'], producer=stream['producer'])
    if cohort.get('teachers'):
        add('teacher', 'teacher', 'Teacher signals',
            'Prepared teacher observations are available. They do not establish an RL update.', priority=10)
    if choices:
        default = sorted(choices, key=lambda c: (-c['priority'], c['id']))[0]
    else:
        # No measured state is implied by a recognized config.
        default = {'id':'use', 'mode':'use', 'label':'Training use',
                   'reason':'No reward or training-use records have arrived for this population.'}
    default = {k:v for k,v in default.items() if k != 'priority'}
    choices = [{k:v for k,v in c.items() if k != 'priority'} for c in choices]
    return {'schema':VERSION, 'default':default, 'choices':choices,
            'boundary':'Defaults use the selected population only. Sampling and learner settings stay separate; no thresholds, methods or stored measurements are changed.'}
