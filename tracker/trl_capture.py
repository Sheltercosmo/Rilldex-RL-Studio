"""Public GRPO reward-hook capture, without importing TRL or Torch.

The callback observes a generated/scored batch, not optimizer consumption.
Each wrapped function is one explicitly named reward component. Use separate
producers for separate ranks/components, and provide actual sampler identity
through context when known. Never infer a policy version from TrainerState.
"""
from copy import deepcopy
from functools import wraps
import inspect
import math
import time
import uuid
import warnings

from .adapters import normalize
from .portable import chat_document,generation_document,json_value
from .schema import InputError

VERSION='trl-grpo-reward-capture/2'


class GRPOCapture:
    def __init__(self,outbox,*,experiment,reward_definition,trainer_version,context,on_error,
                 task_id_column='tracking_task_id',sample_id_column='tracking_sample_id',tools=None):
        if any(not isinstance(v,str) or not v.strip() for v in (experiment,reward_definition,trainer_version)):
            raise InputError('Supply experiment, versioned reward definition and installed trainer version')
        if not callable(context) or on_error not in {'raise','warn'}:
            raise InputError('Supply context callable and explicit on_error: raise or warn')
        self.outbox=outbox;self.experiment=experiment;self.reward_definition=reward_definition
        self.trainer_version=trainer_version;self.context=context;self.on_error=on_error
        self.task_id_column=task_id_column;self.sample_id_column=sample_id_column;self.tools=deepcopy(tools or [])
        self.last_queued_batch=None;self.retain_last_batch=False
        self.counts={'callback_batches':0,'callback_rollouts':0,'queued_rollouts':0,'failed_batches':0,'reward_failed_batches':0,'capture_seconds':0.0}

    def wrap_reward(self,reward_function):
        """Return the original reward object unchanged; no extra reward evaluation.

        Sync and async functions keep their original calling convention. Only
        explicitly selected dataset identity columns enter captured metadata.
        """
        if inspect.iscoroutinefunction(reward_function):
            @wraps(reward_function)
            async def wrapped(*args,**kwargs):
                prepared=self._before(args,kwargs)
                try:result=await reward_function(*args,**kwargs)
                except Exception as exc:self._reward_failed(prepared,exc);raise
                self._after(prepared,result)
                return result
        else:
            @wraps(reward_function)
            def wrapped(*args,**kwargs):
                prepared=self._before(args,kwargs)
                try:result=reward_function(*args,**kwargs)
                except Exception as exc:self._reward_failed(prepared,exc);raise
                self._after(prepared,result)
                return result
        wrapped._jev_capture=self
        return wrapped

    def _reward_failed(self,batch,exc):
        self.counts['reward_failed_batches']+=1
        if batch is None:return
        try:self._after(batch,[None]*len(batch['prompts']),reward_error={'type':type(exc).__name__,'message':str(exc)})
        except Exception as capture_error:
            # A queue failure must not replace the original reward exception.
            exc.add_note('RL tracker could not preserve this failed reward batch: '+str(capture_error))

    def _error(self,exc):
        self.counts['failed_batches']+=1
        if self.on_error=='raise':raise exc
        warnings.warn('RL tracker capture failed; reward function is unchanged, but this batch has no capture: '+str(exc),RuntimeWarning,stacklevel=3)

    def _before(self,args,kwargs):
        start=time.perf_counter()
        self.last_queued_batch=None
        self.counts['callback_batches']+=1
        try:
            if args:raise InputError('TRL reward callback must pass prompts/completions as named arguments')
            prompts=kwargs.get('prompts');completions=kwargs.get('completions');token_ids=kwargs.get('completion_ids')
            if not isinstance(prompts,list) or not prompts or not isinstance(completions,list) or len(prompts)!=len(completions):
                raise InputError('Expected equal nonempty prompts and completions lists')
            n=len(prompts);self.counts['callback_rollouts']+=n
            if n>1000:raise InputError('Reward capture supports up to 1,000 local completions per batch')
            step=getattr(kwargs.get('trainer_state'),'global_step',None)
            if type(step) is not int or step<0:raise InputError('Missing nonnegative TrainerState.global_step')
            context=deepcopy(self.context())
            if not isinstance(context,dict) or context.get('split') not in {'train','evaluation'}:
                raise InputError('Capture context must explicitly declare split: train or evaluation')
            reserved={'experiment','reward_definition','training_step','training_step_basis','generation_step','batch_id','sample_id','task_id','local_completion_index','training_inclusion'}
            if reserved.intersection(context):raise InputError('Capture context overrides reserved identity/clock fields: '+', '.join(sorted(reserved.intersection(context))))
            if not isinstance(token_ids,list) or len(token_ids)!=n or any(not isinstance(row,list) or any(type(t) is not int or t<0 for t in row) for row in token_ids):
                raise InputError('completion_ids must contain one native integer-token list per completion')
            identities={}
            for column,target in [(self.task_id_column,'task_id'),(self.sample_id_column,'sample_id')]:
                if column in kwargs:
                    values=kwargs[column]
                    if not isinstance(values,list) or len(values)!=n or any(type(v) not in (str,int) or str(v)=='' for v in values):
                        raise InputError('Identity column '+column+' must have one nonempty string/integer per completion')
                    identities[target]=deepcopy(values)
            return {'prompts':deepcopy(prompts),'completions':deepcopy(completions),'token_ids':deepcopy(token_ids),
                    'step':step,'context':context,'identities':identities,'batch_id':uuid.uuid4().hex}
        except Exception as exc:self._error(exc);return None
        finally:self.counts['capture_seconds']+=time.perf_counter()-start

    def _after(self,batch,rewards,*,reward_error=None):
        if batch is None:return
        start=time.perf_counter()
        try:
            if not isinstance(rewards,(list,tuple)) or len(rewards)!=len(batch['prompts']):raise InputError('Reward output must have one value per captured completion')
            scores=json_value(rewards)
            if any(r is not None and (type(r) not in (int,float) or not math.isfinite(r)) for r in scores):
                raise InputError('Reward output must contain finite numbers or None; missing is not zero')
            snapshots=[]
            for i,(prompt,completion,score) in enumerate(zip(batch['prompts'],batch['completions'],scores)):
                meta={**batch['context'],'experiment':self.experiment,'reward_definition':self.reward_definition,
                    'training_step':batch['step'],'training_step_basis':'trainer_global_step_at_reward_callback',
                    'training_inclusion':'reward_scored_optimizer_use_unconfirmed','batch_id':batch['batch_id'],'local_completion_index':i,
                    'sampling':'all completions received by this reward callback',
                    'capture_protocol':VERSION,'trainer':'trl','trainer_version':self.trainer_version}
                for key,values in batch['identities'].items():meta[key]=values[i]
                if isinstance(prompt,str) and isinstance(completion,str):doc=generation_document(prompt,completion,metadata=meta,reward=score)
                elif isinstance(prompt,list) and isinstance(completion,list):doc=chat_document(prompt+completion,metadata=meta,tools=self.tools,reward=score)
                else:raise InputError('Prompt/completion must both be strings or both be structured message lists')
                doc['capture_provenance']={'protocol':VERSION,'trainer_version':self.trainer_version,'hook':'reward_function',
                    'reward_scope':'one returned reward component; not an inferred weighted trainer total',
                    'prompt':prompt,'completion':completion,'completion_token_ids':batch['token_ids'][i]}
                if reward_error:
                    doc['capture_provenance']['reward_error']=reward_error
                    doc['metadata']['training_inclusion']='reward_failed_optimizer_use_unconfirmed'
                normalize(doc)  # Validate every row before a batch enters the durable queue.
                snapshots.append({'rollout_id':batch['batch_id']+'/'+str(i),'document':doc,'state':'failed' if reward_error else 'complete'})
            self.outbox.log_many(snapshots)
            if self.retain_last_batch:
                self.last_queued_batch={'batch':deepcopy(batch),'snapshots':snapshots,'scores':scores,'reward_error':reward_error}
            self.counts['queued_rollouts']+=len(snapshots)
        except Exception as exc:self._error(exc)
        finally:self.counts['capture_seconds']+=time.perf_counter()-start

    def status(self):return {**self.counts,'outbox':self.outbox.status()}
