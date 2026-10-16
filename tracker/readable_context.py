"""Source-preserving text views for an inspector that has not decoded media.

Only the request view changes. Original events and source offsets never change.
Every readable fragment maps back to an exact interval in the original event.
"""
from copy import deepcopy
import re

from .schema import InputError, digest

VERSION = 'readable-context/1'
GOVERNING_VERSION = 'readable-context/2'
CONTEXT_VERSION = 'readable-context/3'
POLICY_VERSIONS = {VERSION,GOVERNING_VERSION,CONTEXT_VERSION}
DATA_URI = re.compile(r'data:([a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,[A-Za-z0-9+/=]+')


def is_readable(policy):
    return bool(policy and policy.get('schema') in POLICY_VERSIONS)


def protected_instruction(event,policy):
    # Roles come from the adapter, never words such as "system" in tool text.
    # Retention does not adjudicate conflicting instructions or their adoption.
    return (event['kind']=='instruction' or
            (policy['schema'] in {GOVERNING_VERSION,CONTEXT_VERSION} and event.get('actor') in {'system','developer'}))


def validate_policy(policy):
    if (set(policy) != {'schema','recent_events','max_event_chars','extra_ranges'} or
            policy['schema'] not in POLICY_VERSIONS or type(policy['recent_events']) is not int or
            not 1 <= policy['recent_events'] <= 100 or type(policy['max_event_chars']) is not int or
            not 128 <= policy['max_event_chars'] <= 100_000 or not isinstance(policy['extra_ranges'], list)):
        raise InputError('Invalid readable context policy')
    for ref in policy['extra_ranges']:
        if (not isinstance(ref,dict) or set(ref) != {'event_id','start','end'} or
                not isinstance(ref['event_id'],str) or type(ref['start']) is not int or
                type(ref['end']) is not int or not 0 <= ref['start'] < ref['end']):
            raise InputError('Invalid requested context range')


def merged(ranges):
    result=[]
    for a,b in sorted(ranges):
        if a==b:continue
        if result and a<=result[-1][1]:result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:result.append((a,b))
    return result


def subtract(ranges, excluded):
    result=[]
    for a,b in ranges:
        for c,d in excluded:
            if d<=a or c>=b:continue
            if a<c:result.append((a,c))
            a=max(a,d)
            if a>=b:break
        if a<b:result.append((a,b))
    return result


def edge_ranges(ranges, count, reverse=False):
    result=[]
    for a,b in reversed(ranges) if reverse else ranges:
        take=min(count,b-a)
        result.append((b-take,b) if reverse else (a,a+take));count-=take
        if count<=0:break
    return result


def project(event, policy, subject):
    text=event['text'];size=len(text)
    media=[{'start':m.start(),'end':m.end(),'mime_type':m.group(1),
            'source_digest':digest(m.group(0)),'inspection':'not_decoded_or_visually_inspected'} for m in DATA_URI.finditer(text)]
    excluded=[(m['start'],m['end']) for m in media]
    available=subtract([(0,size)],excluded)
    explicit=[(r['start'],r['end']) for r in policy['extra_ranges'] if r['event_id']==event['id']]
    if any(b>size for a,b in explicit):raise InputError('Requested context range exceeds source cutoff')
    protected=protected_instruction(event,policy) or event['id']==subject['event_id']
    if protected or sum(b-a for a,b in available)<=policy['max_event_chars']:
        keep=available
    else:
        half=policy['max_event_chars']//2
        keep=merged(edge_ranges(available,half)+edge_ranges(available,policy['max_event_chars']-half,True)+subtract(explicit,excluded))
    omitted=subtract(available,keep)
    auxiliary=[]
    def scrub(value,path):
        if isinstance(value,str):
            def replace(m):
                auxiliary.append({'field_path':path,'mime_type':m.group(1),'source_digest':digest(m.group(0)),
                                  'inspection':'not_decoded_or_visually_inspected'})
                return f'[UNOBSERVED MEDIA: {m.group(1)}; encoded data retained in source]'
            return DATA_URI.sub(replace,value)
        if isinstance(value,dict):return {k:scrub(v,path+'/'+str(k)) for k,v in value.items()}
        if isinstance(value,list):return [scrub(v,path+'/'+str(i)) for i,v in enumerate(value)]
        return value
    auxiliary_fields={k:scrub(event[k],'/'+k) for k in ('arguments','tool_contract') if k in event}
    if not media and not omitted and not event.get('media') and not auxiliary:
        return deepcopy(event)
    chunks=[];mapping=[];view_pos=0;pos=0
    gaps=[(a,b,'text') for a,b in omitted]+[(m['start'],m['end'],m['mime_type']) for m in media]
    for a,b,kind in sorted([(a,b,'readable') for a,b in keep]+gaps):
        if kind=='readable':
            value=text[a:b]
            mapping.append({'source_start':a,'source_end':b,'view_start':view_pos,'view_end':view_pos+len(value)})
        elif kind=='text':value=f'\n[OMITTED TEXT: {event["id"]} source characters {a}:{b}; retrievable]\n'
        else:value=f'[UNOBSERVED MEDIA: {kind}; {event["id"]} source characters {a}:{b}; encoded data retained in source, not inspected]'
        chunks.append(value);view_pos+=len(value);pos=b
    out=deepcopy(event);out['text']=''.join(chunks)
    out.update(auxiliary_fields)
    out.update(text_projection=VERSION,source_text_length=size,source_text_ranges=mapping,
               omitted_text_ranges=[{'start':a,'end':b} for a,b in omitted],unobserved_inline_media=media,
               unobserved_auxiliary_media=auxiliary)
    if event.get('media'):
        out['unobserved_media_parts']=[{'type':m.get('type','unknown') if isinstance(m,dict) else 'unknown',
                                      'source_digest':digest(m),'inspection':'not_inspected'} for m in event['media']]
        out.pop('media',None)
    return out


def project_prefix(full, subject, policy):
    validate_policy(policy)
    if DATA_URI.search(subject['text']):
        raise InputError('Binary media occurs inside the required subject; a text-only context view cannot inspect this unit')
    lookup={e['id']:e for e in full}
    for ref in policy['extra_ranges']:
        if ref['event_id'] not in lookup:raise InputError('Requested context is future, another trajectory, or not agent-visible')
        if ref['end']>len(lookup[ref['event_id']]['text']):raise InputError('Requested context range exceeds source cutoff')
    include={e['id'] for e in full[-policy['recent_events']:]}|{r['event_id'] for r in policy['extra_ranges']}
    selected=[e for e in full if e['id'] in include or protected_instruction(e,policy)]
    return [project(e,policy,subject) for e in selected]


def contains(prefix_event, ref):
    """Only actual source text can support citations, never omission descriptors."""
    if prefix_event.get('text_projection') != VERSION:
        return 0<=ref['start']<ref['end']<=len(prefix_event['text'])
    return any(r['source_start']<=ref['start']<ref['end']<=r['source_end'] for r in prefix_event['source_text_ranges'])


def source_fragments(event):
    if event.get('text_projection') != VERSION:
        return [(0,event['text'])]
    return [(r['source_start'],event['text'][r['view_start']:r['view_end']]) for r in event['source_text_ranges']]


def resolve_quote(run, prefix, ref):
    """Convert a supplied verbatim quote to original offsets without LLM counting.

    Ambiguous repeats require explicit source_start. No fuzzy quote correction.
    """
    if not isinstance(ref,dict) or not {'event_id','quote'}<=set(ref)<= {'event_id','quote','source_start'}:
        raise InputError('Invalid source-quote citation')
    quote=ref['quote']
    if not isinstance(quote,str) or not quote.strip():raise InputError('Citation quote must contain source text')
    e=next((e for e in prefix if e['id']==ref['event_id']),None)
    if e is None:raise InputError('Quote cites omitted or unavailable context')
    matches=[]
    for offset,text in source_fragments(e):
        pos=0
        while (pos:=text.find(quote,pos))!=-1:
            matches.append(offset+pos);pos+=1
    if 'source_start' in ref:
        if type(ref['source_start']) is not int:raise InputError('Quote source_start must be an integer')
        matches=[s for s in matches if s==ref['source_start']]
    if len(matches)!=1:raise InputError('Citation quote is missing or ambiguous in supplied context')
    original=next(e for e in run['events'] if e['id']==ref['event_id'])
    start=matches[0];end=start+len(quote)
    if original['text'][start:end]!=quote:raise InputError('Quote view differs from original source')
    return {'event_id':original['id'],'source_pointer':original['source_pointer'],'start':start,'end':end,'text':quote}


def resolve_citation(run, request, ref, citation_format=None):
    """Bind an explicitly selected current-unit reference; never repair a quote.

    The response format is opt-in, so historical requests and quote interpretation
    are unchanged. A whole-unit reference cannot cover omitted source text.
    """
    if not isinstance(ref,dict):raise InputError('Source citation must be an object')
    if 'subject' in ref:
        if citation_format!='source-references/1' or set(ref)!={'subject'} or ref['subject'] is not True:
            raise InputError('Current-unit citation requires the explicit source-reference format')
        from .semantic_extraction import checked_span
        source=deepcopy(request['source']); checked_span(run,source,source)
        visible=next((e for e in request['prefix'] if e['id']==source['event_id']),None)
        if visible is None or not contains(visible,source):
            raise InputError('Current-unit citation includes omitted or unavailable source text')
        # Only source identity and the exact original span leave this resolver.
        return {k:source[k] for k in ('event_id','source_pointer','start','end','text')}
    if isinstance(ref,dict) and 'quote' in ref:
        return resolve_quote(run,request['prefix'],ref)
    return deepcopy(ref)


def resolve_response(run, request, response):
    result=deepcopy(response)
    if result.get('citation_format') not in {'source-quotes/1','source-references/1'}:return result
    def walk(value):
        if isinstance(value,dict):
            for key,item in list(value.items()):
                if key=='evidence':
                    if not isinstance(item,list):raise InputError('Quote evidence must be a list')
                    value[key]=[resolve_citation(run,request,r,result['citation_format'])
                                if result['citation_format']=='source-references/1'
                                else resolve_quote(run,request['prefix'],r) for r in item]
                else:walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(result.get('candidates',[]))
    return result
