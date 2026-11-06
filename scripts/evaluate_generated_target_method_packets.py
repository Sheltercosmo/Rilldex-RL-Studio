"""Separate method instruction placement from complete source-bound method packets."""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_generated_target_identity import base_records
from tracker import method_comparison, semantic_workspace
from tracker.jev import JevClient, validate_answers
from tracker.readable_context import source_fragments
from tracker.schema import digest, dumps
from tracker.semantic_extraction import checked_span, load_extraction, read, write


ARMS=('method_rule_only','method_evidence_packet')


def source_map(row,workspaces):
    if row['origin'] in {'fresh_authored_scenario','selected_public_trace'}:
        folder=Path(workspaces)/row['case_id'];config,source=semantic_workspace.load(folder)
        document=load_extraction(source,folder,action_target_version=config['action_target_version'],
                                plan_relation_version=config['plan_relation_version'])['document']
        return source,document
    if row['origin']=='existing_authored_layer_control':
        from research.method_comparison_trial import CASES,fixture
        return fixture(next(c for c in CASES if 'control_'+c['id']==row['case_id']))
    data=read(row['source_path']);return data['run'],data['document']


def source_ranges(request):
    state=request['state']
    if 'source_ranges' in state:return deepcopy(state['source_ranges'])
    ranges=[]
    for event in state['prefix']:
        for start,text in source_fragments(event):
            if text:ranges.append(dict(event_id=event['id'],start=start,end=start+len(text),text=text))
    return ranges


def records(*,arms=None,focused=False,workspaces='outputs/generated-generalization-refined'):
    for row in base_records(workspaces=workspaces):
        if focused and (row['case_id'],row['event_id'])!=('simulation','e8'):continue
        source,document=source_map(row,workspaces)
        original=row['request'];current=original['state']['current_action']['unit_id']
        units={u['id']:u for u in document['units']};events={e['id']:e for e in source['events']}
        method_packets={}
        for prior in original['state']['prior_actions']:
            method=method_comparison.pair_request(source,document,prior['unit_id'],current,
                                                  version=method_comparison.NATIVE_VERSION)
            cutoff=method['state']['cutoff'];at=events[cutoff['event_id']]
            for ref in method['state']['source_ranges']:
                event=checked_span(source,ref,cutoff)
                if (event['trajectory_id'],event.get('context_id'))!=(at['trajectory_id'],at.get('context_id')):
                    raise AssertionError('Method source crosses recorded context')
            if 'WITHHELD_FUTURE_RESULT' in dumps(method):raise AssertionError('Future result leaked')
            method_packets[prior['id']]=method
        if len({m['state']['rule'] for m in method_packets.values()})!=1:
            raise AssertionError('Rule-only arm must not depend on selected pair')
        for arm in arms or ARMS:
            if arm=='method_rule_only':
                request=deepcopy(original)
                request['state']['rule']=next(iter(method_packets.values()))['state']['rule']
                outputs=[('page',request,row['reference'],None)]
            elif arm=='method_evidence_packet':
                outputs=[]
                for key,method in method_packets.items():
                    request=deepcopy(method)
                    request['questions']={key:deepcopy(original['questions'][key])}
                    # The original question explicitly says follow comparison_rule.
                    # This exact alias resolves that name without changing any rule
                    # text or the existing method evidence packet.
                    request['state']['comparison_rule']=request['state']['rule']
                    outputs.append((key,request,{key:row['reference'][key]},digest(method)))
            else:raise ValueError('Unknown arm')
            for packet_id,request,reference,method_hash in outputs:
                for key,question in request['questions'].items():
                    if question!=original['questions'][key]:raise AssertionError('Question/criteria changed')
                if arm=='method_rule_only':
                    repaired=deepcopy(request);repaired['state']['rule']=original['state']['rule']
                    if repaired!=original:raise AssertionError('Rule-only changed more than state.rule')
                yield {**row,'arm':arm,'packet_id':packet_id,'request':request,'request_hash':digest(request),
                    'reference':reference,'original_response':None,'source':source,'document':document,
                    'original_request_hash':digest(original),'method_request_hash':method_hash,
                    'source_comparison':dict(target=source_ranges(original),supplied=source_ranges(request),
                        meaning='Exact original ranges; complete method packets can select a different prior interval and earlier cited scopes. No source strings, offsets or labels are rewritten.'),
                    'packet_scope':'Only state.rule differs.' if arm=='method_rule_only' else
                        'Exact method /4 state plus comparison_rule alias of its rule; original target question and criteria for this exact pair. Other page questions are separate requests; no expected answer is supplied.'}


def evaluate(directory,live=False,*,arms=None,focused=False,workspaces='outputs/generated-generalization-refined'):
    root=Path(directory);client=JevClient();rows=[];manifest=[]
    for row in records(arms=arms,focused=focused,workspaces=workspaces):
        folder=root/row['case_id'];packet=folder/row['event_id']/row['arm']/row['packet_id']
        path=packet/(row['request_hash']+'.json')
        inputs=dict(source=row['source'],document=row['document'])
        if (folder/'source.json').exists() and read(folder/'source.json')!=inputs:raise ValueError('Source snapshot changed')
        write(folder/'source.json',inputs)
        manifest.append({k:v for k,v in row.items() if k not in {'request','original_response','source','document'}})
        write(root/'manifest.json',manifest)
        if path.exists():
            saved=read(path)
            if saved['request']!=row['request']:raise ValueError('Cached request changed')
            response=saved['response']
        elif live:
            response=client.transport(row['request']);validate_answers(response,row['request'])
            write(path,dict(request=row['request'],response=response))
        else:
            write(packet/'request.json',row['request']);continue
        answers=validate_answers(response,row['request'])
        scores={key:dict(expected=expected,prediction=answers[key]['value'],correct=expected==answers[key]['value'])
                for key,expected in row['reference'].items()}
        record={k:v for k,v in row.items() if k not in {'request','original_response','source','document'}}
        record.update(receipt=str(path.relative_to(root)),scores=scores);rows.append(record)
        write(root/'partial-results.json',rows)
        print(row['case_id'],row['event_id'],row['arm'],dumps({k:s['prediction'] for k,s in scores.items()}),flush=True)
    groups={}
    for row in rows:
        group=groups.setdefault(row['arm'],dict(requests=0,pairs=0,correct=0,failures=[]))
        group['requests']+=1
        for key,score in row['scores'].items():
            group['pairs']+=1;group['correct']+=score['correct']
            if not score['correct']:group['failures'].append('/'.join([row['case_id'],row['event_id'],key]))
    report=dict(schema='generated-target-method-packet-ablation/1',groups=groups,results=rows,
        scope='Original target six-way labels and question wording. Rule-only is a one-field change; full method packets also change source selection and endpoint/context representation. Development controls, not an independent accuracy estimate. No production fallback or changes.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


def freeze(directory,destination):
    """Freeze source, maps and actual decisions for offline semantic review."""
    root=Path(directory);report=read(root/'report.json');requests={};rows=[];sources={}
    for row in report['results']:
        receipt=read(root/row['receipt']);request=receipt['request']
        if digest(request)!=row['request_hash']:raise ValueError('Receipt hash differs')
        validate_answers(receipt['response'],request)
        requests[row['request_hash']]=request
        rows.append({**row,'response':receipt['response']})
        sources[row['case_id']]=read(root/row['case_id']/'source.json')
    write(destination,dict(schema='frozen-generated-target-method-packet-ablation/1',
        groups=report['groups'],scope=report['scope'],requests=requests,rows=rows,sources=sources))
    return dict(requests=len(requests),invocations=len(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/generated-target-method-packets')
    parser.add_argument('--workspaces',default='outputs/generated-generalization-refined')
    parser.add_argument('--focused',action='store_true')
    parser.add_argument('--arms',nargs='+',choices=ARMS)
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,arms=args.arms,focused=args.focused,workspaces=args.workspaces)))
