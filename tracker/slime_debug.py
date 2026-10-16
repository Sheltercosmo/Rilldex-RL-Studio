"""Read Slime's paired native debug dumps, without executing a trainer or pickle.

The train dump is a retained batch view, not an optimizer-use receipt. Native
positions take precedence over nullable sample indexes; array order is never a join.
"""
import json
import math
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .schema import InputError, digest, dumps, event
from . import training_lineage, training_samples, training_token_context

VERSION = 'slime-debug/1'
COMMIT = '05e3b017fed9e02de418c2fbac9d75602a534be5'
MAX_SAMPLES = 1000
MAX_BYTES = 100_000_000


def plain(value):
    """Convert already-loaded CPU tensor values; never resolve paths or classes."""
    if type(value).__module__ == 'torch' and type(value).__name__ == 'Tensor':
        return plain(value.detach().cpu().tolist())
    if value is None or type(value) in {str, bool, int}: return value
    if type(value) is float and math.isfinite(value): return value
    if type(value) in {list, tuple}: return [plain(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k:plain(v) for k,v in value.items()}
    raise InputError('Debug dumps must contain finite primitive values or plain Torch tensors; unsupported objects are not loaded or executed')


def read(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES: raise InputError('Debug dump exceeds the 100 MB import limit')
    if path.suffix.lower() == '.json':
        return plain(json.loads(path.read_text(encoding='utf-8-sig')))
    if path.suffix.lower() != '.pt': raise InputError('Supply a JSON export or native .pt debug dump')
    try: import torch
    except ImportError as e: raise InputError('Native .pt imports need Torch in this Python environment; JSON imports do not') from e
    try: return plain(torch.load(path, map_location='cpu', weights_only=True))
    except InputError: raise
    except Exception as e:
        raise InputError('Safe Torch loading failed. Export primitive JSON from the trusted producer; the importer never retries with weights_only=False') from e


def integer(value, name):
    if type(value) is not int or value < 0: raise InputError(name+' must be a nonnegative integer')
    return value


def vector(value, name, *, length=None, tokens=False, mask=False):
    if not isinstance(value,list) or len(value)>training_token_context.MAX_TOKENS:
        raise InputError(name+' must be a bounded array')
    if length is not None and len(value)!=length: raise InputError(name+' length does not match its native token boundary')
    for v in value:
        if tokens or mask:
            if type(v) is not int or v<0 or mask and v not in {0,1}: raise InputError('Invalid '+name)
        elif type(v) not in {int,float} or not math.isfinite(v): raise InputError('Invalid '+name)
    return value


def rollout_samples(doc):
    if not isinstance(doc,dict) or 'rollout_id' not in doc: raise InputError('Rollout dump requires rollout_id and samples')
    integer(doc['rollout_id'],'rollout_id')
    rows=doc.get('samples')
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_SAMPLES or any(not isinstance(r,dict) for r in rows):
        raise InputError('Supply 1–1000 rollout samples')
    for r in rows:
        tokens=vector(r.get('tokens'),'rollout tokens',tokens=True)
        n=integer(r.get('response_length'),'response_length')
        if n>len(tokens): raise InputError('Response exceeds recorded token sequence')
        if not isinstance(r.get('response'),str) or not isinstance(r.get('prompt'),(str,list)):
            raise InputError('Native prompt and response text are required; no guessed token decoding')
        for key in ('index','group_index','rollout_id'):
            if r.get(key) is not None:integer(r[key],key)
        if r.get('loss_mask') is not None:vector(r['loss_mask'],'rollout loss_mask',length=n,mask=True)
        if r.get('rollout_log_probs') is not None:vector(r['rollout_log_probs'],'rollout log probabilities',length=n)
    return rows


def pair(rollout, train):
    rows=rollout_samples(rollout)
    if train is None:return {},{'status':'rollout_only','matched':0,'unmatched_rollout':len(rows),'join_basis':{}}
    if not isinstance(train,dict) or train.get('format_version')!=2 or type(train.get('format_version')) is not int:
        raise InputError('Only Slime train debug format_version 2 is supported')
    if integer(train.get('rollout_id'),'train rollout_id')!=rollout['rollout_id']:
        raise InputError('Rollout and training dump batch identities differ')
    supplied=train.get('samples')
    if not isinstance(supplied,list) or len(supplied)>MAX_SAMPLES:raise InputError('Invalid training sample list')
    indexes={}
    for pos,r in enumerate(rows):
        if r.get('index') is not None:indexes.setdefault(r['index'],[]).append(pos)
    joined={};basis=Counter()
    for r in supplied:
        if not isinstance(r,dict):raise InputError('Invalid training sample')
        pos=r.get('rollout_position');idx=r.get('sample_index')
        if idx is not None:integer(idx,'sample_index')
        if pos is not None:
            integer(pos,'rollout_position')
            if pos>=len(rows):raise InputError('rollout_position is outside the paired dump')
            if idx is not None and rows[pos].get('index') is not None and idx!=rows[pos]['index']:
                raise InputError('Native rollout_position and sample_index disagree')
            why='rollout_position'
        else:
            matches=indexes.get(idx,[]) if idx is not None else []
            if len(matches)!=1:raise InputError('No unambiguous native sample join; DP-gather order is not identity')
            pos=matches[0];why='unique_sample_index'
        if pos in joined:raise InputError('Duplicate training row for one rollout position')
        integer(r.get('data_parallel_rank'),'data_parallel_rank')
        tokens=vector(r.get('tokens'),'train tokens',tokens=True)
        n=integer(r.get('response_lengths'),'train response length')
        if n>len(tokens):raise InputError('Training response exceeds recorded sequence')
        if r.get('total_lengths') is not None and integer(r['total_lengths'],'total_lengths')!=len(tokens):raise InputError('Training total length differs from tokens')
        vector(r.get('loss_masks'),'training loss mask',length=n,mask=True)
        for key in ('rollout_log_probs','log_probs','ref_log_probs','advantages','values','returns','kl','entropy'):
            if r.get(key) is not None:vector(r[key],key,length=n)
        joined[pos]=r;basis[why]+=1
    return joined,{'status':'paired','matched':len(joined),'unmatched_rollout':len(rows)-len(joined),'join_basis':dict(basis)}


def append_events(doc, events, warnings, meta):
    if doc.get('trajectory_format')!=VERSION:raise InputError('Use slime-debug/1')
    if doc.get('upstream_commit')!=COMMIT:raise InputError('Unvalidated Slime source revision')
    integer(doc.get('position'),'native sample position')
    sample=doc['sample'];rollout_samples({'rollout_id':doc['rollout_batch'],'samples':[sample]})
    prompt=sample['prompt'] if isinstance(sample['prompt'],str) else dumps(sample['prompt'])
    event(events,kind='context',actor='context',text=prompt,pointer='/sample/prompt')
    # A flattened agentic Sample can contain environment responses. No token
    # decoder or text-length heuristic can reconstruct their spans from this dump.
    event(events,kind='context',actor='context',text=sample['response'],pointer='/sample/response',
          agent_visibility='not_established',context_kind='native_flattened_response')
    meta.setdefault('environment','slime-debug');meta['source_schema']=VERSION
    warnings.append('Native debug sample: response ownership, internal turns and tool relationships are unestablished. Raw text and training tokens are retained, but no semantic agent units or optimizer uses are invented.')
    return {'termination':sample.get('status'),'native_reward':sample.get('reward')}


def prepare(rollout, train=None, *, producer, experiment, session, tokenizer_id, upstream_commit=COMMIT):
    for name,value in [('producer',producer),('experiment',experiment),('session',session),('tokenizer_id',tokenizer_id)]:
        training_lineage.text(value,name)
    if upstream_commit!=COMMIT:raise InputError('Unvalidated Slime revision; check the native dump contract before changing the pin')
    rollout=plain(rollout);train=plain(train)
    joined,join=pair(rollout,train);rows=rollout['samples'];batch=rollout['rollout_id']
    records=[];snapshots=[];comparisons=[]
    evidence={'basis':VERSION+'; native debug boundary; Slime '+COMMIT+'; batch '+str(batch)}
    for pos,sample in enumerate(rows):
        row=joined.get(pos)
        identity=digest({'session':session,'batch':batch,'position':pos})
        sid='slime/'+identity
        doc={'trajectory_format':VERSION,'upstream_commit':COMMIT,'rollout_batch':batch,'position':pos,
             'sample':sample,'training_sample':row,'tokenizer_id':tokenizer_id}
        # Content-addressed source IDs keep revision-zero references immutable
        # across outbox restarts and differing exports of the same native sample.
        source_id='slime-source/'+digest({'document':doc,'experiment':experiment,'session':session})
        snapshots.append({'rollout_id':source_id,'document':doc,'format':'slime-debug','state':'complete',
            'metadata':{'experiment':experiment,'sample_id':sid,'split':'train','training_step':batch,
                        'training_step_basis':'slime_rollout_batch','capture_session':session}})
        data={'split':'train','step':batch,'step_basis':'slime_rollout_batch','environment':'slime-debug',
              'environment_version':COMMIT,'display_name':f'Batch {batch} · position {pos}',
              'source':{'producer':producer,'rollout_id':source_id,'revision':0}}
        if sample.get('group_index') is not None:
            data['group_id']='slime-group/'+digest({'session':session,'batch':batch,'group':sample['group_index']})
        # Explicit logical rollout IDs can connect compact/subagent samples.
        # Missing IDs do not imply that different samples are different episodes.
        if sample.get('rollout_id') is not None:
            data['episode']={'producer':producer,'id':'slime-episode/'+digest({'session':session,'batch':batch,'rollout':sample['rollout_id']})}
        if row is not None:
            n=sample['response_length'];p=len(sample['tokens'])-n
            tn=row['response_lengths'];tp=len(row['tokens'])-tn
            generation={'input_ids':sample['tokens'][:p],'output_ids':sample['tokens'][p:]}
            if sample.get('rollout_log_probs') is not None:generation['logprobs']=sample['rollout_log_probs']
            # No prompt log probabilities, token policy versions or scalar
            # advantage are manufactured to fill absent native fields.
            context=training_token_context.validate({'schema':training_token_context.VERSION,'tokenizer_id':tokenizer_id,
                'boundary':'Slime retained train debug batch; not an optimizer-use receipt','generation':generation,
                'training':{'input_ids':row['tokens'],'loss_mask':[0]*tp+row['loss_masks']}})
            data['token_context']=context
            same_response=n==tn and generation['output_ids']==row['tokens'][tp:]
            left=sample.get('rollout_log_probs');right=row.get('rollout_log_probs')
            diff=[abs(a-b) for a,b in zip(left,right)] if same_response and left is not None and right is not None else None
            if diff is not None and any(not math.isfinite(d) for d in diff):
                raise InputError('Rollout log-probability difference overflows; inspect the native numerical values')
            comparisons.append({'position':pos,'sample_id':sid,'data_parallel_rank':row['data_parallel_rank'],
                'token_context':training_token_context.summarize(context),
                'retained_rollout_logprobs':{'status':'compared' if diff is not None else 'unavailable',
                    'compared_tokens':len(diff) if diff is not None else 0,'max_absolute_difference':max(diff,default=0) if diff is not None else None},
                'learning_signal_fields':[k for k in ('advantages','values','returns') if row.get(k) is not None]})
        ref={'producer':producer,'id':sid}
        records.append({'id':'sample/'+sid,'revision':0,'kind':'sample','sample':ref,'evidence':evidence,'data':data})
        reward=sample.get('reward')
        if type(reward) in {int,float}:
            records.append({'id':'reward/'+sid,'revision':0,'kind':'score','sample':ref,'evidence':evidence,
                'data':{'component':'native_rollout_reward','definition':VERSION+'/native-reward/'+COMMIT,'status':'scored','value':reward}})
    packets=[training_lineage.validate({'schema':training_samples.VERSION,'producer':producer,'experiment':experiment,'records':records[i:i+1000]}) for i in range(0,len(records),1000)]
    report={'schema':VERSION,'upstream_commit':COMMIT,'session':session,'experiment':experiment,'rollout_batch':batch,
        'rollout_hash':digest(rollout),'train_hash':digest(train) if train is not None else None,'join':join,'comparisons':comparisons,
        'training_use_receipts':0,'policy_clocks_inferred':0,
        'limits':'Unmatched rollout samples are not rejected samples. Train dump presence is not proof of optimizer application. Weight-version lists lack token intervals and do not establish policy age. Flat response text does not establish semantic agent activity.'}
    return {'report':report,'snapshots':snapshots,'packets':packets,'native_training_dump':train}


def enqueue(outbox, prepared):
    """Queue the validated sources and sample facts in one local transaction."""
    from .adapters import normalize
    values=[]
    for snapshot in prepared['snapshots']:
        normalize(snapshot['document'],snapshot['format'],snapshot['metadata'])
        values.append(outbox._payload(**snapshot))
    for packet in prepared['packets']:
        training_lineage.validate(packet)
        if packet['producer']!=outbox.producer:raise InputError('Prepared dump and outbox producer differ')
        values.append({'rollout_id':'@training/'+digest(packet),'training_records':packet})
    return outbox._enqueue(values)
