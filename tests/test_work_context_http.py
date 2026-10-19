"""Map, graph analysis API and investigation metrics share session boundaries."""
import json
import unittest
from urllib.request import Request,urlopen

from tracker import graph_store,investigation_plans,failure_investigations
from tracker.schema import digest
from tests import test_generation_cohort_transport as transport_fixture
from tests.test_work_episodes import example,edge


class WorkContextHTTPTests(unittest.TestCase):
    setUp=transport_fixture.GenerationCohortTransportTests.setUp
    start_server=transport_fixture.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport_fixture.GenerationCohortTransportTests.stop_server)

    def test_interleaved_sessions_have_same_map_and_investigation_counts(self):
        run,old,actions=example(('A','B','A'))
        for e in run['events']:e['context_id']='second' if 3<=e['index']<6 else 'first'
        units=[n['properties'] for n in old['nodes'] if n['kind']=='unit']
        g=graph_store.build(run,dict(observer=dict(id='session-control',label='Session control'),
            document=dict(schema='semantic-unit-map/1',source_hash=digest(run),units=units,relations=[])))
        edge(g,actions[1],actions[0],'same_action_target')  # stale cross-session interpretation
        edge(g,actions[2],actions[0],'same_action_target')  # valid local recurrence
        g['edges'].sort(key=lambda e:e['id']);g.pop('id');g['id']='graph-'+digest(g)
        self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,g)
        params=dict(graph_id=g['id'],run_id=run['id'],source_hash=digest(run))
        plan=dict(schema='investigation-plan/1',nodes=[
            dict(name='navigation',op='work_navigation',inputs=[],params=params),
            dict(name='episodes',op='work_episodes',inputs=[],params=params)])
        local=investigation_plans.execute(self.store,plan)
        nav=local['outputs']['navigation'];episode=local['outputs']['episodes']
        self.assertEqual((nav['counts']['continued'],nav['counts']['returned']),(1,0))
        self.assertEqual((len(nav['paths']),len(nav['visits'])),(2,2))
        self.assertEqual(episode['counts']['continued'],1)
        snapshot=failure_investigations.snapshot(self.store,run=run['id'],observer='session-control',
                                               signal='episode:returned',operator='ge',threshold=1)
        metrics={m['id']:m for m in snapshot['metrics']}
        self.assertEqual(metrics['episode:returned']['values'][run['id']]['value'],0)
        self.assertEqual(metrics['episode:continued']['values'][run['id']]['value'],1)
        endpoint=self.start_server()
        request=Request(endpoint+'/api/investigation-plans',data=json.dumps(plan).encode(),
                        headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=15) as response:remote=json.load(response)
        self.assertEqual(remote['outputs'],local['outputs'])
        self.assertEqual(remote['execution']['cache_hits'],2)
        self.assertEqual(remote['execution']['inference_calls'],0)
        self.assertEqual(graph_store.read(self.store,g['id'])['source_hash'],digest(run))


if __name__=='__main__':unittest.main()
