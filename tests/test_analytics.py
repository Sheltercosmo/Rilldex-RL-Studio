import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tracker.analytics import Analysis, VIEWS, EXPORT_PROFILES
from tracker.store import Store
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker import monitoring, graph_store


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'db.sqlite');self.a=Analysis(self.store.path)

    def ingest(self, rollout='a', revision=0, state='complete', experiment='test', reward=None):
        return self.store.ingest({'producer':'worker','rollout_id':rollout,'revision':revision,'state':state,
            'format':'generation','metadata':{'experiment':experiment,'generation_step':3},
            'document':generation_document('Question',f'Answer {rollout}/{revision}',reward=reward)})['id']

    def test_missing_database_does_not_create_or_migrate(self):
        path=self.root/'missing.sqlite'
        with self.assertRaises(InputError):Analysis(path)
        self.assertFalse(path.exists())
        with self.store.connect() as c:before=c.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
        self.assertEqual(len(self.a.catalog()['tables']),len(VIEWS))
        with self.store.connect() as c:after=c.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
        self.assertEqual(before,after)

    def test_latest_scope_and_missingness_preserve_grain(self):
        old=self.ingest(state='in_progress');new=self.ingest(revision=1,reward=0);self.ingest('b',experiment='other')
        self.assertEqual([r['run_id'] for r in self.a.table('rollouts',experiment='test')['rows']],[new])
        self.assertEqual(len(self.a.table('rollouts',experiment='test',history=True)['rows']),2)
        r=self.a.table('rollouts',experiment='test')['rows'][0]
        self.assertIsNone(r['training_step']);self.assertEqual(r['generation_step'],3)
        self.assertIsNone(r['verified_success'])
        metrics={r['metric']:r for r in self.a.table('measurements',experiment='test',observer='source')['rows']}
        self.assertEqual(metrics['recorded_reward']['value'],0)
        self.assertIsNone(metrics['recorded_success']['value']);self.assertTrue(metrics['recorded_success']['reason'])
        self.assertTrue(all(r['run_id']!=old for r in self.a.table('nodes')['rows']))

    def test_read_only_sql_parameterization_and_column_collision(self):
        self.ingest()
        for sql in ['DELETE FROM runs','DROP TABLE runs','PRAGMA query_only=OFF',"ATTACH DATABASE ':memory:' AS x",'BEGIN','CREATE TEMP TABLE x(a)',"SELECT load_extension('x')"]:
            with self.assertRaises(InputError,msg=sql):self.a.query(sql)
        with self.assertRaises(InputError):self.a.query('SELECT 1 x,2 x')
        with self.assertRaises(InputError):self.a.query('SELECT 1; SELECT 2')
        result=self.a.query('WITH scoped AS (SELECT * FROM rl_rollouts WHERE experiment=:e) SELECT count(*) n FROM scoped',{'e':'test'})
        self.assertEqual(result['rows'],[{'n':1}]);self.assertFalse(result['truncated'])
        self.assertEqual(self.a.query('SELECT * FROM rl_rollouts WHERE experiment=?',["test' OR 1=1 --"])['rows'],[])

    def test_consistent_snapshot_during_concurrent_capture(self):
        first=self.ingest(state='in_progress')
        with self.a.snapshot() as s:
            before=s.table('rollouts');self.ingest(revision=1)
            self.assertEqual(s.table('rollouts'),before)
            self.assertEqual([r['run_id'] for r in s.table('graphs')['rows']],[first])
        self.assertNotEqual(self.a.table('rollouts')['rows'][0]['run_id'],first)

    def test_independent_resumable_feeds_no_skip_on_new_sources(self):
        first=self.ingest();self.ingest('b')
        page=self.a.changes(limit=1);self.assertEqual(page['rows'][0]['id'],first);self.assertTrue(page['has_more'])
        cursor=page['next_cursor'];self.ingest('c')
        page=self.a.changes(cursor=cursor,limit=5);self.assertEqual(len(page['rows']),2)
        self.assertEqual(Analysis(self.store.path).changes(cursor=page['next_cursor'])['rows'],[])
        with self.assertRaises(InputError):self.a.changes('graphs',cursor=cursor)
        with self.assertRaises(InputError):self.a.changes(cursor={**cursor,'anchor':'wrong-workspace'})
        self.assertEqual(self.a.changes('monitor_values')['rows'],[])
        monitoring.create(self.store,{'name':'Reward','kind':'metric','observer':'source','metric':'recorded_reward'})
        monitoring.sync(self.store)
        self.assertEqual(len(self.a.changes('monitor_values')['rows']),3)
        self.assertEqual(self.a.changes(cursor=page['next_cursor'])['rows'],[])

    def test_graph_relations_export_with_exact_endpoint_identity(self):
        rid=self.ingest();run=self.store.get(rid,raw=True)['run']
        graph=graph_store.build(run)
        with self.store.connect() as c:graph_store.save(c,graph)
        result=self.a.query('''SELECT e.graph_id,e.type,n.node_id source_node,t.node_id target_node
          FROM rl_edges e JOIN rl_nodes n ON n.graph_id=e.graph_id AND n.node_id=e.source
          JOIN rl_nodes t ON t.graph_id=e.graph_id AND t.node_id=e.target''')
        self.assertEqual(len(result['rows']),len(graph['edges']))
        for row in result['rows']:self.assertEqual(row['graph_id'],graph['id'])

    def test_lifecycle_only_revision_is_a_receipt_even_when_source_is_unchanged(self):
        payload={'producer':'worker','rollout_id':'same','revision':0,'state':'in_progress','format':'generation',
                 'metadata':{'experiment':'test'},'document':generation_document('Q','A')}
        rid=self.store.ingest(payload)['id'];before=self.a.changes('revisions')
        result=self.store.ingest({**payload,'revision':1,'state':'complete'})
        self.assertEqual(result['id'],rid)
        self.assertEqual(len(self.a.changes('sources')['rows']),1)
        after=self.a.changes('revisions',cursor=before['next_cursor'])
        self.assertEqual([r['document']['state'] for r in after['rows']],['complete'])

    def test_feed_byte_boundary_does_not_advance_over_unreturned_rows(self):
        self.ingest();self.ingest('b')
        from unittest.mock import patch
        with self.store.connect() as c:size=len(c.execute('SELECT document FROM runs ORDER BY rowid LIMIT 1').fetchone()[0].encode())
        with patch('tracker.analytics.FEED_MAX_BYTES',size+1):
            first=self.a.changes();self.assertEqual(len(first['rows']),1);self.assertTrue(first['has_more'])
            second=self.a.changes(cursor=first['next_cursor']);self.assertEqual(len(second['rows']),1)
            self.assertNotEqual(first['rows'][0]['id'],second['rows'][0]['id'])

    def test_both_trainer_identity_schemas_remain_distinct(self):
        # Storage fixtures isolate export identity behavior from trainer validation.
        with self.store.connect() as c:
            c.execute('INSERT INTO training_records VALUES (?,?,?,?,?,?,?,?,?)',('worker','test','r',0,'sample','worker','episode','{}','2026-10-14'))
            c.execute('INSERT INTO training_sample_records VALUES (?,?,?,?,?,?,?,?,?)',('worker','test','r',0,'sample','worker','sample','{}','2026-10-14'))
        rows=self.a.table('training_records',experiment='test')['rows']
        self.assertEqual({r['record_schema'] for r in rows},{'training-records/1','training-records/2'})
        newer=next(r for r in rows if r['record_schema']=='training-records/2')
        self.assertIsNone(newer['rollout_id']);self.assertEqual(newer['sample_id'],'sample')
        self.assertEqual(len(self.a.changes('training_samples')['rows']),1)

    def test_manifest_checksums_scope_and_no_overwrite_or_partial_archive(self):
        self.ingest();self.ingest('b',experiment='other')
        dest=self.root/'tables.zip';manifest=self.a.export(dest,experiment='test')
        self.assertEqual(manifest['tables']['rollouts']['rows'],1)
        with zipfile.ZipFile(dest) as z:
            self.assertEqual(json.loads(z.read('manifest.json'))['scope'],{'experiment':'test','history':False})
            for info in manifest['tables'].values():self.assertEqual(hashlib.sha256(z.read(info['file'])).hexdigest(),info['sha256'])
        with self.assertRaises(InputError):self.a.export(dest)
        too_small=self.root/'too-small.zip'
        with self.assertRaises(InputError):self.a.export(too_small,max_rows=1)
        self.assertFalse(too_small.exists())
        with self.assertRaises(InputError):self.a.export(too_small,max_bytes=100)
        self.assertFalse(too_small.exists())

    def test_csv_nulls_and_json_details(self):
        self.ingest()
        import csv,io
        dest=self.root/'csv.zip';self.a.export(dest,tables=['measurements'],format='csv')
        with zipfile.ZipFile(dest) as z:rows=list(csv.DictReader(io.StringIO(z.read('measurements.csv').decode())))
        r=next(r for r in rows if r['metric']=='recorded_reward')
        self.assertEqual(r['value'],'');self.assertEqual(r['status'],'unavailable')
        self.assertIsNone(json.loads(r['details_json'])['value'])

    def test_observer_options_and_export_scope_keep_source_context(self):
        self.ingest();self.ingest('b',experiment='other')
        monitoring.create(self.store,{'name':'Reward','kind':'metric','observer':'source','metric':'recorded_reward'})
        monitoring.create(self.store,{'name':'Review','kind':'metric','observer':'authored-review','metric':'recorded_reward'})
        monitoring.sync(self.store)
        monitoring.create(self.store,{'name':'Unused','kind':'metric','observer':'source','metric':'actions'})
        options=self.a.options(experiment='test')
        self.assertEqual({r['experiment']:r['snapshots'] for r in options['experiments']},{'other':1,'test':1})
        self.assertEqual({r['observer']:r['snapshots'] for r in options['observers']},{'authored-review':1,'source':1})
        self.assertEqual(next(r['label'] for r in options['observers'] if r['observer']=='source'),'Recorded source')
        values=self.a.table('monitor_values',experiment='test',observer='source')['rows']
        self.assertEqual([r['monitor_name'] for r in values],['Reward'])
        definitions=self.a.table('monitor_definitions',experiment='test',observer='source')['rows']
        self.assertEqual([r['monitor_name'] for r in definitions],['Reward'])
        path=self.root/'scoped.zip'
        manifest=self.a.export(path,tables=EXPORT_PROFILES['measurements'],experiment='test',observer='source')
        self.assertEqual(manifest['scope']['observer'],'source')
        self.assertEqual(manifest['context_tables'],['rollouts','revisions'])
        self.assertEqual(manifest['tables']['rollouts']['rows'],1)
        self.assertEqual(manifest['tables']['monitor_definitions']['rows'],1)
        with zipfile.ZipFile(path) as z:
            for table in manifest['observer_filtered_tables']:
                for line in z.read(table+'.jsonl').splitlines():self.assertEqual(json.loads(line)['observer'],'source')

    def test_empty_and_unknown_scope_do_not_broaden(self):
        self.assertEqual(self.a.options()['experiments'],[])
        self.ingest()
        self.assertEqual(self.a.options(experiment='unknown')['observers'],[])
        self.assertEqual(self.a.table('measurements',observer='unknown')['rows'],[])

    def test_cli_and_notebook_have_same_read_contract(self):
        self.ingest()
        result=subprocess.run([sys.executable,'-m','rilldex','--db',str(self.store.path),'analysis','table','rollouts'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['rows'],self.a.table('rollouts')['rows'])
        from tracker.notebook import NotebookWorkspace
        ws=NotebookWorkspace(self.store.path)
        self.assertEqual(ws.analysis.table('rollouts')['rows'],self.a.table('rollouts')['rows'])
        self.assertFalse(ws.status()['running'])

    def test_staged_shards_and_continuous_append_produce_same_analysis(self):
        from tracker.export_watch import ExportWatcher
        root=self.root/'shards';root.mkdir()
        def watcher(store):return ExportWatcher(store,root,producer='stages',metadata={'experiment':'staged'})
        doc=lambda i:json.dumps(generation_document('Q',f'A{i}',reward=i))+'\n'
        first=root/'step-1.jsonl';first.write_text(doc(1),encoding='utf-8')
        self.assertEqual(watcher(self.store).poll()['ingested'],1)
        cursor=self.a.changes('revisions')['next_cursor']
        (root/'step-2.jsonl').write_text(doc(2),encoding='utf-8')
        self.assertEqual(watcher(self.store).poll()['ingested'],1)
        with first.open('a',encoding='utf-8') as f:f.write(doc(3))
        self.assertEqual(watcher(self.store).poll()['ingested'],1)
        self.assertEqual(len(self.a.changes('revisions',cursor=cursor)['rows']),2)
        batch=Store(self.root/'batch.sqlite');self.assertEqual(watcher(batch).poll()['ingested'],3)
        self.assertEqual(watcher(self.store).poll()['ingested'],0)
        query='SELECT run_id,metric,value,status,details_json FROM rl_measurements ORDER BY run_id,metric'
        self.assertEqual(self.a.query(query)['rows'],Analysis(batch.path).query(query)['rows'])


if __name__=='__main__':unittest.main()
