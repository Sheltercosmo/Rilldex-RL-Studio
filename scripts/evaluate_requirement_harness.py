"""Export frozen /6 controls, then optionally run full production requirements.

Default is offline. --live --prompt-key enables bounded calls. Reference labels
stay outside every request. Extraction determines later scan questions, so the
pre-live all-term scan export is a preview, not a promised request sequence.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker import requirement_diagnostics as detector
from tracker.diagnostic_worker import CallBudgetReached
from tracker.jev import JevClient
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/requirement-harness-controls.json'


def prepared(fixture_path=FIXTURE):
    fixture=read(fixture_path);version=fixture['protocol'];rows=[]
    if version!=detector.HARNESS_VERSION:raise InputError('Controls require frozen requirement harness /6')
    for case in fixture['cases']:
        run=normalize(case['document'])[0] if 'document' in case else None
        source=detector.source_from_run(run,version) if run else deepcopy(case['source'])
        terms=list(detector.term_requests(source,version=version))
        preview=list(detector.requests(source,version=version))
        if any(req['model']!=fixture['model'] for req in [*terms,*preview]):
            raise InputError('Production model differs from frozen controls')
        rows.append(dict(case_id=case['id'],source=source,source_hash=digest(source),
            normalized_source_hash=digest(run) if run else None,
            term_requests=terms,scan_preview=preview,
            term_request_hashes=[digest(req) for req in terms],
            scan_preview_hashes=[digest(req) for req in preview]))
    return fixture,rows


def evaluate(directory='outputs/requirement-harness-controls',*,live=False,client=None,
             fixture_path=FIXTURE,max_calls=24):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    fixture,rows=prepared(fixture_path);version=fixture['protocol'];root=Path(directory)
    references={case['id']:case['reference'] for case in fixture['cases']}
    manifest=dict(schema='requirement-harness-inputs/1',fixture_hash=digest(fixture),
        reference_hash=digest(references),model=fixture['model'],protocol=detector.protocol(version),
        scan_preview_scope='All discovered instruction paragraphs before model role selection. Actual scan batches depend on production extraction answers.',
        cases=[{k:row[k] for k in ('case_id','source_hash','normalized_source_hash','term_request_hashes','scan_preview_hashes')} for row in rows])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:
        raise InputError('Frozen inputs changed; choose a fresh output directory')
    write(root/'inputs.json',manifest)
    write(root/'references.json',dict(methodology=fixture['methodology'],references=references))
    for row in rows:
        folder=root/'cases'/row['case_id'];write(folder/'source.json',row['source'])
        for request in row['term_requests']:write(root/'exports'/'extraction'/(digest(request)+'.json'),request)
        for request in row['scan_preview']:write(root/'exports'/'all-terms-scan-preview'/(digest(request)+'.json'),request)
    # Every reference, source and preview above is persisted before client use.
    client=client or JevClient(model=fixture['model'])
    if client.model!=fixture['model']:raise InputError('Client model differs from frozen controls')
    calls,results=0,[]
    for row in rows:
        folder=root/'cases'/row['case_id'];reference=references[row['case_id']]
        def transport(request):
            nonlocal calls
            if request['state']['input_hash']!=row['source_hash']:
                raise InputError('Production request belongs to a different source')
            if request['state']['harness']!=version or request['model']!=fixture['model']:
                raise InputError('Production request differs from frozen protocol/model')
            key=digest(request);write(root/'requests'/(key+'.json'),request)
            if not live or calls>=max_calls:raise CallBudgetReached()
            calls+=1
            response=client.transport(request)
            write(root/'receipts'/(key+'.json'),dict(request=request,response=response))
            return response
        try:
            result=detector.execute(row['source'],folder/'workspace',transport,version=version)
            audit=detector.audit(row['source'],result,folder/'workspace')
            complete=result['coverage']['scan_complete'];metric=result['metrics'][detector.METRIC]
            record=dict(case_id=row['case_id'],complete=complete,prediction=metric['value'],
                prediction_status=metric['status'],prediction_reason=metric['reason'],
                accepted_values=reference['accepted_values'],ambiguous=bool(reference.get('uncertainty')),
                reference_match=metric['value'] in reference['accepted_values'] if complete else None,
                requirement_selections=result['requirement_selections'],coverage=result['coverage'],
                finding_ids=[f['id'] for f in result['findings']],audit=audit,error_type=None)
        except Exception as error:
            record=dict(case_id=row['case_id'],complete=False,prediction=None,reference_match=None,
                ambiguous=bool(reference.get('uncertainty')),error_type=type(error).__name__)
        results.append(record);print(dumps(record),flush=True)
    definite=[r for r in results if r['complete'] and not r['ambiguous']]
    report=dict(schema='requirement-harness-report/1',fixture_hash=digest(fixture),reference_hash=digest(references),
        protocol=detector.protocol(version),model=fixture['model'],new_calls_this_invocation=calls,
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        completed_cases=sum(r['complete'] for r in results),
        definite_completed=len(definite),definite_reference_matches=sum(r['reference_match'] for r in definite),
        results=results,methodology=fixture['methodology'])
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-harness-controls')
    parser.add_argument('--fixture',type=Path,default=FIXTURE)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=24)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,fixture_path=args.fixture,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k not in {'results','protocol'}}))
