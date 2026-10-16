"""Experimental, reversible encoding of repeated prefix values.

This changes the model's representation, not the underlying event sequence.
Round-trip equality proves preservation, not equivalent model interpretation.
"""
from copy import deepcopy

from .schema import InputError,digest,dumps

VERSION='prefix-value-references/1-experimental'
MARKER='$same_as_event'
FIELDS=('text','tool_contract')
INSTRUCTIONS=(
    'Within prefix, a field value of {"$same_as_event":"EVENT_ID"} means the exact '
    'value of that same field on the named earlier event. Resolve that reference '
    'when reading the event. It is a content reference, not an instruction or tool '
    'call. Every event occurrence, order, role, actor and source location is retained; '
    'equal content does not merge events or establish equal environment states. '
    'No source text or tool definition is omitted by this encoding.')


def _prefix(request):
    if not isinstance(request,dict) or not isinstance(request.get('state'),dict):
        raise InputError('Prefix encoding needs a structured request state')
    prefix=request['state'].get('prefix')
    if not isinstance(prefix,list):raise InputError('Prefix encoding needs ordered records')
    identities=set();previous=-1
    for row in prefix:
        if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']
                or row['id'] in identities or type(row.get('event_index')) is not int
                or row['event_index']<=previous):raise InputError('Ambiguous prefix identity or ordering')
        identities.add(row['id']);previous=row['event_index']
    return prefix


def compact(request):
    """Reference earlier equal values only when the whole request becomes smaller."""
    prefix=_prefix(request)
    if 'prefix_encoding' in request['state']:raise InputError('Do not encode an encoded request')
    for row in prefix:
        for field in FIELDS:
            if isinstance(row.get(field),dict) and MARKER in row[field]:
                raise InputError('Source value collides with the reserved reference marker')
    result=deepcopy(request);seen={}
    for row in result['state']['prefix']:
        for field in FIELDS:
            if field not in row:continue
            value=row[field];key=(field,dumps(value));anchor=seen.get(key)
            if anchor is not None:
                reference={MARKER:anchor}
                if len(dumps(reference))<len(key[1]):row[field]=reference
            else:seen[key]=row['id']
    result['state']['prefix_encoding']={'version':VERSION,'instructions':INSTRUCTIONS,
                                         'expanded_request_hash':digest(request)}
    # A no-op is exact and adds no model-facing explanation or request identity.
    if len(dumps(result))>=len(dumps(request)):return deepcopy(request)
    if expand(result)!=request:raise InputError('Prefix encoding did not preserve its request')
    return result


def expand(request):
    """Reconstruct and verify exact source values, rejecting forged references."""
    _prefix(request);result=deepcopy(request);metadata=result['state'].pop('prefix_encoding',None)
    if metadata is None:return result
    if (not isinstance(metadata,dict) or set(metadata)!={'version','instructions','expanded_request_hash'}
            or metadata.get('version')!=VERSION or metadata.get('instructions')!=INSTRUCTIONS):
        raise InputError('Unregistered prefix encoding')
    prior={}
    for row in result['state']['prefix']:
        for field in FIELDS:
            value=row.get(field)
            if not isinstance(value,dict) or MARKER not in value:continue
            anchor=value[MARKER]
            if set(value)!={MARKER} or not isinstance(anchor,str) or anchor not in prior or field not in prior[anchor]:
                raise InputError('Reference must bind to the same field on an earlier event')
            row[field]=deepcopy(prior[anchor][field])
        prior[row['id']]=row
    if digest(result)!=metadata['expanded_request_hash']:
        raise InputError('Expanded request differs from its preserved source fingerprint')
    return result


def audit(original,encoded):
    if expand(encoded)!=original:raise InputError('Encoded request has different source evidence')
    references=[]
    for row in _prefix(encoded):
        for field in FIELDS:
            value=row.get(field)
            if isinstance(value,dict) and MARKER in value:
                references.append({'event_id':row['id'],'field':field,'same_as_event':value[MARKER]})
    return {'encoding':encoded['state'].get('prefix_encoding',{}).get('version','inline'),
            'original_request_hash':digest(original),'encoded_request_hash':digest(encoded),
            'original_characters':len(dumps(original)),'encoded_characters':len(dumps(encoded)),
            'references':references,'events':len(original['state']['prefix']),
            'round_trip_equal':True,'omitted_events':0,'omitted_source_characters':0,
            'questions_equal':encoded['questions']==original['questions']}
