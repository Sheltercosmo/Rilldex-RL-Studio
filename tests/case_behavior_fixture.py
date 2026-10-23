"""Authored task-composition shift; no model inference or semantic labels."""
import json
import os
from pathlib import Path
import sys
import threading

from rilldex import Workspace, chat_document
from tracker import monitoring, server
from tracker.store import Store

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
store=Store(root/('behavior-'+str(os.getpid())+'.sqlite'))
for side,easy,hard in [('reference',24,8),('selected',8,24)]:
    for task,count in [('escaping',easy),('nested-quoting',hard)]:
        for trial in range(count):
            success=task=='escaping';messages=[dict(role='user',content='Repair '+task+' in the parser and verify it.')]
            for attempt in range(16):
                messages.extend([dict(role='assistant',content=f'Attempt {attempt+1}: inspect the parser state, revise handling, then run the recorded test.'),
                                 dict(role='tool',name='test',content='Recorded check passes.' if success and attempt==15 else 'Recorded check fails: unexpected delimiter.')])
            meta=dict(experiment=side,task_id=task,task_revision='1',environment='terminal',environment_version='1',
                      split='train',reward_definition='tests/v1',synthetic=True,fixture_recoveries=3 if success else 1,
                      fixture_opportunities=4 if success else 5)
            store.ingest(dict(producer='actor',rollout_id=side+'-'+task+'-'+str(trial),revision=0,state='complete',
                              metadata=meta,document=chat_document(messages,success=success)))
success=monitoring.create(store,dict(name='Reported success',kind='metric',metric='recorded_success',observer='source',group='Training'))
length=monitoring.create(store,dict(name='Response length',kind='metric',metric='agent_text_chars',observer='source',group='Training'))
workspace=Workspace(store.path,observer='source')
recovery=workspace.monitor('Recorded recovery',version='fixture/1',description='Authored opportunity counts for browser testing',
                           unit='fraction',aggregation='opportunity_ratio')
result=recovery.run(lambda c:dict(numerator=c.run['metadata']['fixture_recoveries'],denominator=c.run['metadata']['fixture_opportunities'],unknown=1,
                                details={'basis':'Authored fixture counts; not inferred behavior'}))
assert result['errors']==0
monitoring.sync(store)
saved=workspace.compare_rollouts(reference=dict(experiment='reference'),selected=dict(experiment='selected'),
                                title='Task composition comparison',monitor_ids=[success['id'],recovery.id,length['id']])
(root/'fixture.json').write_text(json.dumps(dict(saved=saved['id'],success=success['id'],recovery=recovery.id,length=length['id'])),encoding='utf-8')
original=server.LocalServer

def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start();return instance
server.LocalServer=managed
server.serve(store,port=0)
