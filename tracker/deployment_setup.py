"""Use-case setup plans. Generate instructions only; never execute commands."""
import json
import re
import shlex

from .schema import InputError
from .launch import SCHEMA as LAUNCH_SCHEMA

CASES = {
    'local': 'Existing files or a local training job',
    'remote': 'Remote GPU host / SSH',
    'docker': 'Isolated collector in Docker',
    'cloud': 'S3 / GCS output',
    'notebook': 'Colab / Jupyter notebook',
    'offline': 'Restricted cluster / offline workers',
}


def plan(value):
    if not isinstance(value, dict):
        raise InputError('Supply setup options as an object')
    case = value.get('case', 'local')
    shell = value.get('shell', 'posix')
    stage = value.get('stage', 'during')
    mode = value.get('mode', 'native')
    fmt = value.get('format', 'auto')
    from .input_catalog import catalog as input_catalog
    if not any(f['id']==fmt and (case=='offline' or mode in f['collection_modes']) for f in input_catalog()['formats']):
        raise InputError('Record schema is incompatible with this file layout. Use JSON/JSONL for common records.')
    if case not in CASES or shell not in {'posix', 'powershell'} or stage not in {'before', 'during', 'after'} or mode not in {'native', 'exports', 'snapshots'}:
        raise InputError('Unsupported setup case, shell, training stage or source layout')
    collector_shell=value.get('collector_shell','posix') if case=='remote' else shell
    if collector_shell not in {'posix','powershell'}:raise InputError('Choose the remote host shell')
    def field(key, default):
        text = value.get(key, default)
        if not isinstance(text, str) or not text.strip() or len(text) > 1024 or any(ord(c) < 32 for c in text):
            raise InputError(f'{key} must be a nonempty single line')
        return text.strip()
    root = field('root', 's3://my-bucket/run-a/outputs' if case == 'cloud' else './outputs')
    experiment = field('experiment', 'run-a')
    producer = field('producer', experiment + '/outputs')
    db = field('database', './workspace/tracker.sqlite')
    port = value.get('port', 8765)
    if type(port) is not int or not (1024 <= port <= 65535 or port==0 and case in {'local','cloud'}):
        raise InputError('Choose a port between 1024 and 65535; local/cloud setups also accept 0 for an available port')
    if len(producer) > 240:
        raise InputError('Producer identity must be at most 240 characters')
    def render_command(args,target_shell):
        quote=(lambda s: "'"+str(s).replace("'","''")+"'") if target_shell=='powershell' else shlex.quote
        # A POSIX host may provide python3 without a python alias.
        args=[('python3' if target_shell=='posix' else 'python') if i==0 and a=='python' else a for i,a in enumerate(args)]
        return ('& ' if target_shell=='powershell' else '')+' '.join(quote(a) for a in args)
    command=lambda args:render_command(args,collector_shell)
    base = ['python', '-m', 'rilldex', '--db', db]
    flags = ['--watch', root, '--mode', mode, '--experiment', experiment, '--producer', producer]
    watch = ['watch', root, '--mode', mode, '--experiment', experiment, '--producer', producer]
    if fmt!='auto':flags+=['--format',fmt];watch+=['--format',fmt]
    snapshot_state=value.get('snapshot_state','in_progress')
    if snapshot_state not in {'in_progress','complete'}:raise InputError('Choose in_progress or complete for raw snapshots')
    if mode=='snapshots':
        flags+=['--snapshot-state',snapshot_state];watch+=['--snapshot-state',snapshot_state]
    pattern = value.get('pattern')
    if pattern:
        suffix = '.jsonl' if mode == 'exports' else '.json'
        if mode == 'native' or not isinstance(pattern, str) or not pattern.endswith(suffix) or any(c in pattern for c in '/\\\n\r'):
            raise InputError('Use a filename glob matching the selected JSON/JSONL layout')
        flags += ['--pattern', pattern]; watch += ['--pattern', pattern]
    steps = []
    def step(title, code, where):
        steps.append({'title': title, 'code': code, 'where': where})
    constraints = ['Training order requires per-rollout step and step basis. Arrival time is not a training step.',
                   'Source maps and recorded measurements are available after capture. Semantic plans and diagnoses require saved observations or a separately configured observer.']
    resume = 'Repeat the start command with the same workspace, producer and source-relative filenames. Existing receipts and reader positions are retained.'
    runtime='python' if collector_shell=='powershell' else 'python3'
    install = f'Use Python 3.11+ in a separate environment: {runtime} -m pip install . (from this checkout), or install the supplied wheel. Base capture needs no GPU, trainer package or model key.'
    connection = dict(root=root, producer=producer, mode=mode, format=fmt, metadata={'experiment': experiment})
    if mode=='snapshots':connection['snapshot_state']=snapshot_state
    if pattern: connection['pattern'] = pattern
    if case in {'local', 'remote', 'cloud'}:
        where = 'Collector machine'
        if case == 'remote':
            where = 'Remote host with read access to job outputs'
        if case == 'cloud':
            from .cloud_watch import source as cloud_source
            cloud_source(root)
            sdk = 's3fs' if root.startswith('s3:') else 'gcsfs'
            step('Install the storage reader', command(['python', '-m', 'pip', 'install', sdk]), where)
            constraints.append('Credentials belong on the collector host. Cloud collection polls object listings; it is not an event subscription.')
        if stage=='before' and case!='cloud':
            step('Prepare the output directory',command(['python','-c','from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)',root]),where)
        step('Check a sample without importing', command(base + watch + ['--check']), where)
        if stage == 'after':
            step('Import all available output', command(base + watch + ['--once']), where)
            step('Open the recorded workspace', command(base + ['start', '--port', str(port)] + ([] if case == 'remote' else ['--open'])), where)
        else:
            step('Collect existing output and follow new records', command(base + ['start', '--port', str(port)] + flags + ([] if case == 'remote' else ['--open'])), where)
        if case == 'remote':
            host = field('host', 'training-host')
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
                raise InputError('Use an SSH host alias or user@hostname')
            step('Connect your browser through SSH', render_command(['ssh', '-N', '-o','ExitOnForwardFailure=yes','-L', f'{port}:127.0.0.1:{port}', host],shell), 'Your workstation')
            constraints.append('Keep the collector in a persistent session or scheduled CPU job. The same tunnel port is required at both ends. Shared/public access needs a separate authenticated deployment.')
        if stage == 'before':
            constraints.append('The preparation step creates an empty local output directory if needed. No training process is launched or modified.')
        if stage == 'after':
            resume = 'The one-off import exits. Repeat it with the same database and producer for later files, or switch to start --watch to follow continuously.'
    elif case == 'docker':
        if ',' in root or not (root.startswith('/') or re.match(r'^[A-Za-z]:[\\/]', root)):
            raise InputError('Docker needs an absolute host output directory without commas')
        step('Build the collector from this checkout', command(['docker', 'build', '-t', 'rilldex', '.']), 'Docker host')
        docker = ['docker', 'run', '--name', 'rilldex', '--init', '--restart', 'unless-stopped', '-d',
                  '-p', f'127.0.0.1:{port}:{port}', '--mount', 'type=volume,source=rilldex-data,target=/data',
                  '--mount', f'type=bind,source={root},target=/outputs,readonly', 'rilldex',
                  '--db', '/data/tracker.sqlite', 'start', '--container', '--port', str(port),
                  '--watch', '/outputs', '--mode', mode, '--experiment', experiment, '--producer', producer]
        if pattern: docker += ['--pattern', pattern]
        if fmt!='auto':docker+=['--format',fmt]
        if mode=='snapshots':docker+=['--snapshot-state',snapshot_state]
        step('Start with persistent data and read-only job files', command(docker), 'Docker host')
        resume = 'docker stop --time 45 rilldex; later run docker start rilldex. Retain the rilldex-data volume. If that container already exists, start it rather than creating another. For an existing installation, keep its original container and volume names.'
        constraints.append('Docker must already be installed; the source directory must exist. Container names and volumes are for one workspace. GPU training stays in its own environment.')
    elif case == 'notebook':
        py = lambda s: json.dumps(s, ensure_ascii=False)
        step('Watch outputs without running a web server',
             'from tracker.notebook import open_workspace\n'
             f'workspace = open_workspace({py(db)})\n'
             f'workspace.watch({py(root)}, producer={py(producer)}, experiment={py(experiment)}, mode={py(mode)}' + (f', format={py(fmt)}' if fmt!='auto' else '') + (f', pattern={py(pattern)}' if pattern else '') + (f', snapshot_state={py(snapshot_state)}' if mode=='snapshots' else '') + ')\n' +
             'workspace.start()\nworkspace.status()', 'Notebook cell')
        step('Save before the notebook runtime disappears',
             'workspace.stop()\nworkspace.snapshot("review.rilldex.zip")', 'Notebook cell; download the archive to persistent storage')
        step('Continue inspection on your computer',
             command(['python', '-m', 'rilldex', '--db', './review/tracker.sqlite', 'workspace', 'restore', 'review.rilldex.zip']) + '\n' +
             command(['python', '-m', 'rilldex', '--db', './review/tracker.sqlite', 'start', '--port',str(port),'--open']), 'Your workstation; restore into a new path')
        resume = 'Rerun the cell with the same local database after an ordinary kernel restart. After VM deletion, restore the downloaded archive; collection starts paused. Retain original outputs separately.'
        constraints.append('Keep active SQLite on local notebook storage, not a Drive/NFS mount. Colab deletion removes local files; automatic cloud backup and a proxied notebook UI are not provided.')
    else:
        step('Record beside each worker without network delivery',
             'from rilldex import Outbox\n'
             f'outbox = Outbox("worker-0.sqlite", producer={json.dumps(experiment + "/worker-0")})\n'
             '# At the point where a complete source document is available:\n'
             'outbox.log(rollout_id=stable_sample_id, document=trajectory,\n'
             f'           format={json.dumps(fmt)}, state="complete", metadata={{"experiment": {json.dumps(experiment)}}})\n'
             '# Do not call .start() for offline capture.', 'Worker code; stable_sample_id and trajectory come from your framework')
        step('Make a consistent portable copy', command(['python', '-m', 'rilldex', 'capture', 'export', 'worker-0.sqlite', 'worker-0.rilldex-capture.zip']), 'Worker host; copy the bundle with your existing artifact or file transfer tool')
        step('Receive on the inspection machine', command(base + ['capture', 'import', 'worker-0.rilldex-capture.zip', '--receipt', 'worker-0.receipts.json']) + '\n' + command(base + ['start', '--port', str(port), '--open']), 'Your workstation')
        step('Return the receipt to free delivered queue space', command(['python', '-m', 'rilldex', 'capture', 'acknowledge', 'worker-0.sqlite', 'worker-0.receipts.json']), 'Worker host; copy the receiving-workspace receipt back first')
        resume = 'Keep each worker outbox and producer stable across restart. Export to a new bundle filename and import again; accepted revisions are reused. Until acknowledgment, pending queue limits still apply. Acknowledgment clears only packets with matching receipts; keep the receiving workspace or a backup.'
        constraints.append('Use one local outbox per worker. Do not share SQLite across ranks or network filesystems. Slurm/Ray/Kubernetes still owns job lifecycle; no scheduler plugin is implied.')
        constraints.append('Bundles include outstanding rollout, training-record, recipe and continuation packets. Already HTTP-delivered packets were removed from the outbox; use their receiving workspace or a workspace backup.')
    launch_file={'schema':LAUNCH_SCHEMA,'database':db,'source':connection,'port':port,
                 'create_output':stage=='before' and case!='cloud'} if case in {'local','remote','cloud'} else None
    return {'schema': 'deployment-plan/1', 'case': case, 'title': CASES[case], 'stage': stage,
            'launch_file':launch_file,'launch_command':command(['python','-m','rilldex','launch','job.rilldex.json']),
            'install': install, 'steps': steps, 'resume': resume, 'constraints': constraints,
            'connection': connection if case in {'local', 'cloud'} else None,
            'browser_url': f'http://127.0.0.1:{port}' if port else None,
            'first_value': ['Connections: verify receipts and evidence coverage.',
                            'Rollouts: open a captured case and its unit map.',
                            'Dashboard: compare recorded measures within the same experiment and clock.']}
