"""Action-flow projection and worker integration, not semantic accuracy estimates."""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker.action_reading import flow
from tracker.adapters import normalize
from tracker.jobs import Worker
from tracker.jev import JevClient
from tracker.schema import dumps
from tracker.store import Store
from test_tracker import harbor, response_for


class ActionFlowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'flow.sqlite')
        self.run = normalize(harbor())[0]
        self.store.add([self.run])
        self.actions = [e for e in self.run['events'] if e['kind'] == 'action' and not e.get('copied_context')]
        self.client = JevClient(transport=response_for)

    def save(self, event, *, stale=False):
        result = self.client.evaluate(self.run, event['id'])
        if stale: result['_provenance']['harness'] = 'obsolete'
        p = result['_provenance']
        self.store.record(self.run['id'], event['id'], p['harness'], p['model'], p['packet_hash'], result)

    def test_flow_preserves_unknown_and_stale_actions_without_heuristic_purpose(self):
        with patch.object(self.client, 'evaluate', side_effect=AssertionError('Flow cannot infer')):
            unread = flow(self.store, self.run['id'], client=self.client)
        self.assertEqual(unread['coverage']['uninspected'], len(self.actions))
        self.assertEqual(unread['purposes'], {'unresolved': len(self.actions)})
        self.save(self.actions[0])
        self.save(self.actions[1], stale=True)
        result = flow(self.store, self.run['id'], client=self.client)
        self.assertEqual(result['coverage'], dict(current=1,reviewed=0,outdated=1,uninspected=1,pending=2,total=3,purpose_decided=1))
        self.assertEqual(result['actions'][1]['purpose'], 'unresolved')
        self.assertEqual(result['actions'][1]['fields']['mode']['source'], 'outdated_observation')
        self.assertEqual({a['event_id'] for a in result['actions']}, {e['id'] for e in self.actions})

    def test_reviewed_purpose_is_retained_but_not_counted_as_model_coverage(self):
        with self.store.connect() as c:
            review = dict(event_id=self.actions[0]['id'], field='mode', value='verify', reviewer='Reader', note='Read the evidence', evidence_ids=[self.actions[0]['id']])
            c.execute('INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)', (self.run['id'], dumps(review), '2026-11-06T00:00:00Z'))
        result = flow(self.store, self.run['id'])
        self.assertEqual(result['coverage']['reviewed'], 1)
        self.assertEqual(result['coverage']['current'], 0)
        self.assertEqual(result['coverage']['purpose_decided'], 1)
        self.assertEqual(result['actions'][0]['purpose'], 'verify')

    def test_contexts_and_parallel_dispatches_remain_separate_and_copied_actions_are_excluded(self):
        run = deepcopy(self.run); run['id'] = 'flow-scope-control'
        seed = deepcopy(self.actions[0]); run['events'] = []
        for i, (context, parent, copied) in enumerate([('a','p',False),('a','p',False),('b','p',False),('b','q',False),('b','copy',True)]):
            run['events'].append({**deepcopy(seed),'id':f'x{i}','index':i,'context_id':context,'parent_id':parent,'source_message_index':i,'copied_context':copied})
        self.store.add([run]); result = flow(self.store, run['id'])
        self.assertEqual(result['coverage']['total'], 4)
        self.assertEqual([lane['action_ids'] for lane in result['lanes']], [['x0','x1'],['x2','x3']])
        self.assertEqual(result['actions'][0]['dispatch_group'], ['x0','x1'])
        self.assertFalse(result['actions'][0]['order_known'])
        self.assertIsNone(result['actions'][2]['same_dispatch_as'])
        self.assertEqual(result['actions'][3]['same_dispatch_as'], 'x2')

    def test_worker_progress_is_visible_before_materialized_refresh_and_resume_uses_cache(self):
        calls = []
        worker = Worker(self.store, client=self.client, max_actions=2, autostart=False)
        self.addCleanup(worker.close)
        def respond(request):
            calls.append(request['state']['cutoff_event_id'])
            if len(calls) == 2:
                during = flow(self.store, self.run['id'], client=self.client, profile=worker.profile, limit=2)
                self.assertEqual(during['job']['status'], 'running')
                self.assertEqual(during['job']['progress'], 1)
                self.assertEqual(during['coverage']['current'], 1)
            return response_for(request)
        self.client.transport = respond
        first = worker.submit(self.run['id']); worker._process(worker._claim())
        partial = flow(self.store, self.run['id'], client=self.client, profile=worker.profile, limit=2)
        self.assertEqual(partial['job']['id'], first)
        self.assertEqual(partial['job']['status'], 'partial')
        self.assertEqual(partial['coverage']['pending'], 1)
        worker.submit(self.run['id']); worker._process(worker._claim())
        complete = flow(self.store, self.run['id'], client=self.client, profile=worker.profile, limit=2)
        self.assertEqual(complete['coverage']['pending'], 0)
        self.assertEqual(complete['job']['status'], 'complete')
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(set(calls)), 3)

