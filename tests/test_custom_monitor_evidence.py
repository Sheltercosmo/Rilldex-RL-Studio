from copy import deepcopy
import json
import unittest

from tracker import graph_store, monitoring, monitor_evidence
from tracker.adapters import normalize
from tracker.evaluation_receipts import cite_source
from tracker.schema import InputError,digest
from tracker.workspace_analysis import Workspace
import test_custom_monitors as fixtures
from test_tracker import harbor


class CustomEvidenceTests(unittest.TestCase):
    setUp=fixtures.CustomMonitorTests.setUp
    add_run=fixtures.CustomMonitorTests.add_run

    def monitor(self):
        return self.workspace.monitor('Cited rule',version='1',description='Authored source-link control')

    def test_exact_citation_resolves_only_overlapping_units_and_native_sql(self):
        document=harbor();document['steps'][0]['message']='Task 🧪. Preserve ISO support.'
        run=normalize(document,'harbor',{'experiment':'train','training_step':0})[0];self.store.add([run])
        event=run['events'][0];cut=event['text'].index('Preserve')
        def unit(name,start,end):
            return {'id':name,'kind':'semantic','activity':'orient','source':{
                'event_id':event['id'],'source_pointer':event['source_pointer'],'start':start,'end':end,'text':event['text'][start:end]}}
        graph=graph_store.build(run,{'document':{'source_hash':digest(run),'units':[unit('other',0,cut),unit('cited',cut,len(event['text']))],'relations':[]},'observer':{'id':'review','label':'Reviewed fixture'}})
        with self.store.connect() as c:graph_store.save(c,graph)
        monitor=self.monitor()
        monitor.run(lambda ctx:{'value':1,'source_citations':[ctx.cite(event['id'],role='requirement',quote='Preserve ISO support.')]})
        value=monitoring.cases(self.store,monitor.id)['rows'][0]['measurement']
        proof=monitor_evidence.read(self.store,value['id']);excerpt=proof['explanation']['source_excerpts'][0]
        self.assertEqual(excerpt['node_ids'],['cited'])
        self.assertEqual(excerpt['actor'],'user')
        self.assertEqual(excerpt['citation']['start'],8) # Unicode code points, including emoji.
        rows=self.workspace.sql("SELECT json_extract(details_json, '$.source_citations[0].text') quote FROM monitor_values WHERE monitor_id=?",[monitor.id]).rows
        self.assertEqual(rows,[{'quote':'Preserve ISO support.'}])

    def test_remote_publication_rejects_wrong_source_offsets_content_and_duplicates(self):
        run,source,graph=self.add_run();monitor=self.monitor()
        citation=cite_source(run,run['events'][0]['id'],role='requirement')
        bad=[]
        for key,value in [('run_id','different'),('source_hash','0'*64),('text','x'*len(citation['text'])),('source_pointer','/wrong'),('start',1)]:
            bad.append([{**citation,key:value}])
        bad.append([citation,citation])
        for citations in bad:
            with self.subTest(citations=citations),self.assertRaises(InputError):
                monitor.publish(run['id'],source_hash=source['source_hash'],graph_id=graph['id'],result={'value':1,'source_citations':citations})
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM custom_monitor_inputs').fetchone()[0],0)

    def test_callback_cannot_rewrite_source_or_graph_to_validate_fabricated_evidence(self):
        a,_,_=self.add_run('a');b,_,_=self.add_run('b');self.add_run('c');monitor=self.monitor()
        def callback(ctx):
            if ctx.run['id']==a['id']:
                ctx.run['events'][0]['text']='Fabricated passage'
                return {'value':1,'source_citations':[ctx.cite(ctx.run['events'][0]['id'])]}
            if ctx.run['id']==b['id']:
                ctx.graph['nodes'].append({'id':'invented'})
                return {'value':1,'evidence_ids':['invented']}
            return {'value':0}
        result=monitor.run(callback)
        self.assertEqual(result['errors'],2);self.assertEqual(result['published'],3)
        rows=monitoring.cases(self.store,monitor.id)['rows']
        self.assertEqual({r['run']['id']:r['measurement']['status'] for r in rows},{'run-a':'error','run-b':'error','run-c':'available'})
        self.assertEqual(monitor.run(callback)['skipped'],3)

    def test_reward_input_evidence_is_checked_against_the_actual_source(self):
        run=normalize(harbor(),'harbor',{'experiment':'train','reward_definition':'score/v1'})[0]
        run['raw']['passed']=False;self.store.add([run]);workspace=Workspace(self.path,experiment='train',observer='source')
        detector=workspace.reward_detector('Input evidence',version='1',description='Fixture',reward_definition='score/v1',inputs={'passed':'/raw/passed'})
        detector.run(lambda ctx:{'status':'flagged','summary':'Recorded check failed','input_evidence':['passed'],
            'source_citations':[ctx.cite(ctx.run['events'][0]['id'],role='requirement')]})
        value=monitoring.cases(self.store,detector.id)['rows'][0]['measurement'];proof=monitor_evidence.read(self.store,value['id'])
        self.assertEqual(proof['explanation']['input_values'],[{'name':'passed','pointer':'/raw/passed','value':False}])
        self.assertEqual(proof['explanation']['source_excerpts'][0]['node_ids'],['event:'+run['events'][0]['id']])
        empty=deepcopy(proof['input_record']['result']);empty['source_citations']=[];empty['details']['detector']['input_evidence']={}
        with self.assertRaisesRegex(InputError,'flagged result needs'):
            detector.monitor.publish(run['id'],source_hash=digest(run),graph_id=proof['graph']['id'],dependencies={'empty':1},result=empty)
        for changed in [0,True]:
            result=deepcopy(proof['input_record']['result']);result['details']['detector']['input_evidence']['passed']['value']=changed
            with self.subTest(changed=changed),self.assertRaisesRegex(InputError,'differs from the saved source'):
                detector.monitor.publish(run['id'],source_hash=digest(run),graph_id=proof['graph']['id'],dependencies={'changed':changed},result=result)

    def test_historical_citations_survive_late_source_and_graph_revisions(self):
        body={'producer':'p','rollout_id':'r','revision':0,'state':'complete','format':'harbor','document':harbor(),'metadata':{'experiment':'train'}}
        first=self.store.ingest(body)
        with self.store.connect() as c:run=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(first['id'],)).fetchone()[0])
        monitor=Workspace(self.path,observer='source').monitor('Source citation',version='1',description='Original source')
        monitor.run(lambda ctx:{'value':1,'source_citations':[ctx.cite(ctx.run['events'][0]['id'],role='requirement')]})
        value=monitoring.cases(self.store,monitor.id)['rows'][0]['measurement']
        body['revision']=1;body['document']['steps'][0]['message']='Revised requirement';self.store.ingest(body)
        proof=monitor_evidence.read(self.store,value['id'])
        self.assertFalse(proof['freshness']['current_source'])
        self.assertEqual(proof['explanation']['source_excerpts'][0]['citation']['text'],run['events'][0]['text'])


if __name__=='__main__':unittest.main()
