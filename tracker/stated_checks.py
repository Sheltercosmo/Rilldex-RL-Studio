"""Source-bound checking contents of agent contributions, followed by evidence.

Candidate generation is external. Contents do not split or relabel the owning
unit. This pass uses recorded expression/action associations for retrieval,
then asks Jev about correspondence; an association alone is not an attempt.
"""
from copy import deepcopy
from pathlib import Path

from .schema import InputError, digest, dumps
from .semantic_map import evidence
from .semantic_extraction import request, checked_span, read, write, replay_decision, audit_result, source_expression_links
from .work_correspondence import compact, references
from .feedback_assessments import linked_feedback
from .readable_context import project_prefix
from .check_correspondence import DISPATCH, ISOLATED_RESPONSE

VERSION = 'stated-check-evidence/1'
FOCUSED_VERSION = 'stated-check-evidence/2'
MATERIAL_VERSION = 'stated-check-evidence/3'
INTENT_VERSION = 'stated-check-evidence/4'
ROUTED_VERSION = 'stated-check-evidence/5'
MATERIAL_VERSIONS = {MATERIAL_VERSION, INTENT_VERSION, ROUTED_VERSION}
VERSIONS = {VERSION, FOCUSED_VERSION, *MATERIAL_VERSIONS}
CHECKING_INTENT = (
    'Select the checking-content bundle actually expressed by this contribution, or an explicit alternative. '
    'Keep the already selected contribution and activity intact. Identify the requested or intended informational '
    'result, rather than matching words such as check, verify, confirm, question or yes/no. '
    'Checking seeks information or evidence about a claim, state, artifact, condition or test result. '
    'It can be an expressed future/conditional check, or a request for another actor to inspect or report facts. '
    'Requesting NEW permission, a preference, a decision, acceptance of an offer or a commitment to act is '
    'coordination, not a factual check: the reply creates or chooses a course of action. Asking whether permission '
    'was ALREADY granted is factual checking of prior authorization. An interrogative or yes/no form does not '
    'determine this difference. A factual assertion, completion claim or request to construct/change something '
    'alone is not checking. Read the source and local meaning together; the base activity is not an eligibility gate. '
    'If checking is expressed alongside other work, select only a faithful bundle of its checking contents. '
    'A bundle that adds approval, construction or unrelated work is not faithful checking content; choose '
    'no_suitable_candidate if none isolates the expressed check. If the source does not distinguish factual '
    'confirmation from approval, choose unresolved instead of guessing. Facets are parts of one checking expression, '
    'not new units. Preserve target identity, attribution and expressed conditions; invent no criterion, '
    'executed operation, outcome or downstream goal.')
CHECKING_ROLES = {
    'checking_work':'This contribution explicitly requests, proposes, intends or performs acquiring information/evidence or a test. This may coexist with reports or other work. A stated future/conditional check counts; whether it was executed is a separate question.',
    'report_only':'It only reports facts, an earlier check or a known/claimed result, or gives an assurance/confirmation. No new/current checking work is expressed. Saying a check was done is not doing or proposing a check here.',
    'decision_only':'It only requests or supplies a new choice, permission, acceptance or commitment to act; no factual checking work is expressed. Asking whether permission had previously been granted can instead be checking work.',
    'other':'It contains no checking request/intention/procedure, checking-related report/assurance, or decision request of the above kinds.',
    'unresolved':'The current contribution does not make these alternatives distinguishable, including an ambiguous confirmation.'}


def role_request(run, local, owner):
    return request(run,owner['source'],'checking_applicability',
        'Determine the role of CHECKING CONTENT in the CURRENT contribution (state.subject), not in the task '
        'or preceding conversation. Prior context resolves references only: a user’s earlier checking request '
        'must not become a new checking intention in an agent’s answer. Read the contribution’s expressed '
        'operation and time: asking/intending to find out, versus telling what is known or claiming a check '
        'already occurred. A confirmation can be an assurance, an approval, or factual inquiry; its wording '
        'alone does not decide. If actual checking work is explicitly present alongside other content, '
        'select checking_work. Otherwise distinguish report_only, decision_only and other; use unresolved '
        'when context cannot settle the meaning. Do not infer an unrecorded check or split/relabel the base unit.',
        CHECKING_ROLES,context_policy=POLICY,check_harness=ROUTED_VERSION,
        extraction_hash=digest(local),origin_unit_id=owner['id'],unit_content=compact(owner['content']))


def select_contents(run, local, owner, row, proposals, decide, version):
    item={'unit_id':owner['id'],'actions':[]}
    if version==ROUTED_VERSION:
        answer,key=decide(role_request(run,local,owner));role=answer['choice']['value']
        item['applicability']={'choice':role,'request':key}
        if role!='checking_work':
            item.update(selection='route:'+role,selection_request=key,content_selection='not_run')
            return item
    answer,key=decide(content_request(run,local,owner,row,proposals,version))
    item.update(selection=answer['choice']['value'],selection_request=key)
    return item
POLICY = {'schema':'readable-context/2','recent_events':6,'max_event_chars':4000,'extra_ranges':[]}
LINKS = {'attempts':'attempts_stated_check','prepares':'prepares_stated_check',
         'sufficient':'supplies_check_evidence','partial':'partly_supplies_check_evidence'}
MATERIAL_CHOICES = {
    'available':'The recorded response supplies the information, artifact content or test result sought by this single checking target. This describes available material, not correctness or a passing result. An explicit negative test result can be available material.',
    'partial':'The response supplies some of the material sought by this target, but other required material is missing. A prerequisite, another entity or a sibling check alone is not partial material.',
    'absent':'The response supplies none of the information, artifact contents or test outcome sought by this target. A filename alone supplies no file contents. A lookup error can leave a requested value absent. This is absence in this response, not absence in the world or the entire trace.',
    'unobserved':'Relevant material is recorded but requires inspecting omitted text, image pixels or other media that this observer has not inspected. Its contents cannot be judged from the supplied view.',
    'unresolved':'Target identity, requested material scope or the response meaning is too ambiguous to judge material availability. An unspecified acceptance criterion alone is not a reason to select this.'}
SPECIFICATION_CHOICES = {
    'test_defined':'The expression specifies a condition/question to resolve, a comparison, an expected property, or a concrete test procedure. Checking whether a file exists specifies a condition. This does not mean the condition is true or the test passed.',
    'observation_only':'The expression asks to retrieve or inspect named information/material, but does not specify a condition or procedure for judging its correctness or adequacy. Reading values or looking at an artifact is not itself an acceptance test.',
    'unresolved':'The stated basis for judging this check cannot be established from the available expression/context.'}


def derive_candidates(run, local, overrides=None):
    """Reuse selected local meanings for every contribution, without keyword gates.

    An offered work target is a candidate, not automatically checking work.
    Rejection remains a recorded selection. Prior finer-grained proposals may
    be retained with their original provenance; no new generator is implied.
    """
    previous={}
    if overrides:
        validate_candidates(run,local,overrides)
        previous={r['unit_id']:r for r in overrides['units'] if r['candidates']}
    rows=[]
    for unit in local['units']:
        if unit['actor']!='agent' or unit['kind']!='semantic' or unit['status']!='selected':continue
        if unit['id'] in previous:
            rows.append({**deepcopy(previous[unit['id']]),'origin':{'kind':'retained_proposals','producer':overrides['producer'],
                         'proposal_hash':digest(overrides)}});continue
        candidates=[];seen=set()
        for field in ['needed_work','work_target']:
            value=unit['content'].get(field,{})
            if value.get('status')!='expressed' or not value.get('text') or value['text'] in seen:continue
            seen.add(value['text']);refs=[unit['source'],*value.get('evidence',[])]
            refs=list({digest(r):r for r in refs}.values())
            candidates.append({'text':value['text'],'evidence':deepcopy(refs),
                'facets':[{'id':field,'text':value['text'],'evidence':deepcopy(refs)}]})
        rows.append({'unit_id':unit['id'],'candidates':candidates,
                     'origin':{'kind':'selected_local_contents','fields':['needed_work','work_target'],
                               'content_request':unit.get('content_request'),
                               'meaning':'Reused meanings, not inferred checking labels. No keyword or activity filter.'}})
    result={'schema':VERSION,'source_hash':digest(run),'extraction_hash':digest(local),
            'producer':'selected-local-contents/1 with attributed retained proposals',
            'coverage':'All selected agent semantic contributions; extraction correctness and upstream generation remain separate.',
            'units':rows}
    validate_candidates(run,local,result);return result


def specification_request(run, local, owner, check, facet, version=MATERIAL_VERSION):
    policy=deepcopy(POLICY)
    refs=[*check['evidence'],*facet['evidence']]
    for ref in refs:checked_span(run,ref,owner['source'])
    policy['extra_ranges']=[{k:r[k] for k in ('event_id','start','end')} for r in refs]
    return request(run,owner['source'],'check_specification',
        'What basis does the agent EXPRESS for this checking target: '+facet['text']+'\n'
        'Judge the stated specification before any linked operation or response. Do not invent a rubric, '
        'borrow later results, or treat a claim of success as a test. Distinguish a defined condition/procedure '
        'from merely inspecting information. This is not a new activity label or an outcome judgment.',
        SPECIFICATION_CHOICES,context_policy=policy,check_harness=version,
        extraction_hash=digest(local),origin_unit_id=owner['id'],parent_check_id=check['id'],facet=compact(facet))


def validate_candidates(run, local, proposals):
    if (local.get('status') != 'complete_local_extraction' or proposals.get('schema') != VERSION
            or proposals.get('source_hash') != digest(run) or proposals.get('extraction_hash') != digest(local)
            or not proposals.get('producer') or not isinstance(proposals.get('units'), list)):
        raise InputError('Checking candidates need complete local contents and exact dependencies')
    units = {u['id']:u for u in local['units']}; seen = set()
    for row in proposals['units']:
        u = units.get(row.get('unit_id'))
        if not u or u['id'] in seen or u['actor'] != 'agent' or u['kind'] != 'semantic' or u['status'] != 'selected':
            raise InputError('Checking candidates need distinct selected agent contributions')
        seen.add(u['id'])
        candidates = row.get('candidates')
        if not isinstance(candidates, list) or len(candidates) > 3:raise InputError('Offer zero to three coherent checking bundles')
        for bundle in candidates:
            facets = bundle.get('facets')
            if not isinstance(facets, list) or not 1 <= len(facets) <= 12:raise InputError('Checking bundle needs bounded readable facets')
            if len({f.get('id') for f in facets}) != len(facets):raise InputError('Duplicate checking facet')
            for value in [bundle, *facets]:
                if not isinstance(value.get('text'), str) or not value['text'].strip() or len(value['text']) > 4000 or not value.get('evidence'):
                    raise InputError('Checking contents need readable meaning and evidence')
                for ref in value['evidence']:checked_span(run,ref,u['source'])
                if not any(r['event_id'] == u['source']['event_id'] and r['start'] < u['source']['end'] and r['end'] > u['source']['start'] for r in value['evidence']):
                    raise InputError('Checking contents must cite their owning contribution')
            if any(not isinstance(f.get('id'),str) or not f['id'] for f in facets):raise InputError('Checking facets need identities')
    return units


def content_request(run, local, u, row, proposals, version=VERSION):
    policy=deepcopy(POLICY)
    policy['extra_ranges']=[{k:r[k] for k in ('event_id','start','end')} for r in references(row['candidates'])]
    options={f'c{i}':dumps(compact(c)) for i,c in enumerate(row['candidates'])}
    options.update(none='No checking work is expressed by this contribution.',
                   no_suitable_candidate='Checking work is expressed, but none of the offered bundles faithfully captures it.',
                   unresolved='The expressed checking work cannot be established from this source.')
    req=request(run,u['source'],'stated_check_contents',
        'Select the faithful checking-content bundle, or the appropriate explicit alternative. '
        'The owning contribution and its activity are already selected: do not split it or change its label. '
        'Checking work seeks to establish, inspect or confirm information, a state or an artifact. '
        'A factual assertion, claimed success, construction, planned conversion or generic next step is not itself checking work. '
        'Facets are independently inspectable parts of the same expressed check, not new units or additional activities. '
        'Preserve the actual scope; do not invent correctness criteria or turn a broad goal into a specific test.',
        options,context_policy=policy,check_harness=VERSION,extraction_hash=digest(local),
        candidate_hash=digest(proposals),unit_content=compact(u['content']),candidate_bundles=compact(row['candidates']))
    if version in MATERIAL_VERSIONS:
        req['state']['candidate_hash']=digest({'row':row,'producer':proposals['producer']})
        req['state']['candidate_origin']=deepcopy(row.get('origin',{'kind':'external','producer':proposals['producer']}))
        req['state']['check_harness']=version
        req['state']['candidate_dependency_scope']='Only this unit’s candidates and their producer; unrelated proposals do not invalidate this decision.'
    if version in {INTENT_VERSION,ROUTED_VERSION}:
        req['questions']['choice']['instructions']=CHECKING_INTENT
        req['questions']['choice']['criteria']['none']='No factual checking work is expressed here; a request for a new decision/authorization alone is not checking.'
        req['questions']['choice']['criteria']['unresolved']='The source meaning or factual-check versus new-decision distinction cannot be established.'
    if version==ROUTED_VERSION:
        req['questions']['choice']['instructions']+=(
            ' The applicability decision merely opens content extraction; it does not validate any bundle. '
            'Select the acquisition/test work expressed in state.subject. A bundle describing explaining, '
            'answering, reporting, assuring or reconfirming an intended transaction does not describe the '
            'checking work. If the source states a future balance check but every bundle only describes '
            'payment confirmation or requesting an ID, choose no_suitable_candidate. Do not reinterpret '
            'a candidate into a different target. None remains available if no checking work is actually expressed.')
        for i,c in enumerate(row['candidates']):
            req['questions']['choice']['criteria'][f'c{i}']='This bundle faithfully describes the explicitly requested/intended/performed CHECKING WORK in the current contribution: '+dumps(compact(c))
    return req


def evidence_request(run, local, owner, check, facet, action, response=None, version=VERSION):
    if version not in VERSIONS:raise InputError('Unknown stated-check evidence version')
    dispatch=checked_span(run,action['source']); origin=checked_span(run,owner['source'])
    if (owner['actor'] != action['actor'] or owner['trajectory_id'] != action['trajectory_id']
            or (origin['index'],owner['source']['end']) > (dispatch['index'],action['source']['start'])):
        raise InputError('Checking scope must precede the same-actor dispatch')
    if response:
        event=response['event']
        if (response['action']['id'] != action['id'] or not dispatch.get('call_id')
                or event.get('source_call_id') != dispatch['call_id'] or event['kind'] != 'feedback'
                or event['trajectory_id'] != action['trajectory_id'] or event['index'] <= dispatch['index']
                or event.get('agent_visibility') == 'not_established'):
            raise InputError('Checking response must bind to this visible dispatch')
    refs=[owner['source'],action['source'],*check['evidence'],*facet['evidence']]
    for ref in refs:checked_span(run,ref,action['source'])
    policy=deepcopy(POLICY);policy['extra_ranges']=[{k:r[k] for k in ('event_id','start','end')} for r in refs]
    cutoff=evidence(run,response['event']['id']) if response else action['source']
    rules=('Judge only THIS recorded response as evidence for the named checking facet. '
           'The parent check and local contents identify the scope, not proof that it was satisfied. '
           'A listed filename can establish presence; it does not reveal file contents or prove their quality. '
           'Uninspected image pixels or omitted text remain unobserved. Use unresolved when this prevents judgment. '
           'Do not infer world truth, a passing result, completion or communication to the user.' if response else
           'Match the actual dispatched operation to this stated checking facet. The source expression/action pairing '
           'retrieves candidates only; it does not establish correspondence. Retrieving the exact information may attempt '
           'the check; obtaining a prerequisite is preparation. Ignore later results and do not infer hidden intentions.')
    req=request(run,cutoff,'stated_check_response' if response else 'stated_check_dispatch',rules,
        ISOLATED_RESPONSE if response else DISPATCH,context_policy=None if response else policy,
        check_harness=VERSION,extraction_hash=digest(local),check=compact(check),facet=compact(facet),
        origin_actor=owner['actor'],origin_unit_id=owner['id'],origin_activity=owner['activity'],
        action_unit_id=action['id'],dispatch_source=compact(action['source']))
    if response:
        raw=req['state']['prefix'];allowed={r['event_id'] for r in refs}|{response['event']['id']}
        projected=[e for e in project_prefix(raw,action['source'],policy)
                   if e['id'] in allowed or e['actor'] in {'system','developer'}]
        req['state'].update(prefix=projected,subject=compact(cutoff),context_policy=policy,
            inspected_response=next(e for e in projected if e['id']==response['event']['id']),
            omitted_context_event_ids=[e['id'] for e in raw if e['id'] not in {p['id'] for p in projected}],
            feedback_unit_id=response['unit_id'],response_scope='Only the linked response supplies answering facts.')
    if version in {FOCUSED_VERSION,*MATERIAL_VERSIONS}:
        # The full bundle in v1 contaminated judgments about individual parts:
        # e.g. a complete presence check became partial because content was not read.
        req['state'].pop('check')
        req['state']['check_harness']=version
        req['state']['parent_check_id']=check['id']
        req['state']['reference_scope']='Only the single facet below is judged. Other checks in the source are context, not additional requirements for this decision.'
        req['questions']['choice']['instructions']=(
            'Evaluate ONLY this checking target: '+facet['text']+'\n'+rules+
            '\nThe role definitions refer to this target alone. Do not score a broader parent check, a sibling facet, '
            'or the downstream task. Evidence for a sibling target is not partial evidence for this target. '
            'A filename alone supplies no file-content evidence. A directory listing can fully answer file presence; '
            'pwd can fully answer the working-directory question. These observations do not establish content correctness.')
    if version in MATERIAL_VERSIONS and response:
        req['state']['response_scope']='Material in this linked response for one target; independent of whether an acceptance condition was stated or satisfied.'
        req['questions']['choice']={'type':'choice','criteria':MATERIAL_CHOICES,'instructions':
            'For ONLY this checking target, what requested material is available in THIS recorded response?\nTARGET: '+facet['text']+
            '\nEvaluate material availability, not whether the check can be graded or passed. No acceptance criterion is needed '
            'to observe that requested material is present or absent. File contents may be absent even when a content-quality '
            'criterion is unspecified. A directory listing can supply existence evidence while supplying no file contents. '
            'Only matching information in this response counts; do not borrow material from sibling targets, surrounding '
            'claims or earlier responses. Relevant recorded pixels/omitted ranges that have not been inspected remain '
            'unobserved. A negative test result supplies material; an error without the requested result does not.'}
    return req


def build(run, local, proposals, decide, version=VERSION):
    if version not in VERSIONS:raise InputError('Unknown stated-check evidence version')
    units=validate_candidates(run,local,proposals)
    associations=source_expression_links(run,local['units']); feedback=linked_feedback(run,local)
    result={'schema':version,'run_id':run['id'],'source_hash':digest(run),'extraction_hash':digest(local),
        'candidate_hash':digest(proposals),'candidate_producer':proposals['producer'],
        'retrieval_scope':'Only dispatches with a recorded source expression association. No nearest-neighbor fallback.',
        'uninspected_unit_ids':[u['id'] for u in local['units'] if u['actor']=='agent' and u['kind']=='semantic' and u['id'] not in {r['unit_id'] for r in proposals['units']}],
        'observations':[],'relations':[],'limits':'Development checking contents and evidence judgments. No new base activities, fulfilled check, active intention history or independent accuracy inferred.'}
    for row in proposals['units']:
        owner=units[row['unit_id']]
        item=select_contents(run,local,owner,row,proposals,decide,version);result['observations'].append(item)
        choice=item['selection'];key=item['selection_request']
        if not choice.startswith('c'):continue
        check=deepcopy(row['candidates'][int(choice[1:])]);check['id']='check-'+digest({'unit':owner['id'],'request':key,'contents':check})[:20]
        item['check']=check
        if version in MATERIAL_VERSIONS:
            item['specifications']=[]
            for facet in check['facets']:
                req=specification_request(run,local,owner,check,facet,version);answers,key=decide(req)
                item['specifications'].append({'facet_id':facet['id'],'choice':answers['choice']['value'],'request':key})
        associated={r['to'] for r in associations if r['from']==owner['id']}
        for action in local['units']:
            if action['id'] not in associated:continue
            action_row={'action_unit_id':action['id'],'facets':[]};item['actions'].append(action_row)
            for facet in check['facets']:
                req=evidence_request(run,local,owner,check,facet,action,version=version)
                answers,key=decide(req);role=answers['choice']['value']
                value={'facet_id':facet['id'],'dispatch_choice':role,'dispatch_request':key,'responses':[]};action_row['facets'].append(value)
                matches=[f for f in feedback if f['action']['id']==action['id']]
                if not matches:value['response_status']='no_linked_recorded_response'
                for response in [None,*matches]:
                    if response:
                        req=evidence_request(run,local,owner,check,facet,action,response,version=version)
                        answers,key=decide(req);role=answers['choice']['value'];supplied=req['state']['inspected_response']
                        value['responses'].append({'feedback_unit_id':response['unit_id'],'event_id':response['event']['id'],
                            'choice':role,'request':key,'omitted_text_ranges':deepcopy(supplied.get('omitted_text_ranges',[])),
                            'unobserved_media':deepcopy([*supplied.get('unobserved_inline_media',[]),
                                *supplied.get('unobserved_media_parts',[]),*supplied.get('unobserved_auxiliary_media',[])])})
                    types=({'available':'provides_check_material','partial':'partly_provides_check_material'}
                           if response and version in MATERIAL_VERSIONS else LINKS)
                    if role not in types:continue
                    refs=[owner['source'],action['source'],*facet['evidence']]
                    if response:refs.append(evidence(run,response['event']['id']))
                    result['relations'].append({'from':response['unit_id'] if response else action['id'],'to':owner['id'],
                        'type':types[role],'basis':'jev_raw_argmax','harness':version,'check_id':check['id'],
                        'check_text':facet['text'],'facet_id':facet['id'],'action_unit_id':action['id'],'request_hash':key,
                        'evidence':deepcopy(refs),'explanation':'Correspondence to this expressed check facet; outcome and fulfillment remain separate.',
                        'cutoff':{'event_id':req['state']['cutoff_event_id'],'end':req['state']['cutoff_codepoint']}})
    return result


def path_for(directory, local):return Path(directory)/'stated_checks'/local['run_id']/f'{digest(local)}.json'
def candidates_path(directory, local):return Path(directory)/'stated_check_candidates'/local['run_id']/f'{digest(local)}.json'


def candidate_repair_request(run, local, item):
    """Bind external generation to the rejected content selection and its cutoff."""
    if item['selection']!='no_suitable_candidate':raise InputError('Content selection did not request new candidates')
    owner=next(u for u in local['units'] if u['id']==item['unit_id'])
    from .semantic_extraction import prefix
    visible,excluded=prefix(run,owner['source'],POLICY)
    return {'schema':'stated-check-proposal-request/1','stage':'stated_check_candidates',
            'source_hash':digest(run),'extraction_hash':digest(local),'source':owner['source'],
            'unit_id':owner['id'],'local_content':owner['content'],'prefix':visible,
            'excluded_not_agent_visible':excluded,'rejected_selection_request':item['selection_request'],
            'instructions':'Propose zero to three faithful checking-content bundles inside this existing contribution. Do not split or relabel the unit. Preserve readable targets, attribution and exact source references. Each bundle has text, evidence and facets, with each facet having id, text and evidence. Do not invent an acceptance criterion, outcome, or relation.',
            'selection':'Candidates only; Jev must select them before use.'}


def audit(run, local, proposals, result, directory):
    def replay(req):
        key=digest(req);saved=read(Path(directory)/'decisions'/f'{key}.json')
        if saved['request']!=req or saved['response'].get('model')!=req['model']:raise InputError('Checking request/model changed')
        answers=replay_decision(saved)
        if answers!=saved['answers']:raise InputError('Checking selection differs from argmax')
        return answers,key
    if build(run,local,proposals,replay,result['schema'])!=result:raise InputError('Checking result differs from dependency replay')
    validation={'units_inspected':len(result['observations']),'units_uninspected':len(result['uninspected_unit_ids']),
            'checks_selected':sum('check' in o for o in result['observations']),
            'relations':len(result['relations']),'argmax_replayed':True,'semantic_accuracy':'not independently measured'}
    if result['schema'] in MATERIAL_VERSIONS:
        from collections import Counter
        validation['content_dispositions']=dict(Counter('selected' if 'check' in o else o['selection'] for o in result['observations']))
        validation['material_observations']=dict(Counter(r['choice'] for o in result['observations'] for a in o['actions'] for f in a['facets'] for r in f['responses']))
        if result['schema']==ROUTED_VERSION:
            validation['applicability']=dict(Counter(o['applicability']['choice'] for o in result['observations']))
            validation['content_selections']=sum(o.get('content_selection')!='not_run' for o in result['observations'])
            validation['applicability_content_disagreements']=sum(o['applicability']['choice']=='checking_work' and o['selection']=='none' for o in result['observations'])
    return validation


def execute(run, local, proposals, engine, version=VERSION):
    previous=path_for(engine.directory,local)
    if previous.exists() and read(previous)['schema']!=version:
        raise InputError('Use a new observation directory to preserve the previous checking version')
    audit_result(run,local,engine.directory)
    if any(r.get('origin',{}).get('kind')=='source_bound_repair' for r in proposals['units']):
        from .check_candidate_repairs import audit_revisions
        audit_revisions(run,local,proposals,engine.directory)
    result=build(run,local,proposals,engine.decide,version);validation=audit(run,local,proposals,result,engine.directory)
    write(Path(engine.directory)/'stated_check_snapshots'/f'{digest(result)}.json',result)
    write(path_for(engine.directory,local),result)
    if version in MATERIAL_VERSIONS:
        # Rejected coarse meanings become an explicit generation task, not a
        # fabricated negative or an automatic repair by a different model.
        for item in result['observations']:
            if item['selection']!='no_suitable_candidate':continue
            repair=candidate_repair_request(run,local,item)
            write(Path(engine.directory)/'check_candidate_repairs'/f'{digest(repair)}.json',repair)
        for item in result['observations']:
            if item.get('applicability',{}).get('choice')!='checking_work' or item['selection']!='none':continue
            owner=next(u for u in local['units'] if u['id']==item['unit_id'])
            review={'schema':'checking-stage-review/1','source_hash':digest(run),'extraction_hash':digest(local),
                'unit_id':owner['id'],'source':owner['source'],'applicability':item['applicability'],
                'content_selection':{'choice':item['selection'],'request':item['selection_request']},
                'reason':'Applicability selected checking_work, but the independent content selector chose none. Inspect scope and candidate completeness; neither decision overrides the other.',
                'selection_policy':'Preserve both raw argmax selections. No probability threshold or automatic relabeling.'}
            write(Path(engine.directory)/'check_review_requests'/f'{digest(review)}.json',review)
    return result,validation


def main():
    import argparse,getpass,os
    from .jev import JevClient
    from .semantic_extraction import Pipeline,FileCandidates
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path);parser.add_argument('run_id')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare',action='store_true');action.add_argument('--run',action='store_true');action.add_argument('--audit',action='store_true')
    parser.add_argument('--retain-proposals',type=Path)
    parser.add_argument('--version',choices=sorted(VERSIONS),default=MATERIAL_VERSION)
    args=parser.parse_args()
    if not args.run_id.isalnum():raise InputError('Invalid run identity')
    run=read(args.directory/'runs'/f'{args.run_id}.json');local=read(args.directory/'results'/f'{args.run_id}.json')
    audit_result(run,local,args.directory)
    if args.prepare:
        proposals=derive_candidates(run,local,read(args.retain_proposals) if args.retain_proposals else None)
        path=candidates_path(args.directory,local)
        if path.exists() and read(path)!=proposals:raise InputError('Use a new observation directory to preserve prior candidates')
        write(path,proposals);print(dumps({'units_prepared':len(proposals['units']),'path':str(path)}));return
    proposals=read(candidates_path(args.directory,local))
    if args.audit:
        print(dumps(audit(run,local,proposals,read(path_for(args.directory,local)),args.directory)));return
    client=JevClient()
    def transport(req):
        if not os.environ.get('JEV_API_KEY'):os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
        value=client.transport(req);print(req['state']['stage'],req['state']['subject']['event_id'],flush=True);return value
    engine=Pipeline(args.directory,FileCandidates(args.directory/'candidates'),transport)
    result,validation=execute(run,local,proposals,engine,args.version)
    print(dumps({'calls':engine.calls,'validation':validation,'result_hash':digest(result)}))


if __name__=='__main__':main()
