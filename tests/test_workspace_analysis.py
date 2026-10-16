import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from rilldex import Workspace
from tracker import graph_store
from tracker.analytics import Analysis
from tracker.cli import main
from tracker.portable import generation_document
from tracker.schema import InputError, digest
from tracker.store import Store


class WorkspaceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'live.sqlite')
        self.ws=Workspace(self.store.path,experiment='train',observer='semantic')

    def ingest(self,name='a',revision=0,experiment='train'):
        return self.store.ingest(dict(producer='worker',rollout_id=name,revision=revision,state='complete',
            format='generation',metadata={'experiment':experiment,'generation_step':revision},
            document=generation_document('Q','Answer '+name+'/'+str(revision))))['id']

    def graph(self,run_id,observer='semantic',activity='revise'):
        nodes=[dict(id='n1',kind='unit',activity='inspect',event_index=0,properties={'text':'Read the feedback'}),
               dict(id='n2',kind='unit',activity=activity,event_index=1,properties={'text':'Change the approach'})]
        edges=[dict(id='e1',source='n1',target='n2',type='next_unit',properties={'causal':False}),
               dict(id='e2',source='n1',target='n2',type='responds_to',properties={'evidence':['n1','n2']})]
        value=dict(schema='test-graph',run_id=run_id,observer=observer,source_hash=run_id,
                   annotation_hash='synthetic',nodes=nodes,edges=edges)
        value['id']='graph-'+digest(value)
        with self.store.connect() as c:graph_store.save(c,value)
        return value['id']

    def test_fresh_reads_and_decoded_records_without_exports(self):
        first=self.ingest()
        with patch.object(Analysis,'export',side_effect=AssertionError('No export')), patch.object(Analysis,'database',side_effect=AssertionError('No copy')):
            self.assertEqual(self.ws.rollouts().rows[0]['metadata']['experiment'],'train')
            self.assertEqual(len(self.ws.rollouts().rows),1)
            second=self.ingest(revision=1)
            self.assertEqual([r['run_id'] for r in self.ws.rollouts().rows],[second])
            self.assertEqual(self.ws.sql('WITH latest AS (SELECT * FROM rollouts) SELECT COUNT(*) n FROM latest').rows,[{'n':1}])
        self.assertFalse(self.ws.results_path.exists())
        self.assertEqual(len(Workspace(self.store.path,experiment='train',history=True).rollouts().rows),2)

    def test_composite_graph_joins_and_parallel_edges(self):
        a=self.ingest();b=self.ingest('b');c=self.ingest('c',experiment='other')
        gid=self.graph(a);self.graph(b);self.graph(c);self.graph(a,observer='other',activity='plan')
        linked=self.ws.relations(source_activity='inspect',target_activity='revise')
        self.assertEqual(len(linked.rows),4)
        self.assertTrue(all(r['source']=='n1' and r['target']=='n2' for r in linked.rows))
        result=self.ws.relation_counts()
        self.assertEqual(sorted(r['links'] for r in result.rows),[2,2])
        self.assertEqual(result['coverage']['source_snapshots'],2)
        self.assertEqual(result['coverage']['tagged_units'],4)
        self.assertIn('semantic',[r['observer'] for r in self.ws.options()['observers']])
        self.assertEqual(sum(r['snapshots'] for r in self.ws.recorded_outcomes().rows),2)
        graph=self.ws.graph(gid)
        self.assertEqual(len(graph.connections('n1')),2)
        self.assertEqual(graph.connections('n2',direction='in',relation='responds_to')[0]['id'],'e2')
        self.assertEqual(graph.nodes[0]['properties']['text'],'Read the feedback')
        with self.assertRaises(InputError):self.ws.graph(gid,limit=1)
        with self.assertRaises(InputError):Workspace(self.store.path,observer='other').graph(gid)

    def test_immutable_graph_versions_and_missing_tags(self):
        rid=self.ingest();old=self.graph(rid);new=self.graph(rid,activity='verify')
        self.assertEqual({r['activity'] for r in self.ws.activity_counts().rows},{'inspect','verify'})
        with self.assertRaises(InputError):self.ws.graph(old)
        self.assertEqual(Workspace(self.store.path,observer='semantic',history=True).graph(old).graph_id,old)
        source=Workspace(self.store.path,observer='source')
        self.assertEqual(source.activity_counts().rows,[])
        self.assertEqual(source.activity_counts()['coverage']['rollouts_with_tagged_units'],0)
        metrics=source.metrics(metric='recorded_success').rows
        self.assertIsNone(metrics[0]['value']);self.assertTrue(metrics[0]['reason'])
        self.assertIsNone(source.metric_series('recorded_success').rows[0]['training_step'])

    def test_work_structure_uses_exact_scoped_graph_without_export(self):
        from test_work_hierarchy import graph, finish
        from tracker.work_structure_metrics import project
        rid=self.ingest();g=graph()
        g.update(run_id=rid,observer='semantic',annotation_hash='authored')
        g=finish(g)
        with self.store.connect() as c:graph_store.save(c,g)
        with patch.object(Analysis,'export',side_effect=AssertionError('No export')):
            self.assertEqual(self.ws.work_structure(g['id']),project(g))
            self.assertEqual(self.ws.work_structure(g['id'],cutoff_event_id='e0'),project(g,'e0'))
        with self.assertRaises(InputError):self.ws.work_structure(g['id'],limit=1)
        with self.assertRaises(InputError):self.ws.work_structure(g['id'],cutoff_event_id='absent')
        with self.assertRaises(InputError):Workspace(self.store.path,observer='other').work_structure(g['id'])

    def test_custom_functions_cached_and_visible_in_managed_results(self):
        self.ingest();calls=[]
        def measure(row,config):
            calls.append(row['run_id'])
            return {'experiment':row['metadata']['experiment'],'value':row['verified_success']}
        before=self.store.path.read_bytes()
        first=self.ws.evaluate('my_measure',measure,version='1')
        repeat=self.ws.evaluate('my_measure',measure,version='1')
        self.assertEqual(first['id'],repeat['id']);self.assertEqual(len(calls),1)
        self.assertEqual(self.ws.saved_analyses()['rows'][0]['id'],first['id'])
        outputs=self.ws.results().results(first['id'])
        self.assertEqual(json.loads(outputs['rows'][0]['output_json'])['experiment'],'train')
        self.assertEqual(self.store.path.read_bytes(),before)
        self.ingest('b');self.ws.evaluate('my_measure',measure,version='1')
        self.assertEqual(len(calls),2)
        with self.assertRaises(InputError):self.ws.evaluate('bad',None,version='1')

    def test_truncation_safety_filters_and_read_only_sql(self):
        self.ingest();self.ingest('b')
        limited=self.ws.rollouts(limit=1)
        self.assertTrue(limited['truncated'])
        with self.assertRaises(InputError):limited.to_pandas()
        with self.assertRaises(InputError):self.ws.rollouts(unknown='x')
        self.assertEqual(self.ws.rollouts(experiment="' OR 1=1 --").rows,[])
        for sql in ('DELETE FROM runs','SELECT 1; DELETE FROM runs',"SELECT load_extension('x')"):
            with self.assertRaises(InputError):self.ws.sql(sql)
        with self.assertRaises(InputError):self.ws.sql("SELECT '{}' AS item_json, 1 AS item")

    def test_frozen_datasets_and_missing_sources_remain_explicit(self):
        self.ingest();path=self.root/'frozen.sqlite';Analysis(self.store.path).database(path)
        data=Workspace(path)
        self.assertEqual(len(data.rollouts().rows),1)
        self.assertFalse(data.table('sources')['available'])
        self.assertEqual(data.table('sources').rows,[])

    def test_cli_and_function_api_agree(self):
        rid=self.ingest();self.graph(rid)
        output=io.StringIO()
        with redirect_stdout(output):main(['--db',str(self.store.path),'analysis','compute','activity_counts','--experiment','train','--observer','semantic'])
        result=json.loads(output.getvalue())
        self.assertEqual(result['rows'],self.ws.activity_counts().rows)

    def test_missing_workspace_never_created_by_reader(self):
        path=self.root/'missing.sqlite'
        with self.assertRaises(InputError):Workspace(path)
        self.assertFalse(path.exists())
        self.assertEqual(self.ws.saved_analyses()['rows'],[])
        self.assertFalse(self.ws.results_path.exists())


if __name__=='__main__':unittest.main()
