import json
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tracker.research import Analysis, Analyzer, Research, Results
from tracker.schema import InputError
from tracker.store import Store
from tracker.portable import generation_document


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'workspace.sqlite')
        self.data=Analysis(self.store.path)
        self.lab=Research(self.data,self.root/'my results.sqlite')
        self.sql='SELECT run_id,metadata_json FROM rl_rollouts WHERE is_latest=1 ORDER BY run_id'

    def ingest(self, key='one', revision=0, **metadata):
        return self.store.ingest(dict(producer='worker',rollout_id=key,revision=revision,state='complete',
            format='generation',metadata=dict(experiment='test',**metadata),
            document=generation_document('Question',f'Answer {key}/{revision}')))['id']

    def evaluate(self, function=lambda row,c:dict(value=1,reason=None), **kwargs):
        return self.lab.evaluate('my-analysis','v1',self.sql,function,key_columns=['run_id'],**kwargs)

    def test_no_source_write_and_sql_join_to_results(self):
        run=self.ingest()
        with self.store.connect() as c: before=list(c.execute('SELECT * FROM runs'))
        batch=self.evaluate();self.assertEqual(batch['computed'],1)
        self.assertEqual(batch['status'],'complete')
        rows=self.lab.query('''SELECT s.run_id,json_extract(c.output_json,'$.value') value
          FROM custom.research_results c JOIN rl_rollouts s
          ON s.run_id=json_extract(c.input_json,'$.run_id')''')['rows']
        self.assertEqual(rows,[dict(run_id=run,value=1)])
        with self.store.connect() as c:self.assertEqual([tuple(r) for r in before],[tuple(r) for r in c.execute('SELECT * FROM runs')])
        with self.assertRaises(InputError): self.lab.query('DELETE FROM custom.research_results')

    def test_restart_reuses_success_and_new_input_is_computed(self):
        self.ingest();calls=[]
        def fn(row,c):calls.append(row['run_id']);return dict(value=len(calls))
        first=self.evaluate(fn)
        self.lab=Research(self.data,self.lab.path)
        second=self.evaluate(fn);self.assertEqual(second['reused'],1);self.assertEqual(len(calls),1)
        self.ingest('two');third=self.evaluate(fn)
        self.assertEqual((third['computed'],third['reused']),(1,1));self.assertEqual(len(calls),2)
        self.assertEqual(len(self.lab.results(first['id'])['rows']),1)
        self.assertEqual(len(self.lab.results(third['id'])['rows']),2)

    def test_changed_config_version_and_query_input_invalidate_cache(self):
        run=self.ingest();self.evaluate()
        self.assertEqual(self.evaluate(config={'window':3})['computed'],1)
        other=self.lab.evaluate('my-analysis','v2',self.sql,lambda r,c:{'ok':True},key_columns=['run_id'])
        self.assertEqual(other['computed'],1)
        self.ingest(revision=1)
        changed=self.evaluate();self.assertEqual((changed['computed'],changed['reused']),(1,0))
        rows=self.lab.results(changed['id'])['rows'];self.assertNotEqual(json.loads(rows[0]['input_json'])['run_id'],run)

    def test_failure_is_not_cached_and_success_survives(self):
        run=self.ingest();other=self.ingest('two');calls=[]
        def fn(row,c):
            reader=Research(self.data,self.lab.path)
            self.assertEqual(reader.query('SELECT count(*) n FROM custom.research_batches')['rows'],[{'n':1}])
            calls.append(row['run_id'])
            if row['run_id']==run:raise ValueError('temporary failure')
            return {'value':None,'status':'unavailable','reason':'No supported opportunity'}
        batch=self.evaluate(fn);self.assertEqual(batch['status'],'partial');self.assertEqual(batch['failed'],1)
        rows=self.lab.results(batch['id'])['rows'];self.assertEqual({r['status'] for r in rows},{'failed','computed'})
        again=self.evaluate();self.assertEqual((again['computed'],again['reused']),(1,1))
        self.assertEqual(len(calls),2)

    def test_interruption_keeps_commits_and_pending_membership(self):
        self.ingest();self.ingest('two');count=0
        def fn(row,c):
            nonlocal count
            count+=1
            if count==2:raise KeyboardInterrupt()
            return {'ok':True}
        with self.assertRaises(KeyboardInterrupt):self.evaluate(fn)
        batch=self.lab.query('SELECT id,status FROM custom.research_batches')['rows'][0]
        self.assertEqual(batch['status'],'interrupted')
        self.assertEqual({r['status'] for r in self.lab.results(batch['id'])['rows']},{'computed','pending'})
        again=self.evaluate();self.assertEqual((again['computed'],again['reused']),(1,1))

    def test_truncation_duplicate_keys_and_null_keys_rejected_before_callback(self):
        self.ingest();self.ingest('two');calls=[]
        with self.assertRaises(InputError):self.evaluate(lambda r,c:calls.append(r),limit=1)
        for sql in ['SELECT 1 k UNION ALL SELECT 1','SELECT null k','SELECT 1 nope']:
            with self.assertRaises(InputError):self.lab.evaluate('a','1',sql,lambda r,c:calls.append(r),key_columns=['k'])
        self.assertEqual(calls,[])
        self.assertEqual(self.lab.query('SELECT count(*) n FROM custom.research_batches')['rows'],[{'n':0}])

    def test_nonfinite_or_nonobject_output_is_failure_and_tampering_is_rejected(self):
        self.ingest()
        for value in [[],{'x':float('nan')}]:self.assertEqual(self.evaluate(lambda r,c:value)['failed'],1)
        self.evaluate()
        with closing(sqlite3.connect(self.lab.path)) as c:
            with c:c.execute("UPDATE research_results SET output_json='{}'")
        with self.assertRaises(InputError):self.evaluate()

    def test_other_destination_and_source_guards(self):
        with self.assertRaises(InputError):Research(self.data,self.data.path)
        unrelated=self.root/'unrelated.sqlite'
        with closing(sqlite3.connect(unrelated)) as c:
            with c:c.execute('CREATE TABLE unrelated(x)')
        with self.assertRaises(InputError):Research(self.data,unrelated)
        second=Store(self.root/'second.sqlite')
        with self.assertRaises(InputError):Research(second.path,self.lab.path)

    def test_concurrent_evaluator_cannot_duplicate_computation(self):
        self.ingest();other=Research(self.data,self.lab.path)
        def fn(row,c):
            with self.assertRaises(InputError):other.evaluate('a','1',self.sql,lambda r,c:{},key_columns=['run_id'])
            return {'ok':True}
        self.assertEqual(self.evaluate(fn)['computed'],1)

    def test_cache_tracks_late_analysis_without_new_source_snapshot(self):
        run=self.ingest()
        sql='''SELECT r.run_id,(SELECT count(*) FROM rl_graphs g WHERE g.run_id=r.run_id) saved_graphs
            FROM rl_rollouts r WHERE r.is_latest=1'''
        def evaluate():return self.lab.evaluate('coverage','1',sql,lambda r,c:dict(graphs=r['saved_graphs']),key_columns=['run_id'])
        first=evaluate()
        graph=self.data.table('graphs')['rows'][0]['graph_id']
        Analyzer(self.data.path).run('work_state',run,graph_id=graph)
        later=evaluate()
        self.assertEqual((later['computed'],later['reused']),(1,0))
        self.assertNotEqual(self.lab.results(first['id'])['rows'][0]['input_hash'],self.lab.results(later['id'])['rows'][0]['input_hash'])

    def test_new_source_during_callback_does_not_change_batch(self):
        self.ingest()
        def fn(row,c):self.ingest('later');return {'ok':True}
        first=self.evaluate(fn);self.assertEqual(first['selected'],1)
        second=self.evaluate();self.assertEqual((second['selected'],second['computed'],second['reused']),(2,1,1))

    def test_builtin_preflight_execution_cache_and_saved_outputs(self):
        run=self.ingest();analyzer=Analyzer(self.data.path)
        graph=self.data.table('graphs')['rows'][0]['graph_id']
        preflight=analyzer.run('sequence',run,graph_id=graph,check=True)
        self.assertEqual(preflight['new_model_calls'],0)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0],0)
        first=analyzer.run('sequence',run,graph_id=graph)
        second=analyzer.run('sequence',run,graph_id=graph)
        self.assertEqual(first['outputs'],second['outputs']);self.assertEqual(second['execution']['computed'],0)
        self.assertEqual(analyzer.saved(first['id'])['outputs'],first['outputs'])
        self.assertIn(first['id'],[r['plan_id'] for r in analyzer.saved_plans()['rows']])
        dependent=analyzer.run('retry_outcomes',run,graph_id=graph)
        self.assertGreater(len(dependent['manifest']['nodes']),1)
        with self.assertRaises(InputError):analyzer.run('sequence',run)
        other=self.ingest('two')
        with self.assertRaises(InputError):analyzer.run('sequence',other,graph_id=graph)

    def test_portable_database_types_scope_graph_joins_and_optional_source(self):
        self.ingest(generation_step=4);self.ingest('other',revision=0,generation_step=5)
        target=self.root/'frozen.sqlite';manifest=self.data.database(target,observer='source')
        with closing(sqlite3.connect(target)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM rl_rollouts').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT typeof(generation_step) FROM rl_rollouts LIMIT 1').fetchone()[0],'integer')
            self.assertEqual(c.execute('SELECT count(*) FROM rl_sources').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM rl_edges e LEFT JOIN rl_nodes n ON n.graph_id=e.graph_id AND n.node_id=e.source WHERE n.node_id IS NULL').fetchone()[0],0)
        self.assertFalse(manifest['tables']['sources']['included'])
        frozen=Analysis(target);self.assertTrue(frozen.catalog()['frozen'])
        self.assertEqual(frozen.options()['experiments'][0]['snapshots'],2)
        self.assertEqual(frozen.table('rollouts')['rows'],self.data.table('rollouts')['rows'])
        with self.assertRaises(InputError):frozen.changes()
        with self.assertRaises(InputError):Analyzer(target)
        with self.assertRaises(InputError):frozen.database(self.root/'invalid-child.sqlite',include_sources=True)
        with self.assertRaises(InputError):self.data.database(target)
        lab=Research(frozen,self.root/'offline-results.sqlite')
        batch=lab.evaluate('offline','1',self.sql,lambda r,c:{'ok':True},key_columns=['run_id'])
        self.assertEqual(batch['computed'],2)

    def test_dataset_rejects_partial_publication_and_captures_history(self):
        old=self.ingest();self.ingest(revision=1)
        for options in [dict(max_rows=1,history=True),dict(max_bytes=1)]:
            target=self.root/'too-small.sqlite'
            with self.assertRaises(InputError):self.data.database(target,**options)
            self.assertFalse(target.exists())
        target=self.root/'full.sqlite';self.data.database(target,history=True,include_sources=True)
        frozen=Analysis(target)
        self.assertEqual(len(frozen.table('sources',history=True)['rows']),2)
        self.assertIn(old,[r['run_id'] for r in frozen.table('rollouts',history=True)['rows']])

    def test_bundled_research_guides_match_executable_examples(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual((root/'tracker/web/research-example.py').read_bytes(),(root/'examples/custom_monitor_policy.py').read_bytes())
        self.assertEqual((root/'tracker/web/research-guide.md').read_bytes(),(root/'docs/CODE_FIRST_ANALYSIS.md').read_bytes())

    def test_resume_exact_batch_after_source_changes_and_disappears(self):
        self.ingest();self.ingest('two');calls=[]
        def interrupted(row,config):
            calls.append(row)
            if len(calls)==2:raise KeyboardInterrupt()
            return {'config':config,'run_id':row['run_id']}
        with self.assertRaises(KeyboardInterrupt):self.evaluate(interrupted,config={'window':3})
        saved=Results(self.lab.path);batch=saved.batches()['rows'][0]
        original=saved.results(batch['id'])['rows']
        self.ingest(revision=1);self.ingest('new')
        self.store.path.rename(self.root/'moved-workspace.sqlite')
        observed=[]
        def resume(row,config):
            observed.append((row,config));return {'config':config,'run_id':row['run_id']}
        recovered=saved.resume(batch['id'],resume,version='v1')
        self.assertEqual((recovered['id'],recovered['computed'],recovered['reused']),(batch['id'],1,1))
        self.assertEqual(observed,[(json.loads(original[1]['input_json']),{'window':3})])
        self.assertEqual(saved.batch(batch['id'])['captured_at'],batch['captured_at'])
        self.assertEqual(saved.batch(batch['id'])['counts'],dict(pending=0,failed=0,computed=2,reused=0))
        self.assertEqual(len(saved.batches()['rows']),1)
        with self.assertRaises(InputError):saved.resume(batch['id'],resume,version='v2')
        def unexpected(*args):self.fail('Completed batch must not execute callbacks')
        self.assertTrue(saved.resume(batch['id'],unexpected,version='v1')['unchanged'])

    def test_resume_failed_rows_clears_error_and_preserves_success(self):
        self.ingest();self.ingest('two');calls=[]
        def fail_once(row,config):
            calls.append(row)
            if len(calls)==2:raise RuntimeError('temporary')
            return {'ok':True}
        batch=self.evaluate(fail_once)
        self.assertEqual(self.lab.batch(batch['id'])['counts']['failed'],1)
        recovered=self.lab.resume(batch['id'],lambda r,c:{'ok':True},version='v1')
        self.assertEqual((recovered['computed'],recovered['reused'],recovered['failed']),(1,1,0))
        self.assertTrue(all(row['error'] is None for row in self.lab.results(batch['id'])['rows']))
        self.assertEqual(len(self.lab.batches()['rows']),1)

    def test_unchanged_poll_reuses_batch_but_new_population_is_retained(self):
        # Empty selection is also an intentional population, not missing results.
        empty=self.evaluate(skip_unchanged=True)
        self.assertEqual(self.evaluate(skip_unchanged=True)['id'],empty['id'])
        self.ingest();first=self.evaluate(skip_unchanged=True)
        for _ in range(4):
            unchanged=self.evaluate(skip_unchanged=True)
            self.assertEqual(unchanged['id'],first['id'])
            self.assertEqual((unchanged['computed'],unchanged['reused'],unchanged['unchanged']),(0,1,True))
            self.assertEqual(unchanged['captured_at'],first['captured_at'])
        self.assertEqual(len(self.lab.batches()['rows']),2)
        self.ingest('two');changed=self.evaluate(skip_unchanged=True)
        self.assertNotEqual(changed['id'],first['id']);self.assertFalse(changed['unchanged'])
        self.assertEqual((changed['computed'],changed['reused']),(1,1))
        self.assertNotEqual(self.evaluate()['id'],changed['id'])

    def test_unchanged_option_does_not_skip_partial_or_corrupt_results(self):
        self.ingest()
        failed=self.evaluate(lambda r,c:1/0,skip_unchanged=True)
        repaired=self.evaluate(skip_unchanged=True)
        self.assertNotEqual(failed['id'],repaired['id']);self.assertEqual(repaired['computed'],1)
        with closing(sqlite3.connect(self.lab.path)) as c:
            with c:c.execute("UPDATE research_results SET input_json='{}'")
        with self.assertRaises(InputError):self.evaluate(skip_unchanged=True)
        with self.assertRaises(InputError):self.lab.resume(repaired['id'],lambda r,c:{},version='v1')

    def test_corrupt_pending_input_rejected_before_resume_callbacks(self):
        self.ingest();self.ingest('two')
        batch=self.evaluate(lambda r,c:1/0);calls=[]
        with closing(sqlite3.connect(self.lab.path)) as c:
            with c:c.execute("UPDATE research_batch_items SET input_json='{}' WHERE ordinal=1")
        with self.assertRaises(InputError):self.lab.resume(batch['id'],lambda r,c:calls.append(r),version='v1')
        self.assertEqual(calls,[])
        self.assertEqual(self.lab.batch(batch['id'])['status'],'partial')

    def test_result_pagination_and_sql_work_without_source_and_never_create_it(self):
        self.ingest();self.ingest('two');batch=self.evaluate();second=self.evaluate()
        saved=Results(self.lab.path);self.store.path.rename(self.root/'elsewhere.sqlite')
        page=saved.results(batch['id'],limit=1)
        self.assertTrue(page['truncated']);self.assertEqual(page['next_after'],0)
        tail=saved.results(batch['id'],limit=1,after=page['next_after'])
        self.assertFalse(tail['truncated']);self.assertEqual(tail['rows'][0]['ordinal'],1)
        self.assertIsNone(tail['next_after'])
        newest=saved.batches(limit=1)
        self.assertEqual(newest['rows'][0]['id'],second['id'])
        older=saved.batches(limit=1,before=newest['next_before'])
        self.assertEqual(older['rows'][0]['id'],batch['id']);self.assertIsNone(older['next_before'])
        self.assertEqual(saved.query('SELECT count(*) n FROM research_results')['rows'],[{'n':2}])
        for sql in ['DELETE FROM research_results',"ATTACH 'evil.sqlite' AS evil",'PRAGMA writable_schema=1']:
            with self.assertRaises(InputError):saved.query(sql)
        with self.assertRaises(InputError):saved.results('missing')
        with self.assertRaises(InputError):saved.batch('missing')
        with self.assertRaises(InputError):saved.results(batch['id'],after=-2)
        with self.assertRaises(InputError):saved.batches(before=0)
        missing=self.root/'missing.sqlite'
        with self.assertRaises(InputError):Results(missing)
        self.assertFalse(missing.exists());self.assertFalse(self.store.path.exists())

    def test_export_preserves_failed_unknown_and_partial_membership(self):
        self.ingest();self.ingest('two');calls=[]
        def partial(row,c):
            calls.append(row)
            if len(calls)==2:raise ValueError('No evaluator available')
            return {'value':None,'status':'unavailable'}
        batch=self.evaluate(partial);saved=Results(self.lab.path)
        destination=self.root/'share.zip'
        manifest=saved.export(batch['id'],destination)
        self.assertEqual(manifest['batch']['status'],'partial')
        with zipfile.ZipFile(destination) as archive:
            data=archive.read('results.jsonl');rows=[json.loads(line) for line in data.splitlines()]
            self.assertEqual(json.loads(archive.read('manifest.json')),manifest)
        self.assertEqual(manifest['files']['results.jsonl'],dict(rows=2,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        self.assertEqual(rows[0]['output'],{'value':None,'status':'unavailable'})
        self.assertIsNone(rows[1]['output']);self.assertIn('No evaluator available',rows[1]['error'])
        self.assertEqual(rows[0]['input'],calls[0])
        with self.assertRaises(InputError):saved.export(batch['id'],destination)
        limited=self.root/'limited.zip'
        with self.assertRaises(InputError):saved.export(batch['id'],limited,max_bytes=1)
        self.assertFalse(limited.exists())

    def test_source_independent_resume_obeys_evaluator_lock(self):
        self.ingest();saved=Results(self.lab.path)
        def callback(row,config):
            batch=saved.batches()['rows'][0]
            self.assertEqual(saved.batch(batch['id'])['counts']['pending'],1)
            with self.assertRaises(InputError):saved.resume(batch['id'],lambda r,c:{},version='v1')
            return {'ok':True}
        self.evaluate(callback)

    def test_initialization_failure_never_publishes_empty_database(self):
        target=self.root/'new.sqlite'
        with patch('tracker.research.os.link',side_effect=OSError('interrupted publication')):
            with self.assertRaises(OSError):Research(self.data,target)
        self.assertFalse(target.exists())
        Research(self.data,target)
        self.assertEqual(Results(target).batches()['rows'],[])


if __name__=='__main__':unittest.main()
