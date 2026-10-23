"""One bounded, fully validated file across UI/API/CLI, with stable row identity."""
import base64
import binascii
import hashlib
import json
from pathlib import Path

from .adapters import normalize, detect
from .schema import InputError, digest, metadata

MAX_BYTES=100_000_000


def read_bytes(raw,*,name='snapshot.json',format='auto',meta=None,max_bytes=MAX_BYTES):
    if not isinstance(raw,bytes) or len(raw)>max_bytes:raise InputError('Source file exceeds import size limit')
    if meta is not None and not isinstance(meta,dict):raise InputError('metadata must be an object')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError as e:raise InputError('Source file must be UTF-8 JSON or JSONL') from e
    meta=metadata(meta)
    if not name.lower().endswith('.jsonl'):
        try:doc=json.loads(text)
        except ValueError as e:raise InputError(f'{name}: invalid JSON: {e}') from e
        return normalize(doc,format,meta)
    # A Weave line is a call, not a rollout. Assemble interleaved trace groups
    # across the complete export before any source or metric is published.
    from .weave_import import is_call
    lines = [(i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()]
    if lines:
        try: first = json.loads(lines[0][1])
        except ValueError as e: raise InputError(f'{name}, line {lines[0][0]}: invalid JSON') from e
        if format == 'weave' or format == 'auto' and is_call(first):
            calls = []
            for line, value in lines:
                try:
                    call = json.loads(value)
                    if not is_call(call): raise InputError('Each Weave JSONL line must be a full native call')
                    calls.append(call)
                except ValueError as e: raise InputError(f'{name}, line {line}: {e}') from e
            return normalize({'calls':calls}, 'weave', meta)
    if not meta.get('experiment'):raise InputError('JSONL batch import requires an explicit experiment in metadata')
    file_hash=hashlib.sha256(raw).hexdigest();runs=[]
    for line,text in enumerate(text.splitlines(),1):
        if not text.strip():continue
        try:
            doc=json.loads(text)
            if not isinstance(doc,dict):raise InputError('Each JSONL record must be an object')
            fmt=format
            if fmt=='auto' and all(k in doc for k in ('input','output','step')):fmt=detect(doc)
            row_meta={**meta,'source_file_sha256':file_hash,'source_line':line,'source_record_sha256':digest(doc),
                      'source_record_id':file_hash+':'+str(line)}
            values=normalize(doc,fmt,row_meta)
            if len(values)!=1:raise InputError('A JSONL line must represent one rollout, not another multi-rollout bundle')
            runs.extend(values)
        except (ValueError,TypeError) as e:raise InputError(f'{name}, line {line}: {e}') from e
    if not runs:raise InputError('JSONL contains no records')
    return runs


def read_path(path,format='auto',meta=None,max_bytes=MAX_BYTES):
    path=Path(path)
    if path.stat().st_size>max_bytes:raise InputError('Source file exceeds import size limit')
    with path.open('rb') as stream:raw=stream.read(max_bytes+1)
    return read_bytes(raw,name=path.name,format=format,meta=meta,max_bytes=max_bytes)


def read_request(body):
    """Base64 preserves the exact file bytes across browser/CLI (including BOM)."""
    file=body.get('file')
    if not isinstance(file,dict) or not isinstance(file.get('name'),str) or not isinstance(file.get('base64'),str):raise InputError('Supply file.name and file.base64')
    if not isinstance(body.get('metadata',{}),dict):raise InputError('metadata must be an object')
    try:raw=base64.b64decode(file['base64'],validate=True)
    except (binascii.Error,ValueError) as e:raise InputError('Malformed base64 file') from e
    return read_bytes(raw,name=Path(file['name']).name,format=body.get('format','auto'),meta=body.get('metadata'),max_bytes=14*1024*1024)


def preflight(runs,*,limit=5):
    from collections import Counter,defaultdict
    from .integrations import inspect
    from .rollout_metrics import source_record
    from .source_grain import describe
    formats=Counter();warnings=Counter();metrics=defaultdict(lambda:{'available':0,'missing':0});clocks=0;actions=0
    units={}
    for run in runs:
        unit=describe(run)
        units.setdefault(unit['id'], {**unit, 'records':0})['records']+=1
        formats[run['adapter']]+=1;warnings.update(run['warnings'])
        m=run['metadata'];clocks+=bool(m.get('experiment') and type(m.get('training_step')) is int and m.get('training_step_basis'))
        for key,value in source_record(run)['metrics'].items():metrics[key]['available' if value['value'] is not None else 'missing']+=1
        actions+=sum(e['kind']=='action' and not e.get('copied_context') for e in run['events'])
    return {'schema':'import-preflight/1','persisted':False,'total_rollouts':len(runs),'preview_rollouts':min(limit,len(runs)),
        'total_records':len(runs),'source_units':list(units.values()),
        'preview_limit':limit,'formats':dict(formats),'recorded_actions':actions,'declared_training_coordinates':clocks,
        'metric_coverage':dict(metrics),'warning_counts':[{'warning':w,'rollouts':n} for w,n in warnings.items()],
        'runs':[inspect(r) for r in runs[:limit]],'note':'Every record was validated. Detailed preview is bounded; absence from the preview does not exclude a record from import.'}
