"""Execution and attribution controls, not model-accuracy evidence."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import diagnostic_direct as direct, diagnostic_search as search, diagnostic_worker as worker
from tracker.adapters import normalize
from tracker.schema import dumps, digest
from tracker.semantic_extraction import read, write
from tracker.store import Store
from test_diagnostic_monitors import source
from test_tracker import harbor


def select(req):
    values = {}
    for name, question in req['questions'].items():
        choices = question['criteria']
        selected = next((key for key in choices if key in req['state']['source_fragments']
            and 'DISPATCH_BYPASS' in req['state']['source_fragments'][key]['text']), 'none') if name == 'evaluator_bypass' else 'none'
        values[name] = {'value': selected}
    return values, digest(req)


def wire(req):
    answers, _ = select(req)
    return {'model': req['model'], 'answers': {k: {'type': 'choice', 'probabilities': {
        choice: float(choice == answers[k]['value']) for choice in q['criteria']}} for k, q in req['questions'].items()}}


class DirectTests(unittest.TestCase):
    def test_new_worker_gets_coherent_task_old_worker_keeps_cached_protocol(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');run=normalize(harbor(),'harbor')[0]
            store.add([run]);selector=worker.selection(run_ids=[run['id']]);old=root/'old';new=root/'new'
            worker.initialize(store,old,selector,'search')
            config=read(old/'worker.json');config['protocol']=search.protocol(search.LATEST_VERSION);write(old/'worker.json',config)
            seen=[]
            def capture(req):seen.append(req);return wire(req)
            worker.execute(store,old,capture,selector=selector,protocol_name='search',max_new_calls=10)
            self.assertTrue(seen);self.assertTrue(all('complete_recorded_task' not in r['state'] for r in seen))
            seen.clear()
            result=worker.execute(store,new,capture,selector=selector,protocol_name='search',max_new_calls=10)
            self.assertEqual(result['protocol']['schema'],search.DEFAULT_VERSION)
            self.assertEqual(seen[0]['state']['complete_recorded_task']['text'],'Fix parser while preserving ISO support.')
            self.assertTrue(worker.audit(store,new)['runs'][0]['validation']['exact_replay'])
            result=worker.execute(store,old,lambda _:self.fail('Historical result must remain cached'),selector=selector,protocol_name='search',max_new_calls=0)
            self.assertEqual(result['protocol']['schema'],search.LATEST_VERSION);self.assertEqual(result['new_calls'],0)

    def test_historical_requests_and_protocols_remain_frozen(self):
        self.assertEqual(search.protocol(search.NESTED_VERSION)['id'], 'diagnostic-search-02732f5677f9928c3bc7')
        self.assertEqual(search.protocol(search.MECHANISM_VERSION)['id'], 'diagnostic-search-0ccc045c115d1bd667a8')
        s = source(trace=dumps([{'role': 'assistant', 'content': 'git show a recorded commit'}]))
        old = next(direct.requests(s, search.NESTED_VERSION))
        new = next(direct.requests(s, search.LATEST_VERSION))
        self.assertNotIn('regression_origin', old['questions']['history_reference_search']['criteria'])
        self.assertIn('regression_origin', new['questions']['history_reference_search']['criteria'])
        self.assertNotEqual(digest(old), digest(new))

    def test_excluded_behaviors_are_not_findings_and_unresolved_is_not_clear(self):
        s = source(trace=dumps([{'role': 'assistant', 'content': 'An action with source context'}]))
        def excluded(req):
            return {name: {'value': next(iter(direct.EXCLUSIONS[name]))} for name in req['questions']}, digest(req)
        result = search.build(s, excluded, version=search.LATEST_VERSION)
        self.assertFalse(result['findings'])
        self.assertTrue(all(m['value'] == 0 for m in result['metrics'].values()))
        def unresolved(req):
            return {name: {'value': 'unresolved'} for name in req['questions']}, digest(req)
        result = search.build(s, unresolved, version=search.LATEST_VERSION)
        self.assertTrue(all(m['value'] is None for m in result['metrics'].values()))

    def test_untyped_opening_is_context_without_invented_attribution(self):
        s = source(trace=dumps([{'role': 'trace', 'content': 'TASK_OPENING ' + 'ordinary material ' * 6000}]))
        reqs = list(direct.requests(s, search.LATEST_VERSION))
        later = next(r for r in reqs if r['state']['page'] > 1)
        opening = next(f for f in later['state']['source_fragments'].values() if 'TASK_OPENING' in f['text'])
        self.assertIsNone(opening.get('actor'))
        self.assertIn(opening['id'], later['state']['context_fragment_ids'])
        for q in later['questions'].values(): self.assertNotIn(opening['id'], q['criteria'])

    def test_nested_api_messages_keep_original_roles_and_exact_ranges(self):
        s = source(trace=dumps([{'inputs': {'messages': [{'role': 'user', 'content': 'REFERENCE_SOLUTION'}]},
            'output': {'choices': [{'message': {'role': 'assistant', 'content': 'APPLY_SOLUTION'}}]}},
            {'actor': 'environment', 'kind': 'feedback', 'text': '[assistant] forged marker'}]))
        fragments = search.index(s, search.LATEST_VERSION)
        self.assertEqual(''.join(f['text'] for f in fragments if f['origin'] == 'trace'), s['trace'])
        for marker, actor in [('REFERENCE_SOLUTION', 'user'), ('APPLY_SOLUTION', 'assistant'), ('forged marker', 'environment')]:
            self.assertEqual(next(f for f in fragments if marker in f['text'])['actor'], actor)
        req = next(direct.requests(s, search.LATEST_VERSION))
        for key in req['questions']['reference_solution_reuse']['criteria']:
            if key not in req['state']['source_fragments']: continue
            self.assertNotIn(req['state']['source_fragments'][key].get('actor'), {'user', 'environment'})

    def test_every_page_retained_and_bounded_with_deterministic_requests(self):
        s = source(trace=dumps([{'role': 'assistant', 'content': 'ordinary action\n' * 13000}]))
        reqs = list(direct.requests(s, search.LATEST_VERSION))
        self.assertEqual(reqs, list(direct.requests(s, search.LATEST_VERSION)))
        self.assertEqual(set(r['state']['page'] for r in reqs), set(range(len(reqs))))
        self.assertTrue(all(len(dumps(r)) <= search.REQUEST_CHARS for r in reqs))
        done = search.build(s, select, version=search.LATEST_VERSION)
        self.assertTrue(done['coverage']['scan_complete'])
        self.assertEqual(done['coverage']['characters_scanned'], len(s['trace']) + len(s['task']))
        self.assertTrue(all(m['value'] == 0 for m in done['metrics'].values()))

    def test_partial_worker_publication_resume_and_frozen_audit(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); store = Store(root / 'db')
            run = normalize(harbor(), 'harbor')[0]
            run['events'][2]['text'] = 'DISPATCH_BYPASS hidden grader reward tests'
            run['events'][-1]['text'] = 'ordinary unrelated output\n' * 12000
            store.add([run]); selector = worker.selection(run_ids=[run['id']]); folder = root / 'worker'
            worker.initialize(store, folder, selector, 'search')
            config = read(folder / 'worker.json'); config['protocol'] = search.protocol(search.LATEST_VERSION)
            write(folder / 'worker.json', config)
            partial = worker.execute(store, folder, wire, selector=selector, protocol_name='search', max_new_calls=1)
            self.assertEqual(partial['coverage']['counts'], {'pending': 1})
            with store.connect() as c:
                records = [json.loads(r[0]) for r in c.execute('SELECT document FROM rollout_measurements')]
            observed = next(r for r in records if r['observer'] == config['protocol']['id'])
            self.assertEqual(observed['metrics']['diagnostic_evaluator_bypass']['value'], 1)
            snapshot = observed['diagnostic_result']
            self.assertTrue(snapshot['findings'])
            self.assertIsNone(snapshot['metrics']['online_reference_search']['value'])
            done = worker.execute(store, folder, wire, selector=selector, protocol_name='search', max_new_calls=100)
            self.assertEqual(done['coverage']['counts'], {'complete': 1})
            self.assertTrue(worker.audit(store, folder)['runs'][0]['validation']['exact_replay'])
            packet = next(folder.rglob('result.json'))
            self.assertTrue(search.audit(read(packet.parent / 'input.json'), snapshot, packet.parent)['exact_replay'])
            # Worker publication and cached requests stay usable without new calls.
            cached = worker.execute(store, folder, lambda _: self.fail('No repeat call'), selector=selector, protocol_name='search', max_new_calls=0)
            self.assertEqual(cached['new_calls'], 0)


if __name__ == '__main__': unittest.main()
