"""Controlled option-identifier variants for choice-harness evaluation.

Only identifiers change. Rubrics, model, state, questions and rendered option
order remain fixed. Decoding is a bijection, never a confidence adjustment.
"""
from copy import deepcopy
from .schema import InputError, digest
from .jev import validate_answers

VERSION='choice-identifiers/1'


def opaque(request):
    if not isinstance(request,dict) or not isinstance(request.get('questions'),dict):raise InputError('Choice request required')
    changed=deepcopy(request);mapping={}
    for q,spec in request['questions'].items():
        if spec.get('type')!='choice' or not isinstance(spec.get('criteria'),dict) or not spec['criteria']:
            raise InputError('Identifier variant accepts only nonempty choice questions')
        # The wire serializer sorts keys; fixed-width codes retain that order.
        mapping[q]={f'o{i:03d}':key for i,key in enumerate(sorted(spec['criteria']))}
        changed['questions'][q]['criteria']={code:spec['criteria'][key] for code,key in mapping[q].items()}
    return dict(schema=VERSION,original_hash=digest(request),variant=changed,mapping=mapping)


def decode(request,receipt,response):
    if receipt!=opaque(request):raise InputError('Choice variant mapping differs from its request')
    if response.get('model')!=request.get('model'):raise InputError('Choice variant response model differs')
    validate_answers(response,receipt['variant'])
    result=deepcopy(response)
    for q,mapping in receipt['mapping'].items():
        row=result['answers'][q]
        row['probabilities']={mapping[key]:value for key,value in row['probabilities'].items()}
        if row.get('choice') in mapping:row['choice']=mapping[row['choice']]
    validate_answers(result,request)
    return result
