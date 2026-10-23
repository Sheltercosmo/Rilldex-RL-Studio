from pathlib import Path
import json
import os
import sys
import threading

sys.path.insert(0,str(Path(__file__).parent))
from test_hardware_history import sample,insert
from tracker import server,run_records
from tracker.store import Store

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
store=Store(root/('hardware-'+str(os.getpid())+'.sqlite'))
for worker in range(2):
    producer='worker-'+str(worker);session='process-'+str(worker)
    manifest=dict(sample(0,session=session),id='manifest-'+str(worker),kind='manifest',payload=dict(name='Long hardware capture',project='hardware-test',config={'workers':2},runtime={}))
    rows=[manifest]
    for i in range(1200):
        gpu=dict(uuid='GPU-'+str(worker),name='Recorded test GPU',utilization_percent=80,memory_used_bytes=(30 if i==3 else 12)*2**30,memory_total_bytes=40*2**30,temperature_c=60,power_watts=200)
        rows.append(sample(i,session=session,host='machine-'+str(worker),cpu=99 if i==3 else None if 400<=i<430 else 50,gpus=[gpu] if i<1150 else []))
    rows.extend([sample(3,session=session,kind='console',text='early-memory-pressure on '+producer),sample(600,session=session,kind='console',text='outside selected interval')])
    insert(store,rows,producer=producer)
for i in range(6):insert(store,[sample(1201,session='restart-'+str(i),host='restarted-host',cpu=20)],producer='worker-0')
(root/'fixture.json').write_text(json.dumps(dict(experiment='training',samples=2406)),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start();return instance
server.LocalServer=managed
server.serve(store,port=0)
