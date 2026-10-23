from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from rilldex import Workspace
from rilldex.scopes import ProgressSaveError
from tracker import graph_store, work_content_results as results, work_mentions
from tracker.schema import InputError, digest
from tracker.store import Store
from test_work_scope_frames import fixture as base_fixture


def fixture(count=1):
    from test_unit_reviews import unit_item
    run,base=base_fixture(count)
    units=[]
    for node in base['nodes']:
        if node['kind']!='unit':continue
        unit=deepcopy(node['properties']);event=run['events'][node['event_index']]
        unit.update(id=node['id'],activity=node['activity'],trajectory_id=node['trajectory_id'])
        unit['source']['source_pointer']=event['source_pointer']
        unit['content']=unit_item(run,unit['source'],text=unit['source']['text'])['fields']
        units.append(unit)
    return run,graph_store.build(run,dict(document=dict(source_hash=digest(run),units=units,relations=[]),
        observer=dict(id='content-control',label='Authored content control')))


class WorkContentResultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'study.sqlite')
        self.db=self.store.path
        self.run,self.graph=fixture();self.store.add([self.run])
        with self.store.connect() as c:graph_store.save(c,self.graph)
        self.workspace=Workspace(self.store.path);self.calls=[];self.seen=[]
        self.contents=[dict(id='c1',kind='operation',mode='proposed',expression=dict(text='create sample 0')),
                       dict(id='c2',kind='operation',mode='proposed',expression=dict(text='test implementation 0'))]
        self.features=[dict(id='f1',type='intent',form='literal',expression=dict(text='I will')),
                       dict(id='f2',type='target',form='literal',expression=dict(text='sample 0')),
                       dict(id='f3',type='target',form='literal',expression=dict(text='implementation 0'))]

    def propose(self,payload):
        stage=payload['request']['stage'];self.calls.append(stage)
        return dict(raw_output=json.dumps(dict(contents=self.contents) if stage=='contents' else dict(features=self.features)),usage={})

    def decide(self,q):
        fid=q['state']['feature']['id'];self.calls.append(fid);answers={}
        for key,cid in q['state']['question_contents'].items():
            value='unresolved' if fid=='f3' else 'applies' if fid=='f1' or cid=='c1' else 'does_not_apply'
            answers[key]=dict(type='choice',choice='unresolved',probabilities={v:float(v==value) for v in q['questions'][key]['criteria']})
        return dict(model=q['model'],answers=answers)

    def progress(self,_):
        self.seen.append(self.workspace.work_contents(self.graph['id'],'unit-0')[0])

    def extract(self,**options):
        defaults=dict(candidate_calls=2,decision_calls=3,input_bytes=1000000,candidate_transport=self.propose,
                      candidate_identity='test/control',decision_transport=self.decide,on_progress=self.progress)
        return self.workspace.extract_work_contents(self.graph['id'],'unit-0',self.root/'pilot',**{**defaults,**options})

    def test_partial_progress_is_shared_with_native_sql_and_cached_resume(self):
        first=self.extract(decision_calls=1)
        self.assertEqual(first['status'],'budget_reached')
        saved=self.workspace.work_contents(self.graph['id'],'unit-0')[0]
        self.assertEqual(saved['view']['counts'],dict(contents=2,features=3,inspected=1,pending=2))
        self.assertTrue(all(n['mode']=='proposed' for n in saved['view']['contents']))
        self.assertIn('work_extraction=',first['saved']['map_url'])
        self.assertNotIn(str(self.root),json.dumps(saved))
        self.assertEqual(len(self.workspace.table('work_contents').rows),2)
        rows=self.workspace.sql('SELECT status,COUNT(*) n FROM work_attachments GROUP BY status').rows
        self.assertEqual({r['status']:r['n'] for r in rows},dict(applies=2,pending=4))
        self.seen=[];last=self.extract()
        self.assertEqual(last['status'],'complete')
        self.assertEqual(last['saved']['id'],first['saved']['id'])
        self.assertTrue(all(r['view']['counts']['inspected']>=1 for r in self.seen))
        counts=self.workspace.sql('SELECT status,COUNT(*) n FROM work_attachments GROUP BY status').rows
        self.assertEqual({r['status']:r['n'] for r in counts},dict(applies=3,does_not_apply=1,unresolved=2))
        self.assertEqual(self.calls,['contents','features','f1','f2','f3'])
        self.seen=[];self.extract()
        self.assertTrue(all(r['status']=='complete' for r in self.seen))
        self.assertEqual(self.calls,['contents','features','f1','f2','f3'])
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM work_content_extractions').fetchone()[0],1)
        self.assertEqual(graph_store.read(self.store,self.graph['id']),self.graph)

    def test_export_and_scoped_queries_retain_pending_and_source_links(self):
        self.extract(decision_calls=1)
        self.assertEqual(Workspace(self.store.path,observer='different').table('work_contents').rows,[])
        self.assertEqual(Workspace(self.store.path,experiment='different').table('work_attachments').rows,[])
        path=self.root/'export.sqlite';self.workspace.data.database(path)
        portable=Workspace(path)
        self.assertEqual(portable.table('work_contents').rows,self.workspace.table('work_contents').rows)
        self.assertEqual(portable.table('work_attachments').rows,self.workspace.table('work_attachments').rows)
        record=portable.table('content_extractions').rows[0]['record']
        self.assertEqual(record['packet']['units'][0]['source']['text'],self.run['events'][0]['text'])
        with self.assertRaises(InputError):portable.work_contents(self.graph['id'])
        before=path.read_bytes()
        with self.assertRaises(InputError):
            portable.extract_work_contents(self.graph['id'],'unit-0',self.root/'export-pilot')
        self.assertEqual(path.read_bytes(),before)
        # Old portable snapshots remain readable, with new tables unavailable.
        import sqlite3
        with closing(sqlite3.connect(path)) as c:
            with c:
                for name in results.VIEW_SQL:c.execute('DROP TABLE rl_'+name)
        self.assertFalse(Workspace(path).table('work_contents')['available'])
        self.assertEqual(Workspace(path).table('work_contents').rows,[])

    def test_older_workspace_empty_and_wrong_graph_do_not_leak_records(self):
        self.assertEqual(self.workspace.work_contents(self.graph['id'],'unit-0'),[])
        self.assertFalse(self.workspace.table('work_contents')['available'])
        self.extract(candidate_calls=0,decision_calls=0)
        self.assertEqual(self.workspace.work_contents(self.graph['id'])[0]['view']['contents'],[])
        self.assertEqual(self.calls,[])
        with self.assertRaises(InputError):results.read(self.store,self.graph['id'],'other-unit')
        with self.assertRaises(InputError):self.workspace.work_contents('other-graph','unit-0')

    def test_failed_progress_writer_stops_calls_but_cached_response_can_resume(self):
        def fail_after_contents(result):
            if result['bound'] is not None:raise OSError('writer failed')
        with self.assertRaises(ProgressSaveError):self.extract(on_progress=fail_after_contents)
        self.assertEqual(self.calls,['contents'])
        self.assertEqual(len(self.workspace.work_contents(self.graph['id'])[0]['view']['contents']),2)
        self.extract()
        self.assertEqual(self.calls,['contents','features','f1','f2','f3'])

    def test_cross_source_and_modified_receipts_are_rejected(self):
        result=self.extract(decision_calls=1);packet=work_mentions.packet(self.graph,['unit-0'])
        bad=deepcopy(result);bad['review']['receipts'][0]['content_ids']=[]
        with self.assertRaises(InputError):results.save(self.store,self.graph,packet,bad)
        other=deepcopy(packet);other['units'][0]['source']['text']+=' extra'
        with self.assertRaises(InputError):results.save(self.store,self.graph,other,result)
        with self.store.connect() as c:c.execute("UPDATE work_content_extractions SET document='{}'")
        with self.assertRaises(InputError):self.workspace.work_contents(self.graph['id'])

    def test_http_unit_panel_reads_saved_progress_without_model_calls(self):
        from test_generation_cohort_transport import GenerationCohortTransportTests
        from urllib.request import urlopen
        from urllib.parse import urlencode
        from urllib.error import HTTPError
        self.stop_server=GenerationCohortTransportTests.stop_server
        self.extract(decision_calls=1)
        endpoint=GenerationCohortTransportTests.start_server(self)
        query=urlencode(dict(graph=self.graph['id'],unit='unit-0'))
        def read(path):
            with urlopen(endpoint+path,timeout=15) as response:return json.load(response)
        initial=read('/api/work-mentions?'+query)
        self.assertEqual(initial['extractions'],read('/api/work-content-extractions?'+query)['extractions'])
        self.assertEqual(initial['extractions'][0]['view']['counts']['pending'],2)
        self.extract()
        updated=read('/api/work-content-extractions?'+query)['extractions'][0]
        self.assertEqual(updated['status'],'complete')
        self.assertEqual(updated['view']['counts']['pending'],0)
        self.assertEqual(self.calls,['contents','features','f1','f2','f3'])
        self.assertNotIn(str(self.root),json.dumps(updated))
        with self.assertRaises(HTTPError) as error:
            read('/api/work-content-extractions?'+urlencode(dict(graph=self.graph['id'],unit='missing')))
        self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
