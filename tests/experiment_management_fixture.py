"""A multi-page sweep with process-only runs, tags and recorded trainer metrics."""
import math
import os
from pathlib import Path
import sys
import threading
from tracker import server
from tracker.run_records import receive, organize
from tracker.store import Store
from tracker.trainer_telemetry import TrainerTelemetry

root=Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
store=Store(root/('sweep-'+str(os.getpid())+'.sqlite'))
for i in range(40):
    experiment=f'sweep/seed-{i:02d}'
    receive(store,dict(schema='run-records/1',producer='worker',experiment=experiment,records=[dict(
        id='manifest',session='first',kind='manifest',observed_at='2026-10-22T00:00:00Z',
        payload=dict(name=f'Seed {i:02d}',project='Baseline' if i<20 else 'Candidates',
                     config={'seed':i,'learning_rate':1e-6,'sampling':{'temperature':0.7 if i%2 else 1.0,'top_p':0.95},
                             'gradient_checkpointing':bool(i%2),'optimizer':'adamw','reward':{'grader':'v1' if i<20 else 'v2'},
                             'eval_datasets':['math','code'],'optional':None},runtime={}))]))
    organize(store,experiment=experiment,tags=['sweep',f'seed-{i}'])
    if i%5:
        logger=TrainerTelemetry(store,experiment=experiment,producer='worker',session='first',
            framework='trl-grpo',framework_version='fixture',objective='grpo',environment='software')
        for step in range(8):logger.log({'reward':0.2+step*.02+math.sin(i+step)*.01,'loss':.7-step*.03},step=step)
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start()
    return instance
server.LocalServer=managed
server.serve(store,port=0)
