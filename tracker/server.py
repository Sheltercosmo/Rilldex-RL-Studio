"""Loopback application with explicit read-only directory connections."""
from __future__ import annotations

import json
import mimetypes
import os
import socket
import signal
import sqlite3
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .adapters import normalize
from .compare import compare
from .comparison_evidence import evidence as comparison_evidence, ComparisonChanged
from .jev import DEFAULT_MODEL
from .jobs import Worker
from .schema import InputError, dumps
from .reviews import options as review_options
from .store import ReviewConflict

WEB = Path(__file__).parent / "web"
MAX_BODY = 20 * 1024 * 1024


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    # Browsers open concurrent asset/API connections. The stdlib backlog of five
    # can refuse one script during navigation bursts on Windows, leaving a page
    # at its loading placeholder without any application-level error handler.
    request_queue_size = 128

    def server_bind(self):
        # Windows otherwise permits a second HTTPServer to share the same port,
        # leaving requests split between old and new application processes.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer normally reverse-resolves this address. A local collector
        # needs no hostname lookup; unavailable DNS can stall macOS startup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def serve(store, host="127.0.0.1", port=8765, *, open_browser=False, container=False,
          workspace_directory=None, stop_event=None, on_ready=None):
    if container:
        host = '0.0.0.0'
    elif host not in {"127.0.0.1", "localhost", "::1"}:
        raise InputError("This version is a local research application; bind to loopback only")
    snapshot_lock = threading.Lock()
    context_review_lock = threading.Lock()
    from .model_pilot import ModelPilotService
    model_pilot = ModelPilotService(store)
    import uuid
    workspace_instance = uuid.uuid4().hex
    workspace_manager = None
    workspace_error = None
    if workspace_directory is None:
        from .workspace_directory import Directory
        try:
            workspace_directory = Directory()
        except (OSError,sqlite3.Error) as error:
            workspace_error = str(error)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def response(self, status, payload, mime="application/json; charset=utf-8", download_name=None):
            data = payload if isinstance(payload, bytes) else dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
            if self.headers.get("Host") not in allowed_hosts:
                self.response(403, {"error": "Invalid local host"}); return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in allowed_hosts}:
                self.response(403, {"error": "Cross-origin requests are not accepted"}); return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = unquote(urlsplit(self.path).path)
            params = parse_qs(urlsplit(self.path).query)
            try:
                if path in {'/context-mix.js','/context-mix.css'}:
                    return self.response(200,(WEB/path[1:]).read_bytes(),'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8')
                if path == '/api/context-mix':
                    from .context_mix import load
                    return self.response(200,load(store,params.get('run',[''])[0],params.get('event',[''])[0]),
                        download_name='context-mix.json' if params.get('download')==['1'] else None)
                if path == '/data-access.js':
                    return self.response(200,(WEB/'data-access.js').read_bytes(),'text/javascript; charset=utf-8')
                if path == '/native-analysis.js':
                    return self.response(200,(WEB/'native-analysis.js').read_bytes(),'text/javascript; charset=utf-8')
                if path.startswith('/api/analysis/'):
                    from .analytics import Analysis
                    analysis = Analysis(store.path)
                    options = {'experiment':params.get('experiment',[None])[0], 'history':params.get('history',['0'])[0]=='1'}
                    if path in ('/api/analysis/functions','/api/analysis/compute','/api/analysis/custom') or path.startswith('/api/analysis/custom/'):
                        from .workspace_analysis import Workspace
                        workspace=Workspace(store.path,**options,observer=params.get('observer',[None])[0])
                        if path=='/api/analysis/functions':
                            return self.response(200,{'functions':workspace.functions(),'database':str(workspace.data.path)})
                        if path=='/api/analysis/compute':
                            return self.response(200,workspace.analyze(params.get('function',['activity_counts'])[0],limit=int(params.get('limit',['1000'])[0])))
                        if path=='/api/analysis/custom':return self.response(200,workspace.saved_analyses(limit=100))
                        return self.response(200,workspace.results().results(path.rsplit('/',1)[-1],limit=100))
                    if path == '/api/analysis/catalog': return self.response(200,analysis.catalog())
                    if path == '/api/analysis/options': return self.response(200,analysis.options(**options))
                    if path == '/api/analysis/changes':
                        cursor=json.loads(params['cursor'][0]) if 'cursor' in params else None
                        return self.response(200,analysis.changes(params.get('feed',['sources'])[0],cursor=cursor,limit=int(params.get('limit',['100'])[0])))
                    if path.startswith('/api/analysis/tables/'):
                        result=analysis.table(path.rsplit('/',1)[-1],**options,observer=params.get('observer',[None])[0],limit=int(params.get('limit',['1000'])[0]))
                        return self.response(200,result,download_name='analysis-table.json' if params.get('download')==['1'] else None)
                    if path == '/api/analysis/export':
                        if not snapshot_lock.acquire(blocking=False):
                            return self.response(409,{'error':'Another archive is being prepared; retry after it finishes'})
                        try:
                            with tempfile.TemporaryDirectory(prefix='jev-analysis-download-') as directory:
                                archive=Path(directory)/'analysis.zip'
                                from .analytics import EXPORT_PROFILES
                                if 'profile' in params and ('table' in params or params['profile'][0] not in EXPORT_PROFILES):
                                    raise InputError('Choose one supported export profile or explicit tables')
                                selected={'tables':params['table']} if 'table' in params else {'tables':EXPORT_PROFILES[params['profile'][0]]} if 'profile' in params else {}
                                analysis.export(archive,**options,**selected,observer=params.get('observer',[None])[0],format=params.get('format',['jsonl'])[0])
                                return self.response(200,archive.read_bytes(),'application/zip',download_name='research-data.zip')
                        finally: snapshot_lock.release()
                    return self.response(404,{'error':'Unknown analysis endpoint'})
                if path == '/api/health':
                    with store.connect() as c:
                        c.execute('SELECT 1').fetchone()
                    return self.response(200, {'ready': True, 'service': 'rilldex'})
                if path == '/api/feature-readiness':
                    from .first_session import readiness
                    return self.response(200,readiness(store,experiment=params.get('experiment',[None])[0],environment=params.get('environment',[None])[0],run_ids=params.get('run')))
                if path == '/api/experiments':
                    from .experiment_catalog import catalog
                    return self.response(200,catalog(store,q=params.get('q',[''])[0],environment=params.get('environment',[None])[0],
                        limit=int(params.get('limit',['30'])[0]),offset=int(params.get('offset',['0'])[0]),
                        project=params.get('project',[None])[0],state=params.get('state',['active'])[0],search_in=params.get('search_in',['labels'])[0]))
                if path == '/api/run-records':
                    from .run_records import records
                    return self.response(200,records(store,experiment=params.get('experiment',[None])[0],
                        kind=params.get('kind',[None])[0],q=params.get('q',[''])[0],after=int(params.get('after',['0'])[0]),
                        limit=int(params.get('limit',['100'])[0]),producer=params.get('producer',[None])[0],
                        session=params.get('session',[None])[0],tail=params.get('tail',['0'])[0]=='1',
                        observed_from=params.get('observed_from',[None])[0],observed_to=params.get('observed_to',[None])[0],
                        as_of=int(params['as_of'][0]) if 'as_of' in params else None))
                if path == '/api/hardware-history':
                    from .hardware_history import query
                    return self.response(200,query(store,experiment=params.get('experiment',[None])[0],
                        producer=params.get('producer',[None])[0],session=params.get('session',[None])[0],
                        observed_from=params.get('observed_from',[None])[0],observed_to=params.get('observed_to',[None])[0],
                        as_of=int(params['as_of'][0]) if 'as_of' in params else None,
                        points=int(params.get('points',['160'])[0]),offset=int(params.get('offset',['0'])[0]),
                        limit=int(params.get('limit',['6'])[0])))
                if path == '/api/run-file':
                    from .run_records import file_content
                    from urllib.parse import quote
                    name,data=file_content(store,experiment=params.get('experiment',[''])[0],sequence=int(params.get('sequence',['0'])[0]))
                    return self.response(200,data,'application/octet-stream',download_name=quote(name,safe='._-'))
                if path == '/api/workspace-identity':
                    import hashlib
                    key=hashlib.sha256(str(store.path.resolve()).encode()).hexdigest()
                    label=workspace_manager.directory.get(key)['name'] if workspace_manager else store.path.name
                    return self.response(200,dict(name=store.path.name,label=label,identity=key,instance=workspace_instance))
                if path == '/api/workspaces':
                    if workspace_manager is None:
                        return self.response(503,{'error':'Workspace picker unavailable: '+str(workspace_error)})
                    return self.response(200,workspace_manager.catalog())
                if path == '/api/experiment-details':
                    from .experiment_details import details
                    return self.response(200,details(store,experiment=params.get('experiment',[None])[0],
                        environment=params.get('environment',[None])[0],section=params.get('section',['settings'])[0],
                        q=params.get('q',[''])[0],limit=int(params.get('limit',['20'])[0]),offset=int(params.get('offset',['0'])[0])))
                if path == '/api/models':
                    return self.response(200,model_pilot.status())
                if path == '/api/workspace/snapshot':
                    if not snapshot_lock.acquire(blocking=False):
                        return self.response(409,{'error':'A workspace snapshot is already being prepared; retry when its download finishes'})
                    started_response = False
                    try:
                        from .workspace_snapshot import export as export_workspace
                        with tempfile.TemporaryDirectory(prefix='jev-download-') as directory:
                            archive = Path(directory)/'workspace.rilldex.zip'
                            export_workspace(store,archive)
                            self.send_response(200)
                            self.send_header('Content-Type','application/zip')
                            self.send_header('Content-Disposition','attachment; filename="workspace.rilldex.zip"')
                            self.send_header('Content-Length',str(archive.stat().st_size))
                            self.send_header('Cache-Control','no-store')
                            self.send_header('X-Content-Type-Options','nosniff')
                            self.end_headers()
                            started_response = True
                            with archive.open('rb') as stream:
                                for chunk in iter(lambda:stream.read(1024*1024),b''):
                                    self.wfile.write(chunk)
                    except (OSError,sqlite3.Error) as e:
                        if not started_response:
                            return self.response(400,{'error':'Workspace snapshot failed: '+str(e)})
                    finally:
                        snapshot_lock.release()
                    return
                if path == '/api/live/events':
                    self.send_response(200)
                    self.send_header('Content-Type','text/event-stream')
                    self.send_header('Cache-Control','no-cache')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers()
                    sequence = None
                    self.connection.settimeout(20)
                    try:
                        while not intake_service.stop.is_set():
                            sequence, state = intake_service.wait(sequence)
                            if state is None:continue
                            data = f'id: {intake_service.session}:{sequence}\nevent: state\ndata: {dumps(state)}\n\n'
                            self.wfile.write(data.encode());self.wfile.flush()
                    except (OSError,TimeoutError):pass
                    return
                if path == '/api/connections':
                    return self.response(200,intake_service.snapshot())
                if path == '/api/integrations':
                    from .integrations import catalog
                    return self.response(200,catalog())
                if path == '/api/investigation-readiness/options':
                    from .investigation_readiness import options
                    return self.response(200,options(store))
                if path == '/api/training-populations':
                    from .training_lineage import snapshot
                    return self.response(200,snapshot(store,**{k:params[k][0] for k in ('experiment','environment','monitor','selection') if k in params}))
                if path == '/api/generation-cohorts':
                    from .generation_cohorts import snapshot
                    return self.response(200,snapshot(store,experiment=params.get('experiment',[''])[0],
                        environment=params.get('environment',[None])[0],monitor=params.get('monitor',[None])[0],
                        include_members=params.get('members',['0'])[0]=='1',
                        clock=params.get('clock',[None])[0],basis=params.get('basis',[None])[0],
                        limit=int(params.get('limit',['100'])[0]),cohort_id=params.get('cohort',[None])[0],
                        producer=params.get('producer',[None])[0]))
                if path == '/api/trainer-telemetry/evidence':
                    from .telemetry_evidence import evidence
                    return self.response(200,evidence(store,**{k:params.get(k,[''])[0] for k in ('producer','experiment','record_id')}))
                if path == '/api/trainer-telemetry/context':
                    from .run_records import trainer_context
                    return self.response(200,trainer_context(store,**{k:params.get(k,[''])[0] for k in ('producer','experiment','session')},
                        as_of=int(params['as_of'][0]) if 'as_of' in params else None))
                if path in {'/api/trainer-telemetry/query','/api/trainer-telemetry/catalog','/api/trainer-telemetry/points','/api/trainer-telemetry/export','/api/trainer-telemetry/sessions'}:
                    from . import telemetry_queries as tq
                    common={k:params[k][0] for k in ('experiment','environment','clock') if k in params}
                    frozen={'as_of':int(params['as_of'][0])} if 'as_of' in params else {}
                    interval={k:json.loads(params[k][0]) for k in ('start','end') if k in params}
                    if path.endswith('/sessions'):
                        return self.response(200,tq.sessions(store,**common,**frozen,search=params.get('search',[''])[0],
                            limit=int(params.get('limit',['50'])[0]),offset=int(params.get('offset',['0'])[0])))
                    common.update({k:params[k][0] for k in ('producer','session','session_mode') if k in params})
                    if path.endswith('/catalog'):
                        return self.response(200,tq.catalog(store,**common,**frozen,search=params.get('search',[''])[0],
                            group=params.get('group',[None])[0],limit=int(params.get('limit',['100'])[0]),offset=int(params.get('offset',['0'])[0])))
                    if path.endswith('/points'):
                        return self.response(200,tq.points(store,series_id=params.get('series',[''])[0],**frozen,**interval,
                            after=json.loads(params['after'][0]) if 'after' in params else None,limit=int(params.get('limit',['100'])[0])))
                    if path.endswith('/export'):
                        cutoff,packets=tq.export_records(store,**common,**frozen,**interval)
                        self.send_response(200)
                        self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
                        self.send_header('Content-Disposition','attachment; filename="rilldex-telemetry.jsonl"')
                        self.send_header('X-Rilldex-As-Of',str(cutoff))
                        self.send_header('X-Content-Type-Options','nosniff')
                        self.send_header('Cache-Control','no-store')
                        self.send_header('Connection','close');self.end_headers();self.close_connection=True
                        try:
                            for packet in packets:self.wfile.write((dumps(packet)+'\n').encode('utf-8'))
                        except (BrokenPipeError,ConnectionResetError):pass
                        return
                    return self.response(200,tq.query(store,**common,**frozen,**interval,
                        max_points=int(params.get('max_points',['240'])[0]),half_life=int(params.get('half_life',['0'])[0]),
                        series_ids=params.get('series',[])))
                if path == '/api/training-execution':
                    from . import execution_timeline
                    if 'saved' in params:return self.response(200,execution_timeline.load(store,params['saved'][0]))
                    options={'experiment':params.get('experiment',[''])[0],**{k:params[k][0] for k in ('environment','clock') if k in params}}
                    options.update({k:float(params[k][0]) for k in ('start','end') if k in params})
                    options['limit']=int(params.get('limit',['1000'])[0])
                    return self.response(200,execution_timeline.snapshot(store,**options))
                if path == '/api/trainer-telemetry':
                    from .trainer_telemetry import snapshot
                    return self.response(200,snapshot(store,experiment=params.get('experiment',[None])[0],environment=params.get('environment',[None])[0],limit=int(params.get('limit',['1000'])[0])))
                if path in {'/trainer-telemetry.js','/trainer-telemetry.css','/training-execution.js','/training-execution.css','/configuration-comparison.js','/configuration-comparison.css'}:
                    return self.response(200,(WEB/path.lstrip('/')).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                if path == '/api/training-health':
                    from .training_health import snapshot
                    return self.response(200,snapshot(store,**{k:params[k][0] for k in ('experiment','environment','monitor','reward_x','reward_y') if k in params}))
                if path == '/api/continuation-studies':
                    from .continuation_studies import snapshot
                    return self.response(200,snapshot(store,**{k:params[k][0] for k in ('experiment','environment') if k in params},
                        limit=int(params.get('limit',['20'])[0]),offset=int(params.get('offset',['0'])[0])))
                if path in {'/interval-investigation.js','/interval-investigation.css','/continuation-studies.js','/continuation-studies.css','/investigation-followups.js','/investigation-followups.css','/investigation-trials.js'}:
                    return self.response(200,(WEB/path.lstrip('/')).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                if path == '/api/investigation-trials/options':
                    from .investigation_trials import options
                    return self.response(200,options(store,params.get('investigation',[''])[0],params.get('run',[None])[0]))
                if path == '/api/investigation-trials/manifest':
                    from .investigation_trials import manifest
                    return self.response(200,manifest(store,params.get('investigation',[''])[0],params.get('check',[''])[0]))
                if path == '/api/retained-rl-signal':
                    from .retained_rl_signals import inspect_source
                    return self.response(200,inspect_source(store,params.get('run',[''])[0]))
                if path == '/api/training-setup':
                    from .training_setup import examples
                    return self.response(200,examples())
                if path == '/api/training-spans':
                    from .training_spans import inspect_use
                    return self.response(200,inspect_use(store,{k:params.get('training_'+k,[''])[0] for k in ('schema','producer','experiment','id')},params.get('graph',[''])[0]))
                if path == '/api/training-recipes':
                    from .training_recipes import snapshot
                    return self.response(200,snapshot(store,params.get('experiment',[None])[0]))
                if path in {'/training-health.js', '/training-health.css', '/training-setup.js', '/training-setup.css', '/training-spans.js', '/training-spans.css'}:
                    return self.response(200,(WEB/path.lstrip('/')).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                if path == '/api/training-comparisons/options':
                    from .training_comparisons import options
                    return self.response(200,options(store))
                if path == '/training-populations.js':
                    return self.response(200,(WEB/'training-populations.js').read_bytes(),'text/javascript; charset=utf-8')
                if path == '/api/investigate':
                    from .failure_investigations import snapshot
                    return self.response(200,snapshot(store,**{k:params[k][0] for k in ('run','focus','scope','steps','limit','observer','signal','operator','threshold','reference') if k in params}))
                if path == '/api/monitoring/questions':
                    from .question_bundles import listing
                    return self.response(200,listing(store,params.get('experiment',[None])[0],params.get('environment',[None])[0]))
                if path == '/api/experiment-history':
                    from .investigation_workspace import history, EVENT_TYPES
                    return self.response(200,{'events':history(store,params.get('experiment',[''])[0],params.get('environment',[None])[0]),'kinds':EVENT_TYPES})
                if path == '/api/investigations':
                    from .failure_investigations import saved
                    return self.response(200,{'investigations':saved(store)})
                if path == '/api/case-comparisons':
                    from .case_comparisons import listing
                    return self.response(200,listing(store,params.get('investigation',[''])[0],
                        status=params.get('status',['all'])[0],offset=int(params.get('offset',['0'])[0]),limit=int(params.get('limit',['20'])[0])))
                if path == '/api/case-comparisons/scopes':
                    from .case_studies import catalog
                    return self.response(200,catalog(store))
                if path == '/api/case-comparisons/pair':
                    from .case_comparisons import pair
                    return self.response(200,pair(store,params.get('investigation',[''])[0],params.get('reference',[''])[0],params.get('selected',[''])[0],observer=params.get('observer',[None])[0]))
                if path.startswith('/api/work-state/'):
                    from .investigation_plans import read_output
                    return self.response(200,read_output(store,path.rsplit('/',1)[-1]))
                if path == '/api/investigation-operations':
                    from .investigation_plans import catalog
                    return self.response(200,catalog())
                if path == '/api/evaluations':
                    from .evaluation_receipts import listing
                    return self.response(200,listing(store,run_id=params.get('run_id',[''])[0],
                        limit=int(params.get('limit',['50'])[0]),offset=int(params.get('offset',['0'])[0])))
                if path == '/api/training-exposure':
                    from .training_exposure import snapshot
                    return self.response(200,snapshot(store,run_id=params.get('run_id',[''])[0],
                        source_hash=params.get('source_hash',[None])[0],experiment=params.get('experiment',[None])[0]))
                if path.startswith('/api/evaluations/'):
                    from .evaluation_receipts import read
                    return self.response(200,read(store,path.rsplit('/',1)[-1]))
                if path.startswith('/api/investigation-plans/'):
                    from .investigation_plans import read_plan
                    return self.response(200,read_plan(store,path.rsplit('/',1)[-1]))
                if path.startswith('/api/investigations/') and path.endswith('/measures'):
                    from . import case_behavior, failure_investigations
                    return self.response(200,case_behavior.options(store,failure_investigations.read(store,path.split('/')[-2])))
                if path.startswith('/api/investigations/') and path.endswith('/revisions'):
                    from .investigation_followups import revisions
                    return self.response(200,revisions(store,path.split('/')[-2]))
                if path.startswith('/api/investigations/') and path.endswith('/cases'):
                    from .investigation_cases import search
                    return self.response(200,search(store,path.split('/')[-2],
                        **{k:params[k][0] for k in ('family','cohort','status','feedback','q') if k in params},
                        limit=int(params.get('limit',['20'])[0]),offset=int(params.get('offset',['0'])[0])))
                if path.startswith('/api/investigations/') and path.endswith('/bundle'):
                    from .investigation_followups import bundle
                    return self.response(200,bundle(store,path.split('/')[-2]),download_name='rilldex-investigation.json' if params.get('download')==['1'] else None)
                if path.startswith('/api/investigations/') and path.endswith('/report'):
                    from .findings_report import render
                    html=render(store,path.split('/')[-2],origin=params.get('origin',[''])[0])
                    return self.response(200,html.encode('utf-8'),'text/html; charset=utf-8',
                                         download_name='rilldex-findings.html' if params.get('download')==['1'] else None)
                if path.startswith('/api/investigations/'):
                    from .failure_investigations import read
                    return self.response(200,read(store,path.rsplit('/',1)[-1]))
                if path == '/api/behavior-comparisons':
                    from .behavior_distributions import saved_comparisons
                    return self.response(200,{'comparisons':saved_comparisons(store,**{k:params[k][0] for k in ('experiment','environment') if k in params})})
                if path.startswith('/api/behavior-comparisons/'):
                    from .behavior_distributions import read_comparison
                    return self.response(200,read_comparison(store,path.rsplit('/',1)[-1]),download_name='behavior-comparison.json' if params.get('download')==['1'] else None)
                if path == '/api/behavior-distributions':
                    from .behavior_distributions import snapshot
                    return self.response(200,snapshot(store,**{k:params[k][0] for k in ('lens','grouping','observer','cohort_id','weighting','population_mode','a_start','a_end','b_start','b_end','experiment','environment','recurrence_order') if k in params}),download_name='behavior-distribution.json' if params.get('download')==['1'] else None)
                if path == '/api/strategies':
                    from .strategy_profiles import snapshot as strategy_snapshot
                    return self.response(200,strategy_snapshot(store,**{k:params[k][0] for k in ('family','measure','observer','cohort_id','experiment','environment','comparison') if k in params}))
                if path.startswith('/api/strategies/observations/'):
                    from .strategy_profiles import read as read_strategy
                    return self.response(200,read_strategy(store,path.rsplit('/',1)[-1]),download_name='strategy-evidence.json' if params.get('download')==['1'] else None)
                if path == '/api/monitoring/status':return self.response(200,monitor_service.status())
                if path == '/api/monitoring/alerts':
                    from .monitor_alerts import snapshot as alert_snapshot
                    return self.response(200,alert_snapshot(store))
                if path == '/api/monitoring/scans':
                    from .scan_progress import snapshot as scan_snapshot
                    return self.response(200,scan_snapshot(store,**{k:params[k][0] for k in ('experiment','environment') if k in params}))
                if path == '/api/monitoring/comparisons':
                    from .monitor_comparisons import listing
                    return self.response(200,listing(store,params.get('experiment',[None])[0]))
                if path.startswith('/api/monitoring/comparisons/'):
                    from .monitor_comparisons import read
                    return self.response(200,read(store,path.rsplit('/',1)[-1]),download_name='monitor-comparison.json' if params.get('download')==['1'] else None)
                if path == '/api/monitoring':
                    from .monitoring import live_snapshot
                    result=live_snapshot(store,monitor_service,params.get('experiment',[None])[0],params.get('environment',[None])[0])
                    return self.response(200,{**result,'capabilities':{'training_health':'training-health/15','reward_relationships':'reward-relationships/2','retained_rl_signals':'retained-rl-signals/1','value_observation':'value-observation/1','recovery_attempt':'recovery-attempt/1','attempt_outcome':'attempt-outcome/1','policy_clock':'policy-clock/1','generation_policy_history':'generation-policy-history/1','policy_age':'policy-age/1','policy_gradient':'policy-gradient-observation/1','training_token_source':'training-token-source/1','training_unit_exposure':'training-unit-exposure/1','training_recipes':'training-recipes/1','sampled_teacher_signal':'sampled-teacher-signal/1'}})
                if path == '/api/monitoring/options':
                    from .monitoring import options
                    return self.response(200,options(store))
                if path == '/api/monitoring/custom-inputs':
                    from .custom_monitors import input_snapshot
                    return self.response(200,input_snapshot(store,params.get('monitor',[''])[0],params.get('run',[''])[0]))
                if path.startswith('/api/monitoring/values/'):
                    from .monitor_evidence import read
                    evidence=read(store,path.rsplit('/',1)[-1],params.get('run',[None])[0])
                    return self.response(200,evidence,download_name='measurement-evidence.json' if params.get('download')==['1'] else None)
                if path == '/api/measurement-reviews':
                    from .measurement_reviews import listing
                    return self.response(200,listing(store,params.get('monitor',[''])[0]))
                if path.startswith('/api/detector-validation'):
                    from . import detector_validation as validation
                    if path=='/api/detector-validation':return self.response(200,validation.listing(store))
                    if path=='/api/detector-validation/compare':
                        return self.response(200,validation.compare(store,params.get('left',[''])[0],params.get('right',[''])[0]))
                    parts=path.strip('/').split('/')
                    if len(parts)==4 and parts[2] in {'sets','results'}:
                        result=(validation.case_view(store,parts[3],params['case'][0]) if 'case' in params and parts[2]=='sets'
                                else validation.load(store,parts[3],parts[2]=='results'))
                        return self.response(200,result,download_name='detector-validation.json' if params.get('download')==['1'] else None)
                    raise InputError('Unknown validation route')
                if path.startswith('/api/measurement-reviews/'):
                    from .measurement_reviews import public, case_view
                    sid=path.rsplit('/',1)[-1]
                    result=case_view(store,sid,params['case'][0],params.get('reviewer',[''])[0]) if 'case' in params else public(store,sid)
                    return self.response(200,result,download_name='measurement-review.json' if params.get('download')==['1'] else None)
                if path.startswith('/api/monitoring/cases/'):
                    from .monitoring import cases
                    return self.response(200,cases(store,path.rsplit('/',1)[-1],params.get('experiment',[None])[0],params.get('environment',[None])[0]))
                if path.startswith('/api/source-status/'):
                    return self.response(200,store.source_status(path.rsplit('/',1)[-1]))
                if path.startswith('/api/monitoring/rollout/'):
                    from .monitoring import rollout
                    return self.response(200,rollout(store,path.rsplit('/',1)[-1],params.get('observer',[None])[0],params.get('graph',[None])[0]))
                if path == '/api/workspace-status':
                    from .graph_store import status
                    return self.response(200,status(store))
                if path == '/api/graphs':
                    from .graph_store import catalog
                    return self.response(200,catalog(store))
                if path == '/api/relationship-reviews':
                    from .relation_reviews import template
                    from .graph_store import read
                    return self.response(200,template(read(store,params.get('graph',[''])[0]),params.get('unit',[''])[0]))
                if path == '/api/procedure-reviews':
                    from .procedure_reviews import template
                    from .graph_store import read
                    return self.response(200,template(read(store,params.get('graph',[''])[0]),
                        params.get('previous',[''])[0],params.get('current',[''])[0]))
                if path == '/api/work-subjects':
                    from .work_subjects import template
                    from .graph_store import read
                    return self.response(200,template(read(store,params.get('graph',[''])[0])))
                if path == '/api/work-scope-audit':
                    from .work_scope_audit import project
                    from .graph_store import read
                    return self.response(200,project(read(store,params.get('graph',[''])[0])),
                        download_name='work-scope-consistency.json' if params.get('download')==['1'] else None)
                if path == '/api/work-hierarchy':
                    from .work_hierarchy import build
                    from .graph_store import read
                    result=build(read(store,params.get('graph',[''])[0]),params.get('through',[None])[0])
                    return self.response(200,result,download_name='plans-and-attempts.json' if params.get('download')==['1'] else None)
                if path == '/api/map-foundation':
                    from .map_foundation import inspect
                    from .graph_store import read
                    graph=read(store,params.get('graph',[''])[0])
                    return self.response(200,inspect(graph,store.get(graph['run_id'],raw=True)['run']))
                if path == '/api/work-outline':
                    from .work_outline import template
                    from .graph_store import read
                    return self.response(200,template(read(store,params.get('graph',[''])[0])))
                if path == '/api/work-mentions':
                    from .work_mentions import project
                    from .graph_store import read
                    from .work_content_results import for_graph
                    graph=read(store,params.get('graph',[''])[0]);unit=params.get('unit',[None])[0]
                    result=project(graph,unit)
                    result['extractions']=for_graph(store,graph,unit)
                    return self.response(200,result,
                        download_name='local-work-contents.json' if params.get('download')==['1'] else None)
                if path == '/api/work-content-extractions':
                    from .work_content_results import read
                    return self.response(200,dict(extractions=read(store,params.get('graph',[''])[0],params.get('unit',[''])[0])))
                if path == '/api/unit-reviews':
                    from .unit_reviews import template
                    return self.response(200,template(store,params.get('graph',[''])[0],params.get('unit',[''])[0],params.get('window',[None])[0]))
                if path == '/api/work-grouping':
                    from .scope_membership import pending_requests
                    from .graph_store import read
                    graph=read(store,params.get('graph',[''])[0])
                    result=pending_requests(store.get(graph['run_id'],raw=True)['run'],graph)
                    return self.response(200,result,download_name='missing-work-comparisons.json' if params.get('download')==['1'] else None)
                if path == '/api/request-evidence':
                    from .request_evidence import project
                    from .graph_store import read
                    return self.response(200,project(read(store,params.get('graph',[''])[0]),params.get('through',[None])[0]),
                        download_name='request-evidence.json' if params.get('download')==['1'] else None)
                if path == '/api/feedback-followthrough':
                    from .feedback_followthrough import project
                    from .graph_store import read
                    return self.response(200,project(read(store,params.get('graph',[''])[0]),params.get('through',[None])[0]),
                        download_name='feedback-followthrough.json' if params.get('download')==['1'] else None)
                if path == '/api/work-candidates':
                    from .work_retrieval import prepare
                    from .graph_store import read
                    graph=read(store,params.get('graph',[''])[0])
                    limit=int(params.get('limit',['8'])[0])
                    result=prepare(store.get(graph['run_id'],raw=True)['run'],graph,
                        limit=limit,recent=min(2,limit),unit_ids=params.get('unit'))
                    return self.response(200,result,download_name='prior-work-candidates.json' if params.get('download')==['1'] else None)
                if path.startswith('/api/graphs/'):
                    from .graph_store import read, matrices
                    graph=read(store,path.removeprefix('/api/graphs/'))
                    if params.get('download')==['1']:
                        return self.response(200,graph,download_name='rollout-graph.json')
                    return self.response(200,{**graph,'matrices':matrices(graph)})
                if path == '/api/graph-requirements':
                    from .graph_queries import saved, PRESETS
                    return self.response(200,{'saved':saved(store),'presets':PRESETS})
                if path == "/api/runs":
                    return self.response(200, {"runs": store.list()})
                if path.startswith('/api/operation-observations/'):
                    return self.response(200,store.operation_observation(path.rsplit('/',1)[-1]))
                if path == "/api/activity-reference.zip":
                    from .activity_reference import build, archive
                    per_kind = int(params.get("per_kind", ["6"])[0])
                    if not 1 <= per_kind <= 20:
                        raise InputError("Browser export supports 1–20 units per kind; use the CLI for larger frozen corpora")
                    package = build([store.get(params.get("run_id", [""])[0], raw=True)], per_kind=per_kind)
                    return self.response(200, archive(package), "application/zip",
                                         "activity-reference-" + package["manifest"]["manifest_hash"][:12] + ".zip")
                if path == "/api/studies":
                    return self.response(200, {"studies": store.studies()})
                if path.startswith("/api/studies/"):
                    from .source_study import compare as compare_source
                    parts = path.removeprefix("/api/studies/").split("/")
                    if len(parts)==2 and parts[1]=='investigations':
                        return self.response(200,{'investigations':store.investigations(parts[0])})
                    if len(parts)==3 and parts[1]=='investigations':
                        value=store.investigation(parts[0],parts[2])
                        return self.response(200,value,download_name='investigation-'+value['id']+'.json' if params.get('download')==['1'] else None)
                    if len(parts) == 3 and parts[1] == "episodes":
                        return self.response(200, store.study_episode(parts[0], parts[2]))
                    if len(parts) != 1:
                        return self.response(404, {"error": "Study endpoint not found"})
                    study = store.study(parts[0])
                    reference = params.get("reference", [None])[0]
                    checkpoint = params.get("checkpoint", [None])[0]
                    if reference or checkpoint:
                        return self.response(200, compare_source(study, reference, checkpoint))
                    return self.response(200, study)
                if path == "/api/review-options":
                    run = store.get(params.get("run_id", [""])[0])["run"]
                    return self.response(200, {"options": review_options(run, params.get("event_id", [""])[0])})
                if path.startswith("/api/runs/"):
                    run_id = path.removeprefix("/api/runs/")
                    return self.response(200, store.get(run_id, raw=params.get("raw") == ["1"]))
                if path == "/api/compare":
                    return self.response(200, compare(store.list(), **self.comparison_filters(params)))
                if path == "/api/compare/evidence":
                    arguments = {key:params.get(key,[None])[0] for key in ('comparison_id','metric','checkpoint','reference','task_id','before_run','after_run')}
                    return self.response(200, comparison_evidence(store.list(),store.get,filters=self.comparison_filters(params),**arguments))
                if path == "/api/config":
                    return self.response(200, {"jev_configured": bool(os.environ.get("JEV_API_KEY")), "model": DEFAULT_MODEL,
                                               "action_limit_per_job": worker.max_actions, "activity_limit_per_job": activity_worker.max_actions,
                                               "activity_complete_run": True, "entities_available": True, "occurrences_available": True, "frames_available": True, "references_available": True, "relations_available": False, "version": "0.2.0"})
                if path=='/api/semantic-maps':
                    from .semantic_catalog import catalog
                    return self.response(200,catalog(store))
                if path.startswith('/api/reward-records/'):
                    from .reward_records import inspect as inspect_reward
                    run=store.get(path.removeprefix('/api/reward-records/'),raw=True)['run']
                    return self.response(200,inspect_reward(run))
                if path=='/api/rollout-metrics':
                    from .rollout_metrics import report, training_series
                    value=report(store)
                    if params.get('metric'):
                        value['training']=training_series(value,params['metric'][0],observer=params.get('observer',['source'])[0],bin_width=int(params.get('bin_width',['1'])[0]))
                    if params.get('view')==['metric'] and params.get('download')!=['1']:
                        from .rollout_metrics import metric_view
                        value=metric_view(value,params.get('metric',[''])[0])
                    return self.response(200,value,download_name='rollout-metrics.json' if params.get('download')==['1'] else None)
                if path.startswith('/api/tool-contracts/'):
                    from .tool_contracts import read_saved
                    return self.response(200,read_saved(store,path.rsplit('/',1)[-1],params.get('observer',[None])[0]))
                if path.startswith('/api/semantic-map/'):
                    from .semantic_map import load_reference
                    run_id = path.removeprefix('/api/semantic-map/')
                    run = store.get(run_id, raw=True)['run']
                    observer=params.get('observer',[None])[0]
                    if observer is not None:
                        from .semantic_catalog import load,export_payload
                        result=load(run,observer,store)
                        if params.get('patterns') in (['1'], ['2']):
                            from .work_patterns import project
                            result=project(result,run,include_returns=params.get('patterns')==['2'])
                        if params.get('plans')==['1']:
                            from .plan_execution import project as project_plans
                            result=project_plans(result,run)
                        if result.get('available'):
                            from .rollout_metrics import record_map
                            record_map(store,run,result)
                        if params.get('download')==['1']:
                            if params.get('expected_digest')!=[result.get('export_digest')]:
                                return self.response(409,{'error':'The saved observation changed. Reload the map before exporting.'})
                            return self.response(200,export_payload(result),download_name='semantic-map-'+run_id+'-'+observer+'.json')
                        return self.response(200,result)
                    result = load_reference(run)
                    if not result['available']:
                        from .semantic_extraction import load_extraction
                        result = load_extraction(run)
                    return self.response(200, result)
                if path == "/api/jobs":
                    return self.response(200, {"jobs": worker.list()})
                if path=='/api/activity-components':
                    return self.response(200,store.activity_component_catalog(params.get('run_id',[None])[0]))
                if path=='/api/activity-components/compare':
                    return self.response(200,store.activity_component_comparison(params.get('collection',[''])[0],
                        params.get('reference',[''])[0],params.get('candidate',[''])[0],params.get('run_id',[None])[0]))
                if path.startswith('/api/activity-components/records/'):
                    return self.response(200,store.activity_component_record(path.removeprefix('/api/activity-components/records/')))
                allowed_files = {"/": "monitoring.html", "/source": "index.html", "/app.js": "app.js", "/details.js": "details.js", "/comparison.js":"comparison.js", "/style.css": "style.css",
                                 "/dashboard":"monitoring.html","/monitors":"monitoring.html","/runs":"monitoring.html","/monitoring.js":"monitoring.js","/monitoring.css":"monitoring.css",
                                 "/rollout-map.js":"rollout-map.js","/rollout-map.css":"rollout-map.css","/map-layout.js":"map-layout.js",
                                 "/work-navigation.js":"work-navigation.js","/work-navigation.css":"work-navigation.css","/work-review.js":"work-review.js",
                                 "/inspection-paths.js":"inspection-paths.js","/inspection-view.js":"inspection-view.js","/inspection-paths.css":"inspection-paths.css",
                                 "/case-behavior.js":"case-behavior.js","/case-behavior.css":"case-behavior.css","/case-comparisons.js":"case-comparisons.js","/case-comparisons.css":"case-comparisons.css",
                                 "/measurement-case-links.js":"measurement-case-links.js",
                                 "/experiment-browser.js":"experiment-browser.js","/experiment-browser.css":"experiment-browser.css",
                                 "/experiment-details.js":"experiment-details.js","/experiment-details.css":"experiment-details.css",
                                 "/run-capture.js":"run-capture.js",
                                 "/hardware-history.js":"hardware-history.js",
                                 "/unit-reading.js":"unit-reading.js","/source-evidence.js":"source-evidence.js","/request-evidence.js":"request-evidence.js","/rollout-story.js":"rollout-story.js","/rollout-story.css":"rollout-story.css",
                                 "/plan-hierarchy.js":"plan-hierarchy.js","/plan-hierarchy.css":"plan-hierarchy.css","/plan-case-context.js":"plan-case-context.js","/structure-lines.js":"structure-lines.js",
                                 "/compact-structure.js":"compact-structure.js","/compact-structure.css":"compact-structure.css",
                                 "/revision-impact.js":"revision-impact.js","/revision-impact.css":"revision-impact.css",
                                 "/nested-work-tree.js":"nested-work-tree.js","/nested-work-tree.css":"nested-work-tree.css",
                                 "/work-outline.js":"work-outline.js","/work-outline.css":"work-outline.css",
                                 "/work-canvas.js":"work-canvas.js","/work-canvas.css":"work-canvas.css",
                                 "/work-contents.js":"work-contents.js","/work-contents.css":"work-contents.css",
                                 "/plan-attempt-path.js":"plan-attempt-path.js","/plan-attempt-path.css":"plan-attempt-path.css",
                                 "/strategy-profiles.js":"strategy-profiles.js","/strategy-profiles.css":"strategy-profiles.css",
                                 "/behavior-distributions.js":"behavior-distributions.js","/behavior-distributions.css":"behavior-distributions.css",
                                 "/distribution-evidence.js":"distribution-evidence.js",
                                 "/evaluation-evidence.js":"evaluation-evidence.js","/evaluation-evidence.css":"evaluation-evidence.css",
                                 "/investigate":"investigate.html","/investigate.js":"investigate.js","/investigate.css":"investigate.css","/investigation-process.js":"investigation-process.js",
                                 "/behavior-blueprint.js":"behavior-blueprint.js", "/rollouts":"monitoring.html", "/legacy/rollouts":"rollouts.html", "/rollouts.js":"rollouts.js", "/rollouts.css":"rollouts.css",
                                 "/studies": "studies.html", "/studies.js": "studies.js", "/studies.css": "studies.css", "/activity.js": "activity.js", "/activity-timeline.js": "activity-timeline.js", "/activity-timeline.css": "activity-timeline.css",
                                 "/components":"components.html","/components.js":"components.js","/components.css":"components.css",
                                 "/unit-graph.js":"unit-graph.js","/unit-graph.css":"unit-graph.css",
                                 "/semantic-map":"rollout-map.html","/legacy/semantic-map":"semantic-map.html","/semantic-map.js":"semantic-map.js","/semantic-map.css":"semantic-map.css",
                                 "/relations":"relations.html","/relations.js":"relations.js","/relations.css":"relations.css","/workspace.css":"workspace.css","/workspace.js":"workspace.js"}
                allowed_files.update({'/training-comparison.js':'training-comparison.js','/unit-review.js':'unit-review.js'})
                allowed_files.update({'/work-timeline.js':'work-timeline.js'})
                allowed_files.update({'/monitor-comparisons.js':'monitor-comparisons.js','/monitor-comparisons.css':'monitor-comparisons.css'})
                allowed_files['/population-evidence.js']='population-evidence.js'
                allowed_files['/custom-monitor-setup.js']='custom-monitor-setup.js'
                allowed_files['/reward-checks.js']='reward-checks.js'
                allowed_files['/workspace-alerts.js']='workspace-alerts.js'
                allowed_files.update({'/workspace-picker.js':'workspace-picker.js','/workspace-picker.css':'workspace-picker.css'})
                allowed_files['/reward-scan-progress.js']='reward-scan-progress.js'
                allowed_files.update({'/custom-monitor-evidence.js':'custom-monitor-evidence.js','/custom-monitor-evidence.css':'custom-monitor-evidence.css'})
                allowed_files['/POPULATION_READINESS.md']='population-readiness.md'
                allowed_files.update({'/geist-sans.woff2':'geist-sans.woff2','/geist-mono.woff2':'geist-mono.woff2','/geist-LICENSE.txt':'geist-LICENSE.txt'})
                allowed_files.update({'/code-syntax.js':'code-syntax.js','/prism-LICENSE.txt':'prism-LICENSE.txt','/choice-labels.js':'choice-labels.js','/workspace-navigation.js':'workspace-navigation.js','/workspace-layout.js':'workspace-layout.js','/workspace-layout.css':'workspace-layout.css'})
                allowed_files.update({'/connections':'connections.html','/connections.js':'connections.js','/connections.css':'connections.css','/source-preview.js':'source-preview.js'})
                allowed_files.update({'/deployment-setup.js':'deployment-setup.js'})
                allowed_files.update({'/source-discovery.js':'source-discovery.js'})
                allowed_files.update({'/first-session.js':'first-session.js','/first-session.css':'first-session.css','/model-setup.js':'model-setup.js','/model-setup.md':'model-setup.md'})
                allowed_files.update({'/integration-guide':'integration-guide.html','/deployment-guide.js':'deployment-guide.js'})
                allowed_files.update({'/research-guide.md':'research-guide.md','/research-example.py':'research-example.py'})
                allowed_files.update({'/execution-guide.md':'execution-guide.md'})
                allowed_files.update({'/workflow-guide.md':'workflow-guide.md'})
                allowed_files.update({'/rilldex-mark.svg':'rilldex-mark.svg','/rilldex-logo.svg':'rilldex-logo.svg','/favicon.ico':'rilldex-mark.svg'})
                allowed_files.update({'/measurement-review':'measurement-review.html','/measurement-review.js':'measurement-review.js','/measurement-review.css':'measurement-review.css'})
                allowed_files.update({'/detector-validation':'detector-validation.html','/detector-validation.js':'detector-validation.js','/detector-validation.css':'detector-validation.css'})
                if path not in allowed_files:
                    return self.response(404, {"error": "Not found"})
                file = WEB / allowed_files[path]
                # Windows MIME registries may not know WOFF2; font delivery must be portable.
                content_type = "font/woff2" if file.suffix == ".woff2" else (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8"
                return self.response(200, file.read_bytes(), content_type)
            except KeyError:
                self.response(404, {"error": "Run not found"})
            except ComparisonChanged as e:
                self.response(409, {"error": str(e)})
            except (ValueError, InputError) as e:
                self.response(400, {"error": str(e)})

        def comparison_filters(self, params):
            filters = {key:params.get(key,[None])[0] for key in ('experiment','environment','environment_version','split','inspector_signature','sampling_hash','reference')}
            if 'checkpoints' in params:
                filters['checkpoints'] = params['checkpoints']
            return filters

        def do_POST(self):
            if not self.allowed():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.response(413, {"error": "JSON body must be between 1 byte and 20 MiB"})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.response(415, {"error": "Content-Type must be application/json"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise InputError("Request body must be an object")
                if self.path == '/api/context-mix/review':
                    from .context_mix import review
                    if not context_review_lock.acquire(blocking=False):
                        return self.response(409,{'error':'A context review is already running. Try again after it finishes.'})
                    try:
                        return self.response(200,review(store,body.get('run'),body.get('event'),body.get('block')))
                    finally: context_review_lock.release()
                if self.path.startswith('/api/workspaces/') and workspace_manager is None:
                    return self.response(503,{'error':'Workspace picker unavailable: '+str(workspace_error)})
                if self.path == '/api/workspaces/open':
                    if type(body.get('create',False)) is not bool:
                        raise InputError('create must be a boolean')
                    try:
                        return self.response(200,workspace_manager.open(key=body.get('id'),path=body.get('path'),name=body.get('name'),
                            create=body.get('create',False),current_view=body.get('current_view','/')))
                    except (OSError,sqlite3.Error) as error:
                        raise InputError('Could not open workspace: '+str(error)) from None
                if self.path == '/api/workspaces/view':
                    workspace_manager.directory.save_view(workspace_manager.key,body.get('view'))
                    return self.response(200,{'saved':True})
                if self.path == '/api/workspaces/forget':
                    return self.response(200,workspace_manager.forget(body.get('id')))
                if self.path == '/api/example':
                    from .first_session import example
                    result=example(store);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/models/pilot':
                    return self.response(202,model_pilot.start(body))
                if self.path == '/api/map-inspection/checks':
                    from .map_inspection import prepare_checks
                    return self.response(200,prepare_checks(store,body))
                if self.path in {'/api/import-file/check','/api/import-file'}:
                    from .import_batch import read_request,preflight
                    runs=read_request(body)
                    if self.path.endswith('/check'):return self.response(200,preflight(runs))
                    result=store.add(runs);monitor_service.wake()
                    from .first_session import readiness
                    return self.response(200,{'runs':result,'total_rollouts':len(result),
                        'readiness':readiness(store,run_ids=[r['id'] for r in result])})
                if self.path == '/api/integrations/check':
                    from .integrations import check
                    return self.response(200,check(body))
                if self.path == '/api/measurement-reviews':
                    from .measurement_reviews import create
                    return self.response(200,create(store,body))
                if self.path == '/api/measurement-reviews/labels':
                    from .measurement_reviews import receive
                    return self.response(200,receive(store,body))
                if self.path in {'/api/detector-validation/sets','/api/detector-validation/capture','/api/detector-validation/results'}:
                    from . import detector_validation as validation
                    operation={'sets':validation.create,'capture':validation.capture,'results':validation.publish}[self.path.rsplit('/',1)[-1]]
                    return self.response(200,operation(store,body))
                if self.path in {'/api/connections','/api/connections/preview'}:
                    from .connections import create,preview
                    return self.response(200,(preview if self.path.endswith('/preview') else create)(store,body))
                if self.path == '/api/setup/plan':
                    from .deployment_setup import plan
                    return self.response(200, plan(body))
                if self.path == '/api/workflows/package':
                    from .workflows import package_request
                    return self.response(200, package_request(body, store.path), 'application/zip')
                if self.path == '/api/connections/discover':
                    from .source_discovery import discover
                    return self.response(200, discover(body.get('root')))
                if self.path == '/api/capture/import':
                    import base64, binascii, io
                    from .capture_bundle import receive
                    encoded = body.get('base64')
                    if not isinstance(encoded, str) or len(encoded) > 20 * 1024 * 1024:
                        raise InputError('Choose a capture bundle up to 14 MiB; use the CLI for larger bundles')
                    try:
                        raw = base64.b64decode(encoded, validate=True)
                    except binascii.Error as exc:
                        raise InputError('Invalid bundle encoding') from exc
                    if len(raw) > 14 * 1024 * 1024:
                        raise InputError('Use the CLI for bundles larger than 14 MiB')
                    result = receive(store, io.BytesIO(raw), with_receipts=True); monitor_service.wake()
                    return self.response(200, result)
                if self.path.startswith('/api/connections/') and self.path.endswith('/state'):
                    from .connections import set_enabled
                    return self.response(200,set_enabled(store,self.path.split('/')[-2],body.get('enabled')))
                if self.path.startswith('/api/connections/') and self.path.endswith('/location'):
                    from .connections import relocate
                    cid = self.path.split('/')[-2]
                    collector = intake_service.collectors.get(cid)
                    if collector and collector.thread.is_alive():
                        raise InputError('Pause collection and wait for its current poll to stop before changing location')
                    return self.response(200,relocate(store,cid,body))
                if self.path == '/api/investigations':
                    from .failure_investigations import save
                    return self.response(200,save(store,body))
                if self.path == '/api/behavior-comparisons':
                    from .behavior_distributions import save_comparison
                    return self.response(201,save_comparison(store,body))
                if self.path == '/api/evaluations':
                    from .evaluation_receipts import receive
                    result=receive(store,body);monitor_service.wake()
                    return self.response(201,result)
                if self.path == '/api/evaluations/compare':
                    from .evaluation_receipts import compare_ids, fields
                    fields(body, ('ids',))
                    return self.response(200,compare_ids(store,body['ids']))
                if self.path in {'/api/investigations/interval','/api/investigations/interval/preview'}:
                    from .investigation_workspace import save, capture
                    return self.response(200,(capture if self.path.endswith('/preview') else save)(store,body))
                if self.path == '/api/investigations/cases':
                    from .case_studies import save
                    return self.response(201,save(store,body))
                if self.path == '/api/investigations/trainer-cases':
                    from .trainer_case_studies import save
                    return self.response(201,save(store,body))
                if self.path == '/api/investigations/trial-cases':
                    from .trial_rollouts import comparison
                    return self.response(201,comparison(store,body))
                if self.path == '/api/experiment-history':
                    from .investigation_workspace import annotate
                    return self.response(201,annotate(store,body))
                if self.path in {'/api/monitoring/questions/activate','/api/monitoring/questions/bind'}:
                    from .question_bundles import activate, bind
                    return self.response(200,(bind if self.path.endswith('/bind') else activate)(store,body))
                if self.path == '/api/investigations/follow-ups':
                    from .investigation_followups import save
                    return self.response(200,save(store,body))
                if self.path == '/api/investigations/follow-ups/preview':
                    from .investigation_followups import evidence, fields
                    from .evaluation_receipts import attached_comparisons
                    fields(body, ('evidence',))
                    receipts=evidence(store,body.get('evidence'))
                    return self.response(200,{'evidence':receipts, 'evaluation_comparisons':attached_comparisons(receipts), 'inference_calls':0})
                if self.path == '/api/investigations/training':
                    from .training_investigations import save
                    return self.response(200,save(store,body))
                if self.path == '/api/investigations/rewards':
                    from .reward_investigations import save
                    return self.response(200,save(store,body))
                if self.path in {'/api/training-comparisons/preview','/api/training-comparisons'}:
                    from .training_comparisons import preview,save
                    return self.response(200,(preview if self.path.endswith('/preview') else save)(store,body))
                if self.path == '/api/investigation-plans/check':
                    from .investigation_plans import preflight
                    return self.response(200,preflight(store,body))
                if self.path == '/api/investigation-plans':
                    from .investigation_plans import execute
                    return self.response(200,execute(store,body))
                if self.path == '/api/behavior-groupings':
                    from .behavior_distributions import save_grouping
                    return self.response(200,save_grouping(store,body))
                if self.path == '/api/monitoring/comparisons':
                    from .monitor_comparisons import save
                    allowed={'monitor_id','baseline','current','experiment','environment'}
                    if not isinstance(body,dict) or set(body)-allowed or not {'monitor_id','baseline','current','experiment'}<=set(body):
                        raise InputError('Supply monitor_id, baseline, current and experiment; environment is optional')
                    return self.response(201,save(store,**body))
                if self.path == '/api/monitoring/monitors':
                    from .monitoring import create
                    result=create(store,body.get('definition'),body.get('replace'));monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/monitoring/starters':
                    from .monitoring import add_starters
                    result=add_starters(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/monitoring/reward-checks':
                    from .reward_detectors import activate
                    result=activate(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/monitoring/custom-values':
                    from .custom_monitors import publish
                    result=publish(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/monitoring/check':
                    from .monitoring import preflight
                    return self.response(200,preflight(store,body))
                if self.path == '/api/investigation-readiness':
                    from .investigation_readiness import check
                    return self.response(200,check(store,body))
                if self.path.startswith('/api/monitoring/monitors/') and self.path.endswith('/state'):
                    from .monitoring import enabled
                    return self.response(200,enabled(store,self.path.split('/')[-2],body.get('enabled')))
                if self.path == '/api/graph-query':
                    from .graph_queries import run
                    return self.response(200,run(store,body))
                if self.path == '/api/relationship-reviews':
                    from .relation_reviews import receive
                    result=receive(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/procedure-reviews':
                    from .procedure_reviews import receive
                    result=receive(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/work-outline':
                    from .work_outline import receive
                    result=receive(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/work-subjects':
                    from .work_subjects import receive
                    result=receive(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/work-grouping':
                    from .scope_membership import receive
                    result=receive(store,body);monitor_service.wake()
                    return self.response(200,result)
                if self.path in {'/api/unit-reviews','/api/unit-reviews/preview'}:
                    from .unit_reviews import receive, preview
                    result=(preview if self.path.endswith('/preview') else receive)(store,body)
                    if not self.path.endswith('/preview'): monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/unit-reviews/monitor':
                    from .unit_reviews import continue_monitor
                    result=continue_monitor(store,body.get('graph_id'),body.get('monitor_id'))
                    monitor_service.wake()
                    return self.response(200,result)
                if self.path == '/api/graph-requirements':
                    from .graph_queries import save
                    return self.response(200,save(store,body))
                if self.path == "/api/import":
                    if not isinstance(body.get("metadata", {}), dict):
                        raise InputError("metadata must be an object")
                    sources = body.get("sources")
                    if body.get("grading") is not None:
                        from .swe_rl import pair_grading
                        grading = body["grading"]
                        if not isinstance(grading, dict) or sources is not None and not isinstance(sources, list):
                            raise InputError("grading must be an object and sources a list")
                        source = pair_grading(grading.get("trajectory_name"), body["document"], grading.get("name"), grading.get("document"))
                        sources = [*(sources or []), source]
                    runs = normalize(body["document"], body.get("format", "auto"), body.get("metadata"), sources)
                    return self.response(200, {"runs": store.add(runs)})
                if self.path == "/api/ingest":
                    result=store.ingest(body);monitor_service.wake()
                    return self.response(200, result)
                if self.path == '/api/training-records':
                    from .training_lineage import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/trainer-telemetry':
                    from .trainer_telemetry import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/run-records':
                    from .run_records import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/experiments/settings':
                    from .configuration_comparison import compare
                    if not isinstance(body,dict) or 'experiments' not in body or set(body)-{'experiments','sources','environment','q','differences_only','limit','offset'}:
                        raise InputError('Invalid settings comparison fields')
                    return self.response(200,compare(store,**body))
                if self.path == '/api/experiments/selection':
                    from .experiment_management import selection
                    if not isinstance(body,dict) or 'experiments' not in body or set(body)-{'experiments','environment'}:
                        raise InputError('Invalid experiment selection fields')
                    return self.response(200,selection(store,**body))
                if self.path == '/api/experiments/organize':
                    from .experiment_management import organize_many
                    if not isinstance(body,dict) or 'experiments' not in body or set(body)-{'experiments','project','add_tags','remove_tags','pinned','archived'}:
                        raise InputError('Invalid bulk organization fields')
                    return self.response(200,organize_many(store,**body))
                if self.path == '/api/experiment-labels':
                    from .run_records import organize
                    if not isinstance(body,dict) or 'experiment' not in body or set(body)-{'experiment','title','project','tags','notes','pinned','archived'}:
                        raise InputError('Invalid organization fields')
                    return self.response(200,organize(store,**body))
                if self.path == '/api/experiment-selections':
                    from .run_records import save_selection
                    if not isinstance(body,dict) or not {'name','experiments'}<=set(body) or set(body)-{'name','experiments','environment'}:
                        raise InputError('Invalid selection fields')
                    return self.response(200,save_selection(store,**body))
                if self.path == '/api/execution-records':
                    from .execution_records import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/training-execution/save':
                    from .execution_timeline import save
                    if not isinstance(body,dict) or 'experiment' not in body or set(body)-{'experiment','environment','clock','start','end','limit'}:
                        raise InputError('Supply an experiment and execution interval')
                    return self.response(200,save(store,**body))
                if self.path == '/api/generation-cohorts':
                    from .generation_cohorts import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/training-recipes':
                    from .training_recipes import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/continuation-studies':
                    from .continuation_studies import receive
                    return self.response(200,receive(store,body))
                if self.path == '/api/training-setup':
                    from .training_setup import inspect
                    return self.response(200,inspect(body))
                if self.path == '/api/producers/report':
                    from .producer_health import receive
                    return self.response(200,receive(store,body))
                if self.path.startswith('/api/studies/') and self.path.endswith('/investigations'):
                    parts=self.path.removeprefix('/api/studies/').split('/')
                    if len(parts)!=2:raise InputError('Unknown investigation endpoint')
                    return self.response(200,store.save_investigation(parts[0],body))
                if self.path == "/api/jobs":
                    if not os.environ.get("JEV_API_KEY"):
                        raise InputError("JEV_API_KEY is not configured on the server")
                    return self.response(202, {"job_id": worker.submit(body["run_id"])})
                if self.path == "/api/activity-jobs":
                    if not os.environ.get("JEV_API_KEY"):
                        raise InputError("JEV_API_KEY is not configured on the server")
                    return self.response(202, {"job_id": activity_worker.submit(body["run_id"])})
                if self.path == '/api/relation-jobs':
                    raise InputError('Complete category-specific entity extraction and reference resolution before relationship inference. Earlier experimental results remain inspectable.')
                if self.path == '/api/reference-jobs':
                    if not os.environ.get('JEV_API_KEY'):
                        raise InputError('JEV_API_KEY is not configured on the server')
                    if not store.get(body['run_id'])['unit_graph']['coverage'].get('reference_eligible_units'):
                        raise InputError('No current extracted reference fields are available. Complete or review local extraction first.')
                    return self.response(202, {'job_id': reference_worker.submit(body['run_id'])})
                if self.path == '/api/entity-jobs':
                    if not os.environ.get('JEV_API_KEY'):
                        raise InputError('JEV_API_KEY is not configured on the server')
                    if not store.get(body['run_id'])['unit_graph']['coverage'].get('entity_routed_units'):
                        raise InputError('No current activity routes require extraction. Complete or review base annotations first.')
                    return self.response(202, {'job_id': entity_worker.submit(body['run_id'])})
                if self.path == '/api/occurrence-jobs':
                    if not os.environ.get('JEV_API_KEY'):
                        raise InputError('JEV_API_KEY is not configured on the server')
                    if not store.get(body['run_id'])['unit_graph']['coverage'].get('occurrence_eligible_units'):
                        raise InputError('No completed category fields with local mention presence are available')
                    return self.response(202, {'job_id': occurrence_worker.submit(body['run_id'])})
                if self.path == "/api/reviews":
                    return self.response(200, store.review(body["run_id"], body))
                if self.path == '/api/frame-jobs':
                    if not os.environ.get('JEV_API_KEY'):
                        raise InputError('JEV_API_KEY is not configured on the server')
                    if not store.get(body['run_id'])['unit_graph']['coverage'].get('frame_eligible_units'):
                        raise InputError('Complete selected local operation/claim fields before inspecting predicate arguments')
                    return self.response(202, {'job_id': frame_worker.submit(body['run_id'])})
                self.response(404, {"error": "Not found"})
            except ReviewConflict as e:
                self.response(409, {"error": str(e)})
            except (KeyError, ValueError, TypeError) as e:
                self.response(400, {"error": str(e)})

    server = LocalServer((host, port), Handler)
    if port == 0 and workspace_directory is not None:
        reserved = workspace_directory.ports()
        # An automatic new workspace must not take another study's saved intake port.
        for _ in range(32):
            if server.server_address[1] not in reserved:
                break
            server.server_close()
            server = LocalServer((host, 0), Handler)
        else:
            server.server_close()
            raise InputError('Could not allocate a distinct workspace port; choose one with --port')
    port = server.server_address[1]
    from .monitoring import Service as MonitoringService
    monitor_service=intake_service=None
    worker = activity_worker = entity_worker = reference_worker = occurrence_worker = frame_worker = None
    try:
        monitor_service=MonitoringService(store)
        from .connections import Service as IntakeService
        intake_service=IntakeService(store,monitor_service)
        worker = Worker(store)
        activity_worker = Worker(store, max_actions=20, activity=True, complete_run=True)
        entity_worker = Worker(store, entities=True, complete_run=True)
        reference_worker = Worker(store, references=True, complete_run=True)
        occurrence_worker = Worker(store, occurrences=True, complete_run=True)
        frame_worker = Worker(store, frames=True, max_actions=20)
        from .workspace_directory import WorkspaceManager
        if workspace_directory is not None:
            try:
                workspace_manager = WorkspaceManager(store, f'http://127.0.0.1:{port}', workspace_instance,
                                                     directory=workspace_directory, enabled=not container)
            except (OSError,sqlite3.Error) as error:
                workspace_error = str(error)
    except Exception:
        if intake_service:intake_service.close()
        if monitor_service:monitor_service.close()
        server.server_close()
        if worker:
            worker.close()
        if activity_worker:
            activity_worker.close()
        if entity_worker:
            entity_worker.close()
        if reference_worker:
            reference_worker.close()
        if occurrence_worker:
            occurrence_worker.close()
        if frame_worker:
            frame_worker.close()
        raise
    url = f'http://127.0.0.1:{port}' if container else f'http://{host}:{port}'
    print(f"Rilldex: {url}", flush=True)
    if on_ready:
        on_ready(url)
    if open_browser:
        import webbrowser
        try:
            webbrowser.open(url + '/')
        except (webbrowser.Error, OSError):
            print('Browser launch unavailable; open the printed URL from your workstation.', flush=True)
    previous_term = None
    if threading.current_thread() is threading.main_thread():
        previous_term = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, terminate)
    finished = threading.Event()
    if stop_event is not None:
        def stop_managed_workspace():
            while not finished.wait(.1):
                if stop_event.is_set():
                    server.shutdown()
                    return
        threading.Thread(target=stop_managed_workspace, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        finished.set()
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
        try:
            if workspace_manager:
                workspace_manager.close()
        finally:
            intake_service.close()
            monitor_service.close()
            server.server_close(); worker.close(); activity_worker.close(); entity_worker.close(); reference_worker.close(); occurrence_worker.close(); frame_worker.close()
