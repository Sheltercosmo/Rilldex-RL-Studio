"""Complete-source work declarations, built after coherent unit/content selection."""
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
import time

from . import declared_work_items as items
from .schema import InputError, digest, dumps
from .semantic_extraction import Pipeline, read, write
from .semantic_workspace import exclusive

VERSION='declared-work-pass/1'


def eligible(document):
    return [u for u in document['units'] if u['actor']=='agent' and u['kind']=='semantic']


def prepare(store,directory,run_id,observer):
    from .semantic_catalog import load as load_map
    run=store.get(run_id,raw=True)['run'];bundle=load_map(run,observer,store)
    if not bundle.get('available'):raise InputError('An available audited semantic map is required')
    doc=bundle['document']
    config={'schema':VERSION,'harness':items.DESCRIBED_VERSION,'run_id':run_id,'source_hash':digest(run),
            'parent_observer':observer,'base_map_hash':digest(doc)}
    with exclusive(directory) as root:
        if (root/'workspace.json').exists():
            if read(root/'workspace.json')!=config:raise InputError('Work-item workspace source or parent map changed')
            load(root)
        else:
            if any(p.name!='.workspace.lock' for p in root.iterdir()):raise InputError('Use an empty work-item workspace')
            write(root/'source.json',run);write(root/'base-map.json',doc);write(root/'workspace.json',config)
        provider=items.FileCandidates(root/'candidates')
        for unit in eligible(doc):provider.get(run,items.proposal_request(run,doc,unit,version=config['harness']))
    return {'config':config,'eligible_units':len(eligible(doc)),
            'limits':'Candidates are proposals; this command makes no Jev decisions.'}


def load(directory):
    root=Path(directory);config=read(root/'workspace.json');run=read(root/'source.json');doc=read(root/'base-map.json')
    if config.get('schema')!=VERSION or config.get('harness')!=items.DESCRIBED_VERSION:
        raise InputError('Unknown work-item workspace version')
    if (config['source_hash']!=digest(run) or config['base_map_hash']!=digest(doc)
            or doc['source_hash']!=digest(run) or config['run_id']!=run['id']):
        raise InputError('Work-item workspace source or parent map changed')
    return config,run,doc


def build(run,doc,provider,engine):
    rows=[items.inspect(run,doc,u,provider,engine,version=items.DESCRIBED_VERSION) for u in eligible(doc)]
    return {'schema':VERSION,'source_hash':digest(run),'base_map_hash':digest(doc),
            'status':'complete' if all(r['status']=='selected' for r in rows) else 'incomplete',
            'observations':rows,'coverage':{'eligible_units':len(rows),'selected_units':sum(r['status']=='selected' for r in rows)},
            'limits':'Source-attributed declarations inside existing units. No active mental state, cross-unit identity, executed work or independently verified achievement.'}


def audit(run,doc,result,directory):
    if (result['schema']!=VERSION or result['source_hash']!=digest(run) or result['base_map_hash']!=digest(doc)):
        raise InputError('Work-item pass source or parent map differs')
    expected=[u['id'] for u in eligible(doc)]
    if [r['unit_id'] for r in result['observations']]!=expected:raise InputError('Work-item pass does not cover every eligible unit exactly once')
    for unit,row in zip(eligible(doc),result['observations']):items.audit(run,doc,unit,row,directory)
    selected=sum(r['status']=='selected' for r in result['observations'])
    if result['coverage']!={'eligible_units':len(expected),'selected_units':selected} or result['status']!=('complete' if selected==len(expected) else 'incomplete'):
        raise InputError('Work-item pass coverage/status differs')
    return {'eligible_units':len(expected),'selected_units':selected,'argmax_replayed':True,
            'semantic_accuracy':'Not independently measured; candidate author is retained for each unit.'}


def execute(directory,transport,progress=None):
    with exclusive(directory) as root:
        config,run,doc=load(root);provider=items.FileCandidates(root/'candidates')
        def recorded(req):
            response=transport(req);write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
            if progress:progress({'unit_id':req['state']['unit_id']})
            return response
        engine=Pipeline(root,provider,recorded);result=build(run,doc,provider,engine)
        validation=audit(run,doc,result,root);write(root/'passes'/f'{digest(result)}.json',result)
        write(root/'latest.json',result)
        if result['status']=='complete':write(root/'complete.json',result)
        return {'status':result['status'],'coverage':result['coverage'],'new_calls':engine.calls,'validation':validation}


def history(directory,transport,progress=None):
    from . import declared_work_history
    with exclusive(directory) as root:
        config,run,doc=load(root);local=read(root/'complete.json');audit(run,doc,local,root)
        def recorded(req):
            response=transport(req);write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
            if progress:progress({'unit_id':req['state']['unit_id'],'item_id':req['state']['item']['id']})
            return response
        engine=Pipeline(root,None,recorded);result,validation=declared_work_history.execute(run,doc,local,engine)
        return {'validation':validation,'new_calls':engine.calls,'history_hash':digest(result)}


def actions(directory,transport,progress=None):
    from . import declared_work_history,declared_work_actions
    with exclusive(directory) as root:
        config,run,doc=load(root);local=read(root/'complete.json');prior=read(root/'history.json')
        audit(run,doc,local,root);declared_work_history.audit(run,doc,local,prior,root)
        def recorded(req):
            response=transport(req);write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
            if progress:progress({'action_unit_id':req['state']['action_unit_id']})
            return response
        engine=Pipeline(root,None,recorded);result,validation=declared_work_actions.execute(run,doc,local,prior,engine)
        return {'validation':validation,'new_calls':engine.calls,'action_correspondence_hash':digest(result)}


def results(directory,transport,progress=None,*,result_directory=None,protocol='legacy'):
    from . import declared_work_history,declared_work_actions,work_results
    with exclusive(directory) as root:
        config,run,doc=load(root);local=read(root/'complete.json');prior=read(root/'history.json');correspondences=read(root/'action-correspondence.json')
        audit(run,doc,local,root);declared_work_history.audit(run,doc,local,prior,root)
        declared_work_actions.audit(run,doc,local,prior,correspondences,root)
        versions={'legacy':work_results.VERSION,'operation':work_results.SUPPORTED_VERSION}
        if protocol not in versions:raise InputError('Unknown work-result protocol')
        output=Path(result_directory).resolve() if result_directory else root.resolve()
        if protocol!='legacy' and output==root.resolve():
            raise InputError('Use a separate result directory for the operation protocol to preserve existing observers')
        with exclusive(output) if output!=root.resolve() else nullcontext(root) as result_root:
            if output!=root.resolve():
                identity={'schema':'work-result-workspace/1','source_hash':digest(run),
                          'base_map_hash':digest(doc),'correspondences_hash':digest(correspondences),
                          'protocol':versions[protocol]}
                path=result_root/'result-workspace.json'
                if path.exists() and read(path)!=identity:raise InputError('Work-result workspace dependencies changed')
                write(path,identity)
            def recorded(req):
                response=transport(req);write(result_root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                if progress:progress({'stage':req['state']['stage'],'scope_id':req['state'].get('scope_id'),
                                      'response_event_id':req['state'].get('cutoff_event_id')})
                return response
            engine=Pipeline(result_root,None,recorded);result,validation=work_results.execute(run,doc,correspondences,engine,versions[protocol])
            return {'validation':validation,'new_calls':engine.calls,'work_results_hash':digest(result),
                    'result_directory':str(result_root.resolve())}


def project(run,bundle,result):
    if result['status']!='complete' or digest(bundle['document'])!=result['base_map_hash'] or digest(run)!=result['source_hash']:
        raise InputError('Only a complete work-item pass over this exact map can be projected')
    out=deepcopy(bundle);out['document']['declared_work_items']=deepcopy(result)
    return out


def scope_parts(directory,transport,progress=None,*,parts_directory):
    from . import work_scope_parts
    with exclusive(directory) as root:
        config,run,doc=load(root);local=read(root/'complete.json');audit(run,doc,local,root)
        output=Path(parts_directory).resolve()
        if output==root.resolve():raise InputError('Use a separate directory for experimental work scope parts')
        with exclusive(output) as parts_root:
            identity={'schema':'work-scope-parts-workspace/1','source_hash':digest(run),
                      'base_map_hash':digest(doc),'work_items_hash':digest(local),'protocol':work_scope_parts.VERSION}
            path=parts_root/'scope-workspace.json'
            if path.exists() and read(path)!=identity:raise InputError('Work scope parts workspace dependencies changed')
            write(path,identity)
            def recorded(req):
                response=transport(req);write(parts_root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                if progress:progress({'unit_id':req['state']['unit_id'],'item_id':req['state']['item_id']})
                return response
            engine=Pipeline(parts_root,None,recorded)
            result=work_scope_parts.build(run,doc,local,engine.decide)
            validation=work_scope_parts.audit(run,doc,local,result,parts_root)
            write(parts_root/'passes'/f'{digest(result)}.json',result);write(parts_root/'work-scope-parts.json',result)
            return {'validation':validation,'new_calls':engine.calls,'scope_parts_hash':digest(result)}


def adjustments(directory,transport,progress=None,*,adjustment_directory,max_calls=50,audit_only=False,protocol='legacy'):
    from . import local_adjustments
    if type(max_calls)!=int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    versions={'legacy':local_adjustments.VERSION,'facet':local_adjustments.FACET_VERSION,'effect':local_adjustments.EFFECT_VERSION}
    if protocol not in versions:raise InputError('Unknown local adjustment protocol')
    version=versions[protocol]
    with exclusive(directory) as root:
        config,run,doc=load(root);local=read(root/'complete.json');audit(run,doc,local,root)
        output=Path(adjustment_directory).resolve()
        if output==root.resolve():raise InputError('Use a separate local-adjustment workspace')
        with exclusive(output) as out:
            definition={'schema':'local-adjustment-workspace/1','source_hash':digest(run),
                'base_map_hash':digest(doc),'work_items_hash':digest(local),'harness':version}
            path=out/'workspace.json'
            if path.exists() and read(path)!=definition:raise InputError('Adjustment workspace dependencies changed')
            if audit_only:
                result=read(out/'local-adjustments.json')
                return {'validation':local_adjustments.audit(run,doc,local,result,out),'new_calls':0}
            write(path,definition);count=0
            def recorded(req):
                nonlocal count
                if count>=max_calls:raise InputError('Local adjustment request budget exhausted; completed decisions remain saved for resume')
                count+=1;response=transport(req);write(out/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                if progress:progress({'event_id':req['state']['subject']['event_id'],'new_calls':count})
                return response
            engine=Pipeline(out,None,recorded);result,validation=local_adjustments.execute(run,doc,local,engine,version)
            return {'validation':validation,'new_calls':engine.calls,'local_adjustments_hash':digest(result),
                    'adjustment_directory':str(out)}


def adjustment_references(directory,transport,progress=None,*,adjustment_directory,reference_directory,max_calls=20,audit_only=False):
    from . import adjustment_references as refs,local_adjustments,declared_work_history,declared_work_actions
    if type(max_calls)!=int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    with exclusive(directory) as root:
        with exclusive(adjustment_directory) as adjustment:
            config,run,doc=load(root);local=read(root/'complete.json');history=read(root/'history.json');actions=read(root/'action-correspondence.json')
            effects=read(adjustment/'local-adjustments.json')
            audit(run,doc,local,root);declared_work_history.audit(run,doc,local,history,root)
            declared_work_actions.audit(run,doc,local,history,actions,root);local_adjustments.audit(run,doc,local,effects,adjustment)
            output=Path(reference_directory).resolve()
            if output in {root.resolve(),adjustment.resolve()}:raise InputError('Use a separate reference workspace')
            with exclusive(output) as out:
                identity={'schema':refs.VERSION,**refs.inputs(run,doc,local,history,actions,effects)};path=out/'workspace.json'
                if path.exists() and read(path)!=identity:raise InputError('Reference workspace dependencies changed')
                if audit_only:
                    result=read(out/'adjustment-references.json')
                    return {'validation':refs.audit(run,doc,local,history,actions,effects,result,out),'new_calls':0}
                write(path,identity);count=0
                def recorded(req):
                    nonlocal count
                    if count>=max_calls:raise InputError('Reference request budget exhausted; saved decisions remain reusable')
                    count+=1;response=transport(req);write(out/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
                    if progress:progress({'event_id':req['state']['subject']['event_id'],'new_calls':count})
                    return response
                engine=Pipeline(out,None,recorded);result,validation=refs.execute(run,doc,local,history,actions,effects,engine)
                return {'validation':validation,'new_calls':engine.calls,'references_hash':digest(result)}


def register(store,directory,label,*,result_directory=None,parts_directory=None):
    from .semantic_catalog import profile,load as load_map
    if not isinstance(label,str) or not label.strip() or len(label)>160:raise InputError('Use an observer label of 1–160 characters')
    with exclusive(directory) as root:
        config,run,doc=load(root);result=read(root/'complete.json');validation=audit(run,doc,result,root)
        current=load_map(run,config['parent_observer'],store)
        project(run,current,result)
        definition={k:str(v) if isinstance(v,Path) else v for k,v in profile(config['parent_observer'],store).items()}
        if definition.get('work_item_directory'):raise InputError('Choose a parent observer without a work-item extension')
        definition.update(label=label.strip(),run_id=run['id'],source_hash=digest(run),
            work_item_directory=str(root.resolve()),work_item_pass_hash=digest(result))
        if parts_directory:
            from . import work_scope_parts
            parts_root=Path(parts_directory).resolve();parts=read(parts_root/'work-scope-parts.json')
            validation['work_scope_parts']=work_scope_parts.audit(run,doc,result,parts,parts_root)
            definition.update(work_scope_parts_directory=str(parts_root),work_scope_parts_hash=digest(parts))
        if (root/'history.json').exists():
            from . import declared_work_history
            history=read(root/'history.json')
            validation['history']=declared_work_history.audit(run,doc,result,history,root)
            definition['work_item_history_hash']=digest(history)
            if (root/'action-correspondence.json').exists():
                from . import declared_work_actions
                correspondences=read(root/'action-correspondence.json')
                validation['actions']=declared_work_actions.audit(run,doc,result,history,correspondences,root)
                definition['work_item_action_hash']=digest(correspondences)
                result_root=Path(result_directory).resolve() if result_directory else root
                if result_directory and not (result_root/'work-results.json').exists():raise InputError('Requested work-result observation is missing')
                if (result_root/'work-results.json').exists():
                    from . import work_results
                    outcomes=read(result_root/'work-results.json')
                    validation['work_results']=work_results.audit(run,doc,correspondences,outcomes,result_root)
                    definition['work_item_results_hash']=digest(outcomes)
                    if result_directory:definition['work_item_results_directory']=str(result_root)
                    if (result_root/'work-result-review.json').exists():
                        result_reviews=read(result_root/'work-result-review.json')
                        validation['work_result_reviews']=work_results.validate_reviews(outcomes,result_reviews)
                        definition['work_item_results_review_hash']=digest(result_reviews)
                if (root/'action-review.json').exists():
                    reviews=read(root/'action-review.json');validation['action_reviews']=declared_work_actions.validate_reviews(run,correspondences,reviews)
                    definition['work_item_action_review_hash']=digest(reviews)
            if (root/'history-review.json').exists():
                reviews=read(root/'history-review.json');validation['history_reviews']=declared_work_history.validate_reviews(run,doc,history,reviews)
                definition['work_item_history_review_hash']=digest(reviews)
        if result_directory and 'work_item_results_directory' not in definition:
            raise InputError('Work results require complete local histories and action correspondences')
        key='saved-'+digest(definition)[:24]
        with store.connect() as c:c.execute('INSERT OR IGNORE INTO semantic_observers VALUES (?,?)',(key,dumps(definition)))
    return {'observer':key,'run_id':run['id'],'validation':validation,
            'url':'/semantic-map?run='+run['id']+'&observer='+key}
