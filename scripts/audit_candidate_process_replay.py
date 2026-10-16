"""Retained real proposals through actual subprocesses, then full HTTP replay.

No fresh inference. Stage-specific historical producer names are preserved so
the selector receives exactly the original requests. Generation is prepared
before the continuous worker, whose file handoff consumes the resulting cache.
"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

if not sys.flags.isolated:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.candidate_worker import CommandCandidates
from tracker import candidate_process
from tracker.schema import digest
from tracker.semantic_budget import ExecutionBudget, summary
from tracker.semantic_extraction import read, write


def run(source, output):
    if output.exists():
        raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True)
    package_path=Path(candidate_process.__file__).resolve()
    if sys.flags.isolated and 'site-packages' not in package_path.parts:
        raise ValueError('Isolated audit must use an installed package')
    retained=source/'work-phases-routed'
    samples=[read(source/'sources'/f'{row["id"]}.json') for row in read(source/'sample.json')['runs']]
    # This fixture reads exact saved data only. It cannot invoke a model.
    script=output/'replay_command.py'
    script.write_text('''import hashlib,json,sys
from pathlib import Path
p=json.load(sys.stdin); root=Path(sys.argv[1]); flag=Path(sys.argv[2])
canonical=json.dumps(p['request'],sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
assert hashlib.sha256(canonical).hexdigest()==p['request_hash']
if not flag.exists():
 flag.touch(); sys.stdout.buffer.write(b'\\xff'); raise SystemExit(0)
saved=json.loads((root/'requests'/(p['request_hash']+'.json')).read_text(encoding='utf-8'))
assert saved==p['request']
sys.stdout.buffer.write((root/'responses'/(p['request_hash']+'.json')).read_bytes())
''',encoding='utf-8')
    command=[sys.executable,'-X','utf8','-I',str(script),str(retained/'candidates'),str(output/'fault-injected')]
    budget=ExecutionBudget(output/'budget',1,{'candidate_requests':200,'jev_requests':0,'input_bytes':20_000_000})
    counts=Counter(); failures=[]; receipts=output/'candidates'; before={}
    for path in sorted((retained/'candidates/responses').glob('*.json')):
        expected=read(path); req=read(retained/'candidates/requests'/path.name)
        assert path.stem==digest(req)
        before[path.name]=digest(expected)
        ref=req['source']
        matching=[r for r in samples if any(e['id']==ref['event_id'] and e['text'][ref['start']:ref['end']]==ref['text'] for e in r['events'])]
        if not matching:
            raise AssertionError('Retained candidate source is absent')
        provider=CommandCandidates(receipts,command,expected['producer'],execution_budget=budget)
        try:
            provider.generate(matching[0],req)
        except candidate_process.CandidateProcessError as exc:
            assert not failures and exc.details['category']=='invalid_utf8'
            failures.append(exc.details)
            provider.generate(matching[0],req)  # Explicit, separately reserved retry.
        counts[req.get('stage','partition')]+=1
    for name, saved in before.items():
        assert digest(read(retained/'candidates/responses'/name))==saved
    usage=summary(output/'budget')
    assert budget.used['candidate_requests']==sum(counts.values())+len(failures)
    spec=importlib.util.spec_from_file_location('http_replay',Path(__file__).with_name('audit_semantic_watch_replay.py'))
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    pipeline=replay.run(source,output/'pipeline',candidate_responses=receipts/'responses')
    report={'schema':'candidate-process-replay/1','status':'passed','stages':dict(counts),
            'subprocess_invocations':budget.used['candidate_requests'],'faults':failures,
            'usage':usage,'pipeline':pipeline,
            'runtime':{'isolated':bool(sys.flags.isolated),'package_path':str(package_path),'execution_policy':candidate_process.POLICY},
            'limits':['Historical proposals and selector responses; zero fresh model calls.',
                      'Subprocess preparation precedes the continuous worker; this is not adaptive generation.',
                      'One exposed development task; no independent semantic accuracy or production throughput claim.']}
    write(output/'report.json',report)
    return {k:report[k] for k in ('status','stages','subprocess_invocations','pipeline','limits')}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('research/training-semantic-pilot-2026-10-08'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.source.resolve(),args.output.resolve()),indent=2))
