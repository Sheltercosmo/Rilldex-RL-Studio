"""Opt-in adapter for a pinned Tinker OPD preparation boundary.

This consumes already-computed native values; it does not install hooks, call
teachers, reconstruct the loss, or assert that a backward pass happened.
"""
from .schema import InputError, digest
from . import teacher_signals, training_lineage

UPSTREAM_COMMIT = '70767c738ba5f523b66210a70e50b0dc14c9fc1a'


def _list(value):
    if hasattr(value, 'to_torch'): value = value.to_torch()
    if hasattr(value, 'detach'): value = value.detach().cpu()
    return value.tolist() if hasattr(value, 'tolist') else list(value)


def _text_tokens(model_input):
    tokens = []
    for chunk in model_input.chunks:
        if getattr(chunk, 'type', None) != 'encoded_text':
            raise InputError('This adapter supports text-only Tinker model inputs')
        tokens.extend(chunk.tokens)
    return tokens


def prepared_record(*, record_id, sample, datum, teacher_input, teacher_logprobs,
                    native_advantage_delta, provider, student_policy, tokenizer_id,
                    probability_basis, recipe, component, step, step_basis,
                    coefficient, discount, upstream_commit):
    if upstream_commit != UPSTREAM_COMMIT:
        raise InputError('Unvalidated Tinker cookbook revision; audit the boundary before capture')
    targets = _list(datum.loss_fn_inputs['target_tokens'])
    model_tokens = _text_tokens(datum.model_input)
    teacher_tokens = _text_tokens(teacher_input)
    # The pinned text recipe sends exactly model input plus its last target.
    # Other renderers/context transformations need their own audited mapping.
    if not targets or len(model_tokens) != len(targets) or model_tokens[1:] != targets[:-1] or teacher_tokens != model_tokens + targets[-1:]:
        raise InputError('Tinker text target/teacher context alignment does not match the pinned recipe')
    teacher_logprobs = _list(teacher_logprobs)
    if len(teacher_logprobs) != len(targets) + 1:
        raise InputError('Teacher log probabilities must include the leading context position')
    mask = _list(datum.loss_fn_inputs['mask'])
    if any(type(m) not in (int, float) or m not in (0, 1) for m in mask):
        raise InputError('Tinker mask must be binary')
    signal = {'schema': teacher_signals.VERSION, 'provider': provider,
        'student_policy': student_policy, 'tokenizer_id': tokenizer_id,
        'probability_basis': probability_basis,
        'context': {'student_digest': digest(teacher_tokens), 'teacher_digest': digest(teacher_tokens),
                    'definition': 'Pinned text OPD: identical model input plus last target; token-ID digest'},
        'coefficient': coefficient, 'discount': discount, 'target_tokens': targets,
        'mask': [int(m) for m in mask], 'student_logprobs': _list(datum.loss_fn_inputs['logprobs']),
        'teacher_logprobs': teacher_logprobs[1:], 'advantage_delta': _list(native_advantage_delta)}
    record = {'id': record_id, 'revision': 0, 'kind': 'supervision', 'sample': sample,
        'evidence': {'basis': 'Tinker OPD native values supplied at preparation; cookbook ' + upstream_commit},
        'data': {'recipe': recipe, 'component': component, 'step': step, 'step_basis': step_basis,
                 'stage': 'prepared', 'boundary': 'incorporate_kl_penalty: prepared kl_advantages', 'signal': signal}}
    training_lineage.validate({'schema': 'training-records/2', 'producer': 'validation',
                               'experiment': 'validation', 'records': [record]})
    return record
