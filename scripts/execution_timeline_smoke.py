"""Synthetic asynchronous execution -> durable HTTP -> frozen view -> source maps.

The curves below are authored test signals, not an RL or NVFP4 experiment.
"""
import argparse
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

from rilldex import Outbox, TrainerTelemetry, chat_document


def run(endpoint,directory,steps=64):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    experiment='synthetic-execution-signals';clock='synthetic/shared-seconds'
    out=Outbox(directory/'sender.sqlite',producer='simulation',endpoint=endpoint)
    definitions={'reward':dict(label='Synthetic reward',group='reward',unit='score',reduction='authored update mean',definition='Authored integration-test curve, not measured RL.'),
                 'gap':dict(label='Synthetic trainer–sampler gap',group='mismatch',unit='nats',reduction='authored masked mean',definition='Authored gap; not a measured divergence or quantization effect.')}
    logger=TrainerTelemetry(out,experiment=experiment,framework='verl',framework_version='authored-test',objective='simulation-only',session='start-1',definitions=definitions)
    def put(record):out.log_execution(experiment,[record],schema='execution-records/2')
    def read(path):
        with urlopen(endpoint+path) as response:return json.load(response)
    def records(step):
        age=1 if step<steps//3 else 4 if step<2*steps//3 else 2
        policy=lambda index:dict(schema='policy-clock/1',clock='synthetic/weights',unit='policy_publication',index=index)
        use_refs=[]
        for worker in range(4):
            identifier=f'episode-{step}-{worker}';start=step*10+worker*.4;duration=3+worker*2
            reference=dict(producer='simulation',rollout_id=identifier)
            span=dict(id=identifier,revision=1,kind='inference',rollout=dict(producer='simulation',id=identifier),state='completed',
                context=dict(worker=f'Sampler {worker+1}',backend='synthetic-server',environment='terminal',policy_version=f'v{step}'),
                source_revision=0,evidence='Synthetic asynchronous integration control',timing=dict(clock=clock,start=start,end=start+duration),
                configuration=dict(precision='bf16' if step<steps//3 else 'nvfp4',backward_mode='dequantized' if step>=2*steps//3 else 'high_precision'),
                metrics=dict(duration_ms=duration*1000,output_tokens=800+worker*300))
            # Completion can arrive before its earlier running report.
            put(span);put({**span,'revision':0,'state':'running','timing':{**span['timing'],'end':None},'metrics':{}})
            messages=[dict(role='user',content='Inspect the failing parser, apply a focused change, and verify the result.')]
            for turn in range(24):
                messages.extend([dict(role='assistant',content=f'Inspection {turn+1}: compare the parser state with the expected input and revise the failing case.'),
                                 dict(role='user',content=f'Test observation {turn+1}: '+('failure remains' if turn<20 else 'case passes'))])
            out.log(identifier,chat_document(messages,success=(step+worker)%7!=0),state='complete',
                metadata=dict(experiment=experiment,environment='terminal',training_step=step,policy_version=f'v{step}'))
            facts=[dict(id='sample-'+identifier,revision=0,kind='sample',sample=reference,evidence=dict(basis='synthetic sample',source_revision=0),
                data=dict(split='train',environment='terminal',step=step,step_basis='generation',policy_history=dict(schema='generation-policy-history/1',token_count=4,segments=[dict(start=0,end=4,policy=policy(step))]))),
                dict(id='selection-'+identifier,revision=0,kind='selection',sample=reference,evidence=dict(basis='synthetic filter'),
                     data=dict(filter='synthetic-admission',definition='authored filter',decision='rejected' if worker==3 and step%4==0 else 'admitted',batch_id=str(step)))]
            if not (worker==3 and step%4==0):
                facts.append(dict(id='use-'+identifier,revision=0,kind='use',sample=reference,evidence=dict(basis='synthetic optimizer receipt'),
                    data=dict(stage='optimizer_step_completed',batch_id=str(step),learner_step=1000+step,model_tokens=4,learner_policy=policy(step+age))))
                use_refs.append(dict(producer='simulation',id='use-'+identifier,revision=0))
            out.log_training(experiment,facts)
        return use_refs
    for step in range(steps):
        refs=records(step)
        phase=step//max(1,steps//3)
        logger.log({'actor/pg_loss':.5/(1+step/10),'actor/grad_norm':2+(12 if phase==1 and step%5==0 else 0),
                    'reward':.5+.003*step-(.2 if phase==1 else 0),'gap':.03 if phase==0 else .23 if phase==1 else .06,
                    'perf/throughput':400 if phase==0 else 700},step=1000+step,record_id=f'log-{step}',
                   training_uses=dict(coverage='complete',basis='authored consumed samples',records=refs))
        put(dict(id=f'update-{step}',revision=1,kind='learner_update',rollout=None,state='completed',context=dict(worker='Learner'),
                 evidence='Synthetic update boundary',timing=dict(clock=clock,start=step*10+12,end=step*10+15),
                 telemetry=[dict(producer='simulation',id=f'log-{step}')],configuration=dict(phase='baseline' if phase==0 else 'changed precision' if phase==1 else 'revised backward')))
        if step%8==0:put(dict(id=f'sync-{step}',revision=1,kind='weight_sync',rollout=None,state='completed',context=dict(worker='Weight publication'),
                             evidence='Synthetic publication boundary',timing=dict(clock=clock,start=step*10+15,end=step*10+16)))
        if step in (steps//3,2*steps//3):put(dict(id=f'configuration-{step}',revision=1,kind='configuration',rollout=None,state='completed',context=dict(worker='Configuration'),
            evidence='Authored phase marker',timing=dict(clock=clock,start=step*10,end=step*10),configuration=dict(phase=phase)))
        if step%8==7:
            result=out.drain(limit=1000);assert result['blocked']==0,result
    # One unfinished request remains visible, with no invented end time.
    put(dict(id='unfinished',revision=0,kind='inference',rollout=dict(producer='simulation',id='pending'),state='running',context=dict(worker='Sampler 4'),
             evidence='Synthetic pending work',timing=dict(clock=clock,start=steps*10,end=None)))
    out=Outbox(out.path,producer='simulation',endpoint=endpoint)
    delivery=out.drain(limit=10000);assert delivery['pending']==delivery['blocked']==0,delivery
    value=read('/api/training-execution?experiment='+experiment+'&clock='+clock)
    assert len(value['logs'])==steps
    assert len(value['samples'])==steps*4
    assert value['counts']['states']['running']==1
    assert not value['truncated']
    assert all(not l['unresolved_uses'] for l in value['logs'])
    assert {c['mean_age'] for l in value['logs'] for c in l['policy_age']['clocks']}=={1,2,4}
    body=json.dumps(dict(experiment=experiment,clock=clock)).encode()
    with urlopen(Request(endpoint+'/api/training-execution/save',data=body,headers={'Content-Type':'application/json'})) as response:frozen=json.load(response)
    put(dict(id='unfinished',revision=1,kind='inference',rollout=dict(producer='simulation',id='pending'),state='failed',context=dict(worker='Sampler 4'),
             evidence='Synthetic pending work',timing=dict(clock=clock,start=steps*10,end=steps*10+15)))
    out.drain()
    assert read('/api/training-execution?saved='+frozen['saved'])==frozen
    assert read('/api/training-execution?experiment='+experiment+'&clock='+clock)['counts']['states']['failed']==1
    first=value['samples'][0]['run_id'];assert first
    with urlopen(endpoint+'/semantic-map?run='+first) as response:assert response.status==200
    return dict(experiment=experiment,steps=steps,rollouts=len(value['samples']),trace_events=steps*4*49,
                spans=value['counts']['executions'],saved=frozen['saved'],url=endpoint+'/?view=execution&experiment='+experiment,
                boundary='Synthetic transport, linkage and UI validation; not real RL or detector accuracy.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--endpoint',required=True);parser.add_argument('--directory',required=True);parser.add_argument('--steps',type=int,default=64)
    args=parser.parse_args();print(json.dumps(run(args.endpoint,args.directory,args.steps),indent=2))
