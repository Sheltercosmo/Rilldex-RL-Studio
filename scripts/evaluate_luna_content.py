"""Local content trial, with fixed prior units/activities and source validation."""
import argparse
import getpass
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient
from tracker.schema import digest, dumps
from tracker.semantic_extraction import Pipeline, read, request, validate_proposals, write


def evaluate(root, transport):
    inputs = read(root/'selection-readable/input.json'); cases = read(root/'luna-content/manifest.json')['cases']
    rows = []; engine = Pipeline(root/'content-selection', None, transport)
    for case in cases:
        domain = case['case'].split('/')[0]; run = inputs['sources'][domain]
        req = read(case['request_file']); response = read(root/'luna-content/responses'/f'{case["request_hash"]}.json')
        assert digest(req) == case['request_hash']
        cs = validate_proposals(run, req, response)
        selector = request(run, req['source'], 'content',
            'Choose the most faithful coherent content bundle for the established activity. Require useful natural-language meanings with source support. A citation alone does not establish entailment. Select no_suitable_candidate if every bundle invents content or loses an essential distinction.',
            {**{f'c{i}': dumps({**{k:v.get('text',v['status']) for k,v in c['fields'].items()},
                 **({'plan_structure':c['plan_structure']} if 'plan_structure' in c else {})}) for i,c in enumerate(cs)},
             'no_suitable_candidate':'All bundles need repair.', 'unresolved':'Source meaning cannot be established.'},
            activity=req['activity'], field_contract=req['field_contract'], content_candidates=cs,
            candidate_producer=response['producer'], context_policy=inputs['context_policy'],
            **({'plan_structure_contract': req['plan_structure_contract']} if 'plan_structure_contract' in req else {}))
        answers, key = engine.decide(selector); winner = answers['choice']['value']
        candidate = cs[int(winner[1:])] if winner.startswith('c') else None
        rows.append({'case': case['case'], 'generation_request': case['request_hash'], 'proposal_hash': digest(response),
                     'structural_and_source_validation': True, 'selection': winner, 'decision': key,
                     'selected_content': candidate, 'upstream_units_and_activities': 'Fixed development input, not evaluated here.'})
        write(root/'content-selection/results.json', {'schema':'local-content-trial/1', 'cases':rows})
        print(case['case'], winner, candidate['fields']['work_target']['text'] if candidate else '', flush=True)
    print({'cases':len(rows), 'selected':sum(x['selected_content'] is not None for x in rows), 'new_calls':engine.calls})


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('directory',type=Path)
    parser.add_argument('--prompt-key',action='store_true'); parser.add_argument('--max-new-calls',type=int,default=10)
    args=parser.parse_args(); client=JevClient(); calls=[0]; prompted=[False]
    def transport(req):
        if calls[0]>=args.max_new_calls:raise RuntimeError('Call budget reached; rerun to resume.')
        if args.prompt_key and not prompted[0]:
            os.environ['JEV_API_KEY']=getpass.getpass('Jev key (process memory only): ');prompted[0]=True
        calls[0]+=1;response=client.transport(req)
        write(args.directory/'content-selection/wire'/digest(req)/f'{time.time_ns()}.json',{'request':req,'response':response})
        return response
    evaluate(args.directory,transport)
