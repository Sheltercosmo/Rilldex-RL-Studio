"""Reconcile a saved measurement; independently join direct feedback assessments.

Run from the workspace: python scripts/audit_monitor_evidence.py VALUE_ID --output PATH
This reads existing data only. SQL agreement is not independent semantic accuracy.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.store import Store
from tracker.monitor_evidence import read
from tracker.graph_queries import PRESETS


def audit(store,identifier):
    receipt=read(store,identifier);e=receipt['explanation'];query=receipt['monitor'].get('requirement')
    result={'value_id':identifier,'run_id':receipt['run']['id'],'graph_id':receipt['graph']['id'] if receipt['graph'] else None,
            'monitor':receipt['monitor']['name'],'value':e['value'],'numerator':e['numerator'],'denominator':e['denominator'],
            'not_established':e.get('not_established'),'integrity':receipt['integrity'],'independent_sql':None}
    if query==PRESETS['assessment_of_inspection_feedback']:
        params={'graph':receipt['graph']['id'],'window':query['within_units']}
        with store.connect() as c:
            denominator=c.execute("SELECT count(*) FROM graph_nodes WHERE graph_id=:graph AND kind='unit' AND activity='inspect' AND event_index IS NOT NULL AND json_extract(document,'$.properties.actor')='agent'",params).fetchone()[0]
            rows=c.execute('''WITH agent AS (
              SELECT id,activity,trajectory_id,event_index,
                coalesce(json_extract(document,'$.properties.source.start'),0) start,
                coalesce(json_extract(document,'$.properties.source.end'),0) end,
                row_number() OVER(PARTITION BY trajectory_id ORDER BY event_index,coalesce(json_extract(document,'$.properties.source.start'),0),id) ordinal
              FROM graph_nodes WHERE graph_id=:graph AND kind='unit' AND event_index IS NOT NULL
                AND json_extract(document,'$.properties.actor')='agent')
              SELECT DISTINCT anchor.id inspection,later.id assessment,feedback.id feedback,assessment.id assessment_edge,binding.id binding_edge
              FROM agent anchor JOIN agent later ON later.trajectory_id=anchor.trajectory_id
                AND later.ordinal>anchor.ordinal AND later.ordinal<=anchor.ordinal+:window
              JOIN graph_edges assessment ON assessment.graph_id=:graph AND assessment.source=later.id AND assessment.type='assesses'
              JOIN graph_nodes feedback ON feedback.graph_id=:graph AND feedback.id=assessment.target
              JOIN graph_edges binding ON binding.graph_id=:graph AND binding.source=feedback.id AND binding.target=anchor.id AND binding.type='feedback_for'
              LEFT JOIN graph_nodes assessment_cutoff ON assessment_cutoff.graph_id=:graph AND assessment_cutoff.kind='event'
                AND json_extract(assessment_cutoff.document,'$.properties.id')=json_extract(assessment.document,'$.properties.cutoff.event_id')
              LEFT JOIN graph_nodes binding_cutoff ON binding_cutoff.graph_id=:graph AND binding_cutoff.kind='event'
                AND json_extract(binding_cutoff.document,'$.properties.id')=json_extract(binding.document,'$.properties.cutoff.event_id')
              WHERE anchor.activity='inspect' AND feedback.kind!='unresolved_reference' AND feedback.trajectory_id=later.trajectory_id
                AND (feedback.event_index<later.event_index OR (feedback.event_index=later.event_index AND json_extract(feedback.document,'$.properties.source.end')<=later.start))
                AND (json_extract(assessment.document,'$.properties.cutoff') IS NULL OR assessment_cutoff.event_index<later.event_index OR (assessment_cutoff.event_index=later.event_index AND json_extract(assessment.document,'$.properties.cutoff.end')<=later.end))
                AND (json_extract(binding.document,'$.properties.cutoff') IS NULL OR binding_cutoff.event_index<later.event_index OR (binding_cutoff.event_index=later.event_index AND json_extract(binding.document,'$.properties.cutoff.end')<=later.end))
              ORDER BY anchor.id,later.id''',params).fetchall()
        n=len({r['inspection'] for r in rows})
        if (n,denominator)!=(e['numerator'],e['denominator']):raise ValueError('SQL membership disagrees with saved measurement')
        expected={(case['anchor'],match['source'],match['target']) for case in e['cases'] for match in case['matches']}
        if expected!={(r['inspection'],r['assessment'],r['feedback']) for r in rows}:raise ValueError('SQL witness membership disagrees with saved measurement')
        by_id={n['id']:n for n in receipt['graph']['nodes']}
        result['independent_sql']={'numerator':n,'denominator':denominator,'witnesses':[]}
        for row in rows:
            item=dict(row);item['excerpts']={role:by_id[row[role]]['properties'].get('source',{}).get('text','')[:1200] for role in ('inspection','assessment','feedback')}
            result['independent_sql']['witnesses'].append(item)
    result['limit']='Checks saved identities, arithmetic and the supported SQL membership rule; does not adjudicate semantic extraction accuracy.'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('value_id');p.add_argument('--database',default='.tracker/tracker.sqlite');p.add_argument('--output');args=p.parse_args()
    result=audit(Store(args.database),args.value_id);content=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:Path(args.output).write_text(content,encoding='utf-8')
    print(content)
