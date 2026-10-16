"""Reclassify a complete source while freezing boundaries and prior evidence.

No derived relationships are inherited. Unchanged categories reuse their exact
selected content decision; changed categories require a fresh candidate bundle.
"""
from copy import deepcopy
from pathlib import Path
import time

from .schema import InputError,digest
from .semantic_extraction import (FileCandidates,Pipeline,activity_choices,
    audit_result,content_selection_request,read,request,write)
from .semantic_workspace import exclusive

VERSION='semantic-revision/1'
QUESTION=('Choose exactly one activity for this established contribution. Supporting rationale, purpose or politeness are content. '
          'Classify what this unit itself does; requesting another actor to check something is Coordinate, not this agent performing Verify.')
IDENTITY=('id','source','actor','trajectory_id','kind','partition_request','boundary_origin')
CONTENT=('content','content_request','content_choice','candidate_request','candidate_producer','plan_structure')


def initialize(directory,parent_directory,run_id,routing):
    activity_choices(routing)
    if not run_id.isalnum():raise InputError('Invalid run ID')
    parent_directory=Path(parent_directory)
    parent=read(parent_directory/'results'/f'{run_id}.json')
    run=read(parent_directory/'runs'/f'{run_id}.json')
    if parent.get('status')!='complete_local_extraction' or parent.get('whole_run') is not True:
        raise InputError('Revision requires a complete whole-run parent')
    audit_result(run,parent,parent_directory)
    if parent.get('content_revision') or parent.get('content_repair_run'):
        raise InputError('Revise activities from the original extraction, then refine targets; category-conditioned target refinements must be rebuilt')
    config={'schema':VERSION,'run_id':run_id,'source_hash':digest(run),
            'parent_hash':digest(parent),'activity_routing':routing,
            'boundary_policy':'Frozen parent boundaries; not a new segmentation evaluation',
            'reading_policy':'Direct classification from original visible source context; prior proposed interpretations are not supplied',
            'content_policy':'Reuse exact selected content only when the category is unchanged; otherwise request new candidates',
            'relation_policy':'Rebuild dependent observations; no parent relations are copied'}
    keys={w['partition_request'] for w in parent['windows'] if w.get('partition_request')}
    keys.update(u[k] for u in parent['units'] for k in ('partition_request','activity_request','content_request') if u.get(k))
    with exclusive(directory) as root:
        if (root/'revision.json').exists():
            if read(root/'revision.json')!=config:raise InputError('Revision configuration changed; use a new directory')
            load(root);return config
        if any(p.name!='.workspace.lock' for p in root.iterdir()):raise InputError('A revision requires an empty directory')
        write(root/'runs'/f'{run_id}.json',run);write(root/'parent.json',parent)
        for key in keys:write(root/'decisions'/f'{key}.json',read(parent_directory/'decisions'/f'{key}.json'))
        write(root/'revision.json',config)
    return config


def load(directory):
    root=Path(directory);config=read(root/'revision.json')
    if config.get('schema')!=VERSION or not config.get('run_id','').isalnum():raise InputError('Unknown revision contract')
    activity_choices(config['activity_routing'])
    run=read(root/'runs'/f'{config["run_id"]}.json');parent=read(root/'parent.json')
    if digest(run)!=config['source_hash'] or digest(parent)!=config['parent_hash']:
        raise InputError('Frozen revision source or parent changed')
    audit_result(run,parent,root)
    return config,run,parent


def activity_request(root,config,run,unit):
    old=read(Path(root)/'decisions'/f'{unit["activity_request"]}.json')['request']
    return request(run,unit['source'],'activity',QUESTION,activity_choices(config['activity_routing']),
        context_policy=old['state'].get('context_policy'),activity_routing=config['activity_routing'],
        expression_form='recorded action dispatch' if unit['kind']=='action' else 'user-authored expression' if unit['actor']=='user' else 'model-authored expression')


def prepare(directory):
    with exclusive(directory) as root:
        config,run,parent=load(root)
        for unit in parent['units']:
            req=activity_request(root,config,run,unit)
            write(root/'requests'/f'{digest(req)}.json',req)
        return {'units':len(parent['units']),'run_id':run['id'],'activity_routing':config['activity_routing'],
                'status':'prepared','provider_calls':0}


def execute(directory,transport,*,max_calls=50,max_input_bytes=1_000_000,progress=None):
    from .semantic_budget import ExecutionBudget,BudgetReached,summary
    with exclusive(directory) as root:
        config,run,parent=load(root);started=time.time_ns()
        budget=ExecutionBudget(root,started,{'jev_requests':max_calls,'candidate_requests':0,'input_bytes':max_input_bytes})
        def send(req):
            def call():
                response=transport(req)
                write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                return response
            return budget.invoke('jev',req,call)
        engine=Pipeline(root,None,send)
        result={k:deepcopy(v) for k,v in parent.items() if k not in {'units','note','activity_reading_contract','reading_context_policy'}}
        result.update(units=[],status='interrupted',activity_routing=config['activity_routing'],
                      revision={'schema':VERSION,'parent_hash':config['parent_hash'],'boundary_policy':config['boundary_policy'],
                                'reading_policy':config['reading_policy'],'content_policy':config['content_policy'],
                                'relation_policy':config['relation_policy']})
        receipt={'schema':VERSION,'started_at_ns':started,'status':'running','changes':[],'reused_content':0,'pending_content':[]}
        def save():
            write(root/'checkpoints'/f'{run["id"]}.json',result)
            write(root/'last-revision.json',{**receipt,'budget_used':budget.used})
            if progress:progress(receipt)
        try:
            for old in parent['units']:
                req=activity_request(root,config,run,old);choice,key=engine.choose(req)
                unit={k:deepcopy(old[k]) for k in IDENTITY if k in old}
                unit.update(activity=choice,activity_request=key,content={},status='needs_candidates')
                result['units'].append(unit)
                if choice==old['activity']:
                    unit.update({k:deepcopy(old[k]) for k in CONTENT if k in old});unit['status']='selected'
                    receipt['reused_content']+=1
                else:
                    receipt['changes'].append({'unit_id':old['id'],'event_id':old['source']['event_id'],'from':old['activity'],'to':choice})
                    if choice in {'other','unresolved'}:unit['status']='needs_activity_review';save();continue
                    provider=FileCandidates(root/'candidates',context_policy=req['state'].get('context_policy'))
                    proposed=provider.content(run,unit['source'],choice);unit['candidate_request']=proposed['request_hash']
                    if proposed['status']!='ready':
                        receipt['pending_content'].append({'unit_id':unit['id'],'activity':choice,'request_hash':proposed['request_hash']})
                        save();continue
                    content_req=content_selection_request(run,unit['source'],choice,proposed,provider.context_policy)
                    selected,content_key=engine.choose(content_req)
                    unit.update(content_choice=selected,content_request=content_key,candidate_producer=proposed['producer'])
                    if selected in {'no_suitable_candidate','unresolved'}:unit['status']='needs_content_repair'
                    else:
                        candidate=proposed['candidates'][int(selected[1:])];unit.update(content=deepcopy(candidate['fields']),status='selected')
                        if 'plan_structure' in candidate:unit['plan_structure']=deepcopy(candidate['plan_structure'])
                save()
            result['status']='complete_local_extraction' if all(u['status']=='selected' for u in result['units']) else 'needs_work'
            result['note']='Full activity revision on inherited source boundaries. Unchanged content selections are reused; relations require a separate audited pass. No independent accuracy claim.'
            receipt['validation']=audit_result(run,result,root);receipt['status']=result['status']
            if result['status']=='complete_local_extraction':
                write(root/'results'/f'{run["id"]}.json',result)
                write(root/'snapshots'/f'{digest(result)}.json',result)
        except BudgetReached as error:
            receipt.update(status='budget_reached',budget_stop=error.reason)
        except (Exception,KeyboardInterrupt):
            receipt['status']='interrupted';raise
        finally:
            save();write(root/'executions'/f'{started}.json',{**receipt,'budget_used':budget.used})
        return {**receipt,'budget_used':budget.used,'provider_usage':summary(root)}


def validate_result(root,config,run,parent,result):
    expected={'schema':VERSION,'parent_hash':config['parent_hash'],**{k:config[k] for k in
        ('boundary_policy','reading_policy','content_policy','relation_policy')}}
    if result.get('revision')!=expected or result.get('activity_routing')!=config['activity_routing']:
        raise InputError('Revision result configuration differs')
    if result['windows']!=parent['windows'] or len(result['units'])!=len(parent['units']):raise InputError('Frozen boundaries changed')
    changes=[]
    for before,after in zip(parent['units'],result['units']):
        if any(before.get(k)!=after.get(k) for k in IDENTITY):raise InputError('Frozen unit identity changed')
        if digest(activity_request(root,config,run,before))!=after['activity_request']:
            raise InputError('Revision activity context differs from parent')
        if before['activity']==after['activity']:
            if any(before.get(k)!=after.get(k) for k in CONTENT):raise InputError('Unchanged activity lost its exact content decision')
        else:changes.append({'unit_id':after['id'],'from':before['activity'],'to':after['activity']})
    return {'schema':VERSION,'units':len(result['units']),'changes':changes,
            'parent_hash':config['parent_hash'],'result_hash':digest(result),'dependent_relationships_inherited':False}


def audit(directory):
    with exclusive(directory) as root:
        config,run,parent=load(root);result=read(root/'results'/f'{run["id"]}.json')
        validation=audit_result(run,result,root)
        report={**validate_result(root,config,run,parent,result),'validation':validation}
        write(root/'revision-audit.json',report);return report


def rebuild_plan_links(directory,transport,*,max_calls=50,max_input_bytes=1_000_000):
    """Rebuild from the complete revision; cache only exact new requests."""
    from .semantic_budget import ExecutionBudget,BudgetReached,summary
    from . import plan_relations
    audit(directory)
    with exclusive(directory) as root:
        config,run,_=load(root);result=read(root/'results'/f'{run["id"]}.json')
        started=time.time_ns()
        budget=ExecutionBudget(root,started,{'jev_requests':max_calls,'candidate_requests':0,'input_bytes':max_input_bytes})
        def send(req):
            def call():
                response=transport(req)
                write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                return response
            return budget.invoke('jev',req,call)
        receipt={'schema':VERSION,'stage':'plan_links','started_at_ns':started,'status':'running'}
        try:
            links,validation=plan_relations.execute(run,result,Pipeline(root,None,send))
            receipt.update(status='complete',relations=len(links['relations']),validation=validation)
        except BudgetReached as error:receipt.update(status='budget_reached',budget_stop=error.reason)
        except (Exception,KeyboardInterrupt):receipt['status']='interrupted';raise
        finally:
            receipt['budget_used']=budget.used
            write(root/'last-plan-links.json',receipt);write(root/'executions'/f'{started}.json',receipt)
        return {**receipt,'provider_usage':summary(root)}
