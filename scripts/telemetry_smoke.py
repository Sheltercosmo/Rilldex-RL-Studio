"""Synthetic native logger -> durable outbox -> real HTTP -> SQL/chart API.

Run against an isolated collector; this creates an explicitly synthetic experiment.
No model or trainer inference is performed.
"""
import argparse
import json
import math
from pathlib import Path
from urllib.request import urlopen

from rilldex import Outbox, TrainerTelemetry, generation_document


def run(endpoint, directory, steps=128):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    experiment='synthetic-native-telemetry'
    for name,profile in [('trl','trl-grpo'),('verl','verl')]:
        outbox=Outbox(directory/(name+'.sqlite'),endpoint=endpoint,producer='simulation/'+name)
        log=TrainerTelemetry(outbox,experiment=experiment,framework=profile,framework_version='synthetic-log-contract-v1',
            objective='synthetic-dapo' if name=='trl' else 'synthetic-gspo',session='simulation-1')
        for step in range(steps):
            loss=.6*math.exp(-step/45)+.015*math.sin(step/5)
            entropy=1.6-.006*step
            if name=='trl':
                native={'loss':loss,'entropy':entropy,'kl':.01+step*.0001,'clip_ratio/region_mean':.1+step*.002,
                        'num_tokens':(step+1)*16384,'train_tokens_per_second':1800+step*5}
            else:
                native={'actor/pg_loss':loss,'actor/entropy':entropy,'actor/ppo_kl':.005+step*.0002,
                        'actor/pg_clipfrac':.15+step*.003,'perf/total_num_tokens':16384,'perf/throughput':450+step*2}
            if step in (43,44):native.pop('entropy' if name=='trl' else 'actor/entropy')
            if step==72:native['loss' if name=='trl' else 'actor/pg_loss']=float('nan')
            log.log(native,step=step)
        # Recreate the transport after enqueue, like a restarted/offline worker.
        resumed=Outbox(outbox.path,endpoint=endpoint,producer=outbox.producer)
        result=resumed.drain(limit=steps+10)
        assert result['pending']==0 and result['blocked']==0,result
    with urlopen(endpoint+'/api/trainer-telemetry?experiment='+experiment) as response:data=json.load(response)
    assert data['records']==steps*2,data['records']
    assert not data['missing_groups'],data['missing_groups']
    assert len(data['series'])==12,len(data['series'])
    for series in data['series']:
        assert len(series['points'])==steps
        if series['group']=='entropy':assert series['recorded']==steps-2
        if series['group']=='loss':assert series['recorded']==steps-1
    # The UI assets are served by the same installed application as the API.
    for route in ('/','/trainer-telemetry.js','/trainer-telemetry.css','/connections'):
        with urlopen(endpoint+route) as response:assert response.status==200
    return dict(experiment=experiment,steps=steps,logs=data['records'],series=len(data['series']),url=endpoint+'/?experiment='+experiment)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--endpoint',required=True);p.add_argument('--directory',required=True)
    a=p.parse_args();print(json.dumps(run(a.endpoint,a.directory),indent=2))
