"""Test broader method candidate recall on frozen, freshly generated source maps.

Reference review stays outside model requests. A related pair is only a candidate;
the independent work-instance decision must pass before comparing procedures.
"""
import argparse
from copy import deepcopy
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker import method_comparison, semantic_workspace as workspace
from tracker.jev import JevClient
from tracker.schema import digest, dumps
from tracker.semantic_extraction import FileCandidates, Pipeline, load_extraction, read, write


VERSION = 'work-method-comparison/5'
RELATED = {'different_work_same_subject', 'overlapping_work_scope'}
DEFAULT_SOURCE = Path('outputs/generated-generalization-refined')
EXPECTED = {
    'simulation': {
        ('e4', 'e8'): ('same_work_instance', 'reconfigured_procedure'),
        ('e4', 'e12'): ('different_work', 'different_work'),
        ('e8', 'e12'): ('different_work', 'different_work'),
    },
    'service': {
        ('e4', 'e12'): ('different_work', 'different_work'),
        ('e8', 'e12'): ('different_work', 'different_work'),
    },
    'software': {
        ('e4', 'e8'): ('different_work', 'different_work'),
        ('e4', 'e12'): ('different_work', 'different_work'),
        ('e8', 'e12'): ('different_work', 'different_work'),
    },
    'public_airline': {('e8', 'e14'): ('different_work', 'different_work')},
    'public_telecom': {},
    'multiagent': {},
}
REASONS = {
    'simulation': 'Both advances seek R2 at G through different routes. Reading position does not move R2.',
    'service': 'Creating a reservation and retrieving its details seek different immediate results. The 18:00 and 18:30 reservations were already classified as distinct instances and are not added candidates.',
    'software': 'Editing and testing are different operations. The later test dispatch covers nested-fields plus quoted-strings; earlier testing covers only nested-fields, so the overlap does not establish identical scope.',
    'public_airline': 'Retrieving reservation details and cancelling that reservation are different operations; the visible prefix has no cancellation result.',
    'public_telecom': 'Customer lookup and a specified line lookup were classified as different instances; no same-subject or overlapping-scope edge is present.',
    'multiagent': 'No eligible recorded relationship spans these separate actors and contexts.',
}


def source_maps(directory=DEFAULT_SOURCE):
    for config_path in sorted(Path(directory).glob('*/workspace.json')):
        folder = config_path.parent
        config, source = workspace.load(folder)
        document = load_extraction(source, folder,
            action_target_version=config['action_target_version'],
            plan_relation_version=config['plan_relation_version'])['document']
        yield folder.name, source, document


def review(source, document, name):
    """An independent source review, never copied into selection requests."""
    ids = {u['id']: u['source']['event_id'] for u in document['units']}
    pairs = [{**deepcopy(r), 'previous_event_id': ids[r['to']],
              'current_event_id': ids[r['from']]}
             for r in document['relations'] if r['type'] in RELATED]
    return dict(origin='selected_public_trace' if name.startswith('public_') else 'authored_scenario',
        source_hash=digest(source), document_hash=digest(document),
        observed_related_pairs=pairs,
        expected=[dict(previous_event_id=a, current_event_id=b, work_instance=w, comparison=c)
                  for (a, b), (w, c) in EXPECTED[name].items()],
        reason=REASONS[name],
        scope='Development source review; not independently annotated or representative deployment accuracy.')


def evaluate(directory, *, source_directory=DEFAULT_SOURCE, live=False, transport=None):
    root = Path(directory)
    if VERSION not in method_comparison.VERSIONS:
        raise RuntimeError('Production method candidate-recall version is not available yet')
    client = JevClient()
    reports = {}
    for name, source, document in source_maps(source_directory):
        folder = root/name
        inputs = dict(source=source, document=document)
        if (folder/'input.json').exists() and read(folder/'input.json') != inputs:
            raise ValueError('Source map changed; use a new output directory')
        write(folder/'input.json', inputs)
        reviewed = review(source, document, name)
        write(folder/'reference-review.json', reviewed)
        before = deepcopy(inputs)
        def unavailable(request):
            raise RuntimeError('No saved response for request '+digest(request)+'; rerun with --live')
        engine = Pipeline(folder, FileCandidates(folder),
                          transport or (client.transport if live else unavailable))
        result, audit = method_comparison.execute(source, document, engine, version=VERSION)
        if inputs != before:
            raise AssertionError('Method analysis changed upstream source or graph')
        ids = {u['id']: u['source']['event_id'] for u in document['units']}
        actual = {(ids[r['previous_unit_id']], ids[r['current_unit_id']]): r
                  for r in result['observations']}
        expected = EXPECTED[name]
        scores = [dict(previous_event_id=a, current_event_id=b,
                       expected_work=w, expected_comparison=c,
                       actual_work=actual.get((a,b),{}).get('work_instance'),
                       actual_comparison=actual.get((a,b),{}).get('comparison'),
                       correct=actual.get((a,b),{}).get('work_instance') == w and
                               actual.get((a,b),{}).get('comparison') == c)
                  for (a,b),(w,c) in expected.items()]
        report = dict(result=result, audit=audit, scores=scores,
                      missing_pairs=[list(pair) for pair in expected if pair not in actual],
                      unexpected_pairs=[list(pair) for pair in actual if pair not in expected])
        write(folder/'report.json', report)
        reports[name] = dict(pairs=len(scores), correct=sum(s['correct'] for s in scores),
                            missing_pairs=report['missing_pairs'], unexpected_pairs=report['unexpected_pairs'],
                            counts=result['counts'])
        write(root/'summary.json', reports)
        print(name, dumps(reports[name]), flush=True)
    return reports


def freeze(directory, destination):
    root=Path(directory)
    records={}
    for report_path in sorted(root.glob('*/report.json')):
        folder=report_path.parent
        records[folder.name] = dict(**read(folder/'input.json'), review=read(folder/'reference-review.json'),
            report=read(report_path),
            receipts={p.stem:read(p) for p in (folder/'decisions').glob('*.json')})
    write(Path(destination), dict(schema='generated-method-candidate-recall/1', cases=records,
        scope='Actual source-bound generated maps and live Jev decisions. Software replay and a small development source review, not a general semantic accuracy estimate.'))
    return dict(cases=len(records), receipts=sum(len(r['receipts']) for r in records.values()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='outputs/generated-method-recall')
    parser.add_argument('--source', default=str(DEFAULT_SOURCE))
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--prompt-key', action='store_true')
    parser.add_argument('--freeze')
    args = parser.parse_args()
    if args.live and args.prompt_key:
        os.environ['JEV_API_KEY'] = getpass.getpass('Jev credential for this process: ')
    print(dumps(evaluate(args.output, source_directory=args.source, live=args.live)))
    if args.freeze:
        print(dumps(freeze(args.output, args.freeze)))
