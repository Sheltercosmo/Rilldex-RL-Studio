"""Compare attributed user work records without rewriting earlier evidence.

Relations describe expressed requested terms, not execution, authorization
validity, mutual knowledge or environmental success. No target identity union
or active-state update is inferred from a pair label.
"""
from copy import deepcopy
from pathlib import Path
import time

from .schema import InputError,digest
from .jev import JevClient,validate_answers,SELECTION_POLICY
from .semantic_extraction import request,read,write,replay_decision,audit_result

VERSION='user-request-history/1'
CRITERIA={
    'no_update':'No supported update or explicit reaffirmation of this earlier requested work. Shared nouns, a related topic, asking about an option, asking whether work was completed, or reporting an environment state are insufficient.',
    'reaffirms':'Explicitly retains or repeats the earlier requested terms without changing them. A question asking whether the assistant followed them is not itself a new reaffirmation.',
    'refines':'Adds expressed detail to the earlier requested work where that detail was previously unspecified, without contradicting a specified term or withdrawing work. Retain any tentative wording; this is not proof of a settled commitment.',
    'replaces':'Explicitly substitutes a different value, option or method for a previously specified requested term. It changes a term while retaining the affected work; merely considering another option is insufficient.',
    'withdraws':'Explicitly withdraws all or part of the earlier requested work. Asking if withdrawal is possible is not withdrawal. Other requested parts may remain unchanged.',
    'unresolved':'A potentially relevant change is present but its relation to this particular earlier record cannot be established.'}
MEANING={
    'reaffirms':'Explicitly retains earlier requested terms.',
    'refines':'Adds detail to earlier requested work; source modality and scope remain in the local contents.',
    'replaces':'Substitutes a previously specified requested term.',
    'withdraws':'Withdraws all or part of earlier requested work; this is not a backend cancellation result.'}
MAX_PRIORS=24


def eligible(result):
    return [u for u in result['units'] if u['actor']=='user' and u['kind']=='semantic' and
            u['status']=='selected' and u['content'].get('work_target',{}).get('status')=='expressed']


def local_record(unit):
    def ref(value):return {k:deepcopy(value[k]) for k in ('event_id','start','end','source_pointer')}
    # Meanings remain readable; the exact quoted source is already in prefix.
    # Do not repeat whole multi-paragraph quotes for every field of every record.
    content={}
    for name,value in unit['content'].items():
        content[name]={k:deepcopy(v) for k,v in value.items() if k!='evidence'}
        if value.get('evidence'):content[name]['evidence_refs']=[ref(a) for a in value['evidence']]
    return {'id':unit['id'],'actor':unit['actor'],'source_ref':ref(unit['source']),
            'activity':unit['activity'],'content':content}


def packets(run,result,policy=None):
    """Root plus recent prior records; expose omissions rather than claiming recall."""
    records=eligible(result)
    for index,current in enumerate(records):
        prior=[u for u in records[:index] if u['trajectory_id']==current['trajectory_id']]
        if not prior:continue
        pool=prior if len(prior)<=MAX_PRIORS else [prior[0],*prior[-(MAX_PRIORS-1):]]
        included={u['id'] for u in pool}
        req=request(run,current['source'],'request_history',
            'Compare the current user contribution with this specific earlier user contribution. '
            'Use the current local meaning and source evidence; do not reinterpret the past using later statements. '
            'Select one relation for each pair. A pair may concern only part of either contribution. '
            'Do not treat an agent proposal, tool result, requested confirmation, possible withdrawal, or future approval '
            'as a completed change in user-requested work. Preserve attributed claims and tentative content.',
            CRITERIA,context_policy=policy,current_record=local_record(current),
            prior_records=[local_record(u) for u in pool],history_harness=VERSION,
            source_reference_rule='local-content-references/1: readable contents are selected model judgments. source_ref/evidence_refs identify original event codepoint ranges in prefix; source text is not repeated inside each field. If needed evidence is omitted from prefix, use unresolved rather than assuming the content is correct.',
            dependency_extraction_hash=digest(result),
            omitted_prior_unit_ids=[u['id'] for u in prior if u['id'] not in included],
            relationship_limit='Pairs preserve before/after contents. They do not identify a canonical work instance, normalize the exact changed field, or establish an active request state.')
        template=req['questions'].pop('choice')
        req['state']['comparison_rule']=template['instructions']
        req['state']['relation_definitions']=deepcopy(CRITERIA)
        req['questions']={u['id']:{'type':'choice',
            'instructions':'Apply comparison_rule to current_record and earlier record '+u['id']+'. Use the complete relation_definitions in state.',
            'criteria':{k:'Select '+k+' as defined in relation_definitions.' for k in CRITERIA}} for u in pool}
        yield current,pool,req


def path_for(directory,result):
    return Path(directory)/'request_history'/f'{digest(result)}.json'


def project(current,prior,answers):
    relations=[]
    for previous in prior:
        value=answers[previous['id']]['value']
        if value not in MEANING:continue
        relations.append({'from':current['id'],'to':previous['id'],'type':'request_'+value,
            'basis':'jev_pair_selection','harness':VERSION,'explanation':MEANING[value],
            'before':previous['content']['work_target']['text'],
            'after':current['content']['work_target']['text'],
            'scope':'All or part of the earlier expression; no canonical target merge or field delta inferred.',
            'evidence':[previous['source'],current['source']]})
    return relations


class Observer:
    def __init__(self,directory,transport=None,context_policy=None):
        self.directory=Path(directory);self.transport=transport or JevClient().transport
        self.policy=context_policy;self.calls=0
    def run(self,run,result):
        audit_result(run,result,self.directory)
        if result['status']!='complete_local_extraction':raise InputError('Complete local records before history relations')
        output={'schema':VERSION,'run_id':run['id'],'source_hash':digest(run),'extraction_hash':digest(result),
            'context_policy':deepcopy(self.policy),'selection_policy':SELECTION_POLICY,
            'max_prior_records':MAX_PRIORS,'relations':[],'observations':[],
            'meaning':'Development comparisons of user-requested terms. No request-state reducer, authorization validity, completion judgment or independent accuracy.'}
        for current,prior,req in packets(run,result,self.policy):
            key=digest(req);path=self.directory/'request_history_decisions'/f'{key}.json'
            if path.exists():
                saved=read(path)
                if saved['request']!=req:raise InputError('Cached history request differs')
                answers=replay_decision(saved)
                if answers!=saved['answers']:raise InputError('Cached history selection differs')
            else:
                start=time.monotonic();response=self.transport(req)
                if response.get('model')!=req['model']:raise InputError('History model differs')
                answers=validate_answers(response,req);self.calls+=1
                write(path,{'request':req,'response':response,'answers':answers,'selection_policy':SELECTION_POLICY,
                    'criterion_order':{k:list(q['criteria']) for k,q in req['questions'].items()},
                    'elapsed_seconds':round(time.monotonic()-start,3)})
            output['observations'].append({'unit_id':current['id'],'request_hash':key,
                'prior_unit_ids':[u['id'] for u in prior],
                'omitted_prior_unit_ids':req['state']['omitted_prior_unit_ids'],
                'choices':{k:v['value'] for k,v in answers.items()}})
            output['relations'].extend(project(current,prior,answers))
        write(path_for(self.directory,result),output)
        return output


def audit(run,result,output,directory):
    if (output.get('schema')!=VERSION or output.get('source_hash')!=digest(run) or
            output.get('extraction_hash')!=digest(result) or output.get('selection_policy')!=SELECTION_POLICY or
            output.get('run_id')!=run['id'] or output.get('max_prior_records')!=MAX_PRIORS):
        raise InputError('Request history dependencies differ')
    expected=[];observations=[];pairs=0
    for current,prior,req in packets(run,result,output['context_policy']):
        key=digest(req);saved=read(Path(directory)/'request_history_decisions'/f'{key}.json')
        if saved['request']!=req or saved['response'].get('model')!=req['model']:raise InputError('History source request differs')
        answers=replay_decision(saved)
        if answers!=saved['answers']:raise InputError('History choices are not raw argmax')
        expected.extend(project(current,prior,answers));pairs+=len(prior)
        observations.append({'unit_id':current['id'],'request_hash':key,'prior_unit_ids':[u['id'] for u in prior],
            'omitted_prior_unit_ids':req['state']['omitted_prior_unit_ids'],'choices':{k:v['value'] for k,v in answers.items()}})
    if output['relations']!=expected or output['observations']!=observations:raise InputError('Published request history differs')
    return {'eligible_user_units':len(eligible(result)),'pair_choices':pairs,'relations':len(expected),
            'omitted_pairs':sum(len(o['omitted_prior_unit_ids']) for o in observations),
            'argmax_replayed':True,'semantic_accuracy':'not independently measured'}
