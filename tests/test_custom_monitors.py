import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker.store import Store
from tracker.workspace_analysis import Workspace
from tracker import graph_store, monitoring
from test_tracker import harbor


class CustomMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'live.sqlite'
        self.store = Store(self.path)
        self.workspace = Workspace(self.path, experiment='train', observer='review')

    def add_run(self, name='r1', step=1, experiment='train'):
        run = normalize(harbor(), 'harbor', {'experiment': experiment, 'training_step': step})[0]
        # Keep fixture run IDs distinct without changing their normalized shape.
        run['id'] = 'run-' + name
        self.store.add([run])
        source = graph_store.build(run)
        semantic = graph_store.build(run, {
            'document': {'source_hash': digest(run), 'units': [], 'relations': []},
            'observer': {'id': 'review', 'label': 'Reviewed fixture'},
        })
        with self.store.connect() as c:
            graph_store.save(c, source)
            graph_store.save(c, semantic)
        return run, source, semantic

    def make_monitor(self, *, aggregation='opportunity_ratio', unit='fraction'):
        return self.workspace.monitor('Custom score', version='code/1',
            description='A custom test measure.', aggregation=aggregation, unit=unit,
            config={'cutoff': 3})

    def snapshot_monitor(self, monitor):
        return next(row for row in monitoring.snapshot(self.store)['monitors'] if row['id'] == monitor.id)

    def test_callback_publishes_ui_cases_and_pooled_ratio(self):
        a, _, _ = self.add_run('a', 1)
        b, _, _ = self.add_run('b', 1)
        monitor = self.make_monitor()
        calls = []

        def callback(context):
            calls.append((context.run['id'], context.config['cutoff'], context.graph['observer']))
            n, d = (1, 2) if context.run['id'] == a['id'] else (1, 8)
            return {'numerator': n, 'denominator': d,
                    'evidence_ids': [context.graph['nodes'][0]['id']],
                    'feedback': {'severity': 'info', 'summary': 'Inspect this result'},
                    'details': {'source': 'fixture'}, 'unknown': 1}

        counts = monitor.run(callback, dependencies={'labels': 'rev-1'})
        self.assertEqual(counts, {'published': 2, 'skipped': 0, 'waiting': 0, 'errors': 0, 'paused': False})
        self.assertEqual(len(calls), 2)
        row = self.snapshot_monitor(monitor)
        point = row['series'][0]['bins'][0]
        self.assertEqual((point['value'], point['numerator'], point['denominator']), (0.2, 2, 10))
        self.assertEqual(point['unknown_opportunities'], 2)
        cases = monitoring.cases(self.store, monitor.id)['rows']
        self.assertEqual(len(cases), 2)
        receipt = cases[0]['measurement']
        self.assertIn('details', receipt)
        self.assertEqual(receipt['feedback']['summary'], 'Inspect this result')
        self.assertEqual(receipt['status'], 'available')

    def test_restart_skips_saved_inputs_and_dependency_revision_recomputes(self):
        run, _, _ = self.add_run()
        monitor = self.make_monitor()
        calls = []

        def callback(context):
            calls.append(context.run['id'])
            revision = context.config['cutoff']
            return {'numerator': revision, 'denominator': 4, 'evidence_ids': []}

        first = monitor.run(callback, dependencies={'external': 'v1'})
        restarted = self.workspace.monitor('Custom score', version='code/1',
            description='A custom test measure.', aggregation='opportunity_ratio', unit='fraction',
            config={'cutoff': 3})
        second = restarted.run(callback, dependencies={'external': 'v1'})
        self.assertEqual(first['published'], 1)
        self.assertEqual(second['skipped'], 1)
        self.assertEqual(calls, [run['id']])
        changed = restarted.run(callback, dependencies={'external': 'v2'})
        self.assertEqual(changed['published'], 1)
        self.assertEqual(calls, [run['id'], run['id']])
        self.assertEqual(len(monitoring.cases(self.store, monitor.id)['rows']), 1)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM custom_monitor_inputs WHERE monitor_id=?',
                (monitor.id,)).fetchone()[0], 2)

    def test_manual_duplicate_publication_is_idempotent_and_conflicts_are_retained(self):
        run, source, semantic = self.add_run()
        monitor = self.make_monitor()
        body = dict(source_hash=source['source_hash'], graph_id=semantic['id'],
                    result={'numerator': 1, 'denominator': 2, 'evidence_ids': []},
                    dependencies={'external': 'same'})
        first = monitor.publish(run['id'], **body)
        duplicate = monitor.publish(run['id'], **body)
        self.assertTrue(first['inserted'])
        self.assertFalse(duplicate['inserted'])
        conflict = {**body, 'result': {'numerator': 0, 'denominator': 2, 'evidence_ids': []}}
        with self.assertRaisesRegex(InputError, 'Conflicting result'):
            monitor.publish(run['id'], **conflict)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM custom_monitor_inputs').fetchone()[0], 1)

    def test_bad_source_graph_and_evidence_are_rejected(self):
        run, source, semantic = self.add_run()
        monitor = self.make_monitor()
        common = dict(source_hash=source['source_hash'], graph_id=semantic['id'],
                      result={'numerator': 1, 'denominator': 2, 'evidence_ids': []})
        with self.assertRaisesRegex(InputError, 'current source'):
            monitor.publish(run['id'], **{**common, 'source_hash': 'stale'})
        with self.assertRaisesRegex(InputError, 'current source'):
            monitor.publish(run['id'], **{**common, 'graph_id': 'missing-graph'})
        with self.assertRaisesRegex(InputError, 'Evidence IDs'):
            monitor.publish(run['id'], **{**common,
                'result': {'numerator': 1, 'denominator': 2, 'evidence_ids': ['node-from-another-graph']}})
        outside, _, _ = self.add_run('outside', 2, experiment='other')
        with self.assertRaisesRegex(InputError, 'population'):
            monitor.publish(outside['id'], **common)

    def test_missing_and_error_results_keep_distinct_status_and_restart_behavior(self):
        run, _, _ = self.add_run()
        unavailable = self.make_monitor()
        unavailable.run(lambda _: {'value': None, 'status': 'unavailable', 'reason': 'No comparable check', 'unknown': 3})
        missing = monitoring.cases(self.store, unavailable.id)['rows'][0]['measurement']
        self.assertEqual(missing['status'], 'unavailable')
        self.assertIsNone(missing['value'])
        self.assertEqual(missing['unknown'], 3)

        failed = self.workspace.monitor('Callback error', version='code/1', description='Error semantics',
            aggregation='mean', unit='value')
        calls = []

        def raises(_):
            calls.append(1)
            raise RuntimeError('fixture failure')

        outcome = failed.run(raises)
        self.assertEqual(outcome['errors'], 1)
        receipt = monitoring.cases(self.store, failed.id)['rows'][0]['measurement']
        self.assertEqual(receipt['status'], 'error')
        self.assertIn('RuntimeError: fixture failure', receipt['reason'])
        self.assertEqual(failed.run(raises)['skipped'], 1)
        self.assertEqual(calls, [1])
        self.assertEqual(failed.run(lambda _: {'value': 2}, dependencies={'retry': '1'})['published'], 1)

    def test_invalid_values_evidence_and_result_status_are_rejected(self):
        run, source, semantic = self.add_run()
        monitor = self.make_monitor()
        base = dict(source_hash=source['source_hash'], graph_id=semantic['id'], dependencies={})
        invalid_results = [
            {'numerator': 3, 'denominator': 2},
            {'numerator': 1, 'denominator': 2, 'value': .7},
            {'value': float('nan')},
            {'value': 2},
            {'value': None},
            {'value': .5, 'status': 'unavailable'},
            {'value': None, 'status': 'available'},
            {'value': None, 'status': 'error'},
        ]
        for result in invalid_results:
            with self.subTest(result=result), self.assertRaises(InputError):
                monitor.publish(run['id'], **base, result=result)

    def test_new_graph_version_makes_old_receipt_wait_for_current_observation(self):
        run, source, semantic = self.add_run()
        monitor = self.make_monitor()
        monitor.publish(run['id'], source_hash=source['source_hash'], graph_id=semantic['id'],
            result={'numerator': 1, 'denominator': 2, 'evidence_ids': []})
        monitoring.sync(self.store,monitor_ids={monitor.id})
        original=monitoring.cases(self.store,monitor.id)['rows'][0]['measurement']
        self.assertEqual(original['value'],.5)
        from tracker.monitor_evidence import read
        self.assertTrue(read(self.store,original['id'])['freshness']['current_measurement'])
        # Publish another immutable graph version for the selected observer.
        updated = graph_store.build(run, {
            'document': {'source_hash': digest(run), 'units': [], 'relations': [], 'annotation': 'new'},
            'observer': {'id': 'review', 'label': 'Reviewed fixture'},
        })
        with self.store.connect() as c:
            graph_store.save(c, updated)
        row = self.snapshot_monitor(monitor)
        self.assertEqual(row['coverage']['unknown'], 1)
        self.assertIsNone(row['series'][0]['points'][0]['value'])
        self.assertEqual(row['series'][0]['points'][0]['status'], 'pending')
        historical=read(self.store,original['id'])
        self.assertEqual(historical['graph']['id'],semantic['id'])
        self.assertEqual(historical['explanation']['basis'],'custom_code')
        self.assertFalse(historical['freshness']['current_input'])
        self.assertFalse(historical['freshness']['current_measurement'])

    def test_feedback_native_sql_and_invalid_callback_evidence_are_isolated(self):
        self.add_run('a');self.add_run('b')
        monitor=self.make_monitor(aggregation='mean',unit='value')
        def callback(ctx):
            if ctx.run['id']=='run-a':return {'value':1,'evidence_ids':['nonexistent']}
            return {'value':2,'feedback':{'severity':'warning','summary':'Review this','next_check':'Inspect response'},'details':{'tool':'inspect'}}
        result=monitor.run(callback)
        self.assertEqual(result['errors'],1)
        self.assertEqual(result['published'],2)
        rows=self.workspace.sql('SELECT status,feedback_summary,result_details_json FROM monitor_values WHERE is_latest=1 AND monitor_id=?',[monitor.id]).rows
        self.assertEqual({r['status'] for r in rows},{'error','available'})
        self.assertIn('Review this',[r['feedback_summary'] for r in rows])
        self.assertEqual(self.snapshot_monitor(monitor)['feedback_counts'],{'warning':1})

    def test_pause_survives_monitor_reregistration(self):
        self.add_run()
        monitor = self.make_monitor()
        monitor.run(lambda _: {'numerator': 1, 'denominator': 2})
        monitoring.enabled(self.store, monitor.id, False)
        restored = self.workspace.monitor('Custom score', version='code/1',
            description='A custom test measure.', aggregation='opportunity_ratio', unit='fraction',
            config={'cutoff': 3})
        self.assertEqual(restored.id, monitor.id)
        result = restored.run(lambda _: self.fail('paused callback ran'))
        self.assertTrue(result['paused'])
        self.assertFalse(next(d for d in monitoring.definitions(self.store) if d['id'] == monitor.id)['enabled'])


if __name__ == '__main__':
    unittest.main()
