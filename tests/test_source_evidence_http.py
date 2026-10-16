"""Packaged browser assets and the source-bound analysis contract over HTTP."""
import json
import re
import unittest
from urllib.request import Request, urlopen

import test_generation_cohort_transport as transport
from test_source_evidence import basic_run
from tracker.schema import digest


class EvidenceHTTPTests(unittest.TestCase):
    setUp = transport.GenerationCohortTransportTests.setUp
    start_server = transport.GenerationCohortTransportTests.start_server
    stop_server = staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_map_assets_and_cached_evidence_plan_are_available(self):
        run = basic_run()
        self.store.add([run])
        endpoint = self.start_server()
        with urlopen(endpoint + '/semantic-map', timeout=10) as response:
            html = response.read().decode()
        scripts = re.findall(r'<script src="([^"]+)"', html)
        self.assertIn('/source-evidence.js', scripts)
        for script in scripts:
            with self.subTest(script=script), urlopen(endpoint + script, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn('javascript', response.headers['Content-Type'])
                self.assertTrue(response.read())
        plan = {'schema': 'investigation-plan/1', 'nodes': [{
            'name': 'evidence', 'op': 'evidence_search', 'inputs': [],
            'params': {'run_id': run['id'], 'source_hash': digest(run),
                       'query': {'anchor': {'event_id': 'e7'}, 'text': 'quasarneedle'}}}]}
        def execute():
            request = Request(endpoint + '/api/investigation-plans',
                              data=json.dumps(plan).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=10) as response:
                return json.load(response)
        first, second = execute(), execute()
        self.assertEqual(first['outputs'], second['outputs'])
        self.assertEqual(second['execution']['cache_hits'], 1)
        result = first['outputs']['evidence']
        self.assertTrue(result['matches'])
        self.assertEqual(result['new_model_calls'], 0)
        self.assertTrue(all(row['event_index'] < 6 for row in result['records']))
        plan['nodes'][0]['params']['query']['questions'] = [
            dict(id='receipt', text='quasarneedle', source_types=['feedback'])]
        grouped = execute()
        self.assertEqual(grouped['outputs']['evidence']['questions'][0]['status'], 'candidates_retained')
        self.assertEqual(grouped['execution']['cache_hits'], 0)
        self.assertEqual(execute()['execution']['cache_hits'], 1)


if __name__ == '__main__':
    unittest.main()
