"""Read pinned native batch fields without manufacturing training-use receipts."""
from collections import Counter, defaultdict
import json
import math

from .schema import InputError, digest
from . import slime_debug, value_observations as vo

VERSION = 'retained-rl-signals/1'
FIELDS = ('advantages', 'values', 'returns')


def field_stats(xs):
    return {'count':len(xs), 'mean':vo.mean(xs), 'variance':vo.variance(xs),
            'zero':sum(x == 0 for x in xs), 'positive':sum(x > 0 for x in xs),
            'negative':sum(x < 0 for x in xs)}


def extract(document, *, details=False):
    """A source projection only. Identity binding to a ledger sample is separate."""
    raw=document.get('raw') or {}
    if not isinstance(raw,dict): return None
    if raw.get('trajectory_format') != slime_debug.VERSION: return None
    base={'schema':VERSION, 'source_run':document['id'], 'status':'unsupported_revision'}
    if raw.get('upstream_commit') != slime_debug.COMMIT: return base
    meta=document.get('metadata') or {};session=meta.get('capture_session')
    try:
        if not isinstance(session,str) or not session: raise InputError('Native session missing')
        tokenizer=raw.get('tokenizer_id')
        if not isinstance(tokenizer,str) or not tokenizer.strip(): raise InputError('Native tokenizer identity missing')
        batch=slime_debug.integer(raw.get('rollout_batch'),'rollout batch')
        pos=slime_debug.integer(raw.get('position'),'sample position')
        expected='slime/'+digest({'session':session,'batch':batch,'position':pos})
        if meta.get('sample_id') != expected: raise InputError('Source sample identity does not match the import contract')
        base.update(sample_id=expected, session=session, step=batch, native_position=pos, step_basis='slime_rollout_batch',
                    upstream_commit=slime_debug.COMMIT, tokenizer_id=raw.get('tokenizer_id'))
        row=raw.get('training_sample')
        if row is None: return {**base,'status':'no_training_row'}
        # Recheck retained source shape. An adapter name alone is not evidence.
        check=dict(row)
        if check.get('rollout_position') not in (None,pos): raise InputError('Native position changed')
        check['rollout_position']=0
        slime_debug.pair({'rollout_id':batch,'samples':[raw['sample']]},
                         {'format_version':2,'rollout_id':batch,'samples':[check]})
        n=row['response_lengths'];mask=row['loss_masks']
        stats={k:field_stats([x for x,m in zip(row[k],mask) if m]) for k in FIELDS if row.get(k) is not None}
        pair=vo.paired_moments([[(v,t) for v,t,m in zip(row['values'],row['returns'],mask) if m]]) if row.get('values') is not None and row.get('returns') is not None else None
        base.update(status='captured' if stats else 'no_signal_fields', recorded_positions=n,
            eligible_positions=sum(mask), fields=stats, value_return=pair,
            input_digest=digest({'tokens':row['tokens'],'response_length':n}),
            settings_status='not_recorded', model_version_status='not_recorded')
        if details:
            base.update(positions=list(range(n)),mask=mask,native_fields={k:row[k] for k in stats},
                native_position=pos,data_parallel_rank=row['data_parallel_rank'])
        return base
    except (InputError,KeyError,TypeError,ValueError):
        return {**base,'status':'invalid_native_evidence'}


def for_sample(document, sample_id, sample_data):
    signal=extract(document)
    if signal is None: return None
    if signal['status'] in {'invalid_native_evidence','unsupported_revision'}: return signal
    if signal.get('sample_id') != sample_id: return {**signal,'status':'sample_identity_mismatch','fields':{},'value_return':None}
    row=(document.get('raw') or {}).get('training_sample')
    training=(sample_data.get('token_context') or {}).get('training')
    if row is not None and training is not None:
        prompt=len(row['tokens'])-row['response_lengths']
        if training['input_ids'] != row['tokens'] or training['loss_mask'] != [0]*prompt+row['loss_masks']:
            return {**signal,'status':'sample_token_context_mismatch','fields':{},'value_return':None}
    return signal


def weighted(rows, key, counts):
    total=sum(counts)
    if not total or any(r[key] is None for r,n in zip(rows,counts) if n): return None
    try: result=math.fsum(r[key]*(n/total) for r,n in zip(rows,counts) if n)
    except (OverflowError,ValueError): return None
    return vo.finite(result)


def pooled_variance(rows, mean_key, var_key, counts):
    center=weighted(rows,mean_key,counts)
    if center is None or any(r[var_key] is None for r,n in zip(rows,counts) if n): return None
    augmented=[{**r,'pooled':r[var_key]+(r[mean_key]-center)*(r[mean_key]-center)} for r,n in zip(rows,counts) if n]
    return weighted(augmented,'pooled',[n for n in counts if n])


def summarize(signals):
    valid=[s for s in signals if s['status']=='captured']
    fields={}
    for field in FIELDS:
        rows=[s['fields'][field] for s in valid if field in s['fields']]
        counts=[r['count'] for r in rows]
        fields[field]={'samples':len(rows),'count':sum(counts),'mean':weighted(rows,'mean',counts),
            'variance':pooled_variance(rows,'mean','variance',counts),
            **{key:sum(r[key] for r in rows) for key in ('zero','positive','negative')}}
    pairs=[s['value_return'] for s in valid if s['value_return'] is not None]
    counts=[p['eligible_positions'] for p in pairs]
    tv=pooled_variance(pairs,'mean_return','return_variance',counts)
    ev=pooled_variance(pairs,'mean_error','error_variance',counts)
    vv=pooled_variance(pairs,'mean_value','value_variance',counts)
    within=weighted(pairs,'within_sample_value_variance',counts)
    return {'states':dict(Counter(s['status'] for s in signals)),
        'samples':len(signals), 'recorded_positions':sum(s['recorded_positions'] for s in valid),
        'eligible_positions':sum(s['eligible_positions'] for s in valid), 'fields':fields,
        'value_return':{'samples':len(pairs),'eligible_positions':sum(counts),
            'mean_squared_error':weighted(pairs,'mean_squared_error',counts),
            'mean_error':weighted(pairs,'mean_error',counts),
            'explained_variance':vo.finite(1-ev/tv) if tv and ev is not None else None,
            'within_sample_variation_fraction':vo.finite(within/vv) if vv and within is not None else None}}


def project(samples, sample_ref):
    groups=defaultdict(list)
    for s in samples:
        signal=s.get('retained_rl_signal')
        if signal and 'step' in signal:
            key=(signal.get('session'),signal.get('upstream_commit'),signal.get('tokenizer_id'))
            groups[key].append(s)
    series=[]
    for key,rows in sorted(groups.items()):
        points=[]
        for step in sorted({s['retained_rl_signal']['step'] for s in rows}):
            selected=sorted([s for s in rows if s['retained_rl_signal']['step']==step],
                            key=lambda s:s['retained_rl_signal'].get('native_position',0))
            points.append({'step':step,**summarize([s['retained_rl_signal'] for s in selected]),
                'records':[{**sample_ref(s),'display_name':s.get('display_name'),
                            'retained_rl_signal':s['retained_rl_signal']} for s in selected]})
        series.append({'id':'retained-'+digest(key),'session':key[0],'upstream_commit':key[1],
            'tokenizer_id':key[2],'step_basis':'slime_rollout_batch','points':points,
            **summarize([s['retained_rl_signal'] for s in rows])})
    return {'schema':VERSION,'series':series,
        'boundary':'Native retained batch fields, not per-sample backward or optimizer-use receipts. '
        'The dump does not record the effective estimator, target definition or value-model version. '
        'Curves describe exported values at rollout-batch coordinates; they do not establish learning quality, '
        'policy age, critic fitting or causal behavior credit. Missing fields remain unavailable.'}


def inspect_source(store, run):
    with store.connect() as c:
        row=c.execute('SELECT document FROM runs WHERE id=?',(run,)).fetchone()
    if row is None: raise InputError('Source rollout was not found')
    result=extract(json.loads(row[0]),details=True)
    if result is None: raise InputError('This source has no supported native batch signal')
    return result
