"""Opt-in, bounded semantic observation of immutable source snapshots.

One local OS-owned lock serializes a worker. SQLite records jobs, lifetime
reservations and atomic publications. This is not a distributed scheduler.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import semantic_workspace as workspace
from .schema import InputError, digest, dumps
from .semantic_budget import BudgetReached, DEFAULT_LIMITS, limits
from .semantic_extraction import read, write, windows, load_extraction

VERSION = 'semantic-watch/1'
ZERO = dict.fromkeys(DEFAULT_LIMITS, 0)
BLOCKED = {'interrupted', 'failed', 'needs_candidates', 'needs_evidence', 'budget_reached'}


def now():
    return datetime.now(timezone.utc).isoformat()


def behavior_options():
    """The installed pilot's relationship stages, pinned for a new worker."""
    from .action_targets import PAGED_VERSION as TARGET
    from .plan_relations import DIRECT_VERSION as PLAN
    from .execution_reports import VERSION as REPORT
    from .method_comparison import NATIVE_VERSION as METHOD
    return dict(action_target_version=TARGET,plan_relation_version=PLAN,execution_report_version=REPORT,method_comparison_version=METHOD)


def initialize_tables(c):
    c.execute('''CREATE TABLE IF NOT EXISTS semantic_watchers (
        id TEXT PRIMARY KEY, document TEXT NOT NULL, allowance TEXT NOT NULL,
        budget_history TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS semantic_watch_jobs (
        worker_id TEXT NOT NULL REFERENCES semantic_watchers(id), run_id TEXT NOT NULL REFERENCES runs(id),
        source_hash TEXT NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(worker_id,run_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS semantic_watch_attempts (
        id TEXT PRIMARY KEY, worker_id TEXT NOT NULL REFERENCES semantic_watchers(id),
        run_id TEXT NOT NULL REFERENCES runs(id), provider TEXT NOT NULL,
        input_bytes INTEGER NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS semantic_watch_attempt_worker ON semantic_watch_attempts(worker_id)')


def fingerprint(options=None):
    # Prevent unnoticed code changes from mixing protocols under one observer.
    names = ('semantic_extraction.py', 'base_standard.py', 'contribution_readings.py',
             'readable_context.py', 'candidate_worker.py', 'candidate_process.py', 'semantic_workspace.py',
             'candidate_cache.py', 'decision_cache.py', 'semantic_watch.py')
    if (options or {}).get('feedback_profile'):
        names+=('semantic_layers.py','feedback_assessments.py','feedback_retrieval.py')
    if (options or {}).get('requested_profile'):
        names+=('semantic_layers.py','requested_work.py','requested_graph.py','request_dispatch.py')
    if (options or {}).get('action_target_version'):
        names+=('action_targets.py','action_scope_pairs.py','action_scope_pages.py','semantic_pages.py','work_order.py')
    if (options or {}).get('plan_relation_version'):
        names+=('plan_relations.py','plan_scope_pages.py','semantic_pages.py')
        if options['plan_relation_version']=='plan-stage-correspondence/4':names+=('plan_scope_roles.py',)
    if (options or {}).get('execution_report_version'):
        names+=('execution_reports.py',)
    if (options or {}).get('method_comparison_version'):
        names+=('method_comparison.py','recurrence_context.py','work_history.py','action_comparison.py','work_correspondence.py')
    return digest({name: (Path(__file__).parent / name).read_text(encoding='utf-8') for name in names})


def initialize(store, directory, *, experiment, label, allowance=None,
               workspace_options=None, command=None, producer=None, citation_format=None, live_prefixes=False,
               cache_directories=(),refresh=False):
    if type(refresh) is not bool:raise InputError('refresh must be boolean')
    if type(live_prefixes) is not bool:
        raise InputError('live_prefixes must be boolean')
    if not isinstance(experiment, str) or not experiment.strip():
        raise InputError('Select an explicit experiment for continuous observation')
    if not isinstance(label, str) or not label.strip() or len(label) > 160:
        raise InputError('Observer label must contain 1–160 characters')
    options = workspace_options or {}
    if not isinstance(options, dict):
        raise InputError('Workspace options must be a JSON object')
    if set(options) - {'include_user', 'context_policy', 'activity_routing', 'reading_protocol', 'partition_standard','feedback_profile','requested_profile','action_target_version','plan_relation_version','execution_report_version','method_comparison_version'}:
        raise InputError('Unknown semantic workspace option')
    from .action_targets import PAGED_VERSION as TARGET_VERSION
    from .plan_relations import PAGED_VERSIONS
    from .execution_reports import VERSION as REPORT_VERSION
    from .method_comparison import NATIVE_VERSION as METHOD_VERSION
    for name,version in [('action_target_version',TARGET_VERSION),('execution_report_version',REPORT_VERSION),('method_comparison_version',METHOD_VERSION)]:
        if options.get(name) not in (None,version):raise InputError('Unsupported '+name)
    if options.get('method_comparison_version') and not options.get('action_target_version'):
        raise InputError('Approach comparison requires work-target links')
    if options.get('plan_relation_version') not in {None,*PAGED_VERSIONS}:raise InputError('Unsupported plan_relation_version')
    from .semantic_layers import profile,requested_profile
    profile(options.get('feedback_profile'))
    requested_profile(options.get('requested_profile'),options.get('include_user',True))
    if 'include_user' in options and type(options['include_user']) is not bool:
        raise InputError('include_user must be boolean')
    from .semantic_extraction import activity_choices, ACTIVITY_ROUTING
    from .contribution_readings import protocol
    from .readable_context import validate_policy
    activity_choices(options.get('activity_routing', ACTIVITY_ROUTING))
    if options.get('partition_standard', workspace.PARTITION_CANDIDATE_STANDARD) not in {workspace.PARTITION_CANDIDATE_STANDARD, workspace.WORK_PHASE_STANDARD}:
        raise InputError('Unsupported workspace partition standard')
    protocol(options.get('reading_protocol', 'contribution-readings/1'))
    context = options.get('context_policy', workspace.DEFAULT_CONTEXT)
    if not isinstance(context, dict):
        raise InputError('Context policy must be a JSON object')
    validate_policy(context)
    from .candidate_worker import CITATION_FORMATS
    if citation_format is not None and citation_format not in CITATION_FORMATS:
        raise InputError('Unknown candidate citation format')
    if command is not None and (not isinstance(command, list) or not command or
            any(not isinstance(x, str) or not x for x in command) or not producer):
        raise InputError('Provide a candidate command argument list and versioned producer')
    if command is None and (producer or citation_format):
        raise InputError('Producer and citation format require a candidate command')
    cap = limits(ZERO if allowance is None else {**ZERO, **allowance})
    root = Path(directory).resolve()
    caches=list(dict.fromkeys(str(Path(p).resolve()) for p in cache_directories))
    for path in caches:
        if Path(path)==root or root in Path(path).parents:
            raise InputError('Reusable workspaces must be outside the new worker directory')
        workspace.load(path)
    definition = {'schema': VERSION, 'database': str(store.path.resolve()), 'directory': str(root),
                  'experiment': experiment, 'label': label.strip(), 'workspace_options': options,
                  'extractor_fingerprint': fingerprint(options), 'command_hash': digest(command) if command else None,
                  'producer': producer, 'citation_format': citation_format}
    if live_prefixes: definition['live_prefixes'] = True
    if caches:definition['cache_directories']=caches
    path=root/'watch.json'
    if refresh and not path.exists():raise InputError('Refresh requires an existing worker directory')
    if path.exists():
        previous=read(path)
        if {**definition,'extractor_fingerprint':previous['extractor_fingerprint']}!=previous:
            raise InputError('Worker source selection or protocol changed; use a new directory')
        from .semantic_refresh import state,refresh as refresh_saved
        if refresh:refresh_saved(store,root)
        old_id='semantic-'+digest(previous)[:24]
        if state(store,old_id,previous,definition['extractor_fingerprint'])['status']=='current':definition=previous
        else:raise InputError('Extractor implementation changed; use semantic watch-refresh or models watch --refresh-worker to replay saved evidence offline')
    identifier = 'semantic-' + digest(definition)[:24]
    with workspace.exclusive(root):
        path = root / 'watch.json'
        if path.exists() and read(path) != definition:
            raise InputError('Worker source selection or protocol changed; use a new directory')
        if not path.exists() and any(p.name != '.workspace.lock' for p in root.iterdir()):
            raise InputError('A new semantic worker requires an empty directory')
        # Validate options using the existing source-bound workspace machinery
        # when a job is prepared; no candidate/provider process runs here.
        write(path, definition)
        with store.connect() as c:
            initialize_tables(c)
            c.execute('INSERT OR IGNORE INTO semantic_watchers VALUES (?,?,?,?)',
                      (identifier, dumps(definition), dumps(cap), dumps([{'at': now(), 'allowance': cap}])))
            saved = c.execute('SELECT document FROM semantic_watchers WHERE id=?', (identifier,)).fetchone()
            if saved[0] != dumps(definition):
                raise InputError('Semantic worker identity collision')
            # Completed members are immutable database archives, rather than an
            # ever-changing collection ID. The empty manifest is intentional.
            c.execute('INSERT OR IGNORE INTO semantic_observers VALUES (?,?)',
                      (identifier, dumps({'kind': 'extraction', 'schema': VERSION, 'directory': str(root),
                                          'label': definition['label'], 'members': {}})))
    return status(store, root)


def load(store, directory):
    root = Path(directory).resolve()
    definition = read(root / 'watch.json')
    if definition.get('schema') != VERSION or definition.get('database') != str(store.path.resolve()) or definition.get('directory') != str(root):
        raise InputError('Semantic worker belongs to another database or directory')
    identifier = 'semantic-' + digest(definition)[:24]
    with store.connect() as c:
        row = c.execute('SELECT * FROM semantic_watchers WHERE id=?', (identifier,)).fetchone()
    if row is None or row['document'] != dumps(definition):
        raise InputError('Worker configuration differs from its database record')
    return identifier, definition, json.loads(row['allowance'])


def population(store, experiment, *, live_prefixes=False):
    with store.connect() as c:
        rows = c.execute('''SELECT r.id,r.document,v.state FROM runs r
            LEFT JOIN rollout_revisions v ON v.run_id=r.id
            WHERE (v.run_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM rollout_revisions n WHERE n.producer=v.producer
                AND n.rollout_id=v.rollout_id AND n.revision>v.revision))
            AND json_extract(r.document,'$.metadata.experiment')=?
            ORDER BY r.imported_at,r.id''', (experiment,)).fetchall()
    # A source snapshot can be referenced by more than one producer record.
    sources = {}
    for row in rows:
        run = json.loads(row['document'])
        state = row['state'] or 'imported_snapshot'
        ready = state in {'complete', 'imported_snapshot'} or live_prefixes and state == 'in_progress'
        previous = sources.get(row['id'])
        sources[row['id']] = {'run': run, 'state': state, 'ready': ready and (previous is None or previous['ready'])}
    return sources


def _jobs(store, identifier):
    with store.connect() as c:
        return {r['run_id']: dict(r) for r in c.execute(
            'SELECT * FROM semantic_watch_jobs WHERE worker_id=? ORDER BY created_at,run_id', (identifier,))}


def _set_job(c, identifier, run_id, state, document):
    c.execute('UPDATE semantic_watch_jobs SET status=?,document=?,updated_at=? WHERE worker_id=? AND run_id=?',
              (state, dumps(document), now(), identifier, run_id))


def _candidate_response_hash(path, request_hash):
    """Hash a complete, request-bound JSON handoff; ignore partial writes."""
    try:
        raw = Path(path).read_bytes()
        response = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (not isinstance(response, dict) or response.get('request_hash') != request_hash or
            not isinstance(response.get('producer'), str) or not response['producer'].strip()):
        return None
    return hashlib.sha256(raw).hexdigest()


def _request_hash_name(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def usage(store, identifier):
    # Aggregate in SQLite: status polling must not load every saved request or
    # attempt document into Python. Missing/invalid counters are not zero usage.
    fields = ('input_tokens', 'output_tokens', 'total_tokens')
    valid = {key: f"json_type(document,'$.reported_usage.{key}')='integer' AND json_extract(document,'$.reported_usage.{key}')>=0"
             for key in fields}
    columns = ','.join(
        f"sum(CASE WHEN {valid[key]} THEN json_extract(document,'$.reported_usage.{key}') ELSE 0 END) {key},"
        f"sum(CASE WHEN {valid[key]} THEN 1 ELSE 0 END) {key}_observations" for key in fields)
    with store.connect() as c:
        rows = c.execute(f'''SELECT provider,status,coalesce(json_extract(document,'$.stage'),'unrecorded') stage,
            count(*) n,sum(input_bytes) bytes,{columns},
            sum(CASE WHEN {' OR '.join('('+v+')' for v in valid.values())} THEN 0 ELSE 1 END) missing
            FROM semantic_watch_attempts WHERE worker_id=? GROUP BY provider,status,stage''', (identifier,)).fetchall()
    used = dict(ZERO)
    states = Counter()
    providers = {}
    for row in rows:
        used[row['provider'] + '_requests'] += row['n']
        used['input_bytes'] += row['bytes']
        states[row['status']] += row['n']
        group = providers.setdefault(row['provider'], {'attempts': 0, 'input_bytes': 0,
            'statuses': Counter(), 'stages': Counter(), 'reported_usage': Counter(),
            'usage_observations': Counter(), 'attempts_without_reported_usage': 0})
        group['attempts'] += row['n']
        group['input_bytes'] += row['bytes']
        group['statuses'][row['status']] += row['n']
        group['stages'][row['stage']] += row['n']
        group['attempts_without_reported_usage'] += row['missing']
        for key in fields:
            if row[key+'_observations']:
                group['reported_usage'][key] += row[key]
                group['usage_observations'][key] += row[key+'_observations']
    return {'used': used, 'attempt_statuses': dict(states),
            'provider_usage': {'schema': 'semantic-provider-usage/1', 'providers': providers,
                'scope': 'Durable attempts for this worker across all jobs and restarts, including failed and unfinished attempts.',
                'limits': 'Reported token counters only; usage_observations gives the number of attempts reporting each counter. Missing counters are unknown. File handoffs and candidate-internal model calls are outside this ledger. These are not token or currency limits.'},
            'basis': 'Reserved provider invocations and UTF-8 payload bytes across all jobs and restarts. Failed/unfinished attempts count. The built-in Jev client no longer retries internally; historical/custom transports and candidate-internal model calls are not separately metered.'}


class Ledger:
    def __init__(self, store, identifier, run_id):
        self.store, self.identifier, self.run_id = store, identifier, run_id

    def reserve(self, row):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            cap = json.loads(c.execute('SELECT allowance FROM semantic_watchers WHERE id=?', (self.identifier,)).fetchone()[0])
            used = dict(ZERO)
            for prior in c.execute('SELECT provider,count(*) n,sum(input_bytes) bytes FROM semantic_watch_attempts WHERE worker_id=? GROUP BY provider', (self.identifier,)):
                used[prior['provider'] + '_requests'] += prior['n']
                used['input_bytes'] += prior['bytes']
            for field, increment in ((row['provider'] + '_requests', 1), ('input_bytes', row['input_bytes'])):
                if used[field] + increment > cap[field]:
                    raise BudgetReached({'scope': 'worker_lifetime', 'limit': field,
                                         'used': used[field], 'allowed': cap[field], 'next': increment})
            c.execute('INSERT INTO semantic_watch_attempts VALUES (?,?,?,?,?,?,?)',
                      (row['attempt_id'], self.identifier, self.run_id, row['provider'], row['input_bytes'], row['status'], dumps(row)))

    def finish(self, row):
        with self.store.connect() as c:
            c.execute('UPDATE semantic_watch_attempts SET status=?,document=? WHERE id=? AND worker_id=?',
                      (row['status'], dumps(row), row['attempt_id'], self.identifier))


def set_allowance(store, directory, allowance):
    """Set absolute lifetime ceilings, never reset consumed reservations."""
    cap = limits(allowance)
    with workspace.exclusive(directory):
        identifier, _, old = load(store, directory)
        if any(cap[k] < old[k] for k in cap):
            raise InputError('Lifetime limits can only increase; consumed reservations are retained')
        with store.connect() as c:
            row = c.execute('SELECT budget_history FROM semantic_watchers WHERE id=?', (identifier,)).fetchone()
            history = json.loads(row[0])
            if cap != old:
                history.append({'at': now(), 'allowance': cap})
                c.execute('UPDATE semantic_watchers SET allowance=?,budget_history=? WHERE id=?',
                          (dumps(cap), dumps(history), identifier))
    return status(store, directory)


class Transaction:
    """Share one publication transaction with existing graph/metric writers."""
    def __init__(self, store, connection):
        self.path, self.connection = store.path, connection

    @contextmanager
    def connect(self):
        yield self.connection


def _current_complete(c, run_id, *, live_prefixes=False):
    rows = c.execute('''SELECT v.state FROM rollout_revisions v WHERE v.run_id=?
        AND NOT EXISTS(SELECT 1 FROM rollout_revisions n WHERE n.producer=v.producer
            AND n.rollout_id=v.rollout_id AND n.revision>v.revision)''', (run_id,)).fetchall()
    if rows:
        return all(r['state'] == 'complete' or live_prefixes and r['state'] == 'in_progress' for r in rows)
    # No producer record means an ordinary imported snapshot. Historical-only
    # producer records mean superseded. Repeated identical revisions may share
    # one run_id and must be evaluated at the latest producer revision.
    return c.execute('SELECT 1 FROM rollout_revisions WHERE run_id=? LIMIT 1', (run_id,)).fetchone() is None


def _prior_workspaces(store, identifier, run_id, root):
    """Earlier revisions of the same logical rollout under this exact worker.

    Only request caches are reused. Results, checkpoints, annotations and budgets
    stay bound to their original snapshots; changed requests are recomputed.
    """
    with store.connect() as c:
        rows = c.execute('''SELECT DISTINCT old.run_id,old.revision
            FROM rollout_revisions current JOIN rollout_revisions old
              ON old.producer=current.producer AND old.rollout_id=current.rollout_id
             AND old.revision<current.revision
            JOIN semantic_watch_jobs job ON job.run_id=old.run_id AND job.worker_id=?
            WHERE current.run_id=? AND old.run_id<>? ORDER BY old.revision DESC''',
            (identifier,run_id,run_id)).fetchall()
    return list(dict.fromkeys(root/'runs'/row['run_id'] for row in rows
                              if (root/'runs'/row['run_id']/'workspace.json').exists()))


def _predecessor_block(c, identifier, run_id):
    """A growing source cannot silently retry an unresolved provider attempt."""
    rows = c.execute('''SELECT old.run_id,job.status,job.document FROM rollout_revisions current
        JOIN rollout_revisions old ON old.producer=current.producer AND old.rollout_id=current.rollout_id
          AND old.revision<current.revision
        JOIN semantic_watch_jobs job ON job.run_id=old.run_id AND job.worker_id=?
        WHERE current.run_id=? AND old.run_id<>?
        ORDER BY old.revision DESC LIMIT 1''', (identifier,run_id,run_id)).fetchall()
    if not rows:return None
    row=rows[0]
    state=json.loads(row['document']).get('resume_status',row['status']) if row['status']=='superseded' else row['status']
    if state=='running':state='interrupted'
    if state in {'interrupted','failed','budget_reached'}:
        return state,{'reason':'Earlier prefix has an unresolved blocked execution; explicit retry of this current snapshot is required',
                      'inherited_from_run':row['run_id']}
    return None


def _candidate_handoff(root):
    result=_queue_handoff(root,'candidates')
    work=_queue_handoff(root,'work_candidates')
    if work['requests']:
        result['work_candidates']=work
        result['fingerprint']=digest({'base':result['requests'],'work':work['requests']})
        base=result['waiting_candidates'];extra=work['waiting_candidates']
        result['waiting_candidates']={
            'missing_responses':base['missing_responses']+extra['missing_responses'],
            'responses_present':base['responses_present']+extra['responses_present'],
            'stages':dict(Counter(base['stages'])+Counter(extra['stages']))}
    return result


def _queue_handoff(root,queue):
    """Fingerprint the exact candidate files in this worker-owned workspace.

    Requests are read only when a wait snapshot is created. Later polls use the
    saved request ids and hash response bytes, so they do not reread the request
    queue. Candidate files are constrained to the workspace's own directories.
    """
    root = Path(root).resolve()
    candidates = root / queue
    requests_dir = candidates / 'requests'
    responses_dir = candidates / 'responses'
    if candidates.is_symlink() or (candidates.exists() and candidates.resolve().parent != root):
        raise InputError('Candidate directory escapes its workspace')
    if responses_dir.is_symlink() or (responses_dir.exists() and responses_dir.resolve().parent != candidates):
        raise InputError('Candidate response directory escapes its workspace')
    requests = {}
    stages = Counter()
    supplied = 0
    if requests_dir.exists():
        if requests_dir.is_symlink() or requests_dir.resolve().parent != candidates:
            raise InputError('Candidate request directory escapes its workspace')
        for path in requests_dir.glob('*.json'):
            if path.is_symlink() or path.resolve().parent != requests_dir.resolve():
                raise InputError('Candidate request file escapes its workspace')
            key = path.stem
            if not _request_hash_name(key):
                raise InputError('Candidate request filename is not a request hash')
            request = read(path)
            if digest(request) != key:
                raise InputError('Candidate request identity differs from its filename')
            stage = request.get('stage', 'partition')
            response_path = responses_dir / path.name
            response_hash = None
            if response_path.exists():
                if response_path.is_symlink() or response_path.resolve().parent != responses_dir.resolve():
                    raise InputError('Candidate response file escapes its workspace')
                response_hash = _candidate_response_hash(response_path, key)
            if response_hash is not None:
                supplied += 1
            else:
                stages[stage] += 1
            requests[key] = {'stage': stage, 'response_sha256': response_hash}
    summary = {'missing_responses': sum(stages.values()), 'responses_present': supplied,
               'stages': dict(stages)}
    return {'schema': 'semantic-candidate-handoff/1', 'requests': requests,
            'fingerprint': digest(requests), 'waiting_candidates': summary}


def _candidate_handoff_changes(root,saved):
    if not isinstance(saved,dict) or saved.get('schema')!='semantic-candidate-handoff/1':return []
    empty={'schema':'semantic-candidate-handoff/1','requests':{}}
    return (_queue_handoff_changes(root,saved,'candidates')+
        _queue_handoff_changes(root,saved.get('work_candidates',empty),'work_candidates'))


def _queue_handoff_changes(root, saved, queue):
    """Return newly supplied or edited awaited response identities.

    Response contents, rather than timestamps, determine identity. Deletions do
    not trigger work. New request files are recognized only when paired with a
    matching response file inside this workspace.
    """
    if not isinstance(saved, dict) or saved.get('schema') != 'semantic-candidate-handoff/1':
        return []
    root = Path(root).resolve()
    candidates = root / queue
    requests_dir = candidates / 'requests'
    responses_dir = candidates / 'responses'
    if candidates.is_symlink() or (candidates.exists() and candidates.resolve().parent != root):
        raise InputError('Candidate directory escapes its workspace')
    if responses_dir.is_symlink() or (responses_dir.exists() and responses_dir.resolve().parent != candidates):
        raise InputError('Candidate response directory escapes its workspace')
    known = saved.get('requests')
    if not isinstance(known, dict):
        return []
    changed = []
    for key, prior in known.items():
        if not _request_hash_name(key) or not isinstance(prior, dict):
            continue
        response_path = responses_dir / f'{key}.json'
        if not response_path.exists():
            continue
        if response_path.is_symlink() or response_path.resolve().parent != responses_dir.resolve():
            raise InputError('Candidate response file escapes its workspace')
        current_hash = _candidate_response_hash(response_path, key)
        if current_hash is None:
            continue
        if current_hash != prior.get('response_sha256'):
            changed.append({'request_hash': key, 'stage': prior.get('stage', 'unknown')})
    # A response may be added for a request generated after the last snapshot.
    # Only inspect matching local request/response pairs; no external path is used.
    if requests_dir.exists() and responses_dir.exists():
        if (requests_dir.is_symlink() or requests_dir.resolve().parent != candidates or
                responses_dir.is_symlink() or responses_dir.resolve().parent != candidates):
            raise InputError('Candidate handoff directories escape their workspace')
        for response_path in responses_dir.glob('*.json'):
            key = response_path.stem
            if key in known:
                continue
            if not _request_hash_name(key):
                continue
            request_path = requests_dir / response_path.name
            if (response_path.is_symlink() or request_path.is_symlink() or
                    response_path.resolve().parent != responses_dir.resolve() or
                    not request_path.exists() or request_path.resolve().parent != requests_dir.resolve()):
                continue
            request = read(request_path)
            if digest(request) != key:
                continue
            if _candidate_response_hash(response_path, key) is not None:
                changed.append({'request_hash': key, 'stage': request.get('stage', 'partition')})
    return changed


def materialize(identifier, definition, run, directory):
    """Replay a publication without writing database graphs or measurements."""
    options=definition['workspace_options']
    result = load_extraction(run, directory,action_target_version=options.get('action_target_version'),
                             plan_relation_version=options.get('plan_relation_version'))
    if not result['available'] or result['raw_extraction']['status'] != 'complete_local_extraction':
        raise InputError('Only an audited complete extraction may be published')
    layers=workspace.status(directory)['layers']
    for name,option in [('action_targets','action_target_version'),('plan_relations','plan_relation_version'),('execution_reports','execution_report_version'),('method_comparison','method_comparison_version')]:
        if options.get(option) and layers[name]['status']!='complete':
            raise InputError('Requested '+name+' inspection is incomplete')
        if options.get(option) and name in {'action_targets','plan_relations'} and name not in result['validation']:
            raise InputError('Requested '+name+' results are missing')
    if options.get('method_comparison_version'):
        from .method_comparison import load as load_methods
        result['document']['method_comparison']=load_methods(run,result['document'],directory)
        if result['document']['method_comparison']['schema']!=options['method_comparison_version']:
            raise InputError('Requested approach comparison result is missing or uses a different protocol')
    if options.get('execution_report_version'):
        from .execution_reports import path_for,audit,project
        reports=read(path_for(directory,run));validation=audit(run,reports,directory)
        result=project(run,result,reports);result['validation']['execution_reports']=validation
    from .semantic_catalog import export_payload
    result['observer'] = {'id': identifier, 'label': definition['label']}
    result['export_digest'] = digest(export_payload(result))
    return result


def _publish(store, identifier, definition, run, directory):
    from .observer_archive import save as archive
    from .rollout_metrics import record_map
    options=definition['workspace_options']
    result=materialize(identifier,definition,run,directory)
    layers=workspace.status(directory)['layers']
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not _current_complete(c, run['id'], live_prefixes=definition.get('live_prefixes',False)):
            _set_job(c, identifier, run['id'], 'superseded', {'reason': 'Source is no longer current or eligible; saved extraction retained'})
            return
        bound = Transaction(store, c)
        provisional = not _current_complete(c, run['id'])
        archive(bound, run, identifier, result)
        measured = record_map(bound, run, result)
        _set_job(c, identifier, run['id'], 'published', {'graph_id': measured['graph_id'],
                 'extraction_hash': digest(result['raw_extraction']), 'unit_count': len(result['raw_extraction']['units']),
                 'source_complete_at_publication': not provisional,
                 'url': '/semantic-map?run=' + run['id'] + '&observer=' + identifier,
                 'layers': {**layers,'feedback':result['validation'].get('feedback_layer'),
                            'requested_conditions':result['validation'].get('requested_layer')},
                 'scope': ('Immutable growing-source prefix; final rollout outcomes and completed-rollout rates remain unavailable. ' if provisional else '') +
                     'Base semantic extraction'+
                     (' plus explicit feedback references' if definition['workspace_options'].get('feedback_profile') else '')+
                     (' and versioned requested terms/checks' if definition['workspace_options'].get('requested_profile') else '')+
                     (' with plan-to-action links' if options.get('plan_relation_version') else '')+
                     (' and work-target links' if options.get('action_target_version') else '')+
                     (' and approach comparisons' if options.get('method_comparison_version') else '')+
                     (' and executor errors/warnings' if options.get('execution_report_version') else '')+
                     '. Correct interpretation, causal use, fulfillment and recovery require further evidence.'})


def run_once(store, directory, transport, *, command=None, max_rollouts=8, max_pending=64, retry_runs=None):
    if type(max_rollouts) is not int or not 1 <= max_rollouts <= 100 or type(max_pending) is not int or not 1 <= max_pending <= 1000:
        raise InputError('Use 1–100 rollouts per batch and 1–1000 pending jobs')
    root = Path(directory).resolve()
    with workspace.exclusive(root):
        identifier, definition, cap = load(store, root)
        from .semantic_refresh import state as implementation_state
        if implementation_state(store,identifier,definition,fingerprint(definition['workspace_options']))['status']!='current':
            raise InputError('Extractor implementation changed; run semantic watch-refresh to replay saved evidence offline')
        if (digest(command) if command else None) != definition['command_hash']:
            raise InputError('Candidate command differs from the worker configuration')
        sources = population(store, definition['experiment'], live_prefixes=definition.get('live_prefixes',False))
        jobs = _jobs(store, identifier)
        retries = set(retry_runs or [])
        if any(rid not in jobs or jobs[rid]['status'] not in BLOCKED | {'running', 'superseded'} or rid not in sources or not sources[rid]['ready'] for rid in retries):
            raise InputError('Retry only blocked jobs whose source is still current and eligible for this worker')
        with store.connect() as c:
            for rid, job in jobs.items():
                if job['status'] == 'published':
                    continue
                if rid not in sources or not sources[rid]['ready']:
                    resume = json.loads(job['document']).get('resume_status', job['status'])
                    _set_job(c, identifier, rid, 'superseded', {'reason': 'No longer a latest eligible source',
                             'resume_status': 'interrupted' if resume == 'running' else resume})
                elif rid in retries:
                    _set_job(c, identifier, rid, 'queued', {'reason': 'Explicit retry; lifetime budget retained'})
                elif job['status'] == 'needs_candidates':
                    previous = json.loads(job['document'])
                    handoff = previous.get('candidate_handoff')
                    changes = _candidate_handoff_changes(root / 'runs' / rid, handoff)
                    if changes:
                        current = _candidate_handoff(root / 'runs' / rid)
                        stages = Counter(row['stage'] for row in changes)
                        detail = {**previous,
                            'reason': 'A new or changed awaited candidate response was supplied; one bounded resume is queued',
                            'candidate_handoff': current,
                            'waiting_candidates': {**current['waiting_candidates'],
                                'changed_responses': {'count': len(changes), 'stages': dict(stages)}},
                            'changed_responses': {'count': len(changes), 'stages': dict(stages)}}
                        _set_job(c, identifier, rid, 'queued', detail)
                elif job['status'] == 'superseded':
                    resume = json.loads(job['document']).get('resume_status', 'queued')
                    _set_job(c, identifier, rid, resume if resume in BLOCKED else 'queued',
                             {'reason': 'This exact source is current and eligible again; prior budget and blocked state retained'})
                elif job['status'] == 'running':
                    # The OS lock proves no previous owner is still executing.
                    # Remote billing/completion can nevertheless be unknown.
                    _set_job(c, identifier, rid, 'interrupted', {'reason': 'Previous owner exited; explicit retry required'})
        jobs = _jobs(store, identifier)
        pending = sum(j['status'] == 'queued' for j in jobs.values())
        with store.connect() as c:
            for rid, item in sources.items():
                if rid in jobs or not item['ready'] or pending >= max_pending:
                    continue
                state = 'queued' if windows(item['run'], include_user=definition['workspace_options'].get('include_user', True)) else 'ineligible'
                inherited = _predecessor_block(c,identifier,rid) if state=='queued' else None
                detail={}
                if inherited:state,detail=inherited
                c.execute('INSERT INTO semantic_watch_jobs VALUES (?,?,?,?,?,?,?)',
                          (identifier, rid, digest(item['run']), state, dumps(detail), now(), now()))
                pending += state == 'queued'
        jobs = _jobs(store, identifier)
        if not retries and any(j['status'] in {'interrupted', 'failed', 'budget_reached'} for j in jobs.values()):
            return status(store, root)
        processed = 0
        for rid, job in _jobs(store, identifier).items():
            if job['status'] != 'queued' or processed >= max_rollouts:
                continue
            run = sources[rid]['run']
            if digest(run) != job['source_hash']:
                raise InputError('Queued source snapshot changed')
            job_root = root / 'runs' / rid
            with store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if not _current_complete(c, rid, live_prefixes=definition.get('live_prefixes',False)):
                    _set_job(c, identifier, rid, 'superseded', {'reason': 'Source changed while waiting in this batch; no extraction started'})
                    continue
                _set_job(c, identifier, rid, 'running', {'directory': str(job_root)})
            processed += 1
            try:
                workspace.initialize(job_root, run, **definition['workspace_options'])
                result = workspace.execute(job_root, transport, command=command, producer=definition['producer'],
                    citation_format=definition['citation_format'], budget_limits=cap,
                    budget_ledger=Ledger(store, identifier, rid),
                    cache_directories=[*definition.get('cache_directories',()),
                        *(_prior_workspaces(store,identifier,rid,root) if definition.get('live_prefixes') else ())])
                if result['status'] == 'complete_local_extraction':
                    _publish(store, identifier, definition, run, job_root)
                else:
                    # Requested-work annotations use the external candidate queue.
                    # Retain its file handoff even when base extraction is complete,
                    # so an edited candidate can resume this layer without rerunning it.
                    requested_pending = result.get('layers', {}).get('requested_conditions', {}).get('status') == 'pending'
                    state = ('budget_reached' if result['status'] == 'budget_reached'
                             else 'needs_evidence' if result['status']=='needs_layers' and not requested_pending
                             else 'needs_candidates')
                    detail = {'coverage': result['coverage'],
                              'workspace_status': result['status'], 'layers':result.get('layers',{}),
                              'directory': str(job_root)}
                    if state == 'needs_candidates':
                        handoff = _candidate_handoff(job_root)
                        previous = json.loads(job['document'])
                        changed = previous.get('changed_responses', {'count': 0, 'stages': {}})
                        detail.update(candidate_handoff=handoff,
                                      changed_responses=changed,
                                      waiting_candidates={**handoff['waiting_candidates'],
                                          'changed_responses': changed})
                    with store.connect() as c:
                        _set_job(c, identifier, rid, state, detail)
                    if state == 'budget_reached':
                        break
            except (Exception, KeyboardInterrupt) as exc:
                from .jev import failure_details
                from .candidate_process import failure_details as candidate_failure
                failure=failure_details(exc) or candidate_failure(exc)
                with store.connect() as c:
                    _set_job(c, identifier, rid, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                             {'reason': 'Execution or publication failed; inspect the saved workspace and explicitly retry',
                              'error_type': type(exc).__name__, 'directory': str(job_root),
                              **({'provider_failure':failure} if failure is not None else {})})
                if isinstance(exc, KeyboardInterrupt):
                    raise
                # Do not spend across other jobs after a provider/config outage.
                break
    return status(store, directory)


def status(store, directory):
    identifier, definition, cap = load(store, directory)
    jobs = _jobs(store, identifier)
    sources = population(store, definition['experiment'], live_prefixes=definition.get('live_prefixes',False))
    counts = Counter(j['status'] for j in jobs.values())
    counters = usage(store, identifier)
    public_jobs = []
    for job in jobs.values():
        details = json.loads(job['document'])
        if job['status'] in {'running','budget_reached','interrupted','needs_evidence'}:
            # Page receipts remain readable while the workspace execution lock
            # is held. Do not run audits or read the entire extraction on polls.
            layers=dict(details.get('layers',{}))
            for name,filename in [('plan_relations','plan-relation-progress.json'),('action_targets','action-target-progress.json'),('execution_reports','execution-report-progress.json'),('method_comparison','method-comparison-progress.json')]:
                path=Path(directory)/'runs'/job['run_id']/filename
                if path.exists():
                    progress=read(path)
                    layers[name]={'status':progress['status'],'coverage':progress['coverage']}
            if layers:details['layers']=layers
        # Fingerprints are internal wait state; expose only the compact summary
        # so polling and --follow output do not grow with the request queue.
        details.pop('candidate_handoff', None)
        public_jobs.append({k: v for k, v in job.items() if k != 'document'} | {'details': details})
    from .semantic_refresh import state as implementation_state
    implementation=implementation_state(store,identifier,definition,fingerprint(definition['workspace_options']))
    if implementation.get('refresh'):
        receipt=implementation['refresh']
        implementation['refresh']={k:v for k,v in receipt.items() if k!='jobs'}
        implementation['refresh']['checked_jobs']=len(receipt['jobs'])
    return {'schema': VERSION, 'observer': identifier, 'label': definition['label'],
            'implementation':implementation,
            'experiment': definition['experiment'], 'allowance': cap, **counters,
            'workspace_options':definition['workspace_options'],
            'live_prefixes':definition.get('live_prefixes',False),
            'remaining': {k: max(0, cap[k] - counters['used'][k]) for k in cap},
            'current_sources': len(sources), 'waiting_for_completion': sum(s['state']=='in_progress' and not s['ready'] for s in sources.values()),
            'current_growing_prefixes':sum(s['state']=='in_progress' for s in sources.values()),
            'not_queued': sum(s['ready'] and rid not in jobs for rid, s in sources.items()),
            'current_published': sum(rid in sources and sources[rid]['ready'] and j['status'] == 'published' for rid, j in jobs.items()),
            'job_counts': dict(counts),
            'paused_for_review': any(counts[s] for s in ('failed', 'interrupted', 'budget_reached')),
            'jobs': public_jobs,
            'limits': ('Local single-owner worker. Growing prefixes are opt-in immutable snapshots; only newly observed requests consume inference. ' if definition.get('live_prefixes') else 'Local single-owner worker. Completed/imported snapshots only. ') + 'Missing observations are not negative detections. Audits verify source/cache consistency, not semantic accuracy. Waiting candidate jobs resume on a changed request-bound file handoff; unchanged responses and other blocked jobs require explicit retry.'}
