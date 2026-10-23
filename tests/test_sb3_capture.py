"""Native CPU integration tests. Install stable-baselines3 to run (not mocks)."""
import copy
from functools import partial
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from rilldex import Run, Outbox
from tracker import trainer_telemetry, capture_bundle
from tracker.schema import InputError
from tracker.store import Store

AVAILABLE=importlib.util.find_spec('stable_baselines3') is not None


def latest(store):
    with store.connect() as c:
        return [(json.loads(r[0]),r[1]) for r in c.execute('''SELECT r.document,rr.state FROM runs r JOIN rollout_revisions rr ON rr.run_id=r.id
          WHERE rr.revision=(SELECT max(x.revision) FROM rollout_revisions x WHERE x.producer=rr.producer AND x.rollout_id=rr.rollout_id)''')]


def make_counter(slot=0):
    import gymnasium as gym
    import numpy as np
    class Counter(gym.Env):
        observation_space=gym.spaces.Box(-100000,100000,shape=(2,),dtype=np.float32)
        action_space=gym.spaces.Discrete(2)
        def reset(self,seed=None,options=None):
            super().reset(seed=seed);self.index=0
            return np.array([slot,0],dtype=np.float32),{'slot':slot}
        def step(self,action):
            self.index+=1
            end=self.index==(3 if slot==0 else 5)
            info={'slot':slot,'action_received':int(action)}
            if end:info['is_success']=slot==0
            return np.array([slot,self.index],dtype=np.float32),float(action+1),end and slot==0,end and slot==1,info
    return Counter()


@unittest.skipUnless(AVAILABLE,'requires native stable-baselines3')
class SB3CaptureTests(unittest.TestCase):
    def setUp(self):
        import torch
        torch.set_num_threads(1)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.store=Store(self.root/'workspace.sqlite')

    def recorder(self,name='native',target=None):
        return Run(name,workspace=self.store.path,target=target,capture_console=False,hardware=False)

    def test_vector_autoresets_are_separate_and_returns_unchanged(self):
        import numpy as np
        from stable_baselines3.common.vec_env import DummyVecEnv
        with self.recorder() as run:
            capture=run.stable_baselines(publish_every=2,environment='counter')
            env=capture.wrap_env(DummyVecEnv([lambda:make_counter(0),lambda:make_counter(1)]))
            baseline=DummyVecEnv([lambda:make_counter(0),lambda:make_counter(1)])
            self.addCleanup(env.close);self.addCleanup(baseline.close)
            np.testing.assert_equal(env.reset(),baseline.reset())
            for _ in range(7):
                observed=env.step(np.array([0,1]));expected=baseline.step(np.array([0,1]))
                for a,b in zip(observed[:3],expected[:3]):np.testing.assert_equal(a,b)
                self.assertEqual([i.keys() for i in observed[3]],[i.keys() for i in expected[3]])
                for a,b in zip(observed[3],expected[3]):
                    if 'terminal_observation' in a:np.testing.assert_equal(a['terminal_observation'],b['terminal_observation'])
            capture.flush()
            self.assertLessEqual(len(capture.hashes),2)
            self.assertLessEqual(len(capture.revisions),2)
        rows=latest(self.store);complete=[r for r,state in rows if state=='complete'];pending=[r for r,state in rows if state=='in_progress']
        self.assertEqual(len(complete),3);self.assertEqual(len(pending),2)
        self.assertEqual(sum(len(r['raw']['steps']) for r,_ in rows),14)
        for r in complete:
            raw=r['raw'];slot=raw['metadata']['vector_slot'];last=raw['steps'][-1]
            self.assertEqual(last['observation'],[slot,3 if slot==0 else 5])
            self.assertEqual(last['truncated'],slot==1);self.assertEqual(last['terminated'],slot==0)
            self.assertEqual(raw['outcome']['success'],slot==0);self.assertIsNone(raw['outcome']['reward'])
        for r in pending:self.assertIsNone(r['raw']['outcome']['success'])

    def test_native_ppo_and_dqn_parameters_and_logged_values_are_unchanged(self):
        import numpy as np
        import torch
        from stable_baselines3 import PPO,DQN
        from stable_baselines3.common.env_util import make_vec_env
        from stable_baselines3.common.logger import Logger,KVWriter
        class Memory(KVWriter):
            def __init__(self):self.rows=[]
            def write(self,values,excluded,step=0):self.rows.append((step,copy.deepcopy(values)))
            def close(self):pass
        for algorithm in (PPO,DQN):
            with self.subTest(algorithm=algorithm.__name__):
                results=[]
                for captured in (False,True):
                    with self.recorder(algorithm.__name__) as run:
                        env=make_vec_env('CartPole-v1',n_envs=2,seed=21)
                        capture=run.stable_baselines(publish_every=16)
                        if captured:env=capture.wrap_env(env)
                        kwargs=dict(n_steps=32,batch_size=16,n_epochs=2) if algorithm is PPO else dict(buffer_size=1024,learning_starts=32,train_freq=4,gradient_steps=1,batch_size=16)
                        model=algorithm('MlpPolicy',env,seed=21,device='cpu',policy_kwargs={'net_arch':[16,16]},**kwargs)
                        memory=Memory();logger=Logger(None,[memory]);model.set_logger(logger)
                        model.learn(256,callback=capture.callback() if captured else None)
                        self.assertIs(model.logger,logger);self.assertEqual(logger.output_formats,[memory])
                        results.append((copy.deepcopy(model.policy.state_dict()),memory.rows))
                        env.close()
                for key,value in results[0][0].items():self.assertTrue(torch.equal(value,results[1][0][key]),key)
                self.assertEqual([s for s,_ in results[0][1]],[s for s,_ in results[1][1]])
                for (_,a),(_,b) in zip(results[0][1],results[1][1]):
                    for key in a:
                        if not key.startswith('time/'):np.testing.assert_equal(a[key],b[key],err_msg=key)
                series=trainer_telemetry.snapshot(self.store,experiment='default/'+algorithm.__name__)['series']
                self.assertTrue(series)
                self.assertTrue(all(s['context']['clock']=='environment_timesteps' for s in series))
                if algorithm is PPO:
                    mapped={s['native_key']:s for s in series}
                    self.assertEqual(mapped['train/entropy_loss']['label'],'Negative policy entropy')
                    self.assertEqual(mapped['train/clip_fraction']['group'],'clipping')
                self.assertTrue(latest(self.store))

    def test_resume_counters_use_distinct_sessions_and_native_logger_is_preserved(self):
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_util import make_vec_env
        with self.recorder() as run:
            cap=run.stable_baselines();env=cap.wrap_env(make_vec_env('CartPole-v1',seed=4))
            model=PPO('MlpPolicy',env,n_steps=16,batch_size=8,n_epochs=1,seed=4,device='cpu')
            callback=cap.callback()
            model.learn(32,callback=callback)
            model.learn(32,reset_num_timesteps=False,callback=callback)
            model.learn(32,reset_num_timesteps=True,callback=callback)
            env.close()
        with self.store.connect() as c:
            sessions=[tuple(r) for r in c.execute('SELECT session,min(step),max(step) FROM trainer_telemetry GROUP BY session ORDER BY session')]
        self.assertEqual(len(sessions),3);self.assertEqual([s[1:] for s in sessions],[(16,32),(48,64),(16,32)])
        from tracker.run_records import trainer_context,records
        snapshots=records(self.store,experiment=run.experiment,kind='manifest')['rows']
        for session,_,_ in sessions:
            captures=trainer_context(self.store,experiment=run.experiment,producer=run.producer,session=session)['capture_sessions']
            self.assertEqual([r['session'] for r in captures],[run.session])
            linked=[r for r in snapshots if session in r['record']['payload'].get('trainer_sessions',[])]
            self.assertEqual(len(linked),1)
            self.assertEqual(linked[0]['record']['payload']['config']['trainer_session'],session)

    def test_outbox_bundle_carries_native_metrics_and_source_episodes(self):
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import DummyVecEnv
        path=self.root/'worker.sqlite';box=Outbox(path,producer='worker')
        with self.recorder(target=box) as run:
            cap=run.stable_baselines(publish_every=2,environment='counter');env=cap.wrap_env(DummyVecEnv([make_counter]))
            PPO('MlpPolicy',env,n_steps=8,batch_size=4,n_epochs=1,device='cpu',seed=3).learn(32,callback=cap.callback())
            env.close()
        bundle=self.root/'bundle.zip';capture_bundle.export(path,bundle)
        result=capture_bundle.receive(self.store,bundle);self.assertTrue(result['complete'],result)
        self.assertTrue(trainer_telemetry.snapshot(self.store)['series']);self.assertTrue(latest(self.store))
        again=capture_bundle.receive(self.store,bundle);self.assertEqual(again['accepted'],0)
        from tracker.run_records import trainer_context
        self.assertEqual(trainer_context(self.store,experiment=run.experiment,producer='worker',session=cap.training_session)['capture_sessions'][0]['session'],run.session)

    def test_missing_terminal_observation_is_not_replaced_with_reset_observation(self):
        from stable_baselines3.common.vec_env import DummyVecEnv
        import numpy as np
        class Broken(DummyVecEnv):
            def step_wait(self):
                result=super().step_wait()
                for info in result[3]:info.pop('terminal_observation',None)
                return result
        with self.recorder() as run:
            cap=run.stable_baselines(publish_every=2);env=cap.wrap_env(Broken([make_counter]));env.reset()
            env.step(np.array([0]));env.step(np.array([0]))
            with self.assertRaisesRegex(InputError,'terminal_observation'):env.step(np.array([0]))
            env.close()
        self.assertTrue(all(state=='in_progress' for _,state in latest(self.store)))

    def test_spawn_workers_preserve_asymmetric_episode_boundaries(self):
        import numpy as np
        from stable_baselines3.common.vec_env import SubprocVecEnv
        with self.recorder() as run:
            cap=run.stable_baselines(publish_every=3,environment='counter')
            env=cap.wrap_env(SubprocVecEnv([partial(make_counter,0),partial(make_counter,1)],start_method='spawn'))
            try:
                env.reset()
                for _ in range(11):env.step(np.array([0,1]))
            finally:env.close()
        rows=latest(self.store)
        self.assertEqual(sum(len(r['raw']['steps']) for r,_ in rows),22)
        self.assertEqual(sum(state=='complete' for _,state in rows),5)
        self.assertEqual(sum(state=='in_progress' for _,state in rows),2)
        for r,state in rows:
            raw=r['raw'];slot=raw['metadata']['vector_slot']
            self.assertTrue(all(s['observation'][0]==slot for s in raw['steps']))
            if state=='complete':self.assertEqual(raw['steps'][-1]['observation'][1],3 if slot==0 else 5)

    def test_normalized_boundary_and_projection_do_not_mutate_training_values(self):
        import numpy as np
        from stable_baselines3.common.vec_env import DummyVecEnv,VecNormalize
        def projection(obs):
            values=obs.tolist();obs[:]=-999  # The hook must receive a copy.
            return {'state':values}
        with self.recorder() as run:
            cap=run.stable_baselines(observation_projection=projection,publish_every=2)
            env=cap.wrap_env(VecNormalize(DummyVecEnv([partial(make_counter,1)])))
            baseline=VecNormalize(DummyVecEnv([partial(make_counter,1)]))
            try:
                np.testing.assert_equal(env.reset(),baseline.reset());rewards=[];terminal=None
                for _ in range(5):
                    actual=env.step(np.array([1]));expected=baseline.step(np.array([1]))
                    for a,b in zip(actual[:3],expected[:3]):np.testing.assert_equal(a,b)
                    rewards.append(float(expected[1][0]))
                    if expected[2][0]:terminal=expected[3][0]['terminal_observation'].tolist()
            finally:env.close();baseline.close()
        raw=next(r['raw'] for r,state in latest(self.store) if state=='complete')
        self.assertEqual([s['reward'] for s in raw['steps']],rewards)
        self.assertEqual(raw['steps'][-1]['observation'],{'state':terminal})
        self.assertTrue(raw['steps'][-1]['truncated'])

    def test_metrics_only_keeps_evaluation_split_and_respects_writer_exclusions(self):
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback,EvalCallback
        from stable_baselines3.common.vec_env import DummyVecEnv
        from stable_baselines3.common.monitor import Monitor
        class Extra(BaseCallback):
            def _on_step(self):
                cap.flush()  # Explicit flush must not detach the metrics writer.
                self.logger.record('custom/visible',2.0)
                self.logger.record('custom/excluded',3.0,exclude='rilldex')
                return True
        with self.recorder() as run:
            cap=run.stable_baselines(environment='counter')
            env=DummyVecEnv([lambda:Monitor(make_counter())]);evaluation=DummyVecEnv([lambda:Monitor(make_counter())])
            try:
                model=PPO('MlpPolicy',env,n_steps=16,batch_size=8,n_epochs=1,seed=5,device='cpu')
                model.learn(32,callback=[cap.callback(),Extra(),EvalCallback(evaluation,eval_freq=16,n_eval_episodes=2,verbose=0)])
            finally:env.close();evaluation.close()
        series=trainer_telemetry.snapshot(self.store)['series'];keys={s['native_key'] for s in series}
        self.assertIn('eval/mean_reward',keys);self.assertIn('custom/visible',keys);self.assertNotIn('custom/excluded',keys)
        self.assertTrue(all(s['context']['split']=='evaluation' for s in series if s['native_key'].startswith('eval/')))
        self.assertFalse(latest(self.store))  # No fabricated rollout evidence from scalar logs.


if __name__=='__main__':unittest.main()
