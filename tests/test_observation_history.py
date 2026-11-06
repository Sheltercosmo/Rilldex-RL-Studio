"""Exact saved readings stay usable across worker resume and graph layers."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import entity_occurrences, local_frames, reference_resolution
from tracker.activity import ActivityClient
from tracker.entity_extraction import EntityClient
from tracker.jobs import Worker
from tracker.jev import JevClient
from tracker.observation_history import select
from tracker.schema import digest, dumps
from tracker.unit_graph import RelationClient, build as build_graph
from tests.test_entity_occurrences import prepared_store, occurrence_transport
from tests.test_reference_resolution import fixture as reference_fixture
from tests.test_tracker import response_for


def obsolete(saved):
    old = deepcopy(saved)
    old['_provenance']['packet_hash'] = 'old-context-' + digest(saved)
    old['_provenance']['request_hash'] = 'old-request-' + digest(saved)
    return old


class ObservationHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store, self.run = prepared_store(Path(directory.name) / 'study.sqlite')

    def shadow(self, table):
        with self.store.connect() as connection:
            rows = connection.execute(f'SELECT * FROM {table} WHERE run_id=? ORDER BY created_at,rowid', (self.run['id'],)).fetchall()
            for row in rows:
                old = obsolete(json.loads(row['result']))
                p = old['_provenance']
                connection.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?,?,?)',
                    (row['run_id'], row['event_id'], p['harness'], p['model'], p['packet_hash'],
                     dumps(old), datetime.now(timezone.utc).isoformat()))
        return len(rows)

    def run_worker(self, client, **options):
        worker = Worker(self.store, autostart=False, client=client, **options)
        try:
            job = worker.submit(self.run['id'])
            worker._process(worker._claim())
            with self.store.connect() as connection:
                row = dict(connection.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone())
            self.assertEqual(row['status'], 'complete', row['error'])
            return row
        finally:
            worker.close()

    def test_current_activity_fields_and_relations_survive_newer_obsolete_records(self):
        self.run_worker(RelationClient(transport=response_for), relations=True)
        before = self.store.get(self.run['id'], raw=True)
        for table in ('activity_observations', 'entity_observations', 'relation_observations'):
            self.assertGreater(self.shadow(table), 0)
        with patch.object(JevClient, '_post', side_effect=AssertionError('No model calls on read')):
            after = self.store.get(self.run['id'], raw=True)
        self.assertEqual(after['activity'], before['activity'])
        self.assertEqual(after['unit_graph']['coverage'], before['unit_graph']['coverage'])
        self.assertEqual(after['unit_graph']['edges'], before['unit_graph']['edges'])
        for node, original in zip(after['unit_graph']['nodes'], before['unit_graph']['nodes']):
            self.assertEqual(node['relation_status'], original['relation_status'])
            self.assertEqual(node['entity_extraction']['extraction_status'], original['entity_extraction']['extraction_status'])
        self.assertEqual(len(after['activity_observation_history']), 2 * len(before['activity_observation_history']))
        def unexpected(request):
            raise AssertionError('Exact saved request should be reused')
        for client, options in ((ActivityClient(transport=unexpected), {'activity': True}),
                                (EntityClient(transport=unexpected), {'entities': True}),
                                (RelationClient(transport=unexpected), {'relations': True})):
            self.assertEqual(self.run_worker(client, **options)['total'], 0)

    def test_occurrence_projection_reuses_complete_evidence(self):
        self.run_worker(entity_occurrences.OccurrenceClient(transport=occurrence_transport), occurrences=True)
        before = self.store.get(self.run['id'], raw=True)
        self.assertGreater(before['unit_graph']['coverage']['occurrence_observed_units'], 0)
        self.assertGreater(self.shadow('occurrence_observations'), 0)
        after = self.store.get(self.run['id'], raw=True)
        self.assertEqual(after['unit_graph']['coverage'], before['unit_graph']['coverage'])
        for a, b in zip(after['unit_graph']['nodes'], before['unit_graph']['nodes']):
            self.assertEqual(a['entity_occurrences']['fields'], b['entity_occurrences']['fields'])

    def test_reference_projection_reuses_complete_evidence(self):
        run, nodes = reference_fixture()
        saved = reference_resolution.ReferenceClient(nodes=nodes, transport=response_for).evaluate(run, 'u4')
        graph = {'nodes': deepcopy(nodes), 'coverage': {}, 'pipeline': {}, 'edges': [], 'entities': []}
        reference_resolution.project_graph(run, graph, [{'event_id': 'u4', 'result': saved}])
        before = deepcopy(graph)
        reference_resolution.project_graph(run, graph, [{'event_id': 'u4', 'result': saved}, {'event_id': 'u4', 'result': obsolete(saved)}])
        self.assertEqual(graph['reference_links'], before['reference_links'])
        self.assertEqual(graph['coverage'], before['coverage'])
        self.assertEqual(graph['nodes'][3]['reference_resolution']['status'], 'observed')

    def test_frame_projection_and_partial_selection_keep_the_current_source(self):
        activity = self.store.get(self.run['id'])['activity']
        uid = next(u['id'] for u in activity['units'] if u['eligible'])
        def local_transport(request):
            response = response_for(request)
            for key, answer in response['answers'].items():
                if request['state']['stage'] == 'field_presence':
                    value = 'local_expression' if key == 'plan__intended_operation' else 'no_local_expression'
                else:
                    value = max(request['state']['candidates'], key=lambda c: len(c.get('text', '')))['id']
                answer['probabilities'] = {choice: float(choice == value) for choice in answer['probabilities']}
            return response
        fields = EntityClient(activity=activity, transport=local_transport).evaluate(self.run, uid)
        graph = build_graph(self.run, activity, entity_observations={uid: fields})
        node = next(n for n in graph['nodes'] if n['id'] == uid)
        client = local_frames.FrameClient(nodes=graph['nodes'], transport=response_for)
        saved = client.evaluate(self.run, node['id'])
        self.assertTrue(client.cache_matches(saved, self.run, node['id']))
        records = [{'event_id': node['id'], 'result': saved}]
        local_frames.project_graph(self.run, graph, records)
        before = deepcopy(node['local_frames'])
        local_frames.project_graph(self.run, graph, [*records, {'event_id': node['id'], 'result': obsolete(saved)}])
        self.assertEqual(node['local_frames']['status'], 'observed')
        self.assertEqual(node['local_frames']['frames'], before['frames'])
        partial = deepcopy(saved)
        partial['_provenance']['completion'] = 'awaiting_arguments'
        partial['_arguments'] = {}
        self.assertTrue(client.heads_match(partial, self.run, node['id']))
        chosen = select([partial, obsolete(saved)], self.run, node['id'], lambda model: client, partial='heads_match')
        self.assertEqual(chosen, partial)
        self.assertFalse(client.cache_matches(chosen, self.run, node['id']))
        other = local_frames.FrameClient(nodes=graph['nodes'], model='jev-other-pinned',
            transport=lambda request: {**response_for(request), 'model': request['model']}).evaluate(self.run, node['id'])
        other['_provenance']['completion'] = 'awaiting_arguments'
        other['_arguments'] = {}
        chosen = select([saved, other], self.run, node['id'],
            lambda model: local_frames.FrameClient(nodes=graph['nodes'], model=model), partial='heads_match')
        self.assertEqual(chosen, other, 'A new model partial reading must not silently revert to a different model')


if __name__ == '__main__':
    unittest.main()
