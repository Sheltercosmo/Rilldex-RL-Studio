"""Persisted source analysis and HTTP reflect the same corrected ordering."""
import json
import unittest
from urllib.request import urlopen
from unittest.mock import patch
from tracker import observe
from tracker.schema import dumps
from test_observation_order_accuracy import fixture
from test_goal_order_accuracy import fixture as goal_fixture
import test_generation_cohort_transport as transport_fixture


class ObservationOrderHTTPTests(unittest.TestCase):
    setUp=transport_fixture.GenerationCohortTransportTests.setUp
    start_server=transport_fixture.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport_fixture.GenerationCohortTransportTests.stop_server)

    def test_existing_goal_annotations_refresh_without_reinference_or_source_changes(self):
        run, actions, semantics = goal_fixture()
        actions[1]['order_known'] = False
        self.store.add([run])
        for eid, result in semantics.items():
            self.store.record(run['id'], eid, 'test', 'fixture', 'packet', result)
        old = observe.analyze(run, semantics)
        old['harness_version'] = 'macro/0.10.0'
        old['metrics']['goal_returns'] = 1
        old['metrics']['target_returns'] = 1
        with self.store.connect() as c:
            c.execute('UPDATE runs SET analysis=? WHERE id=?', (dumps(old), run['id']))
        with patch('tracker.jev.JevClient._post', side_effect=AssertionError('Reuse existing assignments')):
            local = self.store.get(run['id'], raw=True)
        self.assertEqual(local['analysis']['metrics']['goal_assignments'], 4)
        self.assertEqual(local['analysis']['metrics']['goal_returns'], 0)
        self.assertEqual(local['analysis']['metrics']['target_returns'], 0)
        endpoint = self.start_server()
        with urlopen(endpoint+'/api/runs/'+run['id'], timeout=15) as response:
            remote = json.load(response)
        self.assertEqual(remote['analysis'], local['analysis'])
        with self.store.connect() as c:
            self.assertEqual(json.loads(c.execute('SELECT document FROM runs WHERE id=?', (run['id'],)).fetchone()[0]), run)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 4)
        self.assertEqual(self.store.get(run['id'], raw=True)['model_observations'], local['model_observations'])

    def test_stale_analysis_is_corrected_on_read_and_served_without_new_inference(self):
        run=fixture()
        [e for e in run['events'] if e['kind']=='action'][1]['order_known']=False
        self.store.add([run])
        old=observe.analyze(run);old['harness_version']='macro/0.9.0'
        old['metrics']['sequence']['observed_pairs']=2
        old['verification']['actor_tails'][0]['status']='no_later_application_observed'
        with self.store.connect() as c:
            c.execute('UPDATE runs SET analysis=? WHERE id=?',(dumps(old),run['id']))
        with patch('tracker.jev.JevClient._post',side_effect=AssertionError('No model call needed')):
            local=self.store.get(run['id'])
        self.assertEqual(local['analysis']['harness_version'],observe.HARNESS_VERSION)
        self.assertEqual(local['analysis']['metrics']['sequence']['observed_pairs'],0)
        self.assertEqual(local['analysis']['verification']['actor_tails'][0]['status'],'unresolved')
        endpoint=self.start_server()
        with urlopen(endpoint+'/api/runs/'+run['id'],timeout=15) as response:remote=json.load(response)
        self.assertEqual(remote['analysis'],local['analysis'])
        with self.store.connect() as c:
            self.assertEqual(json.loads(c.execute('SELECT document FROM runs WHERE id=?',(run['id'],)).fetchone()[0]),run)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM observations').fetchone()[0],0)


if __name__=='__main__':unittest.main()
