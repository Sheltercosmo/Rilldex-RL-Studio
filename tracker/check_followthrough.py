"""Inspect later operations against earlier, already selected checking targets.

Retrieval is exhaustive over eligible earlier targets in this recorded run.
It is not a claim that every historical intention remains active. Native
expression/dispatch pairs already inspected by stated_checks are reused.
"""
from copy import deepcopy
from pathlib import Path

from .schema import InputError,digest,dumps
from .semantic_map import evidence
from .semantic_extraction import read,write,checked_span,prefix,audit_result,replay_decision
from .readable_context import project
from .work_correspondence import compact
from .feedback_assessments import linked_feedback
from . import stated_checks

VERSION='later-check-correspondence/1'
POLICY={'schema':'readable-context/2','recent_events':8,'max_event_chars':4000,'extra_ranges':[]}
RULE=('Compare with this HISTORICAL checking target. Retrieval by earlier source order is only a candidate '
      'rule, not evidence of correspondence, continuing intent, active scope, compliance or causation. '
      'Use the exact entity, requested property and work instance. User/agent statements available at dispatch '
      'can resolve references but remain attributed claims. A later change to another subject must not silently '
      'rewrite an explicitly named earlier target. If reference identity cannot be established, select unresolved. '
      'Do not infer success or that a prerequisite/authorization was satisfied. An operation can correspond '
      'to historical work even if that work was subsequently withdrawn; current validity is a separate question.')


def candidates(run,local,stated):
    if (local.get('status')!='complete_local_extraction' or stated.get('source_hash')!=digest(run)
            or stated.get('extraction_hash')!=digest(local)):
        raise InputError('Later checking needs complete local units and their exact checking pass')
    units={u['id']:u for u in local['units']};result=[]
    for item in stated['observations']:
        if 'check' not in item:continue
        owner=units[item['unit_id']];origin=checked_span(run,owner['source'])
        if owner['kind']!='semantic' or owner['actor']!='agent':raise InputError('Checking target must belong to agent prose')
        direct={a['action_unit_id'] for a in item['actions']}
        later=[];reused=[]
        for action in local['units']:
            if action['kind']!='action' or action['status']!='selected':continue
            event=checked_span(run,action['source'])
            if (action['trajectory_id']!=owner['trajectory_id'] or action['actor']!=owner['actor']
                    or (event['index'],action['source']['start'])<(origin['index'],owner['source']['end'])):continue
            (reused if action['id'] in direct else later).append(action)
        result.append({'owner':owner,'item':item,'actions':later,'reused_actions':reused})
    return result


def relation_request(run,local,owner,check,facet,action,response=None):
    # Reuse validated temporal/actor/call bindings and the established one-facet
    # definitions. Only retrieval and the supplied at-dispatch context change.
    req=stated_checks.evidence_request(run,local,owner,check,facet,action,response,stated_checks.ROUTED_VERSION)
    policy=deepcopy(POLICY)
    policy['extra_ranges']=deepcopy(req['state']['context_policy']['extra_ranges'])
    at_dispatch,excluded=prefix(run,action['source'],policy)
    state=req['state'];state.update(stage='later_check_response' if response else 'later_check_dispatch',
        check_harness=VERSION,context_policy=policy,historical_scope=RULE,
        retrieval='All earlier selected checking targets by this actor in this trajectory, excluding previously inspected native pairs.',
        context_cutoff=compact(action['source']))
    state['subject']=compact(state['subject'])
    if response:
        # Resolve target references using attributed instructions/statements
        # available AT DISPATCH, not new terms between dispatch and response.
        # Earlier tool results cannot become material supplied by this response.
        context=[e for e in at_dispatch if e['kind']!='feedback' and
                 (e['kind']!='action' or e['id']==action['source']['event_id'])]
        supplied=project(response['event'],policy,action['source'])
        state.update(prefix=[*context,supplied],inspected_response=supplied,
            scope_context_event_ids=[e['id'] for e in context],
            response_scope='Only inspected_response supplies material. At-dispatch participant statements resolve scope and references but are not returned evidence.',
            excluded_scope_feedback_event_ids=[e['id'] for e in at_dispatch if e['kind']=='feedback'])
    else:state['prefix']=at_dispatch
    state['missingness']['excluded_not_agent_visible']=excluded
    full,_=prefix(run,evidence(run,response['event']['id']) if response else action['source'])
    state['omitted_context_event_ids']=[e['id'] for e in full if e['id'] not in {v['id'] for v in state['prefix']}]
    state['context_limit']='Earlier target and dispatch source retained. Context is bounded; missing identity or omitted material remains unresolved/unobserved, not a negative fact.'
    rules=req['questions']['choice']['instructions']
    # The inherited dispatch text describes native retrieval, which does not
    # apply here. The substantive role definitions are unchanged.
    rules=rules.replace('The source expression/action pairing retrieves candidates only; it does not establish correspondence. ', '')
    req['questions']['choice']['instructions']=RULE+'\n'+rules
    if response:
        req['questions']['choice']['instructions']+='\nDo not use an earlier stated balance, another entity’s value, or an execution error as the requested value supplied by THIS response.'
    return req


def build(run,local,stated,decide):
    pool=candidates(run,local,stated);feedback=linked_feedback(run,local)
    result={'schema':VERSION,'run_id':run['id'],'source_hash':digest(run),'extraction_hash':digest(local),
        'stated_checks_hash':digest(stated),'observations':[],'relations':[],
        'retrieval':'Exhaustive earlier selected checking targets in this recorded run; no keyword, distance or confidence pruning.',
        'limits':RULE+' Coverage depends on upstream selected checking contents. Missed contents remain missed.'}
    for entry in pool:
        owner=entry['owner'];check=entry['item']['check']
        row={'unit_id':owner['id'],'check_id':check['id'],'actions':[],
             'native_pairs_reused':[a['id'] for a in entry['reused_actions']]}
        result['observations'].append(row)
        for action in entry['actions']:
            ar={'action_unit_id':action['id'],'retrieval':'earlier_stated_check','facets':[]};row['actions'].append(ar)
            responses=[f for f in feedback if f['action']['id']==action['id']]
            for facet in check['facets']:
                value={'facet_id':facet['id'],'responses':[]};ar['facets'].append(value)
                if not responses:value['response_status']='no_linked_recorded_response'
                for response in [None,*responses]:
                    req=relation_request(run,local,owner,check,facet,action,response)
                    answers,key=decide(req);choice=answers['choice']['value']
                    if response:
                        supplied=req['state']['inspected_response']
                        value['responses'].append({'feedback_unit_id':response['unit_id'],'event_id':response['event']['id'],
                            'choice':choice,'request':key,'omitted_text_ranges':deepcopy(supplied.get('omitted_text_ranges',[])),
                            'unobserved_media':deepcopy([*supplied.get('unobserved_inline_media',[]),
                                *supplied.get('unobserved_media_parts',[]),*supplied.get('unobserved_auxiliary_media',[])])})
                    else:value.update(dispatch_choice=choice,dispatch_request=key)
                    kind=({'available':'provides_check_material','partial':'partly_provides_check_material'} if response else
                          {'attempts':'attempts_stated_check','prepares':'prepares_stated_check'}).get(choice)
                    if not kind:continue
                    refs=[owner['source'],action['source'],*facet['evidence']]
                    if response:refs.append(evidence(run,response['event']['id']))
                    result['relations'].append({'from':response['unit_id'] if response else action['id'],'to':owner['id'],
                        'type':kind,'basis':'jev_raw_argmax','harness':VERSION,'check_id':check['id'],'check_text':facet['text'],
                        'facet_id':facet['id'],'action_unit_id':action['id'],'request_hash':key,'evidence':deepcopy(refs),
                        'explanation':'Selected correspondence to an earlier checking target. Continuing intent, active scope, authorization and completion are not established.',
                        'retrieval':'earlier_stated_check','cutoff':{'event_id':req['state']['cutoff_event_id'],'end':req['state']['cutoff_codepoint']}})
    return result


def path_for(directory,local,stated):
    return Path(directory)/'check_followthrough'/local['run_id']/f'{digest({"local":digest(local),"checks":digest(stated),"version":VERSION})}.json'


def audit(run,local,stated,result,directory):
    def replay(req):
        key=digest(req);saved=read(Path(directory)/'decisions'/f'{key}.json')
        if saved['request']!=req or saved['response'].get('model')!=req['model']:raise InputError('Later checking request/model changed')
        answers=replay_decision(saved)
        if answers!=saved['answers']:raise InputError('Later checking selection differs from raw argmax')
        return answers,key
    if build(run,local,stated,replay)!=result:raise InputError('Later checking differs from dependency replay')
    return {'selected_checks':len(result['observations']),
        'native_pairs_reused':sum(len(o['native_pairs_reused']) for o in result['observations']),
        'later_action_pairs':sum(len(o['actions']) for o in result['observations']),
        'facet_pairs':sum(len(a['facets']) for o in result['observations'] for a in o['actions']),
        'response_observations':sum(len(f['responses']) for o in result['observations'] for a in o['actions'] for f in a['facets']),
        'relations':len(result['relations']),'argmax_replayed':True,'semantic_accuracy':'not independently measured'}


def execute(run,local,stated,engine):
    audit_result(run,local,engine.directory)
    proposals=read(stated_checks.candidates_path(engine.directory,local))
    stated_checks.audit(run,local,proposals,stated,engine.directory)
    result=build(run,local,stated,engine.decide);validation=audit(run,local,stated,result,engine.directory)
    write(Path(engine.directory)/'check_followthrough_snapshots'/f'{digest(result)}.json',result)
    write(path_for(engine.directory,local,stated),result)
    return result,validation


def main():
    import argparse,getpass,os
    from .jev import JevClient
    from .semantic_extraction import Pipeline,FileCandidates
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);parser.add_argument('run_id')
    parser.add_argument('--audit',action='store_true');args=parser.parse_args()
    if not args.run_id.isalnum():raise InputError('Invalid run identity')
    run=read(args.directory/'runs'/f'{args.run_id}.json');local=read(args.directory/'results'/f'{args.run_id}.json')
    stated=read(stated_checks.path_for(args.directory,local))
    if args.audit:print(dumps(audit(run,local,stated,read(path_for(args.directory,local,stated)),args.directory)));return
    client=JevClient()
    def transport(req):
        if not os.environ.get('JEV_API_KEY'):os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
        value=client.transport(req);print(req['state']['stage'],req['state']['subject']['event_id'],flush=True);return value
    engine=Pipeline(args.directory,FileCandidates(args.directory/'candidates'),transport)
    result,validation=execute(run,local,stated,engine)
    print(dumps({'calls':engine.calls,'validation':validation,'result_hash':digest(result)}))


if __name__=='__main__':main()
