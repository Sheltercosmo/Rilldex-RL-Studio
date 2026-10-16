"""Installed tau2 execution -> durable HTTP outbox -> Rilldex evidence and SQL.

Recorded policy messages; actual native tool execution and deterministic native
evaluators. No optimizer, adaptive policy, model provider or LLM evaluator.
The separate population probe chooses cases; it is never the execution result.
"""
import argparse
from copy import deepcopy
import importlib.util
import json
import math
import os
from pathlib import Path
import sys


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();project=Path(__file__).resolve().parents[1];root=args.root.resolve()
    if root.exists():raise ValueError('Use a fresh audit directory; retain prior evidence')
    (root/'outputs').mkdir(parents=True)
    os.environ.update(TAU2_DATA_DIR=str((args.repository/'data').resolve()),PYTHON_DOTENV_DISABLED='1',LITELLM_LOCAL_MODEL_COST_MAP='True')
    # Installation boundaries are part of the audit, not supplied source modules.
    from loguru import logger
    logger.remove()
    import rilldex,tau2
    assert 'site-packages' in str(rilldex.__file__) and 'site-packages' in str(tau2.__file__)
    from rilldex import Outbox,Workspace
    from tracker.adapters import normalize
    from tracker.capabilities import links
    from tracker.store import Store
    from tracker.monitoring import create,validate
    from tau2.data_model.tasks import Task
    lifecycle=load_module('lifecycle',project/'scripts/rl_lifecycle_simulation.py')
    probe=load_module('tau_probe',project/'research/tau_runtime_probe.py')
    summary=json.loads(args.probe.read_text(encoding='utf-8'));population=summary['rows']
    documents=[];seen=set();collections={}
    def add(doc):
        identity=doc['simulation']['id']
        if identity not in seen:seen.add(identity);documents.append(doc)
    for path in sorted((project/'tests/fixtures/tau-bench').glob('*-[0-9]*.json')):add(json.loads(path.read_text(encoding='utf-8')))
    selected=[]
    for domain in ('airline','telecom'):
        selected.append(max((r for r in population if r['domain']==domain),key=lambda r:len(r['calls'])))
    selected.append(next(r for r in population if any(c['error'] for c in r['calls'])))
    selected.extend(r for r in population if r['status']=='incomplete_recorded_feedback')
    for row in selected:
        file,index=row['fixture'].rsplit('#',1)
        if file not in collections:collections[file]=json.loads((project/file).read_text(encoding='utf-8'))
        collection=collections[file];sim=collection['simulations'][int(index)]
        add({'info':collection['info'],'simulation':sim,'task':next(t for t in collection['tasks'] if t['id']==sim['task_id'])})
    monitor_definitions=[validate({'name':label,'kind':'metric','observer':'source','metric':key,
                                  'group':'Reward integrity' if key.startswith('reward_') else 'Behavior'})
        for key,label in [('environment_tool_error_fraction','Tool responses flagged as errors'),
                          ('reward_component_zero_observed','Zero-valued reward component'),
                          ('reward_diagnostic_failure_observed','Unmet checks outside the reward')]]
    experiment='executed-tau-environment-replay';server=lifecycle.Server(root,experiment);evidence=[];finals=[]
    server.start();outbox=Outbox(root/'outbox.sqlite',endpoint=server.url,producer='native-tau',timeout=2)
    outage=False;outage_done=False;callbacks=0;prefix_assertions=0;actual_call_count=0
    def drain():
        status=outbox.drain(limit=1000)
        assert status['blocked']==0 and status['pending']==0,status
    try:
        for index,original in enumerate(documents):
            document=deepcopy(original);document['trajectory_format']='tau-bench/1'
            identity='executed-'+document['simulation']['id']
            document['simulation']['id']=identity
            document['source_origin']={'policy':'recorded public trajectory','execution':'native tau2 runtime',
                                       'source_simulation_id':original['simulation']['id']}
            document['info']['git_commit']='4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699'
            # Do not propagate historical evaluator output or final timestamps into prefixes.
            template=deepcopy(document);template['simulation']['reward_info']=None
            template['simulation'].pop('end_time',None);template['simulation'].pop('duration',None)
            def snapshot(through,calls,terminal=None):
                doc=deepcopy(template);sim=doc['simulation'];sim['messages']=sim['messages'][:through+1]
                for call in calls:
                    at=call.get('response_message_index')
                    if at is None or at>through:continue
                    old=sim['messages'][at]
                    if old['role']=='tool':sim['messages'][at]=deepcopy(call['actual'])
                    else:
                        old['tool_messages']=[deepcopy(call['actual']) if (r['requestor'],r['id'])==(call['requestor'],call['call_id']) else r for r in old['tool_messages']]
                sim['termination_reason']=original['simulation']['termination_reason'] if terminal=='complete' else 'in_progress'
                return doc
            def on_message(position,calls):
                nonlocal callbacks,outage,outage_done,outbox,prefix_assertions
                if not any(c.get('response_message_index')==position for c in calls):return
                callbacks+=1;doc=snapshot(position,calls)
                outbox.log(identity,doc,state='in_progress',format='tau-bench',metadata={'experiment':experiment})
                if callbacks==3:
                    server.stop();outage=True
                    status=outbox.drain();assert status['retryable_error'] and status['pending']>0,status
                if outage and callbacks>=6:
                    server.start();outbox=Outbox(root/'outbox.sqlite',endpoint=server.url,producer='native-tau',timeout=2)
                    drain();outage=False;outage_done=True
                elif not outage:drain()
                if not outage:
                    with outbox.connect() as c:
                        receipt=json.loads(c.execute('SELECT receipt FROM queue WHERE rollout=? ORDER BY revision DESC LIMIT 1',(identity,)).fetchone()[0])
                    observed=server.request('/api/runs/'+receipt['id']+'?raw=1')['run']
                    assert observed['outcome']['recorded_reward'] is None
                    assert len(observed['raw']['simulation']['messages'])==position+1
                    prefix_assertions+=1
            result=probe.replay(document,on_message=on_message);actual_call_count+=len(result['calls'])
            if outage:
                server.start();outbox=Outbox(root/'outbox.sqlite',endpoint=server.url,producer='native-tau',timeout=2)
                drain();outage=False;outage_done=True
            final=snapshot(len(original['simulation']['messages'])-1,result['calls'],terminal='complete' if result['status']=='replayed' else None)
            terminal=result['status']=='replayed' and 'error_type' not in result['native_evaluation']
            if terminal:
                basis=Task.model_validate(document['task']).evaluation_criteria.model_dump(mode='json')['reward_basis']
                reward={'reward_basis':basis,'reward_breakdown':{}}
                for part in result['native_evaluation'].values():
                    reward['reward_breakdown'].update(part.get('reward_breakdown') or {})
                    for field in ('db_check','env_assertions','communicate_checks','action_checks'):
                        if part.get(field) is not None:reward[field]=part[field]
                assert all(k in reward['reward_breakdown'] for k in basis),basis
                reward['reward']=math.prod(reward['reward_breakdown'][k] for k in basis)
                reward['info']={'execution':'Native deterministic evaluators; NL evaluator not run'}
                final['simulation']['reward_info']=reward
            outbox.log(identity,final,state='complete' if terminal else 'failed',format='tau-bench',metadata={'experiment':experiment})
            drain()
            # Exact producer replay should enqueue no further revision.
            sent=outbox.status()['sent'];outbox.log(identity,final,state='complete' if terminal else 'failed',format='tau-bench',metadata={'experiment':experiment})
            drain();assert outbox.status()['sent']==sent
            with outbox.connect() as c:
                receipt=json.loads(c.execute('SELECT receipt FROM queue WHERE rollout=? ORDER BY revision DESC LIMIT 1',(identity,)).fetchone()[0])
            rid=receipt['id'];actual=server.request('/api/runs/'+rid+'?raw=1')['run'];expected=normalize(final,'tau-bench',{'experiment':experiment})[0]
            assert actual['events']==expected['events']
            inspection=server.request('/api/reward-records/'+rid)
            if terminal:
                assert inspection['status']=='complete',inspection
                assert inspection['metrics']['reward_aggregation_gap']['value']==0
                assert actual['outcome']['recorded_reward']==reward['reward']
            else:assert not inspection['available'] and actual['outcome']['recorded_reward'] is None
            finals.append({'run_id':rid,'document':final,'expected':expected,'terminal':terminal})
            evidence.append({'run_id':rid,'source_simulation_id':original['simulation']['id'],'status':result['status'],
                'domain':result['domain'],'executed_calls':len(result['calls']),
                'tool_errors':sum(c['error'] is True for c in result['calls']),
                'state_changes':sum(c['before']!=c['after'] for c in result['calls']),
                'native_evaluation':result['native_evaluation'],'evaluation':inspection})
            (root/'execution-progress.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
            print(json.dumps({'case':index+1,'total':len(documents),'status':result['status'],'calls':len(result['calls'])}),flush=True)
        assert outage_done
        # Batch ingestion of the exact executed documents must preserve evidence.
        batch={'producer':'batch-tau','rollout_id':'batch-executed','revision':0,'state':'complete','format':'tau-bench','metadata':{'experiment':experiment+'-batch'}}
        for row in finals:
            batch.update(rollout_id=row['run_id'],document=row['document'],state='complete' if row['terminal'] else 'failed')
            receipt=server.request('/api/ingest',batch);again=server.request('/api/ingest',batch)
            assert receipt['id']==again['id'];actual=server.request('/api/runs/'+receipt['id']+'?raw=1')['run']
            assert actual['events']==row['expected']['events']
        # The code API triggers native indexes, then HTTP and SQL must agree.
        workspace=Workspace(server.db,experiment=experiment,observer='source')
        graphs=workspace.graphs().rows;assert len(graphs)==len(finals),(len(graphs),len(finals))
        rows=workspace.metrics(limit=10000).rows
        sql=workspace.sql("SELECT run_id,metric,value,numerator,denominator FROM measurements WHERE metric IN ('environment_tool_error_fraction','reward_component_zero_observed')",limit=1000).rows
        assert len(sql)==2*len(finals),len(sql)
        metrics=server.request('/api/rollout-metrics')['rows']
        values={r['run_id']:r['metrics'] for r in metrics if r['observer']=='source'}
        for row in finals:
            run=row['expected'];rid=row['run_id'];feedback={r['feedback_id'] for r in links(run)['records']}
            flagged=[e for e in run['events'] if e['id'] in feedback and type(e.get('reported_tool_error')) is bool]
            measurement=values[rid]['environment_tool_error_fraction']
            assert measurement['denominator']==len(flagged)
            assert measurement['numerator']==sum(e['reported_tool_error'] for e in flagged)
            assert values[rid]['activity_plan_share']['value'] is None,'Source replay fabricated semantic tags'
            assert run['metadata'].get('training_step') is None,'Replay order became a training coordinate'
            graph=next(g for g in graphs if g['run_id']==rid)
            loaded=server.request('/api/graphs/'+graph['graph_id']);ids={n['id'] for n in loaded['nodes']}
            assert all(e['source'] in ids and e['target'] in ids for e in loaded['edges'])
        for row in sql:assert row['value']==values[row['run_id']][row['metric']]['value']
        store=Store(server.db)
        for definition in monitor_definitions:create(store,definition)
        report={'status':'passed','schema':'executed-tau-audit/1','cases':evidence,'executed_calls':actual_call_count,
            'prefix_assertions':prefix_assertions,'outbox':outbox.status(),'server_starts':server.starts,
            'http_requests':server.request_counts,'sql_rows':sql,'graph_count':len(graphs),'measurement_rows':len(rows),
            'packages':{'rilldex':str(rilldex.__file__),'tau2':str(tau2.__file__)},
            'limits':['Agent/user decisions replayed, no fresh policy adaptation','No model API or semantic accuracy validation','No optimizer, GPU, inference-server or distributed-load claim','Historical source clocks are not runtime latency or training order']}
        (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:server.stop()


if __name__=='__main__':main()
