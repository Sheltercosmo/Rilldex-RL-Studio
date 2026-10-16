import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker.capture import Outbox
from tracker.connections import create, validate
from tracker.export_watch import ExportWatcher
from tracker.portable import Episode, chat_document, generation_document
from tracker.schema import InputError
from tracker.store import Store
from test_tracker import harbor


class ExportWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'exports with spaces'
        self.root.mkdir()
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')
        self.path = self.root / 'worker-0.jsonl'
        self.meta = {'experiment': 'portable-test'}

    def watcher(self, store=None, **kwargs):
        return ExportWatcher(store or self.store, self.root, producer='run/worker-0', metadata=self.meta, **kwargs)

    def append(self, doc, end='\n'):
        with self.path.open('ab') as f:
            f.write((json.dumps(doc, ensure_ascii=False) + end).encode())

    def rows(self):
        episode = Episode(goal='Reach the exit')
        episode.reset({'position': 0})
        episode.step(1, {'position': 1}, reward=1, done=True)
        return [
            {'input': 'Question', 'output': 'Answer', 'step': 7, 'score': 0},
            generation_document('Q', 'A', reward=1),
            chat_document([{'role':'user','content':'Check status'},
                           {'role':'assistant','content':None,'tool_calls':[{'id':'call-1','type':'function','function':{'name':'status','arguments':'{}'}}]},
                           {'role':'tool','tool_call_id':'call-1','content':'ready'},
                           {'role':'assistant','content':'Ready'}], reward=.5),
            episode.snapshot(), harbor(),
        ]

    def test_before_mid_after_restart_match_batch_and_preserve_graphs_metrics(self):
        live = self.watcher()
        self.assertEqual(live.poll()['scanned'], 0)
        for row in self.rows():
            self.append(row)
            self.assertEqual(live.poll()['ingested'], 1)
        ids = {r['id'] for r in self.store.list()}
        self.assertEqual(len(ids), 5)
        self.assertEqual(self.watcher().poll()['ingested'], 0)
        offline = Store(Path(self.tmp.name) / 'offline.sqlite')
        self.assertEqual(self.watcher(offline).poll()['ingested'], 5)
        self.assertEqual(ids, {r['id'] for r in offline.list()})
        for rid in ids:
            a, b = self.store.get(rid, raw=True), offline.get(rid, raw=True)
            self.assertEqual(a['run'], b['run'])
            self.assertEqual(a['analysis'], b['analysis'])
            from tracker.integrations import inspect
            from tracker.rollout_metrics import source_record
            self.assertEqual(inspect(a['run']), inspect(b['run']))
            self.assertEqual(source_record(a['run']), source_record(b['run']))
            with self.store.connect() as c, offline.connect() as d:
                self.assertEqual(c.execute('SELECT document FROM rollout_graphs WHERE run_id=?', (rid,)).fetchall(),
                                 d.execute('SELECT document FROM rollout_graphs WHERE run_id=?', (rid,)).fetchall())

    def test_partial_tail_utf8_bom_crlf_and_identical_samples_are_not_lost(self):
        row = generation_document('问题', 'réponse')
        raw = json.dumps(row, ensure_ascii=False).encode()
        self.path.write_bytes(b'\xef\xbb\xbf' + raw + b'\r\n\r\n' + raw[:-2])
        w = self.watcher()
        first = w.poll()
        self.assertEqual((first['ingested'], first['waiting']), (1, 1))
        with self.path.open('ab') as f:
            f.write(raw[-2:] + b'\r\n')
        self.assertEqual(w.poll()['ingested'], 1)
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(sorted(r['metadata']['source_line'] for r in self.store.list()), [1, 3])

    def test_acknowledged_row_replays_after_cursor_commit_crash(self):
        self.append(self.rows()[0])
        w = self.watcher()
        with patch.object(w, '_advance', side_effect=OSError('simulated disk failure')):
            self.assertEqual(w.poll()['deferred'], 1)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.watcher().poll()['ingested'], 0)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM rollout_revisions').fetchone()[0], 1)

    def test_invalid_line_stops_only_its_file_and_retry_resumes(self):
        good = self.rows()[0]
        self.append(good)
        valid = self.path.read_bytes()
        with self.path.open('ab') as f:
            f.write(b'{invalid}\n')
        (self.root / 'worker-1.jsonl').write_text(json.dumps(good) + '\n', encoding='utf-8')
        report = self.watcher().poll()
        self.assertEqual((report['ingested'], report['deferred']), (2, 1))
        self.assertIn('Line 2', report['entries'][1]['error'])
        self.path.write_bytes(valid + json.dumps(good).encode() + b'\n')
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        self.assertEqual(len(self.store.list()), 3)

    def test_truncation_and_accepted_rewrite_are_visible_without_erasing_history(self):
        self.append(self.rows()[0])
        w = self.watcher()
        w.poll()
        before = self.path.read_bytes()
        self.path.write_bytes(before.replace(b'Answer', b'Change'))
        self.assertIn('bytes changed', w.poll()['entries'][0]['error'])
        self.path.write_bytes(b'')
        self.assertIn('truncated', w.poll()['entries'][0]['error'])
        self.assertEqual(len(self.store.list()), 1)
        self.path.write_bytes(before)
        self.assertEqual(w.poll()['deferred'], 0)

    def test_budget_drains_in_pages_and_changed_defaults_do_not_duplicate(self):
        for row in self.rows():
            self.append(row)
        w = self.watcher(max_records=2)
        self.assertEqual(w.poll()['backlog'], 1)
        self.assertEqual(w.poll()['backlog'], 1)
        self.assertEqual(w.poll()['ingested'], 1)
        self.meta['split'] = 'eval'
        report = self.watcher().poll()
        self.assertIn('settings changed', report['entries'][0]['error'])
        self.assertEqual(len(self.store.list()), 5)

    def test_envelopes_keep_http_outbox_identity_and_state_only_revisions(self):
        outbox = Outbox(Path(self.tmp.name) / 'outbox.sqlite', producer='run/worker-0')
        doc = generation_document('Q', 'A')
        outbox.log('sample-1', doc, state='in_progress', metadata=self.meta)
        with outbox.connect() as c:
            envelope = json.loads(c.execute('SELECT payload FROM queue').fetchone()[0])
        self.append(envelope)
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        def send(request, **kwargs):
            return io.BytesIO(json.dumps(self.store.ingest(json.loads(request.data))).encode())
        with patch('tracker.capture.urlopen', side_effect=send):
            self.assertEqual(outbox.drain()['sent'], 1)
        self.append({**envelope, 'revision': 1, 'state': 'complete'})
        self.assertEqual(self.watcher().poll()['ingested'], 1)
        rows = self.store.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ingestion']['state'], 'complete')
        self.assertEqual(len(self.store.get(rows[0]['id'])['ingestion']['history']), 2)

    def test_invalid_scope_or_format_fails_before_connection_is_saved(self):
        config = {'root':str(self.root),'producer':'p','mode':'exports','metadata':self.meta}
        connection = create(self.store, config)
        self.assertFalse(create(self.store, config)['created'])
        self.assertTrue(connection['created'])
        for extra in ({'metadata':{}}, {'pattern':'../*.jsonl'}, {'format':'made-up'}, {'max_records':True}):
            with self.subTest(extra=extra), self.assertRaises(InputError):
                validate(self.store, {**config, **extra})

    def test_unchanged_files_do_not_reparse_or_reingest(self):
        self.append(self.rows()[0])
        w = self.watcher()
        w.poll()
        with patch.object(self.store, 'ingest', side_effect=AssertionError('No recalculate')):
            self.assertEqual(w.poll()['ingested'], 0)

    def test_out_of_order_files_resume_after_prior_revision_arrives(self):
        packet = {'rollout_id':'shared','revision':1,'state':'complete',
                  'document':generation_document('Q','A')}
        self.append(packet)
        w = self.watcher()
        report = w.poll()
        self.assertEqual(report['deferred'], 1)
        self.assertIn('Expected revision 0', report['entries'][0]['error'])
        self.assertEqual(self.store.list(), [])
        (self.root / 'worker-1.jsonl').write_text(json.dumps({**packet,'revision':0,'state':'in_progress'})+'\n', encoding='utf-8')
        self.assertEqual(w.poll()['ingested'], 1)
        self.assertEqual(w.poll()['ingested'], 1)
        self.assertEqual(self.store.list()[0]['ingestion']['state'], 'complete')


if __name__ == '__main__':
    unittest.main()
