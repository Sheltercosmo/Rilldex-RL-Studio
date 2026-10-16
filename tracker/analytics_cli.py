"""Headless entry points for saved-data analysis, separate from ingestion."""
import json
from pathlib import Path
from .analytics import Analysis, DEFAULT_TABLES, EXPORT_PROFILES, FEEDS, VIEWS


def configure(commands):
    p=commands.add_parser('analysis',help='Query data, run saved-evidence analyses, export databases or follow results; no implicit model calls')
    sub=p.add_subparsers(dest='analysis_command',required=True)
    from .workspace_analysis import FUNCTIONS
    compute=sub.add_parser('compute',help='Analyze the live workspace with the same scoped functions as the UI; no export')
    compute.add_argument('function',choices=FUNCTIONS)
    compute.add_argument('--experiment');compute.add_argument('--observer')
    compute.add_argument('--history',action='store_true');compute.add_argument('--limit',type=int,default=1000)
    sub.add_parser('catalog',help='Show stable table views, columns and row meanings')
    sub.add_parser('operations',help='List built-in deterministic analyses and their evidence requirements')
    executions=sub.add_parser('execution-summary',help='Summarize reported workload mix, unfinished attempts and measured latency')
    executions.add_argument('--experiment',required=True)
    executions.add_argument('--kind',choices=('rollout','inference','environment','verification'),default='rollout')
    executions.add_argument('--group-by',action='append',help='Execution context field; repeat to retain environment/backend/model distinctions')
    executions.add_argument('--limit',type=int,default=100000)
    project=sub.add_parser('run',help='Run/resume a built-in analysis using an explicit source and saved graph')
    project.add_argument('operation');project.add_argument('--run-id',required=True);project.add_argument('--graph-id')
    project.add_argument('--parameters-file');project.add_argument('--check',action='store_true')
    plan=sub.add_parser('plan',help='Execute a JSON dependency plan, or validate it without writes')
    plan.add_argument('file');plan.add_argument('--check',action='store_true')
    saved=sub.add_parser('saved',help='Read an exact saved analysis plan and its outputs')
    saved.add_argument('plan_id')
    sub.add_parser('saved-plans',help='List retained plans for programmatic access to exact outputs')
    results=sub.add_parser('results',help='Read/export your custom result database without the original workspace')
    results.add_argument('results_db')
    access=results.add_subparsers(dest='results_command',required=True)
    batches=access.add_parser('batches',help='List batches, completion state and failures')
    batches.add_argument('--limit',type=int,default=1000);batches.add_argument('--before',type=int)
    batch=access.add_parser('batch',help='Read a batch definition and progress counts');batch.add_argument('batch_id')
    rows=access.add_parser('rows',help='Read retained inputs/results, including failed and pending rows')
    rows.add_argument('batch_id');rows.add_argument('--limit',type=int,default=1000);rows.add_argument('--after',type=int,default=-1)
    custom_sql=access.add_parser('sql',help='Run read-only SQL against research_* tables')
    custom_input=custom_sql.add_mutually_exclusive_group(required=True)
    custom_input.add_argument('--query');custom_input.add_argument('--file')
    custom_sql.add_argument('--parameters',default='[]');custom_sql.add_argument('--limit',type=int,default=1000)
    custom_export=access.add_parser('export',help='Export one exact batch as JSONL + manifest in a new ZIP')
    custom_export.add_argument('batch_id');custom_export.add_argument('destination')
    custom_export.add_argument('--max-bytes',type=int,default=100*1024**2)
    database=sub.add_parser('database',help='Create a portable, indexed SQLite research dataset for your own tools')
    database.add_argument('destination');database.add_argument('--experiment');database.add_argument('--observer')
    database.add_argument('--history',action='store_true');database.add_argument('--include-sources',action='store_true')
    database.add_argument('--max-rows',type=int,default=1000000)
    options=sub.add_parser('options',help='List recorded experiments and observation sets')
    options.add_argument('--experiment');options.add_argument('--history',action='store_true')
    table=sub.add_parser('table',help='Read a bounded table; missing values retain their status and reason')
    table.add_argument('table',choices=VIEWS);table.add_argument('--experiment');table.add_argument('--history',action='store_true')
    table.add_argument('--observer');table.add_argument('--limit',type=int,default=1000)
    query=sub.add_parser('sql',help='Execute a local read-only SELECT/WITH query against rl_* views')
    source=query.add_mutually_exclusive_group(required=True);source.add_argument('--query');source.add_argument('--file')
    query.add_argument('--parameters',default='[]',help='JSON positional list or named parameter object');query.add_argument('--limit',type=int,default=1000)
    export=sub.add_parser('export',help='Export consistent relational tables and a manifest into a new ZIP')
    export.add_argument('destination');selection=export.add_mutually_exclusive_group()
    selection.add_argument('--table',action='append',choices=VIEWS);selection.add_argument('--profile',choices=EXPORT_PROFILES)
    export.add_argument('--format',choices=('jsonl','csv'),default='jsonl');export.add_argument('--experiment')
    export.add_argument('--history',action='store_true');export.add_argument('--max-rows',type=int,default=100000)
    export.add_argument('--observer')
    feed=sub.add_parser('changes',help='Read append-only receipts; save the returned cursor after processing')
    feed.add_argument('--feed',choices=FEEDS,default='sources');feed.add_argument('--cursor-file');feed.add_argument('--limit',type=int,default=100)
    sync=sub.add_parser('sync',help='Durably mirror feed receipts and cursors into a separate local SQLite database')
    sync.add_argument('destination');sync.add_argument('--feed',action='append',choices=FEEDS)
    mode=sync.add_mutually_exclusive_group();mode.add_argument('--follow',action='store_true');mode.add_argument('--status',action='store_true')
    sync.add_argument('--limit',type=int,default=100);sync.add_argument('--pages',type=int,default=1)
    sync.add_argument('--interval',type=float,default=2)


def run(args):
    if args.analysis_command=='compute':
        from .workspace_analysis import Workspace
        result=Workspace(args.db,experiment=args.experiment,observer=args.observer,history=args.history).analyze(args.function,limit=args.limit)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.analysis_command=='operations':
        from .research import Analyzer
        print(json.dumps(Analyzer.operations(),ensure_ascii=False,indent=2));return
    if args.analysis_command=='results':
        from .research import Results
        saved=Results(args.results_db)
        if args.results_command=='batches': result=saved.batches(limit=args.limit,before=args.before)
        elif args.results_command=='batch': result=saved.batch(args.batch_id)
        elif args.results_command=='rows': result=saved.results(args.batch_id,limit=args.limit,after=args.after)
        elif args.results_command=='export': result=saved.export(args.batch_id,args.destination,max_bytes=args.max_bytes)
        else:
            sql=Path(args.file).read_text(encoding='utf-8-sig') if args.file else args.query
            result=saved.query(sql,json.loads(args.parameters),limit=args.limit)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    a=Analysis(args.db)
    if args.analysis_command=='catalog': result=a.catalog()
    elif args.analysis_command=='execution-summary':
        from .execution_records import DEFAULT_GROUPS
        result=a.execution_summary(experiment=args.experiment,kind=args.kind,
            group_by=args.group_by or DEFAULT_GROUPS,limit=args.limit)
    elif args.analysis_command in {'run','plan','saved','saved-plans'}:
        from .research import Analyzer
        analyzer=Analyzer(args.db)
        if args.analysis_command=='run':
            params=json.loads(Path(args.parameters_file).read_text(encoding='utf-8-sig')) if args.parameters_file else None
            result=analyzer.run(args.operation,args.run_id,graph_id=args.graph_id,parameters=params,check=args.check)
        elif args.analysis_command=='plan':result=analyzer.execute(json.loads(Path(args.file).read_text(encoding='utf-8-sig')),check=args.check)
        elif args.analysis_command=='saved':result=analyzer.saved(args.plan_id)
        else:result=analyzer.saved_plans()
    elif args.analysis_command=='database':result=a.database(args.destination,experiment=args.experiment,observer=args.observer,
        history=args.history,include_sources=args.include_sources,max_rows=args.max_rows)
    elif args.analysis_command=='options':result=a.options(experiment=args.experiment,history=args.history)
    elif args.analysis_command=='table': result=a.table(args.table,experiment=args.experiment,history=args.history,observer=args.observer,limit=args.limit)
    elif args.analysis_command=='sql':
        sql=Path(args.file).read_text(encoding='utf-8-sig') if args.file else args.query
        result=a.query(sql,json.loads(args.parameters),limit=args.limit)
    elif args.analysis_command=='export': result=a.export(args.destination,tables=args.table or EXPORT_PROFILES.get(args.profile,DEFAULT_TABLES),format=args.format,experiment=args.experiment,history=args.history,observer=args.observer,max_rows=args.max_rows)
    elif args.analysis_command=='sync':
        import time
        from .analysis_mirror import FeedMirror
        from .schema import InputError
        if not .2<=args.interval<=300:raise InputError('Poll interval must be between 0.2 and 300 seconds')
        if args.status and not Path(args.destination).expanduser().is_file():raise InputError('Result mirror does not exist; run sync first')
        mirror=FeedMirror(a,args.destination)
        if args.status:result=mirror.status()
        else:
            first=True
            try:
                while True:
                    result=mirror.sync(feeds=args.feed,limit=args.limit,pages=args.pages)
                    if not args.follow:break
                    if first or any(f['inserted'] for f in result['feeds']):print(json.dumps(result,ensure_ascii=False),flush=True)
                    first=False
                    if not result['has_more']:time.sleep(args.interval)
            except KeyboardInterrupt:result={**mirror.status(),'state':'stopped'}
    else:
        cursor=json.loads(Path(args.cursor_file).read_text(encoding='utf-8-sig')) if args.cursor_file else None
        result=a.changes(args.feed,cursor=cursor,limit=args.limit)
    print(json.dumps(result,ensure_ascii=False,indent=2))
