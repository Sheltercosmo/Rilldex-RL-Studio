"""Fresh content candidates for fixed, previously selected semantic units.

Source, segmentation and activities are frozen. The original bundle competes
with fresh proposals; proposal generation and raw-argmax selection are separate.
"""
from copy import deepcopy
from pathlib import Path

from .schema import InputError,digest
from .semantic_extraction import (read,write,generation_request,content_selection_request,
                                  validate_proposals,audit_result,Pipeline)
from .work_target_refinement import RULE as TARGET_RULE

VERSION='semantic-content-repair/1'
RULE=('Describe what this established contribution does, not every activity that its '
      'text mentions. Supporting rationale, an announced next step and purpose may remain '
      'in the same unit, but do not replace its main contributed work with that future step. '
      'For Reason, preserve the actual question and inference being developed; an intention '
      'to retrieve evidence later is not the reasoning target. For Orient, describe the '
      'stated local situation and needed work without asserting execution. A Plan retains '
      'the complete organized work and its stages. Do not change the established activity, '
      'split the unit, infer hidden mental states, correct source factual errors or add '
      'cross-unit relations. Each field must be supported by its cited source, not merely '
      'by a plausible reading of the overall task.')


def proposal_request(run,unit,context_policy):
    req=generation_request(run,unit['source'],unit['activity'],context_policy)
    req['content_repair_protocol']=VERSION
    if 'work_target' in req['field_contract']:req['field_contract']['work_target']=TARGET_RULE
    req['contribution_content_rule']=RULE
    req['instructions']+=' '+RULE+' Propose at most two coherent bundles; one is enough when there is no material ambiguity.'
    return req


def selection_request(run,unit,response,context_policy):
    generated=proposal_request(run,unit,context_policy)
    fresh=validate_proposals(run,generated,response)
    if len(fresh)>2:raise InputError('At most two fresh repair candidates are supported')
    old={'fields':deepcopy(unit['content'])}
    if 'plan_structure' in unit:old['plan_structure']=deepcopy(unit['plan_structure'])
    candidates=[old];origins=['original_selected_bundle']
    for index,candidate in enumerate(fresh):
        if candidate not in candidates:candidates.append(candidate);origins.append(f'fresh_candidate_{index}')
    proposed={'producer':response['producer'],'candidates':candidates}
    req=content_selection_request(run,unit['source'],unit['activity'],proposed,context_policy)
    req['state'].update(field_contract=generated['field_contract'],contribution_content_rule=RULE,
        content_repair={'schema':VERSION,'parent_content_request':unit['content_request'],
                        'proposal_request':digest(generated),'proposal_response_hash':digest(response),
                        'candidate_origins':origins})
    req['questions']['choice']['instructions']+=(
        ' Apply contribution_content_rule to every field. The original bundle is a candidate, '
        'not a reference label. Fresh candidates are not presumed better. Keep supporting '
        'future work distinct from the work this unit contributes. Reject all candidates '
        'if none is faithful, or select unresolved when the source cannot decide.')
    return req


def initialize(directory,parent_directory,run_id,unit_ids):
    from .semantic_workspace import exclusive
    import shutil
    if not run_id.isalnum():raise InputError('Invalid run ID')
    if not isinstance(unit_ids,list) or not unit_ids or len(unit_ids)!=len(set(unit_ids)):raise InputError('Choose distinct unit IDs for content repair')
    parent_directory=Path(parent_directory);run=read(parent_directory/'runs'/f'{run_id}.json')
    parent=read(parent_directory/'results'/f'{run_id}.json');audit_result(run,parent,parent_directory)
    if parent['status']!='complete_local_extraction':raise InputError('A complete selected parent is required')
    units={u['id']:u for u in parent['units']}
    if any(uid not in units for uid in unit_ids):raise InputError('Repair unit is outside the parent')
    if any(u.get('content_repair') for u in parent['units']):raise InputError('Use the preserved parent for another repair experiment')
    ordered=[u['id'] for u in parent['units'] if u['id'] in unit_ids]
    config={'schema':VERSION,'run_id':run_id,'source_hash':digest(run),'parent_hash':digest(parent),
            'unit_ids':ordered,'scope':'Frozen units and activities; selected content bundles may change. Rebuild dependent semantic relations.'}
    with exclusive(directory) as root:
        path=root/'content-repair.json'
        if path.exists():
            if read(path)!=config:raise InputError('Repair configuration changed; use another directory')
            load(root);return config
        if any(p.name!='.workspace.lock' for p in root.iterdir()):raise InputError('Repair needs an empty directory')
        write(root/'runs'/f'{run_id}.json',run);write(root/'parent.json',parent)
        for folder in ('decisions','candidates'):
            if (parent_directory/folder).exists():shutil.copytree(parent_directory/folder,root/folder)
        write(path,config)
    return config


def load(directory):
    root=Path(directory);config=read(root/'content-repair.json')
    if config.get('schema')!=VERSION or not config.get('run_id','').isalnum():raise InputError('Unknown content repair')
    run=read(root/'runs'/f'{config["run_id"]}.json');parent=read(root/'parent.json')
    if digest(run)!=config['source_hash'] or digest(parent)!=config['parent_hash']:raise InputError('Frozen repair source/parent changed')
    audit_result(run,parent,root)
    return config,run,parent


def prepare(directory):
    from .semantic_workspace import exclusive
    with exclusive(directory) as root:
        config,run,parent=load(root);rows=[]
        for unit in parent['units']:
            if unit['id'] not in config['unit_ids']:continue
            saved=read(root/'decisions'/f'{unit["content_request"]}.json')['request']
            req=proposal_request(run,unit,saved['state'].get('context_policy'));key=digest(req)
            write(root/'repair-candidates/requests'/f'{key}.json',req)
            rows.append({'unit_id':unit['id'],'request_hash':key,
                         'request_path':str(root/'repair-candidates/requests'/f'{key}.json')})
        return {'schema':VERSION,'run_id':run['id'],'requests':rows,'provider_calls':0}


def execute(directory,transport,*,max_calls=0,max_input_bytes=1_000_000):
    from .semantic_workspace import exclusive
    from .semantic_budget import ExecutionBudget,BudgetReached
    import time
    prepare(directory)
    with exclusive(directory) as root:
        config,run,parent=load(root);result=deepcopy(parent);result['content_repair_run']=config
        result['status']='interrupted';old={u['id']:u for u in parent['units']}
        for unit in result['units']:
            if unit['id'] not in config['unit_ids']:continue
            for field in ('content_request','content_choice','candidate_request','candidate_producer','plan_structure','target_refinement'):
                unit.pop(field,None)
            unit.update(content={},status='needs_candidates')
        budget=ExecutionBudget(root,time.time_ns(),{'jev_requests':max_calls,'candidate_requests':0,'input_bytes':max_input_bytes})
        def send(req):
            def call():
                response=transport(req);write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response});return response
            return budget.invoke('jev',req,call)
        engine=Pipeline(root,None,send);receipt={'schema':VERSION,'selected':[],'pending':[]}
        def save():write(root/'checkpoints'/f'{run["id"]}.json',result)
        save()
        try:
            for unit in result['units']:
                if unit['id'] not in config['unit_ids']:continue
                prior=old[unit['id']];policy=read(root/'decisions'/f'{prior["content_request"]}.json')['request']['state'].get('context_policy')
                generated=proposal_request(run,prior,policy);key=digest(generated)
                path=root/'repair-candidates/responses'/f'{key}.json'
                if not path.exists():receipt['pending'].append({'unit_id':unit['id'],'request_hash':key});continue
                proposal=read(path);req=selection_request(run,prior,proposal,policy)
                choice,selected_key=engine.choose(req)
                unit.update(content_request=selected_key,content_choice=choice,candidate_request=key,
                            candidate_producer=proposal['producer'],content_repair=deepcopy(req['state']['content_repair']))
                if choice in {'no_suitable_candidate','unresolved'}:unit['status']='needs_content_repair'
                else:
                    candidate=req['state']['content_candidates'][int(choice[1:])]
                    unit.update(content=deepcopy(candidate['fields']),status='selected')
                    if 'plan_structure' in candidate:unit['plan_structure']=deepcopy(candidate['plan_structure'])
                receipt['selected'].append({'unit_id':unit['id'],'choice':choice,'request_hash':selected_key});save()
            result['status']='complete_local_extraction' if all(u['status']=='selected' for u in result['units']) else 'needs_work'
            receipt['validation']=audit_result(run,result,root)
            if result['status']=='complete_local_extraction':write(root/'results'/f'{run["id"]}.json',result)
        except BudgetReached as error:receipt['budget_stop']=error.reason
        finally:
            save();receipt.update(status=result['status'],budget_used=budget.used);write(root/'last-content-repair.json',receipt)
        return receipt


def audit(directory):
    config,run,parent=load(directory);root=Path(directory);path=root/'results'/f'{run["id"]}.json'
    if not path.exists():path=root/'checkpoints'/f'{run["id"]}.json'
    result=read(path)
    if result.get('content_repair_run')!=config:raise InputError('Repair declaration changed')
    if [u['id'] for u in result['units']]!=[u['id'] for u in parent['units']]:raise InputError('Repair unit coverage changed')
    for unit,old in zip(result['units'],parent['units']):
        if unit['id'] not in config['unit_ids']:
            if unit!=old:raise InputError('Unrequested unit changed during repair')
            continue
        for field in ('source','activity','activity_request','actor','trajectory_id','kind','partition_request','boundary_origin'):
            if unit.get(field)!=old.get(field):raise InputError('Repair changed a base unit')
    return {'schema':VERSION,'status':result['status'],'validation':audit_result(run,result,root),'provider_calls':0}


def audit_provenance(run,result,directory):
    """Used by every map load, not only by the repair CLI."""
    config=result['content_repair_run'];root=Path(directory)
    if config.get('schema')!=VERSION or config.get('source_hash')!=digest(run):raise InputError('Unknown content repair/source')
    parent=read(root/'parent.json')
    if digest(parent)!=config.get('parent_hash') or parent.get('content_repair_run'):raise InputError('Content repair parent changed')
    audit_result(run,parent,root)
    selected=config.get('unit_ids',[])
    ids=[u['id'] for u in parent['units']]
    if not selected or len(selected)!=len(set(selected)) or any(uid not in ids for uid in selected):raise InputError('Invalid repair unit scope')
    if [u['id'] for u in result['units']]!=ids:raise InputError('Repair unit coverage changed')
    for unit,old in zip(result['units'],parent['units']):
        if unit['id'] not in selected:
            if unit!=old:raise InputError('Unrequested unit changed during repair')
        else:
            for field in ('source','activity','activity_request','actor','trajectory_id','kind','partition_request','boundary_origin'):
                if unit.get(field)!=old.get(field):raise InputError('Repair changed a base unit')
            if unit['status']=='selected' and not unit.get('content_repair'):raise InputError('Selected repair lacks provenance')


def audit_selection(run,unit,req,directory):
    root=Path(directory);declared=unit.get('content_repair')
    if req['state'].get('content_repair')!=declared or not declared or declared.get('schema')!=VERSION:
        raise InputError('Content repair selection declaration differs')
    parent=read(root/'parent.json');prior=next((u for u in parent['units'] if u['id']==unit['id']),None)
    if prior is None or declared.get('parent_content_request')!=prior['content_request']:raise InputError('Content repair parent decision differs')
    old=read(root/'decisions'/f'{prior["content_request"]}.json')['request'];policy=old['state'].get('context_policy')
    generated=proposal_request(run,prior,policy);key=digest(generated)
    if unit.get('candidate_request')!=key or declared.get('proposal_request')!=key:raise InputError('Content repair proposal binding differs')
    proposal=read(root/'repair-candidates/responses'/f'{key}.json')
    if req!=selection_request(run,prior,proposal,policy):raise InputError('Content repair request differs from frozen candidates')
