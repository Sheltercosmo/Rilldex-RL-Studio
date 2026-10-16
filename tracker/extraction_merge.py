"""Combine disjoint, audited local passes without rerunning their selections."""
from copy import deepcopy
from pathlib import Path

from .schema import InputError, digest
from .semantic_extraction import audit_result, windows, read, write, PARTICIPANT_SCOPE


def merge(run, inputs, directory, exclusions=()):
    directory=Path(directory);parts=[]
    for result,source_directory in inputs:
        audit_result(run,result,source_directory)
        if result['status']!='complete_local_extraction':raise InputError('Merge requires completed local selections')
        parts.append((result,Path(source_directory)))
    if not parts:raise InputError('No local passes supplied')
    shared=['schema','activity_standard','partition_policy']
    if any(any(p.get(k)!=parts[0][0].get(k) for k in shared) for p,_ in parts):
        raise InputError('Local extraction contracts differ; retain separate passes')
    scope=PARTICIPANT_SCOPE if any(p.get('participant_scope')==PARTICIPANT_SCOPE for p,_ in parts) else None
    eligible=windows(run,include_user=bool(scope));window_ids=[w['id'] for w in eligible]
    combined=deepcopy(parts[0][0]);combined.pop('scope',None)
    for key in ['activity_reading_contract','reading_context_policy']:
        values=[p[key] for p,_ in parts if p.get(key) is not None]
        if values and any(v!=values[0] for v in values):raise InputError('Activity reading contracts differ')
        if values:combined[key]=deepcopy(values[0])
    combined['windows']=[];combined['units']=[];seen=set()
    for result,source_directory in parts:
        for window in result['windows']:
            if window['id'] in seen:raise InputError('Local passes overlap; merge must not choose between annotations')
            seen.add(window['id']);combined['windows'].append(deepcopy(window))
        combined['units'].extend(deepcopy(result['units']))
    missing={w['id']:w for w in eligible if w['id'] not in seen}
    declared={}
    for exclusion in exclusions:
        wid=exclusion.get('window_id')
        if wid in declared or wid not in missing or exclusion.get('source')!=missing[wid] or not exclusion.get('reason') or not exclusion.get('basis'):
            raise InputError('Scope exclusion must identify an unselected source window and its reason/basis')
        declared[wid]=deepcopy(exclusion)
    if set(declared)!=set(missing):raise InputError('Every omitted eligible window needs an explicit scope exclusion')
    combined['windows'].sort(key=lambda w:window_ids.index(w['id']))
    event_order={e['id']:e['index'] for e in run['events']}
    combined['units'].sort(key=lambda u:(event_order[u['source']['event_id']],u['source']['start'],u['source']['end']))
    combined['whole_run']=not missing
    if scope:combined['participant_scope']=scope
    combined['source_exclusions']=list(declared.values())
    combined['augmentation']={'schema':'disjoint-local-merge/1','input_hashes':[digest(p) for p,_ in parts],
        'unchanged_input_units':sum(len(p['units']) for p,_ in parts),
        'rule':'Local units and raw selections are copied unchanged; dependent semantic passes require new dependency replay.'}
    # Decisions are immutable input artifacts. Copy only selections referenced
    # by the merged units/windows, never a dependent relation result.
    for result,source_directory in parts:
        keys={row[field] for rows in [result['windows'],result['units']] for row in rows
              for field in ('partition_request','activity_request','content_request') if row.get(field)}
        for key in keys:
            value=read(source_directory/'decisions'/f'{key}.json');target=directory/'decisions'/f'{key}.json'
            if target.exists() and read(target)!=value:raise InputError('Conflicting decision artifact')
            write(target,value)
    validation=audit_result(run,combined,directory)
    write(directory/'runs'/f'{run["id"]}.json',run)
    write(directory/'snapshots'/f'{digest(combined)}.json',combined)
    write(directory/'results'/f'{run["id"]}.json',combined)
    return combined,validation
