"""Small run recorder for Python programs and arbitrary training commands."""
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from tracker.run_records import VERSION, MAX_FILE, receive
from tracker.schema import InputError


def _command(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=4, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise OSError('Command unavailable')
    return result.stdout.strip()


def runtime_context():
    value = dict(os=platform.system(), os_version=platform.release(), architecture=platform.machine(),
                 python=platform.python_version(), host=platform.node(), packages={})
    for package in ('rilldex','torch','transformers','trl','stable-baselines3','gymnasium','ray','vllm','sglang','psutil'):
        try: value['packages'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: pass
    try:
        value['git']=dict(commit=_command(['git','rev-parse','HEAD']),
                          branch=_command(['git','rev-parse','--abbrev-ref','HEAD']),
                          dirty=bool(_command(['git','status','--porcelain','--untracked-files=no'])))
    except (OSError,subprocess.TimeoutExpired): value['git']=None
    return value


def hardware_sample():
    value=dict(host=platform.node(),cpu_percent=None,memory_used_bytes=None,memory_total_bytes=None,gpus=[],unavailable=[])
    try:
        import psutil
        value['cpu_percent']=psutil.cpu_percent(interval=0.1)
        memory=psutil.virtual_memory(); value.update(memory_used_bytes=memory.used,memory_total_bytes=memory.total)
    except ImportError: value['unavailable'].append('CPU/RAM: install rilldex[system]')
    except (OSError,RuntimeError): value['unavailable'].append('CPU/RAM sensor unavailable')
    try:
        raw=_command(['nvidia-smi','--query-gpu=uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw','--format=csv,noheader,nounits'])
        import csv
        for row in csv.reader(raw.splitlines()):
            if len(row)!=7: continue
            gpu=dict(uuid=row[0].strip(),name=row[1].strip())
            for key,cell,factor in zip(('utilization_percent','memory_used_bytes','memory_total_bytes','temperature_c','power_watts'),row[2:],(1,1048576,1048576,1,1)):
                try:
                    import math
                    number=float(cell)*factor; gpu[key]=number if math.isfinite(number) else None
                except ValueError: gpu[key]=None
            value['gpus'].append(gpu)
    except (OSError,subprocess.TimeoutExpired): value['unavailable'].append('NVIDIA sensor unavailable; AMD/Apple GPU capture is not installed')
    return value


class _Tee:
    def __init__(self, owner, stream, original):
        self.owner,self.stream,self.original=owner,stream,original
        self.pending=''; self.lock=threading.RLock()
    def write(self,text):
        result=self.original.write(text)
        with self.lock:
            self.pending+=text
            while '\n' in self.pending or len(self.pending)>=8192:
                size=min(self.pending.find('\n')+1 if '\n' in self.pending else 8192,8192)
                self.owner.console(self.pending[:size],stream=self.stream); self.pending=self.pending[size:]
        return result
    def flush(self):
        self.original.flush()
        with self.lock:
            if self.pending: self.owner.console(self.pending,stream=self.stream); self.pending=''
    def __getattr__(self,key): return getattr(self.original,key)


class Run:
    """Capture a run locally, or into an Outbox for remote/offline delivery.

    Each instance is a new process session. Reuse the experiment and producer
    across restarts. Scalars retain their native names and trainer definitions.
    """
    def __init__(self,name,*,project='default',workspace='study.sqlite',target=None,experiment=None,
                 producer=None,config=None,framework='custom',framework_version='unspecified',
                 objective='unspecified',clock='learner_update',definitions=None,
                 capture_console=True,hardware=True,interval=10):
        if not isinstance(interval,(int,float)) or not 1<=interval<=3600: raise InputError('Hardware interval must be 1–3600 seconds')
        if not isinstance(name,str) or not name.strip() or not isinstance(project,str) or not project.strip(): raise InputError('Use nonempty project and run names')
        from tracker.store import Store
        from tracker.trainer_telemetry import TrainerTelemetry
        self.target=target if target is not None else Store(workspace)
        self.experiment=experiment or quote(project,safe='')+'/'+quote(name,safe='')
        self.producer=producer or getattr(self.target,'producer',None) or platform.node() or 'local'
        if hasattr(self.target,'producer') and self.target.producer!=self.producer: raise InputError('Run producer must match its Outbox')
        self.session=uuid.uuid4().hex; self.closed=False; self.started=False; self.errors=[]
        self.name,self.project=name,project
        self._capture_finalizers=[]
        self.capture_console=capture_console; self.hardware=hardware; self.interval=interval
        self.stop=threading.Event(); self.thread=None; self.tees=[]
        self.telemetry=TrainerTelemetry(self.target,experiment=self.experiment,framework=framework,
            framework_version=framework_version,objective=objective,session=self.session,producer=self.producer,
            clock=clock,definitions=definitions)
        self._record('manifest',dict(name=name,project=project,config=config or {},runtime=runtime_context(),trainer_sessions=[self.session]))

    def _record(self,kind,payload):
        if self.closed: raise RuntimeError('Run is closed')
        record=dict(id=uuid.uuid4().hex,session=self.session,kind=kind,observed_at=datetime.now(timezone.utc).isoformat(),payload=payload)
        if hasattr(self.target,'log_run_records'): return self.target.log_run_records(self.experiment,[record])
        return receive(self.target,dict(schema=VERSION,producer=self.producer,experiment=self.experiment,records=[record]))

    def log(self,metrics,*,step,**kwargs):
        if self.closed: raise RuntimeError('Run is closed')
        return self.telemetry.log(metrics,step=step,**kwargs)

    def console(self,text,*,stream='stdout'):
        for offset in range(0,len(text),8192): self._record('console',dict(stream=stream,text=text[offset:offset+8192]))

    def log_config(self,config,*,trainer_session=None):
        """Record a configuration snapshot and its trainer-to-process session link."""
        return self._record('manifest',dict(name=self.name,project=self.project,config=config,runtime={},
            trainer_sessions=[self.session if trainer_session is None else trainer_session]))

    def add_file(self,path,*,name=None):
        path=Path(path)
        with path.open('rb') as source: content=source.read(MAX_FILE+1)
        if len(content)>MAX_FILE: raise InputError('File snapshots support up to 2 MiB; keep large checkpoints in artifact storage')
        return self._record('file',dict(name=name or path.name,size=len(content),sha256=hashlib.sha256(content).hexdigest(),content_base64=base64.b64encode(content).decode('ascii')))

    def add_reference(self,source,*,name=None,checksum=True,size=None,sha256=None,version=None,role='artifact',
                      step=None,clock=None,trainer_session=None,max_files=10000):
        """Track local files/directories or a cloud object without uploading bytes.

        Local files are hashed in chunks. A remote URI records supplied metadata;
        no cloud connection occurs. Storage credentials stay on the caller host.
        """
        from tracker.run_files import reference_payload,validate_name,local_path
        if self.closed:raise RuntimeError('Run is closed')
        if type(checksum) is not bool:raise InputError('checksum must be true or false')
        options=dict(checksum=checksum,size=size,sha256=sha256,version=version,role=role,step=step,
            clock=clock if clock is not None else (self.telemetry.context['clock'] if step is not None else None),
            trainer_session=self.session if trainer_session is None else trainer_session)
        raw=os.fspath(source)
        if raw.startswith('file://'):source=local_path(raw);raw=str(source)
        if '://' in raw or not Path(raw).expanduser().is_dir():
            return self._record('file',reference_payload(source,name=name,**options))
        if any(v is not None for v in (size,sha256,version)):raise InputError('Directory members have separate sizes, hashes and versions')
        if type(max_files) is not int or not 1<=max_files<=10000:raise InputError('max_files must be 1–10000')
        root=Path(raw).expanduser().resolve();prefix=name or root.name;validate_name(prefix)
        paths=[]
        for directory,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not (Path(directory)/d).is_symlink())
            for filename in sorted(files):
                path=Path(directory)/filename
                if path.is_file():paths.append(path)
                if len(paths)>max_files:raise InputError('Directory exceeds max_files; choose a smaller checkpoint or dataset directory')
        if not paths:raise InputError('Directory contains no files')
        collection=uuid.uuid4().hex
        payloads=[reference_payload(path,name=prefix+'/'+path.relative_to(root).as_posix(),collection=collection,**options) for path in paths]
        for payload in payloads:payload['collection_size']=len(paths)
        # Build identities before queuing anything; delivery uses the same durable
        # run-record transport as console/config snapshots.
        for payload in payloads:self._record('file',payload)
        return dict(collection=collection,files=len(paths),bytes=sum(p['size'] for p in payloads))

    def sample_hardware(self): return self._record('hardware',hardware_sample())

    def stable_baselines(self, **options):
        """Native SB3 logging and optional vector-episode capture; dependency is lazy."""
        from .stable_baselines import StableBaselinesCapture
        return StableBaselinesCapture(self, **options)

    def start(self):
        if self.closed: raise RuntimeError('Run is closed')
        if self.started: return self
        self.started=True; self._record('lifecycle',dict(state='started'))
        if self.capture_console:
            for name in ('stdout','stderr'):
                original=getattr(sys,name)
                if isinstance(original,_Tee): raise RuntimeError('Nested console capture is not supported; use capture_console=False')
            for name in ('stdout','stderr'):
                tee=_Tee(self,name,getattr(sys,name)); self.tees.append(tee); setattr(sys,name,tee)
        if self.hardware:
            def loop():
                while not self.stop.is_set():
                    try: self.sample_hardware()
                    except Exception as error:
                        self.errors.append(str(error)); break
                    if self.stop.wait(self.interval): break
            self.thread=threading.Thread(target=loop,name='rilldex-hardware',daemon=True); self.thread.start()
        return self

    def close(self,*,exit_code=0):
        if self.closed: return
        self.stop.set()
        if self.thread: self.thread.join(timeout=10)
        try:
            for finish in self._capture_finalizers: finish()
            for tee in self.tees: tee.flush()
            self._record('lifecycle',dict(state='completed' if exit_code==0 else 'failed',exit_code=exit_code,capture_errors=self.errors))
        finally:
            for tee in self.tees:
                if getattr(sys,tee.stream) is tee: setattr(sys,tee.stream,tee.original)
            self.closed=True
        if self.errors: raise RuntimeError('Run capture failed: '+'; '.join(self.errors))

    def __enter__(self): return self.start()
    def __exit__(self,kind,value,traceback): self.close(exit_code=0 if kind is None else 1)


def record_command(command, *, encoding='utf-8', **options):
    """Capture an argv list without shell interpretation; preserve the exit code."""
    if command and command[0]=='--': command=command[1:]
    if not command: raise InputError('Supply a command after --')
    import codecs
    try: codecs.lookup(encoding)
    except LookupError: raise InputError('Unknown console encoding') from None
    errors=[]
    with Run(capture_console=False,**options) as run:
        child_env=dict(os.environ,PYTHONIOENCODING=encoding)
        child_env.setdefault('PYTHONUNBUFFERED','1')
        child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               env=child_env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def copy(pipe,stream):
            import codecs
            decoder=codecs.getincrementaldecoder(encoding)(errors='replace')
            try:
                while chunk:=pipe.read1(8192):
                    text=decoder.decode(chunk); getattr(sys,stream).write(text); getattr(sys,stream).flush()
                    run.console(text,stream=stream)
                text=decoder.decode(b'',final=True)
                if text: run.console(text,stream=stream)
            except Exception as error:
                errors.append(str(error))
                # Keep draining if capture fails so the child cannot block on a full pipe.
                while pipe.read(8192): pass
            finally: pipe.close()
        threads=[threading.Thread(target=copy,args=(getattr(child,name),name),daemon=True) for name in ('stdout','stderr')]
        for thread in threads: thread.start()
        try: code=child.wait()
        except BaseException:
            child.terminate(); child.wait(timeout=10); raise
        finally:
            for thread in threads: thread.join()
        run.errors.extend(errors); run.close(exit_code=code)
        return code
