import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tracker.analytics import Analysis
from tracker.analysis_mirror import FeedMirror
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker.store import Store


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'source.sqlite')
        self.a=Analysis(self.store.path);self.path=self.root/'results.sqlite'

    def ingest(self,rid='a',revision=0,state='complete'):
        return self.store.ingest({'producer':'worker','rollout_id':rid,'revision':revision,'state':state,
            'format':'generation','document':generation_document('Q',rid),'metadata':{'experiment':'mirror-test'}})

    def test_bounded_sync_restart_and_lifecycle_history(self):
        self.ingest(state='in_progress');self.ingest('b')
        mirror=FeedMirror(self.a,self.path)
        first=mirror.sync(feeds=['revisions'],limit=1);self.assertTrue(first['has_more'])
        self.assertEqual(first['feeds'][0]['inserted'],1)
        self.ingest(revision=1)
        reopened=FeedMirror(self.a,self.path);page=reopened.sync(feeds=['revisions'],limit=1,pages=10)
        self.assertEqual(page['feeds'][0]['inserted'],2);self.assertFalse(page['has_more'])
        self.assertEqual(reopened.sync(feeds=['revisions'])['feeds'][0]['inserted'],0)
        self.assertEqual(reopened.status()['feeds'][0]['receipts'],3)
        # Two immutable source documents, but three lifecycle receipts.
        reopened.sync(feeds=['sources'])
        self.assertEqual({r['feed']:r['receipts'] for r in reopened.status()['feeds']},{'sources':2,'revisions':3})

    def test_receipts_and_cursor_roll_back_together(self):
        self.ingest();mirror=FeedMirror(self.a,self.path)
        with patch.object(mirror,'_set_cursor',side_effect=RuntimeError('simulated interruption before checkpoint')):
            with self.assertRaises(RuntimeError):mirror.sync(feeds=['revisions'])
        with mirror.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM receipts').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM feed_cursors').fetchone()[0],0)
        self.assertEqual(FeedMirror(self.a,self.path).sync(feeds=['revisions'])['feeds'][0]['inserted'],1)

    def test_existing_databases_and_source_identity_are_protected(self):
        with self.assertRaises(InputError):FeedMirror(self.a,self.store.path)
        other=Store(self.root/'other.sqlite')
        with self.assertRaises(InputError):FeedMirror(self.a,other.path)
        with other.connect() as c:self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='mirror_identity'").fetchone())
        FeedMirror(self.a,self.path)
        with self.assertRaises(InputError):FeedMirror(Analysis(other.path),self.path)

    def test_concurrent_progress_cannot_move_cursor_backwards(self):
        self.ingest();mirror=FeedMirror(self.a,self.path);page=self.a.changes('revisions')
        mirror.sync(feeds=['revisions'])
        with self.assertRaisesRegex(InputError,'Another consumer'):mirror._commit('revisions',page,None)
        self.assertEqual(mirror.status()['feeds'][0]['receipts'],1)

    def test_conflicting_saved_receipt_is_not_silently_overwritten(self):
        self.ingest();mirror=FeedMirror(self.a,self.path);mirror.sync(feeds=['revisions'])
        with mirror.connect() as c:
            c.execute("UPDATE receipts SET sha256='altered'")
            c.execute('DELETE FROM feed_cursors')
        with self.assertRaisesRegex(InputError,'conflicts'):mirror.sync(feeds=['revisions'])
        self.assertEqual(mirror.status()['feeds'],[])
        with mirror.connect() as c:self.assertEqual(c.execute('SELECT sha256 FROM receipts').fetchone()[0],'altered')

    def test_invalid_feed_and_budget_fail_before_consuming(self):
        mirror=FeedMirror(self.a,self.path)
        for kwargs in [{'feeds':[]},{'feeds':['sources','sources']},{'feeds':['unknown']},{'limit':0},{'pages':0}]:
            with self.assertRaises(InputError):mirror.sync(**kwargs)
        self.assertEqual(mirror.status()['feeds'],[])

    def test_cli_sync_and_status_need_no_server(self):
        self.ingest()
        base=[sys.executable,'-m','rilldex','--db',str(self.store.path),'analysis','sync',str(self.path)]
        first=subprocess.run(base+['--feed','revisions'],capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr);self.assertEqual(json.loads(first.stdout)['feeds'][0]['inserted'],1)
        result=subprocess.run(base+['--status'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['feeds'][0]['receipts'],1)

    def test_status_typo_does_not_create_an_empty_result_mirror(self):
        result=subprocess.run([sys.executable,'-m','rilldex','--db',str(self.store.path),'analysis','sync',str(self.path),'--status'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('does not exist',result.stderr)
        self.assertFalse(self.path.exists())


if __name__=='__main__':unittest.main()
