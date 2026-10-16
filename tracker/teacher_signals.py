"""Sampled teacher evidence at preparation, deliberately separate from use.

No full-distribution KL, correctness, or gradient attribution is inferred.
Arrays align to target-token positions, not model-input positions.
"""
import math
import json
from collections import defaultdict
from .schema import InputError, digest, dumps
from . import training_recipes

VERSION = 'sampled-teacher-signal/1'
MAX_TOKENS = 131072


def validate(value):
    training_recipes.fields(value, {'schema', 'provider', 'student_policy', 'tokenizer_id',
        'probability_basis', 'context', 'coefficient', 'discount', 'target_tokens',
        'mask', 'student_logprobs', 'teacher_logprobs', 'advantage_delta'})
    if value['schema'] != VERSION: raise InputError('Use sampled-teacher-signal/1')
    training_recipes.fields(value['provider'], {'producer', 'id', 'revision'})
    for k, v in value['provider'].items(): training_recipes.text(v, 'teacher ' + k)
    for k in ('student_policy', 'tokenizer_id'): training_recipes.text(value[k], k)
    for key, fields in [('probability_basis', {'student', 'teacher'}),
                        ('context', {'student_digest', 'teacher_digest', 'definition'})]:
        training_recipes.fields(value[key], fields)
        for k, v in value[key].items(): training_recipes.text(v, k)
    for k in ('coefficient', 'discount'):
        v = value[k]
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            raise InputError(k + ' must be finite and nonnegative')
    if value['discount'] > 1: raise InputError('Discount must be at most one')
    tokens = value['target_tokens']
    if not isinstance(tokens, list) or not 1 <= len(tokens) <= MAX_TOKENS or any(type(t) is not int or t < 0 for t in tokens):
        raise InputError('Supply 1–131072 nonnegative target token IDs')
    for k in ('mask', 'student_logprobs', 'teacher_logprobs', 'advantage_delta'):
        if not isinstance(value[k], list) or len(value[k]) != len(tokens):
            raise InputError(k + ' must align with target tokens')
    if any(type(m) is not int or m not in (0, 1) for m in value['mask']):
        raise InputError('Teacher signal mask must be binary integers')
    for k in ('student_logprobs', 'teacher_logprobs'):
        for p, mask in zip(value[k], value['mask']):
            if p is None and not mask: continue
            if type(p) not in (int, float) or not math.isfinite(p) or p > 0:
                raise InputError(k + ' requires finite nonpositive log probabilities on every selected token')
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value['advantage_delta']):
        raise InputError('Observed advantage deltas must be finite on every target position')
    dumps(value)
    return value


def ratio(a, b):
    return {'value': a / b if b else None, 'numerator': a, 'denominator': b}


def summarize(signals):
    selected = masked = positive = negative = zero = off_mask = 0
    differences = []
    for s in signals:
        for m, p, q, delta in zip(s['mask'], s['student_logprobs'], s['teacher_logprobs'], s['advantage_delta']):
            if m:
                selected += 1; differences.append(p - q)
                positive += delta > 0; negative += delta < 0; zero += delta == 0
            else:
                masked += 1; off_mask += delta != 0
    return {'observations': len(signals), 'selected_tokens': selected, 'masked_tokens': masked,
        'sampled_log_ratio': ratio(math.fsum(differences), selected),
        'selected_fraction': ratio(selected, selected + masked),
        'positive_delta': ratio(positive, selected), 'negative_delta': ratio(negative, selected),
        'zero_delta': ratio(zero, selected), 'off_mask_delta': ratio(off_mask, masked)}


def component_binding(context, component, provider):
    if not context['manifest']: return context['status']
    c = next((c for c in context['manifest']['components'] if c['id'] == component), None)
    if c is None: return 'component_missing'
    if c['supervision'] not in {'teacher', 'self_teacher'}: return 'component_not_teacher'
    if 'provider' not in c: return 'provider_not_declared'
    if c['provider'] != provider: return 'provider_conflict'
    return 'matched'


def project(samples, recipes, experiment, sample_ref):
    streams = defaultdict(list)
    for sample in samples:
        for record in sample['records']:
            if record['kind'] != 'supervision': continue
            d = record['data']; s = d['signal']
            key = {'producer': record['record_producer'], 'recipe': d['recipe'],
                   'component': d['component'], 'step_basis': d['step_basis'], 'boundary': d['boundary'],
                   'provider': s['provider'], 'tokenizer_id': s['tokenizer_id'],
                   'probability_basis': s['probability_basis'], 'context_definition': s['context']['definition'],
                   'coefficient': s['coefficient'], 'discount': s['discount']}
            streams[dumps(key)].append({'id': record['id'], 'sample': sample_ref(sample),
                'data': d, 'evidence': record['evidence']})
    views = []
    for key_json, records in sorted(streams.items()):
        key = json.loads(key_json)
        context = training_recipes.resolve(recipes, experiment, key['recipe'])
        points = []
        for step in sorted({r['data']['step'] for r in records}):
            rows = [r for r in records if r['data']['step'] == step]
            points.append({'step': step, **summarize([r['data']['signal'] for r in rows]), 'records': rows})
        observed = {dumps(r['sample']) for r in records}
        views.append({'id': 'teacher-' + digest(key), **key, 'recipe_context': context,
            'component_binding': component_binding(context, key['component'], key['provider']),
            **summarize([r['data']['signal'] for r in records]), 'points': points,
            'unique_samples': len(observed), 'samples_without_this_signal': len(samples) - len(observed)})
    return views
