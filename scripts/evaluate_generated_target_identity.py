"""Separate target-label competition from immediate-result framing.

All arms retain the exact target packet's source, native fields, selected local
content, candidate inventory and cutoff. References never enter model requests.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_generated_target_scope import records as generated_records
from tracker import action_scope_pages, action_targets
from tracker.jev import JevClient, validate_answers
from tracker.method_comparison import DISPATCH_WORK_RULE, WORK_CHOICES
from tracker.schema import digest, dumps
from tracker.semantic_extraction import read, write


DEFAULT_ARMS=('original','binary_identity','result_identity')
ARMS=(*DEFAULT_ARMS,'result_six_way','method_packet')
NEGATIVES=('different_work_same_subject','different_instance','unrelated','partial_work_overlap')
METHOD_LABELS={'same_work_instance':'same_work_target','different_work':'not_same','unresolved_work':'unresolved'}
AUTHORED={'revised_search':'same_work_target','different_route':'same_work_target',
          'different_algorithm':'same_work_target','opaque_operations':'unresolved'}
PUBLIC_PAIRS=(('e13','e34'),('e40','e46'))


def identity(choice):
    return 'not_same' if choice in NEGATIVES else choice


def base_records(*,include_controls=True,workspaces='outputs/generated-generalization-refined'):
    for row in generated_records(workspaces):
        if row['arm']!='original':continue
        yield {**row,'origin':'selected_public_trace' if row['case_id'].startswith('public_') else 'fresh_authored_scenario',
               'reference_scope':'Development source review of generated contents; labels stored separately from requests.'}
    if not include_controls:return
    from research.method_comparison_trial import CASES, fixture
    for case in CASES:
        if case['id'] not in AUTHORED:continue
        source,document=fixture(case)
        prior,current=[u for u in document['units'] if u['kind']=='action']
        req=action_scope_pages.request(source,current,[dict(id='a0',**action_targets.local(prior))])
        if 'WITHHELD_FUTURE_RESULT' in dumps(req):raise AssertionError('Future result leaked')
        yield dict(case_id='control_'+case['id'],event_id=current['source']['event_id'],arm='original',
            request=req,reference={'a0':AUTHORED[case['id']]},original_response=None,
            origin='existing_authored_layer_control',source_hash=digest(source),
            reference_scope='Existing source-bound authored method contrast. Shared target summaries are authored, not fresh generated outputs; judge using exact dispatch source.')
    baseline=Path('research/method-comparison-dispatch-2026-10-08/airline/baseline.json')
    saved=read(baseline);source=saved['run'];document=saved['document']
    actions={u['source']['event_id']:u for u in document['units'] if u['kind']=='action'}
    for earlier,later in PUBLIC_PAIRS:
        prior,current=actions[earlier],actions[later]
        req=action_scope_pages.request(source,current,[dict(id='a0',**action_targets.local(prior))])
        yield dict(case_id='recorded_airline_'+earlier+'_'+later,event_id=later,arm='original',
            request=req,reference={'a0':'same_work_target'},original_response=None,
            origin='selected_public_trace_existing_annotation',source_hash=digest(source),
            source_path=str(baseline),reference_scope=(
                'AgentProcessBench tau2_airline record750. Identical route/date flight search; '
                'or same passenger/flights/booking scope with changed payment allocation. '
                'Existing source-bound summaries are retained unchanged. Selected development pairs, not an independent sample.'))


def transform(original,arm):
    request=deepcopy(original)
    if arm=='original':return request
    if arm not in ARMS:raise ValueError('Unknown arm')
    if arm=='binary_identity':
        rule=request['state']['comparison_rule']
        for label in NEGATIVES:rule=rule.replace(label,'not_same')
        request['state']['comparison_rule']=rule
        for question in request['questions'].values():
            original_choices=question['criteria']
            question['criteria']={
                'same_work_target':original_choices['same_work_target'],
                'not_same':'At least one of these nonidentity relationships is established:\n'+
                    '\n'.join(original_choices[label] for label in NEGATIVES),
                'unresolved':original_choices['unresolved'],
            }
    elif arm=='result_identity':
        rule=DISPATCH_WORK_RULE
        for label,replacement in METHOD_LABELS.items():rule=rule.replace(label,replacement)
        request['state']['comparison_rule']=rule
        choices={METHOD_LABELS[label]:meaning for label,meaning in WORK_CHOICES.items()}
        for question in request['questions'].values():question['criteria']=deepcopy(choices)
    elif arm=='result_six_way':
        request['state']['comparison_rule']=DISPATCH_WORK_RULE.replace('same_work_instance','same_work_target').replace(
            'unresolved_work','unresolved').replace('different_work','the appropriate nonidentity relationship')
        for question in request['questions'].values():
            question['criteria']['same_work_target']=WORK_CHOICES['same_work_instance']
            question['instructions']+=' Use the supplied criteria to distinguish the nonidentity relationship subtypes; partial scope stays partial_work_overlap.'
    elif arm=='method_packet':
        raise ValueError('method_packet requires a saved method request; use records()')
    # Only relationship decision framing differs; the entire readable source and
    # native/semantic endpoint representations are byte-equivalent JSON values.
    before=deepcopy(original['state']);after=deepcopy(request['state'])
    before.pop('comparison_rule');after.pop('comparison_rule')
    if before!=after:raise AssertionError('An ablation changed evidence')
    return request


def method_packet(original, directory='outputs/generated-method-recall/simulation'):
    root=Path(directory);inputs=read(root/'input.json');result=read(root/'report.json')['result']
    units={u['id']:u['source']['event_id'] for u in inputs['document']['units']}
    pair=next(r for r in result['observations'] if
              (units[r['previous_unit_id']],units[r['current_unit_id']])==('e4','e8'))
    saved=read(root/'decisions'/f'{pair["work_request"]}.json')['request']
    if set(saved['questions'])!={'work_instance'}:raise ValueError('Expected independent method work-instance request')
    request=deepcopy(saved)
    request['questions']={'a0':dict(type='choice',
        instructions='Classify CURRENT versus EARLIER using the supplied target relationship criteria. Each choice applies to these exact recorded operations.',
        criteria=deepcopy(original['questions']['a0']['criteria']))}
    return request,dict(method_request_hash=pair['work_request'],method_request_path=str(root/'decisions'/f'{pair["work_request"]}.json'),
        scope='Exact saved method work-instance state with target six-way criteria. Source representation and selected scope differ from target packets, so this is a packet-level contrast, not equal-source evidence.')


def records(*,include_controls=True,workspaces='outputs/generated-generalization-refined',arms=None):
    for row in base_records(include_controls=include_controls,workspaces=workspaces):
        for arm in arms or DEFAULT_ARMS:
            metadata={}
            if arm=='method_packet':
                if row['case_id']!='simulation' or row['event_id']!='e8':continue
                request,metadata=method_packet(row['request'])
            else:request=transform(row['request'],arm)
            yield {**row,'arm':arm,'request':request,'request_hash':digest(request),
                   'original_response':row['original_response'] if arm=='original' else None,**metadata}


def evaluate(directory,live=False,*,include_controls=True,workspaces='outputs/generated-generalization-refined',arms=None):
    root=Path(directory);client=JevClient();rows=[];references=[]
    for row in records(include_controls=include_controls,workspaces=workspaces,arms=arms):
        path=root/row['case_id']/row['event_id']/row['arm']/(row['request_hash']+'.json')
        references.append({k:v for k,v in row.items() if k not in {'request','original_response'}})
        write(root/'references.json',references)
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
        answers=validate_answers(response,row['request']);scores={}
        for key,reference in row['reference'].items():
            answer=answers[key];raw=answer['value'] if answer['status']=='decided' else answer['status']
            prediction=identity(raw);expected=identity(reference)
            scores[key]=dict(expected_target_relation=reference,expected_identity=expected,
                raw_prediction=raw,prediction=prediction,correct=prediction==expected)
            if row['arm'] in {'original','result_six_way','method_packet'}:
                scores[key]['relation_correct']=raw==reference
        record={k:v for k,v in row.items() if k not in {'request','original_response'}}
        record.update(receipt=str(path.relative_to(root)),scores=scores);rows.append(record)
        write(root/'partial-results.json',rows)
        print(row['case_id'],row['arm'],dumps({k:s['raw_prediction'] for k,s in scores.items()}),flush=True)
    groups={}
    for row in rows:
        for grouping in [row['arm'],row['origin']+'/'+row['arm']]:
            group=groups.setdefault(grouping,dict(requests=0,pairs=0,correct=0,positive_pairs=0,
                missed_identities=0,false_identities=0,unknown_pairs=0,failures=[],
                full_relation_pairs=0,full_relation_correct=0,full_relation_failures=[]))
            group['requests']+=1
            for key,score in row['scores'].items():
                group['pairs']+=1;group['correct']+=score['correct']
                group['positive_pairs']+=score['expected_identity']=='same_work_target'
                group['unknown_pairs']+=score['expected_identity']=='unresolved'
                group['missed_identities']+=score['expected_identity']=='same_work_target' and score['prediction']!='same_work_target'
                group['false_identities']+=score['expected_identity']!='same_work_target' and score['prediction']=='same_work_target'
                if not score['correct']:group['failures'].append('/'.join([row['case_id'],row['event_id'],key]))
                if 'relation_correct' in score:
                    group['full_relation_pairs']+=1;group['full_relation_correct']+=score['relation_correct']
                    if not score['relation_correct']:group['full_relation_failures'].append('/'.join([row['case_id'],row['event_id'],key]))
    report=dict(schema='generated-target-identity-ablation/1',model=client.model,groups=groups,results=rows,
        scope='Identity-only diagnostic, not six-way relationship accuracy. Original native fields, source, summaries, candidates and cutoffs stay fixed. Collapsed-label arm preserves original meanings; result-identity arm intentionally changes decision framing/criteria. Existing authored and selected public positive controls are reported separately. No production behavior is changed.')
    write(root/'report.json',report)
    return {k:v for k,v in report.items() if k!='results'}


def freeze(directory,destination):
    root=Path(directory);report=read(root/'report.json');requests={};rows=[]
    for row in report['results']:
        saved=read(root/row['receipt']);key=digest(saved['request'])
        if key!=row['request_hash']:raise ValueError('Receipt hash differs')
        requests[key]=saved['request']
        rows.append({**{k:v for k,v in row.items() if k!='receipt'},'response':saved['response']})
    write(Path(destination),dict(schema='generated-target-identity-evidence/1',requests=requests,
        rows=rows,groups=report['groups'],scope=report['scope']))
    return dict(requests=len(requests),invocations=len(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/generated-target-identity')
    parser.add_argument('--workspaces',default='outputs/generated-generalization-refined')
    parser.add_argument('--no-controls',action='store_true')
    parser.add_argument('--arms',nargs='+',choices=ARMS)
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output,args.live,include_controls=not args.no_controls,workspaces=args.workspaces,arms=args.arms)))
