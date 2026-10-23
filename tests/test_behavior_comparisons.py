import json
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import test_behavior_distributions as fixtures
import test_generation_cohort_transport as transport
from tracker import behavior_distributions as behavior, monitoring
from tracker.schema import InputError
from tracker.store import Store
from rilldex import Workspace


class BehaviorComparisonTests(unittest.TestCase):
    setUp=fixtures.DistributionTests.setUp
    run_fixture=fixtures.DistributionTests.run_fixture
    graph=fixtures.DistributionTests.graph

    def seed(self):
        first=self.run_fixture(1,training_step=0)
        later=self.run_fixture(2,training_step=1)
        self.graph(first,('orient',));self.graph(later,('verify',))
        behavior.sync(self.store)
        return first,later

    def test_membership_and_graphs_share_one_read_snapshot_during_publication(self):
        first,later=self.seed()
        before=behavior.snapshot(self.store,experiment='test')
        original=monitoring.population
        def publish_between_reads(store):
            members=original(store)
            self.graph(later,('construct',))
            self.graph(self.run_fixture(3,training_step=1),('construct',))
            behavior.sync(self.store)
            return members
        with patch.object(monitoring,'population',side_effect=publish_between_reads):
            during=behavior.snapshot(self.store,experiment='test')
        self.assertEqual(during,before)
        after=behavior.snapshot(self.store,experiment='test')
        self.assertEqual(after['population'],3)
        self.assertNotEqual(after['snapshot_id'],before['snapshot_id'])

    def test_saved_capture_survives_late_arrivals_reannotation_and_reopen(self):
        first,later=self.seed()
        saved=behavior.save_comparison(self.store,{'controls':{'experiment':'test'},'title':'Early behavior'})
        old_graphs={p['graph_id'] for p in saved['snapshot']['points']}
        self.graph(later,('construct',))
        self.graph(self.run_fixture(3,training_step=1),('construct',))
        self.graph(self.run_fixture(4,training_step=9),('verify',))
        behavior.sync(self.store)
        reopened=Store(self.store.path)
        self.assertEqual(behavior.read_comparison(reopened,saved['id']),saved)
        child=behavior.save_comparison(reopened,{'parent_id':saved['id']})
        self.assertEqual(child['controls'],saved['controls'])
        self.assertEqual(child['parent_id'],saved['id'])
        self.assertEqual((child['snapshot']['baseline']['start'],child['snapshot']['current']['end']),(0,1))
        self.assertEqual(child['snapshot']['current']['population'],2)
        self.assertNotEqual({p['graph_id'] for p in child['snapshot']['points']},old_graphs)
        self.assertEqual(behavior.read_comparison(reopened,saved['id']),saved)
        self.assertEqual(len(behavior.saved_comparisons(reopened,experiment='test')),2)
        self.assertEqual(behavior.saved_comparisons(reopened,experiment='other'),[])
        self.assertTrue(all('graph='+p['graph_id'] in p['map_url'] for p in saved['snapshot']['cases']))

    def test_invalid_controls_and_unresolved_followups(self):
        self.seed()
        for controls in ({'lens':{}},{'weighting':[]},{'observer':1},{'a_start':True},{'extra':'x'}):
            with self.subTest(controls=controls),self.assertRaises(InputError):
                behavior.save_comparison(self.store,{'controls':controls})
        empty=behavior.save_comparison(self.store,{'controls':{'experiment':'empty'}})
        with self.assertRaisesRegex(InputError,'live comparison'):
            behavior.save_comparison(self.store,{'parent_id':empty['id']})

    def test_code_access_retains_scope_and_returns_the_same_saved_evidence(self):
        self.seed();workspace=Workspace(self.store.path,experiment='test',observer='review')
        live=workspace.compare_behavior(lens='work')
        saved=workspace.compare_behavior(lens='work',save=True,title='Code capture')
        self.assertEqual(live,saved['snapshot'])
        self.assertEqual(workspace.compare_behavior(saved=saved['id']),saved)
        child=workspace.compare_behavior(parent_id=saved['id'],save=True)
        self.assertEqual(child['controls'],saved['controls'])
        for wrong in (Workspace(self.store.path,experiment='wrong'),Workspace(self.store.path,observer='wrong')):
            with self.assertRaisesRegex(InputError,'outside'):wrong.compare_behavior(saved=saved['id'])
        with self.assertRaises(InputError):workspace.compare_behavior(experiment='wrong')
        with self.assertRaises(InputError):workspace.compare_behavior(parent_id=saved['id'])


class BehaviorComparisonHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)
    run_fixture=fixtures.DistributionTests.run_fixture
    graph=fixtures.DistributionTests.graph

    def test_save_read_list_followup_and_validation(self):
        for step in (0,1):self.graph(self.run_fixture(step,training_step=step))
        behavior.sync(self.store);endpoint=self.start_server()
        def call(path,body=None):
            req=Request(endpoint+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=20) as response:return json.load(response)
        saved=call('/api/behavior-comparisons',{'controls':{'experiment':'test'}})
        path='/api/behavior-comparisons/'+saved['id']
        self.assertEqual(call(path),saved)
        self.assertEqual(call(path+'?download=1'),saved)
        self.assertEqual(call('/api/behavior-comparisons?experiment=test')['comparisons'][0]['id'],saved['id'])
        self.assertEqual(call('/api/behavior-comparisons?experiment=other')['comparisons'],[])
        self.assertEqual(call('/api/behavior-comparisons',{'parent_id':saved['id']})['parent_id'],saved['id'])
        for body in ({'controls':{'lens':{}}},{'parent_id':saved['id'],'controls':{}}):
            with self.assertRaises(HTTPError) as error:call('/api/behavior-comparisons',body)
            self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
