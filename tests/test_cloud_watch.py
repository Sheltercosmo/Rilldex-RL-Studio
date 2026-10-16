import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker.cloud_watch import CloudWatcher, source
from tracker.connections import validate, preview
from tracker.store import Store
from tracker.schema import InputError


class ObjectStore:
    """Authored storage protocol control, not proof of a real provider deployment."""
    def __init__(self):
        self.objects, self.versions = {}, {}
        self.offline = False
        self.break_read = False
    def put(self, key, data):
        self.objects[key] = data
        self.versions[key] = self.versions.get(key, 0) + 1
    def invalidate_cache(self, path): pass
    def info(self, key):
        return dict(type='file', size=len(self.objects[key]), ETag=str(self.versions[key]))
    def find(self, prefix, detail=True):
        if self.offline: raise OSError('example secret URL must not escape')
        return {k: self.info(k) for k in self.objects if k.startswith(prefix + '/')}
    def open(self, key, mode):
        if self.break_read: raise OSError('interrupted download')
        return io.BytesIO(self.objects[key])


class CloudWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')
        self.fs = ObjectStore()
        self.config = dict(root='s3://bucket/job', mode='exports', producer='job/w0', metadata={'experiment': 'job'})
        self.patch = patch('tracker.cloud_watch.filesystem', return_value=self.fs)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.raw = json.dumps({'input': 'Q', 'output': 'A', 'step': 4, 'score': 1}).encode() + b'\n'
    def watcher(self): return validate(self.store, self.config)[1]

    def test_existing_future_partial_stop_restart_outage_and_batch_agree(self):
        watcher = self.watcher()
        self.assertEqual(watcher.poll()['ingested'], 0)
        self.fs.put('bucket/job/worker.jsonl', self.raw)
        self.assertEqual(watcher.poll()['ingested'], 1)
        self.fs.put('bucket/job/worker.jsonl', self.raw + self.raw[:-1])
        report = watcher.poll()
        self.assertEqual((report['ingested'], report['waiting']), (0, 1))
        self.fs.offline = True
        failed = self.watcher().poll()
        self.assertEqual(failed['cloud']['state'], 'cached_only')
        self.assertEqual(failed['deferred'], 1)
        self.assertIn('Cloud listing failed', failed['entries'][-1]['error'])
        self.assertNotIn('secret', json.dumps(failed))
        self.assertEqual(len(self.store.list()), 1)
        self.fs.offline = False
        self.fs.put('bucket/job/worker.jsonl', self.raw * 2)
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        self.assertEqual(self.watcher().poll()['cloud']['unchanged'], 1)
        ids = {r['id'] for r in self.store.list()}
        batch = Store(Path(self.tmp.name) / 'batch' / 'db.sqlite')
        self.assertEqual(validate(batch, self.config)[1].poll()['ingested'], 2)
        self.assertEqual(ids, {r['id'] for r in batch.list()})

    def test_failed_download_retains_cache_and_remote_deletion_does_not_delete_evidence(self):
        w = self.watcher()
        self.fs.put('bucket/job/x.jsonl', self.raw)
        w.poll()
        self.fs.put('bucket/job/x.jsonl', self.raw * 2)
        self.fs.break_read = True
        self.assertEqual(w.poll()['deferred'], 1)
        self.assertEqual((w.root / 'x.jsonl').read_bytes(), self.raw)
        self.fs.break_read = False
        self.assertEqual(w.poll()['ingested'], 1)
        self.fs.objects.clear()
        self.assertEqual(w.poll()['ingested'], 0)
        self.assertEqual(len(self.store.list()), 2)

    def test_preview_downloads_temporary_data_without_ingestion_or_cursor_changes(self):
        self.fs.put('bucket/job/x.jsonl', self.raw)
        with self.store.connect() as c: before = list(c.iterdump())
        result = preview(self.store, self.config)
        self.assertEqual(result['coverage']['total_records'], 1)
        self.assertEqual(result['config']['root'], self.config['root'])
        with self.store.connect() as c: self.assertEqual(before, list(c.iterdump()))
        self.assertFalse((Path(self.tmp.name) / 'cloud-cache').exists())

    def test_preview_budget_and_changed_accepted_prefix_are_not_silently_ingested(self):
        self.fs.put('bucket/job/x.jsonl', self.raw)
        w = self.watcher()
        self.assertEqual(w.mirror(byte_budget=1)['errors'][0]['status'], 'deferred')
        self.assertEqual(w.poll()['ingested'], 1)
        self.fs.put('bucket/job/x.jsonl', self.raw.replace(b'"A"', b'"B"'))
        self.assertEqual(w.poll()['deferred'], 1)
        self.assertEqual(len(self.store.list()), 1)

    def test_portable_paths_credentials_and_case_collisions_rejected(self):
        for url in ('https://example/a', 's3://key:secret@bucket/job', 's3://bucket/a?token=x', 'gs://bucket/../a'):
            with self.subTest(url=url), self.assertRaises(InputError): source(url)
        self.fs.put('bucket/job/../escape.jsonl', self.raw)
        self.assertEqual(self.watcher().poll()['deferred'], 1)
        self.fs.objects.clear()
        self.fs.put('bucket/job/A.jsonl', self.raw)
        self.fs.put('bucket/job/a.jsonl', self.raw)
        with self.assertRaisesRegex(InputError, 'case'): self.watcher().mirror()
        self.assertEqual(self.watcher().poll()['cloud']['state'], 'cached_only')
        self.assertEqual(len(self.store.list()), 0)

    def test_cached_backlog_drains_during_outage_and_survives_restart(self):
        self.config['max_records'] = 1
        self.fs.put('bucket/job/a.jsonl', self.raw * 3)
        w = self.watcher()
        self.assertEqual(w.poll()['ingested'], 1)
        self.fs.offline = True
        report = w.poll()
        self.assertEqual((report['ingested'], report['backlog'], report['deferred']), (1, 1, 1))
        self.assertEqual(report['cloud']['state'], 'cached_only')
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        self.fs.offline = False
        report = self.watcher().poll()
        self.assertEqual((report['ingested'], report['deferred'], report['cloud']['state']), (0, 0, 'current'))
        self.assertEqual(len(self.store.list()), 3)

    def test_client_setup_errors_are_sanitized(self):
        self.patch.stop()  # This test exercises the actual client factory.
        from types import SimpleNamespace
        import sys
        from tracker.cloud_watch import filesystem
        def invalid(*args, **kwargs): raise ValueError('private-signed-url-control')
        with patch.dict(sys.modules, {'fsspec': SimpleNamespace(filesystem=invalid)}):
            with self.assertRaisesRegex(InputError, 'Cloud client setup failed') as caught:
                filesystem('s3://bucket/job')
        self.assertNotIn('private-signed-url', str(caught.exception))

    def test_one_off_drains_cache_but_does_not_claim_cloud_replay_complete(self):
        import sys
        from contextlib import redirect_stdout, redirect_stderr
        from tracker.cli import main
        self.config['max_records'] = 1
        self.fs.put('bucket/job/a.jsonl', self.raw * 3)
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        self.fs.offline = True
        args = ['rilldex', '--db', str(self.store.path), 'watch', self.config['root'],
                '--producer', self.config['producer'], '--mode', 'exports', '--experiment', 'job',
                '--max-records', '1', '--once']
        with patch.object(sys, 'argv', args), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as caught: main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('Replay incomplete', errors.getvalue())
        self.assertEqual(len(self.store.list()), 3)
        with self.assertRaisesRegex(InputError, 'Cloud listing failed'):
            preview(self.store, self.config)

    def test_snapshot_one_off_run_uses_cloud_mirror(self):
        self.config.update(mode='snapshots', snapshot_state='complete')
        self.fs.put('bucket/job/one.json', self.raw.rstrip())
        w = self.watcher()
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()): result = w.run(once=True)
        self.assertEqual(result['ingested'], 1)
        self.assertEqual(self.store.list()[0]['ingestion']['state'], 'complete')

    def test_unversioned_objects_do_not_starve_later_files(self):
        for key in ('a', 'b', 'c'):
            self.fs.put('bucket/job/' + key + '.jsonl', self.raw)
        with patch.object(self.fs, 'info', side_effect=lambda k: dict(type='file', size=len(self.fs.objects[k]))):
            for _ in range(3):
                self.watcher().mirror(limit=1)
        self.assertEqual(len(list(self.watcher().root.glob('*.jsonl'))), 3)

    def test_remote_change_during_download_keeps_previous_copy(self):
        self.fs.put('bucket/job/a.jsonl', self.raw)
        w = self.watcher()
        w.poll()
        self.fs.put('bucket/job/a.jsonl', self.raw * 2)
        def changing_open(key, mode):
            stream = io.BytesIO(self.fs.objects[key])
            self.fs.put(key, self.raw * 3)
            return stream
        with patch.object(self.fs, 'open', side_effect=changing_open):
            self.assertEqual(w.poll()['deferred'], 1)
        self.assertEqual((w.root / 'a.jsonl').read_bytes(), self.raw)
        self.assertEqual(w.poll()['ingested'], 2)


if __name__ == '__main__': unittest.main()
