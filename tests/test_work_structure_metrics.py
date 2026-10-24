from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import graph_store, work_outline, work_structure_metrics as metrics
from tracker import analysis_metrics, investigation_plans, monitoring, monitor_evidence
from tracker.adapters import normalize
from tracker.schema import digest, InputError
from tracker.store import Store
from tracker.connections import validate as connection
from test_declared_work_tree import fixture as tree
from test_work_hierarchy import graph as plan, finish
from test_work_outline import fixture as outline


def captured_plan():
    from rilldex import chat_document
    run = normalize(chat_document([
        {'role': 'assistant', 'content': 'Create the artifact, then check it.'},
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'write', 'type': 'function',
            'function': {'name': 'shell', 'arguments': {'cmd': 'echo artifact > output.txt'}}}]},
        {'role': 'tool', 'tool_call_id': 'write', 'content': 'Exit code 0'},
        {'role': 'assistant', 'content': 'The write command returned without an error.'},
    ], metadata={'experiment': 'authored-plan-evidence', 'training_step': 1}))[0]
    events = [e for e in run['events'] if e['text']]
    binding = {'e' + str(i): e for i, e in enumerate(events)}
    def refs(value):
        if isinstance(value, list): return [refs(v) for v in value]
        if not isinstance(value, dict): return value
        result = {k: refs(v) for k, v in value.items()}
        if result.get('event_id') in binding:
            e = binding[result['event_id']]
            result['event_id'] = e['id']
            if 'text' in result:
                result.update(start=0, end=len(e['text']), text=e['text'], source_pointer=e.get('source_pointer'))
        return result
    template = plan(); graph = graph_store.build(run)
    graph.update(observer='authored-plan', observer_label='Authored plan control')
    for node in template['nodes']:
        if node['kind'] == 'event': continue
        node = refs(deepcopy(node)); e = events[node['event_index']]
        node['event_index'] = e['index']
        node['trajectory_id'] = e['trajectory_id']
        if node['kind'] == 'unit': node['properties']['actor'] = e['actor']
        graph['nodes'].append(node)
    for edge in template['edges']:
        edge = refs(deepcopy(edge))
        if edge['target'].startswith('event:'):
            edge['target'] = 'event:' + binding[edge['target'][6:]]['id']
        graph['edges'].append(edge)
    return run, finish(graph)


class WorkStructureMetricTests(unittest.TestCase):
    def test_depth_can_be_monitored_and_receipt_is_inspectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            run = normalize(tree())[0]; store.add([run])
            monitor = monitoring.create(store, dict(name='Goal depth', kind='analysis', observer='source',
                analysis={'measure':'native_goal_depth'}, alert={'operator':'ge','threshold':1,'severity':'warning'}))
            self.assertEqual(monitoring.sync(store, [monitor['id']])['errors'], 0)
            value = monitoring.values(store, monitor['id'], [run['id']])[run['id']]
            self.assertEqual(value['value'], 1)
            self.assertTrue(monitor_evidence.read(store, value['id'])['explanation']['analysis_cases'])
            from tracker.monitor_alerts import snapshot
            self.assertEqual(snapshot(store)['alerts'][0]['run_id'], run['id'])

    def test_declared_order_departure_requires_comparable_attempts(self):
        graph = plan()
        p = next(n for n in graph['nodes'] if n['id'] == 'plan')
        p['properties']['plan_structure']['links'] = [dict(kind='precedes', **{'from':'a','to':'b'},
            evidence=p['properties']['plan_structure']['steps'][0]['evidence'])]
        self.assertIsNone(metrics.measure(metrics.project(finish(graph)), 'plan_order_departures')['value'])
        # B is attempted first, A later. Source order is a recorded departure,
        # not evidence that the adaptation was wrong or that work failed.
        next(e for e in graph['edges'] if e['id']=='attempt')['properties']['plan_step_id']='b'
        event = deepcopy(next(n for n in graph['nodes'] if n['id']=='event:e1'))
        event.update(id='event:e4',event_index=4);event['properties']['id']='e4'
        action = deepcopy(next(n for n in graph['nodes'] if n['id']=='action'))
        action.update(id='later',event_index=4);action['properties']['source']['event_id']='e4'
        graph['nodes'].extend([event,action])
        graph['edges'].extend([dict(id='ground-later',source='later',target='event:e4',type='grounded_in',properties={}),
            dict(id='later-attempt',source='later',target='plan',type='attempts_plan_step',properties={'plan_step_id':'a'})])
        out = metrics.project(finish(graph))
        self.assertEqual(metrics.measure(out,'plan_order_departures')['value'],1)
        self.assertEqual(out['cases']['plan_order_departures'][0]['edge_ids'],['attempt','later-attempt'])
        self.assertIsNone(metrics.measure(metrics.project(finish(graph),'e2'),'plan_order_departures')['value'])
        event['properties']['batch_size']=2
        self.assertIsNone(metrics.measure(metrics.project(finish(graph)),'plan_order_departures')['value'])
        event['properties'].pop('batch_size')
        next(e for e in graph['edges'] if e['id']=='attempt')['properties']['plan_step_id']='a'
        next(e for e in graph['edges'] if e['id']=='later-attempt')['properties']['plan_step_id']='b'
        self.assertEqual(metrics.measure(metrics.project(finish(graph)),'plan_order_departures')['value'],0)

    def test_monitor_receipt_keeps_relationships_and_remains_readable_after_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            run, graph = captured_plan(); store.add([run])
            with store.connect() as c: graph_store.save(c, graph)
            monitor = monitoring.create(store, dict(name='Plan attempts', kind='analysis', observer='authored-plan',
                analysis={'measure': 'plan_attempt_dispatches'}))
            synced = monitoring.sync(store, [monitor['id']])
            self.assertEqual(synced['errors'], 0)
            value = monitoring.values(store, monitor['id'], [run['id']])[run['id']]
            receipt = monitor_evidence.read(store, value['id'])
            self.assertEqual(value['value'], 1)
            self.assertEqual(receipt['explanation']['analysis_cases'][0]['edge_ids'], ['attempt'])
            self.assertEqual(receipt['graph']['id'], graph['id'])
            with patch.dict(investigation_plans.OPS, {'work_structure': 'work-structure-measures/999|work-hierarchy/999'}), patch.object(
                    investigation_plans, 'execute', side_effect=AssertionError('Do not recalculate saved receipts')):
                self.assertEqual(monitor_evidence.read(store, value['id']), receipt)
            self.assertEqual(monitoring.sync(store, [monitor['id']])['inserted'], 0)

    def test_plan_measurements_retain_original_relationship_witnesses(self):
        out = metrics.project(plan())
        for key in ('plan_steps_attempted', 'plan_attempt_dispatches'):
            case = out['cases'][key][0]
            self.assertEqual(case['edge_ids'], ['attempt'])
            self.assertTrue({'action', 'plan', 'plan:a'} <= set(case['node_ids']))
        self.assertEqual(next(r for r in out['rows'] if r['id'] == 'plan:a')['edge_ids'], ['attempt'])

    def test_split_action_annotations_do_not_create_extra_dispatches(self):
        from test_work_hierarchy import split_action
        graph = split_action(plan())
        out = metrics.project(graph)
        self.assertEqual(metrics.measure(out, 'plan_attempt_dispatches')['value'], 1)
        self.assertEqual(out['profiles']['plan_steps']['distinct_effort'], 1)
        case = out['cases']['plan_attempt_dispatches'][0]
        self.assertEqual(case['edge_ids'], ['attempt', 'attempt-fragment'])
        self.assertTrue({'action', 'action-fragment', 'event:e1'} <= set(case['node_ids']))

    def test_public_plan_counts_have_complete_original_edge_witnesses(self):
        graph = json.loads(Path('research/work-path-usefulness-2026-10-15/source.json').read_text(encoding='utf-8'))['graph']
        before = deepcopy(graph)
        expected = {e['id'] for e in graph['edges'] if e['type'] == 'attempts_plan_step'}
        self.assertEqual(len(expected), 6)
        out = metrics.project(graph)
        self.assertEqual(metrics.measure(out, 'plan_attempt_dispatches')['value'], 6)
        for key in ('plan_steps_attempted', 'plan_attempt_dispatches'):
            cases = out['cases'][key]
            self.assertTrue(all(c['edge_ids'] for c in cases))
            self.assertEqual({eid for c in cases for eid in c['edge_ids']}, expected)
            for case in cases:
                for edge in graph['edges']:
                    if edge['id'] in case['edge_ids']:
                        self.assertTrue({edge['source'], edge['target']} <= set(case['node_ids']))
        self.assertEqual(graph, before)

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
