"""Versioned native trainer scalars, independent of rollout/sample identity.

One point is a trainer log at a declared clock. It is never duplicated across
rollouts, averaged across writers, or substituted for a behavioral measurement.
"""
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from numbers import Real, Integral

from .schema import InputError, digest, dumps

VERSION = 'trainer-telemetry/1'
LINKED_VERSION = 'trainer-telemetry/2'
MAPPING = 'native-trainer-metrics/2'
GROUPS = ('loss', 'entropy', 'kl', 'clipping', 'tokens', 'throughput')
EXTRA_GROUPS = ('gradients', 'mismatch', 'reward', 'systems')


def metric(label, group, unit, reduction, definition):
    return dict(label=label, group=group, unit=unit, reduction=reduction, definition=definition)


TRL = {
    'loss': metric('Training loss', 'loss', 'native loss', 'trainer log reduction', 'Logged objective loss; normalization and included terms follow the recorded objective and trainer configuration.'),
    'entropy': metric('Completion token entropy', 'entropy', 'nats', 'trainer token reduction', 'Entropy over generated completion-token predictions under the trainer mask and reduction.'),
    'kl': metric('Reference-policy KL', 'kl', 'nats', 'trainer token reduction', 'Logged policy-to-reference KL estimate; absent when the trainer does not compute it. Not update KL.'),
    'clip_ratio': metric('Policy clipping fraction', 'clipping', 'fraction', 'trainer reduction', 'Liger policy ratio clipping fraction under the configured objective and bounds.'),
    'clip_ratio/region_mean': metric('Policy clipping region', 'clipping', 'fraction', 'trainer reduction', 'Mean fraction in either policy clipping region; not completion truncation.'),
    'clip_ratio/low_mean': metric('Lower policy clipping', 'clipping', 'fraction', 'trainer reduction', 'Mean lower-bound policy clipping fraction under the active loss implementation.'),
    'clip_ratio/high_mean': metric('Upper policy clipping', 'clipping', 'fraction', 'trainer reduction', 'Mean upper-bound policy clipping fraction under the active loss implementation.'),
    'num_tokens': metric('Processed tokens · cumulative', 'tokens', 'tokens', 'cumulative counter', 'Trainer-reported cumulative processed input tokens. Not a per-rollout length or a rate.'),
    'completions/mean_length': metric('Completion length', 'tokens', 'tokens / completion', 'mean', 'Mean generated completion length, including completions without EOS.'),
    'completions/clipped_ratio': metric('Completion truncation', 'tokens', 'fraction', 'mean', 'Fraction of generated completions truncated before EOS. Not policy objective clipping.'),
    'train_tokens_per_second': metric('Training token throughput', 'throughput', 'tokens / second', 'trainer run rate', 'Trainer-reported token rate over its measured training interval; not generation-server throughput.'),
    'train_samples_per_second': metric('Training sample throughput', 'throughput', 'samples / second', 'trainer run rate', 'Trainer-reported sample rate over its measured training interval.'),
    'train_steps_per_second': metric('Training step throughput', 'throughput', 'steps / second', 'trainer run rate', 'Trainer-reported update rate over its measured training interval.'),
}
PPO = {
    'loss/policy_avg': metric('Policy loss', 'loss', 'native loss', 'trainer update mean', 'Native PPO policy objective averaged by the trainer.'),
    'loss/value_avg': metric('Value loss', 'loss', 'native loss', 'trainer update mean', 'Native value prediction loss averaged by the trainer; distinct from policy loss.'),
    'objective/entropy': metric('Rollout sequence entropy estimate', 'entropy', 'nats / sequence', 'mean sequence sum', 'TRL PPO negative sampled log-probabilities summed over sequence positions then averaged; not vocabulary token entropy.'),
    'policy/entropy_avg': metric('Policy token entropy', 'entropy', 'nats', 'trainer update mean', 'Logged PPO policy entropy averaged over optimization minibatches.'),
    'objective/kl': metric('Reference-policy sequence KL', 'kl', 'nats / sequence', 'mean sequence sum', 'Sampled current-to-reference log-probability differences summed per sequence and averaged.'),
    'policy/approxkl_avg': metric('Update approximate KL', 'kl', 'nats', 'trainer update mean', 'Approximate divergence between old and updated PPO policies; not reference-policy KL.'),
    'policy/clipfrac_avg': metric('Policy clipping fraction', 'clipping', 'fraction', 'trainer update mean', 'Native PPO policy clipping fraction averaged over optimization minibatches.'),
    'val/clipfrac_avg': metric('Value clipping fraction', 'clipping', 'fraction', 'trainer update mean', 'Native value-function clipping fraction, separate from policy clipping.'),
    'eps': metric('Episode throughput', 'throughput', 'episodes / second', 'trainer run rate', 'TRL PPO reported episodes per elapsed training second.'),
}
VERL = {
    'actor/pg_loss': metric('Policy loss', 'loss', 'native loss', 'configured actor reduction', 'Actor policy-gradient loss under the configured loss mode and reduction; not total loss.'),
    'critic/vf_loss': metric('Value loss', 'loss', 'native loss', 'configured critic reduction', 'Native critic value loss under its mask and reduction.'),
    'actor/entropy': metric('Actor entropy', 'entropy', 'nats', 'configured actor reduction', 'Logged actor entropy under the configured response mask and loss aggregation.'),
    'actor/kl_loss': metric('Reference KL loss', 'kl', 'native KL loss', 'configured actor reduction', 'Native reference KL loss before multiplying by kl_loss_coef; estimator and normalization follow the configured KL loss type.'),
    'actor/ppo_kl': metric('Update KL estimate', 'kl', 'nats', 'native objective reduction', 'Native PPO log-ratio KL estimate between the old and current policy. The estimator can be signed.'),
    'actor/pg_clipfrac': metric('Policy clipping fraction', 'clipping', 'fraction', 'native objective reduction', 'Native clipping statistic of the active objective. Some objectives (including SAPO) emit a placeholder zero when clipping is unused; zero alone does not establish healthy updates.'),
    'actor/pg_clipfrac_lower': metric('Lower policy clipping', 'clipping', 'fraction', 'native objective reduction', 'Lower/dual clipping statistic reported by the active objective; not assumed equivalent to TRL lower clipping.'),
    'perf/total_num_tokens': metric('Batch processed tokens', 'tokens', 'tokens', 'batch sum', 'Sum of global_token_num for the logged batch; not a lifetime counter.'),
    'response_length/mean': metric('Response length', 'tokens', 'tokens / response', 'batch mean', 'Native response-mask token length mean.'),
    'response_length/clip_ratio': metric('Response length at limit', 'tokens', 'fraction', 'batch fraction', 'Native fraction reaching the response length limit; not policy objective clipping.'),
    'perf/throughput': metric('Token throughput per GPU', 'throughput', 'tokens / second / GPU', 'batch rate', 'Global batch tokens divided by step seconds and GPU count.'),
    'perf/time_per_step': metric('Step duration', 'throughput', 'seconds / step', 'batch duration', 'Elapsed seconds for the logged step; lower is faster, not a token rate.'),
}
VERL['actor/entropy_loss'] = {**VERL['actor/entropy'], 'label':'Actor entropy loss component'}
VERL['kl_loss'] = dict(VERL['actor/kl_loss'])
TRL['grad_norm'] = metric('Gradient norm', 'gradients', 'native norm', 'trainer-reported norm', 'Gradient norm emitted by the trainer. Norm type, distributed reduction and clipping boundary follow the recorded trainer version; not a policy divergence measure.')
VERL['actor/grad_norm'] = metric('Actor gradient norm', 'gradients', 'native norm', 'actor-reported norm', 'Actor gradient norm as emitted by the native optimizer path; norm type, distributed reduction and clipping boundary depend on the recorded trainer implementation.')
VERL['critic/grad_norm'] = {**VERL['actor/grad_norm'], 'label':'Critic gradient norm', 'definition':'Critic gradient norm as emitted by the native optimizer path; separate from actor gradients.'}
# ms-swift's reductions are not interchangeable with TRL's token reductions.
# Source and replay evidence: research/public-trainer-2026-10-21/README.md.
SWIFT = {key: dict(TRL[key]) for key in (
    'loss', 'kl', 'grad_norm', 'num_tokens', 'completions/mean_length',
    'train_tokens_per_second', 'train_samples_per_second', 'train_steps_per_second')}
SWIFT.update({
    'reward': metric('Reward', 'reward', 'reward', 'mean group reward; log-interval mean', 'Mean weighted reward across generation groups, averaged over the logging interval. Reward weights and functions belong to the training configuration; not a solve rate. The recorded split identifies training or evaluation.'),
    'reward_std': metric('Reward standard deviation', 'reward', 'reward', 'configured group or batch standard deviation; log-interval mean', 'Mean within-group standard deviation for group/none reward scaling, or batch standard deviation for batch scaling. The scale_rewards setting is required to distinguish them.'),
    'frac_reward_zero_std': metric('Groups with no reward variation', 'reward', 'fraction', 'group fraction; log-interval mean', 'Fraction of generation groups whose reward standard deviation is close to zero under torch.isclose. Includes all-equal successful and all-equal unsuccessful groups; not a filtering or failure rate.'),
    'learning_rate': metric('Learning rate', 'other', 'learning rate', 'trainer logger value', 'Learning rate emitted by the trainer at the recorded update.'),
    'completions/clipped_ratio': metric('Completion truncation', 'tokens', 'fraction', 'completion fraction; log-interval mean', 'Fraction of generated completions marked truncated. Dynamic sampling uses the final occurrence of each request ID. Not policy clipping or discarded training tokens.'),
    'cispo_clip_ratio': metric('CISPO clipping fraction', 'clipping', 'fraction', 'masked trainer reduction; log-interval mean', 'Fraction above the configured CISPO upper importance-weight bound. The reduction follows the recorded sampling level and active completion mask.'),
})
for suffix, label in (('mean', 'Mean'), ('min', 'Minimum'), ('max', 'Maximum')):
    SWIFT['entropy/' + suffix] = metric(label + ' completion entropy', 'entropy', 'nats', 'per-completion token mean; ' + suffix + '; log-interval mean',
        label + ' of per-completion mean token entropies across gathered completions, then averaged over the logging interval. Min/max are not extrema over all individual tokens.')
for suffix, label in (('min', 'Minimum'), ('max', 'Maximum')):
    SWIFT['completions/' + suffix + '_length'] = metric(label + ' completion length', 'tokens', 'tokens / completion', 'completion ' + suffix + '; log-interval mean',
        label + ' gathered completion length per generation batch, averaged over the logging interval; not a run-wide extreme.')
for key, label in (('region_mean', 'Policy clipping region'), ('low_mean', 'Lower policy clipping'), ('high_mean', 'Upper policy clipping'), ('low_min', 'Minimum lower policy clipping'), ('high_max', 'Maximum upper policy clipping')):
    SWIFT['clip_ratio/' + key] = metric(label, 'clipping', 'fraction', 'masked trainer reduction; rank ' + key.split('_')[-1] + '; log-interval mean',
        'Advantage-sign-aware clipping under the configured policy bounds. Token-level sampling uses the completion mask; sequence-level sampling uses a sequence mean. Rank statistic is averaged over the logging interval. Not completion truncation.')
from .sb3_metrics import definitions as sb3_definitions
GRPO_REWARD = {'reward': metric('Reward','reward','reward','native generation mean; log-interval mean',
    'Native mean of summed reward-function scores weighted by reward_weights, averaged over the logging interval. Scorable population and missing-value handling follow the captured TRL version. Not advantage, task success or independent evaluation; the recorded split identifies training or evaluation.')}
PROFILES = {'trl-grpo': {**TRL,**GRPO_REWARD}, 'trl-ppo': {**TRL, **PPO}, 'ms-swift-grpo': SWIFT, 'verl': VERL, 'stable-baselines3': sb3_definitions(metric), 'custom': {}}
TRANSFORMERS_PROFILES = frozenset(('trl-grpo', 'trl-ppo', 'ms-swift-grpo'))


def _swift_reward_definition(key):
    if not key.startswith('rewards/') or '/' not in key[8:]:
        return None
    name, statistic = key[8:].rsplit('/', 1)
    if not name or statistic not in ('mean', 'std'):
        return None
    label = 'mean' if statistic == 'mean' else 'standard deviation'
    return metric(name + ' · ' + label, 'reward', 'component reward', 'per-function ' + label + '; log-interval mean',
        'Unweighted reward-function ' + label + ' over non-NaN completion rewards, averaged over the logging interval. Function scores may use different scales; not the weighted total reward or a solve rate.')


def initialize(c):
    from .telemetry_queries import initialize as initialize_queries
    initialize_queries(c)
    c.executescript('''CREATE TABLE IF NOT EXISTS trainer_telemetry (
      producer TEXT NOT NULL, experiment TEXT NOT NULL, record_id TEXT NOT NULL,
      session TEXT NOT NULL, step INTEGER NOT NULL, document TEXT NOT NULL,
      received_at TEXT NOT NULL, PRIMARY KEY(producer,experiment,record_id));
      CREATE INDEX IF NOT EXISTS telemetry_scope ON trainer_telemetry(experiment,producer,session,step);''')
    c.executescript('''CREATE TABLE IF NOT EXISTS trainer_telemetry_uses (
      experiment TEXT NOT NULL, producer TEXT NOT NULL, record_id TEXT NOT NULL,
      use_producer TEXT NOT NULL, use_id TEXT NOT NULL, use_revision INTEGER NOT NULL,
      PRIMARY KEY(experiment,producer,record_id,use_producer,use_id,use_revision));
      CREATE INDEX IF NOT EXISTS telemetry_use_lookup ON trainer_telemetry_uses(
        experiment,use_producer,use_id,use_revision);''')


def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise InputError(name + ' requires 1–1,000 characters')


def validate(packet):
    if not isinstance(packet, dict) or set(packet) != {'schema','producer','experiment','records'} or packet['schema'] not in {VERSION,LINKED_VERSION}:
        raise InputError('Use trainer-telemetry/1 or trainer-telemetry/2 with producer, experiment and records')
    for k in ('producer','experiment'): text(packet[k], k)
    if not isinstance(packet['records'], list) or not 1 <= len(packet['records']) <= 1000:
        raise InputError('Supply 1–1,000 telemetry records')
    seen = set()
    for r in packet['records']:
        required = {'id','session','step','clock','split','framework','framework_version','objective','population','environment','metrics','mapping'}
        if packet['schema']==LINKED_VERSION: required.add('training_uses')
        if not isinstance(r, dict) or set(r) != required: raise InputError('Invalid telemetry record fields')
        for k in required - {'step','metrics','training_uses'}: text(r[k], k)
        if 'training_uses' in r:
            link=r['training_uses']
            if not isinstance(link,dict) or set(link)!={'coverage','basis','records'} or not isinstance(link['coverage'],str) or link['coverage'] not in {'complete','partial'}:
                raise InputError('training_uses needs coverage (complete or partial), basis and records')
            text(link['basis'],'training-use link basis')
            if not isinstance(link['records'],list) or not 1<=len(link['records'])<=10000:
                raise InputError('Supply 1–10,000 exact training-use references')
            identities=set()
            for ref in link['records']:
                if not isinstance(ref,dict) or set(ref)!={'producer','id','revision'}:
                    raise InputError('A training-use reference needs producer, id and revision')
                text(ref['producer'],'use producer');text(ref['id'],'use record id')
                if type(ref['revision']) is not int or ref['revision']!=0:raise InputError('Training uses are immutable revision zero records')
                identity=(ref['producer'],ref['id'],ref['revision'])
                if identity in identities:raise InputError('Duplicate training-use reference')
                identities.add(identity)
        if type(r['step']) is not int or not 0 <= r['step'] < 2**63: raise InputError('step must be a nonnegative integer')
        if r['split'] not in {'train','evaluation'}: raise InputError('split must be train or evaluation')
        if r['id'] in seen: raise InputError('Duplicate telemetry identity')
        seen.add(r['id'])
        if not isinstance(r['metrics'], dict) or not 1 <= len(r['metrics']) <= 512: raise InputError('Supply 1–512 metrics')
        for key, m in r['metrics'].items():
            text(key, 'native key')
            if not isinstance(m, dict) or set(m) != {'label','group','unit','reduction','definition','value','status'}:
                raise InputError('Metric needs its definition, value and status')
            for k in ('label','group','unit','reduction','definition'): text(m[k], k)
            if m['group'] not in {*GROUPS,*EXTRA_GROUPS,'other'}: raise InputError('Invalid metric group')
            if m['status'] not in {'recorded','missing','nonfinite','invalid'}: raise InputError('Invalid metric status')
            v = m['value']
            if m['status'] == 'recorded':
                if type(v) not in (float,int) or not math.isfinite(v): raise InputError('Recorded value must be finite')
            elif v is not None: raise InputError('Unavailable values must be null')
    return packet


def packet(logs, *, producer, experiment, framework, framework_version, objective,
           step, session, clock='learner_update', split='train', population='trainer logged batch',
           environment='unspecified', definitions=None, record_id=None, training_uses=None):
    """Adapt a native logger dictionary without pooling or inventing scalars.

    Unknown numeric keys survive as native/unmapped values. Overrides require
    complete definitions; they form distinct series if their meaning changes.
    """
    if framework not in PROFILES: raise InputError('Use trl-grpo, trl-ppo, ms-swift-grpo, verl or custom with explicit definitions')
    if not isinstance(logs, dict): raise InputError('logs must be a dictionary')
    catalog = {**PROFILES[framework], **(definitions or {})}
    values = {}
    for key, raw in logs.items():
        # Native loggers frequently emit NumPy or scalar Torch values. Do not
        # flatten vectors or silently treat a Boolean flag as a measurement.
        if getattr(raw,'shape',None)==() and callable(getattr(raw,'item',None)):
            raw=raw.item()
        if isinstance(raw,Real) and not isinstance(raw,bool):
            raw=int(raw) if isinstance(raw,Integral) else float(raw)
        if key in {'step','epoch','global_step','_step','_timestamp','_runtime'}: continue
        native = key
        if framework in TRANSFORMERS_PROFILES:
            if split == 'evaluation' and key.startswith('eval_'): native = key[5:]
            elif split == 'train' and key.startswith('train/'): native = key[6:]
        definition = catalog.get(native)
        if definition is None and framework == 'ms-swift-grpo':
            definition = _swift_reward_definition(native)
        if definition is None and (type(raw) not in (float,int) or isinstance(raw,bool)): continue
        definition = definition or metric(key, 'other', 'native', 'unmapped', 'Unmapped native scalar. Supply an explicit definition to classify it.')
        if raw is None: value, status = None, 'missing'
        elif type(raw) not in (float,int): value, status = None, 'invalid'
        elif not math.isfinite(raw): value, status = None, 'nonfinite'
        else: value, status = raw, 'recorded'
        values[key] = {**definition, 'value': value, 'status': status}
    if not values: return None
    record = dict(session=session,step=step,clock=clock,split=split,framework=framework,
                  framework_version=framework_version,objective=objective,population=population,
                  environment=environment,metrics=values,mapping='ms-swift-grpo-metrics/1' if framework == 'ms-swift-grpo' else MAPPING)
    if training_uses is not None:
        # Own the supplied references; callers may reuse and mutate their batch.
        from copy import deepcopy
        record['training_uses']=deepcopy(training_uses)
    record['id'] = record_id or 'log-' + digest(record)
    return validate(dict(schema=LINKED_VERSION if training_uses is not None else VERSION,
                         producer=producer,experiment=experiment,records=[record]))


def receive(store, value):
    from .store import ReviewConflict
    validate(value)
    inserted = 0
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in value['records']:
            key = value['producer'], value['experiment'], r['id']
            prior = c.execute('SELECT document FROM trainer_telemetry WHERE producer=? AND experiment=? AND record_id=?', key).fetchone()
            if prior and json.loads(prior[0]) != r: raise ReviewConflict('Telemetry identity conflicts with retained evidence')
            inserted += c.execute('INSERT OR IGNORE INTO trainer_telemetry VALUES (?,?,?,?,?,?,?)',
                (*key,r['session'],r['step'],dumps(r),datetime.now(timezone.utc).isoformat())).rowcount
            for ref in r.get('training_uses',{}).get('records',[]):
                c.execute('INSERT OR IGNORE INTO trainer_telemetry_uses VALUES (?,?,?,?,?,?)',
                    (value['experiment'],value['producer'],r['id'],ref['producer'],ref['id'],ref['revision']))
    return dict(id='telemetry-packet-'+digest(value),revision=0,inserted=inserted)


def snapshot(store, *, experiment=None, environment=None, limit=1000):
    if type(limit) is not int or not 1 <= limit <= 20000: raise InputError('limit must be 1–20,000')
    with store.connect() as c:
        rows = c.execute('''SELECT * FROM trainer_telemetry WHERE (? IS NULL OR experiment=?)
          AND (? IS NULL OR json_extract(document,'$.environment')=?)
          ORDER BY received_at DESC,record_id DESC LIMIT ?''',
          (experiment or None,experiment or None,environment or None,environment or None,limit+1)).fetchall()
    truncated = len(rows) > limit
    streams = defaultdict(list)
    for row in rows[:limit]:
        r = json.loads(row['document'])
        context = {k:r[k] for k in ('session','clock','split','framework','framework_version','objective','population','environment','mapping')}
        context.update(producer=row['producer'],experiment=row['experiment'])
        streams[dumps(context)].append(r)
    series = []
    omitted_series = 0
    for context_key, records in sorted(streams.items()):
        by_step = defaultdict(list)
        for r in records: by_step[r['step']].append(r)
        definitions = {(key,dumps({k:v for k,v in m.items() if k not in ('value','status')}))
                       for r in records for key,m in r['metrics'].items()}
        for key, definition in sorted(definitions):
            if len(series) >= 64:
                omitted_series += 1
                continue
            spec = json.loads(definition)
            points = []
            for step, step_records in sorted(by_step.items()):
                matches = [r for r in step_records if key in r['metrics'] and
                           dumps({k:v for k,v in r['metrics'][key].items() if k not in ('value','status')}) == definition]
                # Distinct log identities at one coordinate are ambiguous, even if equal.
                status = 'missing' if not matches else 'conflicting' if len(matches)>1 else matches[0]['metrics'][key]['status']
                points.append(dict(step=step,status=status,value=matches[0]['metrics'][key]['value'] if status=='recorded' else None,
                                   record_ids=[r['id'] for r in matches]))
            series.append(dict(id='telemetry-'+digest([context_key,key,definition]),context=json.loads(context_key),
                               native_key=key,**spec,points=points,recorded=sum(p['status']=='recorded' for p in points),coordinates=len(points)))
    contexts=[json.loads(key) for key in streams]
    expected=GROUPS
    if contexts and all(c['framework']=='stable-baselines3' for c in contexts):
        expected=('reward','loss','throughput') + (('entropy','kl','clipping') if any(c['objective']=='ppo' for c in contexts) else ())
    return dict(schema=VERSION,series=series,truncated=truncated,omitted_series=omitted_series,record_limit=limit,records=len(rows[:limit]),
                missing_groups=[g for g in expected if not any(s['group']==g and s['recorded'] for s in series)],
                boundary='Native logged coordinates; no rollout joins, cross-writer averaging, inferred values or universal health thresholds.')


class TrainerTelemetry:
    """Write native metrics locally or through a durable Outbox."""
    def __init__(self, target, *, experiment, framework, framework_version, objective, session,
                 producer=None, clock='learner_update', population='trainer logged batch', environment='unspecified', definitions=None):
        self.target = target
        self.context = dict(experiment=experiment,framework=framework,framework_version=framework_version,
            objective=objective,session=session,producer=producer or getattr(target,'producer',None),
            clock=clock,population=population,environment=environment,definitions=definitions)
        for key in ('experiment','framework_version','objective','session','producer','clock','population','environment'):
            text(self.context[key],key)
        if framework not in PROFILES: raise InputError('Unknown telemetry framework profile')

    def log(self, logs, *, step, split='train', record_id=None, training_uses=None):
        value = packet(logs,step=step,split=split,record_id=record_id,training_uses=training_uses,**self.context)
        if value is None: return {'skipped':'No scalar metrics'}
        if hasattr(self.target,'log_telemetry'): return self.target.log_telemetry(value['experiment'],value['records'],schema=value['schema'])
        return receive(self.target,value)

    def log_policy_comparison(self, behavior_logprobs, learner_logprobs, *, mask, step,
                              basis, record_id=None, training_uses=None,
                              probability_thresholds=(), ratio_bounds=None):
        """Compare already aligned, detached token log-probabilities; no forward pass.

        ``basis`` describes the comparison protocol, including distribution and
        mask semantics. Record actual policy/backend versions on execution spans.
        These sampled gaps are not reference KL or proof of quantization error.
        """
        from .policy_comparison import compare_probabilities
        text(basis,'comparison basis')
        report=compare_probabilities(behavior_logprobs,learner_logprobs,mask,
            probability_thresholds=probability_thresholds,ratio_bounds=ratio_bounds)
        logs={'comparison/'+k:v for k,v in report.items() if k not in ('ratio','thresholds')}
        meanings={
            'comparison/mean_absolute_gap':('Mean absolute log-probability gap','nats','Mean |learner log p − behavior log p| over included sampled tokens.'),
            'comparison/mean_signed_gap':('Mean signed log-probability gap','nats','Mean learner log p − behavior log p over included sampled tokens; not a distributional KL.'),
            'comparison/max_absolute_gap':('Maximum log-probability gap','nats','Maximum absolute gap over included sampled tokens.'),
            'comparison/token_weight_ess_fraction':('Token importance-weight ESS fraction','fraction','(sum w)^2 / (N × sum w²), w = exp(learner log p − behavior log p). A token-weight concentration diagnostic, not the trainer objective or independent-sample ESS.'),
            'comparison/compared_tokens':('Compared tokens','tokens','Included aligned token positions in this comparison.'),
            'comparison/mean_probability_gap':('Mean probability gap','probability','Mean absolute learner-versus-behavior sampled-token probability difference; not full-vocabulary total variation or KL.'),
            'comparison/p95_probability_gap':('95th percentile probability gap','probability','Nearest-rank 95th percentile absolute probability difference over included tokens.'),
            'comparison/max_probability_gap':('Maximum probability gap','probability','Largest absolute learner-versus-behavior sampled-token probability difference.')}
        def diagnostic(prefix,item,rule):
            fields={'excluded_tokens':('Excluded tokens','tokens'),'excluded_fraction':('Excluded fraction','fraction'),
                    'probability_only_tokens':('Probability rule only','tokens'),'ratio_only_tokens':('Ratio rule only','tokens'),
                    'disagreement_fraction':('Mask disagreement','fraction')}
            for field,(label,unit) in fields.items():
                if field not in item:continue
                name=prefix+'/'+field;logs[name]=item[field]
                meanings[name]=(label+' · '+rule,unit,'Replayed mask rule: '+rule+'. '+label+' over the supplied base-mask tokens. Fractions use all compared tokens. This is not the actual trainer mask or a prediction of training outcomes.')
        ratio=report['ratio']
        band=''
        if ratio:
            low,high=ratio['bounds'];band=f'ratio outside [{low:g}, {high:g}]'
            diagnostic('comparison/ratio/'+repr(low)+'/'+repr(high),ratio,band)
        for item in report['thresholds']:
            threshold=item['threshold'];rule=f'probability gap > {threshold:g}'
            if band:rule+=' versus '+band
            diagnostic('comparison/probability/'+repr(threshold)+(('/ratio/'+repr(ratio['bounds'][0])+'/'+repr(ratio['bounds'][1])) if ratio else ''),item,rule)
        definitions={key:metric(label,'mismatch',unit,'declared comparison mask',definition+' Basis: '+basis)
                     for key,(label,unit,definition) in meanings.items()}
        context={**self.context,'definitions':{**(self.context['definitions'] or {}),**definitions}}
        value=packet(logs,step=step,record_id=record_id,training_uses=training_uses,**context)
        if hasattr(self.target,'log_telemetry'):return self.target.log_telemetry(value['experiment'],value['records'],schema=value['schema'])
        return receive(self.target,value)

    def transformers_callback(self):
        """Attach to TRL's public TrainerCallback.on_log; only world rank zero logs."""
        from transformers import TrainerCallback
        owner = self
        class Capture(TrainerCallback):
            def on_log(self,args,state,control,logs=None,**kwargs):
                if not state.is_world_process_zero or not logs: return control
                train = {k:v for k,v in logs.items() if not k.startswith('eval_')}
                evaluation = {k:v for k,v in logs.items() if k.startswith('eval_')}
                if train: owner.log(train,step=state.global_step,split='train')
                if evaluation: owner.log(evaluation,step=state.global_step,split='evaluation')
                return control
        return Capture()
