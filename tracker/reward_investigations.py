"""Reward chart -> pinned population -> existing behavior investigation."""
from copy import deepcopy
from urllib.parse import urlencode

from . import training_lineage, training_health, training_investigations, failure_investigations
from . import reward_relationships, generation_cohorts
from .schema import InputError, dumps

VERSION = 'reward-investigation-context/1'


def pattern_label(pattern, selected):
    x, y = selected['x']['component'], selected['y']['component']
    return {'both_above':'Both rewards above their group means',
        'x_above_y_below':x+' above, '+y+' below group mean',
        'x_below_y_above':x+' below, '+y+' above group mean',
        'both_below':'Both rewards below their group means',
        'at_mean':'At least one reward at its group mean',
        'unavailable':'Group comparison unavailable'}[pattern]


def sample_key(row, *, pair=False):
    if pair:
        return dumps((row['schema'], row['producer'], row['id']))
    return dumps((row.get('sample_identity_schema', training_lineage.VERSION), row['producer'],
                  row.get('sample_id', row.get('rollout_id'))))


def selector_members(parent, selector, cohort):
    context = parent.get('reward_comparison')
    if not context or context['schema'] != VERSION or context['cohort'] != cohort:
        raise InputError('Reward patterns require their saved reward-comparison cohort')
    if selector.get('value') not in reward_relationships.PATTERNS:
        raise InputError('Select an existing saved reward pattern')
    return {sample_key(row, pair=True) for row in context['evidence']['records']
            if row['reward_pattern'] == selector['value']}


def save(store, raw):
    required = {'scope','snapshot_id','cohort_id','reward_x','reward_y','title','hypothesis'}
    if not isinstance(raw, dict) or set(raw)-required-{'step'} or not required <= set(raw):
        raise InputError('Supply the displayed reward pair, population and snapshot identity')
    scope = raw['scope']
    if (not isinstance(scope,dict) or set(scope)-{'experiment','environment','monitor'}
            or any(not isinstance(v,str) or not v for v in scope.values())):
        raise InputError('Invalid reward investigation scope')
    for key in ('snapshot_id','cohort_id','reward_x','reward_y','title','hypothesis'):
        if not isinstance(raw[key],str): raise InputError('Invalid '+key)
    if not raw['title'].strip() or len(raw['title'])>120 or len(raw['hypothesis'])>6000:
        raise InputError('Use a title up to 120 characters and hypothesis up to 6000')
    with store.read_snapshot() as saved:
        population = training_lineage.snapshot(saved, **scope)
        health = training_health.with_population_evidence(
            training_health.project(population, reward_x=raw['reward_x'], reward_y=raw['reward_y']),
            generation_cohorts.project(saved, experiment=scope.get('experiment'), environment=scope.get('environment'), monitor=scope.get('monitor')))
        source_graphs=training_investigations.source_graphs(saved,population)
    if raw['snapshot_id'] != health['snapshot_id']:
        raise InputError('Reward evidence changed. Refresh and review before saving.')
    cohort = next((c for c in health['cohorts'] if c['id']==raw['cohort_id']),None)
    if cohort is None or cohort['reward_relationships']['status'] != 'available':
        raise InputError('Selected reward comparison is outside this snapshot')
    pair = cohort['reward_relationships']
    selection = {'cohort':cohort['cohort'], **({'step':raw['step']} if 'step' in raw else {})}
    value = training_investigations.build_value(population, scope, {'stage':'generated','selection':selection},
        raw['title'], raw['hypothesis'], source_graphs)
    value['reward_comparison'] = {'schema':VERSION, 'health_snapshot_id':health['snapshot_id'],
        'cohort':deepcopy(cohort['cohort']), 'cohort_id':cohort['id'], 'evidence':deepcopy(pair),
        'pattern_options':[{'value':key,'label':pattern_label(key,pair['selected']),
                            'samples':pair['patterns'][key]} for key in reward_relationships.PATTERNS],
        'boundary':'Patterns compare each raw score with its mean in a complete native group. '
            'They are case-selection rules, not semantic activity tags, reward preference directions, '
            'native advantages or diagnoses. Group means use the original complete population, '
            'not a subsequently filtered focus/reference subset.'}
    value['live_url'] = '/?' + urlencode({'view':'health', **scope, 'health_mode':'reward_relationships',
        'health_cohort':cohort['id'], 'health_reward_x':raw['reward_x'], 'health_reward_y':raw['reward_y']})
    return failure_investigations.persist(store,value)
