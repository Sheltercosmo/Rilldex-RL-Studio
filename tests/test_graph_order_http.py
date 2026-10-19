"""Source-order evidence through storage, query, monitor receipt and renderer."""
import json
import subprocess
import unittest
from urllib.request import Request, urlopen

from tracker import graph_store, graph_queries, monitoring, monitor_evidence
from tracker.schema import digest
from tests import test_generation_cohort_transport as transport
from tests.test_graph_order_accuracy import fixture, events


class GraphOrderHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def save_graph(self,mode):
        run,g,a=fixture()
        if mode=='parallel':
            for u in a[:2]:
                e=events(g)[u['source']['event_id']];e.pop('parent_id',None);e['source_message_index']=17
        elif mode=='prefix':events(g)[a[2]['source']['event_id']]['order_known']=False
        elif mode=='gap':events(g)[a[1]['source']['event_id']]['order_known']=False
        elif mode=='sessions':
            for u in a[:2]:events(g)[u['source']['event_id']]['context_id']='other'
        run['events']=sorted(events(g).values(),key=lambda e:e['index'])
        run['metadata'].update(experiment='order-controls',training_step=1)
        units=[]
        for n in g['nodes']:
            if n['kind']!='unit':continue
            p=n['properties'];p['activity']=n['activity'];p['trajectory_id']=n['trajectory_id']
            p['source']['source_pointer']=events(g)[p['source']['event_id']].get('source_pointer')
            units.append(p)
        relations=[dict(from_=e['source'],to=e['target'],type=e['type']) for e in g['edges'] if e['type'] in {'revises','uses_evidence'}]
        for r in relations:r['from']=r.pop('from_')
        g=graph_store.build(run,dict(observer=dict(id='test',label='Order controls'),
            document=dict(schema='semantic-unit-map/1',source_hash=digest(run),units=units,relations=relations)))
        self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,g)
        return run,g,a

    def test_order_gaps_survive_http_query_monitor_and_map_without_false_negatives(self):
        run,g,a=self.save_graph('parallel')
        monitor=monitoring.create(self.store,dict(name='Revision after inspection',kind='graph',observer='test',
            requirement=graph_queries.PRESETS['revision_after_inspect']))
        monitoring.sync(self.store,[monitor['id']])
        saved_graph=graph_store.read(self.store,g['id'])
        value=monitoring.values(self.store,monitor['id'],{run['id']})[run['id']]
        proof=monitor_evidence.read(self.store,value['id'])
        self.assertEqual((value['numerator'],value['denominator']),(0,0))
        self.assertIsNone(value['value'])
        self.assertEqual(proof['explanation']['not_established'],0)
        self.assertEqual(proof['explanation']['unavailable_windows'][0]['anchor'],a[0]['id'])
        endpoint=self.start_server()
        def read(path):
            with urlopen(endpoint+path,timeout=15) as response:return json.load(response)
        remote=read('/api/monitoring/values/'+value['id'])
        self.assertEqual(remote['explanation'],proof['explanation'])
        foundation=read('/api/map-foundation?graph='+g['id'])
        matrix=read('/api/graphs/'+g['id'])['matrices']
        self.assertEqual(matrix['transition_coverage']['excluded_pairs'],2)
        self.assertEqual(foundation['source_order']['nodes'][a[0]['id']]['reason'],'parallel_dispatch')
        request=Request(endpoint+'/api/graph-query',data=json.dumps(dict(graph_ids=[g['id']],
            requirement=monitor['requirement'])).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=15) as response:result=json.load(response)
        self.assertEqual(result['training'][0]['bins'][0]['unavailable_windows'],1)
        self.assertEqual(result['training'][0]['bins'][0]['denominator'],0)
        # Execute the actual renderer with the exact HTTP payload, not a second
        # hand-built representation of native grouping rules.
        script="""const fs=require('fs'),L=require('./tracker/web/map-layout.js');
const {graph,f}=JSON.parse(fs.readFileSync(0,'utf8'));
const view=L.project(graph,f.excluded_edge_ids,f.content_sources.excluded_unit_ids,f.source_order);
process.stdout.write(JSON.stringify(view.edges));"""
        rendered=subprocess.run(['node','-e',script],input=json.dumps(dict(graph=g,f=foundation)),
                                text=True,capture_output=True,check=True)
        edges=json.loads(rendered.stdout)
        self.assertFalse(any(e['source']==a[0]['id'] and e['target']==a[1]['id'] for e in edges))
        self.assertFalse(any(e['type']=='revises' for e in edges))
        self.assertEqual(graph_store.read(self.store,g['id']),saved_graph)
        monitoring.sync(self.store,[monitor['id']])
        self.assertEqual(monitoring.values(self.store,monitor['id'],{run['id']})[run['id']]['id'],value['id'])

    def test_earlier_positive_stays_inspectable_when_the_tail_is_unordered(self):
        run,g,_=self.save_graph('prefix')
        monitor=monitoring.create(self.store,dict(name='Revision after inspection',kind='graph',observer='test',
            requirement=graph_queries.PRESETS['revision_after_inspect']))
        monitoring.sync(self.store,[monitor['id']])
        value=monitoring.values(self.store,monitor['id'],{run['id']})[run['id']]
        proof=monitor_evidence.read(self.store,value['id'])['explanation']
        self.assertEqual((proof['numerator'],proof['denominator'],proof['value']),(1,1,1))
        self.assertEqual(proof['cases'][0]['window_status'],'ordered_prefix')
        self.assertEqual(proof['cases'][0]['order_blocker']['reason'],'unresolved_source_order')
        self.assertEqual(proof['unavailable_windows'],[])


if __name__=='__main__':unittest.main()
