"""Exact nondefault /8 validation: 23 scans plus five fresh role calls.

Ten original compact controls reuse eleven actual /6 extraction receipts.
Five fresh compact controls use actual role extraction, then execute and audit.
Six older comparisons retain fixed historical roles and exact witness pages.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_requirement_production import prepared as original_controls
from scripts.evaluate_requirement_coverage import prepared as fresh_controls
from scripts.evaluate_requirement_prior_panel import prepared as public_controls
from tracker import requirement_diagnostics as detector
from tracker.diagnostic_worker import CallBudgetReached
from tracker.jev import JevClient,validate_answers
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

VERSION=detector.EVIDENCE_VERSION
PANEL=Path('outputs/requirement-prior-corrected-panel')


def selected_terms(request,response):
    """Bind answers through the question's literal ID, including saved JSON."""
    answers=validate_answers(response,request);terms=[]
    for field in sorted(request['questions'],key=lambda key:int(key.rsplit('_',1)[1])):
        match=re.search(r'instruction paragraph (\S+)\. Treat its text',request['questions'][field]['instructions'])
        if not match:raise InputError('Role question has no explicit paragraph binding')
        if answers[field]['value'] in {'task_requirement','unresolved'}:
            terms.append(request['state']['instruction_paragraphs'][match.group(1)])
    return terms


def prepared():
    prior,old=original_controls();fresh_meta,fresh=fresh_controls();panel,public=public_controls(PANEL)
    rows=[]
    for row in old:
        source=row['source'];extraction=list(detector.term_requests(source,version=VERSION));terms=[]
        if {digest(r) for r in extraction}!=set(row['extraction']):raise InputError('Actual /6 extraction reuse changed')
        for request in extraction:terms.extend(selected_terms(request,row['extraction'][digest(request)]['response']))
        rows.append(dict(case_id=row['case_id'],kind='original_compact',source=source,
            reference=prior['references'][row['case_id']],role_basis='exact_actual_6_receipts',
            extraction_requests=extraction,reused_extraction=row['extraction'],
            scan_requests=list(detector.requests(source,terms,version=VERSION))))
    for row in fresh:
        if row['case_id']=='authorized-submission':continue
        rows.append(dict(case_id=row['case_id'],kind='fresh_compact',source=row['source'],reference=row['reference'],
            role_basis='fresh_model_extraction',extraction_requests=list(detector.term_requests(row['source'],version=VERSION)),
            reused_extraction={},scan_requests=None))
    for row in public:
        case=row['case'];source=read(PANEL/case['case_id']/'source.json')
        terms=read(PANEL/case['case_id']/'historical-selected-requirements.json')
        scans=[r for r in detector.requests(source,terms,version=VERSION) if r['state']['page'] in case['witness_pages']]
        if len(scans)!=len(row['requests']):raise InputError('Production8 changed witness-page request count')
        for old_req,new_req in zip(row['requests'],scans):
            restored=deepcopy(new_req)
            restored['state'].pop('source_coverage');restored['state'].update(harness=detector.CONFLICT_VERSION,protocol_id=detector.protocol(detector.CONFLICT_VERSION)['id'])
            for field,q in restored['questions'].items():
                q['criteria'].pop('unverified_claim');q['instructions']=old_req['questions'][field]['instructions']
            if restored!=old_req:raise InputError('Production8 changed historical source choices or context')
        rows.append(dict(case_id=case['case_id'],kind='historical_witness',source_kind=case['kind'],source=source,reference=row['reference'],
            role_basis=('historical_actual_roles_explicit_paragraph_mapping' if case.get('historical_role_packet_hashes') else 'prior_authored_fixed_requirements'),
            historical_role_packet_hashes=case.get('historical_role_packet_hashes',[]),
            extraction_requests=[],reused_extraction={},scan_requests=scans,
            target_events=case['target_events'],witness_pages=case['witness_pages']))
    return dict(original_controls_hash=prior['primary_hash'],supplemental_controls_hash=prior['supplemental_hash'],
                original_reference_hash=prior['original_reference_hash'],fresh_controls=fresh_meta,
                public_panel_hash=digest(panel)),rows


def expected_values(reference):
    if 'accepted_values' in reference:return reference['accepted_values']
    for field in ('expected_conflict','expected_candidate'):
        if field in reference:
            value=reference[field]
            return [None if value is None else int(value)]
    if reference.get('expected')=='requirement_conflict':return [1]
    if reference and all(isinstance(row,dict) and 'expectation' in row for row in reference.values()):
        return [int(any(row['expectation'] not in {'none','unresolved','inspect'} for row in reference.values()))]
    raise InputError('Unknown frozen reference format')


def evaluate(directory='outputs/requirement-production8',*,live=False,client=None,max_calls=28):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    context,rows=prepared();root=Path(directory);protocol=detector.protocol(VERSION)
    refs={r['case_id']:r['reference'] for r in rows}
    manifest=dict(schema='requirement-evidence-validation-inputs/1',protocol=protocol,**context,reference_hash=digest(refs),
        budget_scope='One shared budget for new role and scan calls; reused actual extraction receipts cost zero.',
        rows=[dict(case_id=r['case_id'],kind=r['kind'],source_kind=r.get('source_kind'),source_hash=digest(r['source']),role_basis=r['role_basis'],
            extraction_request_hashes=[digest(q) for q in r['extraction_requests']],reused_extraction_request_hashes=list(r['reused_extraction']),
            scan_request_hashes=None if r['scan_requests'] is None else [digest(q) for q in r['scan_requests']],
            historical_role_packet_hashes=r.get('historical_role_packet_hashes',[]),target_events=r.get('target_events'),witness_pages=r.get('witness_pages')) for r in rows])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:raise InputError('Frozen production8 validation changed')
    write(root/'inputs.json',manifest);write(root/'references.json',refs)
    for row in rows:
        write(root/'cases'/row['case_id']/'source.json',row['source'])
        for request in [*row['extraction_requests'],*(row['scan_requests'] or [])]:write(root/'requests'/(digest(request)+'.json'),request)
    client=client or JevClient(model=protocol['model'])
    if client.model!=protocol['model']:raise InputError('Client model differs from production protocol')
    calls=0;counts={'requirement_extraction':0,'requirement_conflict_scan':0};results=[]
    def obtain(request):
        nonlocal calls
        key=digest(request);path=root/'receipts'/(key+'.json')
        # Adaptive fresh scan requests are exported before their provider call.
        write(root/'requests'/(key+'.json'),request)
        if path.exists():
            saved=read(path)
            if saved['request']!=request:raise InputError('Cached production8 request changed')
            response=saved['response']
        else:
            if not live or calls>=max_calls:raise CallBudgetReached()
            calls+=1;counts[request['state']['stage']]+=1
            response=client.transport(request);write(path,dict(request=request,response=response))
        if response.get('model')!=request['model']:raise InputError('Response model differs')
        validate_answers(response,request)
        return response
    # Freeze all five real role decisions before deriving their scan requests.
    fresh_extraction={};fresh_errors={}
    for row in rows:
        if row['kind']!='fresh_compact':continue
        responses={};terms=[]
        try:
            for request in row['extraction_requests']:
                response=obtain(request);responses[digest(request)]=response;terms.extend(selected_terms(request,response))
            row['scan_requests']=list(detector.requests(row['source'],terms,version=VERSION))
            for request in row['scan_requests']:write(root/'requests'/(digest(request)+'.json'),request)
            write(root/'cases'/row['case_id']/'actual-role-plan.json',dict(role_basis='fresh_model_extraction',
                extraction_request_hashes=list(responses),selected_requirement_ids=[t['id'] for t in terms],
                scan_request_hashes=[digest(q) for q in row['scan_requests']]))
            fresh_extraction[row['case_id']]=responses
        except CallBudgetReached:pass
        except Exception as error:fresh_errors[row['case_id']]=type(error).__name__
    for row in rows:
        record=dict(case_id=row['case_id'],kind=row['kind'],source_kind=row.get('source_kind'),role_basis=row['role_basis'],
                    accepted_values=expected_values(row['reference']))
        try:
            if row['kind']=='fresh_compact' and row['case_id'] not in fresh_extraction:
                record.update(complete=False,prediction=None,reference_match=None,error_type=fresh_errors.get(row['case_id']))
            elif row['kind']!='historical_witness':
                requests={digest(q):q for q in [*row['extraction_requests'],*row['scan_requests']]}
                def transport(request):
                    key=digest(request)
                    if requests.get(key)!=request:raise InputError('Production emitted an unplanned request')
                    if request['state']['stage']=='requirement_extraction':
                        return (row['reused_extraction'][key]['response'] if row['reused_extraction'] else fresh_extraction[row['case_id']][key])
                    return obtain(request)
                workspace=root/'cases'/row['case_id']/'workspace'
                result=detector.execute(row['source'],workspace,transport,version=VERSION)
                audit=detector.audit(row['source'],result,workspace)
                prediction=result['metrics'][detector.METRIC]['value'];complete=result['coverage']['scan_complete']
                record.update(complete=complete,prediction=prediction,coverage=result['coverage'],audit=audit,result_hash=digest(result),
                    reference_match=prediction in record['accepted_values'] if complete else None,error_type=None)
            else:
                observations=[];complete=True
                for request in row['scan_requests']:
                    try:response=obtain(request)
                    except CallBudgetReached:complete=False;break
                    answers=validate_answers(response,request)
                    observations.append(dict(request_hash=digest(request),page=request['state']['page'],answers={field:dict(selection=a['value'],
                        event_id=request['state']['source_fragments'].get(a['value'],{}).get('event_id')) for field,a in answers.items()}))
                answers=[a for obs in observations for a in obs['answers'].values()]
                events=sorted({a['event_id'] for a in answers if a['event_id']});unknown=sum(a['selection'] in {'unverified_claim','unresolved'} for a in answers)
                target=bool(set(events)&set(row['target_events']))
                prediction=1 if events else 0 if complete and not unknown else None
                target_prediction=1 if target else 0 if complete and not unknown else None
                record.update(complete=complete,prediction=prediction,target_prediction=target_prediction,
                    reference_match=target_prediction in record['accepted_values'] if complete else None,error_type=None,
                    target_events=row['target_events'],selected_event_ids=events,unknown_questions=unknown,observations=observations,
                    scope='Frozen witness-page comparison, not complete-run production execution or audit. Exact target score remains separate from alternate selected evidence.')
        except Exception as error:record.update(complete=False,prediction=None,reference_match=None,error_type=type(error).__name__)
        results.append(record);print(dumps(record),flush=True)
    report=dict(schema='requirement-evidence-validation-report/1',protocol=protocol,input_hash=digest(manifest),reference_hash=digest(refs),
        new_calls_this_invocation=calls,new_role_calls=counts['requirement_extraction'],new_scan_calls=counts['requirement_conflict_scan'],
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',results=results,
        scope='Exact production8 validation. Original compact controls use actual frozen6 role responses; fresh compact controls use real new6 role responses with no forced selection. Both compact groups execute and audit exact production8. Six historical witness cases preserve four public and two authored origins, original role provenance and frozen pages; strict target scores do not absorb independently adjudicated alternate passages. Development validation, not held-out accuracy.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-production8')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=28)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k not in {'results','protocol'}}))
