"""Evaluate exact target/7 requests plus source-declared tool meaning controls."""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import action_target_intervals as intervals, action_targets
from tracker.adapters import normalize
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest, dumps
from tracker.semantic_extraction import read, write
from tracker.semantic_map import evidence

FIXTURE=Path(__file__).resolve().parents[1]/'tests/fixtures/generated-generalization-target-preselection.json'


def declared_controls():
    """Same encoded calls with meaning supplied or withheld at capture time."""
    for name,meaning,expected in (
        ('declared_same_result','B8 retrieves the same complete record using the fallback storage backend.','same_work_target'),
        ('declared_different_work','B8 updates the stored record to its default state. It does not retrieve a record.','different_work_same_subject'),
        ('undeclared_operations',None,'unresolved')):
        raw=dict(messages=[
            dict(role='user',content='Continue the harness operations on record R7.'),
            dict(role='assistant',content=None,tool_calls=[dict(id='c1',type='function',function=dict(name='dispatch',arguments='{"op":"A3","record":"R7"}'))]),
            dict(role='tool',tool_call_id='c1',content='Temporary backend failure; no result.'),
            dict(role='assistant',content=None,tool_calls=[dict(id='c2',type='function',function=dict(name='dispatch',arguments='{"op":"B8","record":"R7"}'))])])
        if meaning:
            raw['tools']=[dict(type='function',function=dict(name='dispatch',description='A3 retrieves the complete stored record identified by record. '+meaning,
                parameters=dict(type='object',properties=dict(op=dict(type='string',enum=['A3','B8']),record=dict(type='string')),required=['op','record']))) ]
        source=normalize(raw)[0];units=[]
        for event in source['events']:
            if event['kind']!='action':continue
            ref=evidence(source,event['id'])
            units.append(dict(id='control-'+event['id'],kind='action',activity=None,actor=event['actor'],trajectory_id=event['trajectory_id'],
                source=ref,status='selected',content=dict(
                    summary=dict(status='expressed',text='Dispatch the recorded harness operation on record R7.',evidence=[ref]),
                    work_target=dict(status='expressed',text='The operation and record are given in the dispatched arguments; operation semantics require the recorded declaration.',evidence=[ref]))))
        extraction=dict(run_id=source['id'],source_hash=digest(source),status='complete_local_extraction',units=units)
        prior,current=units
        yield dict(case_id=name,event_id=current['source']['event_id'],packet_id='a0',source=source,extraction=extraction,
            reference={'a0':expected},prior_unit_id=prior['id'],current_unit_id=current['id'],
            origin='authored tool-contract contrast; activity intentionally unclassified to isolate declared operation semantics; not end-to-end generated accuracy')


def records(include_controls=True):
    fixture=read(FIXTURE);cases=[]
    for row in fixture['rows']:
        case=fixture['sources'][row['case_id']];old=fixture['requests'][row['request_hash']]
        cases.append(dict(case_id=row['case_id'],event_id=row['event_id'],packet_id=row['packet_id'],
            source=case['source'],extraction=case['extraction'],reference=row['reference'],
            prior_unit_id=old['state']['earlier']['unit_id'],current_unit_id=old['state']['current']['unit_id'],
            origin=row['origin'],previous_request_hash=row['request_hash']))
    if include_controls:cases.extend(declared_controls())
    for row in cases:
        document=intervals.local_document(row['source'],row['extraction'])
        units={u['id']:u for u in row['extraction']['units']}
        prior=dict(id=row['packet_id'],**action_targets.local(units[row['prior_unit_id']]))
        request=intervals.request(row['source'],document,units[row['current_unit_id']],prior)
        yield {**row,'document':document,'request':request,'request_hash':digest(request)}


def evaluate(directory,live=False,include_controls=True):
    root=Path(directory);client=JevClient();rows=[];manifest=[]
    for row in records(include_controls):
        folder=root/row['case_id'];path=folder/row['event_id']/row['packet_id']/(row['request_hash']+'.json')
        inputs={k:row[k] for k in ('source','extraction','document')}
        if (folder/'source.json').exists() and read(folder/'source.json')!=inputs:raise ValueError('Source snapshot differs')
        write(folder/'source.json',inputs)
        record={k:v for k,v in row.items() if k not in {'source','extraction','document','request'}}
        manifest.append(record);write(root/'manifest.json',manifest)
        if path.exists():
            receipt=read(path)
            if receipt['request']!=row['request']:raise ValueError('Cached request differs')
            response=receipt['response']
        elif live:
            response=client.transport(row['request']);validate_answers(response,row['request'])
            write(path,dict(request=row['request'],response=response))
        else:write(path.parent/'request.json',row['request']);continue
        answers=validate_answers(response,row['request'])
        record.update(receipt=str(path.relative_to(root)),scores={k:dict(expected=v,prediction=answers[k]['value'],
            correct=v==answers[k]['value']) for k,v in row['reference'].items()})
        rows.append(record);write(root/'partial-results.json',rows)
        print(row['case_id'],row['event_id'],dumps(record['scores']),flush=True)
    report=dict(schema='target-interval-production-evaluation/1',pairs=sum(len(r['scores']) for r in rows),
        correct=sum(s['correct'] for r in rows for s in r['scores'].values()),results=rows,
        scope='Exact production target/7 reader. Development source-reviewed pairs and separate authored declaration contrasts; not independent population accuracy.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


def freeze(directory,destination):
    root=Path(directory);report=read(root/'report.json');requests={};rows=[];sources={}
    for row in report['results']:
        receipt=read(root/row['receipt']);request=receipt['request']
        if digest(request)!=row['request_hash']:raise ValueError('Receipt hash differs')
        validate_answers(receipt['response'],request);requests[row['request_hash']]=request
        rows.append({**row,'response':receipt['response']});sources[row['case_id']]=read(root/row['case_id']/'source.json')
    write(destination,dict(schema='frozen-target-interval-production/1',pairs=report['pairs'],correct=report['correct'],
        scope=report['scope'],requests=requests,rows=rows,sources=sources))
    return dict(requests=len(requests),invocations=len(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/generated-target-interval-production')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--no-controls',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,not args.no_controls)))
