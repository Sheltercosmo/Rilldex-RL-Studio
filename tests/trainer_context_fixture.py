"""Authored restarts with repeated steps and cross-worker session collisions."""
import json
import sys
from pathlib import Path
from rilldex import Run, TrainerTelemetry
from tracker.store import Store

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True);db=root/'workspace.sqlite'
if db.exists():raise RuntimeError('Use a fresh fixture directory')
store=Store(db);captures={}
for name,worker,session in [('before','learner-a','native/1'),('after','learner-a','native/2'),('other','learner-b','native/1')]:
    with Run('restart-study',project='capture',workspace=db,producer=worker,hardware=False,capture_console=False,config={'seed':42}) as run:
        captures[name]=run.session
        run.log_config({'lr':.001 if name=='before' else .002,'enabled':False,'unknown':None},trainer_session=session)
        if name=='before':run.log_config({'lr':.0005,'enabled':False},trainer_session=session)
        run.console(name+' process console only')
        run._record('hardware',dict(host=name+'-host',cpu_percent=72,memory_used_bytes=1073741824,memory_total_bytes=4294967296,gpus=[],unavailable=[]))
        file=root/(name+'.txt');file.write_text(name+' config file',encoding='utf-8');run.add_file(file)
        trainer=TrainerTelemetry(store,experiment=run.experiment,producer=worker,session=session,framework='trl-grpo',framework_version='authored-context-test',objective='grpo/control')
        for step in range(4):trainer.log({'reward':.3+step*.1,'loss':.8-step*.1},step=step)
(root/'captures.json').write_text(json.dumps(captures),encoding='utf-8')
