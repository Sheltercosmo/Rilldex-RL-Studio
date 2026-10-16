"""Repeatable capture -> frozen SQL analysis -> atomic output publication.

No model calls, remote execution, shell snippets or automatic package installs.
"""
import io
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import zipfile

from .analytics import Analysis, VIEWS, EXPORT_PROFILES
from .collector_lock import ProducerLock
from .schema import InputError, digest, dumps

VERSION = 'rilldex-workflow/1'
FILENAME = 'rilldex.json'
DEFAULT_QUERIES = [
    {'name': 'activity_counts', 'sql': 'SELECT observer, activity, COUNT(*) AS units FROM rl_nodes WHERE activity IS NOT NULL GROUP BY observer, activity ORDER BY observer, units DESC'},
    {'name': 'saved_measures', 'sql': 'SELECT observer, metric, status, COUNT(*) AS observations FROM rl_measurements GROUP BY observer, metric, status ORDER BY observer, metric, status'},
]


def _atomic_json(path,value):
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        temporary=Path(f.name)
        try:f.write(dumps(value)+'\n')
        except BaseException:
            f.close();temporary.unlink(missing_ok=True)
            raise
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def recipe(*, database='workspace/tracker.sqlite', source=None, experiment=None, observer=None, history=False, tables=None, format='jsonl', publish_interval=300, ui_port=8765):
    return {'schema': VERSION, 'database': database, 'source': source,
            'scope': {'experiment': experiment, 'observer': observer, 'history': history},
            'outputs': 'results', 'format': format, 'tables': tables or [n for n in VIEWS if n != 'sources'],
            'queries': [dict(q) for q in DEFAULT_QUERIES], 'interval': 10,
            'publish_interval': publish_interval, 'ui_port': ui_port}


def package_request(body, database):
    """Build files only; never run collection, SQL or model inference on download."""
    if not isinstance(body,dict):raise InputError('Supply workflow package settings')
    if set(body) == {'config'}:
        return package(body['config'])
    if set(body) in ({'launch'}, {'launch','publish_interval'}):
        launch = body['launch']
        if not isinstance(launch, dict) or launch.get('schema') not in ('rilldex-launch/1', 'jev-launch/1'):
            raise InputError('Supply a valid launch profile')
        source = launch.get('source')
        if not isinstance(source, dict): raise InputError('Launch profile needs a source')
        source = dict(source)
        if not isinstance(source.get('metadata',{}),dict):raise InputError('Source metadata must be an object')
        interval = source.pop('interval', 10)
        value = recipe(database=launch.get('database'), source=source, ui_port=launch.get('port', 8765), publish_interval=body.get('publish_interval',300),
            experiment=(source.get('metadata') or {}).get('experiment'))
        value['interval'] = interval
        return package(value)
    if set(body) != {'analysis'} or not isinstance(body['analysis'], dict):
        raise InputError('Supply config or analysis settings')
    settings = body['analysis']
    if set(settings) - {'experiment', 'observer', 'history', 'format', 'profile', 'table', 'publish_interval'}:
        raise InputError('Unknown analysis package setting')
    profile = settings.get('profile', 'research')
    if not isinstance(profile,str):raise InputError('Unknown export profile')
    if profile == 'table':
        tables = [settings.get('table')]
    elif profile in EXPORT_PROFILES:
        tables = list(EXPORT_PROFILES[profile])
    else:
        raise InputError('Unknown export profile')
    return package(recipe(database=str(Path(database).resolve()), tables=tables,
        **{key: settings[key] for key in ('experiment', 'observer', 'history', 'format', 'publish_interval') if key in settings}))


def validate(value):
    if not isinstance(value, dict) or value.get('schema') != VERSION or set(value) - {'schema','database','source','scope','outputs','format','tables','queries','interval','publish_interval','ui_port'}:
        raise InputError('Use a rilldex-workflow/1 configuration')
    result = json.loads(dumps(value))
    for key in ('database','outputs'):
        if not isinstance(result.get(key), str) or not result[key].strip() or len(result[key]) > 4096 or any(ord(c)<32 for c in result[key]):
            raise InputError(key + ' must be a nonempty local path')
        if '://' in result[key]: raise InputError(key + ' must be on local disk')
    scope = result.get('scope', {})
    if not isinstance(scope, dict) or set(scope)-{'experiment','observer','history'}: raise InputError('Unknown workflow scope')
    for key in ('experiment','observer'):
        if scope.get(key) is not None and (not isinstance(scope[key], str) or not scope[key].strip()): raise InputError('Invalid scope '+key)
    if type(scope.get('history',False)) is not bool: raise InputError('history must be boolean')
    source = result.get('source')
    if source is not None:
        if not isinstance(source, dict) or set(source)-{'root','producer','mode','format','metadata','pattern','snapshot_state','max_files','max_records'}: raise InputError('Unknown workflow source settings')
        for key in ('root','producer'):
            if not isinstance(source.get(key), str) or not source[key].strip() or len(source[key]) > (240 if key=='producer' else 4096) or any(ord(c)<32 for c in source[key]): raise InputError('Invalid source '+key)
        if '://' in source['root']:
            from .cloud_watch import source as cloud_source
            cloud_source(source['root'])
        from .adapters import FORMATS
        if not isinstance(source.get('format', 'auto'), str) or source.get('format', 'auto') not in FORMATS:
            raise InputError('Unknown source format')
        if source.get('mode','native') not in ('native','exports','snapshots'): raise InputError('Unknown source mode')
        if not isinstance(source.get('metadata',{}),dict): raise InputError('Source metadata must be an object')
        from .schema import metadata
        meta = metadata(source.get('metadata', {}))
        mode = source.get('mode', 'native')
        if mode != 'native' and not meta.get('experiment'): raise InputError('JSON/JSONL capture requires metadata.experiment')
        if mode == 'native' and source.get('format', 'auto') not in ('auto','harbor','swe-agent'): raise InputError('Native capture supports auto, harbor or swe-agent')
        if mode != 'exports' and 'max_records' in source: raise InputError('max_records requires exports mode')
        for key in ('max_files', 'max_records'):
            bound = 10000 if key == 'max_records' else 100000
            if key in source and (type(source[key]) is not int or not 1 <= source[key] <= bound):
                raise InputError(key+' must be 1–'+str(bound))
        if 'pattern' in source:
            pattern = source['pattern']
            if mode == 'native' or not isinstance(pattern,str) or not pattern.endswith('.jsonl' if mode=='exports' else '.json') or any(c in pattern for c in '/\\\r\n'):
                raise InputError('Source pattern must be a filename glob for its JSON/JSONL mode')
        if 'snapshot_state' in source and (mode != 'snapshots' or source['snapshot_state'] not in ('in_progress', 'complete')):
            raise InputError('Snapshot state must be in_progress or complete')
    if result.get('format') not in ('jsonl','csv'): raise InputError('Choose jsonl or csv output')
    tables = result.get('tables')
    if not isinstance(tables,list) or not tables or any(not isinstance(n,str) or n not in VIEWS for n in tables) or len(tables)!=len(set(tables)):
        raise InputError('Choose distinct research table names')
    queries = result.get('queries',[])
    if not isinstance(queries,list) or len(queries)>12: raise InputError('Use at most 12 saved SQL queries')
    names = set()
    for q in queries:
        if not isinstance(q,dict) or set(q)-{'name','sql','parameters','limit'}: raise InputError('Unknown saved query settings')
        if not isinstance(q.get('name'),str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',q['name']) or q['name'] in names: raise InputError('Use unique short query names')
        names.add(q['name'])
        if not isinstance(q.get('sql'),str) or not q['sql'].strip() or len(q['sql'])>100000: raise InputError('Supply bounded SQL text')
        if not isinstance(q.get('parameters',[]),list): raise InputError('Query parameters must be an array')
        if type(q.get('limit',5000)) is not int or not 1<=q.get('limit',5000)<=100000: raise InputError('Query limit must be 1–100000')
    interval = result.get('interval',10)
    if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not .2<=interval<=86400: raise InputError('Workflow interval must be 0.2–86400 seconds')
    cadence = result.get('publish_interval',0)
    if isinstance(cadence,bool) or not isinstance(cadence,(int,float)) or not 0<=cadence<=86400: raise InputError('Publication interval must be 0–86400 seconds; zero publishes every cycle')
    if type(result.get('ui_port',8765)) is not int or not 0<=result.get('ui_port',8765)<=65535: raise InputError('UI port must be 0–65535')
    return result


def config_path(path):
    path = Path(path).expanduser().resolve()
    return path / FILENAME if path.is_dir() else path


def read(path):
    path = config_path(path)
    if path.stat().st_size > 512*1024: raise InputError('Workflow configuration exceeds 512 KiB')
    return path, validate(json.loads(path.read_text(encoding='utf-8-sig')))


RUNNER = '''"""Run this package with Python 3.11+. No installation needed when runtime/ is bundled."""
from pathlib import Path
import sys
root = Path(__file__).resolve().parent
if sys.version_info < (3, 11): raise SystemExit("Rilldex needs Python 3.11 or newer")
if (root / "runtime").is_dir(): sys.path.insert(0, str(root / "runtime"))
try:
    from tracker.cli import main
except ImportError:
    raise SystemExit("Install Rilldex in this Python environment, or download the portable workflow package.")
if sys.argv[1:2] == ["ui"]:
    from tracker.workflows import Workflow
    with Workflow(root) as job:
        main(["--db", str(job.database), "start", "--port", str(job.config.get("ui_port", 8765)), *sys.argv[2:]])
elif sys.argv[1:2] == ["status"]:
    main(["workflow", "status", str(root), *sys.argv[2:]])
else:
    main(["workflow", "run", str(root), *sys.argv[1:]])
'''

README = '''# Rilldex workflow

1. Review paths and scope in `rilldex.json`. Relative paths start beside that file.
2. Run `python run.py --check` for local preflight without collecting data.
3. Run `python run.py` for a batch, or `python run.py --follow` to keep updating.

Windows, Linux, macOS and notebooks use the same Python entry point. A packaged
runtime needs Python 3.11+ and no installation for local capture, SQL and exports.
For S3/GCS, run `python -m pip install -r requirements.txt` in that Python
environment and configure host credentials. Local workflows need no install.
No environment credentials or training data are included in this package.

`results/latest.json` points to the last complete generation. That directory
contains data.sqlite (all scoped research tables), analysis.json (saved query
results and coverage), tables.zip (the chosen export), and manifest.json.
Every output in one generation comes from the same frozen database snapshot.
Edit `queries` to add read-only SQL over rl_* tables; excessive/truncated queries
fail publication rather than silently publishing incomplete findings.

Stop with Ctrl+C; repeat the same command to catch up. Incomplete source records
are deferred; accepted records can publish with pending capture explicitly marked.
Failed analysis keeps the previous complete output. Revisions/cursors are reused;
unchanged content reuses its generation. Retained generations are not auto-deleted.
Follow mode continues collection after analysis errors and retries publication on
its next cycle. Capture polls every `interval` seconds between operations; full
exports run every `publish_interval` seconds (default 300). Operations are serial:
large exports delay the next collection poll. Use receipt feeds for incremental
analysis at larger scale. One batch always attempts publication immediately.
Do not run two collectors for the same producer. Set source to null to analyze
a database already maintained by the UI, a remote transfer, or another collector.
Restart after changing the configuration. No semantic/model calls are made.

Inspect `python run.py status`: results/status.json reports capture, errors and
the last publication. It is a last report, not proof of process liveness.
Ctrl+C and SIGTERM unwind safely; restart with the same folder and database.
Preflight exits 0 when locally ready, 2 while waiting for a missing source, 1 when
blocked. It does not verify cloud credentials, every record or saved query SQL.
Keep live SQLite on local disk, not NFS/Drive. Copy frozen datasets or use the
existing HTTP/outbox integration for remote workers. Do not copy a live .sqlite
file alone; use workspace backup when moving the complete active workspace.

For the app: `python run.py ui` in a second terminal uses configured ui_port.
Override with `python run.py ui --port 9898`; add --open for a local browser.
Remote users keep the listener on loopback and forward the port over SSH.
For custom Python: use tracker.research.Analysis on the data.sqlite referenced
by latest.json, or the existing Research API for your own resumable calculations.
This is a local workflow, not a distributed scheduler. Export limits are bounded;
scope a large job by experiment/observer instead of exporting the entire cluster.
'''


def initialize(directory, value):
    value = validate(value)
    directory = Path(directory).expanduser().resolve()
    # Refuse to merge over existing project files or user outputs.
    directory.mkdir(parents=True, exist_ok=False)
    (directory/FILENAME).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    (directory/'run.py').write_text(RUNNER,encoding='utf-8')
    (directory/'README.md').write_text(README,encoding='utf-8')
    (directory/'requirements.txt').write_text(requirements(value),encoding='utf-8')
    return str(directory/FILENAME)


def requirements(value):
    root=(value.get('source') or {}).get('root','')
    if root.startswith('s3://'): return 's3fs>=2024.6.0\n'
    if root.startswith(('gs://','gcs://')): return 'gcsfs>=2024.6.0\n'
    return '# Local capture, SQL and exports use the Python standard library.\n'


def package(value):
    value = validate(value)
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name, text in [(FILENAME,json.dumps(value,indent=2)+'\n'),('run.py',RUNNER),('README.md',README),('requirements.txt',requirements(value))]: archive.writestr(name,text)
        base = Path(__file__).parent
        for directory in (base, base.parent/'rilldex'):
            for path in sorted(directory.rglob('*')):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()) and '__pycache__' not in path.parts and path.suffix in {'.py','.html','.css','.js','.svg','.md','.json'}:
                    archive.write(path,'runtime/'+directory.name+'/'+path.relative_to(directory).as_posix())
    if len(output.getvalue()) > 20*1024*1024: raise InputError('Workflow runtime exceeds package size limit')
    return output.getvalue()


class Workflow:
    def __init__(self,path):
        self.path,self.config=read(path)
        self.database=self.local(self.config['database'])
        self.output=self.local(self.config['outputs'])
        if self.database == self.output or self.database.is_relative_to(self.output): raise InputError('Keep the live workspace outside the output generations directory')
        self._connection=None
        self._version=None
        self._identity=None
        self._watcher=None
        self._leased=False
        self._publication={}
        self._last_capture=None
        self._capture_at=None
        self._status_error=None

    def local(self,path):
        from pathlib import PureWindowsPath
        if os.name!='nt' and PureWindowsPath(path).drive: raise InputError('Update Windows paths for this host')
        p=Path(path).expanduser()
        return (p if p.is_absolute() else self.path.parent/p).resolve()

    def _boundaries(self):
        source=self.config.get('source')
        if source and '://' not in source['root']:
            root=self.local(source['root'])
            if self.output.is_relative_to(root): raise InputError('Keep workflow outputs outside the watched source directory')
            if self.database.is_relative_to(root): raise InputError('Keep the live database outside the watched source directory')
        if self.path.is_relative_to(self.output): raise InputError('Keep configuration outside the output generations directory')

    def check(self):
        """Local preflight, without opening a writer, fetching cloud objects or creating paths."""
        self._boundaries()
        source=self.config.get('source')
        checks=[]
        def add(name,state,detail): checks.append(dict(name=name,state=state,detail=detail))
        if self.database.exists():
            try:
                Analysis(self.database).catalog()
                add('database','ready','Existing research tables can be read')
            except (InputError,OSError,sqlite3.Error) as error:
                add('database','blocked',str(error)[:1000])
        else:
            add('database','ready' if source else 'blocked','Created after source becomes available' if source else 'Point database to an existing workspace or dataset')
        if source:
            root=source['root']
            if '://' in root:
                from .cloud_watch import BACKENDS, source as cloud_source
                backend=BACKENDS[cloud_source(root)[0]][1]
                installed=importlib.util.find_spec(backend) is not None
                add('source','ready' if installed else 'blocked','Client installed; credentials and bucket access are not checked' if installed else 'Install generated requirements.txt on the collector host')
            else:
                path=self.local(root)
                if not path.exists():add('source','waiting','Directory is missing. The runner will wait; check that the expected mount is available.')
                elif not path.is_dir():add('source','blocked','Source is a file; select its output directory')
                elif not os.access(path,os.R_OK | os.X_OK):add('source','blocked','Source directory cannot be read')
                else:add('source','ready','Directory is accessible; record formats are checked during capture')
        for name,path in [('outputs',self.output),('database directory',self.database.parent)]:
            if name=='database directory' and not source:continue
            parent=path
            while not parent.exists():parent=parent.parent
            add(name,'ready' if parent.is_dir() and os.access(parent,os.W_OK | os.X_OK) else 'blocked',
                'Parent access checked; free space, quotas and network filesystem semantics require host verification')
        state='blocked' if any(c['state']=='blocked' for c in checks) else 'waiting' if any(c['state']=='waiting' for c in checks) else 'ready'
        return {'schema':VERSION,'database':str(self.database),'outputs':str(self.output),'source':source,
                'scope':self.config.get('scope',{}),'queries':[q['name'] for q in self.config.get('queries',[])],
                'database_exists':self.database.is_file(),'status':state,'checks':checks,
                'note':'Local preflight only: no collection, source writes, SQL execution or cloud requests. Keep live SQLite on local disk; share frozen datasets or use remote ingestion.'}

    def _previous(self):
        latest=self.output/'latest.json'
        if not latest.exists():return None
        previous=json.loads(latest.read_text(encoding='utf-8'))
        if not isinstance(previous,dict) or previous.get('schema')!=VERSION or not re.fullmatch(r'snapshot-[a-f0-9]+',str(previous.get('generation',''))):
            raise InputError('Output directory contains an unrelated latest.json; choose another outputs directory')
        return previous

    @contextmanager
    def session(self):
        """Hold ownership between follow cycles as well as while writing."""
        if self._leased:
            yield self
            return
        self._boundaries()
        self.output.mkdir(parents=True,exist_ok=True)
        with ExitStack() as stack:
            stack.enter_context(ProducerLock(SimpleNamespace(path=self.output/'workflow'),'workflow-publication'))
            previous=self._previous()
            if previous and not self._publication:
                self._publication={'status':'available',**previous}
            if self.config.get('source'):
                stack.enter_context(ProducerLock(SimpleNamespace(path=self.database),self.config['source']['producer']))
            self._leased=True
            try:yield self
            finally:self._leased=False

    def _write_status(self,phase,**fields):
        value={'schema':VERSION,'phase':phase,'updated_at':datetime.now(timezone.utc).isoformat(),
               'pid':os.getpid(),'host':socket.gethostname(),'config_hash':digest(self.config),'capture':self._last_capture,'capture_checked_at':self._capture_at,
               'publication':self._publication,**fields}
        _atomic_json(self.output/'status.json',value)
        return value

    def _record_status(self,phase,**fields):
        try:
            value=self._write_status(phase,**fields)
            self._status_error=None
            return value
        except OSError as error:
            # Health output can be full/unwritable while the capture database is
            # still healthy. Surface that failure in the receipt, without dropping intake.
            self._status_error={'stage':'status','type':type(error).__name__,'message':str(error)[:1000]}
            return {'phase':phase,'health_error':self._status_error}

    def status(self):
        path=self.output/'status.json'
        if not path.is_file():return {'schema':VERSION,'phase':'not_started','note':'No saved runner status in this output directory'}
        if path.stat().st_size>256*1024:raise InputError('Workflow status exceeds 256 KiB')
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('schema')!=VERSION:raise InputError('Unrecognized workflow status')
        age=max(0,time.time()-datetime.fromisoformat(value['updated_at']).timestamp())
        return {**value,'age_seconds':round(age,1),'config_matches':value.get('config_hash')==digest(self.config),
                'heartbeat_overdue':value['phase']!='stopped' and age>max(60,3*self.config.get('interval',10)),
                'note':'Status is a last report, not process liveness. A long capture/export can delay the heartbeat. latest.json is the last complete dataset.'}

    def stopped(self):
        return self._record_status('stopped')

    def _capture(self,max_polls=100):
        source=self.config.get('source')
        if not source: return None
        from .store import Store
        from .connections import validate as connection
        source=dict(source)
        if '://' not in source['root']:
            source['root']=str(self.local(source['root']))
            if Path(source['root']).exists() and not Path(source['root']).is_dir():raise InputError('Source must be a directory')
            if not Path(source['root']).is_dir(): return {'status':'waiting','reason':'Source directory is not available yet; check its mount if training is running','ingested':0}
        if self._watcher is None:
            store=Store(self.database)
            _,self._watcher=connection(store,source)
        watcher=self._watcher
        ingested=0
        for _ in range(max_polls):
            report=watcher.poll();ingested+=report['ingested']
            if not report.get('backlog'): break
        pending=bool(report.get('backlog') or report.get('waiting') or report.get('deferred'))
        entries=report.get('entries',[])
        report={**report,'entries':entries[:10],'entries_total':len(entries),'entries_limited':len(entries)>10}
        return {'status':'waiting' if pending else 'ready','ingested':ingested,'report':report}

    def run(self, *, publish=True, resilient=False, max_polls=100):
        """Capture durably, then optionally publish. Follow mode can retain analysis errors."""
        if type(max_polls) is not int or not 1<=max_polls<=100:raise InputError('max_polls must be 1–100')
        with self.session():
            phase='capture'
            try:
                self._record_status('capturing')
                capture=self._capture(max_polls=max_polls)
                self._last_capture=capture
                self._capture_at=datetime.now(timezone.utc).isoformat()
                pending=bool(capture and capture['status']=='waiting')
                if pending and not self.database.is_file():
                    result={'status':'waiting','capture':capture,'pending':True,'published':False}
                elif not publish:
                    result={'status':'collected','capture':capture,'pending':pending,'published':False}
                else:
                    phase='publication'
                    self._record_status('publishing')
                    if not self.database.is_file():raise InputError('Workspace is missing; connect a source or point database to an existing workspace')
                    result=self._publish(capture,pending)
                    self._publication={k:v for k,v in result.items() if k not in ('capture','pending')}
                self._record_status('idle',pending=pending)
                return {**result,**({'publication_error':self._publication['error']} if self._publication.get('error') else {}),
                        **({'health_error':self._status_error} if self._status_error else {})}
            except (InputError,OSError,sqlite3.Error,ValueError) as error:
                issue={'stage':phase,'type':type(error).__name__,'message':str(error)[:1000]}
                if phase=='publication':self._publication={**self._publication,'status':'error','error':issue}
                self._record_status('error',error=issue)
                if not resilient:raise
                return {'status':'error','error':issue,'capture':self._last_capture,'published':False,
                        **({'health_error':self._status_error} if self._status_error else {})}

    def _publish(self,capture,pending):
        previous=self._previous()
        latest=self.output/'latest.json'
        stat=self.database.stat()
        identity=(stat.st_dev,stat.st_ino)
        if identity!=self._identity:
            self.close();self._version=None;self._identity=identity
        if self._connection is None:self._connection=sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)
        version=self._connection.execute('PRAGMA data_version').fetchone()[0]
        if version==self._version and previous and previous.get('config_hash')==digest(self.config):
            if all((self.output/previous['generation']/f).is_file() for f in ('data.sqlite','analysis.json','tables.zip','manifest.json')):
                return {'status':'unchanged',**previous,'capture':capture,'pending':pending}
        scope=self.config.get('scope',{})
        with tempfile.TemporaryDirectory(prefix='.pending-',dir=self.output) as temp:
            staging=Path(temp)
            manifest=Analysis(self.database).database(staging/'data.sqlite',**scope,include_sources='sources' in self.config['tables'])
            fingerprint=digest({'config':self.config,'tables':manifest['tables']})
            generation='snapshot-'+fingerprint
            manifest['path']='data.sqlite'
            destination=self.output/generation
            if not destination.exists():
                frozen=Analysis(staging/'data.sqlite')
                queries={}
                for q in self.config.get('queries',[]):
                    result=frozen.query(q['sql'],q.get('parameters',[]),limit=q.get('limit',5000))
                    if result['truncated']:raise InputError('Query '+q['name']+' exceeds its limit; narrow it before publishing')
                    queries[q['name']]=result
                report={'schema':VERSION,'captured_at':manifest['captured_at'],'scope':scope,'tables':manifest['tables'],'queries':queries,
                        'note':'Counts describe saved evidence. Missing semantic observations are not generated; unavailable tables remain explicit.'}
                raw=dumps(report)
                if len(raw.encode('utf-8'))>64*1024*1024:raise InputError('Combined query output exceeds 64 MiB')
                (staging/'analysis.json').write_text(raw+'\n',encoding='utf-8')
                frozen.export(staging/'tables.zip',tables=self.config['tables'],format=self.config['format'],**scope)
                (staging/'manifest.json').write_text(dumps({'schema':VERSION,'generation':generation,'dataset':manifest,'queries':self.config.get('queries',[])})+'\n',encoding='utf-8')
                # Atomic directory move; latest is advanced only after all outputs exist.
                staging.rename(destination)
            else:
                if not all((destination/f).is_file() for f in ('data.sqlite','analysis.json','tables.zip','manifest.json')):
                    raise InputError('An existing output generation is incomplete; preserve it and choose a new outputs directory')
            pointer={'schema':VERSION,'generation':generation,'config_hash':digest(self.config),'captured_at':json.loads((destination/'manifest.json').read_text(encoding='utf-8'))['dataset']['captured_at']}
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.output,delete=False) as f:
                pending_file=Path(f.name);f.write(dumps(pointer)+'\n')
            try:os.replace(pending_file,latest)
            finally:pending_file.unlink(missing_ok=True)
        self._version=version
        return {'status':'unchanged' if previous and previous['generation']==generation else 'published',**pointer,'capture':capture,'pending':pending}

    def close(self):
        if self._connection is not None:self._connection.close();self._connection=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
