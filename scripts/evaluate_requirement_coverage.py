"""Source-coverage-state ablation with no production change or global filter.

Compare a bounded producer-coverage block alone versus that exact block plus
the already tested lifecycle clarification. All original choices remain.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_requirement_lifecycle import LIFECYCLE_RULE
from tracker import requirement_diagnostics as detector
from tracker.jev import JevClient,validate_answers
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

FIXTURES=Path(__file__).resolve().parents[1]/'tests/fixtures'
ARMS=('coverage_state','coverage_state_lifecycle')
NOTICE_CHARS=1000


def coverage_state(source):
    """Whitelist declared coverage facts; never infer an omitted action."""
    block=dict(schema='recorded-source-coverage/1',completeness_scope='full_captured_record',
        complete_recorded_text=source['complete_recorded_text'],action_coverage=source['action_coverage'])
    notice=source.get('provenance',{}).get('excerpt_notice')
    if isinstance(notice,str):
        block.update(declared_excerpt_notice=notice[:NOTICE_CHARS],declared_excerpt_notice_characters=len(notice),
            declared_excerpt_notice_truncated=len(notice)>NOTICE_CHARS,
            excerpt_notice_source='source.provenance.excerpt_notice')
    return block


def variant(source,original,arm):
    if arm not in ARMS:raise InputError('Unknown source-coverage arm')
    request=deepcopy(original);request['state']['source_coverage']=coverage_state(source)
    if arm=='coverage_state_lifecycle':
        for question in request['questions'].values():question['instructions']+='\n'+LIFECYCLE_RULE
    if len(dumps(request))>120000:raise InputError('Source-coverage request exceeds bound')
    return request


def prepared():
    review=read(FIXTURES/'requirement-lifecycle-controls.json')
    refs={c['id']:c['reference'] for c in review['cases']}
    if digest(refs)!=review['reference_hash']:raise InputError('Reviewed references changed')
    cases=[]
    for case in review['cases']:
        source=case['source']
        if digest(source)!=case['source_hash']:raise InputError('Reviewed source changed')
        terms={t['id']:t for t in detector.criteria(source,version=detector.CONFLICT_VERSION)}
        requests=list(detector.requests(source,[terms[key] for key in case['selected_requirement_ids']],version=detector.CONFLICT_VERSION))
        if requests!=case['requests']:raise InputError('Reviewed original request changed')
        cases.append(dict(case_id=case['id'],source=source,requests=requests,reference=case['reference'],target_events=None))
    # Only completeness changes: visible task, observations and contradiction
    # remain byte-identical to the already reviewed positive source.
    positive=deepcopy(next(c for c in cases if c['case_id']=='contradicted-completion-claim'))
    positive['case_id']='visible-contradiction-incomplete-record'
    positive['source']['complete_recorded_text']=False
    positive['reference']={**positive['reference'],'expected_complete_recorded_text':False,
        'completeness_contrast':'Same recorded contradiction and positive reference; only source completeness changes from true to false. Frozen before calls.'}
    selected=list(positive['requests'][0]['state']['requirements'].values())
    positive['requests']=list(detector.requests(positive['source'],selected,version=detector.CONFLICT_VERSION))
    cases.append(positive)
    panel=Path('outputs/requirement-prior-corrected-panel');manifest=read(panel/'manifest.json')
    public=next(c for c in manifest['cases'] if c['case_id']=='authorized-submission')
    source=read(panel/'authorized-submission/source.json');reference=read(panel/'authorized-submission/reference.json')
    if digest(source)!=public['source_hash'] or digest(reference)!=public['reference_hash']:raise InputError('Corrected public source/reference changed')
    terms=read(panel/'authorized-submission/historical-selected-requirements.json')
    requests=[r for r in detector.requests(source,terms,version=detector.CONFLICT_VERSION) if r['state']['page'] in public['witness_pages']]
    if [digest(r) for r in requests]!=public['historical_selection_request_hashes']:raise InputError('Corrected public request changed')
    cases.append(dict(case_id='authorized-submission',source=source,requests=requests,reference=reference,target_events=public['target_events']))
    return dict(review_fixture_hash=digest(review),review_reference_hash=review['reference_hash'],public_panel_hash=digest(manifest)),cases


def evaluate(directory='outputs/requirement-source-coverage-review',*,live=False,client=None,max_calls=12):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    context,cases=prepared();root=Path(directory);refs={c['case_id']:c['reference'] for c in cases};rows=[]
    for case in cases:
        for arm in ARMS:
            rows.append({**case,'arm':arm,'requests':[variant(case['source'],r,arm) for r in case['requests']]})
    manifest=dict(schema='requirement-source-coverage-inputs/1',**context,protocol=detector.protocol(detector.CONFLICT_VERSION),
        reference_hash=digest(refs),notice_chars=NOTICE_CHARS,lifecycle_rule=LIFECYCLE_RULE,
        rows=[dict(case_id=r['case_id'],arm=r['arm'],source_hash=digest(r['source']),
                   request_hashes=[digest(q) for q in r['requests']]) for r in rows])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:raise InputError('Frozen source-coverage experiment changed')
    write(root/'inputs.json',manifest);write(root/'references.json',refs)
    for case in cases:write(root/'sources'/(case['case_id']+'.json'),case['source'])
    for row in rows:
        for request in row['requests']:write(root/'requests'/(digest(request)+'.json'),request)
    client=client or JevClient(model=manifest['protocol']['model'])
    if client.model!=manifest['protocol']['model']:raise InputError('Client model differs')
    calls,results=0,[]
    for row in rows:
        observations=[];complete=True;error_type=None
        for request in row['requests']:
            key=digest(request);path=root/'receipts'/(key+'.json')
            try:
                if path.exists():
                    saved=read(path)
                    if saved['request']!=request:raise InputError('Cached coverage request changed')
                    response=saved['response']
                elif live and calls<max_calls:
                    calls+=1;response=client.transport(request);write(path,dict(request=request,response=response))
                else:complete=False;break
                if response.get('model')!=request['model']:raise InputError('Response model differs')
                answers=validate_answers(response,request)
                observations.append(dict(request_hash=key,answers={field:dict(selection=a['value'],
                    event_id=request['state']['source_fragments'].get(a['value'],{}).get('event_id')) for field,a in answers.items()}))
            except Exception as error:complete=False;error_type=type(error).__name__;break
        selections=[a for obs in observations for a in obs['answers'].values()]
        events=sorted({a['event_id'] for a in selections if a['event_id']})
        positive=bool(set(events)&set(row['target_events'])) if row['target_events'] else bool(events)
        unresolved=sum(a['selection']=='unresolved' for a in selections)
        prediction=1 if positive else 0 if complete and not unresolved and row['source']['complete_recorded_text'] else None
        ref=row['reference'];expected=ref.get('expected_conflict',ref.get('expected_candidate'))
        local=['source_candidate' if a['selection'] not in detector.SENTINELS else a['selection'] for a in selections]
        record=dict(case_id=row['case_id'],arm=row['arm'],complete=complete,error_type=error_type,
            source_complete=row['source']['complete_recorded_text'],prediction=prediction,
            expected_value=None if expected is None else int(expected),
            reference_match=prediction==(None if expected is None else int(expected)) if complete else None,
            local_selections=local,selected_event_ids=events,unresolved_questions=unresolved,observations=observations)
        if 'accepted_local_selections' in ref:
            record['local_reference_match']=all(v in ref['accepted_local_selections'] for v in local) if complete else None
        results.append(record);print(dumps(record),flush=True)
    report=dict(schema='requirement-source-coverage-report/1',input_hash=digest(manifest),reference_hash=digest(refs),new_calls=calls,results=results,
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        scope='Coverage-only state vs identical coverage state plus lifecycle clarification, on fixed reviewed controls and corrected public witness. No inferred missing actions, no source/page clipping, and no global positive suppression. Source completeness governs only absence as in production. Development experiment, not a production protocol.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-source-coverage-review')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=12)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k!='results'}))
