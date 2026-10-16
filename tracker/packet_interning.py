"""Lossless interning of identical tool contracts in source-bounded packets."""
from collections import Counter
from copy import deepcopy
from .schema import InputError,digest

VERSION='shared-tool-contracts/1'
FIELD='shared_tool_contracts'
REF='tool_contract_ref'


def compact(request):
    result=deepcopy(request);state=result['state'];events=state['prefix']
    if FIELD in state or any(REF in e for e in events):raise InputError('Packet already has shared-contract fields')
    counts=Counter(digest(e['tool_contract']) for e in events if 'tool_contract' in e)
    definitions={}
    for event in events:
        if 'tool_contract' not in event:continue
        key=digest(event['tool_contract'])
        if counts[key]<2:continue
        definitions[key]=event.pop('tool_contract');event[REF]=key
    if definitions:
        state[FIELD]={'schema':VERSION,'definitions':definitions,
            'instructions':'For every prefix event with tool_contract_ref, resolve that key in these definitions to recover its exact tool_contract. Shared storage does not merge events, arguments, actions or evidence.'}
    return result


def expand(request):
    result=deepcopy(request);state=result['state'];table=state.pop(FIELD,None);used=set()
    if table is not None:
        if table.get('schema')!=VERSION:raise InputError('Unknown shared tool contract format')
        definitions=table['definitions']
        if any(digest(value)!=key for key,value in definitions.items()):raise InputError('Shared contract content hash differs')
    else:definitions={}
    for event in state['prefix']:
        if REF not in event:continue
        key=event.pop(REF)
        if 'tool_contract' in event or key not in definitions:raise InputError('Invalid shared tool contract reference')
        event['tool_contract']=deepcopy(definitions[key]);used.add(key)
    if set(definitions)!=used:raise InputError('Unreferenced shared contract')
    return result
