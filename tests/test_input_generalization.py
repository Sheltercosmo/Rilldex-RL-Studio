"""Cross-route contracts, not claims of native distributed trainer validation."""
import ast
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from rilldex import Episode, Outbox, chat_document, generation_document
from tracker.adapters import FORMATS, detect, normalize
from tracker.capabilities import links
from tracker.connections import validate
from tracker.deployment_setup import plan
from tracker.graph_store import build
from tracker.import_batch import read_bytes
from tracker.input_catalog import catalog
from tracker.rollout_metrics import source_record
from tracker.schema import InputError
from tracker.source_discovery import discover
from tracker.store import Store
from test_portable import conversation


def records():
    chat = conversation()
    del chat['trajectory_format']
    chat['messages'][-1]['tool_calls'] = None
    episode = (Episode(episode_id='maze-42', goal='Reach the exit.')
               .reset({'position': 0})
               .gym_step('right', ({'position': 1}, 1, False, True, {}),
                         model_response='I will try the right passage.').snapshot())
    public = Path(__file__).parent / 'fixtures/tau-bench/airline-0.json'
    return {
        'conversation': chat,
        'reasoning': {'prompt': 'What is 7 + 5?', 'completion': '12', 'outcome': {'reward': 1}},
        'episode': episode,
        'verl': {'input': 'What is 7 + 5?', 'output': '12', 'step': 4, 'score': 1},
        'airline-public': json.loads(public.read_text(encoding='utf-8')),
    }


class GeneralizationTests(unittest.TestCase):
    def test_unmarked_parallel_results_are_linked_by_id_and_outcome_is_explicit(self):
        doc = records()['conversation']
        run = normalize(doc)[0]
        self.assertEqual(run['adapter_version'], 'chat-messages/unmarked-1')
        actions = {e['call_id']: e for e in run['events'] if e['kind'] == 'action'}
        responses = links(run)['by_action']
        self.assertEqual(responses[actions['a']['id']][0]['text'], 'Record A')
        self.assertEqual(responses[actions['b']['id']][0]['text'], 'Record B')
        self.assertEqual(run, normalize(doc, 'chat-messages')[0])
        doc = {'prompt': 'p', 'completion': 'c', 'reward': 1, 'success': True}
        metrics = source_record(normalize(doc)[0])['metrics']
        self.assertIsNone(metrics['recorded_reward']['value'])
        self.assertIsNone(metrics['recorded_success']['value'])
        self.assertIsNone(metrics['actions']['value'])
        self.assertTrue(any('outcome object' in w for w in normalize(doc)[0]['warnings']))

    def test_existing_marked_records_keep_their_adapter_versions(self):
        for doc, version in [(conversation(), 'chat-messages/1'),
                             (generation_document('p', 'c'), 'generation/1')]:
            self.assertEqual(normalize(doc)[0]['adapter_version'], version)
            unmarked = deepcopy(doc)
            del unmarked['trajectory_format']
            a, b = normalize(doc)[0], normalize(unmarked)[0]
            self.assertEqual(a['events'], b['events'])
            self.assertEqual(a['outcome'], b['outcome'])

    def test_no_guessing_of_ambiguous_records_versions_chunks_or_raw_env_steps(self):
        ambiguous = {'messages': [{'role': 'assistant', 'content': 'a'}],
                     'prompt': 'p', 'completion': 'a'}
        with self.assertRaisesRegex(InputError, 'Ambiguous'):
            normalize(ambiguous)
        self.assertEqual(normalize(ambiguous, 'generation')[0]['adapter_version'], 'generation/unmarked-1')
        for doc in ({'prompt': 'p', 'completion': 'c', 'trajectory_format': 'generation/9'},
                    {'prompt': 'p', 'completion': 'c', 'trajectory_format': None},
                    {'choices': [{'delta': {'content': 'partial'}}]},
                    {'steps': [{'action': 0, 'observation': 1}]},
                    {'learning_rate': 1e-5}, {'messages': []}):
            with self.subTest(doc=doc), self.assertRaises(InputError):
                normalize(doc)
        for fmt in ('auto', 'generation'):
            with self.assertRaises(InputError):
                normalize({'prompt': 'p', 'completion': [1, 2]}, fmt)

    def assert_evidence_equal(self, expected, actual):
        self.assertEqual(expected['events'], actual['events'])
        self.assertEqual(expected['outcome'], actual['outcome'])
        self.assertEqual(source_record(expected)['metrics'], source_record(actual)['metrics'])
        self.assertEqual(build(expected)['edges'], build(actual)['edges'])

    def test_record_evidence_survives_batch_watch_replay_and_outbox(self):
        for name, doc in records().items():
            with self.subTest(record=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                expected = normalize(doc)[0]
                raw = json.dumps(doc).encode()
                for filename, data in [('rollout.json', raw), ('rollout.jsonl', raw + b'\n')]:
                    imported = read_bytes(data, name=filename, meta={'experiment': 'parity'})[0]
                    self.assert_evidence_equal(expected, imported)
                for mode, suffix in [('exports', 'jsonl'), ('snapshots', 'json')]:
                    directory = root / mode
                    directory.mkdir()
                    store = Store(root / (mode + '.sqlite'))
                    config = dict(root=str(directory), mode=mode, producer='parity/' + mode,
                                  metadata={'experiment': 'parity'})
                    if mode == 'snapshots': config['snapshot_state'] = 'complete'
                    watcher = validate(store, config)[1]
                    self.assertEqual(watcher.poll()['scanned'], 0)
                    (directory / ('rollout.' + suffix)).write_bytes(raw + b'\n')
                    self.assertEqual(watcher.poll()['ingested'], 1)
                    actual = store.get(store.list()[0]['id'], raw=True)['run']
                    self.assert_evidence_equal(expected, actual)
                    self.assertEqual(validate(Store(store.path), config)[1].poll()['ingested'], 0)
                    found = discover(str(directory))
                    self.assertTrue(any(r['mode'] == mode for r in found['routes']), found)
                store = Store(root / 'http.sqlite')
                outbox = Outbox(root / 'worker.sqlite', producer='parity/worker-0')
                outbox.log(name, doc, state='in_progress')
                outbox.log(name, doc, state='complete')
                def receive(request, **kwargs):
                    return io.BytesIO(json.dumps(store.ingest(json.loads(request.data))).encode())
                # Exercise the actual serialized delivery packet and ingestion contract.
                # HTTP socket behavior is covered separately by the live smoke check.
                with patch('tracker.capture.urlopen', side_effect=receive):
                    self.assertEqual(outbox.drain()['sent_now'], 2)
                    self.assertEqual(outbox.drain()['sent_now'], 0)
                row = store.list()[0]
                self.assertEqual(row['ingestion']['revision'], 1)
                self.assertEqual(row['ingestion']['state'], 'complete')
                self.assert_evidence_equal(expected, store.get(row['id'], raw=True)['run'])

    def test_verl_shape_ambiguity_is_not_bypassed_by_file_routes(self):
        doc = dict(input='p', output='c', step=1, prompt='p', completion='c')
        for name in ('a.json', 'a.jsonl'):
            with self.assertRaisesRegex(InputError, 'Ambiguous'):
                read_bytes(json.dumps(doc).encode(), name=name, meta={'experiment': 'ambiguous'})
        with tempfile.TemporaryDirectory() as tmp:
            for mode, suffix in [('exports', 'jsonl'), ('snapshots', 'json')]:
                root = Path(tmp) / mode
                root.mkdir()
                (root / ('rollout.' + suffix)).write_text(json.dumps(doc) + '\n', encoding='utf-8')
                store = Store(Path(tmp) / (mode + '.sqlite'))
                report = validate(store, dict(root=str(root), mode=mode, producer='w',
                                             metadata={'experiment': 'ambiguous'}))[1].poll()
                self.assertEqual(report['ingested'], 0)
                self.assertEqual(store.list(), [])
                self.assertFalse(discover(str(root))['routes'])

    def test_schema_catalog_and_setup_keep_layout_separate(self):
        formats = catalog()['formats']
        self.assertEqual({f['id'] for f in formats}, set(FORMATS))
        self.assertEqual({f['id'] for f in formats if 'native' in f['collection_modes']},
                         {'auto', 'harbor', 'swe-agent'})
        for case in ('local', 'remote', 'docker', 'cloud', 'notebook', 'offline'):
            options = dict(case=case, mode='snapshots', format='chat-messages')
            if case == 'docker': options['root'] = '/jobs/output'
            if case == 'cloud': options['root'] = 's3://bucket/output'
            result = plan(options)
            self.assertIn('chat-messages', '\n'.join(s['code'] for s in result['steps']))
            if result['launch_file']:
                self.assertEqual(result['launch_file']['source']['format'], 'chat-messages')
            if result['connection']:
                self.assertEqual(result['connection']['format'], 'chat-messages')
            if case == 'notebook': ast.parse(result['steps'][1]['code'])
        with self.assertRaisesRegex(InputError, 'incompatible'):
            plan(dict(mode='native', format='environment-episode'))
        # Offline capture has no file layout, including when the old default is native.
        self.assertIn('environment-episode', plan(dict(case='offline', format='environment-episode'))['steps'][0]['code'])

    def test_code_only_setup_preserves_selected_schema(self):
        result = subprocess.run([sys.executable, '-m', 'rilldex', 'setup', '--mode', 'exports',
                                 '--format', 'chat-messages'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['launch_file']['source']['format'], 'chat-messages')


if __name__ == '__main__':
    unittest.main()
