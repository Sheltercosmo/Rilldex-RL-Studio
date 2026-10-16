"""Opt-in capture of native TRL A*-PO; validated single-process CPU boundary.

No extra generation/reward/forward calls. Raw source capture, native prepared
inputs and confirmed backward/optimizer use remain different observations.
"""
from copy import deepcopy
from importlib.metadata import version
import uuid

from .schema import InputError
from .portable import generation_document
from .trl_lineage import OptimizerWindow
from . import trl_a2po_setup

VERSION = 'trl-a2po-capture/1'


class A2POCaptureMixin:
    def __init__(self, *args, training_outbox, experiment, reward_definition, **kwargs):
        pins = {'trl':'1.13.0','transformers':'5.19.0','accelerate':'1.15.0','torch':'2.14.1'}
        if any(version(name) != pin for name,pin in pins.items()):
            raise InputError('A*-PO capture requires the pinned TRL 1.13.0 / Transformers 5.19.0 / Accelerate 1.15.0 / Torch 2.14.1 runtime')
        if not all(isinstance(s,str) and s.strip() for s in (experiment,reward_definition)):
            raise InputError('Supply experiment and a versioned definition of the combined native reward')
        self.training_outbox = training_outbox
        self.capture_experiment = experiment
        self.reward_definition = reward_definition
        self._capture_session = uuid.uuid4().hex
        self._capture_phase = 'policy'
        self._capture_batch = None
        self._capture_prepared = None
        self._capture_predictions = None
        self._capture_in_loss = False
        self._capture_window = OptimizerWindow()
        self._capture_uses = 0
        self.capture_counts = {'generated':0,'reference_samples':0,'backward_uses':0,'optimizer_uses':0,'optimizer_steps':0}
        super().__init__(*args,**kwargs)
        if (self.accelerator.num_processes != 1 or self.accelerator.device.type != 'cpu'
                or self.args.optim.value != 'adamw_torch' or self.args.bf16 or self.args.fp16):
            raise InputError('A*-PO capture is validated only for single-process FP32 CPU and native AdamW')
        self._capture_setup()
        from transformers import TrainerCallback
        trainer = self
        class ReceiptCallback(TrainerCallback):
            def on_optimizer_step(self,args,state,control,**kwargs): trainer._capture_optimizer(state.global_step)
            def on_train_end(self,args,state,control,**kwargs): trainer._capture_window.clear()
        self.add_callback(ReceiptCallback())

    def _capture_setup(self):
        request = trl_a2po_setup.prepare(self.args,version='1.13.0',resolved=True)
        report = trl_a2po_setup.inspect(request)
        if report['status'] != 'ready': raise InputError('A*-PO capture settings need review')
        recipe = report['recipe']
        previous = getattr(self,'_capture_recipe',None)
        if previous and previous['id'] != recipe['id']:
            # Native V* is a cache from the reference stage; silently relabeling
            # it after changing beta1/reward weights would invent provenance.
            raise InputError('A*-PO settings changed within capture; start a new trainer and baseline cache')
        if previous: return
        self._capture_recipe = recipe
        self.training_outbox.log_recipes(self.capture_experiment,[recipe])
        self._capture_refs = {'policy':{'producer':self.training_outbox.producer,'id':recipe['id'],'revision':0}}

    def _capture_record(self,kind,identifier,sample,data,basis):
        return {'id':identifier,'revision':0,'kind':kind,
                'sample':{'producer':self.training_outbox.producer,'rollout_id':sample},
                'data':data,'evidence':{'basis':basis,'source_revision':0}}

    def _estimate_optimal_values(self):
        self._capture_phase = 'baseline'
        try:
            result = super()._estimate_optimal_values()
            self.capture_baseline = {'cache_entries':len(self._optimal_values),
                'retained_training_prompts':len(self.train_dataset),
                'key_basis':'Native rendered prompt text; duplicate prompt keys follow the native cache overwrite rule',
                'values':deepcopy(self._optimal_values)}
            return result
        finally:
            self._capture_phase = 'policy'
            self._capture_batch = None

    def _calculate_rewards(self,prompts,completions,**kwargs):
        result = super()._calculate_rewards(prompts,completions,**kwargs)
        if not all(isinstance(v,str) for v in [*prompts,*completions]):
            raise InputError('A*-PO capture currently supports plain-text prompts and completions')
        batch = self._capture_session+'/'+uuid.uuid4().hex
        split = 'train' if self.model.training else 'evaluation'
        refs = []; records = []; snapshots = []
        for i,(prompt,completion,reward) in enumerate(zip(prompts,completions,result.detach().cpu().tolist())):
            identifier = batch+'/'+str(i); refs.append(identifier)
            metadata = {'experiment':self.capture_experiment,'capture_protocol':VERSION,'trainer':'trl/A2POTrainer',
                'trainer_version':'1.13.0','capture_phase':self._capture_phase,
                'reward_definition':self.reward_definition,
                'training_inclusion':'reference_baseline_sample' if self._capture_phase=='baseline' else 'optimizer_use_unconfirmed'}
            data = {'split':split,'recipe':self._capture_refs['policy']}
            task_ids = kwargs.get('tracking_task_id')
            if isinstance(task_ids,list) and len(task_ids)==len(prompts) and isinstance(task_ids[i],str):
                metadata['task_id']=task_ids[i]; data['task_id']=task_ids[i]
            if self._capture_phase != 'baseline':
                metadata.update(split=split,training_step=self.state.global_step,training_step_basis='trainer_global_step_at_generation')
                data.update(step=self.state.global_step,step_basis='trainer_global_step_at_generation')
            document = generation_document(prompt,completion,metadata=metadata,reward=reward)
            document['capture_provenance'] = {'phase':self._capture_phase,'reward_scope':'Native combined reward returned by A2POTrainer._calculate_rewards'}
            snapshots.append({'rollout_id':identifier,'document':document,'state':'complete'})
            # The native baseline pass traverses both training and evaluation
            # datasets with no split argument at this hook. Keep these as raw
            # reference rollouts; do not invent a training-sample declaration.
            if self._capture_phase != 'baseline':
                records.extend([self._capture_record('sample',identifier+'/sample',identifier,data,'Native generated completion; no optimizer use inferred'),
                    self._capture_record('score',identifier+'/score',identifier,
                        {'component':'combined reward','definition':self.reward_definition,'status':'scored','value':reward},
                        'Native combined reward from policy generation')])
        self.training_outbox.log_many(snapshots)
        for start in range(0,len(records),1000): self.training_outbox.log_training(self.capture_experiment,records[start:start+1000])
        self.capture_counts['generated'] += len(refs)
        if self._capture_phase == 'baseline': self.capture_counts['reference_samples'] += len(refs)
        self._capture_batch = refs
        return result

    def _prepare_inputs(self,inputs):
        self._capture_batch = None
        prepared = super()._prepare_inputs(inputs)
        if self.model.training:
            self._capture_setup()
            if self._capture_batch is None or len(self._capture_batch) != len(prepared['rewards']):
                raise InputError('A*-PO prepared inputs have no exact generated-sample binding')
            self._capture_prepared = (list(self._capture_batch),prepared)
        return prepared

    def _get_sequence_logps(self,*args,**kwargs):
        result = super()._get_sequence_logps(*args,**kwargs)
        if self._capture_in_loss: self._capture_predictions = result.detach()
        return result

    def compute_loss(self,model,inputs,*args,**kwargs):
        self._capture_in_loss = bool(model.training)
        try: return super().compute_loss(model,inputs,*args,**kwargs)
        finally: self._capture_in_loss = False

    def training_step(self,*args,**kwargs):
        self._capture_prepared = None; self._capture_predictions = None
        before = self.state.global_step
        try:
            result = super().training_step(*args,**kwargs)
            if self._capture_prepared is None or self._capture_predictions is None:
                raise InputError('A*-PO backward has no bound prepared inputs or prediction')
            refs, prepared = self._capture_prepared
            # Reuse detached native tensors; do not run another model or reward.
            predictions = self.args.beta2*(self._capture_predictions-prepared['ref_logps'].detach())
            targets = prepared['rewards'].detach()-prepared['v_star'].detach()
            records = []
            for i,sample in enumerate(refs):
                tokens = int(prepared['attention_mask'][i,-prepared['logits_to_keep']:].sum().item())
                signal = {'schema':'sample-regression/1','component':'rl-policy',
                    'definition':'trl/1.13.0/a2po/sequence-logratio-vs-reward-minus-cache/'+self.reward_definition,
                    'prediction':float(predictions[i].item()),'target':float(targets[i].item()),
                    'baseline':float(prepared['v_star'][i].item()),'reward':float(prepared['rewards'][i].item())}
                data = {'batch_id':self._capture_session+'/update/'+str(before),'learner_step':before,
                    'stage':'backward_completed','recipe':self._capture_refs['policy'],
                    'model_tokens':tokens,'loss_tokens':tokens,'advantage':signal['target'],'regression':signal}
                records.append(self._capture_record('use',sample+'/backward/'+str(self._capture_uses),sample,data,
                    'Native training_step returned after backward; sequence prediction/target reconstructed from the exact detached native loss inputs'))
            self.training_outbox.log_training(self.capture_experiment,records)
            self._capture_window.add(before,records)
            self._capture_uses += 1; self.capture_counts['backward_uses'] += len(records)
            return result
        except BaseException:
            self._capture_window.clear()
            raise
        finally:
            self._capture_prepared = None; self._capture_predictions = None

    def _capture_optimizer(self,step):
        import torch
        from accelerate.optimizer import AcceleratedOptimizer
        if type(self.optimizer) is not AcceleratedOptimizer or type(self.optimizer.optimizer) is not torch.optim.AdamW:
            self._capture_window.clear()
            raise InputError('A*-PO optimizer confirmation requires native AcceleratedOptimizer/AdamW')
        skipped = self.accelerator.optimizer_step_was_skipped
        records = self._capture_window.finish(step,skipped=skipped,synchronized=self.accelerator.sync_gradients)
        confirmed = [{**r,'id':r['id']+'/optimizer','data':{**r['data'],'stage':'optimizer_step_completed'},
            'evidence':{'basis':'Native on_optimizer_step after non-skipped AdamW update; preserves exact backward-use observations','source_revision':0}} for r in records]
        if confirmed: self.training_outbox.log_training(self.capture_experiment,confirmed)
        self.capture_counts['optimizer_uses'] += len(confirmed)
        self.capture_counts['optimizer_steps'] += int(not skipped and self.accelerator.sync_gradients)

    def train(self,*args,**kwargs):
        self._capture_window.clear()
        try: return super().train(*args,**kwargs)
        finally: self._capture_window.clear()
