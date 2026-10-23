"""SB3 callbacks and VecEnv capture without replacing its logger or stepping it."""
from copy import deepcopy
import math
import uuid

from tracker.portable import Episode
from tracker.schema import InputError, digest, dumps
from tracker.trainer_telemetry import TrainerTelemetry


def project(value):
    """Copy low-dimensional JSON/NumPy state; never serialize framework reprs."""
    if type(value).__module__.startswith('numpy'):
        return project(value.item() if value.ndim==0 else value.tolist())
    if isinstance(value,dict): return {str(k):project(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [project(v) for v in value]
    if value is None or type(value) in (str,bool,int): return value
    if type(value) is float and math.isfinite(value): return value
    raise InputError('SB3 state must be finite JSON/NumPy data; supply an observation or info projection for other objects')


class StableBaselinesCapture:
    def __init__(self,run,*,environment=None,publish_every=128,observation_projection=None,info_projection=None):
        try:
            import stable_baselines3
        except ImportError as error: raise ImportError('Install stable-baselines3 in the training environment') from error
        if run.closed: raise RuntimeError('Run is closed')
        if type(publish_every) is not int or publish_every<1: raise InputError('publish_every must be a positive step count')
        self.run=run;self.version=stable_baselines3.__version__;self.environment=environment
        self.publish_every=publish_every;self.project_observation=observation_projection or project
        self.project_info=info_projection or project
        self.wrappers=[];self.writers=[];self.telemetry=None;self.training_session=None
        self.identity=uuid.uuid4().hex[:12]
        self.revisions={};self.hashes={};self.learn_count=0
        run._capture_finalizers.append(self._finish)

    def _publish(self,identifier,episode,*,complete=False,reason=None):
        document=episode.snapshot(success=episode.document['steps'][-1].get('info',{}).get('is_success') if complete and episode.document['steps'] else None)
        meta=document['metadata'];meta.update(experiment=self.run.experiment,capture_session=self.run.session,
            training_step_basis='environment_transitions',observation_projection='custom' if self.project_observation is not project else 'JSON / NumPy state')
        if reason: meta['capture_end_reason']=reason
        fingerprint=digest([document,complete])
        if self.hashes.get(identifier)==fingerprint:return
        if hasattr(self.run.target,'log'):
            result=self.run.target.log(identifier,document,state='complete' if complete else 'in_progress',format='environment-episode')
        else:
            revision=self.revisions.get(identifier,-1)+1
            result=self.run.target.ingest(dict(producer=self.run.producer,rollout_id=identifier,revision=revision,
                document=document,state='complete' if complete else 'in_progress',format='environment-episode'))
            self.revisions[identifier]=revision
        if complete:
            self.revisions.pop(identifier,None);self.hashes.pop(identifier,None)
        else:self.hashes[identifier]=fingerprint
        return result

    def wrap_env(self,env):
        """Place around the VecEnv boundary whose observations/rewards you want."""
        from stable_baselines3.common.vec_env import VecEnv, VecEnvWrapper
        if not isinstance(env,VecEnv): raise InputError('Pass an SB3 VecEnv, for example make_vec_env(...).')
        owner=self
        class CaptureEnv(VecEnvWrapper):
            def __init__(self,venv):
                super().__init__(venv)
                self.episodes=[None]*self.num_envs;self.ids=[None]*self.num_envs;self.numbers=[0]*self.num_envs
                self.actions=None;self.transitions=0;self.clock_offset=0
                self.capture_identity=uuid.uuid4().hex[:12]
                try: specs=venv.get_attr('spec')
                except AttributeError:specs=[None]*self.num_envs
                self.environments=[owner.environment or getattr(s,'id',None) or 'SB3 vector environment' for s in specs]
            def _begin(self,index,observation,info):
                self.numbers[index]+=1
                identifier=f'sb3/{owner.run.session}/{self.capture_identity}/{index}/{self.numbers[index]}'
                self.ids[index]=identifier
                self.episodes[index]=Episode(episode_id=identifier,metadata={
                    'environment':self.environments[index],'vector_slot':index,'split':'train',
                    'framework':'stable-baselines3','framework_version':owner.version,
                    'episode_start_transition':self.clock_offset+self.transitions,
                    'capture_boundary':'values returned by wrapped VecEnv, before trainer reward bootstrapping'})
                obs=owner.project_observation(deepcopy(observation))
                if len(dumps(obs).encode())>65536:raise InputError('Observation exceeds 64 KiB; provide observation_projection for media or large state')
                self.episodes[index].reset(obs,owner.project_info(deepcopy(info)))
            def _observation(self,observations,index):
                if isinstance(observations,dict):return {k:self._observation(v,index) for k,v in observations.items()}
                if isinstance(observations,tuple):return tuple(self._observation(v,index) for v in observations)
                return observations[index]
            def reset(self):
                self.flush('explicit reset')
                for identifier in self.ids:
                    owner.revisions.pop(identifier,None);owner.hashes.pop(identifier,None)
                observations=self.venv.reset();self.reset_infos=self.venv.reset_infos
                self.actions=None
                for i in range(self.num_envs): self._begin(i,self._observation(observations,i),self.reset_infos[i])
                return observations
            def step_async(self,actions):
                if self.actions is not None:raise RuntimeError('step_wait must finish before another step_async')
                if any(e is None for e in self.episodes):raise RuntimeError('Reset the captured environment before stepping')
                self.actions=deepcopy(actions)
                self.venv.step_async(actions)
            def step_wait(self):
                if self.actions is None:raise RuntimeError('step_async must precede step_wait')
                observations,rewards,dones,infos=self.venv.step_wait()
                self.reset_infos=self.venv.reset_infos;self.transitions+=self.num_envs
                for i in range(self.num_envs):
                    info=infos[i];done=bool(dones[i]);truncated=bool(info.get('TimeLimit.truncated',False))
                    if done and 'terminal_observation' not in info:raise InputError('VecEnv omitted terminal_observation; the next reset observation cannot stand in for it')
                    if truncated and not done:raise InputError('VecEnv reported truncation without episode ending')
                    raw=info['terminal_observation'] if done else self._observation(observations,i)
                    observation=owner.project_observation(deepcopy(raw))
                    if len(dumps(observation).encode())>65536:raise InputError('Observation exceeds 64 KiB; provide observation_projection')
                    # Copy before the algorithm can bootstrap/mutate rewards or observations.
                    facts=owner.project_info(deepcopy({k:v for k,v in info.items() if k!='terminal_observation'}))
                    if facts.get('is_success') is not None and type(facts['is_success']) is not bool:
                        raise InputError('is_success must be an explicit boolean')
                    episode=self.episodes[i]
                    episode.gym_step(project(self.actions[i]),(observation,float(rewards[i]),done and not truncated,truncated,facts))
                    episode.document['steps'][-1]['capture_coordinate']={
                        'clock':'environment_timesteps','step':self.clock_offset+self.transitions,'trainer_session':owner.training_session}
                    episode.document['metadata'].update(training_step=self.clock_offset+self.transitions,
                        trainer_session=owner.training_session)
                    if done:
                        owner._publish(self.ids[i],episode,complete=True)
                        self._begin(i,self._observation(observations,i),self.reset_infos[i])
                    elif len(episode.document['steps'])%owner.publish_every==0:
                        owner._publish(self.ids[i],episode)
                self.actions=None
                return observations,rewards,dones,infos
            def flush(self,reason=None):
                for identifier,episode in zip(self.ids,self.episodes):
                    if episode is not None and episode.document['steps']:owner._publish(identifier,episode,reason=reason)
            def close(self):
                try:self.flush('environment closed')
                finally:self.venv.close()
        wrapper=CaptureEnv(env);self.wrappers.append(wrapper);return wrapper

    def callback(self):
        """Append a writer after SB3 initializes its logger; preserve other outputs."""
        from stable_baselines3.common.callbacks import BaseCallback
        from stable_baselines3.common.logger import KVWriter
        owner=self
        class Writer(KVWriter):
            def write(self,key_values,key_excluded,step=0):
                if owner.run.closed:raise RuntimeError('Capture Run closed before trainer logging finished')
                train={};evaluation={}
                for key,value in key_values.items():
                    if 'rilldex' in key_excluded.get(key,()):continue
                    if type(value).__module__.startswith('numpy') and getattr(value,'ndim',None)==0:value=value.item()
                    if type(value) not in (int,float) or isinstance(value,bool):continue
                    (evaluation if key.startswith('eval/') else train)[key]=value
                if train:owner.telemetry.log(train,step=int(step),split='train')
                if evaluation:owner.telemetry.log(evaluation,step=int(step),split='evaluation')
            def close(self):pass
        class CaptureCallback(BaseCallback):
            def _on_training_start(self):
                if owner.writers:raise RuntimeError('This capture already has an active training callback')
                owner.learn_count+=1;owner.training_session=owner.run.session+'/sb3/'+owner.identity+'/'+str(owner.learn_count)
                for wrapper in owner.wrappers:
                    wrapper.clock_offset=int(self.model.num_timesteps)-wrapper.transitions
                    for episode in wrapper.episodes:
                        if episode is not None and not episode.document['steps']:
                            episode.document['metadata']['episode_start_transition']=int(self.model.num_timesteps)
                environments={e for w in owner.wrappers for e in w.environments}
                environment=owner.environment or (next(iter(environments)) if len(environments)==1 else 'mixed / unspecified vector environments')
                objective=type(self.model).__name__.lower()
                owner.telemetry=TrainerTelemetry(owner.run.target,experiment=owner.run.experiment,producer=owner.run.producer,
                    framework='stable-baselines3',framework_version=owner.version,objective=objective,session=owner.training_session,
                    clock='environment_timesteps',environment=environment,population='native SB3 logger dump; reductions are metric-specific')
                config={key:project(getattr(self.model,key)) for key in ('gamma','n_steps','batch_size','n_epochs','learning_starts','buffer_size','gradient_steps','num_timesteps','n_envs','seed')
                        if hasattr(self.model,key) and type(getattr(self.model,key)) in (str,bool,int,float,type(None))}
                config.update(algorithm=type(self.model).__name__,framework='stable-baselines3',framework_version=owner.version,
                    trainer_session=owner.training_session,device=str(self.model.device),policy=type(self.model.policy).__name__,
                    stats_window_size=self.model._stats_window_size,clock='environment_timesteps')
                owner.run.log_config(config,trainer_session=owner.training_session)
                self.writer=Writer();self.native_logger=self.model.logger
                if any(isinstance(w,Writer) for w in self.native_logger.output_formats):raise RuntimeError('This capture is already attached')
                self.native_logger.output_formats.append(self.writer);owner.writers.append((self.native_logger,self.writer))
            def _on_step(self):return True
            def _on_training_end(self):
                owner._finish()
        return CaptureCallback()

    def flush(self):
        """Publish unfinished source episodes without detaching native logging."""
        for wrapper in self.wrappers:wrapper.flush()

    def _finish(self):
        try:
            for wrapper in self.wrappers:wrapper.flush('training capture ended')
        finally:
            for logger,writer in self.writers:
                if writer in logger.output_formats:logger.output_formats.remove(writer)
            self.writers.clear()
