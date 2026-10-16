import copy
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, contextmanager, closing
from pathlib import Path
from unittest.mock import patch

from tracker import observer_archive, semantic_catalog, workspace_snapshot
from tracker.cli import main
from tracker.connections import create, definitions, relocate, set_enabled, validate
from tracker.graph_store import catalog as graphs, read as graph
from tracker.portable import generation_document
from tracker.schema import InputError, digest
from tracker.semantic_extraction import Pipeline
from tracker.store import Store
from tests.test_plan_relations import Provider, fixture, transport


class ConcurrentSnapshotTests(unittest.TestCase):
    def test_snapshot_is_pinned_while_collector_writes_between_backup_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root/'live.sqlite');archive=root/'snapshot.zip'
            with store.connect() as c:
                c.execute('CREATE TABLE snapshot_probe(counter INTEGER,padding BLOB)')
                c.execute('INSERT INTO snapshot_probe VALUES (0,zeroblob(2000000))')
            real_connect=store.connect;written=[]
            @contextmanager
            def instrumented():
                with real_connect() as connection:
                    class BackupConnection:
                        def execute(self,*args):return connection.execute(*args)
                        def backup(self,target,*,pages,progress,sleep):
                            def on_chunk(status,remaining,total):
                                if remaining and not written:
                                    with real_connect() as writer:
                                        writer.execute('UPDATE snapshot_probe SET counter=counter+1')
                                    written.append(True)
                                progress(status,remaining,total)
                            connection.backup(target,pages=pages,progress=on_chunk,sleep=sleep)
                    yield BackupConnection()
            with patch.object(store,'connect',instrumented):workspace_snapshot.export(store,archive)
            self.assertEqual(written,[True],'collector must remain writable during the backup')
            with zipfile.ZipFile(archive) as z:z.extract('workspace.sqlite',root/'saved')
            with closing(sqlite3.connect(root/'saved/workspace.sqlite')) as c:
                self.assertEqual(c.execute('SELECT counter FROM snapshot_probe').fetchone()[0],0)
            with store.connect() as c:
                self.assertEqual(c.execute('SELECT counter FROM snapshot_probe').fetchone()[0],1)


class WorkspaceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root/'live.sqlite')
        self.archive = self.root/'workspace.rilldex.zip'
        self.target = self.root/'relocated'/'workspace.sqlite'
        self.run = fixture()
        self.store.add([self.run])

    def observer(self):
        work = self.root/'review-workspace'
        Pipeline(work,Provider(work/'candidates'),transport).run(self.run)
        return semantic_catalog.register(self.store,work,self.run['id'],'Test plan observer')['observer']

    def export(self):
        with patch('tracker.jev.JevClient.evaluate',side_effect=AssertionError('Snapshot must not infer')):
            return workspace_snapshot.export(self.store,self.archive)

    def test_preserves_graphs_and_source_with_no_dependency_on_original_workspace(self):
        observer = self.observer()
        original = semantic_catalog.load(self.run,observer,self.store)
        manifest = self.export()
        self.assertEqual(manifest['observers']['archived'],1)
        self.assertEqual(manifest['observers']['unavailable'],[])
        self.assertEqual(workspace_snapshot.inspect(self.archive),manifest)
        workspace_snapshot.restore(self.archive,self.target)
        restored = Store(self.target)
        with patch.object(semantic_catalog,'load_extraction',side_effect=AssertionError('No external workspace')):
            loaded = semantic_catalog.load(self.run,observer,restored)
            self.assertEqual(loaded['document'],original['document'])
            self.assertEqual(loaded['export_digest'],original['export_digest'])
            self.assertIn('Preserved',loaded['archive']['audit'])
            row = next(r for r in semantic_catalog.catalog(restored)['maps'] if r['observer']==observer)
            self.assertEqual(row['storage'],'archived')
        self.assertEqual(observer_archive.rows(self.store),[])
        for item in graphs(self.store)['graphs']:
            self.assertEqual(graph(self.store,item['id']),graph(restored,item['id']))

    def test_legacy_profile_is_archived_without_becoming_a_registered_observer(self):
        work = self.root/'legacy'
        Pipeline(work,Provider(work/'candidates'),transport).run(self.run)
        profile = {'kind':'extraction','directory':work,'label':'Legacy plan'}
        with patch.object(semantic_catalog,'PROFILES',{'legacy-test':profile}):
            from tracker.rollout_metrics import record_map
            record_map(self.store,self.run,semantic_catalog.load(self.run,'legacy-test',self.store))
            self.assertEqual(self.export()['observers']['archived'],1)
        workspace_snapshot.restore(self.archive,self.target)
        restored = Store(self.target)
        self.assertEqual(semantic_catalog.load(self.run,'legacy-test',restored)['observer']['label'],'Legacy plan')
        self.assertEqual(len(semantic_catalog.catalog(restored)['maps']),1)

    def test_unavailable_observer_is_reported_and_not_invented(self):
        observer = self.observer()
        with patch.object(semantic_catalog,'load_extraction',return_value={'available':False}):
            manifest = self.export()
        self.assertEqual(manifest['observers']['archived'],0)
        self.assertEqual(manifest['observers']['unavailable'][0]['observer'],observer)
        workspace_snapshot.restore(self.archive,self.target)
        self.assertTrue(graphs(Store(self.target))['graphs'])

    def test_running_capture_and_pending_inference_are_paused_only_in_copy(self):
        output = self.root/'output';output.mkdir()
        create(self.store,{'root':str(output),'producer':'worker'})
        with self.store.connect() as c:
            c.execute("INSERT INTO jobs(run_id,status,created_at) VALUES (?,'queued','test')",(self.run['id'],))
        manifest = self.export()
        self.assertEqual(manifest['paused'],{'connections':1,'inference_jobs':1})
        self.assertTrue(definitions(self.store)[0]['enabled'])
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM jobs').fetchone()[0],'queued')
        workspace_snapshot.restore(self.archive,self.target)
        restored = Store(self.target)
        self.assertFalse(definitions(restored)[0]['enabled'])
        with restored.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM jobs').fetchone()[0],'paused')

    def test_online_backup_includes_committed_wal_records(self):
        # Keep another connection open so committed data can remain in WAL.
        c = sqlite3.connect(self.store.path)
        self.addCleanup(c.close)
        c.execute('PRAGMA journal_mode=WAL')
        self.store.ingest({'producer':'p','rollout_id':'r','revision':0,'state':'complete',
                           'document':generation_document('Q','A')})
        self.export()
        workspace_snapshot.restore(self.archive,self.target)
        self.assertEqual(len(Store(self.target).list()),2)

    def test_existing_destinations_are_never_overwritten(self):
        self.export()
        before = self.archive.read_bytes()
        with self.assertRaises(InputError):self.export()
        self.assertEqual(before,self.archive.read_bytes())
        self.target.parent.mkdir()
        self.target.write_text('valuable existing file')
        with self.assertRaises(InputError):workspace_snapshot.restore(self.archive,self.target)
        self.assertEqual(self.target.read_text(),'valuable existing file')

    def test_corruption_or_extra_archive_members_do_not_publish_database(self):
        self.export()
        with zipfile.ZipFile(self.archive) as z:
            manifest = json.loads(z.read('manifest.json'))
            raw = z.read('workspace.sqlite')
        for i, extra in enumerate((False,True)):
            bad = self.root/f'bad-{i}.zip'
            with zipfile.ZipFile(bad,'w') as z:
                z.writestr('manifest.json',json.dumps(manifest))
                z.writestr('workspace.sqlite',raw if extra else b'x'+raw[1:])
                if extra:z.writestr('../unexpected.txt','bad')
            with self.assertRaises(InputError):workspace_snapshot.restore(bad,self.target)
            self.assertFalse(self.target.exists())
        self.assertFalse((self.root/'unexpected.txt').exists())

    def test_archived_results_remain_bound_to_source_and_contents(self):
        observer = self.observer()
        self.export()
        workspace_snapshot.restore(self.archive,self.target)
        restored = Store(self.target)
        changed = copy.deepcopy(self.run);changed['metadata']['experiment']='changed'
        with self.assertRaisesRegex(InputError,'source or content'):
            semantic_catalog.load(changed,observer,restored)
        with restored.connect() as c:
            c.execute("UPDATE observer_archives SET document='{}'")
        with self.assertRaisesRegex(InputError,'source or content'):
            semantic_catalog.load(self.run,observer,restored)

    def test_relocation_keeps_export_cursors_and_does_not_duplicate_replayed_rows(self):
        output = self.root/'old-output';output.mkdir()
        path = output/'worker.jsonl'
        path.write_text(json.dumps({'input':'Q','output':'A','step':1,'score':1})+'\n',encoding='utf-8')
        config = {'mode':'exports','root':str(output),'producer':'worker','metadata':{'experiment':'move-test'}}
        cid = create(self.store,config)['id']
        _, watcher = validate(self.store,config)
        watcher.poll()
        self.export()
        workspace_snapshot.restore(self.archive,self.target)
        restored = Store(self.target)
        moved = self.root/'new-output';moved.mkdir()
        (moved/'worker.jsonl').write_bytes(path.read_bytes())
        response = relocate(restored,cid,{'root':str(moved)})
        _, follower = validate(restored,response['config'])
        self.assertEqual(follower.poll()['ingested'],0)
        with (moved/'worker.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'input':'Q','output':'B','step':2,'score':0})+'\n')
        self.assertEqual(follower.poll()['ingested'],1)
        self.assertEqual(len(restored.list()),3)  # Original fixture + two exports.
        set_enabled(restored,cid,True)
        with self.assertRaisesRegex(InputError,'Pause'):
            relocate(restored,cid,{'root':str(output)})

    def test_cli_restore_does_not_create_target_before_validation(self):
        self.export()
        with patch('sys.argv',['rilldex','--db',str(self.target),'workspace','restore',str(self.archive)]),redirect_stdout(io.StringIO()) as out:
            main()
        self.assertEqual(json.loads(out.getvalue())['status'],'restored')


if __name__ == '__main__':unittest.main()
