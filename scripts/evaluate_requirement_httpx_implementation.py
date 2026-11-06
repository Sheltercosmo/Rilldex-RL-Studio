"""Two exact production8 implementation-page probes of the reproduced BOM bug.

Original e218 witness/reference is unchanged. Pages9 and21 have independently
reviewed implementation context; pages10 and22 are exported for boundary review.
No requirement, candidate, source, or production request is edited for this probe.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_requirement_prior_panel import prepared as prior_panel
from tracker import requirement_diagnostics as detector
from tracker.jev import JevClient,validate_answers
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

PANEL=Path('outputs/requirement-prior-corrected-panel')
REPRODUCTION=Path('outputs/httpx-bom-source-reproduction.json')
VERSION=detector.EVIDENCE_VERSION
PRIMARY={9:'e68',21:'e208'}
BOUNDARY_PAGES={10,22}
REQUIREMENT='trace:1590:1856'
MARKERS=('def _parse_line','line = line[1:]','def _is_json_whitespace_only',
         'JSON_WHITESPACE','def _parse_json_text','Invalid JSON: empty content')


def coverage(request):
    state=request['state'];locations={}
    for marker in MARKERS:
        locations[marker]=dict(source_fragment_ids=[key for key,f in state['source_fragments'].items() if marker in f['text']],
            linked_record_ids=[record.get('id',record.get('record_id')) for record in state['linked_source_records'] if marker in dumps(record)])
    return dict(page=state['page'],requirement_ids=[t['id'] for t in state['requirements'].values()],
        candidate_choices={field:list(q['criteria']) for field,q in request['questions'].items()},implementation_markers=locations)


def prepared():
    panel,rows=prior_panel(PANEL)
    prior=next(row for row in rows if row['case']['case_id']=='httpx-json-bom');case=prior['case']
    source=read(PANEL/'httpx-json-bom/source.json');terms=read(PANEL/'httpx-json-bom/historical-selected-requirements.json')
    reproduction=read(REPRODUCTION)
    term=next(t for t in terms if t['id']==REQUIREMENT)
    if term['display_text']!=reproduction['requirement']:raise InputError('Reproduced contract differs from source requirement')
    if digest(source)!=case['source_hash']:raise InputError('HTTPX source changed')
    if not reproduction['later_parse_line_ast_matches_initial']:raise InputError('Reproduction did not verify later implementation')
    bad={r['case'] for r in reproduction['results'] if not r['matches_literal_requirement']}
    if not {'bom-only-line-before-json','bom-and-whitespace-only-line','bom-only-final-line'}<=bad:
        raise InputError('Independent BOM reproduction no longer establishes the defect')
    requests={r['state']['page']:r for r in detector.requests(source,terms,version=VERSION)
              if r['state']['page'] in set(PRIMARY)|BOUNDARY_PAGES}
    if set(requests)!=set(PRIMARY)|BOUNDARY_PAGES:raise InputError('Implementation page map changed')
    references={}
    for page,event in PRIMARY.items():
        request=requests[page];shown=list(request['state']['requirements'].values())
        if shown!=terms or len(request['questions'])!=6:raise InputError('Not all original requirements are present')
        shown_coverage=coverage(request)
        if any(not(v['source_fragment_ids'] or v['linked_record_ids']) for v in shown_coverage['implementation_markers'].values()):
            raise InputError('Primary packet lacks an essential reviewed implementation marker')
        references[str(page)]=dict(expected_conflict=True,requirement_id=REQUIREMENT,requirement_text=term['display_text'],
            target_event_id=event,source_hash=digest(source),independent_reproduction_hash=digest(reproduction),
            reproduction_input='LF, then a BOM-only line, then a JSON text on the next line.',
            basis='The recorded parser strips the first-line BOM and returns on the remaining empty/whitespace-only line, bypassing the requirement that each nonblank physical line contain exactly one JSON text. Independent pure-code reproduction establishes the defect before these predictions.',
            scope='Supplemental implementation-page reference; original e218 label and witness score remain unchanged.')
    context=dict(panel_manifest_hash=digest(panel),source_hash=digest(source),historical_reference_hash=digest(prior['reference']),
        historical_role_packet_hashes=case['historical_role_packet_hashes'],reproduction_hash=digest(reproduction),
        decoded_code_sha256=reproduction['selected_pure_code_sha256'],original_witness_pages=case['witness_pages'],
        original_target_events=case['target_events'])
    return context,source,requests,references


def evaluate(directory='outputs/requirement-httpx-implementation',*,live=False,client=None,max_calls=2):
    if type(max_calls) is not int or max_calls<0:raise InputError('max_calls must be nonnegative')
    context,source,requests,references=prepared();root=Path(directory)
    manifest=dict(schema='requirement-httpx-implementation-inputs/1',protocol=detector.protocol(VERSION),**context,
        reference_hash=digest(references),primary_pages=list(PRIMARY),boundary_only_pages=sorted(BOUNDARY_PAGES),
        request_hashes={str(page):digest(r) for page,r in sorted(requests.items())},
        page_coverage={str(page):coverage(r) for page,r in sorted(requests.items())},
        boundary_note='Pages10 and22 retain the faulty branch but omit the whitespace helper definition; exported for context-boundary inspection, not scored as fully supported positive packets.')
    if (root/'inputs.json').exists() and read(root/'inputs.json')!=manifest:raise InputError('Frozen implementation probe changed')
    write(root/'inputs.json',manifest);write(root/'references.json',references);write(root/'source.json',source)
    write(root/'independent-reproduction.json',read(REPRODUCTION))
    for request in requests.values():write(root/'requests'/(digest(request)+'.json'),request)
    model=manifest['protocol']['model'];client=client or JevClient(model=model)
    if client.model!=model:raise InputError('Client model differs')
    results=[];calls=0
    for page,event in PRIMARY.items():
        request=requests[page];key=digest(request);path=root/'receipts'/(key+'.json')
        result=dict(page=page,target_event_id=event,request_hash=key,complete=False,error_type=None)
        try:
            if path.exists():
                saved=read(path)
                if saved['request']!=request:raise InputError('Cached implementation request changed')
                response=saved['response']
            elif live and calls<max_calls:
                calls+=1;response=client.transport(request);write(path,dict(request=request,response=response))
            else:results.append(result);continue
            if response.get('model')!=model:raise InputError('Response model differs')
            answers=validate_answers(response,request)
            selections={field:dict(requirement_id=request['state']['requirements'][field]['id'],selection=a['value'],
                event_id=request['state']['source_fragments'].get(a['value'],{}).get('event_id')) for field,a in answers.items()}
            target=next(a for a in selections.values() if a['requirement_id']==REQUIREMENT)
            prediction=1 if target['event_id']==event else None if target['selection'] in {'unresolved','unverified_claim'} else 0
            result.update(complete=True,target_prediction=prediction,reference_match=prediction==1,answers=selections,
                selected_event_ids=sorted({a['event_id'] for a in selections.values() if a['event_id']}))
        except Exception as error:result['error_type']=type(error).__name__
        results.append(result);print(dumps(result),flush=True)
    report=dict(schema='requirement-httpx-implementation-report/1',input_hash=digest(manifest),reference_hash=digest(references),
        new_calls_this_invocation=calls,status='failed' if any(r['error_type'] for r in results) else 'complete' if all(r['complete'] for r in results) else 'pending',
        results=results,scope='Two supplemental exact production8 implementation-page comparisons, all six original selected requirements and all original choices. Independent reproduction and packet review fixed positive references before calls. Pages10/22 remain boundary-only exports. Original e218 reference and score unchanged; no complete-rollout claim.')
    write(root/'report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='outputs/requirement-httpx-implementation')
    parser.add_argument('--live',action='store_true');parser.add_argument('--prompt-key',action='store_true')
    parser.add_argument('--max-calls',type=int,default=2)
    args=parser.parse_args()
    if args.live and args.prompt_key:os.environ['JEV_API_KEY']=getpass.getpass('Jev credential for this process: ')
    report=evaluate(args.output,live=args.live,max_calls=args.max_calls)
    print(dumps({k:v for k,v in report.items() if k!='results'}))
