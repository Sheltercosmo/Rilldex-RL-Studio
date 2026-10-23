"""Public commands for the staged semantic workspace and observer registry."""
import getpass
import json
import os
from pathlib import Path

from . import semantic_workspace as workspace
from .schema import InputError
from .semantic_extraction import ACTIVITY_ROUTING,WORK_PHASE_ACTIVITY_ROUTING,WORK_ORGANIZATION_ACTIVITY_ROUTING


def configure(commands):
    parser=commands.add_parser('semantic',help='Prepare, resume, audit and display coherent semantic extraction')
    sub=parser.add_subparsers(dest='semantic_command',required=True)
    watch=sub.add_parser('watch-init',help='Configure continuous extraction and optional feedback references; lifetime budget defaults to zero')
    watch.add_argument('directory');watch.add_argument('--experiment',required=True);watch.add_argument('--label',required=True)
    watch.add_argument('--workspace-options',help='JSON workspace options: activity routing, context, reading protocol, include_user, feedback_profile, requested_profile')
    watch.add_argument('--feedback-references',action='store_true',help='After base extraction, select explicit references to earlier tool feedback across primary activities')
    watch.add_argument('--behavior-links',action='store_true',help='Inspect plan steps, work-target relationships, executor feedback and approach comparisons under the same lifetime budget')
    watch.add_argument('--requested-conditions',action='store_true',help='Retain distinct user requirements, requested checks and their revisions after base extraction')
    watch.add_argument('--live-prefixes',action='store_true',help='Observe growing rollouts; reuse exact requests from earlier revisions without adding unfinished captures to completed-rollout rates')
    watch.add_argument('--max-new-calls',type=int,default=0);watch.add_argument('--max-candidate-calls',type=int,default=0);watch.add_argument('--max-input-bytes',type=int,default=0)
    watch.add_argument('--candidate-producer');watch.add_argument('--candidate-citation-format')
    watch.add_argument('--candidate-command',nargs='...')
    watcher=sub.add_parser('watch-run',help='Observe a bounded batch; --follow polls for new eligible snapshots under the configured completion policy')
    watcher.add_argument('directory');watcher.add_argument('--max-rollouts',type=int,default=8);watcher.add_argument('--max-pending',type=int,default=64)
    watcher.add_argument('--follow',action='store_true');watcher.add_argument('--poll-seconds',type=float,default=5)
    watcher.add_argument('--retry-run',action='append',default=[],help='Explicitly resume a blocked run, preserving consumed budget')
    watcher.add_argument('--candidate-command',nargs='...')
    watch_status=sub.add_parser('watch-status',help='Read observation coverage, blocked jobs and persistent provider usage')
    watch_status.add_argument('directory')
    watch_refresh=sub.add_parser('watch-refresh',help='Replay saved evidence offline after a package update; preserve the observer, protocol and lifetime usage')
    watch_refresh.add_argument('directory')
    watch_budget=sub.add_parser('watch-budget',help='Raise absolute lifetime limits without resetting consumed reservations')
    watch_budget.add_argument('directory');watch_budget.add_argument('--max-new-calls',type=int,required=True)
    watch_budget.add_argument('--max-candidate-calls',type=int,required=True);watch_budget.add_argument('--max-input-bytes',type=int,required=True)
    prepare=sub.add_parser('prepare',help='Freeze a source and queue first-stage candidates; no inference')
    prepare.add_argument('directory');prepare.add_argument('--run-id')
    prepare.add_argument('--agent-only',action='store_true',help='Exclude user contributions from extraction, retaining them as context')
    prepare.add_argument('--requested-conditions',action='store_true',help='Pin the requested terms/checks layer; requires user contributions')
    prepare.add_argument('--context-policy',help='Explicit JSON readable-context policy; frozen for this workspace')
    prepare.add_argument('--partition-standard',choices=['contribution-boundaries/3','contribution-boundaries/4'],help='Pinned contribution boundary standard; v4 preserves distinct work phases')
    prepare.add_argument('--activity-routing',choices=[ACTIVITY_ROUTING,WORK_PHASE_ACTIVITY_ROUTING,WORK_ORGANIZATION_ACTIVITY_ROUTING],
                         help='Versioned activity definitions; frozen in a new workspace. Work-organization is experimental.')
    prepare.add_argument('--reading-protocol',choices=['contribution-readings/1','contribution-readings/2'],
                         help='V2 aligns candidate definitions with selection and distinguishes contributed from described work; experimental.')
    revise=sub.add_parser('revise',help='Reclassify a complete extraction on frozen boundaries; changed activities queue fresh content')
    revise.add_argument('directory');revise.add_argument('--from-directory');revise.add_argument('--run-id')
    revise.add_argument('--activity-routing',choices=[ACTIVITY_ROUTING,WORK_PHASE_ACTIVITY_ROUTING,WORK_ORGANIZATION_ACTIVITY_ROUTING])
    revise.add_argument('--prompt-key',action='store_true')
    revise.add_argument('--plan-links',action='store_true',help='After a complete revision, rebuild action-to-Plan-stage links within the remaining call/byte budget')
    revise.add_argument('--max-new-calls',type=int,default=50);revise.add_argument('--max-input-bytes',type=int,default=1_000_000)
    mode=revise.add_mutually_exclusive_group();mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--audit-only',action='store_true')
    targets=sub.add_parser('refine-targets',help='Refine immediate work descriptions from selected fields; experimental, no candidate model calls')
    targets.add_argument('directory');targets.add_argument('--from-directory');targets.add_argument('--run-id')
    targets.add_argument('--prompt-key',action='store_true')
    targets.add_argument('--max-new-calls',type=int,default=0);targets.add_argument('--max-input-bytes',type=int,default=1_000_000)
    mode=targets.add_mutually_exclusive_group();mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--audit-only',action='store_true')
    repair=sub.add_parser('repair-content',help='Queue fresh coherent contents for selected fixed units; preserve the parent and rebuild dependent relations')
    repair.add_argument('directory');repair.add_argument('--from-directory');repair.add_argument('--run-id')
    repair.add_argument('--unit-id',action='append',default=[])
    repair.add_argument('--prompt-key',action='store_true')
    repair.add_argument('--max-new-calls',type=int,default=0);repair.add_argument('--max-input-bytes',type=int,default=1_000_000)
    mode=repair.add_mutually_exclusive_group();mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--audit-only',action='store_true')
    work=sub.add_parser('bind-work',help='Select immediate-work membership for source-bound prose and actions; experimental')
    work.add_argument('directory');work.add_argument('--graph');work.add_argument('--prompt-key',action='store_true')
    work.add_argument('--cache-from',action='append',default=[],help='Reuse exact validated decisions from this workspace; repeatable')
    work.add_argument('--max-new-calls',type=int,default=0);work.add_argument('--max-input-bytes',type=int,default=1_000_000)
    mode=work.add_mutually_exclusive_group();mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--audit-only',action='store_true');mode.add_argument('--register',action='store_true');mode.add_argument('--preflight',action='store_true',help='Read-only cache replay; identify the first required new decision without a model call')
    history=sub.add_parser('rebuild-history',help='Build target recurrence and feedback links in a separate observer, reusing only exact saved decisions')
    history.add_argument('directory');history.add_argument('--from-directory');history.add_argument('--run-id')
    history.add_argument('--reuse-decisions-from',action='append',default=[])
    history.add_argument('--action-target-version')
    history.add_argument('--feedback-reference-rule',choices=['assessment-reference-boundaries/2','assessment-direct-sets/1'],
                         help='Freeze the reference selection protocol; direct-sets is experimental')
    history.add_argument('--feedback-linkage',choices=['adapter-feedback-links/1'],
                         help='Use canonical adapter result bindings, including ATIF same-step correspondence')
    history.add_argument('--feedback-retrieval',choices=['feedback-lexical-retrieval/1','feedback-recent-plus-lexical/1','feedback-context-recent-plus-lexical/1'],
                         help='Search eligible earlier feedback locally instead of offering only the last three responses')
    history.add_argument('--feedback-scope',choices=['agent-contribution-feedback/1'],
                         help='Inspect agent semantic contributions across activities; requires --feedback-reference-rule assessment-direct-sets/1')
    history.add_argument('--prompt-key',action='store_true');history.add_argument('--max-new-calls',type=int,default=0)
    history.add_argument('--max-input-bytes',type=int,default=1_000_000)
    history_mode=history.add_mutually_exclusive_group();history_mode.add_argument('--prepare-only',action='store_true');history_mode.add_argument('--audit-only',action='store_true')
    run=sub.add_parser('run',help='Run/resume bounded Jev decisions and optional candidate generation')
    run.add_argument('directory');run.add_argument('--prompt-key',action='store_true')
    run.add_argument('--candidate-producer',help='Explicit generator name/version')
    from .candidate_worker import CITATION_FORMATS
    run.add_argument('--candidate-citation-format',choices=CITATION_FORMATS,help='Explicit response citation contract; the harness supplies this metadata')
    run.add_argument('--max-new-calls',type=int,default=50,help='New Jev request invocations this execution; built-in client does not retry internally. 0 reuses cache only')
    run.add_argument('--max-candidate-calls',type=int,default=50,help='New candidate subprocess invocations this execution; 0 reuses supplied candidates only')
    run.add_argument('--max-input-bytes',type=int,default=1_000_000,help='Total UTF-8 request payload bytes for new calls this execution; not a token or currency limit')
    run.add_argument('--candidate-command',nargs='...',help='Final option: program and arguments; JSON request on stdin, candidates on stdout')
    for name in ('status','audit'):
        child=sub.add_parser(name);child.add_argument('directory')
    publish=sub.add_parser('register',help='Audit and register a complete pass in the existing Behavior map')
    publish.add_argument('directory');publish.add_argument('--run-id')
    publish.add_argument('--label',required=True)
    publish.add_argument('--action-target-version')
    publish.add_argument('--method-directory')
    collection=sub.add_parser('register-collection',help='Audit a frozen group of rollouts under one common extraction observer')
    collection.add_argument('directory');collection.add_argument('--run-ids',nargs='+',required=True)
    collection.add_argument('--label',required=True)


def execute(args,store):
    root=Path(args.directory)
    if args.semantic_command.startswith('watch-'):
        from . import semantic_watch
        if args.semantic_command in {'watch-init','watch-budget'}:
            allowance={'jev_requests':args.max_new_calls,'candidate_requests':args.max_candidate_calls,'input_bytes':args.max_input_bytes}
            if args.semantic_command=='watch-init':
                options=workspace.read(args.workspace_options) if args.workspace_options else {}
                if args.behavior_links:
                    if not isinstance(options,dict):raise InputError('Workspace options must be a JSON object')
                    for key,value in semantic_watch.behavior_options().items():
                        if key in options and options[key]!=value:raise InputError('Behavior links conflict with '+key)
                        options[key]=value
                if args.feedback_references:
                    from .semantic_layers import FEEDBACK_PROFILE,profile
                    if not isinstance(options,dict):raise InputError('Workspace options must be a JSON object')
                    profile(options.get('feedback_profile'))
                    options={**options,'feedback_profile':FEEDBACK_PROFILE}
                if args.requested_conditions:
                    from .semantic_layers import REQUESTED_PROFILE,requested_profile
                    if not isinstance(options,dict):raise InputError('Workspace options must be a JSON object')
                    requested_profile(options.get('requested_profile'))
                    options={**options,'requested_profile':REQUESTED_PROFILE}
                result=semantic_watch.initialize(store,root,experiment=args.experiment,label=args.label,allowance=allowance,
                    workspace_options=options,live_prefixes=args.live_prefixes,
                    command=args.candidate_command,producer=args.candidate_producer,citation_format=args.candidate_citation_format)
            else:result=semantic_watch.set_allowance(store,root,allowance)
        elif args.semantic_command=='watch-status':result=semantic_watch.status(store,root)
        elif args.semantic_command=='watch-refresh':
            from .semantic_refresh import refresh
            result=refresh(store,root)
        else:
            import math,time
            from .jev import JevClient
            if not math.isfinite(args.poll_seconds) or args.poll_seconds<1:
                raise InputError('Poll interval must be at least one second')
            client=JevClient();retries=args.retry_run;previous=None
            while True:
                result=semantic_watch.run_once(store,root,client.transport,command=args.candidate_command,
                    max_rollouts=args.max_rollouts,max_pending=args.max_pending,retry_runs=retries)
                retries=[]
                if not args.follow:break
                # Emit changes rather than repeating an unchanged status each poll.
                compact={k:v for k,v in result.items() if k!='jobs'}
                if compact!=previous:
                    print(json.dumps(compact,ensure_ascii=False),flush=True);previous=compact
                time.sleep(args.poll_seconds)
    elif args.semantic_command=='bind-work':
        from . import contribution_work,graph_store
        if args.graph:
            graph=graph_store.read(store,args.graph);run=store.get(graph['run_id'],raw=True)['run']
            contribution_work.initialize(root,run,graph)
        if args.prepare_only:
            run,graph,units=contribution_work.load(root)
            result={'units':len(units),'source_hash':graph['source_hash'],'provider_calls':0}
        elif args.preflight:result=contribution_work.preflight(root,cache_directories=args.cache_from)
        elif args.audit_only:
            run,graph,units=contribution_work.load(root)
            result=contribution_work.validate_selection(graph,contribution_work.read(root/'document.json'))
        elif args.register:result=contribution_work.register(store,root)
        else:
            from .jev import JevClient
            client=JevClient();prompted=False
            def transport(req):
                nonlocal prompted
                if args.prompt_key and not prompted:
                    os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
                return client.transport(req)
            result=contribution_work.execute(root,transport,max_calls=args.max_new_calls,max_input_bytes=args.max_input_bytes,cache_directories=args.cache_from)
    elif args.semantic_command=='repair-content':
        from . import semantic_content_repair as repair
        if args.from_directory:
            if not args.run_id or not args.unit_id:raise InputError('Provide --run-id and --unit-id with --from-directory')
            repair.initialize(root,args.from_directory,args.run_id,args.unit_id)
        elif args.run_id or args.unit_id:raise InputError('Content-repair source and units are frozen; resume with only the directory')
        if args.prepare_only:result=repair.prepare(root)
        elif args.audit_only:result=repair.audit(root)
        else:
            from .jev import JevClient
            client=JevClient();prompted=False
            def transport(req):
                nonlocal prompted
                if args.prompt_key and not prompted:
                    os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
                return client.transport(req)
            result=repair.execute(root,transport,max_calls=args.max_new_calls,max_input_bytes=args.max_input_bytes)
    elif args.semantic_command=='refine-targets':
        from . import work_target_refinement as refinement
        if args.from_directory:
            if not args.run_id:raise InputError('Provide --run-id with --from-directory')
            refinement.initialize(root,args.from_directory,args.run_id)
        elif args.run_id:raise InputError('Target-refinement source is frozen; resume with only the directory')
        if args.prepare_only:result=refinement.prepare(root)
        elif args.audit_only:result=refinement.audit(root)
        else:
            from .jev import JevClient
            client=JevClient();prompted=False
            def transport(req):
                nonlocal prompted
                if args.prompt_key and not prompted:
                    os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
                return client.transport(req)
            result=refinement.execute(root,transport,max_calls=args.max_new_calls,max_input_bytes=args.max_input_bytes)
    elif args.semantic_command=='rebuild-history':
        from . import semantic_history
        if args.from_directory:
            if not args.run_id:raise InputError('Provide --run-id with --from-directory')
            config=semantic_history.initialize(root,args.from_directory,args.run_id,args.reuse_decisions_from,args.action_target_version or 'action-target-correspondence/4',
                                               reference_rule=args.feedback_reference_rule or 'assessment-reference-boundaries/2',linkage_version=args.feedback_linkage,
                                               retrieval_version=args.feedback_retrieval,scope_version=args.feedback_scope)
        elif args.run_id or args.reuse_decisions_from or args.action_target_version or args.feedback_reference_rule or args.feedback_linkage or args.feedback_retrieval or args.feedback_scope:raise InputError('History settings are frozen; supply --from-directory to initialize/check them')
        else:config=semantic_history.load(root)[0]
        if args.prepare_only:
            from .feedback_assessments import preflight
            _,frozen,extraction=semantic_history.load(root)
            result={'status':'prepared','configuration':config,'provider_calls':0,
                    'feedback_preflight':preflight(frozen,extraction,**config['feedback_protocol'])}
        elif args.audit_only:result=semantic_history.audit(root)
        else:
            from .jev import JevClient
            client=JevClient();prompted=False
            def transport(req):
                nonlocal prompted
                if args.prompt_key and not prompted:
                    os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
                return client.transport(req)
            result=semantic_history.execute(root,transport,max_calls=args.max_new_calls,max_input_bytes=args.max_input_bytes)
    elif args.semantic_command=='revise':
        from . import semantic_revision as revision
        if args.plan_links and (args.prepare_only or args.audit_only):raise InputError('--plan-links requires execution, not --prepare-only or --audit-only')
        if args.from_directory:
            if not args.run_id or not args.activity_routing:raise InputError('Provide --run-id and --activity-routing with --from-directory')
            revision.initialize(root,args.from_directory,args.run_id,args.activity_routing)
        elif args.run_id or args.activity_routing:raise InputError('Revision settings are frozen; supply --from-directory to initialize/check them')
        if args.prepare_only:result=revision.prepare(root)
        elif args.audit_only:result=revision.audit(root)
        else:
            from .jev import JevClient
            client=JevClient();prompted=False
            def transport(req):
                nonlocal prompted
                if args.prompt_key and not prompted:
                    os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
                return client.transport(req)
            result=revision.execute(root,transport,max_calls=args.max_new_calls,max_input_bytes=args.max_input_bytes)
            if args.plan_links and result['status']=='complete_local_extraction':
                used=result['budget_used']
                result['plan_links']=revision.rebuild_plan_links(root,transport,
                    max_calls=args.max_new_calls-used['jev_requests'],
                    max_input_bytes=args.max_input_bytes-used['input_bytes'])
    elif args.semantic_command=='prepare':
        if args.run_id:
            policy=workspace.read(args.context_policy) if args.context_policy else None
            from .semantic_layers import REQUESTED_PROFILE
            workspace.initialize(root,store.get(args.run_id,raw=True)['run'],
                                 include_user=not args.agent_only,context_policy=policy,
                                 activity_routing=args.activity_routing or ACTIVITY_ROUTING,
                                 reading_protocol=args.reading_protocol or 'contribution-readings/1',
                                 partition_standard=args.partition_standard or workspace.PARTITION_CANDIDATE_STANDARD,
                                 requested_profile=REQUESTED_PROFILE if args.requested_conditions else None)
        elif args.agent_only or args.context_policy or args.activity_routing or args.reading_protocol or args.partition_standard or args.requested_conditions or not (root/'workspace.json').exists():
            raise InputError('Provide --run-id to initialize or check a source-bound configuration')
        result=workspace.prepare(root)
    elif args.semantic_command=='run':
        from .jev import JevClient
        client=JevClient()
        prompted=False
        def transport(request):
            nonlocal prompted
            if args.prompt_key and not prompted:
                os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
                prompted=True
            return client.transport(request)
        def progress(record):
            print(json.dumps({'windows_processed':len(record['windows']),
                              'units_selected':sum(u['status']=='selected' for u in record['units'])}),flush=True)
        result=workspace.execute(root,transport,command=args.candidate_command,
                                 producer=args.candidate_producer,progress=progress,
                                 citation_format=args.candidate_citation_format,
                                 budget_limits={'jev_requests':args.max_new_calls,
                                                'candidate_requests':args.max_candidate_calls,
                                                'input_bytes':args.max_input_bytes})
    elif args.semantic_command=='register-collection':
        from .semantic_collection import register
        with workspace.exclusive(root):result=register(store,root,args.run_ids,args.label)
    elif args.semantic_command=='status':result=workspace.status(root)
    elif args.semantic_command=='audit':result=workspace.audit(root)
    else:
        from .semantic_catalog import register
        rid=args.run_id
        if not rid:
            if (root/'history-rebuild.json').exists():
                from .semantic_history import load
            elif (root/'revision.json').exists():
                from .semantic_revision import load
            elif (root/'target-refinement.json').exists():
                from .work_target_refinement import load
            elif (root/'content-repair.json').exists():
                from .semantic_content_repair import load
            else:load=workspace.load
            rid=load(root)[0]['run_id']
        with workspace.exclusive(root):
            result=register(store,root,rid,args.label,action_target_version=args.action_target_version,
                            method_directory=args.method_directory)
    print(json.dumps(result,ensure_ascii=False,indent=2))
