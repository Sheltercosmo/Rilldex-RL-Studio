"""Reproducible payload-size planning estimate; not provider token telemetry.

Uses saved public proposal requests and their current responses. No model calls.
The 3/4/5 characters-per-token scenarios are assumptions, not a tokenizer.
"""
import argparse
import hashlib
import json
from pathlib import Path


def estimate(root):
    candidate=root/'candidates';rows=[]
    for p in sorted((candidate/'requests').glob('*.json')):
        q=candidate/'responses'/p.name
        request=json.loads(p.read_text(encoding='utf-8'))
        rows.append({'request':p.name,'stage':request.get('stage'),
            'request_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
            'input_chars':len(p.read_text(encoding='utf-8')),
            'output_chars':len(q.read_text(encoding='utf-8')) if q.exists() else None,
            'prefix_chars':len(json.dumps(request.get('prefix',[]),ensure_ascii=False)),
            'response_sha256':hashlib.sha256(q.read_bytes()).hexdigest() if q.exists() else None})
    ic=sum(r['input_chars'] for r in rows);oc=sum(r['output_chars'] or 0 for r in rows)
    jev=[]
    for p in (root/'wire').rglob('*.json'):
        d=json.loads(p.read_text(encoding='utf-8'));usage=d.get('response',{}).get('usage')
        if usage:jev.append(usage)
    base=[]
    for chars in (5,4,3):
        inp,out=ic/chars,oc/chars
        usd=(inp*.10+out*.50)/1_000_000
        base.append({'characters_per_token':chars,'input_tokens_estimate':round(inp),
            'visible_output_tokens_estimate':round(out),'usd_per_example':round(usd,6),
            'usd_by_rollouts':{str(n):round(n*usd,2) for n in (10000,100000,1000000)}})
    mid=base[1]['usd_per_example']
    return {'schema':'proposer-budget-estimate/1','model':'gpt-6-luna','as_of':'2026-10-08',
        'pricing_source':'https://developers.openai.com/api/docs/models/gpt-6-luna',
        'rates_usd_per_million':{'uncached_input':.10,'output':.50,'cached_input':.01},
        'example':{'rollouts':1,'agent_units':19,'user_units':2,'unique_proposal_requests':len(rows),
            'request_characters':ic,'response_characters':oc,'request_rows':rows},
        'assumptions':['Independent stateless API requests with the saved JSON as input and current saved response JSON as output.',
            '3–5 characters per token is a sensitivity assumption, not an actual tokenizer or billing interval.',
            'No cache discount, batch discount or regional premium. Each request is assumed below 272K input tokens.',
            'Existing subagent session overhead, hidden reasoning, actual retries, repair prompts, Jev, storage and serving are excluded.',
            'Current final responses include repairs; this does not reconstruct every response originally generated.'],
        'payload_scenarios':base,
        'extra_reasoning_scenarios':[{'tokens_per_request':t,'additional_usd_per_million_rollouts':round(t*len(rows)*.5,2)} for t in (1000,5000,10000)],
        'scale_examples':{'one_million_rollouts_50_agent_units_linear_proxy_usd':round(mid*1000000*50/19,2),
            'one_million_rollouts_3_percent_proposed_usd':round(mid*1000000*.03,2),
            'steps_1000_prompts_128_samples_8':{'rollouts':1024000,'payload_usd':round(mid*1024000,2)}},
        'jev_usage_receipts':{'count':len(jev),'field_totals':{k:sum(v.get(k,0) for v in jev if isinstance(v.get(k),(int,float))) for k in sorted({k for v in jev for k in v if isinstance(v[k],(int,float))})}},
        'actual_luna_billed_tokens':None,'actual_luna_billed_usd':None}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path('research/global-source-transfer-2026-10-08/nebius'))
    parser.add_argument('--output',type=Path,default=Path('research/behavior-monitoring-review-2026-10-08/cost-estimate.json'));args=parser.parse_args()
    result=estimate(args.root);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'example','assumptions'}},indent=2))
