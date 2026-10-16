"""Deterministic population-accounting scenarios; no model or paid API calls."""
from pathlib import Path
import tempfile
import unittest

from tracker import generation_cohorts, monitor_comparisons, monitoring
from tracker.portable import chat_document
from tracker.store import Store


EXPERIMENT = 'async-cohort-investigation'
BASELINE = range(0, 32)
CURRENT = range(32, 64)


def cohort_row(index, revision, *, terminal=False):
    members = []
    for task, env in [('regression', 'regression-env'), ('control', 'control-env')]:
        for offset in range(8):
            late = task == 'control' and offset >= 6
            state = 'completed' if terminal or not late else 'admitted'
            members.append({'producer': 'generator', 'rollout_id': f'run-{index:02d}-{task}-{offset}',
                'generation_state': state,
                'context': {'task_id': task, 'environment': env, 'environment_version': 'v1'}})
    return {'id': f'cohort-{index:02d}', 'revision': revision, 'label': f'scheduled batch {index}',
        'coordinate': {'clock': 'generation', 'basis': 'batch index', 'index': index},
        'context': {'split': 'train', 'environment_version': 'v1'},
        'sealed': terminal, 'members': members, 'evidence': 'authored deterministic scheduler manifest'}


def success_for(index, task, offset):
    current = index in CURRENT
    if task == 'regression':
        # Six of eight baseline successes versus two of eight current successes.
        return offset < (2 if current else 6)
    # Early arrivals are 2/6; the two late successes lift eventual coverage to 4/8.
    return offset < 2 or offset >= 6


class GenerationCohortInvestigationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = Store(self.root / 'workspace.sqlite')

    def receive_cohorts(self, rows):
        return generation_cohorts.receive(self.store, {'schema': generation_cohorts.VERSION,
            'producer': 'scheduler', 'experiment': EXPERIMENT, 'cohorts': rows})

    def ingest_source(self, index, task, offset):
        environment = 'regression-env' if task == 'regression' else 'control-env'
        metadata = {'experiment': EXPERIMENT, 'training_clock': 'generation',
            'training_step_basis': 'batch index', 'training_step': index,
            'split': 'train', 'environment': environment, 'environment_version': 'v1',
            'task_id': task}
        document = chat_document([
            {'role': 'user', 'content': f'Prompt {index}-{task}-{offset}'},
            {'role': 'assistant', 'content': 'Recorded answer'}], metadata=metadata,
            success=success_for(index, task, offset))
        return self.store.ingest({'producer': 'generator', 'rollout_id': f'run-{index:02d}-{task}-{offset}',
            'revision': 0, 'state': 'complete', 'document': document})

    def ingest_early_sources(self):
        count = 0
        for index in range(64):
            for task in ('regression', 'control'):
                available = range(8) if task == 'regression' else range(6)
                for offset in available:
                    self.ingest_source(index, task, offset); count += 1
        return count

    def ingest_late_sources(self):
        count = 0
        for index in range(64):
            for offset in (6, 7):
                self.ingest_source(index, 'control', offset); count += 1
        return count

    def test_async_64_cohort_denominator_regression_control_and_frozen_comparison(self):
        monitor = monitoring.create(self.store, {'name': 'Recorded success', 'kind': 'metric',
            'observer': 'source', 'metric': 'recorded_success',
            'population': {'experiment': EXPERIMENT}})
        initial = [cohort_row(index, 0) for index in range(64)]
        self.assertEqual(self.receive_cohorts(initial)['inserted'], 64)
        self.assertEqual(self.ingest_early_sources(), 896)
        monitoring.sync(self.store)

        early = generation_cohorts.snapshot(self.store, experiment=EXPERIMENT,
            monitor=monitor['id'], windows={'baseline': [0, 31], 'current': [32, 63]})
        self.assertEqual(len(early['cohorts']), 64)
        self.assertEqual(sum(c['declared'] for c in early['cohorts']), 1024)
        self.assertEqual(sum(c['delivered'] for c in early['cohorts']), 896)
        self.assertTrue(all(c['declared'] == 16 for c in early['cohorts']))
        self.assertTrue(all(c['measurement_coverage'] == 14 / 16 for c in early['cohorts']))
        self.assertEqual(early['distinct_declared_rollouts'], 1024)

        saved = monitor_comparisons.save(self.store, monitor['id'], experiment=EXPERIMENT,
            baseline=[0, 31], current=[32, 63])
        self.assertEqual(saved['population']['selected'], 896)
        self.assertEqual(sum(c['declared'] for c in saved['declared_populations']['cohorts']), 1024)
        by_environment = {c['cohort']['environment']: c for c in saved['cohorts']}
        self.assertAlmostEqual(by_environment['regression-env']['baseline']['value'], .75)
        self.assertAlmostEqual(by_environment['regression-env']['current']['value'], .25)
        self.assertAlmostEqual(by_environment['control-env']['baseline']['value'], 2 / 6)
        self.assertAlmostEqual(by_environment['control-env']['current']['value'], 2 / 6)
        # The source chart is 100% covered among delivered traces; scheduler
        # membership shows the separate 14/16 declared-member coverage.
        self.assertEqual(by_environment['control-env']['baseline']['coverage'], 1)
        self.assertTrue(all(c['measurement_coverage'] == 14 / 16
            for c in saved['declared_populations']['cohorts']))

        final = [cohort_row(index, 1, terminal=True) for index in range(64)]
        self.assertEqual(self.receive_cohorts(final)['inserted'], 64)
        # Duplicate and reverse-order delivery is accepted without displacing revision 1.
        self.assertEqual(self.receive_cohorts(initial)['inserted'], 0)
        self.assertEqual(self.ingest_late_sources(), 128)
        self.assertEqual(monitoring.sync(self.store)['errors'], 0)

        complete = generation_cohorts.snapshot(self.store, experiment=EXPERIMENT,
            monitor=monitor['id'], windows={'baseline': [0, 31], 'current': [32, 63]})
        self.assertEqual(len(complete['cohorts']), 64)
        self.assertEqual(sum(c['declared'] for c in complete['cohorts']), 1024)
        self.assertEqual(sum(c['delivered'] for c in complete['cohorts']), 1024)
        self.assertTrue(all(c['sealed'] and c['generation_settled'] for c in complete['cohorts']))
        self.assertTrue(all(c['measurement_coverage'] == 1 for c in complete['cohorts']))
        by_environment_after = {c['cohort']['environment']: c for c in
            monitor_comparisons.capture(self.store, monitor['id'], experiment=EXPERIMENT,
                baseline=[0, 31], current=[32, 63])['cohorts']}
        self.assertAlmostEqual(by_environment_after['control-env']['baseline']['value'], .5)
        self.assertAlmostEqual(by_environment_after['control-env']['current']['value'], .5)
        self.assertLess(by_environment_after['regression-env']['current']['value'],
            by_environment_after['regression-env']['baseline']['value'])
        self.assertEqual(monitor_comparisons.read(self.store, saved['id']), saved)
        self.assertAlmostEqual(by_environment['control-env']['baseline']['value'], 2 / 6)
        with self.store.connect() as c:
            latest = c.execute("SELECT max(revision) FROM generation_cohorts WHERE cohort_id='cohort-00'").fetchone()[0]
        self.assertEqual(latest, 1)

    def test_clock_alignment_keeps_source_charts_independent(self):
        rows = [{'producer': 'generator', 'rollout_id': rid, 'generation_state': 'completed',
            'context': {'environment': 'terminal', 'environment_version': 'v1'}}
            for rid in ('other-clock', 'wrong-index', 'matching-clock')]
        cohort = {'id': 'clock-cohort', 'revision': 0, 'label': 'Clock boundary',
            'coordinate': {'clock': 'generation', 'basis': 'batch index', 'index': 4},
            'context': {'environment': 'terminal', 'environment_version': 'v1'},
            'sealed': True, 'members': rows, 'evidence': 'clock contract fixture'}
        generation_cohorts.receive(self.store, {'schema': generation_cohorts.VERSION,
            'producer': 'scheduler', 'experiment': 'clock-exp', 'cohorts': [cohort]})
        cases = {
            'other-clock': ('learner', 'optimizer step', 4),
            'wrong-index': ('generation', 'batch index', 5),
            'matching-clock': ('generation', 'batch index', 4),
        }
        for rid, (clock, basis, step) in cases.items():
            self.store.ingest({'producer': 'generator', 'rollout_id': rid, 'revision': 0, 'state': 'complete',
                'document': chat_document([{'role': 'user', 'content': 'Q'}, {'role': 'assistant', 'content': 'A'}],
                    metadata={'experiment': 'clock-exp', 'environment': 'terminal', 'environment_version': 'v1',
                        'training_clock': clock, 'training_step_basis': basis, 'training_step': step})})
        result = generation_cohorts.snapshot(self.store, experiment='clock-exp', include_members=True)
        members = {m['rollout_id']: m for m in result['cohorts'][0]['members']}
        self.assertEqual(members['other-clock']['coordinate_alignment'], 'different_clock')
        self.assertEqual(members['other-clock']['source_status'], 'delivered')
        self.assertEqual(members['wrong-index']['coordinate_alignment'], 'conflicting')
        self.assertEqual(members['wrong-index']['source_status'], 'conflicting_context')
        self.assertEqual(members['matching-clock']['coordinate_alignment'], 'matching')

    def test_environment_subset_cannot_settle_pending_members_elsewhere(self):
        row = {'id': 'multi-env', 'revision': 0, 'label': 'Mixed environment',
            'coordinate': {'clock': 'generation', 'basis': 'batch index', 'index': 0},
            'context': {}, 'sealed': True,
            'members': [
                {'producer': 'generator', 'rollout_id': 'ready', 'generation_state': 'completed',
                    'context': {'environment': 'ready-env'}},
                {'producer': 'generator', 'rollout_id': 'pending', 'generation_state': 'admitted',
                    'context': {'environment': 'pending-env'}}],
            'evidence': 'environment subset fixture'}
        generation_cohorts.receive(self.store, {'schema': generation_cohorts.VERSION,
            'producer': 'scheduler', 'experiment': 'subset-exp', 'cohorts': [row]})
        result = generation_cohorts.snapshot(self.store, experiment='subset-exp', environment='ready-env')
        cohort = result['cohorts'][0]
        self.assertEqual(cohort['declared'], 1)
        self.assertEqual(cohort['whole_cohort_declared'], 2)
        self.assertEqual(cohort['whole_cohort_pending'], 1)
        self.assertTrue(cohort['selected_generation_settled'])
        self.assertFalse(cohort['generation_settled'])

    def test_project_limit_is_bounded_and_windows_filter_before_limit(self):
        rows = []
        for index in range(105):
            rows.append({'id': f'empty-{index:03d}', 'revision': 0, 'label': 'empty',
                'coordinate': {'clock': 'generation', 'basis': 'batch', 'index': index},
                'context': {}, 'sealed': True, 'members': [], 'evidence': 'empty scheduled cohort'})
        for batch in (rows[:100], rows[100:]):
            self.receive_cohorts(batch)
        first = generation_cohorts.snapshot(self.store, experiment=EXPERIMENT, limit=100)
        self.assertEqual(len(first['cohorts']), 100)
        self.assertTrue(first['truncated'])
        filtered = generation_cohorts.snapshot(self.store, experiment=EXPERIMENT,
            windows={'only-one': [0, 0]}, limit=1)
        self.assertEqual([row['id'] for row in filtered['cohorts']], ['empty-000'])
        self.assertFalse(filtered['truncated'])

    def test_overlapping_cohorts_count_distinct_delivery_once(self):
        shared = {'producer': 'generator', 'rollout_id': 'overlap-shared',
            'generation_state': 'completed', 'context': {'environment': 'shared-env'}}
        only_a = {'producer': 'generator', 'rollout_id': 'only-a',
            'generation_state': 'completed', 'context': {'environment': 'shared-env'}}
        rows = []
        for name, members in [('overlap-a', [shared, only_a]), ('overlap-b', [shared])]:
            rows.append({'id': name, 'revision': 0, 'label': name,
                'coordinate': {'clock': 'generation', 'basis': 'batch', 'index': 9},
                'context': {}, 'sealed': True, 'members': members, 'evidence': 'overlap fixture'})
        self.receive_cohorts(rows)
        for rollout_id in ('overlap-shared', 'only-a'):
            metadata = {'experiment': EXPERIMENT, 'training_clock': 'generation',
                'training_step_basis': 'batch', 'training_step': 9, 'environment': 'shared-env'}
            self.store.ingest({'producer': 'generator', 'rollout_id': rollout_id,
                'revision': 0, 'state': 'complete', 'document': chat_document(
                    [{'role': 'user', 'content': 'Q'}, {'role': 'assistant', 'content': 'A'}], metadata=metadata)})
        result = generation_cohorts.snapshot(self.store, experiment=EXPERIMENT)
        self.assertEqual(sum(row['declared'] for row in result['cohorts']), 3)
        self.assertEqual(sum(row['delivered'] for row in result['cohorts']), 3)
        self.assertEqual(result['distinct_declared_rollouts'], 2)
        self.assertEqual(result['distinct_delivered_rollouts'], 2)
        self.assertEqual(result['overlapping_members'], 1)

    def test_incomplete_capture_is_not_measured_and_complete_unsynced_capture_is_pending(self):
        self.receive_cohorts([{'id': 'measure-state', 'revision': 0, 'label': 'measure states',
            'coordinate': {'clock': 'generation', 'basis': 'batch', 'index': 0},
            'context': {}, 'sealed': True, 'members': [
                {'producer': 'generator', 'rollout_id': 'incomplete', 'generation_state': 'completed', 'context': {}},
                {'producer': 'generator', 'rollout_id': 'complete-pending', 'generation_state': 'completed', 'context': {}}],
            'evidence': 'capture-state fixture'}])
        for rollout_id, state in [('incomplete', 'in_progress'), ('complete-pending', 'complete')]:
            metadata = {'experiment': EXPERIMENT, 'training_clock': 'generation',
                'training_step_basis': 'batch', 'training_step': 0}
            self.store.ingest({'producer': 'generator', 'rollout_id': rollout_id,
                'revision': 0, 'state': state, 'document': chat_document(
                    [{'role': 'user', 'content': 'Q'}, {'role': 'assistant', 'content': 'A'}],
                    metadata=metadata, success=True)})
        monitor = monitoring.create(self.store, {'name': 'Source success', 'kind': 'metric',
            'observer': 'source', 'metric': 'recorded_success', 'population': {'experiment': EXPERIMENT}})
        snapshot = generation_cohorts.snapshot(self.store, experiment=EXPERIMENT,
            monitor=monitor['id'], include_members=True)
        cases = {case['rollout_id']: case for case in snapshot['cohorts'][0]['members']}
        self.assertEqual(cases['incomplete']['measurement_status'], 'capture_incomplete')
        self.assertIsNone(cases['incomplete']['measurement'])
        self.assertIsNone(cases['incomplete']['outcome']['verified_success'])
        self.assertEqual(cases['complete-pending']['measurement_status'], 'pending')
        self.assertIsNone(cases['complete-pending']['measurement'])
        self.assertEqual(snapshot['cohorts'][0]['measured'], 0)

    def test_version_two_saved_comparison_remains_readable(self):
        from tracker.schema import digest, dumps
        payload = {'schema': 'monitor-comparison/2', 'captured_at': '2025-01-01T00:00:00+00:00',
            'monitor': {'id': 'legacy-monitor'}, 'scope': {'experiment': EXPERIMENT},
            'cohorts': [], 'mix': {'available': False}}
        identifier = 'comparison-' + digest(payload)
        legacy = {'id': identifier, **payload}
        with self.store.connect() as connection:
            connection.execute('INSERT INTO monitor_comparisons VALUES (?,?,?)',
                (identifier, dumps(legacy), legacy['captured_at']))
        self.assertEqual(monitor_comparisons.read(self.store, identifier), legacy)

    def test_many_windows_fail_before_sql_and_missing_members_do_not_borrow_chart_clocks(self):
        from tracker.schema import InputError
        with self.assertRaisesRegex(InputError,'1–32'):
            generation_cohorts.snapshot(self.store,experiment=EXPERIMENT,windows={str(i):[i,i] for i in range(33)})
        monitor=monitoring.create(self.store,{'name':'Success','kind':'metric','observer':'source','metric':'recorded_success'})
        self.ingest_source(0,'regression',0)
        missing=cohort_row(1,0);missing['coordinate'].update(clock='learner',basis='optimizer')
        self.receive_cohorts([missing])
        comparison=monitor_comparisons.capture(self.store,monitor['id'],experiment=EXPERIMENT,baseline=[0,0],current=[1,1])
        self.assertEqual(comparison['declared_population_alignment'][0]['status'],'unverified_clock')
        self.assertEqual(comparison['declared_population_alignment'][0]['members_in_source_windows'],0)
        self.assertEqual(comparison['review'][0]['title'],'Declared work is not fully represented')

    def test_cohort_only_changes_refresh_live_state_and_are_selectable_before_traces(self):
        from tracker.connections import Service
        from test_connections import MonitorStub
        service=Service(self.store,MonitorStub());self.addCleanup(service.close)
        before=service.snapshot();self.receive_cohorts([cohort_row(0,0)]);after=service.snapshot()
        self.assertNotEqual(before['cohort_revision'],after['cohort_revision'])
        self.assertEqual(before['source_revision'],after['source_revision'])
        state=monitoring.snapshot(self.store,experiment=EXPERIMENT)
        self.assertIn({'id':EXPERIMENT,'count':0},state['experiments'])
        self.assertTrue(state['declared_populations']['available'])


if __name__ == '__main__':
    unittest.main()
