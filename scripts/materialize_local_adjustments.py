"""Register saved graph composition and optional monitors, without inference."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.store import Store
from tracker import semantic_catalog,rollout_metrics,monitoring
from tracker.schema import dumps
from tracker.semantic_extraction import write

store=Store('.tracker/tracker.sqlite');run=store.get('23a6f4b7c76c919e74ae6d50',raw=True)['run']
bundle=semantic_catalog.load(run,'software-local-adjustments',store)
record=rollout_metrics.record_map(store,run,bundle);ids=[]
for metric in ('linked_adjustment_completion_fraction','linked_adjustment_unknown_fraction'):
    existing=next((m for m in monitoring.definitions(store) if m.get('metric')==metric and m['observer']==bundle['observer']['id']),None)
    if existing:ids.append(existing['id']);continue
    m=monitoring.create(store,{'name':rollout_metrics.DEFINITIONS[metric][0],'kind':'metric','metric':metric,'observer':bundle['observer']['id'],'group':'Behavior'})
    monitoring.enabled(store,m['id'],False);ids.append(m['id'])
monitoring.sync(store)
result={'inference_calls':0,'observer':bundle['observer'],'validation':bundle['validation']['adjustment_graph'],
    'observation':record['linked_adjustment_observation'],'optional_monitor_ids':ids}
write('research/local-adjustments-v2-2026-10-08/software/materialized.json',result)
print(dumps({'inference_calls':0,'observer':bundle['observer'],'metrics':{k:record['metrics'][k] for k in ('linked_adjustment_completion_fraction','linked_adjustment_unknown_fraction')}}))
