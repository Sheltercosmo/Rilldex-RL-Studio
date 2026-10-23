"""Compare explicit captured configuration snapshots, never merged run state."""
import json
from datetime import datetime, timezone
from .schema import InputError
from .experiment_details import _execution_scope
from .experiment_management import _experiments


def _flat(value, path=''):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from _flat(child, path+'/'+key.replace('~','~0').replace('/','~1'))
    else:
        yield path, value


def _cell(value):
    kind = ('null' if value is None else 'boolean' if isinstance(value,bool) else
            'number' if isinstance(value,(int,float)) else 'string' if isinstance(value,str) else
            'array' if isinstance(value,list) else 'object')
    return dict(present=True, type=kind, value=value)


def _manifest(row):
    doc=json.loads(row['document'])
    return dict(id=json.dumps(['manifest',row['sequence']]), kind='Run configuration',
                producer=row['producer'], session=row['session'], received_at=row['received_at'],
                recorded_at=doc['observed_at'], config=doc['payload']['config'])


def _execution(row):
    doc=json.loads(row['document'])
    return dict(id=json.dumps(['execution',row['experiment'],row['producer'],row['record_id'],row['revision']]),
                kind='Operation · '+row['kind'].replace('_',' '), producer=row['producer'],
                session=doc.get('context',{}).get('session'), received_at=row['received_at'],
                record_id=row['record_id'], revision=row['revision'], timing=doc.get('timing'),
                config=doc['configuration'])


def _inventory(c, experiment, environment):
    manifests="FROM run_records WHERE experiment=? AND kind='manifest' AND json_type(document,'$.payload.config')='object'"
    operations=_execution_scope()+" AND json_type(e.document,'$.configuration')='object'"
    args=[experiment,environment,environment]
    total=c.execute('SELECT count(*) '+manifests,[experiment]).fetchone()[0]+c.execute('SELECT count(*) '+operations,args).fetchone()[0]
    # Each source family retains its own recent inventory; a stream of operation
    # settings cannot crowd out process snapshots. Explicit older picks still resolve.
    choices=[_manifest(r) for r in c.execute('SELECT * '+manifests+' ORDER BY sequence DESC LIMIT 50',[experiment])]
    choices += [_execution(r) for r in c.execute('SELECT e.* '+operations+' ORDER BY received_at DESC,producer,record_id LIMIT 50',args)]
    return choices,total


def _resolve(c, experiment, identifier, environment):
    try:
        parts=json.loads(identifier)
        if not isinstance(parts,list):raise ValueError()
        if len(parts)==2 and parts[0]=='manifest' and type(parts[1]) is int:
            row=c.execute("SELECT * FROM run_records WHERE experiment=? AND sequence=? AND kind='manifest' AND json_type(document,'$.payload.config')='object'",[experiment,parts[1]]).fetchone()
            if row:return _manifest(row)
        if len(parts)==5 and parts[0]=='execution' and parts[1]==experiment and all(isinstance(p,str) for p in parts[2:4]) and type(parts[4]) is int:
            # A saved pick addresses its original revision, even after a new revision arrives.
            row=c.execute("""SELECT * FROM execution_records WHERE experiment=? AND producer=? AND record_id=? AND revision=?
                AND json_type(document,'$.configuration')='object'
                AND (? IS NULL OR json_extract(document,'$.context.environment')=? OR
                  (json_extract(document,'$.context.environment') IS NULL AND kind IN ('learner_update','weight_sync','configuration')))""",
                [experiment,*parts[2:],environment,environment]).fetchone()
            if row:return _execution(row)
    except (ValueError,TypeError):pass
    raise InputError('Selected configuration is unavailable in this run and environment')


def compare(store, *, experiments, sources=None, environment=None, q='', differences_only=True, limit=100, offset=0):
    _experiments(experiments)
    if not 2<=len(experiments)<=3:raise InputError('Select 2–3 runs to compare settings')
    if environment is not None and (not isinstance(environment,str) or not environment.strip()):raise InputError('Use an exact environment name')
    if sources is None:sources={}
    if (not isinstance(sources,dict) or set(sources)-set(experiments) or
        any(v is not None and (not isinstance(v,str) or len(v)>2000) for v in sources.values())):
        raise InputError('Use configuration identifiers returned for these runs')
    if not isinstance(q,str) or len(q)>200 or type(differences_only) is not bool:raise InputError('Use a short field search and boolean differences_only')
    if type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or offset<0:raise InputError('Use limit 1–200 and a nonnegative offset')
    runs=[];flat=[]
    with store.connect() as c:
        if not c.in_transaction:c.execute('BEGIN')
        for experiment in experiments:
            choices,total=_inventory(c,experiment,environment)
            chosen=(_resolve(c,experiment,sources[experiment],environment) if sources.get(experiment) is not None else
                    None if experiment in sources else choices[0] if choices else None)
            label=c.execute('SELECT title FROM experiment_labels WHERE experiment=?',[experiment]).fetchone()
            runs.append(dict(experiment=experiment,title=label[0] if label else experiment,
                selected=chosen, choices=[{k:v for k,v in r.items() if k!='config'} for r in choices], source_count=total,
                trainer_logs=c.execute("SELECT count(*) FROM trainer_telemetry WHERE experiment=? AND (? IS NULL OR json_extract(document,'$.environment')=?)",[experiment,environment,environment]).fetchone()[0]))
            flat.append(dict(_flat(chosen['config'])) if chosen else {})
    rows=[]
    for path in sorted(set().union(*(f.keys() for f in flat))):
        cells=[_cell(f[path]) if path in f else dict(present=False) for f in flat]
        signatures=[json.dumps(v,sort_keys=True,ensure_ascii=False) for v in cells]
        rows.append(dict(path=path,cells=cells,different=len(set(signatures))>1))
    differences=sum(r['different'] for r in rows);fields=len(rows)
    rows=[r for r in rows if (not differences_only or r['different']) and
          (q.casefold() in (r['path']+' '+' '.join(json.dumps(c['value'],ensure_ascii=False) for c in r['cells'] if c['present'])).casefold())]
    return dict(schema='configuration-comparison/1',runs=runs,rows=rows[offset:offset+limit],total=len(rows),
                fields=fields,differences=differences,limit=limit,offset=offset,environment=environment,
                captured_at=datetime.now(timezone.utc).isoformat())
