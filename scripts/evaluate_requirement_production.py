"""Validate exact production /7 on unchanged development source controls.

Full production execution and audit. All eleven actual extraction responses
are reused exactly; only eleven scan requests can spend provider calls.
Default execution exports all requests without model calls.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_requirement_harness import prepared as controls
from tracker.adapters import normalize
from tracker import requirement_diagnostics as detector
from tracker.diagnostic_worker import CallBudgetReached
from tracker.jev import JevClient,validate_answers
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

FIXTURES=Path(__file__).resolve().parents[1]/'tests/fixtures'


def prepared():
    primary,primary_rows=controls()
    supplement,supplement_rows=controls(FIXTURES/'requirement-intermediate-controls.json')
    baseline=read(FIXTURES/'requirement-harness-live.json')
    intermediate=read(FIXTURES/'requirement-intermediate-live.json')
    if digest(primary)!=baseline['source_fixture_hash'] or digest(supplement)!=intermediate['supplemental_fixture_hash']:
        raise InputError('Production controls changed')
    cases={c['id']:c for c in [*primary['cases'],*supplement['cases']]}
    references={name:case['reference'] for name,case in cases.items()}
    if digest(references)!=intermediate['combined_reference_hash']:raise InputError('Production references changed')
    saved={row['case_id']:row for row in [*baseline['rows'],*[r for r in intermediate['rows'] if r['supplemental']]]}
    rows=[]
    for prior in [*primary_rows,*supplement_rows]:
        case=cases[prior['case_id']]
        run=normalize(case['document'])[0] if 'document' in case else None
        source=detector.source_from_run(run,detector.CONFLICT_VERSION) if run else deepcopy(case['source'])
        if source!=prior['source']:raise InputError('Production /7 changed frozen /6 source capture')
        extraction=list(detector.term_requests(source,version=detector.CONFLICT_VERSION))
        packets={p['request_hash']:p for p in saved[prior['case_id']]['packets'] if p['stage']=='requirement_extraction'}
        if {digest(req) for req in extraction}!=set(packets):raise InputError('Production extraction differs from frozen actual requests')
        terms=[]
        for request in extraction:
            packet=packets[digest(request)]
            if digest(packet['response'])!=packet['response_hash']:raise InputError('Frozen extraction response changed')
            answers=validate_answers(packet['response'],request)
            for i,term in enumerate(request['state']['instruction_paragraphs'].values()):
                if answers['term_'+str(i)]['value'] in {'task_requirement','unresolved'}:terms.append(term)
        scans=list(detector.requests(source,terms,version=detector.CONFLICT_VERSION))
        rows.append(dict(case_id=prior['case_id'],source=source,source_hash=digest(source),
            supplemental=prior['case_id'] in {c['id'] for c in supplement['cases']},
            extraction=packets,requests=[*extraction,*scans]))
    return dict(primary_hash=digest(primary),supplemental_hash=digest(supplement),references=references,
        original_reference_hash=baseline['pre_live_reference_hash'],model=primary['model'],
        baseline_receipts_hash=digest(baseline),supplemental_receipts_hash=digest(intermediate)),rows


def evaluate(directory='outputs/requirement-production7',*,live=False,client=None,max_calls=11):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    frozen,rows=prepared();root=Path(directory);references=frozen['references']
    manifest=dict(schema='requirement-production-inputs/1',protocol=detector.protocol(detector.CONFLICT_VERSION),
        **{k:v for k,v in frozen.items() if k!='references'},reference_hash=digest(references),
        rows=[dict(case_id=row['case_id'],source_hash=row['source_hash'],request_hashes=[digest(r) for r in row['requests']],
            reused_extraction_request_hashes=list(row['extraction'])) for row in rows])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:
        raise InputError('Frozen production validation inputs changed; choose a fresh directory')
    write(root/'inputs.json',manifest);write(root/'references.json',references)
    for row in rows:
        write(root/'cases'/row['case_id']/'source.json',row['source'])
        for request in row['requests']:write(root/'requests'/(digest(request)+'.json'),request)
    client=client or JevClient(model=frozen['model'])
    if client.model!=frozen['model']:raise InputError('Client model differs from frozen controls')
    calls,results=0,[]
    for row in rows:
        expected={digest(request):request for request in row['requests']};reference=references[row['case_id']]
        def transport(request):
            nonlocal calls
            key=digest(request)
            if expected.get(key)!=request:raise InputError('Production emitted an unexported request')
            if request['state']['stage']=='requirement_extraction':return row['extraction'][key]['response']
            if not live or calls>=max_calls:raise CallBudgetReached()
            calls+=1;response=client.transport(request)
            write(root/'receipts'/(key+'.json'),dict(request=request,response=response))
            return response
        record=dict(case_id=row['case_id'],supplemental=row['supplemental'],ambiguous=bool(reference.get('uncertainty')),
            accepted_values=reference['accepted_values'],reused_extraction_request_hashes=list(row['extraction']))
        try:
            workspace=root/'cases'/row['case_id']/'workspace'
            result=detector.execute(row['source'],workspace,transport,version=detector.CONFLICT_VERSION)
            audit=detector.audit(row['source'],result,workspace)
            complete=result['coverage']['scan_complete'];prediction=result['metrics'][detector.METRIC]['value']
            record.update(complete=complete,prediction=prediction,coverage=result['coverage'],audit=audit,
                result_hash=digest(result),reference_match=prediction in reference['accepted_values'] if complete else None,error_type=None)
        except Exception as error:record.update(complete=False,prediction=None,reference_match=None,error_type=type(error).__name__)
        results.append(record);print(dumps(record),flush=True)
    original=[r for r in results if r['complete'] and not r['ambiguous'] and not r['supplemental']]
    added=[r for r in results if r['complete'] and r['supplemental']]
    report=dict(schema='requirement-production-report/1',protocol=detector.protocol(detector.CONFLICT_VERSION),
        reference_hash=digest(references),original_reference_hash=frozen['original_reference_hash'],
        primary_fixture_hash=frozen['primary_hash'],supplemental_fixture_hash=frozen['supplemental_hash'],
        new_calls_this_invocation=calls,status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        original_definite_complete=len(original),original_definite_matches=sum(r['reference_match'] for r in original),
        supplemental_complete=len(added),supplemental_matches=sum(r['reference_match'] for r in added),results=results,
        scope='Exact production /7 execution and audit on the unchanged development controls; all actual /6 extraction responses reused. New calls are scans only. Previous misses remain frozen separately; not held-out accuracy.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-production7')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=11)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k not in {'results','protocol'}}))
