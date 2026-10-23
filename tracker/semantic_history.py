"""Build work identities and feedback links in a separate, audited observer."""
from pathlib import Path
import shutil
import time
from .schema import InputError,digest
from .semantic_extraction import read,write,load_extraction,Pipeline
from .semantic_workspace import exclusive
from . import action_targets,feedback_assessments,decision_cache

VERSION='semantic-history-rebuild/1'
IGNORED={'attempts','wire','executions','reuse','.workspace.lock','registration.json'}


def initialize(directory,source_directory,run_id,cache_directories=(),target_version=action_targets.SCOPE_VERSION,*,reference_rule=feedback_assessments.REFERENCE_RULE,linkage_version=None,retrieval_version=None,scope_version=None):
    root=Path(directory).resolve();source=Path(source_directory).resolve()
    if not run_id.isalnum():raise InputError('Invalid history run ID')
    if root==source or root.is_relative_to(source):raise InputError('Use a separate output directory outside the source workspace')
    if target_version not in {action_targets.VERSION,action_targets.SCOPED_VERSION,action_targets.CHARACTERIZED_VERSION,action_targets.SCOPE_VERSION,action_targets.PAIRWISE_VERSION,action_targets.PAGED_VERSION}:
        raise InputError('Unknown target correspondence version')
    if reference_rule not in {feedback_assessments.REFERENCE_RULE,feedback_assessments.DIRECT_SET_RULE}:
        raise InputError('Unknown feedback reference rule')
    if linkage_version not in {None,feedback_assessments.SOURCE_LINKAGE}:raise InputError('Unknown feedback linkage version')
    if scope_version not in {None,feedback_assessments.CONTRIBUTION_SCOPE}:raise InputError('Unknown feedback contribution scope')
    if scope_version and reference_rule!=feedback_assessments.DIRECT_SET_RULE:raise InputError('Contribution scope requires the direct response-set protocol')
    from .feedback_retrieval import VERSIONS
    if retrieval_version is not None and retrieval_version not in VERSIONS:raise InputError('Unknown feedback retrieval version')
    with exclusive(source):
        run=read(source/'runs'/f'{run_id}.json');base=load_extraction(run,source)
        if not base.get('available') or base['raw_extraction'].get('status')!='complete_local_extraction':
            raise InputError('History requires complete local extraction')
        config={'schema':VERSION,'run_id':run_id,'source_hash':digest(run),
                'base_extraction_hash':digest(base['raw_extraction']),
                'source_directory':str(source),'cache_directories':[str(Path(p).resolve()) for p in cache_directories],
                'target_version':target_version,'feedback_protocol':{
                    'dependency_scope':feedback_assessments.DEPENDENCY_SCOPE,
                    'evidence_layout':feedback_assessments.INLINE_EVIDENCE,'reference_rule':reference_rule}}
        if linkage_version is not None:config['feedback_protocol']['linkage_version']=linkage_version
        if retrieval_version is not None:config['feedback_protocol']['retrieval_version']=retrieval_version
        if scope_version is not None:config['feedback_protocol']['scope_version']=scope_version
        with exclusive(root):
            if (root/'history-rebuild.json').exists():
                if read(root/'history-rebuild.json')!=config:raise InputError('History configuration changed; use a new directory')
                load(root);return config
            if any(p.name!='.workspace.lock' for p in root.iterdir()):raise InputError('History output requires an empty directory')
            # Copy source artifacts, not previous call accounting. Regenerated
            # requests decide which saved decisions are applicable to this pass.
            for item in source.iterdir():
                if item.name in IGNORED or item.name.startswith('last-'):continue
                if item.is_dir():shutil.copytree(item,root/item.name)
                else:shutil.copyfile(item,root/item.name)
            write(root/'history-rebuild.json',config)
            load(root)
    return config


def load(directory):
    root=Path(directory);config=read(root/'history-rebuild.json')
    if config.get('schema')!=VERSION or not config.get('run_id','').isalnum():raise InputError('Unknown history rebuild contract')
    # execute() supports this exact feedback contract. Do not silently resume
    # a frozen workspace using newer defaults after a protocol upgrade.
    supported_feedback={'dependency_scope':feedback_assessments.DEPENDENCY_SCOPE,
                        'evidence_layout':feedback_assessments.INLINE_EVIDENCE,
                        'reference_rule':feedback_assessments.REFERENCE_RULE}
    protocol=config.get('feedback_protocol',{})
    supported_feedback['reference_rule']=protocol.get('reference_rule')
    if 'linkage_version' in protocol:supported_feedback['linkage_version']=feedback_assessments.SOURCE_LINKAGE
    if 'scope_version' in protocol:
        supported_feedback['scope_version']=feedback_assessments.CONTRIBUTION_SCOPE
        if protocol.get('reference_rule')!=feedback_assessments.DIRECT_SET_RULE:raise InputError('Contribution scope requires the direct response-set protocol')
    if 'retrieval_version' in protocol:
        from .feedback_retrieval import VERSIONS
        if protocol['retrieval_version'] not in VERSIONS:raise InputError('Unsupported frozen feedback protocol')
        supported_feedback['retrieval_version']=protocol['retrieval_version']
    if (protocol!=supported_feedback or protocol.get('reference_rule') not in
            {feedback_assessments.REFERENCE_RULE,feedback_assessments.DIRECT_SET_RULE}):
        raise InputError('Unsupported frozen feedback protocol; use its original implementation or a new history workspace')
    run=read(root/'runs'/f'{config["run_id"]}.json')
    result=read(root/'results'/f'{config["run_id"]}.json')
    if digest(run)!=config['source_hash'] or digest(result)!=config['base_extraction_hash']:
        raise InputError('Frozen history source or extraction changed')
    from .semantic_extraction import audit_result
    audit_result(run,result,root)
    return config,run,result


def execute(directory,transport,*,max_calls=0,max_input_bytes=1_000_000):
    from .semantic_budget import ExecutionBudget,BudgetReached,summary
    with exclusive(directory) as root:
        config,run,result=load(root);started=time.time_ns()
        budget=ExecutionBudget(root,started,{'jev_requests':max_calls,'candidate_requests':0,'input_bytes':max_input_bytes})
        def send(req):
            def call():
                response=transport(req);write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response});return response
            return budget.invoke('jev',req,call)
        engine=Pipeline(root,None,send,cache_directories=config['cache_directories'])
        receipt={'schema':VERSION,'status':'running','started_at_ns':started,'completed_stages':[]}
        try:
            targets,validation=action_targets.execute(run,result,engine,version=config['target_version'])
            receipt['completed_stages'].append({'name':'target_identity','validation':validation})
            assessments,validation=feedback_assessments.execute(run,result,engine,
                evidence_layout=config['feedback_protocol']['evidence_layout'],reference_rule=config['feedback_protocol']['reference_rule'],
                linkage_version=config['feedback_protocol'].get('linkage_version'),retrieval_version=config['feedback_protocol'].get('retrieval_version'),
                scope_version=config['feedback_protocol'].get('scope_version'))
            receipt['completed_stages'].append({'name':'feedback_assessment','validation':validation})
            receipt['status']='complete'
        except BudgetReached as error:receipt.update(status='budget_reached',budget_stop=error.reason)
        except (Exception,KeyboardInterrupt):receipt['status']='interrupted';raise
        finally:
            receipt.update(budget_used=budget.used,reused_this_execution=len(engine.reused_decisions))
            write(root/'last-history.json',receipt);write(root/'executions'/f'{started}.json',receipt)
        return {**receipt,'reuse':decision_cache.audit(root),'provider_usage':summary(root)}


def audit(directory):
    with exclusive(directory) as root:
        config,run,result=load(root)
        targets=read(action_targets.path_for(root,result,config['target_version']))
        assessments=read(feedback_assessments.path_for(root,result,**config['feedback_protocol']))
        view=load_extraction(run,root,action_target_version=config['target_version'])
        report={'schema':VERSION,'run_id':run['id'],'extraction_hash':digest(result),
                'targets':action_targets.audit(run,result,targets,root),
                'assessments':feedback_assessments.audit(run,result,assessments,root),
                'reuse':decision_cache.audit(root),'work_history':view['document']['work_history']['counts'],
                'map_hash':digest(view['document']),'semantic_accuracy':'Not independently measured'}
        write(root/'history-audit.json',report);return report


def validate_dependencies(directory,run,result):
    """Publication gate; no recursive map loading and no inference."""
    root=Path(directory);config,frozen,extraction=load(root)
    if frozen!=run or extraction!=result:raise InputError('History source differs from displayed map')
    target_path=action_targets.path_for(root,result,config['target_version'])
    feedback_path=feedback_assessments.path_for(root,result,**config['feedback_protocol'])
    if not target_path.exists() or not feedback_path.exists():raise InputError('History stages are incomplete; resume before registering this observer')
    return {'schema':VERSION,'target_version':config['target_version'],
            'feedback_protocol':config['feedback_protocol'],
            'targets':action_targets.audit(run,result,read(target_path),root),
            'assessments':feedback_assessments.audit(run,result,read(feedback_path),root),
            'reuse':decision_cache.audit(root)}
