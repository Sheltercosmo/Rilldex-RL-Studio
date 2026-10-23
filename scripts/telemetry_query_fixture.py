"""Seed a fresh, labeled 50k-log control for full-run query/browser validation."""
import argparse
import json
import math
from pathlib import Path
import time

from tracker.store import Store
from tracker import trainer_telemetry as t, telemetry_queries as q
from tracker.adapters import normalize
from rilldex import chat_document


def seed(database):
    if Path(database).exists():
        raise ValueError('Use a new database path; this fixture never replaces saved data.')
    store=Store(database)
    store.add(normalize(chat_document([dict(role='assistant',content='Synthetic long-run telemetry validation. No actual model training.')],
                                     metadata=dict(experiment='long-telemetry-control',environment='terminal'))))
    config=dict(experiment='long-telemetry-control',producer='learner',framework='trl-grpo',framework_version='synthetic',
                objective='simulation',session='start-1',environment='terminal',definitions={
                    'reward':t.metric('Synthetic solve rate','reward','fraction','authored batch mean','Synthetic outcome curve for validating long-run inspection; no model was trained.')})
    records=[];started=time.perf_counter()
    for step in range(50000):
        reward=.3+.5*(1-math.exp(-step/7000))+.025*math.sin(step*.31)
        if step>45000:reward-=(step-45000)/20000
        logs={'reward':reward,'loss':.15+.015*math.sin(step*.17),'entropy':.7-.000006*step,
              'kl':1.8 if step==37 else .015+.003*math.sin(step*.11),
              'train_tokens_per_second':500+30*math.sin(step*.21),'num_tokens':step*4096}
        packet=t.packet(logs,step=step,**config);records+=packet['records']
        if len(records)==1000:t.receive(store,{**packet,'records':records});records=[]
    packet=t.packet({f'custom/metric-{i:03}':i for i in range(100)},step=49999,**{**config,'session':'additional-metrics'})
    t.receive(store,packet);ingest=time.perf_counter()-started;times=[]
    for _ in range(2):
        started=time.perf_counter();result=q.query(store,experiment=config['experiment'],half_life=10);times.append(time.perf_counter()-started)
    return dict(native_records=result['total_records'],series=result['total_series'],loaded_series=len(result['series']),
                ingest_seconds=round(ingest,3),cold_query_seconds=round(times[0],3),warm_query_seconds=round(times[1],3),
                plotted_points=sum(len(s['points']) for s in result['series']),as_of=result['as_of'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',required=True)
    print(json.dumps(seed(parser.parse_args().database),indent=2))
