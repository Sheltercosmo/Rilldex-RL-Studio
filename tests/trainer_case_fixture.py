"""Authored long native stream with linked, reused and undelivered rollouts."""
import json
import os
from pathlib import Path
import sys
import threading

from rilldex import TrainerTelemetry, chat_document
from tracker import server, training_lineage
from tracker.store import Store

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
store=Store(root/('linked-'+str(os.getpid())+'.sqlite'))
experiment='linked-update-study';sources={};refs={}
for name,success in [('before',False),('after',True),('shared',True)]:
    messages=[dict(role='user',content='Fix the parser for nested quoted values.')]
    for attempt in range(6):
        messages += [dict(role='assistant',content=f'Attempt {attempt+1}: inspect escaping and revise the parser.'),
                     dict(role='tool',name='test',content='Nested quote case passes.' if success and attempt==5 else 'Nested quote case fails: unexpected delimiter.')]
    messages.append(dict(role='assistant',content='Verified the nested quoting tests.' if success else 'The nested quote case is still unresolved.'))
    meta=dict(experiment=experiment,task_id='parser',task_revision='1',environment='terminal',environment_version='1',
              split='train',reward_definition='tests/v1',training_step=900 if name=='before' else 700,synthetic=True)
    sources[name]=store.ingest(dict(producer='actor',rollout_id=name,revision=0,state='complete',metadata=meta,
                                    document=chat_document(messages,success=success)))['id']
    records=[dict(id='sample-'+name,revision=0,kind='sample',sample=dict(producer='actor',rollout_id=name),
                  evidence=dict(basis='authored source',source_revision=0),data=dict(split='train')),
             dict(id='use-'+name,revision=0,kind='use',sample=dict(producer='actor',rollout_id=name),
                  evidence=dict(basis='authored learner'),data=dict(stage='optimizer_step_completed',learner_step=42,batch_id='batch'))]
    training_lineage.receive(store,dict(schema='training-records/1',producer='learner',experiment=experiment,records=records))
    refs[name]=dict(producer='learner',id='use-'+name,revision=0)
logger=TrainerTelemetry(store,experiment=experiment,producer='learner',session='first',
    framework='trl-grpo',framework_version='authored-test',objective='grpo/control')
for step in range(256):
    uses=[refs['before' if step<128 else 'after'],refs['shared']]
    if step%29==0:uses.append(dict(producer='late-worker',id='pending',revision=0))
    logger.log({'loss':.8-step/1000,'reward':.2+step/500},step=step,record_id='update-'+str(step),
        **({'training_uses':dict(records=uses,coverage='partial' if step%29==0 else 'complete',basis='authored log context')} if step%31 else {}))
other=TrainerTelemetry(store,experiment='reference-without-links',producer='learner',session='first',
    framework='trl-grpo',framework_version='authored-test',objective='grpo/control')
for step in range(256):other.log({'loss':.7-step/1100,'reward':.2+step/550},step=step)
(root/'fixture.json').write_text(json.dumps(dict(experiment=experiment,sources=sources)),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start();return instance
server.LocalServer=managed
server.serve(store,port=0)
