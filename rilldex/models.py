"""Installed model checks and a resumable, single-rollout pilot.

python -m rilldex.models check
python -m rilldex.models probe    # one explicit candidate API request
python -m rilldex.models pilot ./pilot --db study.sqlite --run-id ...
"""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode

from . import candidate
from tracker.schema import InputError, digest
from tracker.jev import DEFAULT_MODEL


def check(environ=None):
    env = os.environ if environ is None else environ
    try:
        config = candidate.settings(env)
        proposal = dict(state='configured', endpoint=config['endpoint'], model=config['model'],
                        credential_set=bool(config['key']), contract=candidate.VERSION)
    except ValueError as exc:
        proposal = dict(state='needs_configuration', detail=str(exc))
    decision = dict(provider='Jev / Typesafe', model=DEFAULT_MODEL,
                    state='configured' if env.get('JEV_API_KEY') else 'needs_credential')
    return dict(candidate=proposal, decision=decision, network_calls=0,
                configured=proposal['state']=='configured' and decision['state']=='configured',
                note='Configuration only. Run probe to check the candidate JSON contract; pilot checks the staged workflow.')


def probe():
    packet = dict(stage='connection-check', instructions='Return exactly {"ok": true}.',
                  response_contract={'ok': True})
    result = candidate.propose(packet, **candidate.settings())
    if result != {'ok': True}:
        raise InputError('Candidate endpoint returned JSON but did not follow the probe contract')
    return dict(candidate_contract='passed', requests=1, semantic_accuracy='not_tested')


def pilot(store, directory, run_id, *, candidate_calls=0, decision_calls=0, input_bytes=0,
          transport=None,inspect_feedback=False,inspect_approaches=False):
    from tracker import semantic_workspace as workspace
    from tracker.semantic_extraction import read, write
    from tracker.semantic_budget import limits, summary
    from tracker.semantic_catalog import register
    from tracker.jev import JevClient
    from tracker.action_targets import PAGED_VERSION
    from tracker.plan_relations import DIRECT_VERSION as PLAN_VERSION
    from tracker.execution_reports import VERSION as REPORT_VERSION
    from tracker.method_comparison import NATIVE_VERSION as METHOD_VERSION
    cap = limits(dict(candidate_requests=candidate_calls, jev_requests=decision_calls, input_bytes=input_bytes))
    if type(inspect_feedback) is not bool:raise InputError('inspect_feedback must be a boolean')
    if type(inspect_approaches) is not bool:raise InputError('inspect_approaches must be a boolean')
    config = candidate.settings()
    identity = dict(adapter=candidate.VERSION, endpoint=config['endpoint'], model=config['model'], decision_model=DEFAULT_MODEL)
    root = Path(directory).resolve()
    # Serialize the lifetime calculation as well as execution. A different lock
    # from workspace.exclusive allows the existing execution lock to remain intact.
    with workspace.exclusive(root / 'pilot-lock'):
        work = root / 'extraction'
        pin = root / 'model.json'
        # Old pilots keep their original local-only protocol and request hashes.
        # New pilots include work correspondence within the same lifetime limits.
        saved=read(pin) if pin.exists() else None
        if saved is None or saved.get('action_target_version'):
            identity['action_target_version']=PAGED_VERSION
        if saved is None or saved.get('plan_relation_version'):
            identity['plan_relation_version']=saved['plan_relation_version'] if saved else PLAN_VERSION
        if saved is None or saved.get('execution_report_version') or inspect_feedback:
            identity['execution_report_version']=REPORT_VERSION
        if saved is None or saved.get('method_comparison_version') or inspect_approaches:
            if not identity.get('action_target_version'):
                raise InputError('Approach comparison needs work-target links. Start a new pilot to add them.')
            identity['method_comparison_version']=METHOD_VERSION
        additive={'execution_report_version','method_comparison_version'}
        added={k:v for k,v in identity.items() if saved is not None and k not in saved}
        upgrade=bool(saved and added and set(added)<=additive and {k:v for k,v in identity.items() if k not in added}==saved)
        if pin.exists() and read(pin) != identity and not upgrade:
            raise InputError('Model configuration changed. Use a new pilot directory to keep cached decisions separate.')
        try:
            run = store.get(run_id, raw=True)['run']
        except KeyError:
            raise InputError('Choose a rollout from this workspace') from None
        from tracker.semantic_watch import _current_complete
        with store.connect() as c:
            if not _current_complete(c, run_id):
                raise InputError('This rollout is still growing or superseded. Select its latest completed revision.')
        if upgrade:
            with workspace.exclusive(work):
                previous,source=workspace.load(work)
                if source!=run:raise InputError('Saved pilot source changed')
                if any(previous.get(k) not in {None,v} for k,v in added.items()):
                    raise InputError('Saved inspection protocol differs')
                write(work/'configuration-history'/f'{digest(previous)}.json',previous)
                write(work/'workspace.json',{**previous,**added})
        workspace.initialize(work, run,action_target_version=identity.get('action_target_version'),plan_relation_version=identity.get('plan_relation_version'),execution_report_version=identity.get('execution_report_version'),method_comparison_version=identity.get('method_comparison_version'))
        write(pin, identity)
        usage = summary(work)['providers']
        used = dict(candidate_requests=usage.get('candidate', {}).get('attempts', 0),
                    jev_requests=usage.get('jev', {}).get('attempts', 0),
                    input_bytes=sum(p['input_bytes'] for p in usage.values()))
        remaining = {k: max(0, cap[k]-used[k]) for k in cap}
        if any(cap[k] < used[k] for k in cap):
            raise InputError('Lifetime limits cannot be below recorded usage. Reuse or raise the previous limits.')
        if remaining['jev_requests'] and transport is None and not os.environ.get('JEV_API_KEY'):
            raise InputError('Set JEV_API_KEY in the worker environment before allowing decision calls')
        result = workspace.execute(work, transport or JevClient().transport,
            command=[sys.executable, '-m', 'rilldex.candidate'], producer='installed-'+digest({k:v for k,v in identity.items() if k not in additive})[:20],
            budget_limits=remaining)
        result.update(lifetime_limits=cap, model=identity, directory=str(root))
        if result['last_complete_result_present']:
            linked=result['layers']['action_targets']['status']=='complete'
            plans=result['layers']['plan_relations'];plan_ready=plans['status']=='complete'
            has_plans=plan_ready and plans.get('coverage',{}).get('plans',0)>0
            reports_ready=result['layers']['execution_reports']['status']=='complete'
            methods_ready=linked and result['layers']['method_comparison']['status']=='complete'
            registered = register(store, work, run_id, ('Plans & activities · ' if has_plans else 'Activities & work links · ' if linked else 'Activities · ')+config['model'],
                action_target_version=identity.get('action_target_version') if linked else None,
                plan_relation_version=identity.get('plan_relation_version') if plan_ready else None,
                method_directory=work if methods_ready else None,
                execution_directory=work if reports_ready else None)
            result['map_url'] = '/semantic-map?'+urlencode(dict(run=run_id, observer=registered['observer'],**({'level':'plans'} if has_plans else {})))
            result['map_scope']='activities_and_work_links' if linked else 'local_activities'
            result['plan_map_available']=has_plans
            result['execution_reports_available']=reports_ready
            result['approach_comparisons_available']=methods_ready
            if methods_ready:
                result['work_map_url']='/semantic-map?'+urlencode(dict(run=run_id,observer=registered['observer'],level='work'))
        write(root/'pilot-result.json',dict(state=result['status'],run_id=run_id,directory=str(root),
            limits=dict(run_id=run_id,candidate_calls=candidate_calls,decision_calls=decision_calls,input_bytes=input_bytes),result=result))
        return result


def watch(store,directory,*,experiment,label=None,from_pilot=None,candidate_calls=None,
          decision_calls=None,input_bytes=None,max_rollouts=8,max_pending=64,retry_runs=None,
          live_prefixes=None,transport=None,refresh_worker=False):
    """Observe existing and arriving rollouts with one persistent observer.

    New workers start at zero allowance. Omitted limits retain their saved
    ceilings on resume; explicit limits can only increase them. A pilot supplies
    exact caches, never its published results or a replenished spending limit.
    """
    from tracker import semantic_watch as worker,semantic_workspace as workspace
    from tracker.semantic_extraction import read
    if live_prefixes is not None and type(live_prefixes) is not bool:raise InputError('live_prefixes must be boolean or omitted')
    if type(refresh_worker) is not bool:raise InputError('refresh_worker must be boolean')
    config=candidate.settings()
    identity=dict(adapter=candidate.VERSION,endpoint=config['endpoint'],model=config['model'],decision_model=DEFAULT_MODEL)
    options=worker.behavior_options();caches=[]
    existing=worker.load(store,directory)[1] if (Path(directory)/'watch.json').exists() else None
    if existing:
        options=existing['workspace_options'];caches=existing.get('cache_directories',[])
        if label is None:label=existing['label']
        if live_prefixes is None:live_prefixes=existing.get('live_prefixes',False)
    if from_pilot:
        origin=Path(from_pilot).resolve();saved=read(origin/'model.json')
        if {k:saved.get(k) for k in identity}!=identity:
            raise InputError('Pilot model configuration differs; use its candidate model and endpoint to continue')
        pinned,_=workspace.load(origin/'extraction')
        options={k:pinned[k] for k in ('include_user','context_policy','activity_routing','reading_protocol',
            'partition_standard','feedback_profile','requested_profile','action_target_version','plan_relation_version','execution_report_version','method_comparison_version') if k in pinned}
        for key in worker.behavior_options():
            if saved.get(key)!=options.get(key):raise InputError('Pilot model and workspace protocols differ')
        identity=saved;caches=[origin/'extraction']
    else:identity.update({k:v for k,v in options.items() if k in worker.behavior_options()})
    command=[sys.executable,'-m','rilldex.candidate']
    producer='installed-'+digest({k:v for k,v in identity.items() if k not in {'execution_report_version','method_comparison_version'}})[:20]
    supplied=dict(candidate_requests=candidate_calls,jev_requests=decision_calls,input_bytes=input_bytes)
    initial={k:0 if v is None else v for k,v in supplied.items()}
    current=worker.initialize(store,directory,experiment=experiment,label=label or 'Activities, plans & feedback',
        workspace_options=options,command=command,producer=producer,allowance=initial,
        live_prefixes=bool(live_prefixes),cache_directories=caches,refresh=refresh_worker)
    cap={k:current['allowance'][k] if v is None else v for k,v in supplied.items()}
    if cap!=current['allowance']:worker.set_allowance(store,directory,cap)
    if cap['jev_requests']>current['used']['jev_requests'] and transport is None and not os.environ.get('JEV_API_KEY'):
        raise InputError('Set JEV_API_KEY in the worker environment before allowing decision calls')
    from tracker.jev import JevClient
    result=worker.run_once(store,directory,transport or JevClient().transport,command=command,
        max_rollouts=max_rollouts,max_pending=max_pending,retry_runs=retry_runs)
    from tracker import monitoring
    measures=[]
    if options.get('execution_report_version'):
        measures=[('Reported execution errors','execution_error_report_fraction'),
                  ('Execution feedback coverage','execution_report_coverage')]
        if options.get('action_target_version'):measures.append(('Returns after reported errors','target_revisit_after_error_count'))
    existing={m['id']:m for m in monitoring.definitions(store)};selected=[]
    for name,metric in measures:
        definition=monitoring.validate(dict(name=name,kind='metric',group='Behavior',observer=result['observer'],
            metric=metric,population=dict(experiment=experiment)))
        identifier='monitor-'+digest(definition)
        # Restart must retain a researcher's edits or pause of a starter measure.
        if identifier not in existing:monitoring.create(store,definition)
        selected.append(identifier)
    if options.get('action_target_version'):
        from tracker.repeated_work import MEASURES
        analysis_measures=[(metric,name) for metric,(_,name,_) in MEASURES.items()]
        if options.get('method_comparison_version'):
            analysis_measures.append(('procedure_change_fraction','Changed approaches in repeated work'))
        if options.get('execution_report_version'):
            analysis_measures.append(('error_report_repeat_fraction','Errors on repeated work'))
        for metric,name in analysis_measures:
            definition=monitoring.validate(dict(name=name,kind='analysis',group='Behavior',observer=result['observer'],
                analysis=dict(measure=metric),population=dict(experiment=experiment)))
            identifier='monitor-'+digest(definition)
            if identifier not in existing:monitoring.create(store,definition)
            selected.append(identifier)
    if selected:monitoring.sync(store,monitor_ids=selected)
    result['monitors']=selected
    result['dashboard_url']='/?'+urlencode(dict(experiment=experiment,view='measures'))
    result['models_url']='/connections#model-section'
    return result


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Configure candidate models and run a bounded rollout pilot')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='Check local configuration; no network calls')
    sub.add_parser('probe', help='Make exactly one candidate request to check its JSON contract')
    run = sub.add_parser('pilot', help='Observe one completed rollout; limits are lifetime totals for this directory')
    run.add_argument('directory'); run.add_argument('--db', required=True); run.add_argument('--run-id', required=True)
    run.add_argument('--candidate-calls', type=int, default=0)
    run.add_argument('--decision-calls', type=int, default=0)
    run.add_argument('--input-bytes', type=int, default=0)
    run.add_argument('--inspect-feedback',action='store_true',help='Add execution feedback inspection to an existing pilot; reuse its units and decisions')
    run.add_argument('--inspect-approaches',action='store_true',help='Add approach comparisons to a saved pilot with work links; reuse its units and decisions')
    follow=sub.add_parser('watch',help='Observe an experiment with the installed models; optionally reuse a pilot')
    follow.add_argument('directory');follow.add_argument('--db',required=True);follow.add_argument('--experiment',required=True)
    follow.add_argument('--label');follow.add_argument('--from-pilot',help='Retain this pilot protocol and reuse its exact saved requests')
    follow.add_argument('--candidate-calls',type=int);follow.add_argument('--decision-calls',type=int);follow.add_argument('--input-bytes',type=int)
    follow.add_argument('--max-rollouts',type=int,default=8);follow.add_argument('--max-pending',type=int,default=64)
    follow.add_argument('--retry-run',action='append',default=[])
    follow.add_argument('--live-prefixes',action='store_true',default=None);follow.add_argument('--follow',action='store_true')
    follow.add_argument('--refresh-worker',action='store_true',help='After a package update, replay saved work offline before resuming the pinned protocol')
    follow.add_argument('--poll-seconds',type=float,default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == 'check': result = check()
        elif args.command == 'probe': result = probe()
        else:
            from tracker.store import Store
            if not Path(args.db).is_file(): raise InputError('Workspace database does not exist')
            if args.command=='pilot':
                result = pilot(Store(args.db), args.directory, args.run_id,
                    candidate_calls=args.candidate_calls, decision_calls=args.decision_calls, input_bytes=args.input_bytes,inspect_feedback=args.inspect_feedback,inspect_approaches=args.inspect_approaches)
            else:
                import math,time
                if not math.isfinite(args.poll_seconds) or args.poll_seconds<1:raise InputError('Poll interval must be at least one second')
                previous=None;retries=args.retry_run
                while True:
                    result=watch(Store(args.db),args.directory,experiment=args.experiment,label=args.label,from_pilot=args.from_pilot,
                        candidate_calls=args.candidate_calls,decision_calls=args.decision_calls,input_bytes=args.input_bytes,
                        max_rollouts=args.max_rollouts,max_pending=args.max_pending,retry_runs=retries,live_prefixes=args.live_prefixes,refresh_worker=args.refresh_worker)
                    retries=[]
                    args.refresh_worker=False
                    if not args.follow:break
                    # Apply startup limits once; retain a ceiling subsequently
                    # raised by an operator through watch-budget.
                    args.candidate_calls=args.decision_calls=args.input_bytes=None
                    compact={k:v for k,v in result.items() if k!='jobs'}
                    if compact!=previous:print(json.dumps(compact,ensure_ascii=False),flush=True);previous=compact
                    time.sleep(args.poll_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (InputError, ValueError) as exc:
        parser.exit(1, str(exc)+'\n')
    except Exception as exc:
        # Never echo provider response bodies, which may include credentials.
        parser.exit(1, 'Model operation failed: '+type(exc).__name__+'\n')


if __name__ == '__main__':
    main()
