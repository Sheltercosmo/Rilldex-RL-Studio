"""Authored, explicitly synthetic findings report demonstration; no model calls."""
import argparse
import json
from pathlib import Path

from rilldex import chat_document, Workspace
from tracker.adapters import normalize
from tracker.store import Store
from tracker.schema import digest
from tracker import monitoring, investigation_workspace, investigation_followups, graph_store, evaluation_receipts


def seed(database):
    store=Store(database);runs=[]
    for step,task,success in [(0,'delivery-A',True),(0,'delivery-B',True),(1,'delivery-A',False),(1,'delivery-B',True)]:
        text='Delivery confirmation: parcel reached its destination.' if success else 'Delivery check failed: parcel remained at the depot after the retry budget was exhausted.'
        run=normalize(chat_document([dict(role='user',content=f'Synthetic report control: deliver parcel {task} in window {step}.'),
            dict(role='assistant',content='I will submit the delivery, inspect the receipt, and retry if needed.'),
            dict(role='user',content=text)],success=success,metadata=dict(experiment='report-controls',environment='synthetic-delivery',task_id=task,
            training_step=step,training_clock='policy',training_step_basis='generation',split='train',reward_definition='delivery/control-v1')))[0]
        run['outcome']['recorded_reward']=1 if success else 0;store.add([run])
        with store.connect() as c:graph_store.save(c,graph_store.build(run))
        runs.append(run)
    monitors=[monitoring.create(store,dict(name=name,kind='metric',metric=metric,observer='source')) for name,metric in [('Task success','recorded_success'),('Reward','recorded_reward'),('Actions','actions')]]
    monitoring.sync(store)
    root=investigation_workspace.save(store,dict(experiment='report-controls',baseline=[0,0],current=[1,1],monitor_ids=[m['id'] for m in monitors],
        title='Delivery regression · synthetic report example',hypothesis='Did a reduced retry budget explain the delivery failure in the selected interval?'))
    def plan(doc,title,hypothesis,procedure):
        return investigation_followups.save(store,dict(parent_id=doc['id'],action='plan',check=dict(title=title,hypothesis=hypothesis,procedure=procedure,expected_result='Compare the saved outcomes and exact source evidence.')))
    def finding(doc,assessment,conclusion,refs,limitations='',next_action=''):
        return investigation_followups.save(store,dict(parent_id=doc['id'],action='result',check=dict(id=doc['follow_up']['checks'][-1]['id'],assessment=assessment,conclusion=conclusion,evidence=refs,limitations=limitations,next_action=next_action)))
    failed=runs[2];ws=Workspace(database)
    receipt=ws.record_evaluation(dict(schema=evaluation_receipts.VERSION,label='Synthetic delivery verification',producer='authored-report-control/1',performed_at='2026-10-21T12:00:00Z',
        run_id=failed['id'],source_hash=digest(failed),purpose='independent_check',inputs={role:dict(label=role,sha256=digest(role)) for role in evaluation_receipts.INPUTS},
        execution='completed',verdict='failed',score=0,summary='Authored control result; no real environment or model was evaluated.',evidence=[dict(label='Control output',text='Parcel remained at the depot.')],
        source_citations=[ws.cite_source(failed['id'],failed['events'][-1]['id'],role='context')]))
    doc=plan(root,'Outcome and source check','The failed delivery followed budget exhaustion.','Inspect the recorded confirmation and failure message.')
    doc=finding(doc,'inconclusive','One of two deliveries failed in the selected window; both baseline deliveries succeeded. The source mentions budget exhaustion, but no controlled budget intervention is recorded.',
        [dict(kind='evaluation',id=receipt['id']),dict(kind='investigation',id=root['id'])],limitations='Four authored rollouts, not evidence of real model behavior.',next_action='Attach a fixed-task budget comparison if one is run.')
    doc=plan(doc,'Counterexample','Every task regressed after the change.','Compare the same task IDs in both windows.')
    doc=finding(doc,'contradicts','Task delivery-B succeeded in both windows. The observed change is limited to delivery-A in this small control set.',[dict(kind='investigation',id=root['id'])])
    doc=plan(doc,'Budget comparison','Changing only the budget restores the failed task.','Run a fixed-task comparison with recorded settings and verification.')
    return dict(investigation=doc['id'],root=root['id'],evaluation=receipt['id'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=seed(args.database);Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
