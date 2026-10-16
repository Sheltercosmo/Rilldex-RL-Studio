"""Reconcile stored opportunities, SQL graph links and model receipts read-only."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import feedback_assessment as fa
from tracker.schema import digest
from tracker.semantic_extraction import read


def main():
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--db',default='.tracker/tracker.sqlite');p.add_argument('--output')
    args=p.parse_args();root=Path(args.directory);c=sqlite3.connect(args.db);rows=[];usage=Counter()
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'result.json').exists():continue
        run=read(folder/'input.json')['run']
        # Browser fixtures live beside real results, in explicitly named folders.
        # CLI-produced real observations are always under their exact run ID.
        if folder.name != run['id']:continue
        result=read(folder/'result.json');fa.audit(run,result,folder)
        matches=c.execute("SELECT id,document FROM rollout_measurements WHERE run_id=? AND observer=?",(run['id'],result['protocol']['id'])).fetchall()
        bound=[(key,json.loads(raw)) for key,raw in matches if json.loads(raw).get('annotation_hash')==digest(result)]
        assert len(bound)==1,'Expected exactly one registered immutable measurement'
        key,record=bound[0];graph_id=record['graph_id'];observations=result['observations'];events={e['id']:e for e in run['events']}
        sql=c.execute('''SELECT e.source,e.target,json_extract(e.document,'$.properties.request_hash') request_hash
            FROM graph_edges e JOIN graph_nodes s ON s.graph_id=e.graph_id AND s.id=e.source
            JOIN graph_nodes t ON t.graph_id=e.graph_id AND t.id=e.target
            WHERE e.graph_id=? AND e.type='assesses_response_group' AND s.kind='event' AND t.kind='event'
              AND s.trajectory_id=t.trajectory_id AND s.event_index>t.event_index''',(graph_id,)).fetchall()
        expected={("event:"+o['assessment_event_id'],"event:"+rid,o['request_hash']) for o in observations if o['value']==1 for rid in o['response_event_ids']}
        assert set(sql)==expected,'Stored SQL relationships differ from selected response groups'
        n=sum(o['value']==1 for o in observations);d=sum(o['value'] is not None for o in observations);u=len(observations)-d
        metric=record['metrics']['feedback_assessment_fraction']
        assert (metric['numerator'],metric['denominator'],metric['value'])==(n,d,n/d if d else None)
        assert record['metrics']['feedback_assessment_unknown_fraction']['value']==(u/len(observations) if observations else None)
        cases=[]
        for o in observations:
            ids=[o['action_event_id'],*o['response_event_ids'],*o['expression_event_ids']]
            assert all(i in events for i in ids)
            assert len({events[i]['trajectory_id'] for i in ids})==1
            if o['value']==0:assert o['closed_window'] and o['complete_readable_evidence']
            if o['assessment_event_id']:assert o['assessment_event_id'] in o['expression_event_ids']
            cases.append({**o,'action':events[o['action_event_id']]['text'],
                          'agent_expressions':[events[i]['text'] for i in o['expression_event_ids']]})
        for f in (folder/'decisions').glob('*.json'):usage.update(read(f)['response'].get('usage') or {})
        rows.append({'run_id':run['id'],'adapter':run['adapter'],'counts':result['counts'],'measurement_id':key,
                     'graph_id':graph_id,'sql_relationship_rows':len(sql),'cases':cases})
    report={'scope':f'{len(rows)} selected public development/transfer traces, no training coordinates. Not a representative training sample.',
            'checks':'Exact raw-argmax replay; independently summed opportunities; physical SQL edge/source-order reconciliation.',
            'semantic_accuracy':'Not independently measured. Source review is implementation-assistant review, not ground truth.',
            'rollouts':rows,'provider_reported_usage':dict(usage),'failed_request_usage':'Unavailable; not included.'}
    if args.output:Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({**{k:v for k,v in report.items() if k!='rollouts'},'rollouts':[{k:v for k,v in r.items() if k!='cases'} for r in rows]},indent=2))


if __name__=='__main__':main()
