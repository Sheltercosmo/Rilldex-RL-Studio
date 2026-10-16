"""Audit and register the correction-effect/reference pass; no inference."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import adjustment_graph,semantic_catalog,rollout_metrics,local_adjustments
from tracker.store import Store
from tracker.schema import digest,dumps
from tracker.semantic_extraction import read,write

root=Path('research/adjustment-effects-2026-10-08');work=Path('research/work-items-complete-2026-10-08/software')
run=read(work/'source.json');doc=read(work/'base-map.json');observed=read(root/'software/local-adjustments.json')
unit_ids={u['source']['event_id']:u['id'] for u in doc['units'] if u['kind']=='semantic'}
notes=[
 {'unit_ids':[unit_ids['e86'],unit_ids['e95']],'text':'Operation/input distinction: checking a path before a repeat is not a correction; converting a document with an already edited path uses a separate correction. These two items no longer create correction-attempt links. Source wording and original declarations are preserved.'},
 {'unit_ids':[unit_ids['e74'],unit_ids['e80']],'text':'Using a separate correction is relative to the described dependent operation, not a claim that its prerequisite has already happened at this statement. These contributions plan installation before conversion. Reference retrieval uses only earlier dispatched corrective work; it does not link a planned prerequisite to a future action or force a match to an unrelated earlier package installation.'},
 {'unit_ids':[unit_ids['e77'],unit_ids['e83'],unit_ids['e95']],'text':'The correction reference is selected from earlier graph-retrieved preparations: Pandoc installation, TeX installation and the image-path edit respectively. This is a source-attributed reference with stored action/preparation witnesses, not verification of the correction, causation or recovered task success.'},
 {'unit_ids':[],'text':'An authored negative-attribution control still fails: a falsely attributed backup-restoration item is treated as correction content despite a source quote and denial. This layer is not independently validated and cannot replace faithful upstream work extraction. Raw choices are retained.'},
]
review={'review_kind':'development_source_review_not_independent_reference','observation_hash':digest(observed),'notes':notes}
p=root/'software/source-review.json'
if p.exists() and read(p)!=review:raise RuntimeError('Saved source review changed')
write(p,review)
usage=[]
for stage in ('controls','contrasts','regressions','software','references'):
    saved=[read(p) for p in (root/stage/'decisions').glob('*.json')]
    row={'stage':stage,'successful_requests':len(saved),'provider_usage':{k:sum(d['response'].get('usage',{}).get(k,0) for d in saved) for k in ('input_tokens','output_tokens')}}
    if (root/stage/'review.json').exists():
        checks=read(root/stage/'review.json')['rows'];row.update(matching_cases=sum(c['matches'] for c in checks),cases=len(checks))
    usage.append(row)
store=Store('.tracker/tracker.sqlite');registered=adjustment_graph.register(store,work,root/'software',
    'Corrections and return to work · experimental',reference_directory=root/'references')
bundle=semantic_catalog.load(run,registered['observer'],store);rollout_metrics.record_map(store,run,bundle)
refs=bundle['document']['adjustment_references'];uids={u['id']:u['source']['event_id'] for u in doc['units']}
result={'registration':registered,'inference_calls':0,'luna_calls':0,'usage':usage,
    'metrics':bundle['document']['adjustment_graph']['metrics'],
    'reference_summary':[{k:r[k] for k in ('type','work_text','correction_work')}|{'from_event':uids[r['from']],'to_event':uids[r['to']]} for r in refs['relations']],
    'known_prior_error_removed':not any(r['type']=='attempts_local_adjustment' and uids.get(r['from'])=='e96' for r in bundle['document']['relations']),
    'limits':'Source development pass, not independent accuracy. Successful new-request receipts exclude upstream costs and earlier experiments. No new monitor is enabled.'}
write(root/'review.json',result)
print(dumps({'url':registered['url'],'usage':usage,'references':result['reference_summary'],'old_error_removed':result['known_prior_error_removed']}))
