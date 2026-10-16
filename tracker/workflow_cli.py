"""Headless, portable capture and research workflows."""
import json
from contextlib import contextmanager
from pathlib import Path
import signal
import threading
import time

from .schema import InputError
from .workflows import Workflow, initialize, package, read, recipe


def configure(commands):
    parser = commands.add_parser('workflow', help='Package and run repeatable capture, SQL and export workflows')
    subs = parser.add_subparsers(dest='workflow_command', required=True)
    init = subs.add_parser('init', help='Create a new workflow directory; never overwrite an existing one')
    init.add_argument('directory')
    init.add_argument('--source', help='Local output directory or S3/GCS URI; omit to analyze --db')
    init.add_argument('--mode', choices=('native', 'exports', 'snapshots'), default='native')
    init.add_argument('--experiment')
    init.add_argument('--observer')
    init.add_argument('--producer', help='Stable identity for this source')
    init.add_argument('--database', help='Workspace path relative to the new workflow directory')
    init.add_argument('--publish-every', type=float, default=300, help='Seconds between dataset exports in follow mode (default: 300)')
    run = subs.add_parser('run', help='Collect available records, analyze and publish complete outputs')
    run.add_argument('path', help='Workflow directory or rilldex.json')
    modes = run.add_mutually_exclusive_group()
    modes.add_argument('--follow', action='store_true', help='Keep updating; Ctrl+C stops safely')
    modes.add_argument('--check', action='store_true', help='Validate configuration without writes or collection')
    pack = subs.add_parser('package', help='Bundle config, runner and runtime; no training data or credentials')
    pack.add_argument('path')
    pack.add_argument('destination')
    status = subs.add_parser('status', help='Read the last durable capture/publication report; no writes')
    status.add_argument('path')


@contextmanager
def stop_signals():
    """Let SIGTERM unwind open snapshots and transactions like Ctrl+C."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous=signal.getsignal(signal.SIGTERM)
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:yield
    finally:signal.signal(signal.SIGTERM,previous)


def run(args):
    if args.workflow_command == 'init':
        source = None
        if args.source:
            if not args.experiment or not args.producer:
                raise InputError('Capture requires --experiment and --producer to preserve job identity')
            root = args.source if '://' in args.source else str(Path(args.source).expanduser().resolve())
            source = dict(root=root, producer=args.producer, mode=args.mode, format='auto', metadata={'experiment': args.experiment})
        database = args.database or ('workspace/tracker.sqlite' if source else str(Path(args.db).expanduser().resolve()))
        path = initialize(args.directory, recipe(database=database, source=source, experiment=args.experiment, observer=args.observer, publish_interval=args.publish_every))
        print(json.dumps({'config': path, 'next': 'Run run.py once, or run.py --follow for continuous updates.'}))
        return 0
    if args.workflow_command == 'package':
        _, value = read(args.path)
        content = package(value)
        with Path(args.destination).open('xb') as f:
            f.write(content)
        print(json.dumps({'package': str(Path(args.destination).resolve()), 'bytes': len(content)}))
        return 0
    with Workflow(args.path) as job:
        if args.workflow_command == 'status':
            print(json.dumps(job.status(),indent=2))
            return 0
        if args.check:
            report=job.check()
            print(json.dumps(report, indent=2))
            return {'ready':0,'waiting':2,'blocked':1}[report['status']]
        previous = None
        next_publish=0
        with stop_signals(), job.session():
            try:
                while True:
                    due=not args.follow or time.monotonic()>=next_publish
                    result = job.run(publish=due,resilient=args.follow,max_polls=1 if args.follow else 100)
                    if due and (result.get('generation') or result.get('error',{}).get('stage')=='publication'):
                        next_publish=time.monotonic()+job.config.get('publish_interval',0)
                    # Print changes, not an identical receipt every polling interval.
                    encoded = json.dumps(result, sort_keys=True)
                    if encoded != previous:
                        print(encoded, flush=True)
                        previous = encoded
                    if not args.follow:
                        return 1 if result.get('health_error') else 2 if result.get('pending') or result['status'] == 'waiting' else 0
                    time.sleep(job.config.get('interval', 10))
            except KeyboardInterrupt:
                stopped=job.stopped()
                print(json.dumps({'status': 'stopped', 'resume': 'Repeat the same command to resume. Run one batch to publish any data collected since the last export.',
                                  **({'health_error':stopped['health_error']} if stopped.get('health_error') else {})}), flush=True)
    return 0
