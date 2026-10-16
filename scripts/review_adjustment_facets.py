"""Save source review, usage and a reusable registered observer. No inference."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import adjustment_graph,semantic_catalog,rollout_metrics
from tracker.store import Store
from tracker.schema import digest,dumps
from tracker.semantic_extraction import read,write

root=Path('research/adjustment-facets-2026-10-08');work=Path('research/work-items-complete-2026-10-08/software')
run=read(work/'source.json');doc=read(work/'base-map.json');observed=read(root/'software/local-adjustments.json')
units={u['source']['event_id']:u['id'] for u in doc['units'] if u['kind']=='semantic'}
notes=[
 {'unit_ids':[units['e101']],'text':'All ten local work items retain their reports_finished declaration. The adjustment-content facet marks them as ordinary completion claims, not new undertakings or independently verified successes. In particular, the SVM implementation/training claims no longer receive a competing ordinary-work temporal label.'},
 {'unit_ids':[units['e86']],'text':'Known scope error in item w2: retrying conversion after checking the image path selects adjustment_content. The cited check is not itself a correction, and the repeated converter operation is unchanged. Raw selection is retained. This item has no selected action correspondence in the saved graph and does not contribute a retry episode.'},
 {'unit_ids':[units['e95']],'text':'Known scope error in item w1: retrying conversion with the already updated image path selects adjustment_content and creates an attempts_local_adjustment link to e96. The preceding e92/e93 artifact repair should carry the change; this contribution resumes conversion. The raw edge is preserved for review. No new measured episode results here because the prior result is not an established failure.'},
 {'unit_ids':[],'text':'The content facet is not a validated replacement for upstream declaration/source checking. A frozen fixture that supplies a present commitment against an explicitly completed past migration was not rejected. The original declaration is preserved even when wrong; contradictions require review.'},
]
review={'review_kind':'development_source_review_not_independent_reference','observation_hash':digest(observed),'notes':notes}
path=root/'software/source-review.json'
if path.exists() and read(path)!=review:raise RuntimeError('Saved source review changed')
write(path,review)
usage=[]
for stage in ('controls','regressions','software'):
    saved=[read(p) for p in (root/stage/'decisions').glob('*.json')]
    usage.append({'stage':stage,'successful_requests':len(saved),
        'provider_usage':{k:sum(d['response'].get('usage',{}).get(k,0) for d in saved) for k in ('input_tokens','output_tokens')}})
store=Store('.tracker/tracker.sqlite')
registered=adjustment_graph.register(store,work,root/'software','Work declarations + correction content · experimental')
bundle=semantic_catalog.load(run,registered['observer'],store);record=rollout_metrics.record_map(store,run,bundle)
result={'registration':registered,'inference_calls':0,'luna_calls':0,'usage':usage,
    'metrics':bundle['document']['adjustment_graph']['metrics'],
    'graph':bundle['document']['adjustment_graph'],'independent_accuracy':False,
    'limits':'Usage covers successful new facet requests only; excludes upstream work and earlier protocols. Review notes preserve known errors. No new monitor is enabled.'}
write(root/'review.json',result)
print(dumps({'observer':registered['observer'],'url':registered['url'],'usage':usage,
    'metrics':{k:{f:v[f] for f in ('numerator','denominator')} for k,v in result['metrics'].items()}}))
