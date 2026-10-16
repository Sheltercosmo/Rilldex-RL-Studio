"""Select held-source proposals; also ablate their semantic descriptions.

Development comparison only. All source references and candidate files are
frozen and checked. The proposer never receives the comparison references.
"""
import argparse
import getpass
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.contribution_readings import describe_partition_request
from tracker.jev import JevClient
from tracker.schema import digest
from tracker.semantic_extraction import (FileCandidates, PARTITION_CANDIDATE_STANDARD,
    SEMANTIC_PARTITIONS, Pipeline, partition_options, partition_request, read, write)


def evaluate(root, transport):
    original = read(root/'selection-readable/input.json')
    provider = FileCandidates(root/'luna-partitions', context_policy=original['context_policy'],
        partition_standard=PARTITION_CANDIDATE_STANDARD, partition_policy=SEMANTIC_PARTITIONS,
        contribution_readings=True)
    work = []
    for case in original['cases']:
        run = original['sources'][case['domain']]; w = case['window']
        proposals, key = provider.partitions(run, w, needed=True)
        if not proposals: raise ValueError('Missing proposal '+key)
        work.append((case, run, proposals, key))
    frozen = {'source_input_hash': digest(original), 'candidate_hashes': {
        key: digest(read(root/'luna-partitions/responses'/f'{key}.json')) for _, _, _, key in work}}
    path = root/'luna-selection/input.json'
    if path.exists() and read(path) != frozen: raise ValueError('Candidate/source changed after selection')
    if not path.exists(): write(path, frozen)
    engine = Pipeline(root/'luna-selection', None, transport); rows = []
    for case, run, proposals, key in work:
        text = case['window']['text']; offset = case['window']['start']
        def normalized(units):
            spans = []
            for unit in units:
                a, b = unit['start']-offset, unit['end']-offset
                while a < b and text[a].isspace(): a += 1
                while b > a and text[b-1].isspace(): b -= 1
                spans.append([a+offset, b+offset])
            return spans
        opts = partition_options(run, case['window'], proposals, semantic_only=True)
        base = partition_request(run, case['window'], opts, original['context_policy'], PARTITION_CANDIDATE_STANDARD)
        readings = describe_partition_request(base, proposals)
        candidate_spans = [normalized(p['units']) for p in opts]
        row = {'domain': case['domain'], 'event_id': case['window']['event_id'],
               'proposal_request': key, 'reference': case['reference'], 'candidate_spans': candidate_spans,
               'reference_partition_available': case['reference'] in candidate_spans}
        for name, req in [('without_descriptions', base), ('with_descriptions', readings)]:
            answers, decision = engine.decide(req); winner = answers['choice']['value']
            selected = next((p for p in opts if p['id'] == winner), None)
            spans = normalized(selected['units']) if selected else None
            row[name] = {'winner': winner, 'spans': spans, 'decision': decision,
                         'exact_development_agreement': spans == case['reference']}
        rows.append(row)
        write(root/'luna-selection/results.json', {'schema': 'luna-partition-comparison/1', 'frozen_hash': digest(frozen), 'cases': rows})
        print(row['domain'], row['event_id'], 'available', row['reference_partition_available'],
              'plain', row['without_descriptions']['spans'], 'described', row['with_descriptions']['spans'], flush=True)
    print({'cases': len(rows), 'candidate_coverage': sum(r['reference_partition_available'] for r in rows),
           **{n: sum(r[n]['exact_development_agreement'] for r in rows) for n in ('without_descriptions', 'with_descriptions')},
           'new_calls': engine.calls})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('directory', type=Path)
    parser.add_argument('--prompt-key', action='store_true'); parser.add_argument('--max-new-calls', type=int, default=40)
    args = parser.parse_args(); client = JevClient(); calls = [0]; prompted = [False]
    def transport(req):
        if calls[0] >= args.max_new_calls: raise RuntimeError('Call budget reached; rerun to resume.')
        if args.prompt_key and not prompted[0]:
            os.environ['JEV_API_KEY'] = getpass.getpass('Jev key (process memory only): '); prompted[0] = True
        calls[0] += 1; response = client.transport(req)
        write(args.directory/'luna-selection/wire'/digest(req)/f'{time.time_ns()}.json', {'request': req, 'response': response})
        return response
    evaluate(args.directory, transport)
