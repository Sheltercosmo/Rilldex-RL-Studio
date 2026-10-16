"""Copy an exact validated decision, never a similar question or derived result."""
from pathlib import Path
from .schema import InputError,digest
from .semantic_extraction import read,replay_decision,write

VERSION='exact-decision-reuse/1'


def lookup(request,sources):
    """Read and validate exact receipts without copying files or calling a provider."""
    key=digest(request)
    candidates=[]
    for source in sources:
        path=Path(source)/'decisions'/f'{key}.json'
        if not path.exists():continue
        saved=read(path)
        if saved.get('request')!=request or saved.get('response',{}).get('model')!=request['model']:
            raise InputError('Reusable decision request/model differs')
        answers=replay_decision(saved)
        if answers!=saved.get('answers'):raise InputError('Reusable decision is not raw argmax')
        candidates.append((path,saved))
    if not candidates:return None
    # Repeated evaluations may have distinct timing metadata; disagreeing
    # answer values must never be selected by incidental source order.
    values=lambda saved:{k:v['value'] for k,v in saved['answers'].items()}
    if any(values(saved)!=values(candidates[0][1]) for _,saved in candidates[1:]):
        raise InputError('Exact cache sources contain conflicting selected answers')
    path,saved=candidates[0]
    return path,saved,len(candidates)


def reuse(directory,request,sources):
    root=Path(directory);key=digest(request)
    if (root/'decisions'/f'{key}.json').exists():return False
    found=lookup(request,sources)
    if found is None:return False
    path,saved,count=found
    receipt={'schema':VERSION,'request_hash':key,'packet_hash':digest(saved),
             'source_path':str(path.resolve()),'compatible_source_count':count,
             'comparison':'Exact complete request, model and raw argmax; no fields removed or rewritten',
             'new_provider_calls':0,'semantic_accuracy':'Not established by reuse'}
    write(root/'reuse'/f'{key}.json',receipt)
    write(root/'decisions'/f'{key}.json',saved)
    return True


def audit(directory):
    root=Path(directory);keys=[]
    for path in (root/'reuse').glob('*.json'):
        row=read(path);key=row.get('request_hash')
        if row.get('schema')!=VERSION or path.stem!=key:raise InputError('Unknown decision reuse receipt')
        saved=read(root/'decisions'/f'{key}.json')
        if digest(saved)!=row.get('packet_hash') or digest(saved['request'])!=key:
            raise InputError('Reused decision packet changed')
        if saved['response'].get('model')!=saved['request']['model'] or replay_decision(saved)!=saved['answers']:
            raise InputError('Reused decision no longer replays')
        keys.append(key)
    return {'schema':VERSION,'exact_reused_decisions':len(keys),'request_hashes':sorted(keys),'new_provider_calls':0}
