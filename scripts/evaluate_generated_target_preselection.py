"""Prototype target interval packets using only local selection and native links.

No target relations, work groups, selected work-context frames, or downstream
method decisions are inputs. This is an evaluation prototype, not a fallback.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import method_comparison
from tracker.feedback_assessments import linked_feedback, SOURCE_LINKAGE
from tracker.jev import JevClient, validate_answers
from tracker.schema import digest, dumps, InputError
from tracker.semantic_extraction import checked_span, read, write, source_expression_links
from tracker.semantic_map import evidence


FIXTURES=Path(__file__).resolve().parents[1]/'tests/fixtures'
VERSION='action-target-correspondence/7'


def local_document(run,extraction):
    """The same local-content projection used by the view, before any histories."""
    if extraction['status']!='complete_local_extraction' or extraction['source_hash']!=digest(run):
        raise InputError('Complete local selection for this source is required')
    units=[];relations=[]
    for selected in extraction['units']:
        if selected['status']!='selected':raise InputError('Incomplete selected unit')
        checked_span(run,selected['source'])
        values={k:{'text':v['text'],'evidence':deepcopy(v['evidence'])} if v['status']=='expressed'
                else {'text':'Not expressed','evidence':[]} for k,v in selected['content'].items()}
        work=values.pop('work_target',None)
        if 'target' in values:
            values['requested_target' if selected['activity']=='coordinate' else 'local_target']=values.pop('target')
        values['target']=work or {'text':'No task target expressed' if selected['activity']=='social' else 'Not yet selected','evidence':[]}
        units.append({k:deepcopy(selected[k]) for k in ('id','kind','activity','actor','trajectory_id','source')})
        units[-1]['content']=values
    by_id={u['id']:u for u in units}
    for item in linked_feedback(run,extraction,SOURCE_LINKAGE):
        action=by_id[item['action']['id']];event=item['event'];ref=evidence(run,event['id'])
        units.append(dict(id=item['unit_id'],kind='feedback',activity=None,actor=event['actor'],
            trajectory_id=event['trajectory_id'],source=ref,content=dict(
                summary=dict(text='Recorded environment response to this dispatch.',evidence=[ref]),
                target=deepcopy(action['content']['target']),recorded_response=dict(text=event['text'],evidence=[ref]))))
        relations.append(dict(type='feedback_for',**{'from':item['unit_id'],'to':action['id']}))
    relations.extend(source_expression_links(run,extraction['units']))
    return dict(schema='pre-target-local-evidence/1',run_id=run['id'],source_hash=digest(run),units=units,relations=relations)


def existing_local_selection(run,document):
    """Recover only already selected local fields for legacy annotated controls.

    These cases do not have a saved fresh extraction. This inverse presentation
    conversion adds no new meaning; native linkage is reconstructed separately.
    """
    units=[]
    for original in document['units']:
        if original['kind']=='feedback':continue
        content=deepcopy(original['content'])
        work=content.pop('target',None)
        if 'requested_target' in content:content['target']=content.pop('requested_target')
        elif 'local_target' in content:content['target']=content.pop('local_target')
        if work is not None:content['work_target']=work
        values={k:{**v,'status':'not_expressed' if v['text']=='Not expressed' and not v.get('evidence') else 'expressed'}
                for k,v in content.items()}
        units.append({**{k:deepcopy(original[k]) for k in ('id','kind','activity','actor','trajectory_id','source')},
                      'status':'selected','content':values})
    return dict(status='complete_local_extraction',source_hash=digest(run),units=units)


def records():
    saved=read(FIXTURES/'generated-generalization-target-method-packets.json')
    fresh=read(FIXTURES/'generated-generalization-e2e.json')['cases']
    for row in saved['rows']:
        if row['arm']!='method_evidence_packet':continue
        source=saved['sources'][row['case_id']]['source']
        document=saved['sources'][row['case_id']]['document']
        if row['case_id'] in fresh:
            extraction=fresh[row['case_id']]['selected'];origin='actual complete local extraction'
        else:
            extraction=existing_local_selection(source,document);origin='existing selected local contents reconstructed from saved view; no fresh candidate generation'
        local=local_document(source,extraction)
        previous=saved['requests'][row['request_hash']]
        request=method_comparison.pair_request(source,local,previous['state']['earlier']['unit_id'],
            previous['state']['current']['unit_id'],version=method_comparison.NATIVE_VERSION)
        request['questions']=deepcopy(previous['questions'])
        request['state']['comparison_rule']=request['state']['rule']
        request['state']['harness']=VERSION
        request['state']['stage']='action_targets'
        events={e['id']:e for e in source['events']};cutoff=request['state']['cutoff'];at=events[cutoff['event_id']]
        for ref in request['state']['source_ranges']:
            event=checked_span(source,ref,cutoff)
            if (event['trajectory_id'],event.get('context_id'))!=(at['trajectory_id'],at.get('context_id')):
                raise InputError('Source crosses recorded context')
        changed={k:dict(before=previous['state'].get(k),after=request['state'].get(k))
                 for k in previous['state'].keys()|request['state'].keys() if previous['state'].get(k)!=request['state'].get(k)}
        yield dict(case_id=row['case_id'],event_id=row['event_id'],packet_id=row['packet_id'],
            reference=row['reference'],origin=row['origin'],extraction_origin=origin,
            source=source,extraction=extraction,document=local,request=request,request_hash=digest(request),
            prior_request_hash=row['request_hash'],changed_state=changed,
            evidence_changed_fields=sorted(set(changed)-{'base_map_hash','harness','stage'}))


def evaluate(directory,live=False):
    root=Path(directory);client=JevClient();rows=[];manifest=[]
    for row in records():
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
    report=dict(schema='target-preselection-prototype/1',pairs=sum(len(r['scores']) for r in rows),
        correct=sum(s['correct'] for r in rows for s in r['scores'].values()),results=rows,
        scope='Local selected content and native source links only. Legacy controls reconstruct selected local fields from existing views. No target relations, selected work-context frames or later outcomes are inputs. Development set, not independent accuracy.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


def freeze(directory,destination):
    root=Path(directory);report=read(root/'report.json');requests={};rows=[];sources={}
    for row in report['results']:
        receipt=read(root/row['receipt']);request=receipt['request']
        if digest(request)!=row['request_hash']:raise ValueError('Receipt hash differs')
        validate_answers(receipt['response'],request)
        requests[row['request_hash']]=request
        rows.append({**row,'response':receipt['response']})
        sources[row['case_id']]=read(root/row['case_id']/'source.json')
    write(destination,dict(schema='frozen-target-preselection-prototype/1',pairs=report['pairs'],
        correct=report['correct'],scope=report['scope'],requests=requests,rows=rows,sources=sources))
    return dict(requests=len(requests),invocations=len(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/generated-target-preselection')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live)))
