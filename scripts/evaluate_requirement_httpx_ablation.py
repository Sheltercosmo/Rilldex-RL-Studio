"""Three controlled evidence-representation probes of the frozen HTTPX miss.

No production change. Preserve the independent positive reference while testing
question competition, candidate granularity, and compact exact code evidence.
"""
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient,validate_answers
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/requirement-httpx-implementation-live.json'
ARMS=('requirement_only','event_choice','compact_code')
FIELD='requirement_3'
SLICES=((1605,2606),(8787,10776))


def prepared(*,complete_schema=False):
    frozen=read(FIXTURE);source=frozen['source']
    if digest(source)!=frozen['source_hash']:raise InputError('Frozen HTTPX source changed')
    baseline=next(row for row in frozen['rows'] if row['page']==9);original=baseline['request']
    if digest(original)!=baseline['request_hash']:raise InputError('Frozen baseline request changed')
    event=next(e for e in json.loads(source['trace']) if e.get('id')=='e68')
    fragments=[event['text'][start:end] for start,end in SLICES]
    if not fragments[0].startswith('JSON_WHITESPACE = ') or not fragments[1].startswith('class NDJSONParser:'):
        raise InputError('Reviewed exact code spans changed')
    code='\n\n'.join(fragments)
    provenance=dict(event_id='e68',source_pointer=event['source_pointer'],
        slice_origin='decoded event.text',slices=[dict(start=start,end=end,sha256=digest(event['text'][start:end])) for start,end in SLICES],
        joined_code_hash=digest(code),join_separator='two newline characters',
        evidence_scope='Recorded text-parser implementation, including initialization and all application helpers called by the class. No byte decoder or runtime counterexample is supplied.')
    requests={}
    request=deepcopy(original);request['questions']={FIELD:deepcopy(original['questions'][FIELD])};requests['requirement_only']=request
    event_request=deepcopy(request)
    event_request['questions'][FIELD]['criteria']={'e68':'Recorded source event e68, shown in the source fragments in this state.',
        **{key:original['questions'][FIELD]['criteria'][key] for key in ('none','unverified_claim','unresolved')}}
    requests['event_choice']=event_request
    state=original['state'];sample=next(f for f in state['source_fragments'].values() if f['event_id']=='e68')
    compact=deepcopy(event_request)
    compact['state']={key:deepcopy(state[key]) for key in ('harness','protocol_id','stage','input_hash','page','scope','source_coverage')}
    compact['state'].update(requirements={FIELD:deepcopy(state['requirements'][FIELD])},
        source_fragments={'e68':dict(id='e68',event_id='e68',actor=event['actor'],kind=event['kind'],text=code,
            source_pointer=event['source_pointer'],native_scope=sample['native_scope'],
            source_slices=[dict(origin='decoded event.text',start=start,end=end) for start,end in SLICES])})
    if complete_schema:
        # Explicit repair arm: retain the original malformed request/receipt,
        # and restore only these validator-required baseline fields separately.
        for key in ('missingness','cutoff_event_id'):compact['state'][key]=deepcopy(state[key])
    requests['compact_code']=compact
    for request in requests.values():
        if len(dumps(request))>120000:raise InputError('Ablation request exceeds bound')
        if request['questions'][FIELD]['instructions']!=original['questions'][FIELD]['instructions']:
            raise InputError('Judgment framing changed')
    return frozen,baseline,provenance,requests


def evaluate(directory='outputs/requirement-httpx-ablation',*,live=False,client=None,max_calls=3,complete_schema=False,arms=None):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be nonnegative')
    selected_arms=tuple(arms) if arms is not None else ARMS
    if not selected_arms or any(arm not in ARMS for arm in selected_arms) or len(set(selected_arms))!=len(selected_arms):
        raise InputError('Invalid ablation arm selection')
    frozen,baseline,provenance,requests=prepared(complete_schema=complete_schema);root=Path(directory);reference=baseline['reference']
    requests={arm:requests[arm] for arm in selected_arms}
    manifest=dict(schema='requirement-httpx-ablation-inputs/1',source_fixture_hash=digest(frozen),source_hash=frozen['source_hash'],
        baseline_request_hash=baseline['request_hash'],baseline_response_hash=baseline['response_hash'],
        reference_hash=digest(reference),code_provenance=provenance,
        request_hashes={arm:digest(request) for arm,request in requests.items()},
        arm_definitions=dict(requirement_only='Exactly the original whole state and candidate choices, with only requirement_3 question.',
            event_choice='Same whole state and singleton question; e68 event replaces fragment choices, with all three original sentinels.',
            compact_code='Same singleton question and event choices; exact recorded class/constants/helpers and original requirement replace the large page state. No counterexample, reproduction, outcome label or bug explanation enters the request.'))
    if complete_schema:manifest['schema_repair']='Restore only baseline missingness and cutoff_event_id in the compact state. Original malformed compact trial remains frozen separately.'
    if selected_arms!=ARMS:manifest['selected_arms']=list(selected_arms)
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:raise InputError('Frozen HTTPX ablation changed')
    write(root/'inputs.json',manifest);write(root/'reference.json',reference)
    for request in requests.values():write(root/'requests'/(digest(request)+'.json'),request)
    model=baseline['request']['model'];client=client or JevClient(model=model)
    if client.model!=model:raise InputError('Client model differs')
    calls=0;results=[]
    for arm in selected_arms:
        request=requests[arm];key=digest(request);path=root/'receipts'/(key+'.json')
        result=dict(arm=arm,request_hash=key,complete=False,error_type=None)
        try:
            if path.exists():
                saved=read(path)
                if saved['request']!=request:raise InputError('Cached ablation request changed')
                response=saved['response']
            elif live and calls<max_calls:
                calls+=1;response=client.transport(request);write(path,dict(request=request,response=response))
            else:results.append(result);continue
            if response.get('model')!=model:raise InputError('Response model differs')
            answers=validate_answers(response,request);selection=answers[FIELD]['value']
            event='e68' if selection=='e68' else request['state']['source_fragments'].get(selection,{}).get('event_id')
            prediction=1 if event=='e68' else None if selection in {'unresolved','unverified_claim'} else 0
            result.update(complete=True,selection=selection,selected_event_id=event,prediction=prediction,reference_match=prediction==1)
        except Exception as error:result['error_type']=type(error).__name__
        results.append(result);print(dumps(result),flush=True)
    report=dict(schema='requirement-httpx-ablation-report/1',input_hash=digest(manifest),reference_hash=digest(reference),new_calls_this_invocation=calls,results=results,
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        scope='Three experimental representation probes on one independently reproduced source defect. All share the same original NDJSON requirement and production8 judgment instructions. No reference/counterexample enters model requests. Original exact8 two-page miss and original e218 witness score remain unchanged; no production change.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-httpx-ablation')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=3)
    parser.add_argument('--complete-schema',action='store_true',help='Use a new output directory; restore validator-required fields in compact state.')
    parser.add_argument('--arm',action='append',choices=ARMS,help='Evaluate only selected arms; may be repeated.')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls,complete_schema=args.complete_schema,arms=args.arm)
    print(dumps({k:v for k,v in report.items() if k!='results'}))
