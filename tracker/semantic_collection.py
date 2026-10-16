"""Register complete source-bound maps as one frozen observer collection.

Collections let a single extraction protocol span rollouts without adding a
hard-coded catalog entry per experiment. They do not establish accuracy.
"""
from pathlib import Path
from .schema import InputError,digest,dumps
from .semantic_extraction import load_extraction,read

VERSION='registered-semantic-collection/1'


def protocol(result,directory):
    raw=result['raw_extraction'];stages={}
    keys={row['partition_request'] for row in raw['windows'] if row.get('partition_request')}
    keys.update(u[k] for u in raw['units'] for k in ('activity_request','content_request') if u.get(k))
    for key in keys:
        req=read(Path(directory)/'decisions'/f'{key}.json')['request'];s=req['state'];stage=s['stage']
        spec={'model':req['model'],**{k:s.get(k) for k in ('harness','activity_standard','context_policy',
            'activity_routing','partition_standard','boundary_harness','candidate_description_contract')},
            'rule_hash':digest(s['rule'])}
        if stage=='partition':spec['candidate_producers']=sorted({p['origin'] for p in s['partitions']})
        if stage=='activity':spec['reading_producer']=s.get('activity_reading_candidates',{}).get('producer')
        if stage in stages and stages[stage]!=spec:raise InputError('Mixed extraction protocols within a rollout')
        stages[stage]=spec
    scope={k:raw.get(k) for k in ('schema','activity_standard','partition_policy','participant_scope','activity_reading_contract')}
    if raw.get('content_revision'):
        scope['content_revision']={k:raw['content_revision'].get(k) for k in ('schema','candidate_policy')}
    if raw.get('content_repair_run'):
        # A targeted repair is deliberately not interchangeable with uniform
        # extraction across a cohort: preserve which unit IDs received it.
        scope['content_repair']={k:raw['content_repair_run'].get(k) for k in ('schema','unit_ids')}
    return {'scope':scope,
        'stages':stages,'candidate_producers':sorted({u['candidate_producer'] for u in raw['units'] if u.get('candidate_producer')})}


def register(store,directory,run_ids,label):
    if (not isinstance(run_ids,list) or not run_ids or len(run_ids)>10000 or
            any(not isinstance(r,str) or not r.isalnum() for r in run_ids) or len(set(run_ids))!=len(run_ids)):
        raise InputError('Select 1–10000 distinct run IDs')
    if not isinstance(label,str) or not label.strip() or len(label)>160:raise InputError('Observer label must contain 1–160 characters')
    directory=Path(directory).resolve();members={};loaded=[];common=None
    for rid in sorted(run_ids):
        run=store.get(rid,raw=True)['run'];result=load_extraction(run,directory)
        if not result['available'] or result['raw_extraction']['status']!='complete_local_extraction':
            raise InputError('Every collection member requires audited complete extraction')
        current=protocol(result,directory)
        if common is None:common=current
        else:
            if current['scope']!=common['scope'] or current['candidate_producers']!=common['candidate_producers']:
                raise InputError('Collection members use different extraction protocols or candidate producers')
            for stage,spec in current['stages'].items():
                if stage in common['stages'] and common['stages'][stage]!=spec:raise InputError('Collection members use different decision protocols')
                common['stages'][stage]=spec
        members[rid]={'source_hash':digest(run),'extraction_hash':digest(result['raw_extraction']),
            'map_hash':digest(result['document'])}
        loaded.append((run,result))
    definition={'schema':VERSION,'kind':'extraction','directory':str(directory),'label':label.strip(),
        'members':members,'protocol':common}
    identifier='saved-'+digest(definition)[:24]
    # Validate every member before publishing any of them.
    with store.connect() as c:
        c.execute('INSERT OR IGNORE INTO semantic_observers VALUES (?,?)',(identifier,dumps(definition)))
    from .rollout_metrics import record_map
    for run,result in loaded:record_map(store,run,{**result,'observer':{'id':identifier,'label':label.strip()}})
    return {'observer':identifier,'members':list(members),'protocol':common,
        'urls':{rid:'/semantic-map?run='+rid+'&observer='+identifier for rid in members},
        'accuracy':'Not independently measured'}
