from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,math,sys,threading
from rilldex import Run
from rilldex.run import hardware_sample
from tracker.store import Store
from tracker import server,run_records

root=Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
db=root/('demo-'+str(__import__('os').getpid())+'.sqlite')
store=Store(db)
from tracker.execution_records import receive
receive(store,dict(schema='execution-records/2',producer='learner',experiment='Legacy run',records=[dict(
    id='config',revision=0,kind='configuration',rollout=None,state='completed',context={},
    evidence='authored UI fixture',timing=dict(clock='seconds',start=1,end=2),configuration={'learning_rate':0.01})]))
if not run_records.records(store,experiment='product-check/baseline')['total']:
    for name in ('baseline','candidate','long context / λ'):
        with Run(name,project='product-check',workspace=db,capture_console=False,hardware=False,producer='worker-0',config={'learning_rate':1e-6,'batch_size':128,'precision':'bf16'}) as r:
            for i in range(40):
                r.log({'loss':0.6+math.sin(i/5)*0.02,'reward':0.3+i/100},step=i)
                r.console(f'update={i} loss={0.6+math.sin(i/5)*0.02:.4f}\n')
            r.console('A recoverable timeout on worker-2\n',stream='stderr')
            file=root/'configuration.json';file.write_text(json.dumps({'lr':1e-6,'batch':128}),encoding='utf-8');r.add_file(file)
            for i in range(36):
                record={'id':'sample-'+str(i),'session':r.session,'kind':'hardware','observed_at':(datetime.now(timezone.utc)-timedelta(seconds=(36-i)*10)).isoformat(),'payload':{'host':'simulated-worker','cpu_percent':50+math.sin(i)*8,'memory_used_bytes':16*1073741824,'memory_total_bytes':64*1073741824,'gpus':[{'uuid':'sim-GPU','name':'Illustrative GPU','utilization_percent':80+math.sin(i)*10,'memory_used_bytes':30*1073741824,'memory_total_bytes':80*1073741824}],'unavailable':[]}}
                run_records.receive(store,{'schema':run_records.VERSION,'producer':r.producer,'experiment':r.experiment,'records':[record]})
    (root/'host-sensors.json').write_text(json.dumps(hardware_sample(),indent=2),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():
        sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start()
    return instance
server.LocalServer=managed
server.serve(store,port=0)
