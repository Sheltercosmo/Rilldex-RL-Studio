"""Reproduce a bounded source review using pinned local public-trace exports.

No inference calls, authored traces or synthetic labels masquerading as a holdout.
Run: python scripts/audit_revision_flow.py --output .tracker/revision-flow-audit.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker import graph_store, work_hierarchy
from tracker.schema import digest


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit(source_root, reference):
    rows = []
    for domain, expected in reference['sources'].items():
        run = read(source_root / domain / 'baseline.json')['run']
        if digest(run) != expected['run_hash']:
            raise ValueError(f'{domain}: source differs from the reviewed snapshot')
        bundle = read(source_root / domain / 'projected.json')
        hierarchy = work_hierarchy.build(graph_store.build(run, bundle))
        nodes = {n['id']: n for n in hierarchy['nodes']}
        def event(uid):
            refs = nodes[uid]['evidence']
            return refs[0]['event_id'] if refs else None
        episodes = hierarchy['revision_episodes']['episodes']
        predictions = {event(e['declaration_id']) for e in episodes}
        positives, negatives = set(expected['positive']), set(expected['negative'])
        reviewed = positives | negatives | set(expected['ambiguous'])
        prose = {e['id'] for e in run['events'] if e['actor']=='agent' and e['kind']!='action' and e['text'].strip()}
        if reviewed != prose:
            raise ValueError(f'{domain}: review does not cover all nonempty prose records')
        chain_results=[]
        for chain in expected['chains']:
            matched = [e for e in episodes if event(e['declaration_id']) == chain['declaration'] and event(e['previous_id']) == chain['previous']]
            e = matched[0] if len(matched) == 1 else None
            implementations = [event(uid) for s in e['stages'] if s['label']=='Implementation' for uid in s['node_ids']] if e else []
            outcomes = [(event(r['action_id']), r['outcome']) for r in e['results']] if e else []
            chain_results.append(dict(**chain, implementation_found=chain['implementation'] in implementations,
                retry_and_outcome_found=(chain['retry'], chain['outcome']) in outcomes))
        rows.append(dict(domain=domain, source_hash=digest(run), bundle_hash=digest(bundle),
            reviewed=len(positives|negatives), ambiguous=len(expected['ambiguous']),
            true_positive=len(predictions&positives), false_positive=len(predictions&negatives),
            false_negative=len(positives-predictions), misses=[dict(event=e,note=expected['miss_notes'].get(e,'')) for e in sorted(positives-predictions)],
            chains=chain_results, task_quality_check_pairs=sum(len(e['impact']['checks']) for e in episodes)))
    total={key:sum(r[key] for r in rows) for key in ['reviewed','ambiguous','true_positive','false_positive','false_negative','task_quality_check_pairs']}
    chains=[c for r in rows for c in r['chains']]
    total.update(reviewed_chains=len(chains), implementation_links=sum(c['implementation_found'] for c in chains), retry_results=sum(c['retry_and_outcome_found'] for c in chains))
    return dict(schema='revision-flow-audit/1',reviewer=reference['reviewer'],population=reference['population'],totals=total,sources=rows,
        limits='Development source review after inspecting predictions, not independent accuracy. Three trajectories and 12 positive prose decisions cannot establish general precision or recall. No task-quality capture: consequences are operation outcomes only. No automatic assumption/context/reversion inference was evaluated.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('research/attempt-revisions-v4-2026-10-08'))
    parser.add_argument('--output',type=Path,default=Path('.tracker/revision-flow-audit.json'))
    args=parser.parse_args()
    result=audit(args.root,read(Path('tests/fixtures/revision_flow_review.json')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result['totals']))
