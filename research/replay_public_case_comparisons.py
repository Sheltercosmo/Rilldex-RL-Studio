"""Replay pinned public SWE-bench attempts; no model or benchmark execution.

Run from the checkout, or with an installed Rilldex Python and absolute paths.
Cache expects the source manifest and trajectories described in the evidence note.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from rilldex import Workspace
from tracker.adapters import normalize
from tracker import case_comparisons, findings_report, graph_store
from tracker.schema import digest
from tracker.store import Store


def prepare(cache, manifest_path):
    from urllib.request import urlopen
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));cache.mkdir(parents=True,exist_ok=True)
    for source in manifest['sources']+manifest['reports']:
        path=cache/source['submission']/(source['task_id']+'.traj.json') if 'task_id' in source else cache/(source['submission']+'.results.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            with urlopen(source['url'],timeout=60) as response:data=response.read()
            assert hashlib.sha256(data).hexdigest()==source['sha256'],source['url']
            path.write_bytes(data)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256'],str(path)
    (cache/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (cache/'selection.json').write_text(json.dumps(manifest['selection'],indent=2),encoding='utf-8')


def replay(cache, database):
    manifest = json.loads((cache/'manifest.json').read_text(encoding='utf-8'))
    store = Store(database); workspace = Workspace(database)
    evidence = []; names = []; by_run = {}
    selector = dict(label='SWE-bench published resolution', producer='SWE-bench/experiments', purpose='independent_check')
    for source in manifest['sources']:
        submission, task = source['submission'], source['task_id']
        if submission not in names: names.append(submission)
        path = cache/submission/(task+'.traj.json'); data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == source['sha256']
        document = json.loads(data)
        assert document['instance_id'] == task
        report_path = cache/(submission+'.results.json')
        report_bytes = report_path.read_bytes(); result = json.loads(report_bytes)[task]
        expected_report=next(r for r in manifest['reports'] if r['submission']==submission)
        assert hashlib.sha256(report_bytes).hexdigest()==expected_report['sha256']
        assert type(result['resolved']) is bool
        run = normalize(document, meta=dict(experiment=submission, environment='SWE-bench Verified',
            split='verified', source_uri=source['url'], benchmark_submission=submission))[0]
        # Raw native records and native parsed dispatch/result counts are retained.
        assert run['raw'] == document and 'verified_success' not in run['outcome']
        assert run['metadata']['model'] == document['info']['config']['model']['model_name']
        expected_actions = sum(len(m.get('extra',{}).get('actions',[])) for m in document['messages'])
        actions = [e for e in run['events'] if e['kind']=='action']
        returns = [e for e in run['events'] if e['kind']=='feedback' and e.get('source_call_id')]
        assert len(actions) == expected_actions
        native_returns=[m for m in document['messages'] if m.get('role')=='tool' or m.get('type')=='function_call_output'
            or m.get('role')=='user' and any(k in m.get('extra',{}) for k in ('returncode','raw_output'))]
        assert len(returns)==len(native_returns)
        action_ids = {e['call_id'] for e in actions}
        assert all(e['source_call_id'] in action_ids for e in returns)
        # Every native response with an explicit call ID must bind that exact ID.
        native_calls = {e.get('native_call_id'):e['call_id'] for e in actions if e.get('native_call_id')}
        for event in returns:
            parts=event['source_pointer'].split('/');message=document['messages'][int(parts[2])]
            native_id=message.get('call_id') or message.get('tool_call_id')
            if native_id: assert event['source_call_id']==native_calls[native_id]
        store.add([run]); by_run[(submission,task)] = run
        result_url = f"https://github.com/SWE-bench/experiments/blob/{manifest['github_commit']}/evaluation/verified/{submission}/per_instance_details.json"
        receipt = workspace.record_evaluation(dict(schema='evaluation-receipt/1', **selector,
            performed_at=None, run_id=run['id'], source_hash=digest(run), execution='completed',
            verdict='passed' if result['resolved'] else 'failed', score=None,
            inputs=dict(task=dict(label=task,sha256=digest(task)), criterion=None,
                        artifact=dict(label='Submitted patch',sha256=digest(document['info']['submission'])),
                        evaluator=None, environment=None, output_boundary=None),
            summary='Publisher-reported resolved flag. Tests were not rerun; evaluator time and implementation are not supplied.',
            evidence=[dict(label='Published result',text=json.dumps(dict(task_id=task, result=result, url=result_url,
                document_sha256=hashlib.sha256(report_bytes).hexdigest()),indent=2))]))
        evidence.append(dict(task_id=task,submission=submission,run_id=run['id'],model=run['metadata']['model'],
            actions=len(actions),linked_returns=len(returns),events=len(run['events']),reported_resolved=result['resolved'],receipt=receipt['id']))
    def capture():
        return workspace.compare_rollouts(reference=dict(experiment=names[0],evaluation=selector),
            selected=dict(experiment=names[1],evaluation=selector),title='Public SWE-bench attempts: model comparison')
    saved=capture(); listing=case_comparisons.listing(store,saved['id'])
    expected=Counter()
    for task in sorted({r['task_id'] for r in evidence}):
        a,b=[next(e for e in evidence if e['submission']==n and e['task_id']==task) for n in names]
        label='unchanged' if a['reported_resolved']==b['reported_resolved'] else 'improved' if b['reported_resolved'] else 'regressed'
        expected[label]+=1
        pair=case_comparisons.pair(store,saved['id'],a['run_id'],b['run_id'])
        assert pair['status']==label
        for side in ('reference','selected'):
            graph=graph_store.read(store,pair[side]['graph']['id'])
            assert graph['run_id']==pair[side]['run']['id']
            assert pair[side]['run']['outcome_evaluation']['records'][0]['performed_at'] is None
    assert listing['counts']==dict(expected)
    # An exact repeated import and report delivery add no trials or reports.
    before=sum(len(workspace.evaluations(e['run_id'])['receipts']) for e in evidence)
    for run in by_run.values(): store.add([run])
    for e in evidence:
        for receipt in workspace.evaluations(e['run_id'])['receipts']:
            repeated=workspace.record_evaluation({k:v for k,v in receipt.items() if k!='id'})
            assert repeated['id']==receipt['id']
    assert sum(len(workspace.evaluations(e['run_id'])['receipts']) for e in evidence)==before
    assert case_comparisons.listing(Store(database),saved['id'])==listing
    report_path=cache/('public-comparison-'+saved['id'].removeprefix('investigation-')+'.html')
    findings_report.export_findings(database,saved['id'],report_path)
    output=dict(investigation_id=saved['id'],report_path=str(report_path),counts=listing['counts'],sources=evidence,evaluations=before,
        population_note=json.loads((cache/'selection.json').read_text(encoding='utf-8')),model_calls=0,
        boundary='Purposive evaluation sample, not RL checkpoints, prevalence, semantic ground truth or a causal comparison.')
    (cache/'replay.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--db',type=Path,required=True)
    p.add_argument('--download',action='store_true',help='Fetch and verify missing public artifacts')
    p.add_argument('--manifest',type=Path,default=Path(__file__).parent/'public-case-comparison-2026-10-21/manifest.json')
    a=p.parse_args()
    if a.download:prepare(a.cache,a.manifest)
    result=replay(a.cache,a.db)
    print(json.dumps({k:v for k,v in result.items() if k not in ('sources','population_note')}))
