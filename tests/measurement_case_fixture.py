"""Recorded check mechanics and authored work links for UI navigation tests."""
import json
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).parent))
from test_recovery_windows import captured, check, change
from test_repeated_work import fixture, freeze
from rilldex import Workspace
from tracker import monitoring, server, graph_store, monitor_evidence, investigation_workspace, annotation_changes
from tracker.schema import digest
from tracker.store import Store

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
os.environ['RILLDEX_WORKSPACE_REGISTRY']=str(root/'registry.sqlite')
store=Store(root/('measured-cases-'+str(os.getpid())+'.sqlite'));sources={}
for side in ['reference','selected']:
    steps=[]
    for index in range(35):
        criterion='parser-case-'+str(index).zfill(2)
        steps.extend([check(criterion=criterion,text=f'{side}: validate parser case {index}.'),change(state={'record':index+1}),
                      check('unknown' if index%9==0 else 'passed',criterion=criterion)])
    run=captured(steps)
    run['metadata'].update(experiment=side,task_id='parser-checks',task_revision='1',environment='terminal',environment_version='1',
                           split='train',reward_definition='checks/v1',training_step=0 if side=='reference' else 1,
                           training_clock='policy',training_step_basis='generation',synthetic=True)
    run['id']=digest(run)[:24];store.add([run]);sources[side]=run['id']
    run,graph,_=fixture(('train --lr 0.01','install dependency','train --lr 0.01' if side=='reference' else 'train --lr 0.005'))
    events={event['id']:event for event in run['events']}
    for node in graph['nodes']:
        if node['kind']=='unit':
            unit=node['properties'];event=events[unit['source']['event_id']]
            unit['source']['source_pointer']=event['source_pointer']
            unit['trajectory_id']=event['trajectory_id']
    run['metadata'].update(experiment=side,task_id='training-command',task_revision='1',environment='terminal',environment_version='1',split='train',reward_definition='checks/v1',synthetic=True)
    run['id']=digest(run)[:24];graph.update(run_id=run['id'],source_hash=digest(run),metadata=run['metadata']);graph=freeze(graph)
    annotation_changes._inventory(graph)
    store.add([run])
    with store.connect() as c:graph_store.save(c,graph)
    sources[side+'-revisit']=run['id']
monitors={}
for name,measure,observer in [('recovery','criterion_recovery_window','source'),('revisit','revisit_input_change_fraction','test')]:
    monitors[name]=monitoring.create(store,dict(name='Recovery windows' if name=='recovery' else 'Changed repeated attempts',kind='analysis',observer=observer,analysis=dict(measure=measure)))
monitoring.sync(store)
workspace=Workspace(store.path)
saved=workspace.compare_rollouts(reference=dict(experiment='reference'),selected=dict(experiment='selected'),monitor_ids=[m['id'] for m in monitors.values()])
interval=investigation_workspace.save(store,dict(experiment='reference',baseline=[0,0],current=[1,1],monitor_ids=[monitors['recovery']['id']]))
values={}
for name,monitor in monitors.items():
    rid=sources['reference' if name=='recovery' else 'reference-revisit']
    value=monitoring.values(store,monitor['id'],[rid])[rid];receipt=monitor_evidence.read(store,value['id'])
    values[name]=dict(value=value['id'],run=rid,graph=receipt['graph']['id'],cases=receipt['explanation']['analysis_cases'])
(root/'fixture.json').write_text(json.dumps(dict(saved=saved['id'],interval=interval['id'],monitors={k:v['id'] for k,v in monitors.items()},values=values)),encoding='utf-8')
original=server.LocalServer
def managed(*args,**kwargs):
    instance=original(*args,**kwargs)
    def stop():sys.stdin.read();instance.shutdown()
    threading.Thread(target=stop,daemon=True).start();return instance
server.LocalServer=managed
server.serve(store,port=0)
