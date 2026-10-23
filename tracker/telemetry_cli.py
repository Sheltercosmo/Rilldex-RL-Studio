"""Batch/repeated import of native trainer JSONL or Transformers log_history."""
import json
from pathlib import Path
from .schema import InputError
from .store import Store
from .trainer_telemetry import TrainerTelemetry, snapshot, PROFILES, TRANSFORMERS_PROFILES


def configure(commands):
    p=commands.add_parser('telemetry',help='Import native trainer logs or read their measured series')
    s=p.add_subparsers(dest='telemetry_command',required=True)
    show=s.add_parser('show');show.add_argument('--experiment');show.add_argument('--limit',type=int,default=1000)
    query=s.add_parser('query',help='Full-run summaries and spike-preserving chart points')
    export=s.add_parser('export',help='Stream original telemetry packets for an exact step interval')
    for parser in (query,export):
        for name in ('experiment','environment','clock','producer','session'):parser.add_argument('--'+name)
        parser.add_argument('--session-mode',choices=('all','latest'),default='all')
        parser.add_argument('--from-step',type=json.loads,dest='start');parser.add_argument('--to-step',type=json.loads,dest='end')
        parser.add_argument('--as-of',type=int,help='Freeze at the source cutoff returned by query')
    query.add_argument('--max-points',type=int,default=240)
    query.add_argument('--half-life',type=int,choices=(0,10,50,100),default=0)
    query.add_argument('--series',action='append',default=[],dest='series_ids')
    export.add_argument('destination',help='New JSONL file; native records can be replayed through the telemetry API')
    load=s.add_parser('import',help='Read JSONL logs or a trainer_state.json log_history; replay is idempotent')
    load.add_argument('path')
    for name in ('experiment','producer','framework-version','objective','session'):
        load.add_argument('--'+name,required=True)
    load.add_argument('--framework',choices=tuple(PROFILES),required=True)
    load.add_argument('--clock',default='learner_update')
    load.add_argument('--split',choices=('train','evaluation'),default='train')
    load.add_argument('--population',default='trainer logged batch')
    load.add_argument('--environment',default='unspecified')
    load.add_argument('--definitions',help='JSON mapping of custom native keys to full metric definitions')


def run(args):
    store=Store(args.db)
    if args.telemetry_command=='show':return snapshot(store,experiment=args.experiment,limit=args.limit)
    if args.telemetry_command in {'query','export'}:
        from . import telemetry_queries as tq
        options={k:getattr(args,k) for k in ('experiment','environment','clock','start','end','as_of')}
        options.update({k:getattr(args,k) for k in ('producer','session','session_mode') if getattr(args,k,None) is not None})
        if args.telemetry_command=='query':
            return tq.query(store,**options,max_points=args.max_points,half_life=args.half_life,series_ids=args.series_ids)
        cutoff,records=tq.export_records(store,**options);count=0
        with Path(args.destination).open('x',encoding='utf-8',newline='\n') as stream:
            for packet in records:
                stream.write(json.dumps(packet,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n');count+=len(packet['records'])
        return dict(path=str(Path(args.destination).resolve()),records=count,as_of=cutoff,range=[args.start,args.end])
    path=Path(args.path)
    if path.stat().st_size>64*1024*1024:raise InputError('Split log imports into files of at most 64 MiB')
    raw=path.read_text(encoding='utf-8-sig')
    try:
        value=json.loads(raw)
        rows=value.get('log_history',[value]) if isinstance(value,dict) else value
    except ValueError:
        lines=raw.splitlines(keepends=True)
        # A live writer's incomplete final line is left for the next import.
        rows=[json.loads(line) for line in lines if line.strip() and line.endswith(('\n','\r'))]
        if lines and lines[-1].strip() and not lines[-1].endswith(('\n','\r')):
            try:rows.append(json.loads(lines[-1]))
            except ValueError:pass
    if not isinstance(rows,list):raise InputError('Expected JSONL records or trainer log_history')
    collector=TrainerTelemetry(store,**{k:getattr(args,k) for k in ('experiment','producer','framework','framework_version','objective','session','clock','population','environment')},
        definitions=json.loads(Path(args.definitions).read_text(encoding='utf-8')) if args.definitions else None)
    inserted=0
    for row in rows:
        if not isinstance(row,dict):raise InputError('Each log must be an object')
        step=row.get('step',row.get('global_step',row.get('_step')))
        logs=row.get('metrics',row)
        if not isinstance(logs,dict):raise InputError('metrics must be an object')
        references=row.get('training_uses')
        if references is not None:
            if 'metrics' not in row or row.get('split') not in ('train','evaluation'):
                raise InputError('Linked logs require metrics and an explicit train/evaluation split')
            partitions=[(row['split'],logs)]
        elif args.framework in TRANSFORMERS_PROFILES and args.split=='train':
            partitions=[('train',{k:v for k,v in logs.items() if not k.startswith('eval_')}),
                        ('evaluation',{k:v for k,v in logs.items() if k.startswith('eval_')})]
        else:partitions=[(args.split,logs)]
        for split,values in partitions:
            if values:inserted+=collector.log(values,step=step,split=split,training_uses=references).get('inserted',0)
    return dict(imported=inserted,read_logs=len(rows),experiment=args.experiment)
