"""Token evidence at one declared producer boundary, not optimizer attribution."""
import math
from .schema import InputError, digest

VERSION='training-token-context/1'
MAX_TOKENS=131072
GENERATION_VERSION='generation-token-context/1'


def _integers(values, name, *, minimum=0, maximum=None):
    if not isinstance(values,list) or len(values)>MAX_TOKENS or any(type(x) is not int or x<minimum or maximum is not None and x>maximum for x in values):
        raise InputError(name+' must be a bounded integer array')


def validate_generation(value):
    required={'schema','tokenizer_id','boundary','input_ids','output_ids'}
    if not isinstance(value,dict) or not required<=value.keys() or value.keys()-required-{'policy_versions','logprobs'} or value['schema']!=GENERATION_VERSION:
        raise InputError('Generation context requires generation-token-context/1, tokenizer, boundary and native input/output IDs')
    for k in ('tokenizer_id','boundary'):
        if not isinstance(value[k],str) or not value[k].strip() or len(value[k])>500:raise InputError('Generation '+k+' must be bounded text')
    for k in ('input_ids','output_ids'):_integers(value[k],k)
    if len(value['input_ids'])+len(value['output_ids'])>MAX_TOKENS:raise InputError('Generation sequence exceeds token capture limit')
    n=len(value['output_ids'])
    if 'policy_versions' in value:
        _integers(value['policy_versions'],'policy_versions',minimum=-1)
        if len(value['policy_versions'])!=n:raise InputError('Generation policy versions must align with output tokens')
    if 'logprobs' in value:
        v=value['logprobs']
        if not isinstance(v,list) or len(v)!=n or any(type(p) not in (int,float) or not math.isfinite(p) for p in v):raise InputError('Generation log probabilities must be finite and output-aligned')
    return value


def generation_summary(value):
    validate_generation(value)
    return {'schema':'generation-token-context-summary/1','id':'generation-context-'+digest(value),
            'boundary':value['boundary'],'tokenizer_id':value['tokenizer_id'],
            'input_tokens':len(value['input_ids']),'output_tokens':len(value['output_ids'])}


def validate(value):
    if not isinstance(value,dict) or set(value)!={'schema','tokenizer_id','boundary','generation','training'} or value['schema']!=VERSION:
        raise InputError('Token context requires its schema, tokenizer identity, capture boundary, generation and training')
    for k in ('tokenizer_id','boundary'):
        if not isinstance(value[k],str) or not value[k].strip() or len(value[k])>500:
            raise InputError('Token context '+k+' must be a nonempty bounded string')
    g=value['generation'];t=value['training']
    if not isinstance(g,dict) or not {'input_ids','output_ids'}<=set(g) or set(g)-{'input_ids','output_ids','policy_versions','logprobs'}:
        raise InputError('Generation requires input_ids, output_ids and optional output policy_versions/logprobs')
    if not isinstance(t,dict) or not {'input_ids','loss_mask'}<=set(t) or set(t)-{'input_ids','loss_mask','policy_versions','logprobs'}:
        raise InputError('Training requires unpadded input_ids, loss_mask and optional policy_versions/logprobs')
    for k in ('input_ids','output_ids'):_integers(g[k],'generation.'+k)
    if len(g['input_ids'])+len(g['output_ids'])>MAX_TOKENS:raise InputError('Generation sequence exceeds token capture limit')
    _integers(t['input_ids'],'training.input_ids');_integers(t['loss_mask'],'training.loss_mask',maximum=1)
    if len(t['loss_mask'])!=len(t['input_ids']):raise InputError('Training loss mask length differs from input IDs')
    for name,part,n in [('generation',g,len(g['output_ids'])),('training',t,len(t['input_ids']))]:
        if 'policy_versions' in part:
            _integers(part['policy_versions'],name+'.policy_versions',minimum=-1)
            if len(part['policy_versions'])!=n:raise InputError('Policy version count differs from token count')
        if 'logprobs' in part:
            x=part['logprobs']
            if not isinstance(x,list) or len(x)!=n or any(type(p) not in (int,float) or not math.isfinite(p) for p in x):
                raise InputError('Log probabilities must be finite and token-aligned')
    return value


def summarize(value):
    validate(value);g=value['generation'];t=value['training']
    generated=g['input_ids']+g['output_ids'];exported=t['input_ids']
    common=min(len(generated),len(exported));different=[i for i in range(common) if generated[i]!=exported[i]]
    mismatch=len(different)+abs(len(generated)-len(exported))
    first=different[0] if different else common if len(generated)!=len(exported) else None
    versions=t.get('policy_versions');selected=[v for v,m in zip(versions or [],t['loss_mask']) if m]
    return {'id':'token-context-'+digest(value),'schema':'training-token-context-summary/1',
        'boundary':value['boundary'],'tokenizer_id':value['tokenizer_id'],
        'sequence_equal':not mismatch,'different_positions':mismatch,'first_difference':first,
        'generation_prompt_tokens':len(g['input_ids']),'generation_output_tokens':len(g['output_ids']),
        'training_tokens':len(exported),'loss_tokens':sum(t['loss_mask']),
        'loss_policy_versions':sorted({v for v in selected if v>=0}) if versions is not None else None,
        'loss_tokens_without_policy_version':sum(v<0 for v in selected) if versions is not None else None,
        'generation_policy_versions':sorted({v for v in g.get('policy_versions',[]) if v>=0}) if 'policy_versions' in g else None,
        'comparison':'Positional token-ID equality under the producer-declared common tokenizer. Differences are observations, not correctness judgments. Export masks do not establish actual training use.'}
