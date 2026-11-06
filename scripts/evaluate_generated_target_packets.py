"""Isolate target packet representation while freezing labels and readable source."""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_generated_target_identity import base_records
from tracker import action_targets, semantic_workspace
from tracker.action_comparison import recorded_fields
from tracker.jev import JevClient, validate_answers
from tracker.readable_context import contains
from tracker.schema import digest, dumps
from tracker.semantic_extraction import checked_span, read, write
from tracker.work_correspondence import references


ARMS=('original','full_selected_content','endpoint_dispatch_views','no_segmentation_rule','combined')


def evidence_for(row,workspaces):
    """Retrieve original saved inputs, never invent replacement interpretations."""
    if row['origin'] in {'fresh_authored_scenario','selected_public_trace'}:
        folder=Path(workspaces)/row['case_id'];config,source=semantic_workspace.load(folder)
        selected=read(folder/'results'/f'{config["run_id"]}.json')
        return source,selected['units']
    if row['origin']=='existing_authored_layer_control':
        from research.method_comparison_trial import CASES, fixture
        source,document=fixture(next(c for c in CASES if 'control_'+c['id']==row['case_id']))
        return source,document['units']
    source_map=read(row['source_path'])
    return source_map['run'],source_map['document']['units']


def transform(original,arm,source,units):
    if arm not in ARMS:raise ValueError('Unknown packet arm')
    request=deepcopy(original);state=request['state'];changes={}
    by_id={u['id']:u for u in units};prefix={e['id']:e for e in state['prefix']}
    endpoint_views=[state['current_action'],*state['prior_actions']]
    if arm in {'full_selected_content','combined'}:
        for endpoint in endpoint_views:
            unit=by_id[endpoint['unit_id']]
            complete=action_targets.compact_local(action_targets.local(unit))['content']
            # Existing selected fields may not be silently rewritten or renamed.
            for key,value in endpoint['content'].items():
                if complete.get(key)!=value:raise ValueError('Saved selected field differs: '+key)
            added={k:v for k,v in complete.items() if k not in endpoint['content']}
            for ref in references({key:unit['content'][key] for key in added}):
                checked_span(source,ref,by_id[state['current_action']['unit_id']]['source'])
                visible=prefix.get(ref['event_id'])
                if visible is None or not contains(visible,ref):
                    raise ValueError('Omitted content citation is not already readable; do not expand source')
            endpoint['content'].update(deepcopy(added))
            if added:changes.setdefault('restored_fields',{})[endpoint['unit_id']]=sorted(added)
        # Do not update current_meaning: this arm isolates the omitted selected
        # endpoint fields rather than changing the already duplicated summary.
    if arm in {'endpoint_dispatch_views','combined'}:
        def native(endpoint):
            ref=endpoint['source'];event=prefix.get(ref['event_id'])
            original_event=next(e for e in source['events'] if e['id']==ref['event_id'])
            whole=ref['start']==0 and ref['end']==len(original_event.get('text',''))
            # Only duplicate fields already in the readable target prefix.
            fields=recorded_fields(event) if event and whole else None
            return dict(unit_id=endpoint['unit_id'],event_id=ref['event_id'],fields=fields,
                        scope='full captured dispatch' if whole else 'partial action span; no whole native attribution')
        state['dispatch_pairs']={p['id']:dict(earlier=deepcopy(p),current=deepcopy(state['current_action']),
                    native_dispatches=[native(p),native(state['current_action'])]) for p in state['prior_actions']}
        changes['explicit_pair_ids']=list(state['dispatch_pairs'])
    if arm in {'no_segmentation_rule','combined'}:
        changes['removed_incidental_rule']=state.pop('rule')
    if request['questions']!=original['questions']:
        raise AssertionError('Labels, criteria or instructions changed')
    for key in ('prefix','subject','context_policy','context_projection','current_meaning','comparison_rule',
                'tool_contracts','tool_catalog','cutoff_event_id','cutoff_codepoint'):
        if state.get(key)!=original['state'].get(key):raise AssertionError('Evidence or interpretation changed: '+key)
    return request,changes


def records(*,focused=False,arms=None,workspaces='outputs/generated-generalization-refined'):
    baseline=read(Path(__file__).resolve().parents[1]/'tests/fixtures/generated-generalization-target-identity.json')
    saved_originals={r['request_hash']:r['response'] for r in baseline['rows'] if r['arm']=='original'}
    for row in base_records(workspaces=workspaces):
        if focused and (row['case_id'],row['event_id'])!=('simulation','e8'):continue
        original_hash=digest(row['request'])
        if original_hash in saved_originals:
            if baseline['requests'][original_hash]!=row['request']:raise ValueError('Original packet differs')
            row={**row,'original_response':saved_originals[original_hash]}
        source,units=evidence_for(row,workspaces)
        for arm in arms or ARMS:
            request,changes=transform(row['request'],arm,source,units)
            yield {**row,'arm':arm,'request':request,'request_hash':digest(request),
                'original_request_hash':digest(row['request']),'source_hash':digest(source),
                'source':source,'selected_units':units,'packet_changes':changes,
                'original_response':row['original_response'] if request==row['request'] else None}


def evaluate(directory,live=False,*,focused=False,arms=None,workspaces='outputs/generated-generalization-refined'):
    root=Path(directory);client=JevClient();rows=[];manifest=[]
    for row in records(focused=focused,arms=arms,workspaces=workspaces):
        folder=root/row['case_id'];path=folder/row['event_id']/row['arm']/(row['request_hash']+'.json')
        source=dict(source=row['source'],selected_units=row['selected_units'])
        if (folder/'source.json').exists() and read(folder/'source.json')!=source:raise ValueError('Frozen source changed')
        write(folder/'source.json',source)
        write(folder/row['event_id']/'reference-review.json',dict(origin=row['origin'],reference=row['reference'],
            source_hash=row['source_hash'],reference_scope=row['reference_scope']))
        manifest.append({k:v for k,v in row.items() if k not in {'request','source','selected_units','original_response'}})
        write(root/'manifest.json',manifest)
        if row['original_response'] is not None:
            response=row['original_response'];write(path,dict(request=row['request'],response=response))
        elif path.exists():
            saved=read(path)
            if saved['request']!=row['request']:raise ValueError('Cached request differs')
            response=saved['response']
        elif live:
            response=client.transport(row['request']);validate_answers(response,row['request'])
            write(path,dict(request=row['request'],response=response))
        else:
            write(path.parent/'request.json',row['request']);continue
        answers=validate_answers(response,row['request'])
        scores={key:dict(expected=expected,prediction=answers[key]['value'],correct=expected==answers[key]['value'])
                for key,expected in row['reference'].items()}
        record={k:v for k,v in row.items() if k not in {'request','source','selected_units','original_response'}}
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
    report=dict(schema='generated-target-packet-ablation/1',groups=groups,results=rows,
        scope='Exact original six-way labels, criteria and question instructions. No source or cutoff changes. Restored selected fields must cite source already in the prefix; endpoint views only duplicate supplied information; segmentation-rule arm removes only the incidental unit rule. Development source review, not independent accuracy.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


def freeze(directory,destination):
    """Preserve actual failures and requests without rerunning a selector."""
    root=Path(directory);report=read(root/'report.json');requests={};rows=[];sources={}
    for row in report['results']:
        receipt=read(root/row['receipt']);request=receipt['request']
        if digest(request)!=row['request_hash']:raise ValueError('Receipt hash differs')
        validate_answers(receipt['response'],request)
        requests[row['request_hash']]=request
        rows.append({**row,'response':receipt['response']})
        sources[row['case_id']]=read(root/row['case_id']/'source.json')
    write(destination,dict(schema='frozen-generated-target-packet-ablation/1',
        groups=report['groups'],scope=report['scope'],requests=requests,rows=rows,sources=sources))
    return dict(requests=len(requests),invocations=len(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/generated-target-packets')
    parser.add_argument('--workspaces',default='outputs/generated-generalization-refined')
    parser.add_argument('--focused',action='store_true',help='Only the rover reroute; four new calls')
    parser.add_argument('--arms',nargs='+',choices=ARMS)
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,focused=args.focused,arms=args.arms,workspaces=args.workspaces)))
