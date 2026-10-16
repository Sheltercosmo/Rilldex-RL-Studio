"""Bind dispatches to the requested-work version available at dispatch time.

Uses established local contents and work records. The finite candidate pool is
derived from state, without a generative provider or a new activity taxonomy.
Correspondence is not compliance, authorization validity or task success.
"""
from copy import deepcopy
from pathlib import Path

from .schema import InputError,digest,dumps
from .semantic_extraction import request,checked_span,read,write,audit_result,replay_decision
from .requested_work import audit as audit_work

VERSION='requested-work-action-correspondence/1'
BATCH_SIZE=12
POLICY={'schema':'readable-context/2','recent_events':8,'max_event_chars':4000,'extra_ranges':[]}
ROLES={
    'prepares':'Specifically obtains information or establishes a prerequisite for this work. It does not perform the requested operation or examine that operation’s result. Shared subject or generic usefulness alone is insufficient.',
    'attempts':'Dispatch performs all or part of the operation requested by this work, on the corresponding task instance. If the requested work itself is a check, dispatching that check is an attempt at it. This does not establish success or full coverage.',
    'checks':'Dispatch examines the result or progress of this requested operation against an expectation. Checking a prerequisite is prepares; directly doing a check named as the requested work is attempts. A check need not pass.',
    'none':'No supported correspondence to this particular work instance. Related subject matter, compatible tools or an unexpressed possible purpose are insufficient.',
    'unresolved':'A correspondence may exist, but its work instance or role cannot be established from the supplied evidence.'}
EXPLANATIONS={
    'prepares':'Dispatch prepares information or a prerequisite for this requested work.',
    'attempts':'Dispatch attempts this requested operation; success and coverage remain separate.',
    'checks':'Dispatch checks a result or progress of this requested work; outcome remains separate.'}


def source_order(run,ref):
    e=checked_span(run,ref)
    return e['index'],ref['start'],ref['end']


def state_before(run,extraction,work,action):
    """Return the last completed local update before this dispatch, per trajectory."""
    if (work.get('status')!='complete' or work.get('extraction_hash')!=digest(extraction)
            or work.get('source_hash')!=digest(run)):
        raise InputError('Complete source-bound requested work is required')
    units={u['id']:u for u in extraction['units']}
    current=source_order(run,action['source']);prior=[]
    for step in work['steps']:
        u=units[step['unit_id']];position=source_order(run,u['source'])
        if u['trajectory_id']==action['trajectory_id'] and (position[0],position[2])<=(current[0],current[1]):
            prior.append((position,step))
    if not prior:return {'source_unit_id':None,'records':[],'state_hash':digest([])}
    step=max(prior,key=lambda p:p[0])[1];records=deepcopy(step['state_after'])
    if any(r['trajectory_id']!=action['trajectory_id'] for r in records):raise InputError('Cross-trajectory work state')
    for record in records:
        for ref in record['evidence']:checked_span(run,ref,action['source'])
    return {'source_unit_id':step['unit_id'],'records':records,'state_hash':digest(records)}


def candidate_records(work,snapshot):
    pool=[]
    for record in snapshot['records']:
        if record['kind']!='work':continue
        value=deepcopy(record)
        if record['status']=='withdrawn':
            withdrawal=next((c for c in work['changes'] if c['after']['version_id']==record['version_id']),None)
            if not withdrawal or withdrawal['operation']!='withdraw' or not withdrawal['before']:
                raise InputError('Withdrawn work needs its previous requested terms')
            value['requested_before_withdrawal']=deepcopy(withdrawal['before'])
        pool.append(value)
    return pool


def references(value):
    """Read only explicit evidence arrays, including prior requested terms."""
    if isinstance(value,dict):
        for key,child in value.items():
            if key=='evidence':yield from child
            else:yield from references(child)
    elif isinstance(value,list):
        for child in value:yield from references(child)


def compact(value):
    if isinstance(value,dict):
        if {'event_id','start','end','source_pointer','text'}<=set(value):
            return {k:value[k] for k in ('event_id','source_pointer','start','end')}
        return {k:compact(v) for k,v in value.items()}
    if isinstance(value,list):return [compact(v) for v in value]
    return value


def relation_request(run,extraction,work,action,snapshot,pool,policy=None):
    context_policy=deepcopy(policy or POLICY)
    if context_policy.get('schema') not in {'readable-context/1','readable-context/2'}:
        raise InputError('Work correspondence requires readable source context')
    refs=[action['source'],*references(action['content']),*references(snapshot['records']),*references(pool)]
    ranges={(r['event_id'],r['start'],r['end']):{k:r[k] for k in ('event_id','start','end')} for r in refs}
    for ref in refs:checked_span(run,ref,action['source'])
    context_policy['extra_ranges']=[*context_policy.get('extra_ranges',[]),*ranges.values()]
    req=request(run,action['source'],'requested_work_correspondence',
        'Select one correspondence for EACH candidate work record, using the actual dispatched operation, '
        'its readable local meaning and source context at dispatch time. More than one work item may genuinely '
        'share a prerequisite; do not force a single winner or link every related item. '
        'Withdrawn work remains a candidate so a later attempt can be observed; withdrawal alone neither '
        'proves nor disproves a correspondence. Use its previous requested terms to identify the work. '
        'Select none for a different or merely related work instance, unresolved for an indeterminate instance/role. '
        'Conditions are supplied as context, not extra work items. No choice establishes authorization, '
        'compliance with the terms, successful execution, completion, deviation or a cause. '
        'Later events, including action responses and subsequent approvals, are unavailable to this decision.',
        ROLES,context_policy=context_policy,relation_harness=VERSION,
        extraction_hash=digest(extraction),requested_work_hash=digest(work),
        source_state_unit_id=snapshot['source_unit_id'],requested_state_hash=snapshot['state_hash'],
        action_unit_id=action['id'],action_activity=action['activity'],action_content=compact(action['content']),
        current_requested_records=compact(snapshot['records']),candidate_work_records=compact(pool),
        evidence_reference_rule='Source references address exact original codepoint ranges in prefix. Selected meanings are judgments; use the source to check them. No future or cross-trajectory records are supplied.')
    instructions=req['questions']['choice']['instructions']
    req['state']['comparison_rule']=instructions;req['state']['role_definitions']=deepcopy(ROLES)
    req['questions']={r['version_id']:{'type':'choice',
        'instructions':'Apply comparison_rule to action_unit_id and candidate work version '+r['version_id']+'. Use role_definitions in state.',
        'criteria':{k:'Select '+k+' as defined in role_definitions.' for k in ROLES}} for r in pool}
    return req


def build(run,extraction,work,decide,policy=None):
    if extraction.get('status')!='complete_local_extraction':raise InputError('Complete local contents before action correspondence')
    result={'schema':VERSION,'run_id':run['id'],'source_hash':digest(run),'extraction_hash':digest(extraction),
        'requested_work_hash':digest(work),'context_policy':deepcopy(policy or POLICY),'batch_size':BATCH_SIZE,
        'actions':[],'relations':[],
        'limits':'Model-selected correspondence to requested work at dispatch time. Conditions are contextual, not checked for satisfaction. No authorization, fulfillment, compliance, macro behavior or independent accuracy is inferred.'}
    for action in extraction['units']:
        if action['kind']!='action':continue
        snapshot=state_before(run,extraction,work,action);pool=candidate_records(work,snapshot)
        row={'action_unit_id':action['id'],'source_state_unit_id':snapshot['source_unit_id'],
             'requested_state_hash':snapshot['state_hash'],'state_at_dispatch':snapshot['records'],
             'candidate_count':len(pool),'choices':{},'requests':[]}
        result['actions'].append(row)
        if not pool:row['status']='no_prior_selected_requested_work';continue
        for start in range(0,len(pool),BATCH_SIZE):
            batch=pool[start:start+BATCH_SIZE]
            req=relation_request(run,extraction,work,action,snapshot,batch,policy)
            answers,key=decide(req);row['requests'].append(key)
            for record in batch:
                role=answers[record['version_id']]['value'];row['choices'][record['version_id']]=role
                if role not in EXPLANATIONS:continue
                result['relations'].append({'from':action['id'],'to':record['source_unit_id'],
                    'type':role+'_requested_work','basis':'jev_raw_argmax','harness':VERSION,
                    'requested_work_id':record['id'],'requested_work_version_id':record['version_id'],
                    'requested_work_text':record['text'],'requested_status_at_dispatch':record['status'],
                    **({'requested_before_withdrawal':record['requested_before_withdrawal']['text']} if record.get('requested_before_withdrawal') else {}),
                    'explanation':EXPLANATIONS[role],'evidence':[action['source'],*record['evidence']],
                    'request_hash':key,'requested_state_hash':snapshot['state_hash'],
                    'cutoff':{'event_id':action['source']['event_id'],'end':action['source']['end']},
                    'evidence_scope':'Dispatch and record provenance. Not a minimal proof or a judgment of condition satisfaction.'})
        row['status']='inspected'
    return result


def path_for(directory,extraction,work):
    return Path(directory)/'work_correspondence'/extraction['run_id']/f'{digest({"extraction":digest(extraction),"work":digest(work),"version":VERSION})}.json'


def audit(run,extraction,work,result,directory):
    def replay(req):
        key=digest(req);saved=read(Path(directory)/'decisions'/f'{key}.json')
        if saved['request']!=req or saved['response'].get('model')!=req['model']:raise InputError('Work correspondence request/model differs')
        answers=replay_decision(saved)
        if answers!=saved['answers']:raise InputError('Work correspondence differs from raw argmax')
        return answers,key
    if build(run,extraction,work,replay,result['context_policy'])!=result:
        raise InputError('Work correspondence differs from dependency replay')
    return {'actions_reviewed':len(result['actions']),'candidate_pairs':sum(a['candidate_count'] for a in result['actions']),
            'relations':len(result['relations']),'argmax_replayed':True,'completion_inferred':False,
            'semantic_accuracy':'not independently measured'}


def execute(run,extraction,work,engine,policy=None):
    audit_result(run,extraction,engine.directory);audit_work(run,extraction,work,engine.directory)
    result=build(run,extraction,work,engine.decide,policy)
    validation=audit(run,extraction,work,result,engine.directory)
    write(Path(engine.directory)/'work_correspondence_snapshots'/f'{digest(result)}.json',result)
    write(path_for(engine.directory,extraction,work),result)
    return result,validation


def main():
    import argparse
    import getpass
    import os
    from .jev import JevClient
    from .semantic_extraction import Pipeline,FileCandidates
    from .requested_work import path_for as work_path
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('run_id')
    p.add_argument('--context-policy',type=Path);p.add_argument('--audit-only',action='store_true')
    a=p.parse_args()
    if not a.run_id.isalnum():raise InputError('Invalid run ID')
    run=read(a.directory/'runs'/f'{a.run_id}.json');local=read(a.directory/'results'/f'{a.run_id}.json')
    work=read(work_path(a.directory,local))
    audit_result(run,local,a.directory);audit_work(run,local,work,a.directory)
    if a.audit_only:
        print(dumps(audit(run,local,work,read(path_for(a.directory,local,work)),a.directory)));return
    client=JevClient()
    def transport(req):
        if not os.environ.get('JEV_API_KEY'):os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
        return client.transport(req)
    engine=Pipeline(a.directory,FileCandidates(a.directory/'candidates'),transport)
    result,validation=execute(run,local,work,engine,read(a.context_policy) if a.context_policy else None)
    print(dumps({'validation':validation,'calls':engine.calls,'result_hash':digest(result)}))


if __name__=='__main__':main()
