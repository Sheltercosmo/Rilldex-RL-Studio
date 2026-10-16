"""Refine immediate work descriptions from already selected semantic contents.

Candidate construction is deterministic; it reuses readable, source-cited fields
instead of generating text. This cannot recover information absent from those
fields. Jev may reject all candidates. Boundaries and activities stay frozen.
"""
from copy import deepcopy
from pathlib import Path

from .schema import InputError,digest
from .semantic_extraction import read,write,content_selection_request,audit_result,Pipeline

VERSION='work-target-refinement/1'
PRODUCER='selected-content-field-projection/1'
RULE=('Describe the immediate work or question contributed by this established unit, '
      'including its specific subject and any task instance actually supported. '
      'Choose at the unit\'s own scope: retrieving one fact is not answering the broader '
      'question it serves; changing an intermediate artifact is not completing the whole task. '
      'Keep an organized Plan\'s complete stated work scope rather than reducing it to its first step. '
      'Prefer an operation with its object or a specific question over an isolated entity or tool name. '
      'The operation, its subject, its purpose and its means are different roles. Do not replace '
      'immediate work with a broader purpose or a method alone. A description may retain how the '
      'work is done without making every method or parameter part of the goal\'s identity. '
      'Preserve intended/requested versus performed/reported work and all material conditions. '
      'Do not invent a task instance or participant from topical similarity. Resolve a reference '
      'only when visible source establishes it. A general or underspecified description may '
      'faithfully remain general; it does not establish identity with another unit. '
      'No text is automatically correct because it was selected previously. Reject all bundles '
      'when none provides a faithful useful immediate work description. Do not infer relationships.')
FIELDS={'orient':('needed_work','focus'),'knowledge':('subject',),'plan':('target',),
        'hypothesize':('focus',),'reason':('focus',),'decide':('choice',),
        'inspect':('operation','target'),'construct':('change','target'),
        'verify':('check','target'),'coordinate':('request','target'),
        'report':('target',),'decline':('withheld_work',),'social':()}


def proposals(unit):
    """Keep original and at most two category-conditioned, unchanged field values."""
    if unit['activity'] not in FIELDS:raise InputError('Unresolved activity cannot refine a target')
    if unit.get('target_refinement'):raise InputError('Refine from an original content selection, not another refinement')
    original={'fields':deepcopy(unit['content'])}
    if 'plan_structure' in unit:original['plan_structure']=deepcopy(unit['plan_structure'])
    if 'work_target' not in original['fields']:return [],[]
    candidates=[original];origins=['original_work_target']
    for field in FIELDS[unit['activity']]:
        value=unit['content'].get(field,{})
        if value.get('status')!='expressed':continue
        if any(c['fields']['work_target']==value for c in candidates):continue
        candidate=deepcopy(original);candidate['fields']['work_target']=deepcopy(value)
        candidates.append(candidate);origins.append(field)
    return candidates,origins


def request(run,unit,context_policy):
    candidates,origins=proposals(unit)
    if not candidates:raise InputError('This unit has no work-target field')
    proposed={'producer':PRODUCER,'candidates':candidates}
    req=content_selection_request(run,unit['source'],unit['activity'],proposed,context_policy)
    req['state']['field_contract']['work_target']=RULE
    req['state']['target_refinement']={'schema':VERSION,
        'parent_content_request':unit['content_request'],'candidate_origins':origins,
        'scope':'Only work_target may change. Other field values, boundaries, activity and Plan structure are inherited. No new generative model or source-span splitter is used.'}
    req['questions']['choice']['instructions']=(
        'Choose the most faithful bundle under the work_target rule and all other field contracts. '
        'Candidates reuse previously selected fields; their origin is not proof of adequacy. '
        'Choose no_suitable_candidate when all need repair, including inherited fields; '
        'choose unresolved when the visible source cannot establish the meaning. '
        'This decision neither selects a relationship nor validates task success.')
    return req


def initialize(directory,parent_directory,run_id):
    from .semantic_workspace import exclusive
    if not run_id.isalnum():raise InputError('Invalid run ID')
    parent_directory=Path(parent_directory)
    run=read(parent_directory/'runs'/f'{run_id}.json')
    parent=read(parent_directory/'results'/f'{run_id}.json')
    audit_result(run,parent,parent_directory)
    if parent['status']!='complete_local_extraction':raise InputError('Complete local contents required')
    if any(u.get('target_refinement') for u in parent['units']):raise InputError('Parent already refines targets')
    config={'schema':VERSION,'run_id':run_id,'source_hash':digest(run),'parent_hash':digest(parent),
            'relation_policy':'Rebuild all dependent semantic relations; no prior relation files are copied.',
            'candidate_policy':PRODUCER}
    with exclusive(directory) as root:
        path=root/'target-refinement.json'
        if path.exists():
            if read(path)!=config:raise InputError('Refinement configuration changed; use another directory')
            load(root);return config
        if any(p.name!='.workspace.lock' for p in root.iterdir()):raise InputError('Refinement requires an empty directory')
        write(root/'runs'/f'{run_id}.json',run);write(root/'parent.json',parent)
        # Parent audit can reference boundary-reading proposals as well as selections.
        import shutil
        for folder in ('decisions','candidates'):
            if (parent_directory/folder).exists():shutil.copytree(parent_directory/folder,root/folder)
        write(path,config)
    return config


def load(directory):
    root=Path(directory);config=read(root/'target-refinement.json')
    if config.get('schema')!=VERSION or not config.get('run_id','').isalnum():raise InputError('Unknown target refinement')
    run=read(root/'runs'/f'{config["run_id"]}.json');parent=read(root/'parent.json')
    if digest(run)!=config['source_hash'] or digest(parent)!=config['parent_hash']:raise InputError('Frozen target source/parent changed')
    audit_result(run,parent,root)
    return config,run,parent


def requests(directory):
    config,run,parent=load(directory);root=Path(directory);rows=[]
    for unit in parent['units']:
        if 'work_target' not in unit['content']:continue
        previous=read(root/'decisions'/f'{unit["content_request"]}.json')['request']
        req=request(run,unit,previous['state'].get('context_policy'))
        rows.append((unit,req));write(root/'requests'/f'{digest(req)}.json',req)
    return config,run,parent,rows


def prepare(directory):
    from .semantic_workspace import exclusive
    with exclusive(directory):
        config,run,parent,rows=requests(directory)
        return {'schema':VERSION,'run_id':run['id'],'requests':len(rows),
                'unchanged_units':len(parent['units'])-len(rows),'provider_calls':0}


def execute(directory,transport,*,max_calls=50,max_input_bytes=1_000_000):
    from .semantic_budget import ExecutionBudget,BudgetReached
    from .semantic_workspace import exclusive
    import time
    with exclusive(directory) as root:
        config,run,parent,rows=requests(root)
        budget=ExecutionBudget(root,time.time_ns(),{'jev_requests':max_calls,'candidate_requests':0,'input_bytes':max_input_bytes})
        def send(req):
            def call():
                response=transport(req)
                write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                return response
            return budget.invoke('jev',req,call)
        engine=Pipeline(root,None,send);result=deepcopy(parent)
        result['content_revision']=config
        result['status']='interrupted';pending={u['id']:req for u,req in rows}
        for unit in result['units']:
            if unit['id'] in pending:
                # Never expose stale contents as the new protocol's selected output.
                for k in ('content_request','content_choice','candidate_request','candidate_producer','plan_structure'):
                    unit.pop(k,None)
                unit.update(status='needs_content_selection',content={})
        def save():write(root/'checkpoints'/f'{run["id"]}.json',result)
        save();receipt={'schema':VERSION,'run_id':run['id'],'changes':[]}
        try:
            for unit in result['units']:
                req=pending.get(unit['id'])
                if req is None:continue
                choice,key=engine.choose(req)
                unit.update(content_request=key,content_choice=choice,candidate_producer=PRODUCER,
                            target_refinement=deepcopy(req['state']['target_refinement']))
                if choice in {'no_suitable_candidate','unresolved'}:unit['status']='needs_content_repair'
                else:
                    selected=req['state']['content_candidates'][int(choice[1:])]
                    unit.update(content=deepcopy(selected['fields']),status='selected')
                    if 'plan_structure' in selected:unit['plan_structure']=deepcopy(selected['plan_structure'])
                receipt['changes'].append({'unit_id':unit['id'],'choice':choice,
                    'origin':req['state']['target_refinement']['candidate_origins'][int(choice[1:])] if choice.startswith('c') else None})
                save()
            result['status']='complete_local_extraction' if all(u['status']=='selected' for u in result['units']) else 'needs_work'
            receipt['validation']=audit_result(run,result,root)
            if result['status']=='complete_local_extraction':write(root/'results'/f'{run["id"]}.json',result)
        except BudgetReached as exc:
            receipt['budget_stop']=exc.reason
        finally:
            save();receipt.update(status=result['status'],budget_used=budget.used)
            write(root/'last-target-refinement.json',receipt)
        return receipt


def audit(directory):
    config,run,parent=load(directory);root=Path(directory)
    path=root/'results'/f'{run["id"]}.json'
    if not path.exists():path=root/'checkpoints'/f'{run["id"]}.json'
    result=read(path)
    if result.get('content_revision')!=config:raise InputError('Content revision provenance differs')
    old={u['id']:u for u in parent['units']}
    if [u['id'] for u in result['units']]!=list(old):raise InputError('Content refinement changed unit coverage')
    for unit in result['units']:
        prior=old[unit['id']]
        for field in ('source','actor','trajectory_id','kind','activity','activity_request','partition_request','boundary_origin'):
            if unit.get(field)!=prior.get(field):raise InputError('Content refinement changed base unit')
        if unit.get('target_refinement',{}).get('parent_content_request',prior['content_request'])!=prior['content_request']:
            raise InputError('Refinement parent decision differs')
    return {'schema':VERSION,'run_id':run['id'],'status':result['status'],
            'validation':audit_result(run,result,root),'provider_calls':0}
