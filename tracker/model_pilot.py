"""One explicitly budgeted local pilot at a time; provider code is installed."""
import json
from pathlib import Path
import threading

from .schema import InputError, digest


class ModelPilotService:
    def __init__(self, store):
        self.store=store
        database=Path(store.path).resolve()
        self.root=database.with_name(database.name+'.models')
        self.lock=threading.Lock()
        self.thread=None
        self.current=None
        saved=sorted(self.root.glob('*/pilot-result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        if saved:
            try:
                self.current=json.loads(saved[0].read_text(encoding='utf-8'))
                if self.current['state']=='running':
                    self.current.update(state='saved',message='Saved pilot found. Resume with the same rollout and lifetime limits.')
            except (ValueError, OSError, KeyError):pass

    def status(self):
        from rilldex.models import check
        with self.lock:
            current=dict(self.current) if self.current else None
            if current and not (self.thread and self.thread.is_alive()):
                try:
                    saved=json.loads((Path(current['directory'])/'pilot-result.json').read_text(encoding='utf-8'))
                    if saved.get('state')!='running':current=saved;self.current=saved
                except (OSError, ValueError):pass
        if current:
            from .semantic_budget import summary
            current['usage']=summary(Path(current['directory'])/'extraction')
            # Read durable page progress while the worker is running, not only
            # the result returned after the pilot stops.
            from .semantic_extraction import read
            for name,filename in [('work_links','action-target-progress.json'),('plan_links','plan-relation-progress.json'),('execution_reports','execution-report-progress.json'),('method_comparison','method-comparison-progress.json')]:
                path=Path(current['directory'])/'extraction'/filename
                if path.exists():
                    saved=read(path)
                    current[name]={'status':saved['status'],'coverage':saved['coverage']}
        return dict(configuration=check(), pilot=current)

    def start(self, body):
        from rilldex.models import check, pilot
        from .semantic_extraction import write
        allowed={'run_id','candidate_calls','decision_calls','input_bytes'}
        if set(body)-{'inspect_feedback','inspect_approaches'}!=allowed or not isinstance(body.get('run_id'),str) or not body['run_id'].isalnum():
            raise InputError('Select a rollout and supply candidate, decision and byte limits')
        if 'inspect_feedback' in body and type(body['inspect_feedback']) is not bool:
            raise InputError('inspect_feedback must be a boolean')
        if 'inspect_approaches' in body and type(body['inspect_approaches']) is not bool:
            raise InputError('inspect_approaches must be a boolean')
        for field, maximum in (('candidate_calls',1000),('decision_calls',1000),('input_bytes',100_000_000)):
            if type(body[field]) is not int or not 0<=body[field]<=maximum:
                raise InputError(f'{field} must be an integer between 0 and {maximum}')
        config=check()
        if config['candidate']['state']!='configured':
            raise InputError('Configure the candidate model in the server environment, then restart the server.')
        if body['decision_calls'] and config['decision']['state']!='configured':
            raise InputError('Set JEV_API_KEY in the server environment and restart before allowing decision calls.')
        with self.store.connect() as c:
            if not c.execute('SELECT 1 FROM runs WHERE id=?',(body['run_id'],)).fetchone():
                raise InputError('Rollout not found')
            from .semantic_watch import _current_complete
            if not _current_complete(c,body['run_id']):raise InputError('Select the latest completed rollout revision.')
        # Credentials never enter the directory name, metadata or status response.
        identity={k:config['candidate'][k] for k in ('endpoint','model','contract')}
        directory=self.root/digest(dict(run=body['run_id'],candidate=identity,decision=config['decision']['model']))[:24]
        with self.lock:
            if self.thread and self.thread.is_alive():raise InputError('A model pilot is already running. Its progress is shown below.')
            self.current=dict(state='running',run_id=body['run_id'],directory=str(directory),limits=body)
            # A resume should not remove the already published inspection link.
            saved=directory/'pilot-result.json'
            if saved.exists():
                previous=json.loads(saved.read_text(encoding='utf-8'))
                if previous.get('run_id')==body['run_id'] and previous.get('result'):
                    self.current['result']=previous['result']
            write(directory/'pilot-result.json',self.current)
            def work():
                try:
                    result=pilot(self.store,directory,**body)
                    update=dict(state=result['status'],result=result)
                except InputError as exc:
                    update=dict(state='blocked',message=str(exc))
                except Exception as exc:
                    update=dict(state='blocked',message='Pilot stopped: '+type(exc).__name__+'. Saved requests and usage are retained.')
                with self.lock:
                    self.current.update(update)
                    write(directory/'pilot-result.json',self.current)
            self.thread=threading.Thread(target=work,name='rilldex-model-pilot',daemon=True)
            self.thread.start()
        return self.status()
