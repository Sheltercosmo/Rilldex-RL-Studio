"""Learning-signal diagnostics from retained native facts; no inference or model calls.

Generation-coordinate reward groups and learner-coordinate use receipts are
different populations. A component's lack of contrast is not zero total reward
advantage, and a positive loss mask is not proof of a nonzero gradient.
"""
from collections import Counter, defaultdict
from statistics import fmean, pstdev
import json

from .schema import digest, dumps
from . import training_lineage, training_selection, training_recipes, teacher_signals, policy_gradients
from . import policy_age, attempt_chains, training_monitoring, training_behavior, training_dashboard, regression_signals, value_observations, retained_rl_signals
from .population_statistics import summary as behavior_summary
from . import reward_relationships

VERSION = 'training-health/15'


def ratio(numerator, denominator):
    return {'value': numerator / denominator if denominator else None,
            'numerator': numerator, 'denominator': denominator}


def sample_ref(sample):
    return {'schema': sample.get('sample_identity_schema', training_lineage.VERSION),
            'producer': sample['producer'], 'id': sample.get('sample_id', sample.get('rollout_id')),
            'run_id': sample.get('run_id')}


def score_key(record):
    d = record['data']
    return {'producer': record['record_producer'], 'component': d['component'], 'definition': d['definition']}


def scored(sample, key):
    matches = [r for r in sample['records'] if r['kind'] == 'score' and score_key(r) == key]
    if not matches:
        return {'status': 'missing', 'value': None}
    # Two independent records for the same component are ambiguous, even when
    # their values happen to match. Revisions were resolved by lineage.snapshot.
    if len(matches) != 1:
        return {'status': 'conflicting', 'value': None}
    return {**matches[0]['data'], 'record': {'id': matches[0]['id'], 'revision': matches[0]['revision']}}


def reward_summary(samples, key):
    scores = [scored(s, key) for s in samples]
    values = [s['value'] for s in scores if s['status'] == 'scored']
    return {'samples': len(samples), 'states': dict(Counter(s['status'] for s in scores)),
            'mean': fmean(values) if values else None,
            'std': pstdev(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None,
            'scored_fraction': ratio(len(values), len(samples))}


def reward_groups(samples, key):
    groups = defaultdict(list)
    for s in samples:
        if s.get('group_id'):
            groups[s['group_id']].append(s)
    result = []
    for group, members in sorted(groups.items()):
        values = [scored(s, key) for s in members]
        expected = {s.get('group_size') for s in members}
        context_conflict = any(len({dumps(s.get(k)) for s in members}) > 1
                               for k in ('task_id', 'policy_version', 'step'))
        ambiguous_namespace = any(s.get('sample_identity_schema') for s in members) and len({s['producer'] for s in members}) > 1
        if context_conflict or ambiguous_namespace or len(expected) > 1:
            status = 'conflicting_context'
        elif None in expected:
            status = 'size_unrecorded'
        elif len(members) != next(iter(expected)):
            status = 'incomplete' if len(members) < next(iter(expected)) else 'overfull'
        elif len(members) < 2:
            status = 'singleton'
        elif any(s['status'] != 'scored' for s in values):
            status = 'scores_incomplete'
        else:
            status = 'complete'
        numeric = [s['value'] for s in values if s['status'] == 'scored']
        result.append({'group_id': group, 'status': status, 'observed': len(members),
            'expected': next(iter(expected)) if len(expected) == 1 else None,
            'step': members[0].get('step') if not context_conflict else None,
            'policy_version': members[0].get('policy_version') if not context_conflict else None,
            'constant': len(set(numeric)) == 1 if status == 'complete' else None,
            'mean': fmean(numeric) if numeric else None,
            'std': pstdev(numeric) if len(numeric) > 1 else None,
            'samples': [{**sample_ref(s), 'score': scored(s, key)} for s in members]})
    return result


def group_summary(groups):
    complete = [g for g in groups if g['status'] == 'complete']
    constant = [g for g in complete if g['constant']]
    return {'group_states': dict(Counter(g['status'] for g in groups)),
            'constant_groups': ratio(len(constant), len(complete)),
            'samples_in_constant_groups': ratio(sum(g['observed'] for g in constant), sum(g['observed'] for g in complete))}


def use_summary(receipts):
    known_mask = [r for r in receipts if 'loss_tokens' in r['data']]
    positive = [r for r in known_mask if r['data']['loss_tokens'] > 0]
    advantages = [r for r in positive if 'advantage' in r['data']]
    token_pairs = [r for r in known_mask if 'model_tokens' in r['data']]
    return {'receipts': len(receipts),
        'unique_samples': len({dumps(r['sample']) for r in receipts}),
        'positive_mask': ratio(len(positive), len(known_mask)),
        'zero_advantage': ratio(sum(r['data']['advantage'] == 0 for r in advantages), len(advantages)),
        'negative_advantage': ratio(sum(r['data']['advantage'] < 0 for r in advantages), len(advantages)),
        'positive_advantage': ratio(sum(r['data']['advantage'] > 0 for r in advantages), len(advantages)),
        'loss_token_fraction': ratio(sum(r['data']['loss_tokens'] for r in token_pairs), sum(r['data']['model_tokens'] for r in token_pairs)),
        'unknown_mask': len(receipts) - len(known_mask),
        'unknown_advantage_with_positive_mask': len(positive) - len(advantages),
        'unknown_token_pair': len(receipts) - len(token_pairs)}


def project(population, *, reward_x=None, reward_y=None):
    from .monitoring import unit, description, aggregation
    opportunity_ratio=bool(population['monitor'] and aggregation(population['monitor'])=='opportunity_ratio')
    cohorts = []
    for c in population['cohorts']:
        context = c['cohort']
        samples = [s for s in population['samples'] if all(s.get(k) == v for k, v in context.items())]
        # The legacy cohort has no sample_identity_schema key.
        samples = [s for s in samples if bool(s.get('sample_identity_schema')) == bool(context.get('sample_identity_schema'))]
        rewards = {}
        for s in samples:
            for record in s['records']:
                if record['kind'] == 'score':
                    key = score_key(record)
                    rewards[dumps(key)] = key
        reward_views = []
        for _, key in sorted(rewards.items()):
            groups = reward_groups(samples, key)
            points = []
            for step in sorted({s['step'] for s in samples if 'step' in s}):
                members = [s for s in samples if s.get('step') == step]
                points.append({'step': step, **reward_summary(members, key),
                    **group_summary([g for g in groups if g['step'] == step]),
                    'samples': [{**sample_ref(s), 'score': scored(s, key)} for s in members]})
            reward_views.append({'id': 'reward-' + digest(key), **key, **reward_summary(samples, key),
                **group_summary(groups), 'groups': groups, 'points': points,
                'missing_group': sum(not s.get('group_id') for s in samples),
                'missing_step': sum('step' not in s for s in samples)})
        uses = defaultdict(list)
        for s in samples:
            for r in s['records']:
                if r['kind'] == 'use':
                    policy=r['data'].get('learner_policy')
                    clock={k:policy[k] for k in ('clock','unit')} if policy else None
                    uses[(r['record_producer'], r['data']['stage'], dumps(r['data'].get('recipe')), dumps(clock))].append({
                        'id': r['id'], 'revision': r['revision'], 'sample': sample_ref(s),
                        'record_producer':r['record_producer'], 'record_schema':r.get('record_schema',training_lineage.VERSION),
                        'policy_age':policy_age.observe(s.get('policy_history'), r['data'].get('learner_policy'), r['data'].get('model_tokens')),
                        'data': r['data'], 'evidence': r['evidence']})
        use_views = []
        for (producer, stage, recipe_key, clock_key), receipts in sorted(uses.items()):
            recipe_ref = json.loads(recipe_key)
            learner_clock = json.loads(clock_key)
            recipe_context = training_recipes.resolve(population.get('recipes', []), context['experiment'], recipe_ref)
            points = []
            for step in sorted({r['data']['learner_step'] for r in receipts}):
                rows = [r for r in receipts if r['data']['learner_step'] == step]
                points.append({'step': step, **use_summary(rows),
                    'policy_age':policy_age.summarize(rows),
                    'policy_gradient':policy_gradients.summarize(rows, recipe_context),
                    'value_observation':value_observations.summarize(rows, recipe_context),
                    'regression':regression_signals.summarize(rows,recipe_context), 'records': rows})
            by_sign = {}
            sources = {}
            for sign, test in [('positive', lambda a: a > 0), ('negative', lambda a: a < 0), ('zero', lambda a: a == 0)]:
                eligible = [r for r in receipts if r['data'].get('loss_tokens', 0) > 0
                            and 'advantage' in r['data'] and test(r['data']['advantage'])]
                identities = {dumps(r['sample']) for r in eligible}
                members = [s for s in samples if dumps(sample_ref(s)) in identities and s['monitor_population'] == 'included']
                sources[sign] = {s['run_id'] for s in members if s.get('run_id')}
                by_sign[sign] = {**behavior_summary(members, False, source_weighted=True),
                    'receipts': len(eligible), 'outside_monitor_scope': len(identities) - len(members),
                    'samples': [{**sample_ref(s), 'measurement': s.get('measurement')} for s in members]}
            by_gradient = {}; gradient_sources = {}
            for state in ('zero','nonzero','masked_out','unavailable'):
                eligible = [r for r in receipts if policy_gradients.sample_state(r,recipe_context) == state]
                identities = {dumps(r['sample']) for r in eligible}
                members = [s for s in samples if dumps(sample_ref(s)) in identities and s['monitor_population']=='included']
                gradient_sources[state] = {s['run_id'] for s in members if s.get('run_id')}
                by_gradient[state] = {**behavior_summary(members,False,source_weighted=True),
                    'receipts':len(eligible),'outside_monitor_scope':len(identities)-len(members),
                    'samples':[{**sample_ref(s),'measurement':s.get('measurement')} for s in members]}
            use_views.append({'id': producer+'/'+stage+('/'+digest(recipe_ref) if recipe_ref else '')+('/'+digest(learner_clock) if learner_clock else ''),
                'producer': producer, 'stage': stage, 'recipe_context': recipe_context, 'learner_policy_clock':learner_clock,
                'monitoring_plan':training_monitoring.for_context(recipe_context),
                'behavior_timeline':training_behavior.project(samples,sample_ref,receipts=receipts,opportunity_ratio=opportunity_ratio) if population['monitor'] else None,
                'capabilities': training_recipes.capabilities(recipe_context, uses=receipts),
                **use_summary(receipts), 'points': points,
                'policy_gradient':policy_gradients.summarize(receipts, recipe_context),
                'value_observation':value_observations.summarize(receipts, recipe_context),
                'regression':regression_signals.summarize(receipts, recipe_context),
                'policy_age':policy_age.summarize(receipts),
                'behavior_by_policy_age':policy_age.behavior_groups(receipts,samples,sample_ref) if population['monitor'] else None,
                'behavior_by_policy_gradient':by_gradient if population['monitor'] else None,
                'zero_nonzero_gradient_shared_sources':len(gradient_sources['zero'] & gradient_sources['nonzero']),
                'behavior_by_advantage': by_sign if population['monitor'] else None,
                'positive_negative_shared_sources': len(sources['positive'] & sources['negative'])})
        filters = []
        for f in training_selection.options(samples):
            states = Counter(training_selection.decision(s, f)['state'] for s in samples)
            filters.append({**f, 'states': dict(states),
                'admission': ratio(states['admitted'], states['admitted'] + states['rejected'])})
        recipe_context = training_recipes.resolve(population.get('recipes', []), context['experiment'], context.get('recipe'))
        teachers = teacher_signals.project(samples, population.get('recipes', []), context['experiment'], sample_ref)
        cohorts.append({'id': 'health-' + digest(context), 'cohort': context, 'samples': len(samples),
            'recipe_context': recipe_context, 'capabilities': training_recipes.capabilities(recipe_context, rewards=reward_views),
            'monitoring_plan':training_monitoring.for_context(recipe_context),
            'behavior_timeline':training_behavior.project(samples,sample_ref,opportunity_ratio=opportunity_ratio) if population['monitor'] else None,
            'rewards': reward_views, 'uses': use_views, 'teachers': teachers, 'filters': filters,
            'reward_relationships': reward_relationships.project(samples, reward_views, scored, sample_ref, x=reward_x, y=reward_y),
            'retained_rl_signals':retained_rl_signals.project(samples, sample_ref),
            'attempt_chains': attempt_chains.project(samples, sample_ref, monitor=bool(population['monitor'])),
            'missing_source': sum(s.get('run_id') is None for s in samples)})
    for cohort in cohorts:
        cohort['dashboard'] = training_dashboard.project(cohort, has_monitor=bool(population['monitor']))
    result = {'schema': VERSION, 'revision': population['revision'], 'cohorts': cohorts,
        'monitor': population['monitor'], 'monitor_options': population['monitor_options'],
        'behavior_metric': {'unit': unit(population['monitor']), 'description': description(population['monitor']),
                            'aggregation':aggregation(population['monitor'])} if population['monitor'] else None,
        'orphan_samples': population['orphan_samples'], 'conflicting_samples': population['conflicting_samples'],
        'scope': 'Captured facts only. Reward curves use the sample generation coordinate; use curves use the producer learner coordinate; teacher curves use the declared signal-preparation coordinate. Prepared supervision is not proof of backward or optimizer use. Sampled log ratios are not full-distribution KL. Components, record producers, environments, splits and source clocks stay separate. Missing receipts do not establish non-use. Component contrast and scalar advantages do not establish final gradient contribution. No universal alert thresholds.'}
    return {**result, 'snapshot_id': 'training-health-' + digest(result)}


def snapshot(store, *, experiment=None, environment=None, monitor=None, reward_x=None, reward_y=None):
    from . import generation_cohorts
    # Curves and scheduler completeness must describe the same read transaction.
    with store.read_snapshot() as saved:
        result=project(training_lineage.snapshot(saved, experiment=experiment, environment=environment, monitor=monitor),
                       reward_x=reward_x, reward_y=reward_y)
        return with_population_evidence(result,generation_cohorts.project(saved,experiment=experiment,environment=environment,monitor=monitor))


def with_population_evidence(result,evidence):
    core={k:v for k,v in result.items() if k!='snapshot_id'}
    core['declared_populations']=evidence
    return {**core,'snapshot_id':'training-health-'+digest(core)}
