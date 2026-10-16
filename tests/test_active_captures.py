import json
from pathlib import Path
import tempfile
import unittest

from tracker.active_captures import snapshot
from tracker import monitoring
from tracker.portable import chat_document
from tracker.schema import InputError
from tracker.store import Store


def document(*, task='task-1', environment='sim', text='latest prefix'):
    messages = [
        {'role': 'user', 'content': 'Please inspect the state.'},
        {'role': 'assistant', 'content': 'I am checking.' if text else ''},
        {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'call-1', 'type': 'function',
             'function': {'name': 'read_state', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'State is ready.'},
        {'role': 'assistant', 'content': text},
    ]
    return chat_document(messages, metadata={
        'experiment': 'exp-a', 'environment': environment, 'task_id': task,
    })


class ActiveCaptureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / 'store.sqlite')

    def ingest(self, rollout_id, revision=0, state='in_progress', **kwargs):
        return self.store.ingest({
            'producer': 'worker-a', 'rollout_id': rollout_id, 'revision': revision,
            'state': state, 'document': document(**kwargs),
        })

    def test_latest_prefix_has_compact_source_counts_and_bounded_excerpt(self):
        long_text = 'X' * 350
        receipt = self.ingest('active', text=long_text)
        run_id = receipt['id']
        with self.store.connect() as c:
            raw = json.loads(c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()[0])
            # These source events are explicitly marked copied context and must
            # not inflate live agent/action/feedback counts.
            raw['events'].extend([
                {'id': 'copied-action', 'actor': 'agent', 'kind': 'action', 'text': 'copy', 'copied_context': True},
                {'id': 'copied-feedback', 'actor': 'environment', 'kind': 'feedback', 'text': 'copy', 'copied_context': True},
                {'id': 'copied-message', 'actor': 'agent', 'kind': 'message', 'text': 'copy', 'copied_context': True},
            ])
            c.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(raw), run_id))

        got = snapshot(self.store)
        self.assertEqual(set(got), {'schema', 'total', 'limit', 'truncated', 'rows', 'boundary'})
        self.assertEqual(got['total'], 1)
        self.assertFalse(got['truncated'])
        row = got['rows'][0]
        self.assertEqual(set(row), {'run_id', 'producer', 'rollout_id', 'revision', 'received_at',
                                   'task_id', 'environment', 'event_count', 'action_count',
                                   'feedback_count', 'agent_text_chars', 'last_agent_text',
                                   'last_agent_event_id','semantic_observations'})
        self.assertEqual(row['run_id'], run_id)
        self.assertEqual((row['producer'], row['rollout_id'], row['revision']), ('worker-a', 'active', 0))
        self.assertEqual((row['task_id'], row['environment']), ('task-1', 'sim'))
        self.assertEqual(row['event_count'], 6)
        self.assertEqual(row['action_count'], 1)
        self.assertEqual(row['feedback_count'], 1)
        self.assertEqual(row['agent_text_chars'], len('I am checking.') + len(long_text))
        self.assertEqual(len(row['last_agent_text']), 300)
        self.assertEqual(row['last_agent_event_id'], 'e6')
        self.assertNotIn('success', row)
        self.assertNotIn('reward', row)
        self.assertNotIn('duration', row)
        self.assertNotIn('stall', row)

    def test_empty_agent_text_is_unknown_and_not_an_empty_excerpt_claim(self):
        receipt = self.ingest('empty', text='')
        got = snapshot(self.store)
        row = next(r for r in got['rows'] if r['run_id'] == receipt['id'])
        self.assertEqual(row['agent_text_chars'], 0)
        self.assertEqual(row['last_agent_text'], '')
        self.assertIsNone(row['last_agent_event_id'])

    def test_new_terminal_revision_removes_identity_from_active_count(self):
        self.ingest('complete-after-prefix', revision=0, state='in_progress')
        self.ingest('complete-after-prefix', revision=1, state='complete')
        self.ingest('failed-after-prefix', revision=0, state='in_progress')
        self.ingest('failed-after-prefix', revision=1, state='failed')
        active = self.ingest('still-active', revision=0, state='in_progress')
        got = snapshot(self.store)
        self.assertEqual(got['total'], 1)
        self.assertEqual([r['run_id'] for r in got['rows']], [active['id']])

    def test_context_filter_and_limit_apply_to_latest_logical_identities(self):
        self.ingest('one', task='t1', environment='sim')
        self.ingest('two', task='t2', environment='sim')
        self.ingest('three', task='t3', environment='other')
        filtered = snapshot(self.store, experiment='exp-a', environment='sim', limit=1)
        self.assertEqual(filtered['total'], 2)
        self.assertEqual(filtered['limit'], 1)
        self.assertTrue(filtered['truncated'])
        self.assertEqual(len(filtered['rows']), 1)
        self.assertEqual(filtered['rows'][0]['environment'], 'sim')
        self.assertEqual(snapshot(self.store, experiment='missing')['total'], 0)

    def test_unassigned_experiment_matches_missing_null_and_empty_metadata(self):
        run_ids = [self.ingest(name)['id'] for name in ('missing', 'null', 'empty')]
        with self.store.connect() as c:
            for run_id, value in zip(run_ids, ('missing', None, '')):
                raw = json.loads(c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()[0])
                if value == 'missing':
                    raw['metadata'].pop('experiment', None)
                else:
                    raw['metadata']['experiment'] = value
                c.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(raw), run_id))

        got = snapshot(self.store, experiment='__unassigned__')
        self.assertEqual(got['total'], 3)
        self.assertEqual({r['run_id'] for r in got['rows']}, set(run_ids))
        self.assertEqual(snapshot(self.store, experiment='exp-a')['total'], 0)

    def test_monitor_snapshot_exposes_active_count_then_clears_on_completion(self):
        prefix = self.ingest('monitor-transition', state='in_progress')
        with self.store.read_snapshot() as saved:
            live = monitoring._snapshot(saved)
            self.assertEqual(live['active_captures']['total'], 1)
            self.assertEqual(live['active_captures']['rows'][0]['run_id'], prefix['id'])

        self.ingest('monitor-transition', revision=1, state='complete')
        with self.store.read_snapshot() as saved:
            complete = monitoring._snapshot(saved)
            self.assertEqual(complete['active_captures']['total'], 0)
            self.assertEqual(complete['active_captures']['rows'], [])

    def test_limit_is_bounded_and_context_must_be_explicit_text(self):
        for limit in (0, 13, True):
            with self.assertRaises(InputError):
                snapshot(self.store, limit=limit)
        with self.assertRaises(InputError):
            snapshot(self.store, experiment='   ')

    def test_can_read_inside_existing_query_only_snapshot(self):
        self.ingest('inside-snapshot')
        with self.store.read_snapshot() as saved:
            got = snapshot(saved)
            self.assertEqual(got['total'], 1)

    def test_semantic_observations_are_current_snapshot_only_and_bounded(self):
        from tracker.semantic_watch import initialize_tables
        from tracker.schema import dumps
        receipt = self.ingest('many-observers')
        definition = {'label': 'fixture observer'}
        with self.store.connect() as c:
            initialize_tables(c)
            c.execute('INSERT INTO semantic_watchers VALUES (?,?,?,?)',
                ('observer', dumps(definition), '{}', '[]'))
            for index in range(5):
                worker = f'worker-{index}'
                detail = {'unit_count': index + 1, 'graph_id': f'graph-{index}'}
                c.execute('INSERT INTO semantic_watch_jobs VALUES (?,?,?,?,?,?,?)',
                    ('observer', receipt['id'], f'hash-{index}',
                     'published' if index % 2 == 0 else 'queued', dumps(detail),
                     f'2026-01-01T00:00:0{index}+00:00', f'2026-01-01T00:00:0{index}+00:00'))
                c.execute('INSERT INTO semantic_watchers VALUES (?,?,?,?)',
                    (worker, dumps({'label': f'label-{index}'}), '{}', '[]'))
                c.execute('UPDATE semantic_watch_jobs SET worker_id=? WHERE worker_id=? AND run_id=?',
                    (worker, 'observer', receipt['id']))

        row = snapshot(self.store)['rows'][0]
        observations = row['semantic_observations']
        self.assertEqual(observations['total'], 5)
        self.assertEqual(len(observations['rows']), 3)
        self.assertEqual([item['observer'] for item in observations['rows']],
            ['worker-4', 'worker-3', 'worker-2'])
        self.assertIn('graph_id', observations['rows'][0])
        self.assertNotIn('graph_id', observations['rows'][1])

    def test_observation_for_older_source_snapshot_does_not_make_current_row_ready(self):
        from tracker.semantic_watch import initialize_tables
        from tracker.schema import dumps
        older = self.ingest('revised-live-source', revision=0, state='in_progress')
        with self.store.connect() as c:
            initialize_tables(c)
            c.execute('INSERT INTO semantic_watchers VALUES (?,?,?,?)',
                ('observer', dumps({'label': 'fixture observer'}), '{}', '[]'))
            c.execute('INSERT INTO semantic_watch_jobs VALUES (?,?,?,?,?,?,?)',
                ('observer', older['id'], 'old-source-hash', 'published',
                 dumps({'unit_count': 1, 'graph_id': 'old-graph'}),
                 '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'))
        newer = self.ingest('revised-live-source', revision=1, state='in_progress', text='new prefix')
        row = snapshot(self.store)['rows'][0]
        self.assertEqual(row['run_id'], newer['id'])
        self.assertNotEqual(row['run_id'], older['id'])
        self.assertEqual(row['semantic_observations'], {'total': 0, 'rows': []})

    def test_waiting_observation_exposes_coverage_without_claiming_map_ready(self):
        from tracker.semantic_watch import initialize_tables
        from tracker.schema import dumps
        current=self.ingest('partly-observed')['id']
        with self.store.connect() as c:
            initialize_tables(c)
            c.execute('INSERT INTO semantic_watchers VALUES (?,?,?,?)',
                ('observer',dumps({'label':'Live observation'}),'{}','[]'))
            c.execute('INSERT INTO semantic_watch_jobs VALUES (?,?,?,?,?,?,?)',
                ('observer',current,'source','needs_candidates',dumps({'coverage':{
                    'selected_units':9,'selected_source_bytes':4435,'eligible_source_bytes':12532,
                    'eligible_windows':35,'basis':'internal details'},'directory':'private/local/path',
                    'waiting_candidates':{'missing_responses':13}}),
                    '2026-01-01','2026-01-01'))
        observation=snapshot(self.store)['rows'][0]['semantic_observations']['rows'][0]
        self.assertEqual(observation['annotation_progress'],{
            'selected_units':9,'selected_source_bytes':4435,'eligible_source_bytes':12532})
        self.assertNotIn('graph_id',observation)
        self.assertNotIn('directory',observation)
        self.assertEqual(observation['pending_proposals'],13)


if __name__ == '__main__':
    unittest.main()
