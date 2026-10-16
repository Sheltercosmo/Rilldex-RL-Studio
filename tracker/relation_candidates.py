"""Experimental, label-blind candidates for source-unit relationships.

No native annotation labels, outcomes, or future units enter ranking. The
caller must validate extraction against original sources before using this
generic contract. This module is not connected to production observations.
"""
from collections import Counter
import math
import re

from .schema import InputError,digest

VERSION = 'relation-candidates/0.1-experimental'
BUDGET_VERSION = 'relation-candidate-budget/1-experimental'
PROFILES = {'recent12':(12,0),'hybrid12':(6,6)}
FIELDS = ('id','trace_id','actor_id','event_index','source_pointer','start','end','text','role')
ROLES = {'model','instruction','context','feedback'}
STOP = set('a an and are as at be been but by can could did do does for from had has have i if in into is it its let me my of on or our should so that the their then there these they this those to was we were what when where which will with would you your'.split())


def project(unit):
    try:result={k:unit[k] for k in FIELDS}
    except KeyError as error:raise InputError('Missing relation-unit field: '+str(error)) from error
    if (not all(isinstance(result[k],str) and result[k] for k in ('id','trace_id','actor_id','source_pointer'))
            or result['role'] not in ROLES or not isinstance(result['text'],str)
            or any(type(result[k]) is not int for k in ('event_index','start','end'))
            or not 0<=result['start']<result['end'] or len(result['text'])!=result['end']-result['start']):
        raise InputError('Invalid relation-unit source identity or code-point span')
    return result


def previous_units(units,subject):
    subject=project(subject);result=[];seen=set()
    for value in units:
        unit=project(value)
        key=(unit['trace_id'],unit['actor_id'],unit['id'])
        if key in seen:raise InputError('Duplicate qualified relation-unit identity')
        seen.add(key)
        if key==(subject['trace_id'],subject['actor_id'],subject['id']) and unit!=subject:
            raise InputError('Subject identity conflicts with supplied source unit')
        if unit['trace_id']!=subject['trace_id'] or unit['actor_id']!=subject['actor_id']:continue
        before=(unit['event_index']<subject['event_index'] or
                (unit['event_index']==subject['event_index'] and unit['source_pointer']==subject['source_pointer'] and unit['end']<=subject['start']))
        if before:result.append(unit)
    return sorted(result,key=lambda u:(u['event_index'],u['start'],u['end'],u['id']))


def terms(text):
    # Preserve numbers and math symbols; lexical similarity is only retrieval.
    return Counter(t for t in re.findall(r'\w+|[=+*/<>−-]',text.casefold()) if t not in STOP)


def retrieve(units,subject,profile='hybrid12'):
    if profile not in PROFILES:raise InputError('Unknown relation candidate profile')
    return _retrieve(units,subject,profile,*PROFILES[profile],VERSION)


def retrieve_budgeted(units,subject,*,candidate_limit=24,recent_limit=12):
    """Explicit non-LLM budget, separate from Jev's raw-argmax decision rule.

    Existing profiles and their result identities are unchanged. This optional
    experimental interface does not enable automatic production inference.
    """
    if (type(candidate_limit) is not int or not 1<=candidate_limit<=64 or
            type(recent_limit) is not int or not 0<=recent_limit<=candidate_limit):
        raise InputError('Use a candidate limit of 1–64 and a recent limit within that budget')
    return _retrieve(units,subject,f'hybrid{candidate_limit}/recent{recent_limit}',
                     recent_limit,candidate_limit-recent_limit,BUDGET_VERSION)


def _retrieve(units,subject,profile,recent_count,lexical_count,version):
    subject=project(subject);prior=previous_units(units,subject)
    selected={u['id']:['recency'] for u in (prior[-recent_count:] if recent_count else [])}
    scores={}
    if lexical_count:
        # IDF is computed on eligible past units only; future text cannot change ranking.
        bags=[terms(u['text']) for u in prior];df=Counter(t for bag in bags for t in bag)
        query=terms(subject['text']);total=len(prior)
        def vector(bag):return {t:(1+math.log(v))*math.log(1+total/(1+df.get(t,0))) for t,v in bag.items()}
        q=vector(query);qn=math.sqrt(sum(v*v for v in q.values()))
        for unit,bag in zip(prior,bags):
            v=vector(bag);vn=math.sqrt(sum(x*x for x in v.values()))
            scores[unit['id']]=sum(q.get(t,0)*x for t,x in v.items())/(qn*vn) if qn and vn else 0.0
        ranking=sorted(enumerate(prior),key=lambda p:(-scores[p[1]['id']],-p[0],p[1]['id']))
        added=0
        for _,unit in ranking:
            if unit['id'] in selected:continue
            if added>=lexical_count:break
            selected[unit['id']]=['lexical_rank'];added+=1
    candidates=[{'unit':u,'retrieval_basis':selected[u['id']],
                 'lexical_score':scores.get(u['id'])} for u in prior if u['id'] in selected]
    return {'version':version,'profile':profile,'subject':subject,'eligible_prior_units':len(prior),
            'candidates':candidates,'candidate_set_hash':digest([c['unit'] for c in candidates]),
            'scope':'Exact supplied source units; retrieval rank is not a semantic or confidence decision.'}
