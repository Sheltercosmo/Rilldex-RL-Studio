"""Resumable experimental full-run extraction using global source boundaries.

Jev chooses boundaries, activities and content in order. Only content proposals
use an external file queue. No dashboard inference or automatic publication.
"""
import argparse
from collections import Counter
import getpass
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient
from tracker.schema import digest, InputError
from tracker.semantic_boundaries import GlobalSourceCandidates, VERSION
from tracker.semantic_extraction import Pipeline, audit_result, read, write, checked_span
from tracker.semantic_workspace import exclusive
from tracker.store import Store

CONTEXT={'schema':'readable-context/2','recent_events':4,'max_event_chars':2000,'extra_ranges':[]}


def pending_manifest(root, result):
    """Queue current dependencies, including invalid responses needing repair.

    A response file's existence does not mean the unit is annotated. Conversely,
    old unanswered files must not requeue superseded activity/boundary choices.
    """
    root=Path(root);requests=[];reviews=[];seen=set()
    for item in [*result['windows'],*result['units']]:
        if item['status'] in {'partitioned','selected'}:continue
        key=(item.get('activity_reading_request') if item['status']=='needs_activity_readings' else
             item.get('candidate_request') if item['status'] in
             {'needs_candidates','needs_candidate_repair','needs_content_repair'} else item.get('repair_request'))
        identity={'id':item['id'],'status':item['status'],'event_id':item['source']['event_id']}
        if not key:
            reviews.append({**identity,'reason':item.get('reason',item['status'])})
            continue
        if key in seen:continue
        seen.add(key)
        path=root/'candidates/requests'/f'{key}.json';req=read(path)
        if digest(req)!=key:raise InputError('Pending candidate request changed')
        entry={**identity,'request_hash':key,'request_file':str(path.resolve()),
               'stage':req.get('stage','partition')}
        response=root/'candidates/responses'/f'{key}.json'
        if response.exists():entry['response_file']=str(response.resolve())
        if item.get('candidate_rejection'):
            receipt=root/'candidates/rejections'/f'{item['candidate_rejection']}.json'
            rejected=read(receipt)
            if digest(rejected)!=item['candidate_rejection'] or rejected['request_hash']!=key:
                raise InputError('Pending candidate rejection changed')
            entry.update(rejection_file=str(receipt.resolve()),validation_error=rejected['validation_error'])
        if item.get('content_choice'):
            entry.update(selection=item['content_choice'],decision_hash=item['content_request'])
        requests.append(entry)
    return {'schema':'global-source-content-queue/2','run_id':result['run_id'],
            'extraction_hash':digest(result),'requests':requests,'pending_reviews':reviews,
            'rule':'Only current dependencies. Repair an invalid or rejected response without overwriting its original receipt. Source-bound proposals only; Jev selects later.'}


def run(args):
    with exclusive(args.directory) as root:
        path=root/'input.json'
        if path.exists():
            inputs=read(path)
            if inputs['run']['id']!=args.run_id or inputs['protocol']!=VERSION or inputs['context_policy']!=CONTEXT:
                raise InputError('Experimental extraction source/configuration changed')
            source=inputs['run']
            if digest(source)!=inputs['source_hash']:raise InputError('Frozen source changed')
        else:
            source=Store(args.db).get(args.run_id,raw=True)['run']
            inputs={'run':source,'source_hash':digest(source),'protocol':VERSION,'context_policy':CONTEXT}
            write(path,inputs);write(root/'runs'/f'{source["id"]}.json',source)
        repair_path=root/'activity-repairs.json'
        repairs=read(repair_path)['sources'] if repair_path.exists() else []
        for ref in repairs:checked_span(source,ref)
        candidates=GlobalSourceCandidates(root/'candidates',CONTEXT,activity_reading_sources=repairs)
        client=JevClient();calls=0;prompted=False
        def transport(req):
            nonlocal calls,prompted
            if calls>=args.max_new_calls:raise InputError('Call budget reached; rerun to resume.')
            if args.prompt_key and not prompted:
                os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted=True
            calls+=1;response=client.transport(req)
            write(root/'wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
            return response
        engine=Pipeline(root,candidates,transport)
        result=engine.run(source,include_user=True)
        validation=audit_result(source,result,root)
        write(root/'audit.json',validation)
        manifest=pending_manifest(root,result)
        write(root/'candidates/manifest.json',manifest)
        print({'run_id':source['id'],'status':result['status'],'new_calls':engine.calls,
               'windows':dict(Counter(w['status'] for w in result['windows'])),
               'units':dict(Counter(u['status'] for u in result['units'])),
               'activities':dict(Counter(u['activity'] for u in result['units'])),
               'candidate_requests':len(manifest['requests']),
               'pending_reviews':len(manifest['pending_reviews']),'audit':validation})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--run-id',required=True)
    p.add_argument('--db',default='.tracker/tracker.sqlite');p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--max-new-calls',type=int,default=60);run(p.parse_args())
