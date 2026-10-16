"""Reproduce incremental-stage receipts; no inference or token-price assumptions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.semantic_extraction import read,write
from tracker.schema import digest,dumps

ROOT=Path('research/local-adjustments-v2-2026-10-08')
def usage(directory):
    rows=[read(p) for p in sorted((directory/'decisions').glob('*.json'))]
    keys={k for row in rows for k in row['response'].get('usage',{})}
    return {'successful_requests':len(rows),'provider_usage':{k:sum(r['response'].get('usage',{}).get(k,0) for r in rows) for k in sorted(keys)}}

old=next(v for v in read('research/attempt-revisions-v4-2026-10-08/usage-review.json')['latest_pass'] if v['scope']=='software')
new=usage(ROOT/'software');controls=read(ROOT/'controls/review.json');corrected=read(ROOT/'corrected-controls/review.json')
result=read(ROOT/'software/local-adjustments.json');reference=read('research/local-adjustments-2026-10-08/software/local-adjustments.json')
before={(o['unit_id'],i['item_id']):i for o in reference['observations'] for i in o['items']}
changes=[{'unit_id':o['unit_id'],'item_id':i['item_id'],'work':i['work'],'before':before[o['unit_id'],i['item_id']]['selection'],'after':i['selection']}
    for o in result['observations'] for i in o['items'] if before[o['unit_id'],i['item_id']]['selection']!=i['selection']]
report={'schema':'local-adjustment-stage-cost/1','observation_hash':digest(result),
    'software':new,'earlier_pairwise_software':old,
    'incremental_input_reduction_fraction':1-new['provider_usage']['input_tokens']/old['provider_usage']['input_tokens'],
    'controls':{**usage(ROOT/'controls'),'matching_cases':sum(r['matches'] for r in controls['rows']),'cases':len(controls['rows'])},
    'corrected_control_inputs':{**usage(ROOT/'corrected-controls'),'matching_cases':sum(r['matches'] for r in corrected['rows']),'cases':len(corrected['rows'])},
    'local_selections_changed_from_v1':changes,'luna_calls':0,'composition_inference_calls':0,
    'limits':['Incremental stages over one reused development trace, not total pipeline cost or a matched accuracy benchmark.',
        'Upstream extraction, authored candidate generation, work history, action correspondences, identity and outcomes are excluded.',
        'Earlier and local passes differ in context and measured scope; local requests use an explicitly limited visible prefix.',
        'Recorded successful requests only. Earlier experiments, failures, storage and serving are excluded. No confirmed Jev price is assumed.',
        'Controls are authored expectations, not independent semantic accuracy. Original and corrected inputs remain separate.']}
write(ROOT/'usage-review.json',report)
print(dumps({k:report[k] for k in ['software','incremental_input_reduction_fraction','controls','corrected_control_inputs','luna_calls']}))
