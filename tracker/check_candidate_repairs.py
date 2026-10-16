"""Validate checking-content proposals and prepare an immutable observer revision.

This file protocol accepts authored or externally generated candidates. It does
not generate meanings, override selections, or call another model service.
Run tracker.stated_checks on the prepared directory to let Jev select contents.
"""
from copy import deepcopy
from pathlib import Path
import shutil

from .schema import InputError, digest, dumps
from .semantic_extraction import read, write, audit_result, checked_span
from .readable_context import resolve_response, contains
from .stated_checks import (MATERIAL_VERSIONS, candidates_path, path_for, audit,
                           validate_candidates, candidate_repair_request)

RESPONSE_VERSION='stated-check-proposal-response/1'
REVISION_VERSION='stated-check-candidate-revision/1'
# Dependencies consumed by load_extraction and its replay audits. Published
# checking results/candidates are saved separately as the immutable baseline.
DEPENDENCIES=('runs','results','candidates','decisions','plan_relations',
              'feedback_assessments','action_targets','reviews','requested_work',
              'work_candidates','work_correspondence','condition_records',
              'check_correspondence','check_candidate_revisions','check_followthrough','response_material')


def revise_candidates(run, local, proposals, previous, req, response):
    """Return a new proposal set; callers must also replay the prior decisions."""
    validate_candidates(run,local,proposals)
    if (previous.get('schema') not in MATERIAL_VERSIONS or previous.get('source_hash')!=digest(run)
            or previous.get('extraction_hash')!=digest(local) or previous.get('candidate_hash')!=digest(proposals)):
        raise InputError('Repair needs the exact preceding checking pass and candidates')
    item=next((o for o in previous['observations'] if o['unit_id']==req.get('unit_id')),None)
    if not item or req!=candidate_repair_request(run,local,item):
        raise InputError('Repair request differs from the current source-bound rejection')
    if (not isinstance(response,dict) or set(response)!={'schema','request_hash','producer','citation_format','candidates'}
            or response['schema']!=RESPONSE_VERSION or response['request_hash']!=digest(req)
            or not isinstance(response['producer'],str) or not response['producer'].strip()
            or response['citation_format'] not in {'source-quotes/1','source-offsets/1'}):
        raise InputError('Response needs an exact request binding, producer and citation format; no selected answer')
    cs=response['candidates']
    if not isinstance(cs,list) or len(cs)>3:raise InputError('Offer zero to three checking bundles')
    for bundle in cs:
        if not isinstance(bundle,dict) or set(bundle)!={'text','evidence','facets'}:
            raise InputError('Checking bundle needs text, evidence and facets only')
        if not isinstance(bundle['facets'],list) or not 1<=len(bundle['facets'])<=12:
            raise InputError('Checking bundle needs one to twelve facets')
        for facet in bundle['facets']:
            if not isinstance(facet,dict) or set(facet)!={'id','text','evidence'}:
                raise InputError('Checking facet needs id, text and evidence only')
            if not isinstance(facet['id'],str) or not facet['id'].strip():raise InputError('Facet needs a readable identity')
        for value in [bundle,*bundle['facets']]:
            if (not isinstance(value['text'],str) or not value['text'].strip() or len(value['text'])>4000
                    or not isinstance(value['evidence'],list) or not value['evidence']
                    or any(not isinstance(r,dict) for r in value['evidence'])):
                raise InputError('Checking contents need readable meanings and citation lists')
    resolved=resolve_response(run,req,response)
    supplied={e['id']:e for e in req['prefix']}
    for bundle in resolved['candidates']:
        for value in [bundle,*bundle['facets']]:
            for ref in value['evidence']:
                checked_span(run,ref,req['source'])
                if ref['event_id'] not in supplied or not contains(supplied[ref['event_id']],ref):
                    raise InputError('Repair cites text outside the supplied generation context')
    revision={'schema':REVISION_VERSION,'source_hash':digest(run),'extraction_hash':digest(local),
              'unit_id':req['unit_id'],'request_hash':digest(req),'response_hash':digest(response),
              'previous_candidate_hash':digest(proposals),'previous_result_hash':digest(previous)}
    revision_id=digest(revision)
    revised=deepcopy(proposals)
    row=next(r for r in revised['units'] if r['unit_id']==req['unit_id'])
    old_row_hash=digest(row)
    row.update(candidates=resolved['candidates'],origin={'kind':'source_bound_repair',
        'producer':response['producer'],'revision_id':revision_id,'request_hash':digest(req),
        'response_hash':digest(response),'previous_row_hash':old_row_hash,
        'previous_selection_request':item['selection_request'],
        'meaning':'External candidate repair; meanings require a fresh Jev selection. Source validation is not semantic accuracy.'})
    # Keep the top-level producer unchanged: row-local provenance invalidates
    # only this contribution's content request, not unrelated saved decisions.
    validate_candidates(run,local,revised)
    return revised,revision


def prepare_revision(directory, run_id, req, response, output):
    directory=Path(directory).resolve();output=Path(output).resolve()
    if not run_id.isalnum():raise InputError('Invalid run identity')
    if directory.is_relative_to(output) or output.is_relative_to(directory):
        raise InputError('Revision and source directories must be separate')
    if output.exists():raise InputError('Revision directory already exists; resume its checking pass instead')
    run=read(directory/'runs'/f'{run_id}.json');local=read(directory/'results'/f'{run_id}.json')
    audit_result(run,local,directory)
    proposals=read(candidates_path(directory,local));previous=read(path_for(directory,local))
    audit(run,local,proposals,previous,directory)
    revised,revision=revise_candidates(run,local,proposals,previous,req,response)
    # Validate everything before creating the destination. Copy only JSON data
    # dependencies, never provider commands, credentials or arbitrary files.
    sources=[]
    for folder in DEPENDENCIES:
        for source in sorted((directory/folder).rglob('*.json')):
            if not source.resolve().is_relative_to(directory):raise InputError('Dependency escapes source directory')
            sources.append((source,source.relative_to(directory)))
    output.mkdir(parents=True,exist_ok=False)
    for source,relative in sources:
        target=output/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    history=output/'check_candidate_revisions'/digest(revision)
    for name,value in [('request',req),('response',response),('previous-candidates',proposals),
                       ('previous-result',previous),('revision',revision)]:write(history/f'{name}.json',value)
    write(candidates_path(output,local),revised)
    return {'revision_id':digest(revision),'directory':str(output),'unit_id':req['unit_id'],
            'candidate_hash':digest(revised),'version':previous['schema'],
            'status':'candidates_prepared; Jev selection not run','copied_dependencies':len(sources)}


def audit_revisions(run, local, proposals, directory):
    """Replay repair provenance without relying on the original directory."""
    rows=[]
    for row in proposals['units']:
        origin=row.get('origin',{})
        if origin.get('kind')!='source_bound_repair':continue
        key=origin.get('revision_id','')
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise InputError('Invalid candidate revision identity')
        folder=Path(directory)/'check_candidate_revisions'/key
        req=read(folder/'request.json');response=read(folder/'response.json')
        prior=read(folder/'previous-candidates.json');previous=read(folder/'previous-result.json')
        audit(run,local,prior,previous,directory)
        revised,revision=revise_candidates(run,local,prior,previous,req,response)
        if digest(revision)!=key or read(folder/'revision.json')!=revision:
            raise InputError('Candidate revision history differs')
        if next(r for r in revised['units'] if r['unit_id']==row['unit_id'])!=row:
            raise InputError('Candidate row differs from validated repair')
        old_row=next(r for r in prior['units'] if r['unit_id']==row['unit_id'])
        old_item=next(o for o in previous['observations'] if o['unit_id']==row['unit_id'])
        rows.append({**revision,'revision_id':key,'producer':response['producer'],
                     'previous_selection':old_item['selection'],'previous_candidates':deepcopy(old_row['candidates']),
                     'proposed_candidates':deepcopy(row['candidates']),
                     'scope':'Candidate repair only. Unit, activity and raw selection policy remain unchanged.'})
    return rows


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path);parser.add_argument('run_id')
    parser.add_argument('--request',required=True,type=Path);parser.add_argument('--response',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(dumps(prepare_revision(args.directory,args.run_id,read(args.request),read(args.response),args.output)))


if __name__=='__main__':main()
