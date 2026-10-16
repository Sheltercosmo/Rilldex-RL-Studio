"""Native paired-dump import: check first, optionally queue durable delivery."""
import json
from pathlib import Path
from .schema import InputError
from .slime_debug import read, prepare, enqueue, COMMIT


def configure(commands):
    p=commands.add_parser('slime-dump',help='Check paired Slime debug dumps and optionally queue them for import; no model calls')
    p.add_argument('rollout',help='Native rollout .pt or primitive JSON')
    p.add_argument('--train',required=True,help='Matching format-2 train .pt or primitive JSON')
    p.add_argument('--experiment',required=True)
    p.add_argument('--session',required=True,help='Stable native job/branch identity, preserved across retry')
    p.add_argument('--producer',required=True)
    p.add_argument('--tokenizer',required=True,help='Actual common tokenizer revision/identity; no downloads')
    p.add_argument('--upstream-commit',required=True,help='Installed native revision (tested: '+COMMIT+')')
    p.add_argument('--output',required=True,help='Directory for the validated report and native evidence')
    p.add_argument('--outbox',help='Optional durable queue; delivery uses the existing outbox send command')
    p.add_argument('--endpoint',default='http://127.0.0.1:8765')


def execute(args):
    result=prepare(read(args.rollout),read(args.train),producer=args.producer,experiment=args.experiment,
        session=args.session,tokenizer_id=args.tokenizer,upstream_commit=args.upstream_commit)
    root=Path(args.output)
    # Preserve old evidence when a source or import definition changes.
    report=json.dumps(result['report'],ensure_ascii=False,indent=2)+'\n'
    if (root/'report.json').exists() and (root/'report.json').read_text(encoding='utf-8')!=report:
        raise InputError('This output directory contains a different report; choose a new evidence directory')
    root.mkdir(parents=True,exist_ok=True)
    for name,value in [('report',result['report']),('sources',result['snapshots']),('training-records',result['packets']),('native-training-dump',result['native_training_dump'])]:
        (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    status={'report':str((root/'report.json').resolve()),'join':result['report']['join'],'model_calls':0,'queued':False}
    if args.outbox:
        from .capture import Outbox
        outbox=Outbox(args.outbox,producer=args.producer,endpoint=args.endpoint)
        receipts=enqueue(outbox,result)
        status.update(queued=True,queue_entries=len(receipts),reused=sum(r['duplicate'] for r in receipts))
    print(json.dumps(status,indent=2))
