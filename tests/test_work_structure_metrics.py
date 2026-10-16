from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store, work_outline, work_structure_metrics as metrics
from tracker import analysis_metrics, investigation_plans, monitoring, monitor_evidence
from tracker.adapters import normalize
from tracker.schema import digest, InputError
from tracker.store import Store
from tracker.connections import validate as connection
from test_declared_work_tree import fixture as tree
from test_work_hierarchy import graph as plan, finish
from test_work_outline import fixture as outline


class WorkStructureMetricTests(unittest.TestCase):
    def test_plan_attempts_are_not_checks_and_shared_dispatch_counts_once(self):
        graph = plan()
        base = metrics.project(graph)
        self.assertEqual(metrics.measure(base, 'plan_steps_attempted')['value'], 1)
        self.assertEqual(metrics.measure(base, 'plan_attempt_dispatches')['value'], 1)
        self.assertEqual(base['profiles']['plan_steps']['declared'], 2)
        graph['edges'].append(dict(id='second-attempt', source='action', target='plan', type='attempts_plan_step',
                                   properties={'plan_step_id': 'b'}))
        shared = metrics.project(finish(graph))
        self.assertEqual(metrics.measure(shared, 'plan_steps_attempted')['value'], 2)
        self.assertEqual(metrics.measure(shared, 'plan_attempt_dispatches')['value'], 1)
        self.assertEqual(len(shared['cases']['plan_attempt_dispatches'][0]['work_structure']['shared_scopes']), 2)
        graph['edges'][-1]['type'] = 'checks_plan_step'
        checked = metrics.project(finish(graph))
        self.assertEqual(metrics.measure(checked, 'plan_steps_attempted')['value'], 1)

    def test_cutoff_withholds_future_attempt_and_future_decision(self):
        early = metrics.project(plan(), 'e0')
        self.assertEqual(metrics.measure(early, 'plan_steps_attempted')['value'], 0)
        run, graph, review, refs = outline()
        graph = work_outline.fork(graph, review)
        early = metrics.project(graph, refs[3]['event_id'])
        self.assertEqual(metrics.measure(early, 'work_resume_decisions')['value'], 0)
        self.assertEqual(metrics.measure(early, 'work_defer_decisions')['value'], 1)
        late = metrics.project(graph)
        self.assertEqual(metrics.measure(late, 'work_resume_decisions')['value'], 1)
        self.assertEqual(metrics.measure(late, 'work_stop_decisions')['value'], 0)
        self.assertEqual(late['profiles']['work_outline']['observed'], 0)

    def test_native_scopes_share_occurrence_without_duplicate_effort_or_parent_visit(self):
        document = tree()
        operation = next(r for r in document['declared_work_tree']['records'] if r['kind'] == 'operation')
        document['declared_work_tree']['records'].append({**deepcopy(operation), 'node_id': 'a'})
        graph = graph_store.build(normalize(document)[0])
        out = metrics.project(graph)
        self.assertEqual(metrics.measure(out, 'native_operation_requests')['value'], 1)
        self.assertEqual(metrics.measure(out, 'native_goals_visited')['value'], 3)
        rows = {r['label']: r for r in out['rows']}
        self.assertEqual(rows['Make artifact']['effort'], 1)
        self.assertEqual(rows['Build']['effort'], 1)
        self.assertEqual(rows['Build']['depth_min'], 1)
        self.assertEqual(rows['Check']['depth_min'], 1)
        plain = metrics.project(graph_store.build(normalize(tree())[0]))
        parent = next(r for r in plain['rows'] if r['label'] == 'Make artifact')
        self.assertFalse(parent['observed'])
        self.assertEqual(parent['effort'], 1)

    def test_missing_profile_is_unavailable_not_zero_and_no_cross_profile_pooling(self):
        out = metrics.project(plan())
        self.assertIsNone(metrics.measure(out, 'native_operation_requests')['value'])
        self.assertIsNone(metrics.measure(out, 'work_stop_decisions')['value'])
        native = metrics.project(graph_store.build(normalize(tree())[0]))
        self.assertIsNone(metrics.measure(native, 'plan_steps_attempted')['value'])

    def test_depth_handles_shared_ancestors_without_choosing_one_route(self):
        result = metrics.depths({'root', 'a', 'b', 'shared'},
                                {'a': {'root'}, 'b': {'a'}, 'shared': {'root', 'b'}})
        self.assertEqual(result['shared'], (1, 3))
        with self.assertRaises(InputError):
            metrics.depths({'a', 'b'}, {'a': {'b'}, 'b': {'a'}})

    def test_public_native_operations_reconcile_with_literal_source_listing(self):
        root = Path('research/nested-plan-map-2026-10-13')
        graph = json.loads((root / 'graph.json').read_text(encoding='utf-8'))
        out = metrics.project(graph)
        # Independent line-level oracle; do not use the graph converter or hierarchy.
        lines = (root / 'paper-listing.txt').read_text(encoding='utf-8').splitlines()
        requests = [line.strip() for line in lines if line.strip().startswith('Act:')
                    and line.strip()[4:].strip() not in {'done', 'failure'}]
        self.assertEqual(len(requests), 45)
        self.assertEqual(metrics.measure(out, 'native_operation_requests')['value'], len(requests))
        self.assertEqual(out['profiles']['declared_tree']['declared'], 10)
        self.assertEqual(out['profiles']['declared_tree']['observed'], 10)
        # Source reconciliation: kitchen 1 room + 1 table + 4 fridge + 16 cabinet.
        rows = {r['label']: r for r in out['rows']}
        self.assertIn(22, [r['direct_effort'] for r in rows.values()])
        self.assertIn(7, [r['direct_effort'] for r in rows.values()])
        self.assertIn(5, [r['direct_effort'] for r in rows.values()])
        self.assertEqual(max(r['depth_max'] for r in rows.values()), 3)

    def test_registered_measure_persists_cases_and_reuses_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            run = normalize(tree())[0]
            store.add([run])
            graph = graph_store.build(run)
            with store.connect() as c:
                graph_store.save(c, graph)
            monitor = monitoring.create(store, dict(name='Native branch work', kind='analysis', observer='source',
                group='Behavior', analysis={'measure': 'native_operation_requests'}))
            result = analysis_metrics.evaluate(store, monitor, graph)
            self.assertEqual(result['value'], 1)
            again = analysis_metrics.evaluate(store, monitor, graph)
            self.assertEqual(result, again)
            output = investigation_plans.read_output(store, result['analysis']['output_id'])
            self.assertEqual(output['graph_id'], graph['id'])
            with store.connect() as c:
                self.assertEqual(c.execute("SELECT count(*) FROM investigation_nodes WHERE operation='work_structure'").fetchone()[0], 1)
            other = monitoring.create(store, dict(name='Visited goals', kind='analysis', observer='source',
                group='Behavior', analysis={'measure': 'native_goals_visited'}))
            monitoring.sync(store)
            value = monitoring.values(store, monitor['id'], {run['id']})[run['id']]
            receipt = monitor_evidence.read(store, value['id'])
            self.assertEqual(receipt['measurement']['value'], 1)
            self.assertEqual(receipt['explanation']['analysis_cases'][0]['work_structure']['profile'], 'declared_tree')
            self.assertEqual(monitoring.values(store, other['id'], {run['id']})[run['id']]['value'], 2)
            with store.connect() as c:
                self.assertEqual(c.execute("SELECT count(*) FROM investigation_nodes WHERE operation='work_structure'").fetchone()[0], 1)

    def test_live_revisions_and_batch_replay_match_across_transports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = [tree(), tree(), tree()]
            documents[0]['messages'] = documents[0]['messages'][:3]
            documents[0]['declared_work_tree']['records'] = documents[0]['declared_work_tree']['records'][:1]
            documents[2]['messages'].append(dict(role='assistant', content='Act: recheck'))
            documents[2]['declared_work_tree']['records'].append(dict(node_id='d', kind='operation',
                evidence=dict(event_id='e8', start=0, end=12, text='Act: recheck')))
            envelopes = [dict(producer='test/worker', rollout_id='sample', revision=i,
                state='in_progress' if i == 0 else 'complete', document=d,
                metadata=dict(experiment='authored lifecycle control', training_step=7))
                for i, d in enumerate(documents)]
            stores, watchers = {}, {}
            for mode in ('direct', 'exports', 'snapshots', 'batch'):
                stores[mode] = Store(root / (mode + '.sqlite'))
                if mode in ('exports', 'snapshots'):
                    output = root / mode
                    output.mkdir()
                    watchers[mode] = connection(stores[mode], dict(root=str(output), mode=mode,
                        producer='test/worker', metadata={'experiment': 'authored lifecycle control'}))[1]
                    self.assertEqual(watchers[mode].poll()['scanned'], 0)
            monitor_args = dict(name='Native work', kind='analysis', observer='source', group='Behavior',
                                analysis={'measure': 'native_operation_requests'})
            monitors = {mode: monitoring.create(store, monitor_args) for mode, store in stores.items()}
            old_receipts = {}
            for revision, envelope in enumerate(envelopes):
                stores['direct'].ingest(envelope)
                with (root / 'exports' / 'worker.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(envelope) + '\n')
                (root / 'snapshots' / 'sample.json').write_text(json.dumps(envelope), encoding='utf-8')
                for watcher in watchers.values():
                    self.assertEqual(watcher.poll()['ingested'], 1)
                current = []
                for mode in ('direct', 'exports', 'snapshots'):
                    store = stores[mode]
                    monitoring.sync(store)
                    runs = monitoring.population(store)
                    self.assertEqual(len(runs), 1)  # Historical revisions do not become new samples.
                    value = monitoring.values(store, monitors[mode]['id'], {runs[0]['id']})[runs[0]['id']]
                    if revision == 0:
                        self.assertEqual(value['status'], 'incomplete')
                        self.assertIsNone(value['value'])
                    else:
                        self.assertEqual(value['value'], revision)
                        receipt = monitor_evidence.read(store, value['id'])
                        self.assertEqual(len(receipt['explanation']['analysis_cases']), revision)
                        if revision == 1:
                            old_receipts[mode] = receipt
                        else:
                            earlier = monitor_evidence.read(store, old_receipts[mode]['measurement']['id'])
                            for field in ('measurement', 'graph', 'explanation'):
                                self.assertEqual(earlier[field], old_receipts[mode][field])
                    current.append(value)
                self.assertEqual(current[0], current[1])
                self.assertEqual(current[1], current[2])
            batch = connection(stores['batch'], dict(root=str(root / 'exports'), mode='exports',
                producer='test/worker', metadata={'experiment': 'authored lifecycle control'}))[1]
            self.assertEqual(batch.poll()['ingested'], 3)
            monitoring.sync(stores['batch'])
            run = monitoring.population(stores['batch'])[0]
            values = monitoring.values(stores['batch'], monitors['batch']['id'], {run['id']})
            self.assertEqual(values[run['id']], current[0])
            chart = monitoring.chart(monitors['batch'], [run], values)
            self.assertEqual(chart['series'][0]['bins'][0]['value'], 2)
            self.assertEqual(chart['series'][0]['bins'][0]['step'], 7)
            self.assertEqual(chart['coverage']['available'], 1)


if __name__ == '__main__':
    unittest.main()
