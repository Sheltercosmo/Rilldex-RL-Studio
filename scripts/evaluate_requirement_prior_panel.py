"""Exact /7 witness-page regression against previously frozen public references.

The prepared panel reuses historical requirement-role annotations matched to
unchanged source paragraphs. This tests the matcher on selected pages, not a
fresh extraction run or whole-rollout accuracy. Default is cache/export only.
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import requirement_diagnostics as detector
from tracker.diagnostic_worker import CallBudgetReached
from tracker.jev import JevClient
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import Pipeline,read,write,replay_decision


def historical_terms(packet):
    """Saved JSON dict order is not the original term_i question binding."""
    request=packet['request'];answers=replay_decision(packet);result=[]
    if request['state']['stage']!='requirement_extraction':raise InputError('Expected historical role extraction')
    for field in sorted(request['questions'],key=lambda k:int(k.rsplit('_',1)[1])):
        question=request['questions'][field]
        match=re.search(r'instruction paragraph (\S+)\. Treat its text',question['instructions'])
        if match is None:raise InputError('Historical role question has no explicit paragraph binding')
        term=request['state']['instruction_paragraphs'][match.group(1)]
        result.append(dict(question_field=field,term=term,selection=answers[field]['value']))
    return result


def prepared(panel,version=detector.CONFLICT_VERSION):
    panel=Path(panel);manifest=read(panel/'manifest.json');rows=[]
    if manifest.get('validation_status')=='invalid_input_trial':raise InputError('This panel has invalid historical role bindings; use the corrected panel')
    if manifest['protocol']!=detector.protocol(detector.CONFLICT_VERSION):raise InputError('Panel production protocol changed')
    for row in manifest['cases']:
        folder=panel/row['case_id'];source=read(folder/'source.json');reference=read(folder/'reference.json')
        if digest(source)!=row['source_hash'] or digest(reference)!=row['reference_hash']:raise InputError('Panel source or reference changed')
        if row['unmapped_historical_requirements']:raise InputError('Historical requirement roles did not map exactly')
        terms=read(folder/'historical-selected-requirements.json')
        available={t['id']:t for t in detector.criteria(source,version=detector.CONFLICT_VERSION)}
        if any(available.get(t['id'])!=t for t in terms):raise InputError('Historical selected requirement source changed')
        if row.get('historical_role_packet_hashes'):
            lookup={(t['origin'],t.get('event_id'),t.get('display_text',t['text'])):t for t in available.values()};bound=[]
            for key in row['historical_role_packet_hashes']:
                packet=read(folder/'role-source-packets'/(key+'.json'))
                if digest(packet['request'])!=key:raise InputError('Historical role source packet changed')
                for binding in historical_terms(packet):
                    if binding['selection'] not in {'task_requirement','unresolved'}:continue
                    term=binding['term'];bound.append(lookup[(term['origin'],term.get('event_id'),term.get('display_text',term['text']))])
            if terms!=bound:raise InputError('Historical role answers were not bound through their explicit paragraph IDs')
        generated={digest(req):req for req in detector.requests(source,terms,version=detector.CONFLICT_VERSION)
                   if req['state']['page'] in row['witness_pages']}
        if set(generated)!=set(row['historical_selection_request_hashes']):raise InputError('Production witness request set changed')
        requests=[]
        for key in row['historical_selection_request_hashes']:
            request=read(folder/'witness-historical-selection'/(key+'.json'))
            if request!=generated[key]:raise InputError('Exported production request changed')
            requests.append(request)
        if version!=detector.CONFLICT_VERSION:
            if version!=detector.HARNESS_VERSION:raise InputError('Only the same-capture /6 baseline is supported')
            baseline=list(req for req in detector.requests(source,terms,version=version) if req['state']['page'] in row['witness_pages'])
            if len(baseline)!=len(requests):raise InputError('Baseline changed request count')
            optional={'candidate_fragment_ids','candidate_readings','candidate_reading_rule','omitted_candidate_reading_ids'}
            for current,old in zip(requests,baseline):
                if set(current['questions'])!=set(old['questions']):raise InputError('Baseline changed questions')
                for field,q in old['questions'].items():
                    if current['questions'][field]['criteria']!=q['criteria']:raise InputError('Baseline changed candidate choices')
                left={k:v for k,v in current['state'].items() if k not in optional|{'harness','protocol_id'}}
                right={k:v for k,v in old['state'].items() if k not in {'harness','protocol_id'}}
                if left!=right:raise InputError('Baseline changed canonical source or context')
            requests=baseline
        rows.append(dict(case=row,reference=reference,requests=requests))
    return manifest,rows


def evaluate(panel='outputs/requirement-prior-corrected-panel',directory='outputs/requirement-prior-corrected-live',*,live=False,client=None,max_calls=7,
             version=detector.CONFLICT_VERSION,reuse_directory=None):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be a nonnegative integer')
    manifest,rows=prepared(panel,version);root=Path(directory);protocol=detector.protocol(version)
    frozen=dict(schema='requirement-prior-panel-inputs/1',panel_manifest_hash=digest(manifest),protocol=protocol,
        rows=[dict(case_id=r['case']['case_id'],source_hash=r['case']['source_hash'],reference_hash=r['case']['reference_hash'],
                   request_hashes=[digest(req) for req in r['requests']]) for r in rows])
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=frozen:raise InputError('Frozen panel validation changed')
    write(root/'inputs.json',frozen);write(root/'references.json',{r['case']['case_id']:r['reference'] for r in rows})
    for row in rows:
        for request in row['requests']:write(root/'requests'/(digest(request)+'.json'),request)
    client=client or JevClient(model=protocol['model'])
    if client.model!=protocol['model']:raise InputError('Model differs from panel')
    calls,results=0,[]
    for row in rows:
        case=row['case'];reference=row['reference'];observations=[];error_type=None;complete=True
        def transport(request):
            nonlocal calls
            if not live or calls>=max_calls:raise CallBudgetReached()
            calls+=1;response=client.transport(request)
            write(root/'receipts'/(digest(request)+'.json'),dict(request=request,response=response))
            return response
        engine=Pipeline(root/'cases'/case['case_id'],None,transport,
            cache_directories=[Path(reuse_directory)/'cases'/case['case_id']] if reuse_directory else ())
        try:
            for request in row['requests']:
                answers,key=engine.decide(request)
                observations.append(dict(request_hash=key,page=request['state']['page'],
                    answers={field:dict(selection=a['value'],event_id=request['state']['source_fragments'].get(a['value'],{}).get('event_id')) for field,a in answers.items()}))
        except CallBudgetReached:complete=False
        except Exception as error:complete=False;error_type=type(error).__name__
        selections=[a for obs in observations for a in obs['answers'].values()]
        selected=sorted({a['event_id'] for a in selections if a['event_id']})
        unresolved=sum(a['selection']=='unresolved' for a in selections)
        target=bool(set(selected)&set(case['target_events']))
        if 'expected_candidate' in reference:expected=reference['expected_candidate']
        elif reference.get('expected')=='requirement_conflict':expected=True
        else:expected=any(r['expectation'] not in {'none','unresolved','inspect'} for r in reference.values())
        # Negative public labels concern only the fixed target behavior. Keep
        # every other selection visible and withhold agreement on unresolved.
        match=(target==expected) if complete and (target or not unresolved) else None
        record=dict(case_id=case['case_id'],kind=case['kind'],complete=complete,error_type=error_type,
            expected_target_conflict=expected,target_events=case['target_events'],target_selected=target,
            selected_event_ids=selected,unresolved_questions=unresolved,reference_match=match,observations=observations)
        results.append(record);print(dumps(record),flush=True)
    report=dict(schema='requirement-prior-panel-report/1',protocol=protocol,panel_manifest_hash=digest(manifest),
        new_calls_this_invocation=calls,case_count=len(rows),results=results,
        status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        reference_matches=sum(r['reference_match'] is True for r in results),unresolved_comparisons=sum(r['reference_match'] is None for r in results),
        scope=manifest['scope'],limits=manifest['limits'],
        role_selection='Frozen historical role annotations mapped exactly, not fresh role extraction or exact extraction receipt reuse.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel',default='outputs/requirement-prior-corrected-panel')
    parser.add_argument('--output',default='outputs/requirement-prior-corrected-live')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=7)
    parser.add_argument('--version',choices=(detector.CONFLICT_VERSION,detector.HARNESS_VERSION),default=detector.CONFLICT_VERSION)
    parser.add_argument('--reuse',type=Path,help='Reuse only exact request matches from another panel run')
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.panel,args.output,live=args.live,max_calls=args.max_calls,version=args.version,reuse_directory=args.reuse)
    print(dumps({k:v for k,v in report.items() if k not in {'results','protocol'}}))
