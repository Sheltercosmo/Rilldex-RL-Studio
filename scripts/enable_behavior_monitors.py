"""Materialize the saved public examples and enable behavior monitors, no inference."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.store import Store
from tracker import monitoring, rollout_metrics
from tracker.semantic_catalog import load


if __name__=='__main__':
    store=Store('.tracker/tracker.sqlite')
    rollout_metrics.report(store)  # Append metric schema extensions, preserving originals.
    records=[]
    for rid,observer in [('d8c0e38f633a068fbc7aed74','airline-operation-outcomes'),('23a6f4b7c76c919e74ae6d50','software-plan-evidence')]:
        run=store.get(rid,raw=True)['run'];bundle=load(run,observer,store)
        records.append(rollout_metrics.record_map(store,run,bundle))
    specs=[('Feedback assessed before next action · experimental','feedback_assessment_fraction','feedback-assessment-827bdfcbcd78070b08cb',True),
        ('Changed retries completed · experimental','changed_retry_completion_fraction','airline-operation-outcomes',True),
        ('Plan stages attempted','plan_stage_attempt_fraction','software-plan-evidence',True),
        ('Unchanged retry payloads · experimental','unchanged_retry_fraction','airline-operation-outcomes',False),
        ('Unknown changed-retry outcomes','changed_retry_unknown_fraction','airline-operation-outcomes',False),
        ('Unknown feedback assessments','feedback_assessment_unknown_fraction','feedback-assessment-827bdfcbcd78070b08cb',False)]
    ids=[]
    for name,metric,observer,on in specs:
        existing=next((d for d in monitoring.definitions(store) if d.get('metric')==metric and d['observer']==observer),None)
        if existing:ids.append(existing['id']);continue
        d=monitoring.create(store,{'name':name,'kind':'metric','metric':metric,'observer':observer,'group':'Behavior'})
        if not on:monitoring.enabled(store,d['id'],False)
        ids.append(d['id'])
    monitoring.sync(store)
    selected=[m for m in monitoring.snapshot(store)['monitors'] if m['id'] in ids]
    out=Path('research/behavior-monitoring-review-2026-10-08');out.mkdir(parents=True,exist_ok=True)
    receipt={'schema':'behavior-monitor-activation/1','inference_calls':0,
        'monitors':[{k:m.get(k) for k in ('id','name','metric','observer','enabled','coverage','unplaced_points','aggregation')} for m in selected],
        'retry_observation':records[0].get('retry_observation')}
    (out/'monitor-validation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{'name':m['name'],'coverage':m.get('coverage'),'points':m.get('unplaced_points')} for m in selected],indent=2))
