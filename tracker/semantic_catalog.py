"""Expose saved, complete observer passes without replacing older predictions."""
from pathlib import Path

from .schema import InputError,digest,dumps
from .semantic_extraction import load_extraction,read
from .semantic_map import load_reference,REFERENCE_DIR

ROOT=Path(__file__).resolve().parent.parent
PROFILES={
    'airline-work-context':{'kind':'extraction','directory':ROOT/'research/work-context-2026-10-08/airline',
        'label':'Work scopes · development','action_target_version':'action-target-correspondence/3',
        'method_directory':ROOT/'research/method-comparison-dispatch-2026-10-08/airline'},
    'retail-work-context':{'kind':'extraction','directory':ROOT/'research/work-context-2026-10-08/retail',
        'label':'Work scopes · development','action_target_version':'action-target-correspondence/4',
        'method_directory':ROOT/'research/method-comparison-dispatch-2026-10-08/retail'},
    'software-work-context':{'kind':'extraction','directory':ROOT/'research/work-context-2026-10-08/software',
        'label':'Work scopes · development','action_target_version':'action-target-correspondence/4',
        'method_directory':ROOT/'research/method-comparison-dispatch-2026-10-08/software'},
    'reference':{'kind':'reference','directory':REFERENCE_DIR,'label':'Authored reference'},
    'local':{'kind':'extraction','directory':ROOT/'research/semantic-extraction-2026-10-07','label':'Local extraction'},
    'governing-context':{'kind':'extraction','directory':ROOT/'research/governing-context-2026-10-07','label':'Retained instructions'},
    'partition-revision':{'kind':'extraction','directory':ROOT/'research/partition-revision-2026-10-07','label':'Contribution boundaries v3'},
    'scoped-targets':{'kind':'extraction','directory':ROOT/'research/scoped-targets-2026-10-07','label':'Task-instance relations',
        'action_target_version':'action-target-correspondence/3'},
    'work-paths':{'kind':'extraction','directory':ROOT/'research/work-paths-2026-10-07','label':'Connected work paths',
        'action_target_version':'action-target-correspondence/4'},
    'contribution-readings':{'kind':'extraction','directory':ROOT/'research/contribution-readings-2026-10-07',
        'label':'Contribution readings · development','action_target_version':'action-target-correspondence/4'},
    'participant-contributions':{'kind':'extraction','directory':ROOT/'research/participant-contributions-2026-10-07',
        'label':'User scope and agent work · development','action_target_version':'action-target-correspondence/4'},
    'condition-records':{'kind':'extraction','directory':ROOT/'research/condition-records-2026-10-07',
        'label':'Retained conditions · development','action_target_version':'action-target-correspondence/4'},
    'check-evidence':{'kind':'extraction','directory':ROOT/'research/check-evidence-isolated-2026-10-07',
        'label':'Requested-check evidence · development','action_target_version':'action-target-correspondence/4'},
    'software-checks':{'kind':'extraction','directory':ROOT/'research/software-check-focused-2026-10-07',
        'label':'Stated checks and evidence · development','action_target_version':'action-target-correspondence/4'},
    'checking-role':{'kind':'extraction','directory':ROOT/'research/checking-role-2026-10-07/software',
        'label':'Checking applicability and material · development','action_target_version':'action-target-correspondence/4'},
    'airline-checking-role':{'kind':'extraction','directory':ROOT/'research/checking-role-2026-10-07/airline',
        'label':'Checking applicability · development','action_target_version':'action-target-correspondence/3'},
    'airline-participants':{'kind':'extraction','directory':ROOT/'research/airline-participants-2026-10-08/observer',
        'label':'Requests through recurring work · development','action_target_version':'action-target-correspondence/3'},
    'retail-checking-role':{'kind':'extraction','directory':ROOT/'research/checking-role-2026-10-07/retail',
        'label':'Checking applicability · development','action_target_version':'action-target-correspondence/4'},
    'retail-checking-repair':{'kind':'extraction','directory':ROOT/'research/checking-candidate-repair-2026-10-07/retail',
        'label':'Checking contents · repaired development','action_target_version':'action-target-correspondence/4'},
    'retail-later-checks':{'kind':'extraction','directory':ROOT/'research/check-followthrough-2026-10-07/retail',
        'label':'Later check links · development','action_target_version':'action-target-correspondence/4'},
    'software-later-checks':{'kind':'extraction','directory':ROOT/'research/check-followthrough-2026-10-07/software',
        'label':'Later check links · development','action_target_version':'action-target-correspondence/4'},
    'retail-response-material':{'kind':'extraction','directory':ROOT/'research/response-material-dispatch-2026-10-07/retail',
        'label':'Response material and operation · development','action_target_version':'action-target-correspondence/4'},
    'software-response-material':{'kind':'extraction','directory':ROOT/'research/response-material-dispatch-2026-10-07/software',
        'label':'Response material and operation · development','action_target_version':'action-target-correspondence/4'}}

# Additive observer: existing work-context observations remain unchanged/exportable.
for domain in ('software','airline','retail'):
    PROFILES[domain+'-execution-reports']={**PROFILES[domain+'-work-context'],
        'label':'Work scopes + executor reports · development',
        'execution_directory':ROOT/'research/execution-reports-2026-10-08'/domain}
PROFILES['software-plan-evidence']={**PROFILES['software-execution-reports'],
    'label':'Plan stages and result evidence · development',
    'stage_material_directory':ROOT/'research/plan-execution-2026-10-08/software'}
for domain in ('software','airline','retail'):
    PROFILES[domain+'-operation-outcomes']={**PROFILES[domain+('-plan-evidence' if domain=='software' else '-execution-reports')],
        'label':'Operation outcomes and returns · development',
        'operation_directory':ROOT/'research/operation-outcomes-2026-10-08'/domain}
    PROFILES[domain+'-attempt-revisions']={**PROFILES[domain+'-operation-outcomes'],
        'label':'Stated changes, actions and retry outcomes · experimental',
        'attempt_revision_directory':ROOT/'research/attempt-revisions-v4-2026-10-08'/domain}
PROFILES['software-local-adjustments']={**PROFILES['software-operation-outcomes'],
    'label':'Reusable work adjustments and evidence paths · experimental',
    'local_adjustment_directory':ROOT/'research/local-adjustments-v2-2026-10-08/software',
    'adjustment_work_directory':ROOT/'research/work-items-complete-2026-10-08/software'}


def registered(store):
    if store is None:return {}
    with store.connect() as connection:
        import json
        return {row['id']:json.loads(row['document']) for row in connection.execute('SELECT id, document FROM semantic_observers ORDER BY id')}


def profile(observer,store=None):
    if observer in PROFILES:return PROFILES[observer]
    saved=registered(store).get(observer)
    if saved is None:raise InputError('Unknown semantic observer')
    return {**saved,'directory':Path(saved['directory'])}


def load(run,observer,store=None):
    from .observer_archive import load as load_archive
    archived = load_archive(store,run,observer)
    if archived is not None:return archived
    p=profile(observer,store)
    if 'members' in p:
        member=p['members'].get(run['id'])
        if member is None:raise InputError('Rollout is outside this frozen observer collection')
        p={**p,**member,'run_id':run['id']}
    if p.get('run_id') and (p['run_id']!=run['id'] or p['source_hash']!=digest(run)):
        raise InputError('Registered observer belongs to another source')
    result=load_reference(run) if p['kind']=='reference' else load_extraction(run,p['directory'],action_target_version=p.get('action_target_version'),plan_relation_version=p.get('plan_relation_version'))
    if result['available']:
        if p.get('method_directory'):
            from .method_comparison import load as load_methods
            result['document']['method_comparison']=load_methods(run,result['document'],p['method_directory'])
        if p.get('extraction_hash') and (p['extraction_hash']!=digest(result['raw_extraction']) or p.get('base_map_hash',p['map_hash'])!=digest(result['document'])):
            raise InputError('Registered observation changed; register its new audited version')
        if p.get('execution_directory'):
            from .execution_reports import path_for,audit,project
            reports=read(path_for(p['execution_directory'],run))
            if p.get('execution_report_hash') and digest(reports)!=p['execution_report_hash']:
                raise InputError('Registered execution reports changed')
            validation=audit(run,reports,p['execution_directory'])
            result=project(run,result,reports)
            result['validation']['execution_reports']=validation
            if p.get('base_map_hash') and p['map_hash']!=digest(result['document']):
                raise InputError('Registered execution map changed')
        if p.get('stage_material_directory'):
            from .plan_stage_material import path_for,audit
            material=read(path_for(p['stage_material_directory'],run,result['document']))
            result['validation']['plan_stage_material']=audit(run,result['document'],material,p['stage_material_directory'])
            result['document']['plan_stage_material']=material
        if p.get('operation_directory'):
            from .operation_outcomes import path_for,audit,project
            outcomes=read(path_for(p['operation_directory'],run))
            result['validation']['operation_outcomes']=audit(run,outcomes,p['operation_directory'])
            result=project(run,result,outcomes)
        if p.get('work_item_directory'):
            from .work_item_pass import audit,project
            observed=read(Path(p['work_item_directory'])/'complete.json')
            if digest(observed)!=p['work_item_pass_hash']:raise InputError('Registered work-item observation changed')
            result['validation']['declared_work_items']=audit(run,result['document'],observed,p['work_item_directory'])
            scope_parts=None
            if p.get('work_scope_parts_directory'):
                from . import work_scope_parts
                scope_root=Path(p['work_scope_parts_directory']);scope_parts=read(scope_root/'work-scope-parts.json')
                if digest(scope_parts)!=p['work_scope_parts_hash']:raise InputError('Registered work scope parts changed')
                result['validation']['work_scope_parts']=work_scope_parts.audit(run,result['document'],observed,scope_parts,scope_root)
            history=None;correspondences=None;work_outcomes=None;work_result_reviews=None
            if p.get('work_item_history_hash'):
                from . import declared_work_history
                history=read(Path(p['work_item_directory'])/'history.json')
                if digest(history)!=p['work_item_history_hash']:raise InputError('Registered work history changed')
                result['validation']['declared_work_history']=declared_work_history.audit(run,result['document'],observed,history,p['work_item_directory'])
                if p.get('work_item_action_hash'):
                    from . import declared_work_actions
                    correspondences=read(Path(p['work_item_directory'])/'action-correspondence.json')
                    if digest(correspondences)!=p['work_item_action_hash']:raise InputError('Registered work-action observation changed')
                    result['validation']['declared_work_actions']=declared_work_actions.audit(run,result['document'],observed,history,correspondences,p['work_item_directory'])
                    if p.get('work_item_results_hash'):
                        from . import work_results
                        result_root=Path(p.get('work_item_results_directory',p['work_item_directory']))
                        work_outcomes=read(result_root/'work-results.json')
                        if digest(work_outcomes)!=p['work_item_results_hash']:raise InputError('Registered work results changed')
                        result['validation']['work_results']=work_results.audit(run,result['document'],correspondences,work_outcomes,result_root)
                        if p.get('work_item_results_review_hash'):
                            work_result_reviews=read(result_root/'work-result-review.json')
                            if digest(work_result_reviews)!=p['work_item_results_review_hash']:raise InputError('Registered work-result review changed')
                            result['validation']['work_result_reviews']=work_results.validate_reviews(work_outcomes,work_result_reviews)
            result=project(run,result,observed)
            if scope_parts:result['document']['work_scope_parts']=scope_parts
            if correspondences:
                result['document']['declared_work_actions']=correspondences
                result['document']['relations'].extend(correspondences['relations'])
                if p.get('work_item_action_review_hash'):
                    reviews=read(Path(p['work_item_directory'])/'action-review.json')
                    if digest(reviews)!=p['work_item_action_review_hash']:raise InputError('Registered work-action review changed')
                    result['validation']['declared_work_action_reviews']=declared_work_actions.validate_reviews(run,correspondences,reviews)
                    result['document']['declared_work_action_review']=reviews
                    for note in reviews['notes']:
                        relation=next(r for r in correspondences['relations'] if all(r.get(k)==v for k,v in note['relation_ref'].items()))
                        result['document'].setdefault('review_notes',[]).append({**note,'evidence':relation['evidence']})
            if history:
                result['document']['declared_work_history']=history
                result['document']['relations'].extend(history['relations'])
                if p.get('work_item_history_review_hash'):
                    reviews=read(Path(p['work_item_directory'])/'history-review.json')
                    if digest(reviews)!=p['work_item_history_review_hash']:raise InputError('Registered work-history review changed')
                    result['validation']['declared_work_history_reviews']=declared_work_history.validate_reviews(run,result['document'],history,reviews)
                    history['review_notes']=reviews['notes']
            if work_outcomes:
                from .work_results import project as project_work_results
                result['document']=project_work_results(result['document'],work_outcomes,work_result_reviews)
        if p.get('attempt_revision_directory'):
            from .attempt_revision import load as load_revisions
            result=load_revisions(run,result,p['attempt_revision_directory'])
        if p.get('local_adjustment_directory'):
            from .adjustment_graph import load as load_adjustments
            result=load_adjustments(run,result,p['local_adjustment_directory'],p['adjustment_work_directory'],include_work_graph=p.get('adjustment_work_links',False),reference_directory=p.get('adjustment_reference_directory'))
            if p.get('local_adjustment_map_hash') and digest(result['document'])!=p['local_adjustment_map_hash']:
                raise InputError('Registered local adjustment observation or review changed')
        result['observer']={'id':observer,'label':p['label']}
        result['export_digest']=digest(export_payload(result))
    return result


def register(store,directory,run_id,label,*,action_target_version=None,method_directory=None,plan_relation_version=None,execution_directory=None):
    """Register an audited complete pass; bind both extraction and derived map."""
    if not isinstance(label,str) or not label.strip() or len(label)>160:
        raise InputError('Observer label must contain 1–160 characters')
    run=store.get(run_id,raw=True)['run']
    directory=Path(directory).resolve()
    result=load_extraction(run,directory,action_target_version=action_target_version,plan_relation_version=plan_relation_version)
    if not result['available'] or result['raw_extraction']['status']!='complete_local_extraction':
        raise InputError('Only an audited complete extraction can be registered')
    if method_directory:
        from .method_comparison import load as load_methods
        method_directory=str(Path(method_directory).resolve())
        result['document']['method_comparison']=load_methods(run,result['document'],method_directory)
    document={'schema':'registered-semantic-observer/1','kind':'extraction','directory':str(directory),
              'run_id':run_id,'source_hash':digest(run),'label':label.strip(),
              'extraction_hash':digest(result['raw_extraction']),'map_hash':digest(result['document'])}
    if action_target_version:document['action_target_version']=action_target_version
    if plan_relation_version:document['plan_relation_version']=plan_relation_version
    if method_directory:document['method_directory']=method_directory
    if execution_directory:
        from .execution_reports import path_for,audit,project
        execution_directory=str(Path(execution_directory).resolve())
        reports=read(path_for(execution_directory,run))
        validation=audit(run,reports,execution_directory)
        result=project(run,result,reports)
        result['validation']['execution_reports']=validation
        document.update(execution_directory=execution_directory,execution_report_hash=digest(reports),
            base_map_hash=document['map_hash'],map_hash=digest(result['document']))
    identifier='saved-'+digest(document)[:24]
    with store.connect() as connection:
        previous=connection.execute('SELECT document FROM semantic_observers WHERE id=?',(identifier,)).fetchone()
        if previous and previous['document']!=dumps(document):raise InputError('Observer identity collision')
        connection.execute('INSERT OR IGNORE INTO semantic_observers(id,document) VALUES(?,?)',(identifier,dumps(document)))
    from .rollout_metrics import record_map
    record_map(store,run,{**result,'observer':{'id':identifier,'label':label.strip()}})
    return {'observer':identifier,'run_id':run_id,'label':document['label'],'map_hash':document['map_hash'],
            'url':'/semantic-map?run='+run_id+'&observer='+identifier,
            'validation':result['validation'],'accuracy':'Not independently measured'}


def export_payload(result):
    if not result.get('available') or not result.get('observer'):
        raise InputError('A complete selected observer is required for export')
    source=result.get('raw_extraction',result['document'])
    observer={**result['observer'],'extraction_hash':digest(source)}
    if 'raw_extraction' in result:
        return {**source,'observer':observer,'map':result['document']}
    return {**result['document'],'observer':observer}


def catalog(store):
    from .observer_archive import catalog_rows
    rows=catalog_rows(store);unavailable=[]
    archived={(r['observer'],r['run_id']) for r in rows}
    saved_profiles=registered(store) if hasattr(store,'connect') else {}
    for observer,p in {**PROFILES,**saved_profiles}.items():
        p={**p,'directory':Path(p['directory'])}
        if observer in saved_profiles:
            if 'members' in p:
                for rid in p['members']:
                    if (observer,rid) in archived:continue
                    try:
                        run=store.get(rid,raw=True)['run'];checked=load(run,observer,store)
                        if not checked['available']:raise InputError('Registered result is missing')
                        rows.append({'run_id':rid,'observer':observer,'observer_label':p['label'],
                            'task':run.get('metadata',{}).get('task_id') or rid,'adapter':run.get('adapter'),
                            'source_hash':digest(run),'extraction_hash':digest(checked['raw_extraction'])})
                    except (InputError,OSError,KeyError,ValueError):
                        unavailable.append({'observer':observer,'run_id':rid,
                            'reason':'Collection member is missing, changed or failed its audit; register the intended version.'})
                continue
            if (observer,p['run_id']) in archived:continue
            try:
                run=store.get(p['run_id'],raw=True)['run']
                checked=load(run,observer,store)
                if not checked['available']:raise InputError('Registered result is missing')
                rows.append({'run_id':run['id'],'observer':observer,'observer_label':p['label'],
                    'task':run.get('metadata',{}).get('task_id') or run['id'],
                    'adapter':run.get('adapter'),'source_hash':digest(run),
                    'extraction_hash':digest(checked.get('raw_extraction',checked['document']))})
            except (InputError,OSError,KeyError,ValueError):
                unavailable.append({'observer':observer,'run_id':p['run_id'],
                                    'reason':'Registered result is missing, changed or failed its audit; inspect/register the intended version.'})
            continue
        folder=p['directory'] if p['kind']=='reference' else p['directory']/'results'
        for path in sorted(folder.glob('*.json')):
            if not path.stem.isalnum():continue
            if (observer,path.stem) in archived:continue
            saved=read(path)
            if p['kind']=='extraction' and saved.get('status')!='complete_local_extraction':continue
            try:run=store.get(path.stem,raw=True)['run']
            except (InputError,KeyError):continue
            if saved.get('run_id')!=run['id'] or saved.get('source_hash')!=digest(run):continue
            if p.get('execution_directory'):
                from .execution_reports import path_for
                if not path_for(p['execution_directory'],run).exists():continue
            if p.get('operation_directory'):
                from .operation_outcomes import path_for
                if not path_for(p['operation_directory'],run).exists():continue
            if p.get('attempt_revision_directory'):
                baseline=p['attempt_revision_directory']/'baseline.json'
                if not baseline.exists():continue
                base=read(baseline)
                if base['run']['id']!=run['id'] or not (p['attempt_revision_directory']/'results'/f'{digest(base["bundle"]["document"])}.json').exists():continue
            if p.get('local_adjustment_directory'):
                path=Path(p['local_adjustment_directory'])/'local-adjustments.json'
                if not path.exists() or read(path).get('source_hash')!=digest(run):continue
            if p.get('stage_material_directory'):
                # Only publish the explicitly inspected source, never unrelated files
                # that happen to share the upstream extraction directory.
                if not (p['stage_material_directory']/'baseline.json').exists():continue
                material_baseline=read(p['stage_material_directory']/'baseline.json')
                from .plan_stage_material import path_for
                if material_baseline['run']['id']!=run['id'] or not path_for(p['stage_material_directory'],run,material_baseline['bundle']['document']).exists():continue
            rows.append({'run_id':run['id'],'observer':observer,'observer_label':p['label'],
                'task':run.get('metadata',{}).get('task_id') or run['id'],
                'adapter':run.get('adapter'),'source_hash':digest(run),'extraction_hash':digest(saved)})
    return {'maps':rows,'unavailable':unavailable,'scope':'Saved observer passes on recorded trajectories. Changing observer is not a model-training comparison.'}
