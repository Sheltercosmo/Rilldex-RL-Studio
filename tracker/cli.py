from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
from pathlib import Path

from .adapters import FORMATS, normalize
from .schema import InputError
from .store import Store


def main(argv=None, *, _metadata=None):
    import sys
    # Pipes and files are a public JSON interface. Windows locale encodings can
    # fail after a successful mutation (e.g. restoring to a Unicode path), or
    # produce bytes that a UTF-8 consumer cannot read. Leave interactive consoles
    # and caller-supplied StringIO streams alone.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    from . import __version__
    parser = argparse.ArgumentParser(prog="rilldex", description="Rilldex — RL Behavior Inspector. Inspect training signals, behavior maps and source evidence.")
    parser.add_argument('--version', action='version', version=f'Rilldex {__version__}')
    parser.add_argument("--db", default=".tracker/tracker.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser('record', help='Capture console logs, environment and hardware from any training command')
    record.add_argument('--name', required=True)
    record.add_argument('--project', default='default')
    record.add_argument('--experiment', help='Attach to an existing experiment identity')
    record.add_argument('--producer', help='Stable worker identity')
    record.add_argument('--endpoint', help='Collector URL; uses a durable outbox')
    record.add_argument('--offline', action='store_true', help='Only queue locally; transfer the outbox later')
    record.add_argument('--encoding', default='utf-8', help='Child console encoding (default: utf-8)')
    record.add_argument('--outbox', default='.rilldex/record-outbox.sqlite')
    record.add_argument('--no-hardware', action='store_true')
    record.add_argument('--interval', type=float, default=10)
    record.add_argument('argv', nargs=argparse.REMAINDER)
    launch = commands.add_parser('launch', help='Run a reusable launch file; paths are relative to the file, not the terminal')
    launch.add_argument('path')
    launch_mode=launch.add_mutually_exclusive_group()
    launch_mode.add_argument('--check',action='store_true',help='Check installation and a source sample without changing the workspace')
    launch_mode.add_argument('--once',action='store_true',help='Replay available output and exit; repeat for staged batches')
    launch.add_argument('--port',type=int,help='Override the saved port; 0 selects a free port')
    launch.add_argument('--open',action='store_true',help='Open the local browser when starting live capture')
    start = commands.add_parser('start', help='Start the application and optionally resume a managed data connection')
    start.add_argument('--port', type=int, default=8765, help='Local port; use 0 to select an available port')
    start.add_argument('--container', action='store_true', help='Listen inside a container; publish the same port on host 127.0.0.1 only')
    start.add_argument('--open', action='store_true', help='Open the local browser after startup (omit on a remote host)')
    start.add_argument('--watch', metavar='DIRECTORY', help='Existing output directory; it can be empty before training starts')
    start.add_argument('--producer', help='Stable job/worker identity; required with --watch')
    start.add_argument('--mode', choices=('native','exports','snapshots'), default='native')
    start.add_argument('--format', choices=FORMATS, default='auto')
    start.add_argument('--experiment')
    start.add_argument('--metadata', help='JSON defaults; keep changing step/policy coordinates in the records')
    start.add_argument('--pattern', help='Filename glob; defaults to *.jsonl for exports or *.json for snapshots')
    start.add_argument('--interval', type=float, default=2)
    start.add_argument('--snapshot-state', choices=('in_progress','complete'), default='in_progress')
    doctor = commands.add_parser('doctor', help='Check installation, local storage and port; no model calls')
    doctor.add_argument('--port', type=int, default=8765)
    discover = commands.add_parser('discover', help='Inspect output and suggest a capture layout; no database or model calls')
    discover.add_argument('root', help='Directory on this host or S3/GCS prefix')
    setup = commands.add_parser('setup', help='Print a use-case launch plan; does not change or start anything')
    setup.add_argument('--case', choices=('local','remote','docker','cloud','notebook','offline'), default='local')
    setup.add_argument('--shell', choices=('posix','powershell'), default='posix')
    setup.add_argument('--collector-shell',choices=('posix','powershell'),default='posix',help='Remote host shell; independent of workstation --shell')
    setup.add_argument('--stage', choices=('before','during','after'), default='during')
    setup.add_argument('--mode', choices=('native','exports','snapshots'), default='native')
    setup.add_argument('--format', choices=FORMATS, default='auto', help='Record schema, independent of the file layout')
    setup.add_argument('--root'); setup.add_argument('--experiment'); setup.add_argument('--producer')
    setup.add_argument('--pattern', help='Optional JSON/JSONL filename glob, including a discovered filter')
    setup.add_argument('--host'); setup.add_argument('--port', type=int, default=8765)
    setup.add_argument('--snapshot-state',choices=('in_progress','complete'),default='in_progress',help='Explicit meaning of raw JSON snapshots; training stage does not establish completion')
    setup.add_argument('--save-launch',help='Save a reusable launch file to a new path (local, remote or cloud setup)')
    workspace = commands.add_parser('workspace', help='Snapshot or restore recorded maps, measurements and observations')
    workspace_commands = workspace.add_subparsers(dest='workspace_command', required=True)
    workspace_commands.add_parser('snapshot', help='Create a new portable inspection archive; no inference').add_argument('path')
    workspace_commands.add_parser('inspect', help='Verify an archive and show its manifest without restoring').add_argument('path')
    workspace_commands.add_parser('restore', help='Restore into a new --db path; collection and inference stay paused').add_argument('path')
    workspace_commands.add_parser('list', help='List recent local workspaces and their server status')
    workspace_add=workspace_commands.add_parser('add', help='Add an existing workspace to the local picker')
    workspace_add.add_argument('path')
    workspace_add.add_argument('--name', help='Readable name in the workspace picker')
    continuations = commands.add_parser('continuation-studies', help='Import or inspect recorded prefix-continuation experiments')
    continuation_commands = continuations.add_subparsers(dest='continuation_command', required=True)
    continuation_commands.add_parser('import').add_argument('path')
    continuation_view = continuation_commands.add_parser('view')
    continuation_view.add_argument('--experiment')
    continuation_view.add_argument('--environment')
    continuation_view.add_argument('--limit', type=int, default=20)
    continuation_view.add_argument('--offset', type=int, default=0)
    tool_checks = commands.add_parser('inspect-tools', help='Check recorded tool parameter schemas offline; no model calls')
    tool_checks.add_argument('run_ids', nargs='*')
    tool_checks.add_argument('--all', action='store_true', help='Inspect every current rollout snapshot')
    tool_checks.add_argument('--details', action='store_true', help='Include individual calls, constraint paths and unavailable reasons')
    server = commands.add_parser("serve", help="Open the local research application")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument('--container', action='store_true', help='Container listener; publish to host loopback only')
    server.add_argument("--prompt-key", action="store_true", help="Read Jev key without echo; retain only in this server process")
    outbox = commands.add_parser('outbox', help='Inspect or resume delivery from a durable training outbox')
    outbox.add_argument('path')
    outbox.add_argument('--producer', required=True)
    outbox.add_argument('--endpoint', default='http://127.0.0.1:8765')
    outbox.add_argument('--send', action='store_true', help='Deliver pending snapshots; default only shows status')
    outbox.add_argument('--retry-blocked', action='store_true', help='Retry unchanged blocked payloads after fixing the receiving server or configuration')
    outbox.add_argument('--limit', type=int, default=100)
    capture = commands.add_parser('capture', help='Move offline worker packets without a running server')
    capture_commands = capture.add_subparsers(dest='capture_command', required=True)
    capture_export = capture_commands.add_parser('export', help='Copy outstanding outbox packets into a portable bundle')
    capture_export.add_argument('outbox'); capture_export.add_argument('destination')
    capture_commands.add_parser('inspect', help='Validate every packet without importing').add_argument('path')
    capture_import = capture_commands.add_parser('import', help='Receive bundles with the same identities as HTTP delivery')
    capture_import.add_argument('paths', nargs='+')
    capture_import.add_argument('--receipt', help='Write acknowledgment for one bundle; return this file to its original worker')
    capture_ack = capture_commands.add_parser('acknowledge', help='Clear only outbox packets with matching receiving-workspace receipts')
    capture_ack.add_argument('outbox'); capture_ack.add_argument('receipt')
    ingest = commands.add_parser("import", help="Import complete JSON trajectories, native result bundles or JSONL batches")
    ingest.add_argument("paths", nargs="+")
    ingest.add_argument("--format", choices=FORMATS, default="auto")
    ingest.add_argument("--metadata", help="JSON sidecar with explicit task and training provenance")
    ingest.add_argument("--grading", help="Explicit matching _rewards.json for one SWE RL messages file")
    snapshot = commands.add_parser("ingest", help="Append a producer's explicitly identified rollout revision")
    snapshot.add_argument("path")
    snapshot.add_argument("--producer", required=True)
    snapshot.add_argument("--rollout-id", required=True)
    snapshot.add_argument("--revision", type=int, required=True)
    snapshot.add_argument("--state", choices=("in_progress", "complete", "failed"), required=True)
    snapshot.add_argument("--format", choices=FORMATS, default="auto")
    snapshot.add_argument("--metadata")
    training=commands.add_parser('training-records',help='Import immutable training facts or inspect joined populations')
    training_sub=training.add_subparsers(dest='training_command',required=True)
    training_import=training_sub.add_parser('import');training_import.add_argument('path')
    training_view=training_sub.add_parser('view')
    for field in ('experiment','environment','monitor'):training_view.add_argument('--'+field)
    recipes=commands.add_parser('training-recipes',help='Import or inspect pinned training recipe declarations')
    recipes_sub=recipes.add_subparsers(dest='recipe_command',required=True)
    recipes_sub.add_parser('import').add_argument('path')
    recipes_sub.add_parser('view').add_argument('--experiment')
    setup=commands.add_parser('training-setup',help='Read resolved RL settings and suggest relevant monitors; no inference or writes')
    setup.add_argument('path',help='JSON with framework, version, resolved and config')
    preflight=commands.add_parser('check',help='Check snapshot evidence and supported functions without a database or inference')
    preflight.add_argument('path')
    preflight.add_argument('--format',choices=FORMATS,default='auto')
    preflight.add_argument('--metadata')
    watch = commands.add_parser("watch", help="Collect native job outputs or replay/follow JSONL exports")
    watch.add_argument("root")
    watch.add_argument("--producer", required=True)
    watch.add_argument("--format", choices=FORMATS, default="auto")
    watch.add_argument('--mode', choices=('native','exports','snapshots'), default='native')
    watch.add_argument('--pattern', help='Filename glob; defaults to *.jsonl for exports or *.json for snapshots')
    watch.add_argument('--experiment')
    watch.add_argument('--max-records', type=int, default=100, help='Export rows per file per poll')
    watch.add_argument("--metadata", help="JSON defaults; per-rollout tracking.json sidecars take precedence")
    watch.add_argument("--task-root", help="Optional explicitly authorized root for task.toml/instruction.md")
    watch.add_argument("--interval", type=float, default=2.0)
    watch.add_argument("--max-files", type=int, default=1000)
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--check", action="store_true", help="Validate a bounded sample without importing or calling models")
    watch.add_argument("--snapshot-state", choices=("in_progress","complete"), default="in_progress")
    export = commands.add_parser("export", help="Export a run, immutable source and derived observations")
    export.add_argument("run_id"); export.add_argument("output")
    observe = commands.add_parser("observe", help="Run a bounded semantic observation pass against Jev")
    observe.add_argument("run_id")
    observe.add_argument("--limit", type=int, default=20)
    observe.add_argument("--prompt-key", action="store_true", help="Read the key without echo; never save it")
    activity = commands.add_parser("observe-activities", help="Classify source spans and dispatches with the semantic activity harness")
    activity.add_argument("run_id")
    activity.add_argument("--limit", type=int, default=20)
    activity.add_argument("--prompt-key", action="store_true")
    commands.add_parser("list")
    commands.add_parser("reindex", help="Recompute observations from preserved evidence after a harness update")
    reselect = commands.add_parser("reselect", help="Preview argmax selection from exact saved distributions, without API calls")
    reselect.add_argument("--apply", action="store_true", help="Append new decisions, preserving all original observations")
    commands.add_parser("contracts", help="Show metric definitions, evidence requirements and validation status")
    capabilities = commands.add_parser("capabilities", help="Show which measurement evidence is available in a saved run")
    capabilities.add_argument("run_id")
    reference = commands.add_parser("reference", help="Prepare and evaluate an independent reference benchmark")
    reference_commands = reference.add_subparsers(dest="reference_command", required=True)
    prepare = reference_commands.add_parser("prepare", help="Write prediction-blind cases, frozen predictions and empty labels")
    prepare.add_argument("output")
    prepare.add_argument("--run-id", action="append", help="Repeat to select runs; defaults to all latest runs")
    prepare.add_argument("--group-map", help="JSON run-ID map with group, split and exposure; defaults to development")
    prepare.add_argument("--per-run", type=int, default=12, help="Uniform action sample per rollout; 0 includes every action")
    prepare.add_argument("--seed", default="reference-pilot-1")
    evaluate = reference_commands.add_parser("evaluate", help="Score explicit reference labels; missing references yield no accuracy claim")
    evaluate.add_argument("directory")
    evaluate.add_argument("--labels")
    evaluate.add_argument("--predictions")
    evaluate.add_argument("--split", choices=("development", "holdout"), default="holdout")
    evaluate.add_argument("--output", help="Optional JSON report; use a new path to preserve previous results")
    activity_reference = commands.add_parser("activity-reference", help="Prepare blind multi-label reviews and evaluate agreement/adjudication")
    ar_commands = activity_reference.add_subparsers(dest="reference_command", required=True)
    ar_prepare = ar_commands.add_parser("prepare")
    ar_prepare.add_argument("output")
    ar_prepare.add_argument("--run-id", action="append")
    ar_prepare.add_argument("--group-map")
    ar_prepare.add_argument("--selected-units", help="Optional frozen run-ID to unit-ID list map")
    ar_prepare.add_argument("--per-kind", type=int, default=6)
    ar_prepare.add_argument("--seed", default="activity-reference-1")
    ar_evaluate = ar_commands.add_parser("evaluate")
    ar_evaluate.add_argument("directory")
    ar_evaluate.add_argument("--annotations", action="append", help="Repeat for independent reviewers and adjudication files")
    ar_evaluate.add_argument("--split", choices=("development", "holdout"), default="holdout")
    ar_evaluate.add_argument("--output")
    ar_evaluate.add_argument("--html", help="Optional interactive inspection report; exposes predictions and requires a new output path")
    components=commands.add_parser('activity-components',help='Import and inspect separately versioned saved component results; no inference')
    component_commands=components.add_subparsers(dest='component_command',required=True)
    component_import=component_commands.add_parser('import');component_import.add_argument('directory');component_import.add_argument('--name')
    component_commands.add_parser('list')
    from .semantic_cli import configure as configure_semantic
    configure_semantic(commands)
    from .operation_cli import configure as configure_outcomes
    configure_outcomes(commands)
    from .work_item_cli import configure as configure_work_items
    configure_work_items(commands)
    from .diagnostic_cli import configure as configure_monitors
    configure_monitors(commands)
    from .diagnostic_worker_cli import configure as configure_monitor_worker
    configure_monitor_worker(commands)
    from .feedback_cli import configure as configure_feedback
    configure_feedback(commands)
    from .slime_debug_cli import configure as configure_slime
    configure_slime(commands)
    from .analytics_cli import configure as configure_analysis
    configure_analysis(commands)
    from .workflow_cli import configure as configure_workflow
    configure_workflow(commands)
    from .telemetry_cli import configure as configure_telemetry
    configure_telemetry(commands)
    args = parser.parse_args(argv)
    # Setup describes paths on a possibly different host; preserve its spelling.
    if args.command!='setup':args.db = str(Path(args.db).expanduser())
    try:
        if args.command == 'record':
            from rilldex.run import record_command
            from .capture import Outbox
            import platform
            outbox=Outbox(args.outbox,endpoint=args.endpoint or 'http://127.0.0.1:8765',producer=args.producer or platform.node() or 'local') if args.endpoint or args.offline else None
            if outbox and not args.offline: outbox.start()
            try:
                code=record_command(args.argv,name=args.name,project=args.project,experiment=args.experiment,
                    producer=args.producer,workspace=args.db,target=outbox,hardware=not args.no_hardware,interval=args.interval,encoding=args.encoding)
            finally:
                if outbox:
                    if not args.offline: outbox.drain()
                    status=outbox.close()
                    if status.get('pending') or status.get('blocked'): print('Rilldex: undelivered records retained in '+args.outbox,file=sys.stderr)
            if code: parser.exit(code if code>0 else 1)
            return
        if args.command == 'telemetry':
            from .telemetry_cli import run as run_telemetry
            print(json.dumps(run_telemetry(args),indent=2));return
        if args.command == 'workflow':
            from .workflow_cli import run as run_workflow
            code = run_workflow(args)
            if code: parser.exit(code)
            return
        if args.command == 'launch':
            from .launch import execute
            if args.open and (args.check or args.once):raise InputError('--open requires live launch')
            if Path(args.db) != Path('.tracker/tracker.sqlite'):raise InputError('Launch uses database from its file; edit that field instead of --db')
            code=execute(args,main)
            if code:parser.exit(code)
            return
        if args.command == 'analysis':
            from .analytics_cli import run as run_analysis
            run_analysis(args)
            return
        if args.command == 'discover':
            from .source_discovery import discover
            print(json.dumps(discover(args.root), indent=2))
            return
        if args.command == 'setup':
            from .deployment_setup import plan
            options = {k: getattr(args, k) for k in ('case','shell','collector_shell','stage','mode','format','root','experiment','producer','host','port','pattern','snapshot_state') if getattr(args, k) is not None}
            result=plan({**options, 'database': args.db})
            if args.save_launch:
                if result['launch_file'] is None:raise InputError('Launch files support local, remote-host and cloud collectors')
                with Path(args.save_launch).open('x',encoding='utf-8') as file:json.dump(result['launch_file'],file,indent=2,ensure_ascii=False)
                result['saved_launch']=str(Path(args.save_launch).resolve())
            print(json.dumps(result, indent=2))
            return
        if args.command == 'capture':
            from . import capture_bundle
            if args.capture_command == 'export':
                result = capture_bundle.export(args.outbox, args.destination)
            elif args.capture_command == 'inspect':
                result = capture_bundle.inspect(args.path)
            elif args.capture_command == 'acknowledge':
                result = capture_bundle.acknowledge(args.outbox, args.receipt)
            else:
                if args.receipt and (len(args.paths) != 1 or Path(args.receipt).exists()):
                    raise InputError('--receipt requires one bundle and a new receipt filename')
                target = Store(args.db)
                results = [capture_bundle.receive(target, path, with_receipts=bool(args.receipt)) for path in args.paths]
                if args.receipt:
                    acknowledgments = results[0].pop('acknowledgments')
                    with Path(args.receipt).open('x', encoding='utf-8') as stream:
                        json.dump({'schema':'jev-capture-receipts/1','acknowledgments':acknowledgments}, stream)
                result = {'bundles': results, 'complete': all(r['complete'] for r in results)}
            print(json.dumps(result, indent=2))
            if result.get('complete') is False:
                parser.exit(1, 'Some packets need attention. Retrying preserves accepted receipts.\n')
            return
        if args.command == 'workspace' and args.workspace_command in {'list','add'}:
            from .workspace_directory import Directory, database_path, validate_database
            directory=Directory()
            if args.workspace_command=='add':
                path=database_path(args.path)
                validate_database(path)
                result=directory.remember(path,args.name)
            else:
                result={'workspaces':directory.list(None)}
            print(json.dumps(result,indent=2,ensure_ascii=False))
            return
        if args.command == 'workspace' and args.workspace_command in {'restore','inspect'}:
            from . import workspace_snapshot
            result = workspace_snapshot.restore(args.path,args.db) if args.workspace_command == 'restore' else workspace_snapshot.inspect(args.path)
            print(json.dumps(result,indent=2,ensure_ascii=False))
            return
        if args.command == 'workspace' and not Path(args.db).is_file():
            raise InputError('Source database does not exist; use --db to select the workspace to snapshot')
        if args.command == 'doctor':
            from .startup import doctor
            report = doctor(args.db, args.port)
            print(json.dumps(report, indent=2))
            if not report['ready']:
                parser.exit(1)
            return
        if args.command in {'start','watch'}:
            if args.snapshot_state != 'in_progress' and args.mode != 'snapshots':
                raise InputError('--snapshot-state requires --mode snapshots')
            if args.pattern and args.mode == 'native':
                raise InputError('--pattern requires --mode exports or snapshots')
        if args.command == 'start':
            from .startup import doctor
            report = doctor(args.db, args.port)
            if not report['ready']:
                raise InputError('; '.join(c['name'] + ': ' + c['detail'] for c in report['checks'] if not c['ok']))
            if args.watch and not args.producer:
                raise InputError('Supply --producer for a managed output directory')
            if not args.watch and (args.producer or args.experiment or args.metadata or args.mode != 'native' or args.format != 'auto'):
                raise InputError('Capture options require --watch DIRECTORY')
        if args.command=='slime-dump':
            from .slime_debug_cli import execute
            execute(args);return
        if args.command=='training-setup':
            from .training_setup import inspect
            print(json.dumps(inspect(json.loads(Path(args.path).read_text(encoding='utf-8-sig'))),indent=2))
            return
        if args.command=='check':
            from .import_batch import read_path,preflight
            meta=json.loads(Path(args.metadata).read_text(encoding='utf-8-sig')) if args.metadata else {}
            print(json.dumps(preflight(read_path(args.path,args.format,meta)),indent=2))
            return
        if args.command=='outbox':
            from .capture import Outbox
            if not 1<=args.limit<=10000:raise InputError('Use a delivery limit of 1–10000')
            client=Outbox(args.path,producer=args.producer,endpoint=args.endpoint)
            if args.retry_blocked:client.retry_blocked()
            print(json.dumps(client.drain(args.limit) if args.send else client.status(),indent=2))
            return
        if args.command == "contracts":
            from .contracts import catalog
            print(json.dumps(catalog(), indent=2))
            return
        if args.command == "reference" and args.reference_command == "evaluate":
            from .reference import evaluate as evaluate_reference
            result = evaluate_reference(args.directory, args.labels, args.predictions, split=args.split)
            if args.output:
                with Path(args.output).open("x", encoding="utf-8") as f:
                    f.write(json.dumps(result, indent=2) + "\n")
            else:
                print(json.dumps(result, indent=2))
            return
        if args.command == "activity-reference" and args.reference_command == "evaluate":
            from .activity_reference import evaluate as evaluate_activities, render_report
            destinations = [Path(path) for path in (args.output, args.html) if path]
            if len({path.resolve() for path in destinations}) != len(destinations) or any(path.exists() for path in destinations):
                raise InputError("Use distinct new paths for reference reports; existing results are preserved")
            result = evaluate_activities(args.directory, args.annotations, split=args.split)
            if args.html:
                with Path(args.html).open("x", encoding="utf-8") as f:
                    f.write(render_report(result))
            if args.output:
                with Path(args.output).open("x", encoding="utf-8") as f:
                    f.write(json.dumps(result, indent=2) + "\n")
            else:
                print(json.dumps(result, indent=2))
            return
        store = Store(args.db)
        if args.command == 'workspace':
            from .workspace_snapshot import export as export_workspace
            print(json.dumps(export_workspace(store,args.path),indent=2,ensure_ascii=False))
            return
        if args.command == 'start':
            from .server import serve
            if args.watch:
                from .connections import create
                meta = _metadata if _metadata is not None else json.loads(Path(args.metadata).read_text(encoding='utf-8-sig')) if args.metadata else {}
                if not isinstance(meta, dict):
                    raise InputError('Metadata must be an object')
                if args.experiment:
                    meta['experiment'] = args.experiment
                config = dict(root=args.watch,producer=args.producer,format=args.format,metadata=meta,interval=args.interval)
                if args.mode == 'exports':
                    config.update(mode='exports',pattern=args.pattern or '*.jsonl')
                elif args.mode == 'snapshots':
                    config.update(mode='snapshots',pattern=args.pattern or '*.json',snapshot_state=args.snapshot_state)
                result = create(store, config)
                print(json.dumps({'connection': result['id'], 'database': str(store.path), 'resumed': not result['created']}), flush=True)
            print('Collection uses saved source and observations. Paid inference is not started automatically.', flush=True)
            serve(store, port=args.port, open_browser=args.open, container=args.container)
            return
        if args.command=='training-recipes':
            from .training_recipes import receive,snapshot
            result=receive(store,json.loads(Path(args.path).read_text(encoding='utf-8-sig'))) if args.recipe_command=='import' else snapshot(store,args.experiment)
            print(json.dumps(result,indent=2));return
        if args.command=='training-records':
            from .training_lineage import receive,snapshot as training_snapshot
            result=receive(store,json.loads(Path(args.path).read_text(encoding='utf-8-sig'))) if args.training_command=='import' else training_snapshot(store,experiment=args.experiment,environment=args.environment,monitor=args.monitor)
            print(json.dumps(result,indent=2));return
        if args.command=='continuation-studies':
            from .continuation_studies import receive,snapshot
            result=receive(store,json.loads(Path(args.path).read_text(encoding='utf-8-sig'))) if args.continuation_command=='import' else snapshot(store,experiment=args.experiment,environment=args.environment,limit=args.limit,offset=args.offset)
            print(json.dumps(result,indent=2));return
        if args.command=='monitor-rollouts':
            from .diagnostic_worker_cli import execute as execute_monitor_worker
            execute_monitor_worker(args,store);return
        if args.command=='inspect-tools':
            from .tool_contracts import register, protocol
            if args.all and args.run_ids:raise InputError('Choose explicit run IDs or --all')
            ids=[r['id'] for r in store.list()] if args.all else args.run_ids
            if not ids:raise InputError('Supply run IDs or import rollouts before using --all')
            protocol()  # Check the optional dependency before writing any observations.
            result=[]
            for rid in dict.fromkeys(ids):
                observed=register(store,store.get(rid,raw=True)['run'])
                result.append(observed if args.details else {k:v for k,v in observed.items() if k!='inspection'}|{'run_id':rid,'counts':observed['inspection']['counts']})
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        if args.command=='monitors':
            from .diagnostic_cli import execute as execute_monitors
            execute_monitors(args,store);return
        if args.command=='work-items':
            from .work_item_cli import execute as execute_work_items
            execute_work_items(args,store);return
        if args.command=='outcomes':
            from .operation_cli import execute as execute_outcomes
            execute_outcomes(args,store);return
        if args.command=='semantic':
            from .semantic_cli import execute as execute_semantic
            execute_semantic(args,store);return
        if args.command=='activity-components':
            result=store.import_activity_components(args.directory,args.name) if args.component_command=='import' else store.activity_component_catalog()
            print(json.dumps(result,indent=2));return
        if args.command == "capabilities":
            result = store.get(args.run_id)["analysis"].get("capabilities")
            if not result:
                raise InputError("Saved view predates measurement support; run reindex first")
            print(json.dumps(result, indent=2))
        elif args.command == "serve":
            from .server import serve
            if args.prompt_key:
                os.environ["JEV_API_KEY"] = getpass.getpass("Jev key (process memory only): ")
            serve(store, port=args.port, container=args.container)
        elif args.command == "observe-activities":
            from .activity import ActivityClient, units
            if not 1 <= args.limit <= 100:
                raise InputError("Activity limit must be 1–100 units")
            if args.prompt_key:
                os.environ["JEV_API_KEY"] = getpass.getpass("Jev key (not stored): ")
            run = store.get(args.run_id, raw=True)["run"]
            client, cached = ActivityClient(), store.activity_observations(args.run_id)
            pending = [u for u in units(run) if u["eligible"] and not client.cache_matches(cached.get(u["id"], {}), run, u["id"])]
            for unit in pending[:args.limit]:
                result = client.evaluate(run, unit["id"])
                store.record_activity(args.run_id, unit["id"], result)
                print(json.dumps({"unit_id": unit["id"], "kind": unit["kind"], "saved": True}), flush=True)
            print(json.dumps({"processed": min(len(pending), args.limit), "remaining": max(0, len(pending)-args.limit)}))
        elif args.command == 'feedback-monitor':
            from .feedback_cli import execute as execute_feedback
            execute_feedback(args,store)
        elif args.command == "watch":
            from .connections import validate
            meta = _metadata if _metadata is not None else json.loads(Path(args.metadata).read_text(encoding="utf-8-sig")) if args.metadata else {}
            if not isinstance(meta, dict):
                raise InputError('Metadata must be an object')
            if args.experiment:
                meta['experiment'] = args.experiment
            config = dict(root=args.root,producer=args.producer,format=args.format,metadata=meta,
                          task_root=args.task_root,max_files=args.max_files,interval=args.interval)
            if args.mode == 'exports':
                config.update(mode='exports',pattern=args.pattern or '*.jsonl',max_records=args.max_records)
            elif args.mode == 'snapshots':
                config.update(mode='snapshots',pattern=args.pattern or '*.json',snapshot_state=args.snapshot_state)
            if args.check:
                from .connections import preview
                report = preview(store, config)
                print(json.dumps(report,ensure_ascii=False))
                if any(r['status']=='deferred' for r in report['samples']) or report.get('cloud', {}).get('errors'):
                    parser.exit(1, 'Some sampled sources need attention; no records imported.\n')
                return
            _, watcher = validate(store, config)
            # A one-off replay drains existing rows in bounded polls. Live mode
            # uses the same cursor and identities when attached later.
            from .collector_lock import ProducerLock
            with ProducerLock(store, watcher.producer):
                if args.once and (args.mode == 'exports' or '://' in args.root):
                    while True:
                        result = watcher.poll()
                        print(json.dumps(result,ensure_ascii=False),flush=True)
                        if not result['backlog']:
                            if result['deferred'] or result.get('waiting'):
                                parser.exit(1, 'Replay incomplete; inspect deferred files or append a newline to finish the last record.\n')
                            break
                else:
                    report = watcher.run(args.interval,args.once)
                    if args.once and report and report.get('deferred'):
                        parser.exit(1, 'Some sources could not be collected; inspect deferred files.\n')
        elif args.command == "ingest":
            meta = json.loads(Path(args.metadata).read_text(encoding="utf-8-sig")) if args.metadata else {}
            doc = json.loads(Path(args.path).read_text(encoding="utf-8-sig"))
            print(json.dumps(store.ingest({"document": doc, "format": args.format, "metadata": meta,
                "producer": args.producer, "rollout_id": args.rollout_id, "revision": args.revision, "state": args.state})))
        elif args.command == "import":
            if args.grading and len(args.paths) != 1:
                raise InputError("--grading requires exactly one trajectory file")
            meta = json.loads(Path(args.metadata).read_text(encoding="utf-8-sig")) if args.metadata else {}
            for name in args.paths:
                p = Path(name)
                if not args.grading:
                    from .import_batch import read_path
                    print(json.dumps({'file':p.name,'runs':store.add(read_path(p,args.format,meta))}))
                    continue
                if p.suffix.lower() == '.jsonl':
                    raise InputError('--grading is only for one SWE RL messages JSON file')
                document = json.loads(p.read_text(encoding="utf-8-sig"))
                sources = None
                if args.grading:
                    from .swe_rl import grading_source
                    sources = [grading_source(p, document, args.grading)]
                print(json.dumps({"file": p.name, "runs": store.add(normalize(document, args.format, meta, sources))}))
        elif args.command == "export":
            bundle = store.get(args.run_id, raw=True)
            bundle["observations"] = store.observations(args.run_id)
            Path(args.output).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        elif args.command == "observe":
            from .jev import JevClient, JEV_HARNESS
            if not 1 <= args.limit <= 200:
                raise InputError("Observation limit must be between 1 and 200 actions")
            if args.prompt_key:
                os.environ["JEV_API_KEY"] = getpass.getpass("Jev API key (not saved): ")
            client = JevClient()
            bundle = store.get(args.run_id, raw=True)
            cached = store.observations(args.run_id)
            pending = [a for a in bundle["analysis"]["actions"] if not
                       client.cache_matches(cached.get(a["event_id"], {}), bundle["run"], a["event_id"])]
            try:
                for action in pending[:args.limit]:
                    result = client.evaluate(bundle["run"], action["event_id"])
                    p = result["_provenance"]
                    store.record(args.run_id, action["event_id"], JEV_HARNESS, p["model"], p["packet_hash"], result)
                    print(json.dumps({"event": action["event_id"], "observations": {k: {"value": v["value"], "status": v["status"]} for k,v in result.items() if not k.startswith("_")}}), flush=True)
            finally:
                store.refresh(args.run_id)
        elif args.command == "list":
            for r in store.list():
                print(r["id"], r["metadata"].get("task_id"), r["metrics"]["actions"], "actions")
        elif args.command == "reselect":
            print(json.dumps(store.reselect_observations(apply=args.apply), indent=2))
        elif args.command == "reindex":
            for r in store.list():
                store.refresh(r["id"])
            print("Recomputed derived views; source evidence unchanged")
        elif args.command == "activity-reference":
            from .activity_reference import prepare as prepare_activities
            ids = args.run_id or [r["id"] for r in store.list()]
            groups = json.loads(Path(args.group_map).read_text(encoding="utf-8-sig")) if args.group_map else None
            selected = json.loads(Path(args.selected_units).read_text(encoding="utf-8-sig")) if args.selected_units else None
            result = prepare_activities([store.get(rid, raw=True) for rid in ids], args.output,
                                        group_map=groups, selected_units=selected, per_kind=args.per_kind, seed=args.seed)
            print(json.dumps(result, indent=2))
        elif args.command == "reference":
            from .reference import prepare as prepare_reference
            ids = args.run_id or [r["id"] for r in store.list()]
            groups = json.loads(Path(args.group_map).read_text(encoding="utf-8-sig")) if args.group_map else None
            result = prepare_reference([store.get(rid, raw=True) for rid in ids], args.output,
                                       group_map=groups, per_run=args.per_run, seed=args.seed)
            print(json.dumps(result, indent=2))
    except (InputError, KeyError, OSError, ValueError, sqlite3.Error) as e:
        parser.exit(1, str(e) + "\n")


if __name__ == "__main__":
    main()
