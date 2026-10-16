"""Relate retained checking requests to dispatches and recorded evidence.

Dispatch correspondence and response sufficiency are separate selections with
different source cutoffs. Neither establishes that the agent communicated an
answer, that a requirement was satisfied, or that the environment is truthful.
"""
from copy import deepcopy
from pathlib import Path

from .schema import InputError,digest,dumps
from .semantic_map import evidence
from .semantic_extraction import request,checked_span,read,write,audit_result,replay_decision
from .requested_work import audit as audit_work,CLAUSE_VERSION
from .work_correspondence import state_before,references,compact,POLICY
from .feedback_assessments import linked_feedback

VERSION='requested-check-evidence/1'
ISOLATED_VERSION='requested-check-evidence/2'
BATCH_SIZE=12
DISPATCH={
    'attempts':'The actual operation examines the specific information/state or performs the test requested by this check. It may retrieve evidence for the check without itself comparing or reporting it. Match the work instance; do not require a successful response or infer hidden intention.',
    'prepares':'The operation specifically establishes a prerequisite for doing this check, but does not yet examine the requested information/state or perform the requested test. Generic usefulness and shared subject are insufficient.',
    'none':'The operation does not have a supported checking/preparation correspondence to this particular request. An unrelated operation can still incidentally return relevant evidence.',
    'unresolved':'The operation, requested instance or correspondence cannot be established from the supplied evidence.'}
RESPONSE={
    'sufficient':'This recorded response supplies the information or test outcome needed to answer the whole requested check for its exact subject and scope. A negative test outcome can be sufficient evidence. This is answer availability in this source, not a passing check, world truth, communication or completed task.',
    'partial':'This response supplies directly relevant facts for part of the requested check on the corresponding instance, but some requested information or necessary scope remains uncovered. A prerequisite, shared topic or different instance alone is not partial answering evidence.',
    'no_answer':'This response supplies no answering evidence for the requested information on the corresponding instance. Examples include only a different entity, an irrelevant payload, or an execution error that leaves the requested fact unknown. This does not prove the answer is unavailable elsewhere.',
    'unresolved':'Response meaning, matching instance, omitted material or scope prevents a supported sufficiency judgment. Missing evidence is not a negative test outcome.'}
ISOLATED_RESPONSE={**RESPONSE,
    'sufficient':RESPONSE['sufficient']+' For a requested value (such as a balance), the value must be supplied for the correct subject. A negative result answers a requested yes/no test; a failed lookup or missing entity does not supply a requested value.',
    'no_answer':RESPONSE['no_answer']+' Finding only another card, or reporting that the requested card is absent, does not answer what the requested card balance is. Do not substitute existence, lookup status or another entity’s value for the requested information.'}
LINKS={
    'attempts':('attempts_requested_check','Dispatch examines information or performs a test corresponding to this requested check; outcome remains separate.'),
    'prepares':('prepares_requested_check','Dispatch establishes a specific prerequisite for the requested check.'),
    'sufficient':('supplies_requested_evidence','This response is selected as supplying the evidence needed to answer the requested check; passing, communication and fulfillment are not inferred.'),
    'partial':('partly_supplies_requested_evidence','This response supplies some answering evidence but does not cover the whole requested check.')}


def candidate_checks(snapshot):
    pool=[];seen=set()
    for record in snapshot['records']:
        if record['status']!='requested':continue
        for clause in record.get('clauses',[]):
            if clause['kind']!='requested_check':continue
            if clause['version_id'] in seen:raise InputError('Duplicate requested-check version')
            seen.add(clause['version_id'])
            pool.append({'record_id':record['id'],'record_version_id':record['version_id'],
                         'trajectory_id':record['trajectory_id'],'clause':deepcopy(clause)})
    return pool


def selection_request(run,extraction,work,action,snapshot,pool,response=None,policy=None,version=VERSION):
    """Response assessment uses the dispatch snapshot, not later requested terms."""
    if response:
        dispatch=checked_span(run,action['source']);event=response['event']
        if (response['action']['id']!=action['id'] or event['kind']!='feedback'
            or not dispatch.get('call_id') or event.get('source_call_id')!=dispatch['call_id']
            or event['trajectory_id']!=action['trajectory_id'] or event['index']<=dispatch['index']
            or event.get('agent_visibility')=='not_established'):
            raise InputError('Response does not bind to this visible dispatch')
    if version not in {VERSION,ISOLATED_VERSION}:raise InputError('Unknown check correspondence version')
    isolated=bool(response and version==ISOLATED_VERSION)
    context_policy=deepcopy(policy or POLICY)
    if context_policy.get('schema') not in {'readable-context/1','readable-context/2','readable-context/3'}:
        raise InputError('Check correspondence requires readable context')
    for ref in [action['source'],*references(action['content']),*references(snapshot['records'])]:
        checked_span(run,ref,action['source'])
    records=[r for r in snapshot['records'] if not isolated or any(c['record_version_id']==r['version_id'] for c in pool)]
    refs=([action['source'],*references(records)] if isolated else
          [action['source'],*references(action['content']),*references(snapshot['records'])])
    ranges={(r['event_id'],r['start'],r['end']):{k:r[k] for k in ('event_id','start','end')} for r in refs}
    context_policy['extra_ranges']=[*context_policy.get('extra_ranges',[]),*ranges.values()]
    cutoff=evidence(run,response['event']['id']) if response else action['source']
    roles=(ISOLATED_RESPONSE if isolated else RESPONSE) if response else DISPATCH
    instructions=(
        'For EACH retained requested-check clause, judge the evidence supplied by THIS recorded response. '
        'Use the request version that existed at dispatch. Earlier context identifies the subject and scope; '
        'do not borrow an earlier answer or an attributed user/agent claim as evidence supplied by this response. '
        'Judge independently of whether the action was intended to check this: relevant evidence can be incidental. '
        'Do not infer a passing test, a successful transaction, an actual shipment, an answer communicated to the user, '
        'or world truth. A negative test result can fully answer a check, while an error can leave its answer unknown. '
        'Account/profile facts do not automatically establish a particular transaction state. Respect omitted '
        'text/media: select unresolved when it prevents the judgment, rather than treating unseen material as absent.'
        if response else
        'For EACH retained requested-check clause, match the actual dispatched operation to that precise check. '
        'Use its operation and local meaning in source context, not adjacency or generic usefulness alone. '
        'Retrieving the specifically requested information can attempt the checking work even before comparison '
        'or reporting; do not require an eventual successful response. Prerequisite work is separate. '
        'No response or later approval is available here. Do not infer hidden intention, fulfillment or correctness.')
    req=request(run,cutoff,'requested_check_response' if response else 'requested_check_dispatch',instructions,roles,
        context_policy=None if response else context_policy,relation_harness=version if response else VERSION,extraction_hash=digest(extraction),
        requested_work_hash=digest(work),requested_state_hash=snapshot['state_hash'],
        source_state_unit_id=snapshot['source_unit_id'],action_unit_id=action['id'],
        action_content=compact(action['content']),candidate_checks=compact(pool),
        state_at_dispatch=compact(records))
    req['state']['comparison_rule']=instructions;req['state']['role_definitions']=deepcopy(roles)
    if response:
        # Local unit extraction protects its whole subject. Here the subject is
        # a potentially huge tool result: protect the dispatch instead and apply
        # the existing source-preserving response projection before transport.
        from .readable_context import project_prefix
        raw=req['state']['prefix'];projected=project_prefix(raw,action['source'],context_policy)
        if isolated:
            allowed={r['event_id'] for r in refs}|{response['event']['id']}
            projected=[e for e in projected if e['id'] in allowed or e['actor'] in {'system','developer'}]
            req['state'].pop('action_content')
            req['state']['dispatch_source']=compact(action['source'])
            req['state']['evidence_rule']='One check, its attributed terms and source references, the actual dispatch, linked response and governing instructions. Other conversation and selected action interpretations are omitted deliberately. Only this response supplies answering facts; terms and instructions identify scope and semantics, not observed fulfillment.'
        included={e['id'] for e in projected}
        req['state'].update(prefix=projected,context_policy=context_policy,
            response_projection='bounded-response-evidence/1',
            omitted_context_event_ids=[e['id'] for e in raw if e['id'] not in included],
            context_limit='Dispatch and requested terms are retained. Responses use bounded readable source ranges; omitted text and unobserved media are not evidence of absence.')
        req['state']['subject']=compact(cutoff)
        supplied=next(e for e in req['state']['prefix'] if e['id']==response['event']['id'])
        req['state']['inspected_response']=deepcopy(supplied)
        req['state']['feedback_unit_id']=response['unit_id']
    req['questions']={c['clause']['version_id']:{'type':'choice',
        'instructions':'Apply comparison_rule to candidate check version '+c['clause']['version_id']+'. Use role_definitions in state.',
        'criteria':{k:'Select '+k+' as defined in role_definitions.' for k in roles}} for c in pool}
    return req


def selected_link(run,action,snapshot,candidate,choice,key,response=None,req=None,version=VERSION):
    kind,explanation=LINKS[choice];clause=candidate['clause']
    source=response['unit_id'] if response else action['id']
    refs=[action['source'],*clause['evidence']]
    if response:refs.insert(0,evidence(run,response['event']['id']))
    result={'from':source,'to':clause['source_unit_id'],'type':kind,'basis':'jev_raw_argmax','harness':version,
        'requested_work_id':candidate['record_id'],'requested_work_version_id':candidate['record_version_id'],
        'requested_work_text':clause['text'],'requested_status_at_dispatch':'requested',
        'check_clause_id':clause['id'],'check_clause_version_id':clause['version_id'],
        'action_unit_id':action['id'],'explanation':explanation,'evidence':deepcopy(refs),
        'request_hash':key,'requested_state_hash':snapshot['state_hash'],
        'cutoff':{'event_id':req['state']['cutoff_event_id'],'end':req['state']['cutoff_codepoint']}}
    if response:
        supplied=req['state']['inspected_response']
        result.update(evidence_sufficiency=choice,omitted_feedback_ranges=deepcopy(supplied.get('omitted_text_ranges',[])),
            evidence_scope='Recorded response availability for this check, not world truth, passing outcome, communication or fulfillment.')
    else:result['evidence_scope']='Dispatch correspondence with no future response evidence.'
    return result


def build(run,extraction,work,decide,policy=None,version=VERSION):
    if version not in {VERSION,ISOLATED_VERSION}:raise InputError('Unknown check correspondence version')
    if extraction.get('status')!='complete_local_extraction' or work.get('schema')!=CLAUSE_VERSION:
        raise InputError('Complete local contents and version 2 condition records are required')
    feedback=linked_feedback(run,extraction)
    result={'schema':version,'run_id':run['id'],'source_hash':digest(run),'extraction_hash':digest(extraction),
        'requested_work_hash':digest(work),'context_policy':deepcopy(policy or POLICY),'batch_size':BATCH_SIZE,
        'actions':[],'relations':[],'limits':'Only retained requested-check clauses. Dispatch role and response sufficiency are independent model selections. No passed check, communicated answer, fulfillment, world truth or independent semantic accuracy is inferred.'}
    for action in extraction['units']:
        if action['kind']!='action':continue
        snapshot=state_before(run,extraction,work,action);pool=candidate_checks(snapshot)
        row={'action_unit_id':action['id'],'requested_state_hash':snapshot['state_hash'],
            'candidates':deepcopy(pool),'dispatch_choices':{},'dispatch_requests':[],'responses':[],
            'status':'inspected' if pool else 'no_prior_retained_requested_checks'}
        result['actions'].append(row)
        if not pool:continue
        responses=[f for f in feedback if f['action']['id']==action['id']]
        if not responses:row['response_status']='no_linked_recorded_response'
        for response in [None,*responses]:
            target={'feedback_unit_id':response['unit_id'],'event_id':response['event']['id'],'choices':{},'requests':[]} if response else row
            if response:row['responses'].append(target)
            batch_size=1 if response and version==ISOLATED_VERSION else BATCH_SIZE
            for start in range(0,len(pool),batch_size):
                batch=pool[start:start+batch_size]
                req=selection_request(run,extraction,work,action,snapshot,batch,response,policy,version)
                answers,key=decide(req)
                target['requests' if response else 'dispatch_requests'].append(key)
                for candidate in batch:
                    cid=candidate['clause']['version_id'];choice=answers[cid]['value']
                    target['choices' if response else 'dispatch_choices'][cid]=choice
                    if choice not in LINKS:continue
                    result['relations'].append(selected_link(run,action,snapshot,candidate,choice,key,response,req,version))
    return result


def path_for(directory,extraction,work,version=VERSION):
    return Path(directory)/'check_correspondence'/extraction['run_id']/f'{digest({"extraction":digest(extraction),"work":digest(work),"version":version})}.json'


def audit(run,extraction,work,result,directory):
    def replay(req):
        key=digest(req);saved=read(Path(directory)/'decisions'/f'{key}.json')
        if saved['request']!=req or saved['response'].get('model')!=req['model']:raise InputError('Check correspondence request/model differs')
        answers=replay_decision(saved)
        if answers!=saved['answers']:raise InputError('Check correspondence differs from raw argmax')
        return answers,key
    if build(run,extraction,work,replay,result['context_policy'],result['schema'])!=result:raise InputError('Check correspondence differs from dependency replay')
    return {'actions_reviewed':len(result['actions']),'candidate_pairs':sum(len(a['candidates']) for a in result['actions']),
            'responses_reviewed':sum(len(a['responses']) for a in result['actions']),'relations':len(result['relations']),
            'argmax_replayed':True,'completion_inferred':False,'semantic_accuracy':'not independently measured'}


def execute(run,extraction,work,engine,policy=None,version=VERSION):
    audit_result(run,extraction,engine.directory);audit_work(run,extraction,work,engine.directory)
    result=build(run,extraction,work,engine.decide,policy,version);validation=audit(run,extraction,work,result,engine.directory)
    write(Path(engine.directory)/'check_correspondence_snapshots'/f'{digest(result)}.json',result)
    write(path_for(engine.directory,extraction,work,version),result)
    return result,validation


def main():
    import argparse,getpass,os
    from .jev import JevClient
    from .semantic_extraction import Pipeline,FileCandidates
    from .requested_work import path_for as work_path
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('run_id');p.add_argument('--audit-only',action='store_true')
    p.add_argument('--version',choices=[VERSION,ISOLATED_VERSION],default=ISOLATED_VERSION)
    a=p.parse_args()
    if not a.run_id.isalnum():raise InputError('Invalid run ID')
    run=read(a.directory/'runs'/f'{a.run_id}.json');local=read(a.directory/'results'/f'{a.run_id}.json');work=read(work_path(a.directory,local))
    audit_result(run,local,a.directory);audit_work(run,local,work,a.directory)
    if a.audit_only:print(dumps(audit(run,local,work,read(path_for(a.directory,local,work,a.version)),a.directory)));return
    client=JevClient()
    def transport(req):
        if not os.environ.get('JEV_API_KEY'):os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
        value=client.transport(req);print(req['state']['stage'],req['state']['subject']['event_id'],flush=True);return value
    engine=Pipeline(a.directory,FileCandidates(a.directory/'candidates'),transport)
    result,validation=execute(run,local,work,engine,version=a.version)
    print(dumps({'validation':validation,'calls':engine.calls,'result_hash':digest(result)}))


if __name__=='__main__':main()
