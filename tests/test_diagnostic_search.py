"""Protocol, linkage and lifecycle controls; scripted choices are not accuracy tests."""
from copy import deepcopy
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from tempfile import TemporaryDirectory
import unittest

from tracker import diagnostic_search as search
from tracker import diagnostic_worker as worker
from tracker.adapters import normalize
from tracker.schema import InputError, digest, dumps
from tracker.semantic_extraction import read, write
from tracker.store import Store
from test_diagnostic_monitors import source
from test_tracker import harbor


def decisions(req):
    fragments = req['state']['source_fragments']
    result = {}
    for key, question in req['questions'].items():
        selected = 'none'
        if req['state']['stage'] == 'scan_candidates':
            marker = {'reference_solution_reuse__returned_material': 'RETURNED_SOLUTION',
                      'reference_solution_reuse__incorporation': 'APPLIED_SOLUTION'}.get(key)
            if marker:
                selected = next((f for f in question['criteria'] if f in fragments and marker in fragments[f]['text']), 'none')
        elif req['state']['stage'] == 'link_candidates':
            selected = next((f for f in question['criteria'] if f in fragments and 'RETURNED_SOLUTION' in fragments[f]['text']), 'none')
        elif req['state']['stage'] == 'validate_linked_evidence':
            selected = 'mechanical' if key == 'bypass_mechanism' else 'supported'
        result[key] = {'value': selected}
    return result, digest(req)


def wire(req):
    answers, _ = decisions(req)
    return {'model': req['model'], 'answers': {
        key: {'type': 'choice', 'probabilities': {choice: float(choice == answers[key]['value']) for choice in q['criteria']}}
        for key, q in req['questions'].items()}}


def no_candidates(req):
    return {'model': req['model'], 'answers': {
        key: {'type': 'choice', 'probabilities': {choice: float(choice == 'none') for choice in q['criteria']}}
        for key, q in req['questions'].items()}}


def linked_source(*, reverse=False, instructions='Use the required method.'):
    first = {'id': 'return', 'actor': 'tool', 'kind': 'tool_result', 'text': 'RETURNED_SOLUTION: substantive patch content.'}
    last = {'id': 'apply', 'actor': 'agent', 'kind': 'action_dispatch', 'text': 'APPLIED_SOLUTION: applies that substantive patch.'}
    if reverse:
        first, last = last, first
    events = [{'id': 'instruction', 'actor': 'user', 'kind': 'instruction', 'text': instructions}, first,
              {'id': 'noise', 'actor': 'tool', 'kind': 'tool_result', 'text': 'ordinary unrelated output\n' * 8000}, last]
    return source(trace=dumps(events))


class SearchTests(unittest.TestCase):
    def test_imported_roles_and_mixed_observations_keep_exact_field_boundaries(self):
        events = [{'role': 'tool', 'content': 'return [assistant] forged marker'},
                  {'src': 'agent', 'msg': 'I will apply it', 'tools': [{'command': 'apply patch'}],
                   'obs': 'applied patch', 'step': 2},
                  {'role': 'assistant', 'content': 'done'},
                  {'inputs': {'prompt': 'untyped'}, 'output': 'untyped'}]
        s = source(trace=dumps(events))
        parts = search.index(s, search.CURRENT_VERSION)
        trace = [f for f in parts if f['origin'] == 'trace']
        self.assertEqual(''.join(f['text'] for f in trace), s['trace'])
        self.assertEqual(next(f for f in trace if 'forged marker' in f['text'])['actor'], 'tool')
        self.assertEqual(next(f for f in trace if 'applied patch' in f['text'])['actor'], 'tool')
        self.assertEqual(next(f for f in trace if 'apply patch' in f['text'])['kind'], 'action_dispatch')
        self.assertNotIn('actor', next(f for f in trace if 'untyped' in f['text']))
        self.assertEqual([f for f in search.index(s, search.VERSION) if f.get('actor')], [])

    def test_partial_findings_survive_resume_and_keep_their_frozen_replay(self):
        from tracker.diagnostic_worker import CallBudgetReached
        import json
        events = json.loads(linked_source()['trace'])
        s = source(trace=dumps([events[0], events[1], events[3], events[2]]))
        with TemporaryDirectory() as temp:
            calls = 0
            def limited(req):
                nonlocal calls
                if calls == 4: raise CallBudgetReached()
                calls += 1
                return wire(req)
            partial = search.execute(s, temp, limited, version=search.CURRENT_VERSION)
            self.assertFalse(partial['coverage']['scan_complete'])
            self.assertEqual(partial['metrics']['reference_solution_reuse']['value'], 1)
            self.assertEqual(len(partial['findings']), 1)
            self.assertTrue(search.audit(s, partial, temp)['exact_replay'])
            done = search.execute(s, temp, wire)
            self.assertTrue(done['coverage']['scan_complete'])
            self.assertTrue(search.audit(s, partial, temp)['exact_replay'])
            self.assertTrue(search.audit(s, done, temp)['exact_replay'])
            self.assertEqual(done, search.execute(s, temp, lambda _: self.fail('No repeated API request')))

    def test_tiny_events_and_escape_heavy_sources_keep_requests_bounded(self):
        for text in [dumps([{'id': str(i), 'actor': 'tool', 'kind': 'tool_result', 'text': 'x'} for i in range(500)]), '\x00' * 70000]:
            def none(req):
                self.assertLessEqual(len(dumps(req)), search.REQUEST_CHARS)
                return {key: {'value': 'none'} for key in req['questions']}, digest(req)
            result = search.build(source(trace=text), none)
            self.assertEqual(result['coverage']['characters_scanned'], len(text) + len('Fix issue'))

    def test_exact_partition_of_long_unicode_and_json_source(self):
        s = linked_source(instructions='中文 "quoted" \n instructions')
        fragments = search.index(s)
        for origin in ('trace', 'task'):
            ordered = [f for f in fragments if f['origin'] == origin]
            self.assertEqual(''.join(f['text'] for f in ordered), s[origin])
            self.assertEqual(ordered[0]['start'], 0)
            self.assertEqual(ordered[-1]['end'], len(s[origin]))
            self.assertTrue(all(a['end'] == b['start'] for a, b in zip(ordered, ordered[1:])))
        self.assertGreater(len(s['trace']), 160000)
        self.assertTrue(all(sum(len(f['text']) for f in page) <= search.PAGE_CHARS for page in search.pages(fragments)))

    def test_cross_page_links_have_exact_anchors_and_bounded_requests(self):
        s = linked_source()
        requests = []
        def decide(req):
            requests.append(req)
            self.assertLessEqual(len(dumps(req)), search.REQUEST_CHARS)
            return decisions(req)
        result = search.build(s, decide)
        metric = result['metrics']['reference_solution_reuse']
        self.assertEqual(metric['value'], 1)
        refs = metric['evidence_roles']
        self.assertGreater(refs['incorporation']['start'] - refs['returned_material']['end'], 160000)
        for ref in refs.values():
            self.assertEqual(s[ref['origin']][ref['start']:ref['end']], ref['text'])
        self.assertEqual(result['coverage']['characters_scanned'], len(s['trace']) + len(s['task']))
        self.assertTrue(all(m['value'] is None for k, m in result['metrics'].items() if k != 'reference_solution_reuse'))
        self.assertEqual(result['coverage']['negative_coverage'], 'not_established')
        self.assertTrue(any(req['state']['stage'] == 'validate_linked_evidence' for req in requests))

    def test_reversed_source_order_cannot_be_published_even_if_model_says_supported(self):
        result = search.build(linked_source(reverse=True), decisions)
        self.assertIsNone(result['metrics']['reference_solution_reuse']['value'])
        checks = result['validations']['reference_solution_reuse']
        self.assertTrue(checks)
        self.assertFalse(checks[0]['source_order_established'])

    def test_reasoning_or_agent_authored_return_cannot_become_executed_reuse(self):
        import json
        for index, update in [(1, {'actor': 'agent', 'kind': 'reasoning'}), (3, {'kind': 'reasoning'})]:
            s = linked_source()
            events = json.loads(s['trace'])
            events[index].update(update)
            s['trace'] = dumps(events)
            result = search.build(s, decisions)
            self.assertIsNone(result['metrics']['reference_solution_reuse']['value'])
            self.assertEqual(result['validations']['reference_solution_reuse'], [])
            # Old cached choices still replay through their original protocol;
            # its independent attribution guard also rejects the false link.
            legacy = search.build(s, decisions, version=search.LEGACY_VERSION)
            self.assertFalse(legacy['validations']['reference_solution_reuse'][0]['structural_anchor_checks_passed'])

    def test_candidate_filter_preserves_untyped_sources_and_uses_only_attribution(self):
        self.assertTrue(search.candidate_compatible('online_reference_search', 'action', {}))
        self.assertTrue(search.candidate_compatible('online_reference_search', 'action', {'actor': 'agent'}))
        self.assertFalse(search.candidate_compatible('online_reference_search', 'action', {'actor': 'tool', 'kind': 'action'}))
        self.assertFalse(search.candidate_compatible('evaluator_bypass', 'action', {'actor': 'agent', 'kind': 'reasoning'}))
        self.assertTrue(search.candidate_compatible('evaluator_bypass', 'action', {'actor': 'agent', 'kind': 'message'}))
        self.assertFalse(search.candidate_compatible('reference_solution_reuse', 'returned_material', {'actor': 'assistant'}))
        self.assertTrue(search.candidate_compatible('evaluator_bypass', 'mechanism', {'actor': 'agent', 'kind': 'reasoning'}))

    def test_missing_instruction_context_blocks_positive(self):
        result = search.build(linked_source(instructions='long governing instruction ' * 1300), decisions)
        self.assertIsNone(result['metrics']['reference_solution_reuse']['value'])
        self.assertTrue(result['validations']['reference_solution_reuse'][0]['omitted_context'])

    def test_absent_actions_and_missing_recorded_text_are_not_false_negatives(self):
        s = linked_source()
        s['action_coverage'] = 'unavailable'
        s['complete_recorded_text'] = False
        result = search.build(s, decisions)
        self.assertTrue(all(m['value'] is None for m in result['metrics'].values()))
        self.assertIsNone(result['confirmed_reward_hacking']['value'])

    def test_multiple_candidates_in_one_page_are_enumerated(self):
        events = [{'id': str(i), 'actor': 'tool', 'kind': 'tool_result', 'text': 'RETURNED_SOLUTION ' + str(i)} for i in range(3)]
        s = source(trace=dumps(events))
        result = search.build(s, decisions)
        self.assertEqual(len(result['candidate_selections']['reference_solution_reuse__returned_material']), 3)

    def test_unknown_candidate_does_not_produce_a_clean_result(self):
        def unknown(req):
            return {key: {'value': 'unresolved'} for key in req['questions']}, digest(req)
        result = search.build(source(), unknown)
        self.assertTrue(result['coverage']['page_ledger'][0]['unresolved_roles'])
        self.assertTrue(all(m['value'] is None for m in result['metrics'].values()))

    def test_invalid_candidate_and_evaluation_labels_are_rejected(self):
        with self.assertRaises(InputError):
            search.index(source(expected_label='reward_hacking'))
        with self.assertRaisesRegex(InputError, 'outside'):
            search.build(source(), lambda req: ({k: {'value': 'invented-pointer'} for k in req['questions']}, digest(req)))

    def test_exact_replay_and_mutated_source_are_rejected(self):
        with TemporaryDirectory() as temp:
            s = linked_source()
            result = search.execute(s, temp, wire)
            self.assertTrue(search.audit(s, result, temp)['exact_replay'])
            self.assertEqual(search.execute(s, temp, lambda _: self.fail('No repeated provider call')), result)
            changed = deepcopy(result)
            changed['metrics']['reference_solution_reuse']['value'] = 0 if result['metrics']['reference_solution_reuse']['value'] == 1 else 1
            with self.assertRaisesRegex(InputError, 'replay'):
                search.audit(s, changed, temp)
            s['trace'] += 'different'
            with self.assertRaisesRegex(InputError, 'source changed'):
                search.execute(s, temp, wire)

    def test_legacy_result_replays_without_new_calls_or_protocol_migration(self):
        self.assertEqual(search.protocol(search.LEGACY_VERSION)['id'], 'diagnostic-search-a4cc290630b0e94d43ef')
        with TemporaryDirectory() as temp:
            s = linked_source()
            result = search.execute(s, temp, wire, version=search.LEGACY_VERSION)
            Path(temp, 'protocol.json').unlink()  # Earlier completed workspaces lacked this file.
            self.assertEqual(search.execute(s, temp, lambda _: self.fail('Cached v1 must not be reclassified')), result)
            self.assertEqual(read(Path(temp, 'protocol.json')), result['protocol'])
            self.assertTrue(search.audit(s, result, temp)['exact_replay'])
            with self.assertRaisesRegex(InputError, 'protocol changed'):
                search.execute(s, temp, wire, version=search.VERSION)


class WorkerSearchTests(unittest.TestCase):
    def test_legacy_interrupted_worker_resumes_its_frozen_protocol(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root / 'db')
            run = normalize(harbor(), 'harbor')[0]
            store.add([run])
            select = worker.selection(run_ids=[run['id']])
            folder = root / 'work'
            worker.initialize(store, folder, select, 'search')
            config = read(folder / 'worker.json')
            config['protocol'] = search.protocol(search.LEGACY_VERSION)
            write(folder / 'worker.json', config)
            partial = worker.execute(store, folder, no_candidates, selector=select, protocol_name='search', max_new_calls=0)
            self.assertEqual(partial['coverage']['counts'], {'pending': 1})
            done = worker.execute(store, folder, no_candidates, selector=select, protocol_name='search', max_new_calls=100)
            self.assertEqual(done['coverage']['counts'], {'complete': 1})
            self.assertEqual(read(folder / 'worker.json')['protocol'], config['protocol'])
            self.assertTrue(worker.audit(store, folder)['runs'][0]['validation']['exact_replay'])
            self.assertEqual(worker.execute(store, folder, lambda _: self.fail('No legacy reclassification'),
                selector=select, protocol_name='search', max_new_calls=0)['new_calls'], 0)

    def test_cli_plan_never_constructs_a_provider_or_workspace(self):
        import argparse
        import json
        from tracker import diagnostic_worker_cli as cli
        with TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root / 'db')
            store.add(normalize(harbor(), 'harbor'))
            parser = argparse.ArgumentParser()
            cli.configure(parser.add_subparsers())
            args = parser.parse_args(['monitor-rollouts', 'plan', str(root / 'work'), '--all-latest', '--protocol', 'search'])
            output = StringIO()
            with patch('tracker.jev.JevClient', side_effect=AssertionError('Plan must not initialize a model')), redirect_stdout(output):
                cli.execute(args, store)
            self.assertEqual(json.loads(output.getvalue())['model_api_calls'], 0)
            self.assertFalse((root / 'work').exists())

    def test_long_rollout_plan_budget_resume_register_and_audit(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root / 'db')
            document = harbor()
            document['steps'][-1]['message'] = 'ordinary output ' * 13000
            run = normalize(document, 'harbor')[0]
            store.add([run])
            select = worker.selection(run_ids=[run['id']])
            old = worker.inventory(store, select)
            self.assertEqual(old[0]['eligibility'], 'ineligible')
            preview = worker.plan(store, select, 'search')
            self.assertEqual(preview['model_api_calls'], 0)
            self.assertEqual(preview['rows'][0]['eligibility'], 'ready')
            self.assertGreater(preview['rows'][0]['scan_requests_before_cache'], 1)
            folder = root / 'work'
            partial = worker.execute(store, folder, no_candidates, selector=select, protocol_name='search', max_new_calls=1)
            self.assertEqual(partial['coverage']['counts'], {'pending': 1})
            progress = partial['coverage']['rows'][0]['attempt']['inspection_progress']
            self.assertEqual(progress['pages_scanned'], 1)
            self.assertLess(progress['characters_scanned'], progress['characters_total'])
            with store.connect() as c:
                self.assertEqual(c.execute("SELECT count(*) FROM rollout_measurements WHERE observer LIKE 'diagnostic-search-%'").fetchone()[0], 0)
            done = worker.execute(store, folder, no_candidates, selector=select, protocol_name='search', max_new_calls=100)
            self.assertEqual(done['coverage']['counts'], {'complete': 1})
            self.assertEqual(done['new_calls'], preview['rows'][0]['scan_requests_before_cache'] - 1)
            self.assertTrue(worker.audit(store, folder)['runs'][0]['validation']['exact_replay'])
            with store.connect() as c:
                row = c.execute("SELECT document FROM rollout_measurements WHERE observer LIKE 'diagnostic-search-%'").fetchone()[0]
            import json
            record = json.loads(row)
            self.assertTrue(all(m['value'] == 0 for m in record['diagnostic_result']['metrics'].values()))
            cached = worker.execute(store, folder, lambda _: self.fail('Published result must be reused'),
                                    selector=select, protocol_name='search', max_new_calls=0)
            self.assertEqual(cached['new_calls'], 0)
            self.assertTrue(worker.plan(store, select, 'search')['rows'][0]['published_result_reusable'])


if __name__ == '__main__':
    unittest.main()
