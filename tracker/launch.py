"""Portable launch files: data configuration, never shell commands or plugins."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path, PureWindowsPath
import tempfile

from .adapters import FORMATS
from .schema import InputError

SCHEMA = 'rilldex-launch/1'
LEGACY_SCHEMA = 'jev-launch/1'
SOURCE_FIELDS = {'root','producer','mode','format','metadata','pattern','interval','snapshot_state'}


def read(path):
    path = Path(path).expanduser().resolve()
    if path.stat().st_size > 128 * 1024:raise InputError('Launch file exceeds 128 KiB')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict) or set(value)-{'schema','database','source','port','create_output'} or value.get('schema') not in (SCHEMA, LEGACY_SCHEMA):
        raise InputError('Use a rilldex-launch/1 file with database, source and optional port/create_output')
    source = value.get('source')
    if not isinstance(source,dict) or set(source)-SOURCE_FIELDS:
        raise InputError('Launch source contains unsupported settings')
    def text(v,name):
        if not isinstance(v,str) or not v.strip() or len(v)>4096 or any(ord(c)<32 for c in v):
            raise InputError(name+' must be nonempty single-line text')
        return v
    def local(v,name):
        v=text(v,name)
        if '://' in v:raise InputError(name+' must be a local filesystem path')
        if os.name!='nt' and PureWindowsPath(v).drive:raise InputError(name+' is a Windows path; update it for this host')
        expanded=Path(v).expanduser()
        return str((expanded if expanded.is_absolute() else path.parent/expanded).resolve())
    database=local(value.get('database'),'database')
    root=text(source.get('root'),'source.root')
    if '://' in root:
        from .cloud_watch import source as cloud_source
        cloud_source(root)
    else:root=local(root,'source.root')
    producer=text(source.get('producer'),'source.producer')
    if len(producer)>240:raise InputError('Producer identity must be at most 240 characters')
    mode=source.get('mode','native');fmt=source.get('format','auto')
    if not isinstance(mode,str) or not isinstance(fmt,str) or mode not in {'native','exports','snapshots'} or fmt not in FORMATS:raise InputError('Unsupported source mode or format')
    meta=source.get('metadata',{})
    if not isinstance(meta,dict):raise InputError('Source metadata must be an object')
    if mode!='native' and not meta.get('experiment'):raise InputError('JSON/JSONL capture needs metadata.experiment')
    interval=source.get('interval',2)
    if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not .2<=interval<=300:raise InputError('Interval must be 0.2–300 seconds')
    if 'pattern' in source:
        pattern=source['pattern'];suffix='.jsonl' if mode=='exports' else '.json'
        if mode=='native' or not isinstance(pattern,str) or not pattern.endswith(suffix) or any(c in pattern for c in '/\\\r\n'):
            raise InputError('Pattern must be a filename glob for the selected JSON/JSONL mode')
    if 'snapshot_state' in source and (mode!='snapshots' or not isinstance(source['snapshot_state'],str) or source['snapshot_state'] not in {'in_progress','complete'}):
        raise InputError('snapshot_state requires snapshots mode and in_progress or complete')
    port=value.get('port',8765)
    if type(port) is not int or not 0<=port<=65535:raise InputError('Port must be 0–65535')
    create=value.get('create_output',False)
    if type(create) is not bool or create and '://' in root:raise InputError('create_output is only available for a local directory')
    return {**value,'database':database,'source':{**source,'root':root,'producer':producer,'mode':mode,'format':fmt,'metadata':meta,'interval':interval},'port':port,'create_output':create}


def execute(args, cli):
    config=read(args.path);source=config['source'];port=config['port'] if args.port is None else args.port
    if type(port) is not int or not 0<=port<=65535:raise InputError('Port must be 0–65535')
    from .startup import doctor
    # Headless checks/replay remain usable while this workspace UI is running.
    health=doctor(config['database'],0 if args.once or args.check else port)
    if not health['ready']:raise InputError('; '.join(c['name']+': '+c['detail'] for c in health['checks'] if not c['ok']))
    root=source['root']
    if config['create_output'] and not Path(root).exists() and Path(config['database']).is_file():
        with closing(sqlite3.connect(Path(config['database']).as_uri()+'?mode=ro',uri=True)) as saved:
            tables={r[0] for r in saved.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            known=any(saved.execute('SELECT 1 FROM '+table+' WHERE producer=? LIMIT 1',(source['producer'],)).fetchone()
                      for table in ('data_connections','rollout_revisions') if table in tables)
        if known:raise InputError('Previously connected output directory is missing. Restore its mount/path or pause and relocate the saved connection; no empty replacement was created.')
    if args.check:
        with tempfile.TemporaryDirectory(prefix='jev-launch-') as tmp:
            from .connections import preview
            from .store import Store
            root=source['root'];pending='://' not in root and not Path(root).exists() and config['create_output']
            if pending:
                empty=Path(tmp)/'empty-output';empty.mkdir();sample={**source,'root':str(empty)}
            else:sample=source
            report=preview(Store(Path(tmp)/'check.sqlite'),sample)
            report['config']['root']=root
            ready=not any(r['status']=='deferred' for r in report['samples']) and not report.get('cloud',{}).get('errors')
            print(json.dumps({'ready':bool(ready),'database':config['database'],'source':report,'startup':health,
                'waiting_for_output':pending,'note':'No workspace or source writes. Missing pre-training output is created only when launched.'},ensure_ascii=False,indent=2))
            return 0 if ready else 1
    if config['create_output']:Path(source['root']).mkdir(parents=True,exist_ok=True)
    # Route through the existing CLI so locks, cursors and replay semantics stay identical.
    # Keep metadata in memory; a killed collector must not leave launch temp files.
    argv=['--db',config['database']]
    if args.once:argv+=['watch',source['root'],'--once','--max-files','10000']
    else:argv+=['start','--watch',source['root'],'--port',str(port)]+(['--open'] if args.open else [])
    for key in ('producer','mode','format','pattern','interval','snapshot_state'):
        if key in source:argv+=['--'+key.replace('_','-'),str(source[key])]
    cli(argv,_metadata=source['metadata'])
    return 0
