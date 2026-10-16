"""Optional AReaL interaction-export bridge. No AReaL/Torch imports or calls.

The caller supplies already-exported native objects and per-interaction tensor
rows. This records that boundary; later grouping, filtering and learner use
remain separate evidence. Native runtime conformance is not yet established.
"""
from copy import deepcopy
from .schema import InputError, digest
from . import training_lineage, training_samples, training_token_context

VERSION='areal-interaction-capture/1'
UPSTREAM_COMMIT='298412a40f5b84ae6b2042987e81777e6dd0f284'


def _list(value):
    if hasattr(value,'detach'):value=value.detach().cpu().tolist()
    return deepcopy(value)


def _row(value, key):
    value=_list(value)
    if not isinstance(value,list) or len(value)!=1 or not isinstance(value[0],list):
        raise InputError('AReaL '+key+' must have exactly one tensor row per interaction')
    return value[0]


def _token_context(interaction, row, tokenizer_id, boundary):
    response=getattr(interaction,'model_response',None)
    if response is None:raise InputError('Native token generation evidence is absent')
    if not isinstance(row,dict) or not {'input_ids','loss_mask','attention_mask','rewards'}<=set(row):
        raise InputError('Export row requires input IDs, loss and attention masks, and reward')
    ids=_row(row['input_ids'],'input_ids');mask=_row(row['loss_mask'],'loss_mask');attention=_row(row['attention_mask'],'attention_mask')
    if len(ids)!=len(mask) or len(ids)!=len(attention) or any(type(a) not in (bool,int) or a not in (0,1) for a in attention):
        raise InputError('Export tensor lengths or attention mask are invalid')
    count=sum(attention)
    if attention!=[1]*count+[0]*(len(attention)-count):raise InputError('Only right-padded export rows are supported; do not silently reorder tokens')
    if any(m!=0 for m in mask[count:]):raise InputError('Padding carries nonzero loss mask; preserve and inspect it before capture')
    generation={'input_ids':_list(response.input_tokens),'output_ids':_list(response.output_tokens)}
    for attr,key in [('output_versions','policy_versions'),('output_logprobs','logprobs')]:
        v=getattr(response,attr,None)
        if v is not None:generation[key]=_list(v)
    training={'input_ids':ids[:count],'loss_mask':mask[:count]}
    for field,key in [('versions','policy_versions'),('logprobs','logprobs')]:
        if field in row:
            values=_row(row[field],field)
            if len(values)!=len(ids):raise InputError('Export '+field+' is not aligned with input IDs')
            training[key]=values[:count]
    token_context={'schema':training_token_context.VERSION,'tokenizer_id':tokenizer_id,'boundary':boundary,
        'generation':generation,'training':training}
    training_token_context.validate(token_context)
    return token_context


def build_packet(interactions, tensor_rows, *, producer, experiment, episode_id,
                 tokenizer_id, boundary, export_style, sample_context, source=None, spans_by_interaction=None,
                 upstream_commit, capture_token_context=False):
    """Inspect supplied exports without invoking tensorization/reward propagation.

    Stable episode identity is mandatory even when no source has been delivered.
    `source` refers to the separately captured episode; no flattened transcript
    or policy clock is manufactured from model-call inputs.
    """
    for k,v in [('episode_id',episode_id),('upstream_commit',upstream_commit),('boundary',boundary)]:training_lineage.text(v,k)
    if type(capture_token_context) is not bool:raise InputError('capture_token_context must be an explicit boolean')
    if export_style not in {'individual','concat'}:raise InputError('Declare the actual AReaL export style: individual or concat')
    if upstream_commit!=UPSTREAM_COMMIT:raise InputError('Unvalidated AReaL revision; audit the capture boundary before changing the pin')
    if not isinstance(interactions,dict) or not isinstance(tensor_rows,dict) or not 1<=len(interactions)<=250 or set(interactions)!=set(tensor_rows):
        raise InputError('Supply one to 250 interactions and exactly matching per-interaction tensor rows')
    indices=[getattr(v,'rollout_index',None) for v in interactions.values()]
    if any(v is not None and (type(v) is not int or v<0) for v in indices) or len(set(indices))!=1:
        raise InputError('Capture one logical rollout at a time; mixed or ambiguous rollout_index membership is not one episode')
    references=[getattr(v,'rollout_reward',None) for v in interactions.values()]
    references=[v for v in references if v is not None]
    if any(type(v) not in (int,float) for v in references) or len(set(references))>1:
        raise InputError('Conflicting logical-rollout reward references')
    if not isinstance(sample_context,dict) or set(sample_context)-{'split','task_id','group_id','step','step_basis','environment','environment_version'} or 'split' not in sample_context:
        raise InputError('Supply explicit sample context; policy versions come from token evidence, not a guessed rollout label')
    spans_by_interaction={} if spans_by_interaction is None else spans_by_interaction
    if not isinstance(spans_by_interaction,dict) or set(spans_by_interaction)-set(interactions) or spans_by_interaction and source is None:
        raise InputError('Span mappings require known interaction IDs and a pinned source')
    records=[]
    for identifier,interaction in interactions.items():
        training_lineage.text(identifier,'interaction identity')
        if getattr(interaction,'interaction_id',None)!=identifier:raise InputError('Native interaction identity differs from its export key')
        row=tensor_rows[identifier]
        if not isinstance(row,dict) or 'rewards' not in row:raise InputError('Export row requires rewards')
        token_context=_token_context(interaction,row,tokenizer_id,boundary) if capture_token_context else None
        sample_id='areal/'+digest({'episode_id':episode_id,'interaction_id':identifier,'export_style':export_style})
        ref={'producer':producer,'id':sample_id}
        evidence={'basis':VERSION+'; AReaL '+upstream_commit+'; '+export_style+'; '+boundary+'; episode '+episode_id}
        data={**deepcopy(sample_context),'episode':{'producer':producer,'id':episode_id},'interaction_ids':[identifier]}
        if token_context is not None:data['token_context']=token_context
        if source is not None:
            data['source']=deepcopy(source)
            if identifier in spans_by_interaction:data['source']['spans']=deepcopy(spans_by_interaction[identifier])
        records.append({'id':'sample/'+sample_id,'revision':0,'kind':'sample','sample':ref,'evidence':evidence,'data':data})
        for key,component in [('rewards','export_reward'),('original_rewards','original_export_reward')]:
            if key not in row:continue
            reward=_list(row[key])
            if not isinstance(reward,list) or len(reward)!=1:raise InputError('Export reward must have exactly one value')
            records.append({'id':key+'/'+sample_id,'revision':0,'kind':'score','sample':ref,'evidence':evidence,
                'data':{'component':component,'definition':VERSION+'/'+key+'/'+upstream_commit,'status':'scored','value':reward[0]}})
        reference=getattr(interaction,'rollout_reward',None)
        if reference is not None:
            records.append({'id':'rollout-reference/'+sample_id,'revision':0,'kind':'score','sample':ref,'evidence':evidence,
                'data':{'component':'logical_rollout_reward_reference','definition':VERSION+'/rollout_reward/'+upstream_commit,
                    'status':'scored','value':reference}})
    return training_lineage.validate({'schema':training_samples.VERSION,'producer':producer,'experiment':experiment,'records':records})


def capture(outbox, interactions, tensor_rows, **context):
    packet=build_packet(interactions,tensor_rows,producer=outbox.producer,**context)
    return outbox.log_training(packet['experiment'],packet['records'],schema=packet['schema'])
