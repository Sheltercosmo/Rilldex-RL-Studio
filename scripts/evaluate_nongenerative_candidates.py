"""Evaluate candidate availability, not semantic accuracy or Jev selection.

The three saved development maps are comparison references, not independent
gold. No model is called and no production observation is modified.
"""
import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.entity_candidates import span_candidates
from tracker.schema import digest
from tracker.semantic_extraction import partition_options, read, windows, write


def bounds(text, a, b):
    while a < b and text[a].isspace(): a += 1
    while b > a and text[b-1].isspace(): b -= 1
    return (a, b)


def evaluate(root):
    rows = []; content = []; sources = []; exclusions = []
    for domain in ('software', 'airline', 'retail'):
        directory = root/'research/work-context-2026-10-08'/domain
        result = read(next((directory/'results').glob('*.json')))
        run = read(directory/'runs'/f'{result["run_id"]}.json')
        assert digest(run) == result['source_hash']
        sources.append({'domain': domain, 'run_id': run['id'], 'source_hash': digest(run),
                        'reference_hash': digest(result), 'reference_path': str(directory/'results'/f'{run["id"]}.json')})
        events = {e['id']: e for e in run['events']}
        for w in windows(run, include_user=bool(result.get('participant_scope'))):
            text = events[w['event_id']]['text']
            units = [u for u in result['units'] if u['source']['event_id'] == w['event_id']
                     and w['start'] <= u['source']['start'] < u['source']['end'] <= w['end']]
            if not units:
                excluded = next((x for x in result.get('source_exclusions', []) if x['window_id'] == w['id']), None)
                if excluded:
                    exclusions.append({'domain': domain, **excluded}); continue
                raise ValueError(f'No reference coverage for {domain}/{w["id"]}')
            expected = [bounds(text, u['source']['start'], u['source']['end']) for u in units]
            options = partition_options(run, w)
            available = [[bounds(text, r['start'], r['end']) for r in p['units']] for p in options]
            sites = set()
            for ps in available:
                for (_, end), (start, _) in zip(ps, ps[1:]): sites.add((end, start))
            wanted = [(a[1], b[0]) for a, b in zip(expected, expected[1:])]
            rows.append({'domain': domain, 'run_id': run['id'], 'event_id': w['event_id'],
                         'kind': w['kind'], 'source': w['text'], 'reference': expected,
                         'reference_activities': [u['activity'] for u in units],
                         'options': [{'origin': p['origin'], 'spans': ps} for p, ps in zip(options, available)],
                         'whole_matches': available[0] == expected,
                         'existing_partition_available': expected in available,
                         'mergeable_boundary_pool_covers': all(s in sites for s in wanted),
                         'missing_boundary_sites': [s for s in wanted if s not in sites],
                         'proposed_internal_sites': len(sites),
                         'all_boundary_subsets': 2**len(sites)})
        for u in result['units']:
            if u['kind'] == 'action': continue
            ref = u['source']; event = events[ref['event_id']]
            unit = {'id': u['id'], 'event_id': ref['event_id'], 'source_pointer': ref['source_pointer'],
                    'start': ref['start'], 'end': ref['end'], 'text': ref['text'], 'kind': 'semantic'}
            candidates, coverage = span_candidates(unit, event)
            target = u['content'].get('work_target')
            content.append({'domain': domain, 'run_id': run['id'], 'unit_id': u['id'],
                            'event_id': ref['event_id'], 'actor': u.get('actor', 'agent'),
                            'activity': u['activity'], 'source': ref['text'],
                            'reference_target': target, 'reference_plan': u.get('plan_structure'),
                            'candidates': candidates, 'coverage': coverage})
    counts = Counter()
    for r in rows:
        prefix = 'dispatch' if r['kind'] == 'action_dispatch' else 'prose'
        counts[prefix+'_windows'] += 1
        for metric in ('whole_matches', 'existing_partition_available', 'mergeable_boundary_pool_covers'):
            counts[prefix+'_'+metric] += int(r[metric])
    return {'schema': 'nongenerative-candidate-evaluation/1',
            'reference_status': 'Previously inspected, assistant-proposed development maps. Not independent gold.',
            'scope': 'Candidate availability only; no Jev inference and no accuracy estimate.',
            'sources': sources, 'counts': dict(counts), 'exclusions': exclusions,
            'boundaries': rows, 'content_candidates': content}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = evaluate(Path(__file__).resolve().parents[1])
    write(args.output, report)
    print(report['counts'])
    for r in report['boundaries']:
        if not r['existing_partition_available']:
            print(r['domain'], r['event_id'], 'expected', r['reference'],
                  'pool_covers', r['mergeable_boundary_pool_covers'], 'source:', r['source'][:700])
