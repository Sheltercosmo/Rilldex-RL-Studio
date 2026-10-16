"""Bind reusable population comparisons to a saved training investigation."""
from copy import deepcopy
import json

from . import failure_investigations as investigations, training_investigations, training_selection
from . import monitoring, population_comparisons, training_samples
from .schema import InputError, digest
from . import reward_investigations

VERSION = 'training-measure-comparison/1'


def options(store):
    return {'monitors': [{k: m[k] for k in ('id', 'name', 'observer', 'enabled')}
                          for m in monitoring.definitions(store)], 'max_monitors': 8}


def validate(parent, raw):
    if not isinstance(raw, dict) or set(raw) - {'cohort', 'step', 'focus', 'reference', 'monitors'} or not {'cohort','focus','reference','monitors'} <= set(raw):
        raise InputError('Choose a cohort, focus, reference and monitors')
    if raw['cohort'] not in [c['cohort'] for c in parent['snapshot']['cohorts']]:
        raise InputError('Cohort is outside the saved population')
    if 'step' in raw and (type(raw['step']) is not int or raw['step'] < 0):
        raise InputError('Step must be a recorded nonnegative integer')
    monitors = raw['monitors']
    if not isinstance(monitors, list) or not 1 <= len(monitors) <= 8 or any(not isinstance(k,str) or not k for k in monitors) or len(set(monitors)) != len(monitors):
        raise InputError('Select one to eight distinct monitors')
    for key in ('focus', 'reference'):
        s = raw[key]
        if not isinstance(s,dict) or set(s) != {'kind','value'} or not isinstance(s['value'],str):
            raise InputError('Invalid population selector')
        if s['kind'] == 'stage' and s['value'] in training_investigations.STAGES: continue
        if s['kind'] == 'filter' and parent['snapshot']['selection'] and s['value'] in training_selection.STATES: continue
        if s['kind'] == 'reward_pattern':
            reward_investigations.selector_members(parent,s,raw['cohort'])
            continue
        raise InputError('Select a recorded stage or a decision from the saved named filter')
    if raw['focus'] == raw['reference']: raise InputError('Focus and reference must differ')
    return deepcopy(raw)


def preview(store, raw):
    if not isinstance(raw,dict) or set(raw) != {'parent_id','spec'} or not isinstance(raw['parent_id'],str):
        raise InputError('Provide a saved investigation and comparison specification')
    parent = investigations.read(store, raw['parent_id'])
    if parent['schema'] != training_investigations.VERSION: raise InputError('Expected a saved training investigation')
    spec = validate(parent, raw['spec']); snapshot = parent['snapshot']
    rows = [r for r in snapshot['samples'] if all(r.get(k) == v for k,v in spec['cohort'].items()) and
            ('step' not in spec or r.get('step') == spec['step'])]
    if not rows: raise InputError('No saved samples at this coordinate')
    fields = ('experiment','producer','rollout_id','run_id','task_id','policy_version','step','group_id')
    samples = [{**{k: r.get(k) for k in fields}, **{k:r[k] for k in ('sample_id','sample_identity_schema','source','interaction_ids','source_mapping_status','measurement_grain','episode','token_context_summary','recipe') if k in r},
        'id': 'sample-' + digest(training_samples.identity(r))} for r in rows]
    if len({s['id'] for s in samples}) != len(samples): raise InputError('Duplicate declared sample identity')
    reward_context = parent.get('reward_comparison')
    if reward_context and reward_context['cohort'] == spec['cohort']:
        paired = {reward_investigations.sample_key(r,pair=True):r for r in reward_context['evidence']['records']}
        for sample,row in zip(samples,rows):
            evidence=paired.get(reward_investigations.sample_key(row))
            if evidence:
                sample['reward_evidence']={k:deepcopy(evidence[k]) for k in ('reward_pattern','group_status','group_id','step','x','y')}
    def members(selector):
        if selector['kind']=='reward_pattern':
            selected = reward_investigations.selector_members(parent,selector,spec['cohort'])
            return [s['id'] for s,r in zip(samples,rows) if reward_investigations.sample_key(r) in selected]
        return [s['id'] for s,r in zip(samples,rows) if (r['populations'][selector['value']] if selector['kind']=='stage'
                else training_selection.decision(r,snapshot['selection'])['state']==selector['value'])]
    # Source identities come from the saved join; late deliveries cannot enter it.
    with store.connect() as c:
        metadata = {r['id']:json.loads(r['metadata']) for r in c.execute(
            "SELECT id,json_extract(document,'$.metadata') metadata FROM runs") if r['id'] in parent['source_graphs']}
    definitions = {m['id']:m for m in monitoring.definitions(store)}
    retained = {m['monitor']['id']:m for m in parent.get('measure_comparison',{}).get('metrics',[])}
    primary = snapshot['monitor']; measures = []
    for mid in spec['monitors']:
        if mid in retained:
            definition = retained[mid]['monitor']; values = retained[mid]['values']; origin = 'saved_comparison'
        elif primary and mid == primary['id']:
            definition = primary; values = {s['id']:r.get('measurement') for s,r in zip(samples,rows)}; origin = 'saved_primary'
        else:
            if mid not in definitions: raise InputError('Unknown monitor')
            definition = definitions[mid]
            latest = monitoring.values(store, mid, {r['run_id'] for r in rows if r['run_id']})
            values = {s['id']:latest.get(s['run_id']) for s in samples}; origin = 'current_saved_observations'
        definition = {k:v for k,v in definition.items() if k!='enabled'}
        if definition['id'] != 'monitor-' + digest({k:v for k,v in definition.items() if k!='id'}):
            raise InputError('Monitor definition identity mismatch')
        bound = {}
        for sample in samples:
            sid = sample['id']; rid = sample['run_id']; graph = parent['source_graphs'].get(rid); v = values.get(sid)
            if rid not in metadata or not graph:
                value = {'status':'source_unavailable','value':None,'reason':'No source binding in the saved population'}
            elif not monitoring.in_population(definition, {'metadata':metadata[rid]}):
                value = {'status':'outside_monitor_population','value':None,'reason':'Outside this monitor definition’s source population'}
            elif not v:
                value = {'status':'not_materialized','value':None,'reason':'No retained measurement for this sample'}
            elif origin == 'saved_comparison' and 'id' not in v:
                value = deepcopy(v)  # Hash-verified parent's explicit missingness.
            else:
                if v['id'] != 'value-' + digest({k:x for k,x in v.items() if k!='id'}) or v['monitor_id'] != mid or v['run_id'] != rid:
                    raise InputError('Measurement identity mismatch')
                value = deepcopy(v)
                if v.get('source_hash') != graph['source_hash']:
                    value = {'status':'source_mismatch','value':None,'reason':'Measurement does not bind the saved source'}
                elif v['status']=='available' and not population_comparisons.available(v):
                    raise InputError('Available measurement must have a finite numeric value')
            bound[sid] = value
        measures.append({'monitor':definition,'description':monitoring.description(definition),'unit':monitoring.unit(definition),
            'aggregation':monitoring.aggregation(definition),'observation_origin':origin,'values':bound})
    result = population_comparisons.compare(samples,members(spec['focus']),members(spec['reference']),measures)
    result.update(schema='training-measure-comparison/2' if result.get('weighting') else VERSION, comparison_schema=result['schema'], parent_id=parent['id'],
                  population_snapshot_id=snapshot['snapshot_id'], spec=spec, inference_calls=0)
    if any(spec[k]['kind']=='reward_pattern' for k in ('focus','reference')):
        context=parent['reward_comparison']
        result['reward_context']={'health_snapshot_id':context['health_snapshot_id'],
            'selected':context['evidence']['selected'],'boundary':context['boundary'],
            'patterns':context['evidence']['patterns']}
    return {'id':'training-comparison-'+digest(result), **result}


def save(store, raw):
    if not isinstance(raw,dict) or set(raw) != {'parent_id','spec','preview_id'}:
        raise InputError('Provide the reviewed comparison identity')
    result = preview(store, {k:raw[k] for k in ('parent_id','spec')})
    if result['id'] != raw['preview_id']: raise InputError('Comparison observations changed. Preview and review again before saving.')
    parent = investigations.read(store,raw['parent_id'])
    value = {k:v for k,v in parent.items() if k!='id'}
    value.update(parent_id=parent['id'],measure_comparison=result)
    return investigations.persist(store,value)
