"""Export or evaluate fixed source controls through production diagnostics /20.

References are model-reviewed development judgments, kept outside every model
request. All results, including failures and unresolved cases, are retained.
Default execution exports requests only; --live --prompt-key enables calls.
"""
import argparse
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.adapters import normalize
from tracker import diagnostic_direct as direct, diagnostic_search as search
from tracker.diagnostic_worker import CallBudgetReached
from tracker.jev import JevClient, validate_answers
from tracker.schema import InputError, digest, dumps
from tracker.semantic_extraction import read, write

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/diagnostic-harness-contrasts.json'


def prepared(fixture_path=FIXTURE, versions=None):
    fixture = read(fixture_path)
    versions = versions or [search.HARNESS_VERSION]
    rows = []
    for case in fixture['cases']:
        run = normalize(case['document'])[0]
        for version in versions:
            source = search.source_from_run(run,version)
            requests = list(direct.requests(source,version))
            if any(request['model']!=fixture['model'] for request in requests):
                raise InputError('Current production model differs from the frozen control model')
            rows.append(dict(case_id=case['id'],version=version,source=source,source_hash=digest(source),
                             normalized_source_hash=digest(run),requests=requests,
                             request_hashes=[digest(request) for request in requests]))
    return fixture, rows


def evaluate(directory='outputs/diagnostic-harness-contrasts', *, live=False, client=None,
             fixture_path=FIXTURE, versions=None, max_calls=30):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    fixture, rows = prepared(fixture_path,versions)
    root = Path(directory)
    client = client or JevClient(model=fixture['model'])
    if client.model!=fixture['model']:raise InputError('Client model differs from frozen controls')
    references = {case['id']:case['reference'] for case in fixture['cases']}
    manifest = dict(schema='diagnostic-harness-contrast-inputs/1',fixture_hash=digest(fixture),
        reference_hash=digest(references),model=fixture['model'],
        protocols={version:search.protocol(version) for version in sorted({r['version'] for r in rows})},
        cases=[{key:row[key] for key in ('case_id','version','source_hash','normalized_source_hash','request_hashes')} for row in rows])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:
        raise InputError('Frozen inputs changed; select a fresh output directory')
    write(root/'inputs.json',manifest)
    write(root/'references.json',dict(methodology=fixture['methodology'],references=references))
    for row in rows:
        folder = root/row['version'].replace('/','-')/row['case_id']
        write(folder/'source.json',row['source'])
        for request in row['requests']:write(root/'requests'/(digest(request)+'.json'),request)
    calls, results = 0, []
    for row in rows:
        folder = root/row['version'].replace('/','-')/row['case_id']
        def decide(request):
            nonlocal calls
            key = digest(request)
            if key not in row['request_hashes']:raise InputError('Builder emitted a request outside the frozen manifest')
            path = root/'receipts'/(key+'.json')
            if path.exists():
                receipt=read(path)
                if receipt['request']!=request:raise InputError('Cached request changed')
                response=receipt['response']
            elif live and calls<max_calls:
                response=client.transport(request)
                calls+=1
                write(path,dict(request=request,response=response))
            else:raise CallBudgetReached()
            if response.get('model')!=request['model']:raise InputError('Response model differs')
            return validate_answers(response,request), key
        result = direct.build(row['source'],decide,version=row['version'])
        write(folder/'result.json',result)
        complete = result['coverage']['scan_complete']
        scores = {}
        if complete:
            for detector, expected in references[row['case_id']]['metrics'].items():
                prediction=result['metrics'][detector]['value']
                scores[detector]=dict(prediction=prediction,reference=expected,reference_match=prediction==expected)
        record=dict(case_id=row['case_id'],version=row['version'],complete=complete,scores=scores,
            unresolved_detectors=result['coverage']['unresolved_detectors'],
            finding_ids=[finding['id'] for finding in result['findings']])
        results.append(record)
        print(dumps(record),flush=True)
    report=dict(schema='diagnostic-harness-contrasts/1',fixture_hash=digest(fixture),reference_hash=digest(references),
        status='complete' if all(r['complete'] for r in results) else 'pending',new_calls_this_invocation=calls,
        scored_answers=sum(len(r['scores']) for r in results),
        reference_matches=sum(s['reference_match'] for r in results for s in r['scores'].values()),
        results=results,methodology=fixture['methodology'])
    write(root/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/diagnostic-harness-contrasts')
    parser.add_argument('--fixture',type=Path,default=FIXTURE)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=30)
    parser.add_argument('--version', action='append', choices=sorted(search.DIRECT_VERSIONS))
    parser.add_argument('--baseline',action='store_true',help='Also run preserved /19 source capture')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    versions=args.version or ([search.CONTRACT_VERSION,search.HARNESS_VERSION] if args.baseline else None)
    result=evaluate(args.output,live=args.live,fixture_path=args.fixture,versions=versions,max_calls=args.max_calls)
    print(dumps({k:v for k,v in result.items() if k!='results'}))
