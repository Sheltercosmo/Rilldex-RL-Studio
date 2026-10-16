"""Evaluate complete source-block groupings with frozen development references."""
import argparse
from collections import Counter
import getpass
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient
from tracker.schema import digest
from tracker.semantic_extraction import Pipeline, read, write, windows
from tracker.semantic_boundaries import VERSION, proposals, selection_request, materialize

CONTEXT={'schema':'readable-context/2','recent_events':4,'max_event_chars':2000,'extra_ranges':[]}


def initialize(root):
    baseline=read('research/nongenerative-candidates-2026-10-08/baseline.json')
    prior=read('research/nongenerative-candidates-2026-10-08/selection-readable/results.json')
    sources={s['domain']:read(Path(s['reference_path']).parent.parent/'runs'/f'{s["run_id"]}.json') for s in baseline['sources']}
    seen={(c['domain'],c['event_id']) for c in prior['cases']};cases=[]
    for row in baseline['boundaries']:
        if row['kind']=='action_dispatch':continue
        run=sources[row['domain']]
        w=next(w for w in windows(run,include_user=True) if w['event_id']==row['event_id'])
        cases.append({'domain':row['domain'],'window':w,'reference':row['reference'],
                      'exposure':'previous_selection_test' if (row['domain'],row['event_id']) in seen else 'remaining_development_region'})
    value={'schema':VERSION,'baseline_hash':digest(baseline),'sources':sources,'context_policy':CONTEXT,'cases':cases,
           'reference_status':'Existing assistant-proposed development maps; not independent gold.'}
    path=root/'input.json'
    if path.exists() and read(path)!=value:raise ValueError('Frozen global-boundary input changed')
    if not path.exists():write(path,value)
    return value


def execute(root,inputs,transport):
    engine=Pipeline(root,None,transport);rows=[]
    for case in inputs['cases']:
        run=inputs['sources'][case['domain']];w=case['window'];candidate=proposals(run,w)
        write(root/'candidates'/f'{digest(candidate)}.json',candidate)
        options=[[[s['start'],s['end']] for s in p['units']] for p in candidate['partitions']]
        if candidate['coverage']=='partition_budget_exceeded':selected={'status':'partition_budget_exceeded','units':[]};key=None;winner=None
        else:
            req=selection_request(run,candidate,inputs['context_policy'])
            answers,key=engine.decide(req);winner=answers['choice']['value'];selected=materialize(candidate,winner)
        spans=[[s['start'],s['end']] for s in selected['units']]
        row={'domain':case['domain'],'event_id':w['event_id'],'exposure':case['exposure'],
             'source':w,'candidate_hash':digest(candidate),'candidate_count':len(options),
             'reference_available':case['reference'] in options,'reference':case['reference'],
             'status':selected['status'],'selected':spans,'winner':winner,'decision':key,
             'exact_development_agreement':spans==case['reference']}
        rows.append(row)
        write(root/'results.json',{'schema':VERSION,'input_hash':digest(inputs),'cases':rows})
        print(case['domain'],w['event_id'],len(options),'options',selected['status'],spans,'reference',case['reference'],flush=True)
    summary={'regions':len(rows),'new_calls':engine.calls,'candidate_coverage':sum(r['reference_available'] for r in rows),
             'exact_development_agreement':sum(r['exact_development_agreement'] for r in rows),
             'statuses':dict(Counter(r['status'] for r in rows)),
             'exposures':{label:{'regions':sum(r['exposure']==label for r in rows),
                                'agreement':sum(r['exposure']==label and r['exact_development_agreement'] for r in rows)}
                          for label in sorted({r['exposure'] for r in rows})}}
    write(root/'summary.json',summary);print(summary)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--max-new-calls',type=int,default=65);args=p.parse_args();inputs=initialize(args.directory)
    client=JevClient();calls=[0];prompted=[False]
    def transport(req):
        if calls[0]>=args.max_new_calls:raise RuntimeError('Budget reached; resume the same command.')
        if args.prompt_key and not prompted[0]:
            os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted[0]=True
        calls[0]+=1;response=client.transport(req)
        write(args.directory/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
        return response
    execute(args.directory,inputs,transport)
