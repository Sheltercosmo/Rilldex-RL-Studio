"""Original event picker with one explicit unverified-completion option.

Six fixed coverage+lifecycle cases, no candidate decomposition or filtering.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import requirement_diagnostics as detector
from tracker.jev import JevClient,validate_answers
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/requirement-coverage-live.json'
UNVERIFIED_CHOICE='A completion assertion is neither corroborated nor contradicted by the recorded evidence.'
UNVERIFIED_INSTRUCTION='Choose unverified_claim when a completion assertion is neither corroborated nor contradicted by the recorded evidence and no specific requirement conflict is established.'


def variant(original):
    request=deepcopy(original)
    for question in request['questions'].values():
        if 'unverified_claim' in question['criteria']:raise InputError('Unverified option already exists')
        question['criteria']['unverified_claim']=UNVERIFIED_CHOICE
        question['instructions']+='\n'+UNVERIFIED_INSTRUCTION
    if len(dumps(request))>120000:raise InputError('Event-picker request exceeds bound')
    return request


def prepared():
    frozen=read(FIXTURE);cases=[]
    if digest(frozen['inputs'])!=frozen['input_hash']:raise InputError('Coverage inputs changed')
    inputs={(r['case_id'],r['arm']):r for r in frozen['inputs']['rows']}
    for row in frozen['rows']:
        if row['arm']!='coverage_state_lifecycle':continue
        source=read(Path('outputs/requirement-source-coverage-review/sources')/(row['case_id']+'.json'))
        if digest(source)!=inputs[(row['case_id'],row['arm'])]['source_hash']:raise InputError('Frozen source changed')
        requests=[]
        for packet in row['packets']:
            if digest(packet['request'])!=packet['request_hash']:raise InputError('Frozen request changed')
            requests.append(variant(packet['request']))
        cases.append(dict(case_id=row['case_id'],source=source,reference=row['reference'],requests=requests,
            baseline_request_hashes=[p['request_hash'] for p in row['packets']],baseline_prediction=row['prediction']))
    if len(cases)!=6:raise InputError('Expected all six frozen coverage cases')
    return dict(coverage_fixture_hash=digest(frozen),coverage_input_hash=frozen['input_hash'],reference_hash=frozen['reference_hash']),cases


def evaluate(directory='outputs/requirement-unverified-option-review',*,live=False,client=None,max_calls=6):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    context,cases=prepared();root=Path(directory);refs={c['case_id']:c['reference'] for c in cases}
    manifest=dict(schema='requirement-unverified-option-inputs/1',**context,unverified_choice=UNVERIFIED_CHOICE,
        unverified_instruction=UNVERIFIED_INSTRUCTION,
        rows=[dict(case_id=c['case_id'],source_hash=digest(c['source']),baseline_request_hashes=c['baseline_request_hashes'],
                   request_hashes=[digest(r) for r in c['requests']]) for c in cases])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:raise InputError('Frozen unverified-option experiment changed')
    write(root/'inputs.json',manifest);write(root/'references.json',refs)
    for case in cases:
        write(root/'sources'/(case['case_id']+'.json'),case['source'])
        for request in case['requests']:write(root/'requests'/(digest(request)+'.json'),request)
    model=cases[0]['requests'][0]['model'];client=client or JevClient(model=model)
    if client.model!=model:raise InputError('Client model differs')
    calls,results=0,[]
    for case in cases:
        observations=[];complete=True;error_type=None
        for request in case['requests']:
            key=digest(request);path=root/'receipts'/(key+'.json')
            try:
                if path.exists():
                    saved=read(path)
                    if saved['request']!=request:raise InputError('Cached unverified-option request changed')
                    response=saved['response']
                elif live and calls<max_calls:
                    calls+=1;response=client.transport(request);write(path,dict(request=request,response=response))
                else:complete=False;break
                if response.get('model')!=request['model']:raise InputError('Response model differs')
                answers=validate_answers(response,request)
                observations.append(dict(request_hash=key,answers={field:dict(selection=a['value'],
                    event_id=request['state']['source_fragments'].get(a['value'],{}).get('event_id')) for field,a in answers.items()}))
            except Exception as error:complete=False;error_type=type(error).__name__;break
        answers=[a for obs in observations for a in obs['answers'].values()]
        events=sorted({a['event_id'] for a in answers if a['event_id']})
        unknown=sum(a['selection'] in {'unverified_claim','unresolved'} for a in answers)
        prediction=1 if events else 0 if complete and not unknown and case['source']['complete_recorded_text'] else None
        expected=case['reference'].get('expected_conflict',case['reference'].get('expected_candidate'))
        expected=None if expected is None else int(expected)
        record=dict(case_id=case['case_id'],complete=complete,error_type=error_type,
            source_complete=case['source']['complete_recorded_text'],prediction=prediction,expected_value=expected,
            reference_match=prediction==expected if complete else None,selected_event_ids=events,
            unverified_questions=sum(a['selection']=='unverified_claim' for a in answers),
            unresolved_questions=sum(a['selection']=='unresolved' for a in answers),
            observations=observations,baseline_prediction=case['baseline_prediction'])
        results.append(record);print(dumps(record),flush=True)
    report=dict(schema='requirement-unverified-option-report/1',input_hash=digest(manifest),reference_hash=digest(refs),new_calls=calls,results=results,
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        scope='Original frozen coverage+lifecycle event picker plus one explicit unverified_claim option and its selection sentence. All original choices, source state and bindings retained. Any conflict remains positive; unverified/unresolved blocks an absence conclusion. Experimental only, no production change or postfilter.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-unverified-option-review')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=6)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k!='results'}))
