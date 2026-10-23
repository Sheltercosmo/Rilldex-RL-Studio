"""Immutable run capture and mutable organization, independent of rollout traces."""
import base64
import hashlib
import json
import math
from datetime import datetime, timezone

from .schema import InputError, digest, dumps

VERSION = 'run-records/1'
KINDS = ('manifest', 'console', 'hardware', 'file', 'lifecycle')
MAX_FILE = 2 * 1024 * 1024
VIEW_COLUMNS = ('sequence','producer','experiment','record_id','session','kind','observed_at','payload_json','received_at')
VIEW_SQL = "SELECT sequence,producer,experiment,record_id,session,kind,observed_at,json_remove(json_extract(document,'$.payload'),'$.content_base64') payload_json,received_at FROM run_records"
EMPTY_SQL = 'SELECT '+','.join('NULL '+key for key in VIEW_COLUMNS)+' WHERE 0'


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS run_records (
      sequence INTEGER PRIMARY KEY AUTOINCREMENT, producer TEXT NOT NULL, experiment TEXT NOT NULL,
      record_id TEXT NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL, observed_at TEXT NOT NULL,
      document TEXT NOT NULL, received_at TEXT NOT NULL, UNIQUE(producer,experiment,record_id));
      CREATE INDEX IF NOT EXISTS run_capture_scope ON run_records(experiment,kind,sequence);
      CREATE INDEX IF NOT EXISTS run_capture_session ON run_records(experiment,producer,session,sequence);
      CREATE TABLE IF NOT EXISTS experiment_labels (
        experiment TEXT PRIMARY KEY,title TEXT NOT NULL,project TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',notes TEXT NOT NULL DEFAULT '',
        pinned INTEGER NOT NULL DEFAULT 0,archived INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS experiment_selections (
        name TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL);
    ''')


def _text(value, name, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputError(name + ' must be nonempty text, at most ' + str(maximum) + ' characters')
    return value


def validate(packet):
    if not isinstance(packet, dict) or packet.get('schema') != VERSION:
        raise InputError('Expected ' + VERSION)
    _text(packet.get('producer'), 'producer'); _text(packet.get('experiment'), 'experiment')
    records = packet.get('records')
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise InputError('Supply 1–100 run records')
    for r in records:
        if not isinstance(r, dict) or r.get('kind') not in KINDS:
            raise InputError('Unknown run record kind')
        _text(r.get('id'), 'record id'); _text(r.get('session'), 'session')
        try:
            stamp = datetime.fromisoformat(r['observed_at'].replace('Z', '+00:00'))
            if stamp.utcoffset() is None: raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise InputError('observed_at requires an ISO timestamp with timezone') from None
        p = r.get('payload')
        if not isinstance(p, dict): raise InputError('payload must be an object')
        if r['kind'] == 'console':
            if p.get('stream') not in ('stdout', 'stderr') or not isinstance(p.get('text'), str) or len(p['text']) > 16384:
                raise InputError('Console chunks need stdout/stderr and at most 16384 characters')
        if r['kind'] == 'manifest':
            _text(p.get('name'), 'run name'); _text(p.get('project'), 'project')
            if not isinstance(p.get('config',{}),dict) or not isinstance(p.get('runtime',{}),dict):
                raise InputError('Configuration and runtime must be objects')
            if 'trainer_sessions' in p:
                if not isinstance(p['trainer_sessions'],list) or len(p['trainer_sessions'])>100:
                    raise InputError('trainer_sessions must be a list of at most 100 session identifiers')
                for session in p['trainer_sessions']: _text(session,'trainer session')
        if r['kind'] == 'lifecycle' and p.get('state') not in ('started','completed','failed'):
            raise InputError('Invalid session lifecycle state')
        if r['kind'] == 'hardware':
            _text(p.get('host'),'hardware host')
            if not isinstance(p.get('gpus',[]),list) or len(p.get('gpus',[]))>256:
                raise InputError('GPUs must be a list of device samples')
            if not isinstance(p.get('unavailable',[]),list) or any(not isinstance(s,str) for s in p.get('unavailable',[])):
                raise InputError('Sensor availability must be text')
            def numeric(sample,key,maximum=None):
                value=sample.get(key)
                if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0 or maximum is not None and value>maximum):
                    raise InputError('Invalid hardware sample: '+key)
            numeric(p,'cpu_percent',100)
            for key in ('memory_used_bytes','memory_total_bytes'): numeric(p,key)
            for gpu in p.get('gpus',[]):
                if not isinstance(gpu,dict): raise InputError('Invalid GPU sample')
                _text(gpu.get('uuid'),'GPU identity'); _text(gpu.get('name'),'GPU name')
                numeric(gpu,'utilization_percent',100)
                for key in ('memory_used_bytes','memory_total_bytes','temperature_c','power_watts'): numeric(gpu,key)
        if r['kind'] == 'file':
            if 'reference' in p:
                from .run_files import validate_reference
                validate_reference(p)
            else:
                _validate_embedded_file(p)
        try: encoded = json.dumps(r, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError): raise InputError('Run records must contain finite JSON values') from None
        if len(encoded) > 3 * 1024 * 1024: raise InputError('Run record is too large')
    if len(dumps(packet).encode('utf-8')) > 18 * 1024 * 1024: raise InputError('Run packet is too large')
    return packet


def _validate_embedded_file(p):
    name = _text(p.get('name'), 'file name', 240)
    if any(ord(ch) < 32 for ch in name) or '/' in name or '\\' in name or name in ('.', '..'):
        raise InputError('Use a simple file name without directories')
    try: data = base64.b64decode(p['content_base64'], validate=True)
    except (ValueError, KeyError, TypeError): raise InputError('Invalid file content') from None
    if len(data) > MAX_FILE or p.get('size') != len(data) or p.get('sha256') != hashlib.sha256(data).hexdigest():
        raise InputError('File size or checksum differs; maximum snapshot size is 2 MiB')

def receive(store, packet):
    packet = validate(packet); inserted = 0; now = datetime.now(timezone.utc).isoformat()
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in packet['records']:
            key = (packet['producer'], packet['experiment'], r['id']); document = dumps(r)
            old = c.execute('SELECT document FROM run_records WHERE producer=? AND experiment=? AND record_id=?', key).fetchone()
            if old:
                if old[0] != document: raise InputError('Run record identity already contains different content')
                continue
            c.execute('''INSERT INTO run_records(producer,experiment,record_id,session,kind,observed_at,document,received_at)
                         VALUES(?,?,?,?,?,?,?,?)''', (*key,r['session'],r['kind'],r['observed_at'],document,now))
            inserted += 1
            if r['kind'] == 'manifest':
                p = r['payload']
                # Restarts cannot overwrite organization edited in the UI.
                c.execute('INSERT OR IGNORE INTO experiment_labels(experiment,title,project,updated_at) VALUES(?,?,?,?)',
                          (packet['experiment'],p['name'],p['project'],now))
    return dict(id='run-packet-'+digest(packet), revision=0, inserted=inserted)


def timestamp_us(value):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.utcoffset() is None: raise ValueError()
        delta=stamp-datetime(1970,1,1,tzinfo=timezone.utc)
        return (delta.days*86400+delta.seconds)*1000000+delta.microseconds
    except (ValueError,TypeError,AttributeError,OverflowError):
        raise InputError('Use an ISO timestamp with timezone') from None


def capture_filters(observed_from=None, observed_to=None, as_of=None):
    bounds=[timestamp_us(v) if v is not None else None for v in (observed_from,observed_to)]
    if all(v is not None for v in bounds) and bounds[0]>bounds[1]: raise InputError('Start time must not follow end time')
    if as_of is not None and (type(as_of) is not int or as_of<0): raise InputError('Capture cutoff must be a nonnegative integer')
    return bounds


def records(store, *, experiment, kind=None, q='', after=0, limit=100, producer=None, session=None, tail=False,
            observed_from=None, observed_to=None, as_of=None):
    _text(experiment, 'experiment')
    if kind is not None and kind not in KINDS: raise InputError('Unknown capture section')
    if not isinstance(q,str) or len(q)>200 or type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=500:
        raise InputError('Use a short search, nonnegative cursor and limit 1–500')
    bounds=capture_filters(observed_from,observed_to,as_of)
    where='experiment=?'; args=[experiment]
    for column,value in (('kind',kind),('producer',producer),('session',session)):
        if value is not None:
            _text(value,column); where+=' AND '+column+'=?'; args.append(value)
    if q:
        where+=" AND instr(lower(json_remove(json_extract(document,'$.payload'),'$.content_base64')),lower(?))>0"; args.append(q)
    for comparison,value in zip(('>=','<='),bounds):
        if value is not None: where+=' AND capture_time(observed_at)'+comparison+'?';args.append(value)
    if as_of is not None:where+=' AND sequence<=?';args.append(as_of)
    with store.connect() as c:
        c.create_function('capture_time',1,timestamp_us,deterministic=True)
        c.execute('BEGIN')
        counts={r[0]:r[1] for r in c.execute('SELECT kind,count(*) FROM run_records WHERE experiment=? GROUP BY kind',(experiment,))}
        streams=[dict(r) for r in c.execute('''SELECT producer,session,
            ROW_NUMBER() OVER(ORDER BY MIN(sequence)) ordinal FROM run_records
            WHERE experiment=? GROUP BY producer,session ORDER BY MIN(sequence)''',(experiment,))]
        total=c.execute('SELECT count(*) FROM run_records WHERE '+where,args).fetchone()[0]
        rows=[dict(r) for r in c.execute('SELECT * FROM run_records WHERE '+where+' AND sequence>? ORDER BY sequence '+('DESC' if tail else 'ASC')+' LIMIT ?',args+[after,limit+1])]
    more=len(rows)>limit; rows=rows[:limit]
    if tail: rows.reverse()
    for row in rows:
        row['record']=json.loads(row.pop('document'))
        row['record']['payload'].pop('content_base64',None)
    return dict(rows=rows,counts=counts,streams=streams,total=total,more=more,next_cursor=max([after]+[r['sequence'] for r in rows]),limit=limit)


def trainer_context(store, *, experiment, producer, session, as_of=None):
    """Resolve a trainer session to process capture by exact recorded identity.

    No timestamp, step or session-prefix join. More than one declared capture
    stays an explicit choice. A cutoff freezes this capture inventory only.
    """
    for name,value in (('experiment',experiment),('producer',producer),('session',session)):_text(value,name)
    with store.connect() as c:
        c.execute('BEGIN')
        maximum=c.execute('SELECT COALESCE(MAX(sequence),0) FROM run_records').fetchone()[0]
        cutoff=maximum if as_of is None else as_of
        if type(cutoff) is not int or not 0<=cutoff<=maximum:raise InputError('Invalid run capture cutoff')
        matches={}
        if c.execute('SELECT 1 FROM run_records WHERE experiment=? AND producer=? AND session=? AND sequence<=? LIMIT 1',
                     (experiment,producer,session,cutoff)).fetchone():
            matches[session]=dict(producer=producer,session=session,basis=['same_session'],manifest_sequences=[])
        rows=c.execute('''SELECT sequence,session,kind FROM run_records
            WHERE experiment=? AND producer=? AND sequence<=? AND kind='manifest' AND (session=? OR
              EXISTS (SELECT 1 FROM json_each(document,'$.payload.trainer_sessions') WHERE value=?)
                OR json_extract(document,'$.payload.config.trainer_session')=?)
            ORDER BY sequence''',(experiment,producer,cutoff,session,session,session)).fetchall()
        for row in rows:
            item=matches.setdefault(row['session'],dict(producer=producer,session=row['session'],basis=[],manifest_sequences=[]))
            basis='same_session' if row['session']==session else 'declared_trainer_session'
            if basis not in item['basis']:item['basis'].append(basis)
            if row['kind']=='manifest':item['manifest_sequences'].append(row['sequence'])
        for item in matches.values():
            item['counts']={r[0]:r[1] for r in c.execute('''SELECT kind,count(*) FROM run_records
                WHERE experiment=? AND producer=? AND session=? AND sequence<=? GROUP BY kind''',
                (experiment,producer,item['session'],cutoff))}
    return dict(experiment=experiment,producer=producer,trainer_session=session,as_of=cutoff,
                capture_sessions=list(matches.values()))


def file_content(store, *, experiment, sequence):
    with store.connect() as c:
        row=c.execute("SELECT document FROM run_records WHERE experiment=? AND sequence=? AND kind='file'",(experiment,sequence)).fetchone()
    if row is None: raise InputError('File snapshot not found')
    p=json.loads(row[0])['payload']
    if 'reference' in p:raise InputError('External artifact: open its storage location or use Workspace.download_file()')
    return p['name'],base64.b64decode(p['content_base64'])


def organize(store, *, experiment, title=None, project=None, tags=None, notes=None, pinned=None, archived=None):
    _text(experiment,'experiment')
    if title is not None: _text(title,'title',200)
    if project is not None and (not isinstance(project,str) or len(project)>200):
        raise InputError('Project names are limited to 200 characters')
    if tags is not None and (not isinstance(tags,list) or len(tags)>20 or any(not isinstance(t,str) or not t.strip() or len(t)>60 for t in tags)):
        raise InputError('Use up to 20 short tags')
    if notes is not None and (not isinstance(notes,str) or len(notes)>10000): raise InputError('Notes are limited to 10000 characters')
    if any(v is not None and type(v) is not bool for v in (pinned,archived)): raise InputError('Pinned and archived must be booleans')
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT OR IGNORE INTO experiment_labels(experiment,title,updated_at) VALUES(?,?,?)',(experiment,experiment,datetime.now(timezone.utc).isoformat()))
        for key,value in dict(title=title,project=project,tags=dumps(tags) if tags is not None else None,notes=notes,pinned=pinned,archived=archived).items():
            if value is not None: c.execute('UPDATE experiment_labels SET '+key+'=? WHERE experiment=?',(value,experiment))
        c.execute('UPDATE experiment_labels SET updated_at=? WHERE experiment=?',(datetime.now(timezone.utc).isoformat(),experiment))
        result=dict(c.execute('SELECT * FROM experiment_labels WHERE experiment=?',(experiment,)).fetchone())
    result['tags']=json.loads(result['tags']); return result


def save_selection(store, *, name, experiments, environment=None):
    _text(name,'selection name',100)
    if not isinstance(experiments,list) or not 1<=len(experiments)<=3:
        raise InputError('Select 1–3 distinct experiments')
    for experiment in experiments: _text(experiment,'experiment')
    if len(set(experiments))!=len(experiments): raise InputError('Select distinct experiments')
    if environment is not None: _text(environment,'environment')
    value=dict(name=name,experiments=experiments,environment=environment)
    with store.connect() as c:
        c.execute('INSERT INTO experiment_selections VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET document=excluded.document,updated_at=excluded.updated_at',
                  (name,dumps(value),datetime.now(timezone.utc).isoformat()))
    return value
