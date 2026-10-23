"""Native CPU capture exercise: offline start, HTTP delivery, checkpoint resume.

python scripts/validate_sb3_capture.py --output /path/to/new-validation-folder
Requires stable-baselines3. No model-provider requests or synthetic metric curves.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.parse import urlencode


def serve(db):
    import threading
    from tracker import server
    from tracker.store import Store
    original=server.LocalServer
    def managed(*args,**kwargs):
        instance=original(*args,**kwargs)
        def stop():sys.stdin.read();instance.shutdown()
        threading.Thread(target=stop,daemon=True).start()
        return instance
    server.LocalServer=managed
    server.serve(Store(db),port=0)


def validate(root):
    import importlib.metadata
    import torch
    from stable_baselines3 import PPO,DQN
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.callbacks import BaseCallback
    from rilldex import Run,Outbox,Workspace
    from tracker.store import Store
    from tracker import run_records
    torch.set_num_threads(1)
    root.mkdir(parents=True,exist_ok=True)
    db=root/'workspace.sqlite';queue=root/'worker.sqlite'
    if db.exists() or queue.exists():raise RuntimeError('Use a new output directory; existing workspaces are preserved')
    store=Store(db);box=Outbox(queue,producer='native-cpu-worker')
    checks=[];live=[];started=time.monotonic()
    class ConsoleProgress(BaseCallback):
        def _on_step(self):return True
        def _on_rollout_end(self):print('Collected environment transitions:',self.num_timesteps)
    with Run('ppo-cartpole',project='native-control',target=box,interval=1) as run:
        cap=run.stable_baselines(publish_every=64)
        env=cap.wrap_env(make_vec_env('CartPole-v1',n_envs=4,seed=31))
        try:
            model=PPO('MlpPolicy',env,n_steps=64,batch_size=64,n_epochs=2,seed=31,device='cpu')
            model.learn(2048,callback=[cap.callback(),ConsoleProgress()])
            model.save(root/'ppo-checkpoint');run.add_file(root/'ppo-checkpoint.zip')
            run.sample_hardware()
        finally:env.close()
    assert box.status()['pending']>0
    checks.append('Offline native capture retained in durable outbox')
    stream=(root/'server.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,*(['-I'] if sys.flags.isolated else []),'-u',__file__,'--serve',str(db)],
        stdin=subprocess.PIPE,stdout=stream,stderr=stream,env=dict(os.environ,PYTHONUTF8='1'),
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        deadline=time.monotonic()+30;endpoint=None
        while time.monotonic()<deadline and process.poll() is None:
            match=re.search(r'Rilldex: (http://127\.0\.0\.1:\d+)',(root/'server.log').read_text(encoding='utf-8'))
            if match:endpoint=match[1];break
            time.sleep(.05)
        assert endpoint,(root/'server.log').read_text(encoding='utf-8')
        # Reopen the queue in a fresh client, like a restarted process.
        box=Outbox(queue,producer='native-cpu-worker',endpoint=endpoint)
        def drain():
            result=box.drain(limit=10000)
            assert result['pending']==0 and result['blocked']==0,result
            return result
        drain()
        def fetch(path,**params):
            with urlopen(endpoint+path+'?'+urlencode(params)) as response:return json.loads(response.read())
        baseline=fetch('/api/trainer-telemetry/query',experiment='native-control/ppo-cartpole')
        assert baseline['records']==8,baseline['records']
        checks.append('Queued logs, metrics and episodes delivered through real HTTP')
        class LiveCheck(BaseCallback):
            def _on_step(self):
                if self.num_timesteps%512==0:
                    drain()
                    state=fetch('/api/trainer-telemetry/query',experiment='native-control/ppo-cartpole')
                    live.append({'training_step':self.num_timesteps,'native_logs_visible':state['records']})
                return True
        with Run('ppo-cartpole',project='native-control',target=box,interval=1) as run:
            cap=run.stable_baselines(publish_every=64)
            env=cap.wrap_env(make_vec_env('CartPole-v1',n_envs=4,seed=32))
            try:
                model=PPO.load(root/'ppo-checkpoint.zip',env=env,device='cpu')
                model.learn(2048,reset_num_timesteps=False,callback=[cap.callback(),ConsoleProgress(),LiveCheck()])
                assert model.num_timesteps==4096
            finally:env.close()
        drain()
        assert live[-1]['native_logs_visible']>live[0]['native_logs_visible'],live
        checks.append('Checkpoint resume retained both sessions and advancing live HTTP curves')
        with Run('dqn-cartpole',project='native-control',target=box,interval=1) as run:
            cap=run.stable_baselines(publish_every=64)
            env=cap.wrap_env(make_vec_env('CartPole-v1',n_envs=2,seed=19))
            try:
                model=DQN('MlpPolicy',env,buffer_size=4096,learning_starts=64,train_freq=4,
                    gradient_steps=1,batch_size=32,seed=19,device='cpu')
                model.learn(1024,callback=cap.callback())
                print('DQN completed environment transitions:',model.num_timesteps)
            finally:env.close()
        drain();assert box.drain(limit=10000)['sent_now']==0
        with store.connect() as c:
            rows=[(json.loads(r[0]),r[1]) for r in c.execute('''SELECT r.document,rr.state FROM runs r JOIN rollout_revisions rr ON rr.run_id=r.id
                WHERE rr.revision=(SELECT max(x.revision) FROM rollout_revisions x WHERE x.producer=rr.producer AND x.rollout_id=rr.rollout_id)''')]
        assert sum(len(r['raw']['steps']) for r,_ in rows)==5120
        assert all(r['outcome'].get('success') is None for r,_ in rows)
        assert sum(state=='in_progress' for _,state in rows)>0
        sessions={r['raw']['metadata']['capture_session'] for r,_ in rows};assert len(sessions)==3
        checks.append('All 5,120 transitions retained across completed and unfinished episodes; success not fabricated')
        curves=fetch('/api/trainer-telemetry/query',experiment='native-control/ppo-cartpole')
        assert curves['records']==16 and curves['clock']=='environment_timesteps'
        assert len({s['context']['session'] for s in curves['series']})==2
        audit={}
        for experiment in ('native-control/ppo-cartpole','native-control/dqn-cartpole'):
            records=Workspace(db,experiment=experiment).run_records(limit=200)
            assert all(records['counts'].get(k,0)>0 for k in ('manifest','lifecycle','console','hardware'))
            audit[experiment]=records['counts']
        files=run_records.records(store,experiment='native-control/ppo-cartpole',kind='file')['rows']
        assert run_records.file_content(store,experiment='native-control/ppo-cartpole',sequence=files[0]['sequence'])[1]==(root/'ppo-checkpoint.zip').read_bytes()
        # The source graph is computed from captured actions/results, without an LLM.
        run_id=next(r['id'] for r,state in rows if state=='complete')
        mapped=fetch('/api/monitoring/rollout/'+run_id,observer='source')
        assert mapped['graph']['nodes']
        checks.append('Python access, immutable checkpoint snapshot and HTTP source map verified')
        report=dict(passed=True,versions={p:importlib.metadata.version(p) for p in ('stable-baselines3','gymnasium','torch')},
            platform=sys.platform,device='cpu',environment='CartPole-v1',transitions=5120,episodes=len(rows),
            completed=sum(state=='complete' for _,state in rows),unfinished=sum(state=='in_progress' for _,state in rows),
            native_ppo_logs=curves['records'],live=live,run_records=audit,checks=checks,provider_calls=0,
            map_run=run_id,seconds=round(time.monotonic()-started,2),limitations=['No GPU or cluster execution','No exact optimizer/sample attribution','CartPole capture validation, not evidence of model quality'])
        (root/'native-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
    finally:
        if process.poll() is None:process.stdin.close();process.wait(timeout=15)
        stream.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--serve',type=Path)
    args=parser.parse_args()
    if args.serve:serve(args.serve)
    elif args.output:validate(args.output.resolve())
    else:parser.error('Supply --output or --serve')
