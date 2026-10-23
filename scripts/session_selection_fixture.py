"""Authored multi-worker/restart history for selection and export regression tests."""
import argparse
import json
import math
from pathlib import Path

from tracker.store import Store
from tracker.trainer_telemetry import TrainerTelemetry,packet


def build(root):
    root.mkdir(parents=True,exist_ok=True);db=root/'workspace.sqlite'
    if db.exists():raise RuntimeError('Use a fresh fixture directory')
    store=Store(db)
    def config(experiment,producer,session):return dict(experiment=experiment,producer=producer,session=session,
        framework='trl-grpo',framework_version='authored-session-control',objective='grpo/control',environment='authored tasks')
    for index in range(120):
        collector=TrainerTelemetry(store,**config('session-history','worker-'+str(index%3),f'phase-{index//3:03}'))
        for step in range(16):
            values={'loss':.5+index/1000+math.sin(step/3)*.02,'reward':.2+index/500+step/200,
                'entropy':.8-step/100,'kl':.01+step/10000,'clip_ratio/region_mean':.1+step/1000,'num_tokens':step*1000}
            if index==119:values.update({f'custom/{i:03}':step+i for i in range(75)})
            collector.log(values,step=step)
    for i in range(3):
        collector=TrainerTelemetry(store,**config('session-baseline','baseline-worker',f'baseline-{i}'))
        for step in range(16):collector.log({'loss':.5,'reward':.2+i/10+step/200,'entropy':.8,'kl':.01,'clip_ratio/region_mean':.1,'num_tokens':step*1000},step=step)
    newer=packet({'loss':.4,'reward':.6,'entropy':.7,'kl':.01,'clip_ratio/region_mean':.1,'num_tokens':20000},
        step=0,**config('session-history','worker-0','new-phase'))
    (root/'arrival.json').write_text(json.dumps(newer),encoding='utf-8')
    print(db)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args();build(args.output.resolve())
