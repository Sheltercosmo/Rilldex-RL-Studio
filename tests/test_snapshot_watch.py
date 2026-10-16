import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker.connections import preview, validate
from tracker.graph_store import build
from tracker.portable import generation_document
from tracker.rollout_metrics import source_record
from tracker.schema import InputError
from tracker.store import Store
import test_export_watch
from test_portable import conversation


class SnapshotWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'output with spaces'
        self.root.mkdir()
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')
        self.config = dict(root=str(self.root), producer='experiment/worker-0', mode='snapshots',
                           metadata={'experiment': 'inspect'}, pattern='rollout-*.json')

    def watcher(self, store=None, **extra):
        return validate(store or self.store, {**self.config, **extra})[1]

    def write(self, name, doc):
        (self.root / name).write_text(json.dumps(doc), encoding='utf-8')

    def test_empty_attach_partial_update_restart_and_finished_replay(self):
        watcher = self.watcher()
        self.assertEqual(watcher.poll()['scanned'], 0)
        doc = conversation()
        path = self.root / 'rollout-a.json'
        path.write_text('{', encoding='utf-8')
        self.assertEqual(watcher.poll()['deferred'], 1)
        self.assertEqual(self.store.list(), [])
        self.write(path.name, doc)
        self.assertEqual(watcher.poll()['ingested'], 1)
        self.assertEqual(self.store.list()[0]['ingestion']['state'], 'in_progress')
        with patch.object(watcher, '_read', side_effect=AssertionError('Unchanged file reparsed')):
            self.assertEqual(watcher.poll()['ingested'], 0)
        doc['messages'].append({'role': 'assistant', 'content': 'The second record is newer.'})
        self.write(path.name, doc)
        watcher = self.watcher(Store(self.store.path))
        self.assertEqual(watcher.poll()['ingested'], 1)
        self.assertEqual(self.store.list()[0]['ingestion']['revision'], 1)
        final = self.watcher(snapshot_state='complete')
        self.assertEqual(final.poll()['ingested'], 1)
        self.assertEqual(self.store.list()[0]['ingestion']['revision'], 2)
        self.assertEqual(self.store.list()[0]['ingestion']['state'], 'complete')
        self.assertEqual(self.watcher(snapshot_state='complete').poll()['ingested'], 0)
        self.assertEqual(self.watcher().poll()['ingested'], 0)
        self.assertEqual(self.store.list()[0]['ingestion']['state'], 'complete')
        offline = Store(Path(self.tmp.name) / 'offline.sqlite')
        self.assertEqual(self.watcher(offline, snapshot_state='complete').poll()['ingested'], 1)
        run_id = self.store.list()[0]['id']
        self.assertEqual(offline.list()[0]['id'], run_id)
        a, b = self.store.get(run_id, raw=True), offline.get(run_id, raw=True)
        self.assertEqual(a['analysis'], b['analysis'])
        self.assertEqual(source_record(a['run']), source_record(b['run']))
        self.assertEqual(build(a['run']), build(b['run']))

    def test_portable_formats_share_decoder_and_keep_repeated_samples(self):
        # The same five authored source contracts used by JSONL/HTTP tests.
        documents = test_export_watch.ExportWatchTests.rows(self)
        for index, doc in enumerate(documents):
            self.write(f'rollout-{index}.json', doc)
        self.write('rollout-repeat.json', documents[0])
        self.write('config.json', {'not': 'a rollout'})
        self.assertEqual(self.watcher().poll()['ingested'], 6)
        self.assertEqual(len(self.store.list()), 6)
        self.assertEqual(self.watcher().poll()['ingested'], 0)

    def test_explicit_envelope_http_replay_identity_and_order(self):
        envelope = dict(producer=self.config['producer'], rollout_id='sample-1', revision=0,
                        state='in_progress', document=conversation(), metadata=self.config['metadata'])
        direct = self.store.ingest(envelope)
        self.write('rollout-a.json', envelope)
        self.assertEqual(self.watcher().poll()['ingested'], 0)
        envelope.update(revision=2, state='complete')
        self.write('rollout-a.json', envelope)
        self.assertEqual(self.watcher().poll()['deferred'], 1)
        envelope['revision'] = 1
        self.write('rollout-a.json', envelope)
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        self.assertEqual(self.store.list()[0]['id'], direct['id'])
        self.assertEqual(self.store.list()[0]['ingestion']['state'], 'complete')
        self.assertFalse(self.store.ingest(envelope)['received'])

    def test_missing_explicit_revision_rejected_in_preview_and_collection(self):
        self.write('rollout-a.json', dict(document=conversation(), rollout_id='x', state='complete'))
        checked = preview(self.store, self.config)
        self.assertIn('revision', checked['samples'][0]['detail'])
        self.assertEqual(self.watcher().poll()['deferred'], 1)

    def test_invalid_file_does_not_block_other_files_or_erase_last_good_source(self):
        self.write('rollout-a.json', conversation())
        self.write('rollout-b.json', generation_document('Q', 'A'))
        watcher = self.watcher()
        self.assertEqual(watcher.poll()['ingested'], 2)
        (self.root / 'rollout-a.json').write_text('{', encoding='utf-8')
        self.write('rollout-c.json', generation_document('Q', 'B'))
        report = watcher.poll()
        self.assertEqual((report['ingested'], report['deferred']), (1, 1))
        self.assertEqual(len(self.store.list()), 3)

    def test_preflight_is_bounded_read_only_and_reports_capabilities(self):
        for index in range(8):
            self.write(f'rollout-{index}.json', conversation())
        with self.store.connect() as c:
            before = list(c.iterdump())
        with patch.object(self.store, 'ingest', side_effect=AssertionError('Preview persisted')):
            checked = preview(self.store, self.config)
        self.assertEqual(checked['files'], 8)
        self.assertEqual(checked['checked_files'], 5)
        self.assertEqual(checked['coverage']['total_records'], 5)
        self.assertEqual(checked['coverage']['recorded_actions'], 10)
        self.assertEqual(checked['coverage']['metric_coverage']['recorded_reward']['available'], 5)
        with self.store.connect() as c:
            self.assertEqual(list(c.iterdump()), before)

    def test_jsonl_preview_does_not_advance_cursor_and_reports_partial_tail(self):
        config = {**self.config, 'mode': 'exports', 'pattern': '*.jsonl'}
        path = self.root / 'worker.jsonl'
        path.write_text(json.dumps(generation_document('Q', 'A')) + '\n{', encoding='utf-8')
        with self.store.connect() as c:
            before = list(c.iterdump())
        report = preview(self.store, config)
        self.assertEqual([s['status'] for s in report['samples']], ['valid', 'waiting'])
        self.assertEqual(report['coverage']['total_records'], 1)
        with self.store.connect() as c:
            self.assertEqual(list(c.iterdump()), before)
        watcher = validate(self.store, config)[1]
        self.assertEqual(watcher.poll()['ingested'], 1)
        self.assertEqual(preview(self.store, config)['coverage']['total_records'], 1)
        self.assertEqual(watcher.poll()['ingested'], 0)

    def test_cli_check_and_once_errors_are_actionable(self):
        from tracker.cli import main
        args = ['tracker', '--db', str(self.store.path), 'watch', str(self.root), '--producer', 'p',
                '--mode', 'snapshots', '--experiment', 'x']
        self.write('rollout.json', conversation())
        for flags in (['--check'], ['--once']):
            with patch.object(sys, 'argv', args + flags), contextlib.redirect_stdout(io.StringIO()):
                main()
        self.assertEqual(len(self.store.list()), 1)
        self.write('bad.json', {'invalid': True})
        for flags in (['--check'], ['--once']):
            with patch.object(sys, 'argv', args + flags), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as e:
                    main()
                self.assertEqual(e.exception.code, 1)

    def test_configuration_rejects_ambiguous_defaults(self):
        for extra in ({'metadata': {}}, {'pattern': '../*.json'}, {'snapshot_state': 'auto'},
                      {'max_records': 3}, {'task_root': str(self.root)}):
            with self.subTest(extra=extra), self.assertRaises(InputError):
                self.watcher(**extra)

    def test_source_status_distinguishes_new_content_from_state_only_revision(self):
        envelope = dict(producer='p', rollout_id='sample', revision=0, state='in_progress',
                        document=generation_document('Q', 'A'))
        first = self.store.ingest(envelope)['id']
        self.assertTrue(self.store.source_status(first)['is_latest'])
        envelope.update(revision=1, document=generation_document('Q', 'B'))
        second = self.store.ingest(envelope)['id']
        older = self.store.source_status(first)
        self.assertFalse(older['is_latest'])
        self.assertEqual(older['latest_run_id'], second)
        self.store.ingest({**envelope, 'revision': 2, 'state': 'complete'})
        current = self.store.source_status(second)
        self.assertTrue(current['is_latest'])
        self.assertEqual((current['revision'], current['state']), (2, 'complete'))
        self.assertNotIn('history', current)
        with self.assertRaises(KeyError):
            self.store.source_status('missing')

    def test_preview_byte_budget_does_not_change_collection_limit(self):
        self.write('rollout-a.json', conversation())
        with patch('tracker.connection_check.BYTE_LIMIT', 10):
            checked = preview(self.store, self.config)
        self.assertEqual(checked['samples'][0]['status'], 'limited')
        self.assertIsNone(checked['coverage'])
        self.assertEqual(self.watcher().poll()['ingested'], 1)

    def test_native_preflight_includes_result_sidecar(self):
        from test_tracker import harbor
        self.write('trajectory.json', harbor())
        self.write('result.json', {'finished_at': '2026-10-14T00:00:00Z', 'verifier_result': {'rewards': {'reward': 1}}})
        checked = preview(self.store, dict(root=str(self.root), producer='native'))
        self.assertEqual(checked['coverage']['total_records'], 1)
        self.assertEqual(checked['coverage']['metric_coverage']['recorded_reward']['available'], 1)
        self.assertEqual(self.store.list(), [])


if __name__ == '__main__':
    unittest.main()
