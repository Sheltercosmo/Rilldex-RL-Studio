"""Development ablation: source boundary lattice + Jev; no generated proposals.

Not connected to live monitors. Cases and full sources freeze before inference.
Selected unit endpoints are raw finite-choice winners; no probability threshold.
"""
import argparse
import getpass
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.jev import JevClient
from tracker.schema import digest
from tracker.semantic_extraction import (PARTITION_CANDIDATE_RULE, Pipeline,
                                        partition, read, request, windows, write)


VERSION = 'source-boundary-lattice/2'
CONTEXT = {'schema': 'readable-context/2', 'recent_events': 4, 'max_event_chars': 2000, 'extra_ranges': []}
CONTROLS = {('software', e) for e in ('e2', 'e8', 'e29', 'e56', 'e74', 'e101')}
CONTROLS.add(('airline', 'e28'))


def frozen_cases(root, baseline):
    sources = {s['domain']: read(Path(s['reference_path']).parent.parent/'runs'/f'{s["run_id"]}.json')
               for s in baseline['sources']}
    cases = []
    for row in baseline['boundaries']:
        if row['kind'] == 'action_dispatch': continue
        if row['existing_partition_available'] and (row['domain'], row['event_id']) not in CONTROLS: continue
        run = sources[row['domain']]
        w = next(w for w in windows(run, include_user=True) if w['event_id'] == row['event_id'])
        sites = [list(s) for s in sorted({(a[1], b[0]) for p in row['options'] for a, b in zip(p['spans'], p['spans'][1:])})]
        cases.append({'domain': row['domain'], 'run_id': run['id'], 'window': w, 'sites': sites,
                      'reference': row['reference'], 'reference_activities': row['reference_activities']})
    inputs = {'schema': VERSION, 'context_policy': CONTEXT, 'baseline_hash': digest(baseline), 'cases': cases, 'sources': sources,
              'reference_status': baseline['reference_status'],
              'sampling': 'All nine current complete-partition misses plus seven named coherent-unit controls. Development cases, not a held-out test.'}
    path = root/'input.json'
    if path.exists() and read(path) != inputs: raise ValueError('Frozen cases changed')
    if not path.exists(): write(path, inputs)
    return inputs


def build(inputs, engine):
    output = []
    for case in inputs['cases']:
        run = inputs['sources'][case['domain']]; w = case['window']; pos = w['start']; chosen = []
        decisions = []; status = 'complete'
        while pos < w['end']:
            options = [{'end': end, 'next_start': nxt} for end, nxt in case['sites'] if pos < end]
            options.append({'end': w['end'], 'next_start': w['end']})
            # Multiple syntax parsers can propose different whitespace gaps at
            # the same boundary. Keep only unique complete source spans.
            options = list({(o['end'], o['next_start']): o for o in options}.values())
            if len(options) == 1:
                choice = options[0]; key = None
            else:
                event_text = next(e['text'] for e in run['events'] if e['id'] == w['event_id'])
                criteria = {f'u{i}': f'Start {pos}, end {o["end"]} (exclusive). Final text: ' +
                            event_text[max(pos, o['end']-100):o['end']]
                            for i, o in enumerate(options)}
                criteria.update(no_suitable_candidate='The first coherent contribution ends somewhere not offered.',
                                unresolved='The contribution boundary cannot be established from supplied context.')
                req = request(run, w, 'nongenerative-unit-boundary',
                    'Select the span containing exactly the FIRST complete contribution in remaining_source. '
                    'Keep supporting rationale, concrete details and local adjustment together. Stop before a distinct contribution. '
                    'The entire remaining source is a valid choice if it is coherent. A short span is not preferable merely because it is shorter. '
                    'Do not choose based on an anticipated activity tag. Each option is literal source, not an interpretation.',
                    criteria, context_policy=CONTEXT, rule=PARTITION_CANDIDATE_RULE, boundary_harness=VERSION,
                    previous_selected_units=chosen, remaining_start=pos,
                    remaining_source=event_text[pos:w['end']])
                answers, key = engine.decide(req); winner = answers['choice']['value']
                if winner in {'no_suitable_candidate', 'unresolved'}:
                    status = winner; decisions.append(key); break
                choice = options[int(winner[1:])]
            chosen.append({'start': pos, 'end': choice['end']}); decisions.append(key); pos = choice['next_start']
        if status == 'complete': partition(run, w, chosen)
        spans = [[s['start'], s['end']] for s in chosen]
        output.append({'domain': case['domain'], 'event_id': w['event_id'], 'status': status,
                       'selected': spans, 'reference': case['reference'],
                       'exact_development_agreement': status == 'complete' and spans == case['reference'],
                       'decisions': decisions})
        write(engine.directory/'results.json', {'schema': VERSION, 'input_hash': digest(inputs), 'cases': output})
        print(case['domain'], w['event_id'], status, spans, 'reference', case['reference'], flush=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('directory', type=Path)
    parser.add_argument('--max-new-calls', type=int, default=60); parser.add_argument('--prompt-key', action='store_true')
    args = parser.parse_args(); root = args.directory
    baseline = read(root.parent/'baseline.json'); inputs = frozen_cases(root, baseline)
    client = JevClient(); calls = [0]; prompted = [False]
    def transport(req):
        if calls[0] >= args.max_new_calls: raise RuntimeError('Call budget reached; rerun to resume.')
        if args.prompt_key and not prompted[0]:
            os.environ['JEV_API_KEY'] = getpass.getpass('Jev key (process memory only): '); prompted[0] = True
        calls[0] += 1
        response = client.transport(req)
        write(root/'wire'/digest(req)/f'{time.time_ns()}.json', {'request': req, 'response': response})
        return response
    engine = Pipeline(root, None, transport)
    output = build(inputs, engine)
    print({'cases': len(output), 'exact_development_agreement': sum(x['exact_development_agreement'] for x in output), 'new_calls': calls[0]})
