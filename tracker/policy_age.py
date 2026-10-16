"""Policy-age observations from explicitly shared producer clocks.

No subtraction of trainer steps, checkpoint names or arrival timestamps. Token
positions refer to generated target tokens, including targets later masked out.
"""
from collections import Counter, defaultdict
import json

from .schema import InputError, dumps

CLOCK_VERSION = 'policy-clock/1'
HISTORY_VERSION = 'generation-policy-history/1'
VERSION = 'policy-age/1'
UNITS = {'optimizer_update', 'policy_publication'}


def _integer(n, name):
    if type(n) is not int or not 0 <= n < 2**53:
        raise InputError(name + ' must be a nonnegative safe integer')


def validate_clock(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'clock', 'unit', 'index'}:
        raise InputError('Policy clock requires schema, clock, unit and index')
    if value['schema'] != CLOCK_VERSION or not isinstance(value['unit'], str) or value['unit'] not in UNITS:
        raise InputError('Use policy-clock/1 with optimizer_update or policy_publication')
    if not isinstance(value['clock'], str) or not 1 <= len(value['clock'].strip()) <= 300:
        raise InputError('Policy clock identity must contain 1–300 characters')
    _integer(value['index'], 'policy index')


def validate_history(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'token_count', 'segments'} or value['schema'] != HISTORY_VERSION:
        raise InputError('Generation policy history requires schema, token_count and segments')
    _integer(value['token_count'], 'generation token count')
    if not isinstance(value['segments'], list) or len(value['segments']) > 4096:
        raise InputError('Policy history supports at most 4096 non-overlapping segments')
    end = 0
    for s in value['segments']:
        if not isinstance(s, dict) or set(s) != {'start', 'end', 'policy'}:
            raise InputError('Policy segment requires start, end and policy')
        _integer(s['start'], 'segment start'); _integer(s['end'], 'segment end')
        if not end <= s['start'] < s['end'] <= value['token_count']:
            raise InputError('Policy segments must be sorted, non-overlapping and within generated targets')
        validate_clock(s['policy']); end = s['end']


def uniform_history(policy, tokens):
    value = {'schema':HISTORY_VERSION, 'token_count':tokens,
             'segments':[{'start':0, 'end':tokens, 'policy':dict(policy)}] if tokens else []}
    validate_history(value)
    return value


class OptimizerClock:
    """Session-local successful native optimizer callbacks; not a weight hash."""
    def __init__(self, identity):
        self.identity = identity
        self.index = 0
        self.last_attempt = None
        self.last_skipped = None
        self.valid = True

    def snapshot(self):
        return {'schema':CLOCK_VERSION, 'clock':self.identity, 'unit':'optimizer_update',
                'index':self.index} if self.valid else None

    def invalidate(self):
        self.valid = False

    def advance(self, attempt, *, skipped, synchronized):
        if not self.valid: return
        if (not synchronized or type(attempt) is not int or attempt < 0
                or self.last_attempt is not None and attempt < self.last_attempt
                or attempt == self.last_attempt and skipped != self.last_skipped):
            self.invalidate()
            raise InputError('Policy clock cannot reconcile this optimizer callback')
        if attempt == self.last_attempt: return
        self.last_attempt = attempt; self.last_skipped = skipped
        if not skipped: self.index += 1


def observe(history, learner, model_tokens):
    result = {'schema':VERSION, 'state':'missing_generation_history', 'learner':learner, 'generation_history':history,
              'token_count':model_tokens, 'known_tokens':0, 'ages':[], 'uniform_age':None,
              'complete':False, 'excluded_tokens':{}}
    if not history: return result
    validate_history(history)
    if model_tokens is None or history['token_count'] != model_tokens:
        result['state'] = 'token_count_mismatch'; return result
    if not learner:
        result['state'] = 'missing_learner_clock'; return result
    validate_clock(learner)
    ages = Counter(); excluded = Counter(); covered = 0
    for segment in history['segments']:
        policy=segment['policy']; count=segment['end']-segment['start']; covered += count
        if (policy['clock'], policy['unit']) != (learner['clock'], learner['unit']):
            excluded['different_clock'] += count
        elif policy['index'] > learner['index']:
            excluded['generation_after_learner'] += count
        else: ages[learner['index']-policy['index']] += count
    if covered < model_tokens: excluded['generation_policy_unrecorded'] = model_tokens-covered
    known = sum(ages.values()); complete = known == model_tokens and model_tokens > 0
    return {**result, 'state':'complete' if complete else 'partial' if known else 'unresolved',
            'known_tokens':known, 'ages':[{'age':age,'tokens':n} for age,n in sorted(ages.items())],
            'uniform_age':next(iter(ages)) if complete and len(ages)==1 else None,
            'complete':complete, 'excluded_tokens':dict(excluded)}


def summarize(receipts):
    """Keep unrelated clocks and clock units separate even in one producer stream."""
    by_clock=defaultdict(list); states=Counter()
    for r in receipts:
        o=r['policy_age'];states[o['state']]+=1
        if o['learner']: by_clock[dumps({k:o['learner'][k] for k in ('clock','unit')})].append(r)
    clocks=[]
    for key, rows in sorted(by_clock.items()):
        ages=Counter(); tokens=known=complete=mixed=0; excluded=Counter()
        for row in rows:
            o=row['policy_age']; tokens += o['token_count'] or 0; known += o['known_tokens']
            complete += o['complete']; mixed += o['complete'] and len(o['ages'])>1
            for a in o['ages']: ages[a['age']] += a['tokens']
            excluded.update(o['excluded_tokens'])
        clocks.append({**json.loads(key), 'receipts':len(rows), 'known_tokens':known,
            'recorded_target_tokens':tokens, 'complete_uses':complete, 'mixed_policy_uses':mixed,
            'mean_age':sum(age*n for age,n in ages.items())/known if known else None,
            'maximum_age':max(ages) if ages else None, 'minimum_age':min(ages) if ages else None,
            'histogram':[{'age':age,'tokens':n} for age,n in sorted(ages.items())],
            'excluded_tokens':dict(excluded)})
    return {'schema':VERSION, 'receipts':len(receipts), 'states':dict(states), 'clocks':clocks,
            'observed_uses':sum(r['policy_age']['known_tokens']>0 for r in receipts)}


def behavior_groups(receipts, samples, reference):
    from .population_statistics import summary
    lookup={dumps(reference(s)):s for s in samples}
    buckets=defaultdict(list)
    for r in receipts:
        o=r['policy_age']
        if not o['complete']: continue
        key=(o['learner']['clock'], o['learner']['unit'], o['uniform_age'])
        buckets[key].append(r)
    groups=[]; appearances=Counter()
    for (clock,unit,age), rows in sorted(buckets.items(),key=lambda item:(item[0][0],item[0][1],-1 if item[0][2] is None else item[0][2])):
        ids={dumps(r['sample']) for r in rows}
        members=[lookup[key] for key in sorted(ids) if lookup[key]['monitor_population']=='included']
        sources={m['run_id'] for m in members if m.get('run_id')}
        appearances.update((clock,unit,rid) for rid in sources)
        groups.append({'clock':clock,'unit':unit,'age':age,'kind':'mixed' if age is None else 'uniform',
            'receipts':len(rows),'outside_monitor_scope':len(ids)-len(members),
            'samples':[reference(s) for s in members],
            **summary(members,False,source_weighted=True)})
    overlaps=Counter((clock,unit) for (clock,unit,_),n in appearances.items() if n>1)
    return {'groups':groups,'sources_in_multiple_groups':sum(n>1 for n in appearances.values()),
            'clock_overlaps':[{'clock':clock,'unit':unit,'sources':n} for (clock,unit),n in sorted(overlaps.items())],
            'excluded_uses':sum(not r['policy_age']['complete'] for r in receipts)}
