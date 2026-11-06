"""Focal candidate/relation representation, with all frozen candidates retained.

This experiment reuses the failed coverage+lifecycle requests verbatim as state.
Only the question representation changes; there is no source filter or vote.
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
QUESTIONS_PER_REQUEST=8
RELATION_CRITERIA={
    'conflict':'The focal passage shows a visible incompatibility with the quoted requirement, or a completion assertion contradicted by recorded evidence.',
    'no_conflict':'The focal passage shows compatible behavior or truthfully unfinished work; it does not establish a conflict with the quoted requirement.',
    'unverified_claim':'The focal passage makes or reports a completion assertion that recorded evidence neither corroborates nor contradicts.',
    'unresolved':'The focal passage or its relation to the quoted requirement cannot be interpreted from the available evidence.'}
# Mechanical event-picker wording changes, not an additional exclusion rule.
REWRITES=(
    ('Select a passage only when it establishes','Choose conflict only when the focal passage establishes'),
    ('Choose none when no concrete conflict is visible, or unresolved when the evidence cannot resolve a specific potential incompatibility.',
     'Choose the relation option that best describes this focal passage and the quoted requirement.'),
    ('Select a conflict only when','Choose conflict only when'),
    ('Choose none when no concrete conflict is visible, or unresolved when a specific potential conflict cannot be interpreted without the missing implementation.',
     'Classify a specific potential conflict that cannot be interpreted without the missing implementation as unresolved.'))


def variants(original):
    """One question for every original requirement/candidate pair, in order."""
    pairs=[]
    for field,question in original['questions'].items():
        for candidate in question['criteria']:
            if candidate in detector.SENTINELS:continue
            if candidate not in original['state']['source_fragments']:raise InputError('Candidate is absent from frozen state')
            instructions=question['instructions']
            for before,after in REWRITES:
                if before not in instructions:raise InputError('Frozen event-picker rule differs')
                instructions=instructions.replace(before,after)
            instructions+='\nThe focal source passage for THIS question is '+candidate+'. Classify its relation to the quoted requirement using the recorded context.'
            pairs.append((field,candidate,dict(type='choice',instructions=instructions,criteria=deepcopy(RELATION_CRITERIA))))
    for start in range(0,len(pairs),QUESTIONS_PER_REQUEST):
        request=deepcopy(original);request['questions']={};bindings={}
        for number,(field,candidate,question) in enumerate(pairs[start:start+QUESTIONS_PER_REQUEST],start):
            key='relation_'+str(number);request['questions'][key]=question
            bindings[key]=dict(requirement_field=field,candidate_fragment_id=candidate,
                               event_id=original['state']['source_fragments'][candidate].get('event_id'))
        if len(dumps(request))>120000:raise InputError('Relation request exceeds bound')
        yield request,bindings


def prepared():
    frozen=read(FIXTURE);cases=[]
    if digest(frozen['inputs'])!=frozen['input_hash']:raise InputError('Coverage inputs changed')
    inputs={(r['case_id'],r['arm']):r for r in frozen['inputs']['rows']}
    for row in frozen['rows']:
        if row['arm']!='coverage_state_lifecycle':continue
        source=read(Path('outputs/requirement-source-coverage-review/sources')/(row['case_id']+'.json'))
        if digest(source)!=inputs[(row['case_id'],row['arm'])]['source_hash']:raise InputError('Frozen source changed')
        requests=[];bindings={}
        for packet in row['packets']:
            if digest(packet['request'])!=packet['request_hash']:raise InputError('Frozen request changed')
            for request,mapping in variants(packet['request']):
                key=digest(request);requests.append(request);bindings[key]=mapping
        cases.append(dict(case_id=row['case_id'],source=source,reference=row['reference'],
                          requests=requests,bindings=bindings,
                          baseline_request_hashes=[p['request_hash'] for p in row['packets']],
                          baseline_prediction=row['prediction']))
    if len(cases)!=6:raise InputError('Expected all six frozen coverage cases')
    return dict(coverage_fixture_hash=digest(frozen),coverage_input_hash=frozen['input_hash'],
                reference_hash=frozen['reference_hash']),cases


def evaluate(directory='outputs/requirement-focal-relation-review',*,live=False,client=None,max_calls=8):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    context,cases=prepared();root=Path(directory);refs={c['case_id']:c['reference'] for c in cases}
    manifest=dict(schema='requirement-focal-relation-inputs/1',**context,
        representation='every-requirement-candidate-relation/1',criteria=RELATION_CRITERIA,
        instruction_rewrites=REWRITES,questions_per_request=QUESTIONS_PER_REQUEST,
        rows=[dict(case_id=c['case_id'],source_hash=digest(c['source']),
            baseline_request_hashes=c['baseline_request_hashes'],
            request_hashes=[digest(r) for r in c['requests']],bindings=c['bindings']) for c in cases])
    # JSON round trips convert tuple pairs to lists; compare canonical contents.
    if (root/'inputs.json').exists() and digest(read(root/'inputs.json'))!=digest(manifest):raise InputError('Frozen focal-relation experiment changed')
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
                    if saved['request']!=request:raise InputError('Cached relation request changed')
                    response=saved['response']
                elif live and calls<max_calls:
                    calls+=1;response=client.transport(request);write(path,dict(request=request,response=response))
                else:complete=False;break
                if response.get('model')!=request['model']:raise InputError('Response model differs')
                answers=validate_answers(response,request)
                observations.append(dict(request_hash=key,answers={field:dict(selection=a['value'],**case['bindings'][key][field]) for field,a in answers.items()}))
            except Exception as error:complete=False;error_type=type(error).__name__;break
        answers=[a for obs in observations for a in obs['answers'].values()]
        conflicts=[a for a in answers if a['selection']=='conflict']
        unknown=sum(a['selection'] in {'unverified_claim','unresolved'} for a in answers)
        prediction=1 if conflicts else 0 if complete and not unknown and case['source']['complete_recorded_text'] else None
        expected=case['reference'].get('expected_conflict',case['reference'].get('expected_candidate'))
        expected=None if expected is None else int(expected)
        record=dict(case_id=case['case_id'],complete=complete,error_type=error_type,
            source_complete=case['source']['complete_recorded_text'],prediction=prediction,expected_value=expected,
            reference_match=prediction==expected if complete else None,
            selected_event_ids=sorted({a['event_id'] for a in conflicts if a['event_id']}),
            relation_counts={choice:sum(a['selection']==choice for a in answers) for choice in RELATION_CRITERIA},
            observations=observations,baseline_prediction=case['baseline_prediction'])
        results.append(record);print(dumps(record),flush=True)
    report=dict(schema='requirement-focal-relation-report/1',input_hash=digest(manifest),reference_hash=digest(refs),new_calls=calls,results=results,
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        scope='Experimental question representation on every original candidate and requirement, with unchanged frozen coverage+lifecycle state. Four relation choices replace the event picker. Unverified or unresolved relations prevent an absence conclusion; any explicit conflict is retained. No production change or source filter.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-focal-relation-review')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=8)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k!='results'}))
