"""Ordering, reference and receipt controls; no semantic-accuracy claim."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from tracker import work_return_references as refs, work_order, work_navigation
from tracker import analysis_metrics as am, investigation_plans as plans
from tracker import graph_store as gs, monitoring, monitor_evidence
from tracker.schema import InputError
from tracker.store import Store
from tests.test_parallel_work_returns import fixture, graph
from tests.test_work_return_references import query, graph as ordered_graph
from tests.test_work_route_context import edge, rehash


def example(reverse=False, gap=False, link=True):
    run, units = fixture(reverse)
    g = graph(run, units, ('A', None if gap else 'B', 'C', 'A'))
    if link:
        edge(g, units[-1]['id'], units[0]['id'], 'revises',
             cutoff=deepcopy(units[-1]['source']), basis='Authored structural control')
    return run, rehash(g), units


class ParallelReturnReferenceTests(unittest.TestCase):
    def test_complete_group_recognizes_same_return_as_map_with_one_reference(self):
        for reverse in (False, True):
            _, g, units = example(reverse)
            frozen = deepcopy(g)
            old = refs.evaluate(g, query())
            out = refs.evaluate(g, query(), recurrence_order=work_order.VERSION)
            self.assertEqual(old['value'], 0)
            self.assertNotIn('recurrence_order', old)
            self.assertEqual(out['value'], 1)
            self.assertEqual(out['coverage']['recorded_returns'],
                             work_navigation.project(g, recurrence_order=work_order.VERSION)['counts']['returned'])
            self.assertEqual(out['records'][0]['episode']['ordering']['status'], 'bracketed_parallel')
            self.assertIn(units[-1]['id'], out['records'][0]['node_ids'])
            self.assertEqual(g, frozen)
            self.assertEqual(old, refs.evaluate(g, query()))

    def test_missing_relationship_is_unestablished_and_missing_coverage_blocks_return(self):
        _, g, _ = example(link=False)
        out = refs.evaluate(g, query(), recurrence_order=work_order.VERSION)
        self.assertEqual(out['value'], 0)
        self.assertEqual(out['coverage']['recorded_returns'], 1)
        self.assertEqual(out['records'][0]['status'], 'not_established')
        _, g, _ = example(gap=True)
        out = refs.evaluate(g, query(), recurrence_order=work_order.VERSION)
        self.assertEqual(out['coverage']['recorded_returns'], 0)
        self.assertGreater(out['coverage']['unresolved_work_switches'], 0)

    def test_intervening_and_same_work_references_remain_distinct(self):
        _, g, units = example(link=False)
        edge(g, units[-1]['id'], units[1]['id'], 'uses_evidence',
             cutoff=deepcopy(units[-1]['source']), basis='Authored structural control')
        g = rehash(g)
        same = refs.evaluate(g, query(types=('uses_evidence',)), recurrence_order=work_order.VERSION)
        between = refs.evaluate(g, query('intervening_work', ('uses_evidence',)), recurrence_order=work_order.VERSION)
        self.assertEqual(same['value'], 0)
        self.assertEqual(between['value'], 1)
        self.assertEqual(len(between['records'][0]['references']), 1)

    def test_future_reference_evidence_remains_rejected(self):
        _, g, units = ordered_graph(('A', 'B', 'A', 'C'))
        link = next(e for e in g['edges'] if e['type'] == 'revises')
        link['properties']['context_evidence'] = [deepcopy(units[3]['source'])]
        out = refs.evaluate(rehash(g), query(), recurrence_order=work_order.VERSION)
        self.assertEqual(out['value'], 0)
        self.assertEqual(out['coverage']['recorded_returns'], 1)
        self.assertGreater(out['coverage']['rejected_relationships'], 0)

    def test_measure_rejects_mixed_ordering_policies(self):
        _, g, _ = example()
        old = am.definition(am.validate(dict(measure='work_return_references', query=query())))
        new = am.definition(am.validate(dict(measure='work_return_references_parallel', query=query())))
        out = refs.evaluate(g, query(), recurrence_order=work_order.VERSION, scope_consistency=new['scope_consistency'])
        self.assertEqual(am.measure(out, new)['value'], 1)
        with self.assertRaises(InputError): am.measure(out, old)
        with self.assertRaises(InputError): am.measure(refs.evaluate(g, query(), scope_consistency=new['scope_consistency']), new)
        with self.assertRaises(InputError): refs.evaluate(g, query(), recurrence_order='guess-order')

    def test_saved_positive_and_unestablished_cases_keep_policy_and_cache(self):
        for has_link in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                store = Store(Path(folder)/'test.sqlite')
                run, g, _ = example(link=has_link)
                store.add([run])
                with store.connect() as c: gs.save(c, g)
                monitors = [monitoring.create(store, dict(name=name, kind='analysis', observer=g['observer'],
                    analysis=dict(measure=measure, query=query()))) for name, measure in
                    [('Earlier rule', 'work_return_references'), ('Parallel work included', 'work_return_references_parallel')]]
                monitoring.sync(store)
                before = monitoring.values(store, monitors[0]['id'], {run['id']})[run['id']]
                value = monitoring.values(store, monitors[1]['id'], {run['id']})[run['id']]
                self.assertEqual(before['value'], 0)
                self.assertEqual(value['value'], int(has_link))
                receipt = monitor_evidence.read(store, value['id'])
                cases = receipt['explanation']['analysis_cases']
                self.assertEqual(len(cases), 1)
                self.assertEqual(cases[0]['recurrence_order'], work_order.VERSION)
                self.assertEqual(cases[0]['taken'], True if has_link else None)
                self.assertEqual(receipt['explanation']['coverage']['recorded_returns'], 1)
                spec = am.specification(monitors[1])
                plan = am.projection_plan(spec, run['id'], g['source_hash'], g['id'])
                a = plans.execute(store, plan); b = plans.execute(store, plan)
                self.assertEqual(a['id'], b['id'])
                self.assertGreater(b['execution']['cache_hits'], 0)
                monitoring.sync(store)
                self.assertEqual(before, monitoring.values(store, monitors[0]['id'], {run['id']})[run['id']])


if __name__ == '__main__': unittest.main()
