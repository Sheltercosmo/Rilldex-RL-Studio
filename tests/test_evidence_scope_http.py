"""Native history findings agree between persisted analysis and the HTTP API."""
import json
import unittest
from urllib.request import Request, urlopen

from tracker import graph_store, investigation_plans
from tracker.schema import digest
from test_generation_cohort_transport import GenerationCohortTransportTests
from test_history_evidence import source, body, query


class EvidenceScopeHTTPTests(unittest.TestCase):
    setUp = GenerationCohortTransportTests.setUp
    start_server = GenerationCohortTransportTests.start_server
    stop_server = staticmethod(GenerationCohortTransportTests.stop_server)

    def test_local_and_http_history_keep_session_specific_results_and_cache(self):
        run = source([('lookup', {'account': 'A'}, body(True)),
                      ('use', {'account': 'A', 'ids': ['x']}, None),
                      ('lookup', {'account': 'A'}, body(False)),
                      ('use', {'account': 'A', 'ids': ['x']}, None)])
        run.update(adapter='authored-session-control', outcome={}, sources=[], warnings=[], raw={})
        for event in run['events']:
            event['context_id'] = 'first' if event['index'] < 2 else 'second'
            if event.get('tool') == 'lookup': event['call_id'] = 'lookup'
            if event['kind'] == 'feedback': event['source_call_id'] = 'lookup'
        self.store.add([run])
        plan = dict(schema='investigation-plan/1', nodes=[dict(name='history', op='history_evidence', inputs=[],
            params=dict(run_id=run['id'], source_hash=digest(run), query=query()))])
        local = investigation_plans.execute(self.store, plan)
        result = local['outputs']['history']
        self.assertEqual([r['value'] for r in result['observations']], [None, False])
        self.assertEqual(result['metrics'], dict(opportunities=2, denominator=1, numerator=0, unknown=1, value=0.0))
        graph = graph_store.read(self.store, result['graph_id'])
        self.assertEqual({(e['source'], e['target']) for e in graph['edges'] if e['type']=='response_to'},
                         {('event:e2', 'event:e1'), ('event:e5', 'event:e4')})
        endpoint = self.start_server()
        request = Request(endpoint+'/api/investigation-plans', data=json.dumps(plan).encode(),
                          headers={'Content-Type':'application/json'})
        with urlopen(request, timeout=15) as response:
            remote = json.load(response)
        self.assertEqual(remote['outputs'], local['outputs'])
        self.assertEqual(remote['execution']['cache_hits'], 1)


if __name__ == '__main__':
    unittest.main()
