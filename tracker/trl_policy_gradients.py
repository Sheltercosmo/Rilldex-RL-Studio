"""Opt-in native autograd observation; no reconstructed loss or second backward.

The bound mixin intentionally supports one pinned CPU, text-only policy-surrogate
path first. Other objectives must not silently acquire this component label.
"""
from .schema import InputError, digest
from .policy_gradients import VERSION, MAX_TOKENS, validate


def check_runtime(trainer):
    from importlib.metadata import version
    from trl import GRPOTrainer
    for name, pin in [('torch','2.14.1'),('trl','1.13.0'),('transformers','5.19.0'),('accelerate','1.15.0')]:
        if version(name) != pin: raise InputError('Policy-gradient capture requires the validated CPU runtime')
    if (trainer.beta != 0 or trainer.entropy_coef != 0 or trainer.aux_loss_enabled
            or trainer.use_liger_kernel or trainer.args.fp16 or trainer.args.bf16
            or trainer.use_adaptive_entropy or trainer._entropy_bonus_enabled):
        raise InputError('Policy-gradient capture currently requires FP32, no KL/entropy/router auxiliary loss and no Liger kernel')
    if trainer.loss_type not in {'grpo','dr_grpo','dapo','bnpo','cispo','sapo','luspo','vespo'}:
        raise InputError('Policy-gradient objective is not validated')
    if (getattr(trainer._compute_loss, '__func__', None) is not GRPOTrainer._compute_loss
            or getattr(trainer.compute_loss, '__func__', None) is not GRPOTrainer.compute_loss):
        raise InputError('Policy-gradient component capture requires the native GRPO loss methods')


def attach(trainer, logps):
    """Observe the native tensor's arriving derivative. Never replace a gradient."""
    refs, prepared, recipe = trainer._jev_prepared
    if recipe is None: raise InputError('Policy gradient cannot bind without effective training settings')
    check_runtime(trainer)
    if any(k in prepared for k in ('tool_mask','pixel_values','pixel_values_videos','image_grid_thw')):
        raise InputError('Policy-gradient source alignment currently supports text-only completions')
    if not logps.requires_grad: raise InputError('Current policy log probabilities do not require gradients')
    if prepared['advantages'].ndim != 1: raise InputError('Current adapter requires native sample-scalar advantages')
    ids = prepared['completion_ids']; mask = prepared['completion_mask']
    if len(refs) != len(ids) or tuple(logps.shape) != tuple(ids.shape) or tuple(mask.shape) != tuple(ids.shape):
        raise InputError('Native policy gradient shape does not match the retained sample rows')
    if ids.numel() > MAX_TOKENS: raise InputError('Policy-gradient observation exceeds the 131072-token batch budget')
    if trainer._jev_gradient_hook is not None: raise InputError('More than one current-policy log-probability tensor in a backward step')
    # Detach small immutable context before backward; never retain its graph.
    tokenizer = trainer.processing_class
    tokenizer_id = 'tokenizer-' + digest(tokenizer.backend_tokenizer.to_str())
    metadata = []
    for i,ref in enumerate(refs):
        n = ref['model_tokens']
        if n < 1 or n > ids.shape[1]: raise InputError('Unpadded native completion length is invalid')
        target = ids[i,:n].tolist()
        if digest(target) != ref.get('completion_digest'):
            raise InputError('Native completion tokens differ from the captured source sample')
        context = {'microbatch_rows':len(refs), 'gradient_accumulation_steps':trainer.current_gradient_accumulation_steps,
                   'steps_per_generation':trainer.args.steps_per_generation,
                   'num_items_in_batch':float(prepared['num_items_in_batch'].item())}
        metadata.append({'schema':VERSION, 'component':'rl-policy',
            'definition':'trl/1.13.0/native-policy-surrogate-dloss-dlogp/1',
            'tokenizer_id':tokenizer_id, 'input_digest':digest({'prompt':prepared['prompt_ids'][i].tolist(),'completion':target}),
            'probability_basis':'Native TRL target log probability after temperature scaling',
            'normalization':'Derivative arriving during native backward; includes native loss reduction and backward scaling',
            'normalization_context':context,'target_tokens':target,'loss_mask':mask[i,:n].to(dtype=__import__('torch').int64).tolist(),
            **({'source_alignment':ref['source_alignment']} if 'source_alignment' in ref else {})})

    def observe(gradient):
        try:
            if trainer._jev_policy_gradients is not None: raise InputError('Duplicate backward observation')
            rows=[]
            for i,entry in enumerate(metadata):
                value={**entry,'d_loss_d_logp':gradient[i,:len(entry['target_tokens'])].detach().tolist()}
                validate(value);rows.append(value)
            trainer._jev_policy_gradients=rows
        except Exception as exc:
            trainer._jev_gradient_error=exc
        return None  # PyTorch leaves the original gradient untouched.
    trainer._jev_gradient_hook=logps.register_hook(observe)
