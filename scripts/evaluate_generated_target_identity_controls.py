"""Fresh explicit-identity contrasts after the ambiguous booking reference review."""
from copy import deepcopy
from pathlib import Path
import argparse
import getpass
import os
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import action_target_intervals as intervals, action_targets
from tracker.adapters import normalize
from tracker.jev import JevClient,validate_answers
from tracker.schema import digest,dumps
from tracker.semantic_extraction import read,write
from tracker.semantic_map import evidence

CASES=(
    dict(id='created_record_readback',before=dict(request_id='R7',candidate_time='18:30'),after_tool='booking',after=dict(record_id='B17'),
         feedback='{"status":"created","request_id":"R7","record_id":"B17","time":"18:30"}',expected='different_work_same_subject',
         review='The first call creates B17 and the second reads that exact returned record. Same concrete reservation, different immediate operations.'),
    dict(id='other_requested_record_readback',before=dict(request_id='R7',candidate_time='18:30'),after_tool='booking',after=dict(record_id='B42'),
         feedback='{"status":"created","request_id":"R7","record_id":"B17","time":"18:30"}',expected='different_instance',
         review='The earlier call creates record B17 for request R7. The current call explicitly reads separate record B42 for request R8. Concrete referents differ; no shared reservation is implied.'),
    dict(id='same_request_permitted_fallback',before=dict(request_id='R7',candidate_time='18:00'),after_tool='reserve',after=dict(request_id='R7',candidate_time='18:30'),
         feedback='{"status":"unavailable","request_id":"R7","candidate_time":"18:00","reservation_created":false,"permitted_remaining_times":["18:30"]}',expected='same_work_target',
         review='Both dispatches fulfill the same one-booking request R7. Its declared slot alternatives are 18:00 and 18:30, and the native operation contract identifies candidate_time as a permitted choice within that request.'),
    dict(id='separate_requests_same_slot',before=dict(request_id='R7',candidate_time='18:30'),after_tool='reserve',after=dict(request_id='R8',candidate_time='18:30'),
         feedback='{"status":"created","request_id":"R7","record_id":"B17","time":"18:30"}',expected='different_instance',
         review='R7 and R8 are explicitly independent booking requests, even though their chosen time is identical.'),
)


def records():
    tools=[dict(type='function',function=dict(name='reserve',description='Fulfill one logical booking request identified by request_id. candidate_time selects one of the times permitted within that same request; changing that choice does not create a second request. A successful response returns the concrete reservation record_id.',parameters=dict(type='object'))),
           dict(type='function',function=dict(name='booking',description='Read the existing concrete reservation named by record_id. Does not create or modify a reservation.',parameters=dict(type='object')))]
    for case in CASES:
        raw=dict(tools=tools,messages=[
            dict(role='user',content='R7 and R8 are independent requests for two separate reservations. R7 permits either 18:00 or 18:30 for one reservation. R8 permits 18:30. Existing record B42 belongs to R8.'),
            dict(role='assistant',content=None,tool_calls=[dict(id='call1',type='function',function=dict(name='reserve',arguments=dumps(case['before'])))]),
            dict(role='tool',tool_call_id='call1',content=case['feedback']),
            dict(role='assistant',content=None,tool_calls=[dict(id='call2',type='function',function=dict(name=case['after_tool'],arguments=dumps(case['after'])))])])
        source=normalize(raw)[0];units=[];initial=source['events'][0]
        for event in source['events']:
            if event['kind']!='action':continue
            ref=evidence(source,event['id'])
            units.append(dict(id='u-'+event['id'],kind='action',activity='inspect' if event['tool']=='booking' else 'construct',
                actor=event['actor'],trajectory_id=event['trajectory_id'],source=ref,status='selected',content=dict(
                    summary=dict(status='expressed',text=event['text'],evidence=[ref]),
                    work_target=dict(status='expressed',text='Carry out the named operation for the explicit request or record in these arguments.',evidence=[ref,evidence(source,initial['id'])]))))
        extraction=dict(status='complete_local_extraction',source_hash=digest(source),run_id=source['id'],units=units)
        document=intervals.local_document(source,extraction);prior,current=units
        request=intervals.request(source,document,current,dict(id='a0',**action_targets.local(prior)))
        yield dict(case_id=case['id'],source=source,extraction=extraction,document=document,request=request,request_hash=digest(request),
            reference={'a0':case['expected']},source_review=case['review'],
            origin='Authored explicit-identity source controls and source-bound local summaries, reviewed before calls; not independently sampled end-to-end accuracy.')


def evaluate(directory,live=False):
    root=Path(directory);client=JevClient();rows=[];manifest=[]
    for row in records():
        path=root/row['case_id']/(row['request_hash']+'.json')
        write(path.parent/'source.json',{k:row[k] for k in ('source','extraction','document')})
        review={k:v for k,v in row.items() if k not in {'source','extraction','document','request'}}
        write(path.parent/'reference-review.json',review);manifest.append(review);write(root/'manifest.json',manifest)
        if path.exists():
            receipt=read(path)
            if receipt['request']!=row['request']:raise ValueError('Cached packet differs')
            response=receipt['response']
        elif live:
            response=client.transport(row['request']);validate_answers(response,row['request']);write(path,dict(request=row['request'],response=response))
        else:write(path.parent/'request.json',row['request']);continue
        answer=validate_answers(response,row['request'])['a0']['value']
        rows.append({**review,'prediction':answer,'correct':answer==row['reference']['a0'],'receipt':str(path.relative_to(root))})
        write(root/'partial-results.json',rows);print(row['case_id'],answer,flush=True)
    report=dict(schema='target-explicit-identity-controls/1',pairs=len(rows),correct=sum(r['correct'] for r in rows),results=rows)
    write(root/'report.json',report);return {k:v for k,v in report.items() if k!='results'}


def freeze(directory,destination):
    root=Path(directory);report=read(root/'report.json');requests={};rows=[];sources={}
    for row in report['results']:
        receipt=read(root/row['receipt']);request=receipt['request']
        if digest(request)!=row['request_hash']:raise ValueError('Receipt hash differs')
        validate_answers(receipt['response'],request);requests[row['request_hash']]=request
        rows.append({**row,'response':receipt['response']});sources[row['case_id']]=read(root/row['case_id']/'source.json')
    write(destination,dict(schema='frozen-target-explicit-identity-controls/1',pairs=report['pairs'],correct=report['correct'],
        requests=requests,rows=rows,sources=sources))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='outputs/generated-target-identity-controls')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live)))
