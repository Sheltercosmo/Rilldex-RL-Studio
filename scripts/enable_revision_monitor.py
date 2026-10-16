"""Publish audited development observations, without model calls."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.store import Store
from tracker import monitoring,rollout_metrics
from tracker.semantic_catalog import load
from tracker.semantic_extraction import read,write

store=Store('.tracker/tracker.sqlite');rollout_metrics.report(store);records=[]
for domain,rid in [('software','23a6f4b7c76c919e74ae6d50'),('airline','d8c0e38f633a068fbc7aed74'),('retail','9f5b00fa0c3418a66d561730')]:
    run=store.get(rid,raw=True)['run'];bundle=load(run,domain+'-attempt-revisions',store)
    record=rollout_metrics.record_map(store,run,bundle)
    records.append({'domain':domain,'run_id':rid,'observer':bundle['observer']['id'],
        'validation':bundle['validation']['attempt_revisions'],'metrics':record['revision_observation']['metrics'],
        'episodes':record['revision_observation']['episodes'],'relation_count':len(bundle['document']['relations'])})
ids=[]
for metric,on in [('enacted_revision_completion_fraction',True),('enacted_revision_unknown_fraction',False)]:
    existing=next((m for m in monitoring.definitions(store) if m.get('metric')==metric and m['observer']=='software-attempt-revisions'),None)
    if existing:ids.append(existing['id']);continue
    definition=monitoring.create(store,{'name':rollout_metrics.DEFINITIONS[metric][0],'kind':'metric',
        'metric':metric,'observer':'software-attempt-revisions','group':'Behavior'})
    if not on:monitoring.enabled(store,definition['id'],False)
    ids.append(definition['id'])
monitoring.sync(store)
snapshot=monitoring.snapshot(store)
receipt={'schema':'revision-monitor-activation/1','inference_calls':0,'records':records,
    'monitors':[{k:m.get(k) for k in ('id','name','metric','observer','enabled','coverage','unplaced_points','aggregation')} for m in snapshot['monitors'] if m['id'] in ids]}
write('research/attempt-revisions-v4-2026-10-08/monitor-validation.json',receipt)
print([(r['domain'],[(k,v['numerator'],v['denominator']) for k,v in r['metrics'].items()]) for r in records])
