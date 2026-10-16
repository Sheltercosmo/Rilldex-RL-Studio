"""Versioned, attributed requested work after local contribution extraction.

External providers propose readable records and edits. Jev selects a complete
edit bundle or retains the previous state. State concerns requested terms only;
it never establishes that the environment performed or completed them.
"""
from copy import deepcopy
from pathlib import Path
import re

from .schema import InputError,digest,dumps
from .semantic_extraction import (request,prefix,read,write,checked_span,
    audit_result,replay_decision)

VERSION='requested-work-records/1'
CLAUSE_VERSION='requested-work-records/2'
VERSIONS={VERSION,CLAUSE_VERSION}
OPS={'introduce','revise','withdraw','restore'}
CLAUSE_KINDS={'requirement','requested_check','attributed_claim'}


def condition_clauses(run,unit,previous,edit):
    """Retain distinct terms, requested checks and claims within one record."""
    supplied=edit.get('clauses');retired=edit.get('retired_clauses',[])
    if not isinstance(supplied,list) or not 1<=len(supplied)<=64 or not isinstance(retired,list) or len(retired)>64:
        raise InputError('Condition records need readable clauses and explicit retirements')
    old={c['id']:c for c in (previous or {}).get('clauses',[])};new={}
    for value in supplied:
        if not isinstance(value,dict):raise InputError('Invalid condition clause')
        cid=value.get('id');kind=value.get('kind');text=value.get('text');refs=value.get('evidence')
        if (not isinstance(cid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',cid) or cid in new
            or kind not in CLAUSE_KINDS or not isinstance(text,str) or not text.strip() or len(text)>4000
            or not isinstance(refs,list) or not refs):raise InputError('Invalid condition clause')
        for ref in refs:checked_span(run,ref,unit['source'])
        prior=old.get(cid)
        if prior and prior['kind']!=kind:raise InputError('Clause identity cannot silently change its content role')
        content={'id':cid,'kind':kind,'text':text,'evidence':deepcopy(refs)}
        unchanged=prior and all(prior[k]==v for k,v in content.items())
        if unchanged:new[cid]=deepcopy(prior);continue
        if not any(r['event_id']==unit['source']['event_id'] and r['start']<unit['source']['end'] and r['end']>unit['source']['start'] for r in refs):
            raise InputError('A new or revised condition clause must cite its current contribution')
        content['source_unit_id']=unit['id']
        content['version_id']='cv'+digest({'record_id':edit['record_id'],'content':content,'previous_version':prior['version_id'] if prior else None})[:20]
        new[cid]=content
    removed={}
    for value in retired:
        if not isinstance(value,dict):raise InputError('Invalid condition-clause retirement')
        cid=value.get('id');reason=value.get('reason');refs=value.get('evidence')
        if not isinstance(cid,str) or cid not in old or cid in new or cid in removed or not isinstance(reason,str) or not reason.strip() or len(reason)>4000 or not isinstance(refs,list) or not refs:
            raise InputError('Invalid condition-clause retirement')
        for ref in refs:checked_span(run,ref,unit['source'])
        if not any(r['event_id']==unit['source']['event_id'] and r['start']<unit['source']['end'] and r['end']>unit['source']['start'] for r in refs):
            raise InputError('Clause retirement must cite the current contribution')
        removed[cid]={'id':cid,'reason':reason,'evidence':deepcopy(refs),'previous':deepcopy(old[cid])}
    if set(old)-set(new)!=set(removed):raise InputError('Condition clauses cannot be silently dropped')
    return list(new.values()),list(removed.values())


def user_units(extraction):
    return [u for u in extraction['units'] if u['actor']=='user' and u['kind']=='semantic' and u['status']=='selected']


def proposal_request(run,extraction,unit,records,policy,version=VERSION):
    if version not in VERSIONS:raise InputError('Unknown requested-work version')
    visible,excluded=prefix(run,unit['source'],policy)
    result={'schema':version,'stage':'requested_work_candidates','run_id':run['id'],
        'source_hash':digest(run),'extraction_hash':digest(extraction),'source':unit['source'],
        'local_content':unit['content'],'actor':unit['actor'],'previous_records':deepcopy(records),
        'prefix':visible,'excluded_not_agent_visible':excluded,
        'instructions':'Propose 0–3 coherent edit bundles to the user’s requested work/conditions. '
        'Track negotiated work scope and terms, not a queue of every conversational question. '
        'Clarification or status questions remain in local contents and do not automatically change requested scope. '
        'Keep distinct requested items separately addressable, even inside one semantic contribution. '
        'A record has a readable natural-language meaning; do not extract isolated entity names. '
        'Introduce new records, revise expressed terms, withdraw an existing requested item, or explicitly restore it. '
        'Retain previous record IDs and unchanged records. Repeated terms or asking for confirmation do not create '
        'another withdrawal or replace previous history. A tentative preference remains tentative in the record text. '
        'A request-state status is not environmental completion. Each edit cites the current contribution and any '
        'earlier visible source needed. Prior selected records are model judgments, not new source facts.',
        'response_contract':{'request_hash':'digest of this request','producer':'candidate provider/version',
          'candidates':[{'edits':[{'op':'introduce | revise | withdraw | restore','record_id':'stable identifier',
            'kind':'work | condition (introduce only)','text':'complete readable requested work or condition',
            'evidence':['exact source references']}]}]}}
    if version==CLAUSE_VERSION:
        result['instructions']+=' For every condition record, preserve separate readable clauses: requirement (a requested term, restriction or prerequisite), requested_check (work requested to establish/confirm something), and attributed_claim (an assertion with its speaker, not an established fact). A request to check is not the fact being checked and does not establish a passing result. Retain existing clause IDs and exact contents when unchanged. New or revised clauses cite this contribution. A clause may be removed from current terms only through an explicit retired_clauses entry with a source-backed reason; this does not make a past claim false or establish fulfillment. Capture a material restriction expressed here even when phrased as reconfirmation and missing from previous records; record enrichment is not itself a changed objective. Keep multiple clauses inside one condition, not new base activity units.'
        result['response_contract']['condition_edits']={'clauses':[{'id':'stable ID within condition','kind':'requirement | requested_check | attributed_claim','text':'complete readable attributed meaning','evidence':['exact references']}],
            'retired_clauses':[{'id':'prior clause ID','reason':'why it no longer belongs to current terms, not a completion judgment','evidence':['current contribution evidence']}]}
    return result


def apply_edits(run,unit,records,edits,version=VERSION):
    """Validate edits and return an immutable next snapshot plus version events."""
    if version not in VERSIONS:raise InputError('Unknown requested-work version')
    if not isinstance(edits,list) or not edits:raise InputError('An update bundle needs edits')
    result=deepcopy(records);changes=[];seen=set()
    for edit in edits:
        op=edit.get('op');rid=edit.get('record_id')
        if op not in OPS or not isinstance(rid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',rid) or rid in seen:
            raise InputError('Invalid or repeated requested-work edit')
        seen.add(rid)
        previous=next((r for r in result if r['id']==rid),None)
        if (op=='introduce')!=(previous is None):raise InputError('Requested-work identity does not match edit')
        if previous:
            if op=='restore' and previous['status']!='withdrawn':raise InputError('Only withdrawn work can be restored')
            if op in {'revise','withdraw'} and previous['status']!='requested':raise InputError('Cannot revise or withdraw inactive requested work')
        elif edit.get('kind') not in {'work','condition'}:raise InputError('New record needs a work/condition kind')
        text=edit.get('text');refs=edit.get('evidence')
        if not isinstance(text,str) or not text.strip() or len(text)>4000 or not isinstance(refs,list) or not refs:
            raise InputError('Work edits need readable content and evidence')
        for ref in refs:checked_span(run,ref,unit['source'])
        if not any(a['event_id']==unit['source']['event_id'] and a['start']<unit['source']['end'] and a['end']>unit['source']['start'] for a in refs):
            raise InputError('A work edit must cite its current contribution')
        kind=previous['kind'] if previous else edit['kind']
        clauses=None;retired=[]
        if version==CLAUSE_VERSION and kind=='condition':clauses,retired=condition_clauses(run,unit,previous,edit)
        elif 'clauses' in edit or 'retired_clauses' in edit:raise InputError('Clauses belong to version 2 condition records')
        if previous and op=='revise' and text==previous['text'] and (clauses is None or clauses==previous.get('clauses')):
            raise InputError('Identical terms do not create a new version')
        status='withdrawn' if op=='withdraw' else 'requested'
        current={'id':rid,'kind':previous['kind'] if previous else edit['kind'],'actor':unit['actor'],
            'trajectory_id':unit['trajectory_id'],'text':text,'status':status,
            'source_unit_id':unit['id'],'evidence':deepcopy(refs)}
        if clauses is not None:current['clauses']=clauses
        current['version_id']='rv'+digest({'record':current,'previous_version':previous['version_id'] if previous else None})[:20]
        if previous:result[result.index(previous)]=current
        else:result.append(current)
        change={'record_id':rid,'operation':op,'before':deepcopy(previous),'after':deepcopy(current),'source_unit_id':unit['id']}
        if clauses is not None:change['retired_clauses']=retired
        changes.append(change)
    return result,changes


def validate_proposals(run,req,unit,response):
    if response.get('request_hash')!=digest(req) or not response.get('producer'):raise InputError('Work proposal binding differs')
    from .readable_context import resolve_response
    if response.get('citation_format') not in {None,'source-offsets/1','source-quotes/1','source-references/1'}:
        raise InputError('Unknown requested-work citation format')
    response=resolve_response(run,req,response)
    candidates=response.get('candidates')
    if not isinstance(candidates,list) or len(candidates)>3:raise InputError('Expected 0–3 work update candidates')
    from .readable_context import contains
    visible={e['id']:e for e in req['prefix']}
    for candidate in candidates:
        apply_edits(run,unit,req['previous_records'],candidate.get('edits'),req['schema'])
        for edit in candidate['edits']:
            refs=[*edit['evidence'],*[r for c in edit.get('clauses',[]) for r in c['evidence']],*[r for c in edit.get('retired_clauses',[]) for r in c['evidence']]]
            for ref in refs:
                if ref['event_id'] not in visible or not contains(visible[ref['event_id']],ref):raise InputError('Work edit cites omitted source')
    return candidates


class FileCandidates:
    def __init__(self,directory,*,cache_directories=()):
        self.directory=Path(directory);self.cache_directories=tuple(cache_directories)
    def get(self,run,req,unit):
        key=digest(req);write(self.directory/'requests'/f'{key}.json',req)
        if self.cache_directories:
            from .candidate_cache import reuse
            reuse(self.directory,req,self.cache_directories,queue='work_candidates')
        path=self.directory/'responses'/f'{key}.json'
        if not path.exists():return None
        value=read(path);validate_proposals(run,req,unit,value);return value


class CommandCandidates(FileCandidates):
    """Use the same bounded proposer process for requested terms as for units."""
    def __init__(self,directory,command,producer,*,execution_budget=None,citation_format=None,cache_directories=()):
        super().__init__(directory,cache_directories=cache_directories)
        from .candidate_worker import CommandCandidates as Process
        self.process=Process(directory,command,producer,execution_budget=execution_budget,citation_format=citation_format)

    @property
    def generation_calls(self):return self.process.generation_calls

    def get(self,run,req,unit):
        value=super().get(run,req,unit)
        if value is None:
            self.process.generate(run,req,validator=lambda response:validate_proposals(run,req,unit,response))
            value=super().get(run,req,unit)
        return value


def selection_request(run,unit,proposal,candidates,policy):
    result=request(run,unit['source'],'requested_work',
        'Select the faithful change to CURRENT requested work, using the current contribution and previous_records. '
        'This tracks negotiated work scope and terms, not a queue of all questions. '
        'Do not compare this passage with every historical request or repeat a change already applied. '
        'Choose unchanged when the user only restates current terms or asks whether they were followed. '
        'Select no_suitable_candidate if a real new change is expressed but all offered edits miss or distort it. '
        'Preserve tentative wording, user attribution, distinct work items and untouched terms. '
        'Requested/withdrawn describes requested scope, never execution, success or completed cancellation.',
        {**{f'c{i}':dumps(c['edits']) for i,c in enumerate(candidates)},
         'unchanged':'The current contribution establishes no new change to the previous requested-work records.',
         'no_suitable_candidate':'There is a supported update, but the candidate edits need repair.',
         'unresolved':'The source or the prior work state is insufficient to select a faithful update.'},
        context_policy=policy,requested_work_harness=proposal['schema'],local_content=unit['content'],
        previous_records=proposal['previous_records'],candidate_edits=candidates,
        proposal_request_hash=digest(proposal),source_attribution=unit['actor'])
    if proposal['schema']==CLAUSE_VERSION:
        result['questions']['choice']['instructions']+=' Also judge condition-clause completeness. Requirements, requested checks and attributed claims are different contents of the same condition, not overlapping base activities. Preserve unchanged restrictions. A reconfirmed restriction missing from the stored clauses may require record enrichment even if the broad work is unchanged. Choose unchanged only when previous records already retain the material expressed terms. Retiring a clause means it no longer describes current terms after a supported change, not that a request was fulfilled or an assertion disproved.'
    return result


def path_for(directory,extraction):return Path(directory)/'requested_work'/f'{digest(extraction)}.json'


def build(run,extraction,provider,choose,policy=None,version=VERSION):
    if extraction['status']!='complete_local_extraction':raise InputError('Complete local extraction before work records')
    records=[];steps=[];changes=[]
    for unit in user_units(extraction):
        # Keep concurrent trajectories independent; never carry one user's task into another.
        current=[r for r in records if r['trajectory_id']==unit['trajectory_id']]
        req=proposal_request(run,extraction,unit,current,policy,version);proposal=provider.get(run,req,unit)
        step={'unit_id':unit['id'],'proposal_request_hash':digest(req),'previous_state_hash':digest(current)}
        if proposal is None:
            steps.append({**step,'status':'needs_candidates'});break
        candidates=validate_proposals(run,req,unit,proposal)
        select=selection_request(run,unit,req,candidates,policy);choice,key=choose(select)
        step.update(choice=choice,request_hash=key,candidate_producer=proposal['producer'])
        if choice.startswith('c'):
            index=int(choice[1:])
            if index>=len(candidates):raise InputError('Unknown work candidate')
            updated,delta=apply_edits(run,unit,current,candidates[index]['edits'],version)
            records=[r for r in records if r['trajectory_id']!=unit['trajectory_id']]+updated
            changes.extend(delta);step['status']='selected_update';step['changes']=delta
        elif choice=='unchanged':step['status']='unchanged';step['changes']=[]
        elif choice in {'no_suitable_candidate','unresolved'}:
            steps.append({**step,'status':'needs_review'});break
        else:raise InputError('Unknown requested-work selection')
        step['state_after']=deepcopy([r for r in records if r['trajectory_id']==unit['trajectory_id']]);steps.append(step)
    complete=len(steps)==len(user_units(extraction)) and all(s['status'] in {'selected_update','unchanged'} for s in steps)
    return {'schema':version,'run_id':run['id'],'source_hash':digest(run),'extraction_hash':digest(extraction),
        'context_policy':deepcopy(policy),'status':'complete' if complete else 'needs_work',
        'records':records,'steps':steps,'changes':changes,
        'limits':'Model-selected requested terms with assistant/external candidate provenance. Status is request scope, not environmental fulfillment. No independent accuracy or RL checkpoint comparison.'}


def execute(run,extraction,provider,engine,policy=None,version=VERSION):
    audit_result(run,extraction,engine.directory)
    result=build(run,extraction,provider,engine.choose,policy,version)
    write(Path(engine.directory)/'requested_work_checkpoints'/f'{extraction["run_id"]}.json',result)
    write(Path(engine.directory)/'requested_work_snapshots'/f'{digest(result)}.json',result)
    if result['status']=='complete':write(path_for(engine.directory,extraction),result)
    return result


def audit(run,extraction,result,directory):
    provider=FileCandidates(Path(directory)/'work_candidates')
    def replay(req):
        key=digest(req);saved=read(Path(directory)/'decisions'/f'{key}.json')
        if saved['request']!=req or saved['response'].get('model')!=req['model']:raise InputError('Work decision request differs')
        answers=replay_decision(saved)
        if answers!=saved['answers']:raise InputError('Work selection differs from raw argmax')
        return answers['choice']['value'],key
    expected=build(run,extraction,provider,replay,result['context_policy'],result['schema'])
    if expected!=result:raise InputError('Requested-work history differs from source replay')
    validation={'records':len(result['records']),'changes':len(result['changes']),
            'units_reviewed':len(result['steps']),'argmax_replayed':True,
            'semantic_accuracy':'not independently measured'}
    if result['schema']==CLAUSE_VERSION:
        validation.update(current_condition_clauses=sum(len(r.get('clauses',[])) for r in result['records']),
            distinct_clause_versions=len({c['version_id'] for s in result['steps'] for r in s.get('state_after',[]) for c in r.get('clauses',[])}),
            explicit_clause_retirements=sum(len(c.get('retired_clauses',[])) for c in result['changes']))
    return validation


def main():
    """File-queue entry point for any completed participant extraction."""
    import argparse
    import getpass
    import os
    from .jev import JevClient
    from .semantic_extraction import Pipeline,FileCandidates as LocalCandidates
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path,help='Extraction directory with runs, results and decisions')
    p.add_argument('run_id')
    p.add_argument('--context-policy',type=Path,help='Optional readable-context policy JSON')
    p.add_argument('--audit-only',action='store_true')
    p.add_argument('--version',choices=sorted(VERSIONS),default=VERSION)
    a=p.parse_args()
    if not a.run_id.isalnum():raise InputError('Invalid run ID')
    run=read(a.directory/'runs'/f'{a.run_id}.json')
    local=read(a.directory/'results'/f'{a.run_id}.json')
    if not local.get('participant_scope'):raise InputError('Extract attributed user contributions with --include-user first')
    audit_result(run,local,a.directory)
    if a.audit_only:
        print(dumps(audit(run,local,read(path_for(a.directory,local)),a.directory)));return
    client=JevClient()
    def transport(req):
        if not os.environ.get('JEV_API_KEY'):
            os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ')
        return client.transport(req)
    engine=Pipeline(a.directory,LocalCandidates(a.directory/'candidates'),transport)
    policy=read(a.context_policy) if a.context_policy else None
    result=execute(run,local,FileCandidates(a.directory/'work_candidates'),engine,policy,a.version)
    print(dumps({'status':result['status'],'units_reviewed':len(result['steps']),
                 'candidate_requests':str(a.directory/'work_candidates'/'requests'),
                 'calls':engine.calls}))


if __name__=='__main__':main()
