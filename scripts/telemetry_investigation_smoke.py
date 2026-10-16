"""Installed HTTP replay of asynchronous native logs and long source traces.

Synthetic transport/attribution controls, not real RL or semantic-accuracy evidence.
"""
import argparse
import json
from pathlib import Path
import tempfile
from urllib.parse import urlencode

from rilldex import Outbox, TrainerTelemetry, Workspace, chat_document
from rl_lifecycle_simulation import Server


def run(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    server=Server(root,'synthetic-linked-telemetry');server.outputs.mkdir(exist_ok=True);server.start()
    try:
        exp=server.experiment
        actors=Outbox(root/'actors.sqlite',producer='actor',endpoint=server.url)
        metrics=Outbox(root/'metrics.sqlite',producer='metric-logger',endpoint=server.url)
        uses=Outbox(root/'uses.sqlite',producer='learner',endpoint=server.url)
        logger=TrainerTelemetry(metrics,experiment=exp,framework='verl',framework_version='authored-contract',
            objective='synthetic-gspo',session='start-1')
        for step in range(64):
            name=f'rollout-{step}';messages=[dict(role='user',content='Inspect, modify and verify the supplied artifact.')]
            for action in range(24):
                call=f'call-{action}'
                messages.append(dict(role='assistant',content=f'Check artifact revision {action}.',tool_calls=[dict(id=call,type='function',
                    function=dict(name='exec_command',arguments=json.dumps({'cmd':f'check artifact-{action}'})))]))
                messages.append(dict(role='tool',tool_call_id=call,content=json.dumps({'exit_code':1 if action%5==0 else 0})))
            messages.append(dict(role='assistant',content='Recorded checks are complete.'))
            actors.log(name,chat_document(messages,success=step%3!=0),state='complete',
                metadata=dict(experiment=exp,training_step=step,training_clock='policy',training_step_basis='generation',task_id=f'task-{step%8}'))
            records=[dict(id='sample-'+name,revision=0,kind='sample',sample=dict(producer='actor',rollout_id=name),
                evidence=dict(source_revision=0,basis='captured source'),data=dict(split='train')),
                dict(id='use-'+name,revision=0,kind='use',sample=dict(producer='actor',rollout_id=name),
                evidence=dict(basis='authored optimizer receipt'),data=dict(stage='optimizer_step_completed',learner_step=700+step%32,batch_id=f'batch-{step%32}'))]
            uses.log_training(exp,records)
        for step in reversed(range(32)):
            refs=[dict(producer='learner',id=f'use-rollout-{s}',revision=0) for s in (step,step+32)]
            logger.log({'actor/pg_loss':.6-step*.01,'actor/entropy':1-step*.01,'actor/ppo_kl':.01,
                'actor/pg_clipfrac':.2,'perf/total_num_tokens':4096,'perf/throughput':500+step},step=700+step,
                record_id=f'log-{step}',training_uses=dict(records=refs,coverage='complete',basis='Authored two-use log context'))
        assert actors.drain(limit=100)['pending']==0
        assert metrics.drain(limit=100)['pending']==0
        controls=dict(experiment=exp,baseline=[0,31],current=[32,63],monitor_ids=[],title='Synthetic linked trainer replay')
        original=server.request('/api/investigations/interval',controls)
        assert original['snapshot']['native_telemetry']['records']==[]
        # Retain logs and their references through a real collector restart.
        server.stop();server.start()
        uses=Outbox(uses.path,producer='learner',endpoint=server.url)
        assert uses.drain(limit=100)['pending']==0
        current=server.request('/api/investigations/interval',{**controls,'parent_id':original['id']})
        native=current['snapshot']['native_telemetry']
        assert len(native['records'])==32 and native['referenced_selected_uses']==64
        assert all(r['windows']==['baseline','current'] and len(r['run_ids'])==2 for r in native['records'])
        assert all('delta' not in r for r in native['records'])
        assert server.request('/api/investigations/'+original['id'])==original
        point=server.request('/api/trainer-telemetry/evidence?'+urlencode(dict(experiment=exp,producer='metric-logger',record_id='log-0')))
        assert point['matched_uses']==2
        mapped=server.request('/api/monitoring/rollout/'+point['run_ids'][0]+'?observer=source')
        assert len(mapped['run']['events'])>=50 and mapped['graph']['edges']
        ws=Workspace(server.db,experiment=exp)
        assert ws.telemetry_evidence(producer='metric-logger',record_id='log-0')==point
        assert len(ws.telemetry().rows)==32
        result=dict(result='passed',rollouts=64,native_logs=32,linked_uses=64,events_per_inspected_rollout=len(mapped['run']['events']),
            checks=['real HTTP and durable outboxes','out-of-order native logs','delayed use receipts','collector restart',
                    'mixed-window aggregate retained once','immutable earlier comparison','exact-source map drill-down','Python/HTTP parity'],
            investigation=current['id'],experiment=exp,database=str(server.db),
            boundary='Synthetic capture and attribution controls; no RL training, model inference or semantic accuracy claim.')
        (root/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result
    finally:server.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    if args.output:print(json.dumps(run(args.output),indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix='rilldex-telemetry-links-') as tmp:print(json.dumps(run(tmp),indent=2))
