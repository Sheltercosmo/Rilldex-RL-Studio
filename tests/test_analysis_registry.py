"""Operator portability, dependency integrity and retained plan compatibility."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import analysis_contracts as contracts, analysis_operations as ops
from tracker import analysis_metrics, graph_store, investigation_plans as plans, monitoring
from tracker.analysis_registry import Registry, Operation, Parameters, Dependencies, Dependency, Binding
from tracker.adapters import normalize
from tracker.portable import generation_document
from tracker.schema import InputError, digest
from tracker.store import Store
from test_history_evidence import query


class RegistryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'test.sqlite')
        self.run = normalize(generation_document('Compute.', 'Two plus two is four.'))[0]
        self.store.add([self.run]); self.graph = graph_store.build(self.run)
        with self.store.connect() as c: graph_store.save(c, self.graph)
        self.binding = dict(run_id=self.run['id'], source_hash=digest(self.run), graph_id=self.graph['id'])
        self.calls = []

    def count(self):
        with self.store.connect() as c:
            return c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0]

    def contract(self):
        return contracts.projection(
            'Captured event count', 'How many events were recorded?', 'captured event',
            [], 'Recorded events only.', 'Authored extension mechanics control.', observer='source')

    def operators(self):
        def source(ctx):
            self.calls.append('source')
            return {'run_id': ctx.run['id'], 'events': len(ctx.run['events'])}
        def dependent(ctx):
            self.calls.append('dependent')
            return {'run_id': ctx.run['id'], 'events': ctx.inputs[0]['events'],
                    'graph_id': ctx.graph['id']}
        registry = Registry()
        registry.register(Operation('future_events', 'authored-events/1', self.contract(),
            Parameters(('run_id', 'source_hash'), identifiers=('run_id', 'source_hash')), source))
        registry.register(Operation('future_bound_events', 'authored-bound-events/1', self.contract(),
            Parameters(('graph_id',), identifiers=('graph_id',)), dependent,
            Dependencies((Dependency('future_events', 'events'),)), Binding('dependency', source_input=0)))
        return registry

    def test_new_source_and_composed_operator_need_no_engine_branch(self):
        registry = self.operators()
        plan = registry.projection_plan('future_bound_events', self.binding, schema=plans.VERSION)
        self.assertEqual([n['name'] for n in plan['nodes']], ['events', 'observation'])
        self.assertEqual(plan['nodes'][0]['params'], {k: self.binding[k] for k in ('run_id', 'source_hash')})
        check = plans.preflight(self.store, plan, registry=registry)
        self.assertEqual(self.calls, []); self.assertEqual(self.count(), 0)
        self.assertEqual(check['nodes'][1]['operator']['binding']['source_input'], 0)
        result = plans.execute(self.store, plan, registry=registry)
        self.assertEqual(result['outputs']['observation']['events'], len(self.run['events']))
        self.assertEqual(self.calls, ['source', 'dependent'])
        replay = plans.execute(self.store, plan, registry=registry)
        self.assertEqual(replay['id'], result['id']); self.assertEqual(replay['execution']['cache_hits'], 2)
        self.assertEqual(self.calls, ['source', 'dependent'])

    def test_version_change_recomputes_consumer_without_discarding_upstream(self):
        registry = self.operators()
        plan = registry.projection_plan('future_bound_events', self.binding, schema=plans.VERSION)
        first = plans.execute(self.store, plan, registry=registry)
        upgraded = Registry()
        upgraded.register(registry.get('future_events'))
        upgraded.register(replace(registry.get('future_bound_events'), version='authored-bound-events/2'))
        second = plans.execute(self.store, plan, registry=upgraded)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(second['execution']['cache_hits'], 1)
        self.assertEqual(plans.read_plan(self.store, first['id'])['definition'], plan)

    def test_invalid_later_parameters_and_wrong_dependency_type_precede_execution(self):
        registry = self.operators()
        plan = registry.projection_plan('future_bound_events', self.binding, schema=plans.VERSION)
        bad = copy.deepcopy(plan); bad['nodes'][-1]['params']['unexpected'] = True
        with self.assertRaises(InputError): plans.execute(self.store, bad, registry=registry)
        wrong = copy.deepcopy(plan)
        wrong['nodes'].append(dict(name='again', op='future_bound_events',
            inputs=['observation'], params={'graph_id': self.graph['id']}))
        with self.assertRaisesRegex(InputError, 'dependency type'):
            plans.execute(self.store, wrong, registry=registry)
        self.assertEqual(self.count(), 0); self.assertEqual(self.calls, [])

    def test_dependency_cannot_rebind_a_different_rollout(self):
        registry = self.operators()
        other = normalize(generation_document('Other.', 'A different response.'))[0]
        self.store.add([other]); graph = graph_store.build(other)
        with self.store.connect() as c: graph_store.save(c, graph)
        plan = registry.projection_plan('future_bound_events', self.binding, schema=plans.VERSION)
        plan['nodes'][-1]['params']['graph_id'] = graph['id']
        with self.assertRaisesRegex(InputError, 'binding'): plans.execute(self.store, plan, registry=registry)
        self.assertEqual(self.count(), 0); self.assertEqual(self.calls, [])

    def test_registered_capability_absence_is_missing_not_satisfied(self):
        registry = Registry(); c = self.contract(); c['evidence_needs'] = ['future_modality']
        registry.register(Operation('future_events', '1', c,
            Parameters(('run_id', 'source_hash'), identifiers=('run_id', 'source_hash')),
            lambda context: {}))
        plan = registry.projection_plan('future_events', self.binding, schema=plans.VERSION)
        row = plans.preflight(self.store, plan, registry=registry)['nodes'][0]
        self.assertEqual(row['missing_evidence'], ['future_modality'])
        self.assertEqual(row['evidence_status'], 'missing_inputs')

    def test_catalog_and_monitor_setup_use_the_registered_extension(self):
        registry = Registry()
        for name in ops.REGISTRY.versions: registry.register(ops.REGISTRY.get(name))
        extension = self.operators().get('future_events')
        registry.register(extension)
        with patch.object(ops, 'REGISTRY', registry):
            row = next(x for x in plans.catalog()['operations'] if x['id'] == 'future_events')
            self.assertEqual(row['operator']['parameters']['required'], ['run_id', 'source_hash'])
            self.assertEqual(monitoring.options(self.store)['analysis_inputs']['operations']['future_events']['accepted'], ['source'])
            row['observer_input']['accepted'].clear()
            self.assertEqual(contracts.registered()['future_events']['observer_input']['accepted'], ['source'])

    def test_every_existing_monitor_expands_to_its_original_plan(self):
        for name, spec in analysis_metrics.catalog().items():
            spec = dict(spec)
            if spec.get('requires_query'):
                spec['query'] = (copy.deepcopy(ops.work_return_references.DEFAULT_QUERY)
                                 if spec['operation'] == 'work_return_references' else query())
            old_params = analysis_metrics.projection_params(spec, **self.binding)
            if spec['operation']=='declared_plans':
                # New source-only operator; the legacy helper predates its contract.
                old_params.pop('graph_id')
            if spec['operation'] == 'retry_outcomes':
                expected = {'schema': plans.VERSION, 'nodes': [
                    dict(name='recovery/recorded_state', op='work_state', inputs=[], params=old_params),
                    dict(name='recovery', op='recovery_windows', inputs=['recovery/recorded_state'],
                         params={'graph_id': self.graph['id']}),
                    dict(name='observation', op='retry_outcomes', inputs=['recovery'],
                         params={'graph_id': self.graph['id']})]}
            elif spec['operation'] == 'recovery_windows':
                expected = {'schema': plans.VERSION, 'nodes': [
                    dict(name='recorded_state', op='work_state', inputs=[], params=old_params),
                    dict(name='observation', op='recovery_windows', inputs=['recorded_state'],
                         params={'graph_id': self.graph['id']})]}
            else:
                expected = {'schema': plans.VERSION, 'nodes': [
                    dict(name='observation', op=spec['operation'], inputs=[], params=old_params)]}
            with self.subTest(measure=name):
                self.assertEqual(analysis_metrics.projection_plan(spec, **self.binding), expected)

    def test_registration_rejects_replacement_unbound_dependencies_and_model_jobs(self):
        registry = self.operators(); original = registry.get('future_events')
        invalid = [
            original,
            replace(original, name='new', contract=dict(original.contract, new_model_calls=1)),
            replace(original, name='new', parameters=Parameters(('other',))),
            replace(original, name='new', dependencies=Dependencies((Dependency('missing', 'x'),))),
            replace(original, name='new', binding=Binding('dependency', source_input=0)),
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate.name):
                with self.assertRaises(ValueError): registry.register(candidate)
        self.assertEqual(set(registry.versions), {'future_events', 'future_bound_events'})

    def test_population_declaration_rejects_duplicate_or_incomplete_membership(self):
        registry = self.operators()
        registry.register(Operation('future_compare', '1', self.contract(),
            Parameters(('focus', 'reference'), comparison=True), lambda ctx: {},
            Dependencies(variadic='future_events'), Binding('population', complete_population=True)))
        source = registry.projection_plan('future_events', self.binding, schema=plans.VERSION)
        source['nodes'].append(dict(name='compare', op='future_compare', inputs=['observation'],
                                   params={'focus': [], 'reference': []}))
        with self.assertRaisesRegex(InputError, 'account'):
            plans.execute(self.store, source, registry=registry)
        source['nodes'][-1]['inputs'].append('observation')
        with self.assertRaisesRegex(InputError, 'Duplicate'):
            plans.execute(self.store, source, registry=registry)
        self.assertEqual(self.count(), 0); self.assertEqual(self.calls, [])

    def test_operator_cannot_mutate_the_plan_or_an_upstream_receipt(self):
        registry = self.operators()
        def mutator(ctx):
            ctx.inputs[0]['events'] = -1
            ctx.run['metadata']['changed'] = True
            ctx.params['graph_id'] = 'changed'
            return {'run_id': ctx.run['id'], 'events': -1}
        registry.register(replace(registry.get('future_bound_events'), name='future_mutator', execute=mutator))
        plan = registry.projection_plan('future_mutator', self.binding, schema=plans.VERSION)
        original = copy.deepcopy(plan)
        result = plans.execute(self.store, plan, registry=registry)
        self.assertEqual(plan, original)
        self.assertEqual(result['outputs']['events']['events'], len(self.run['events']))
        self.assertNotIn('changed', plans.run_source(self.store, self.run['id'])['metadata'])
        self.assertEqual(plans.execute(self.store, plan, registry=registry)['outputs'], result['outputs'])

    def test_unregistered_operation_does_not_load_executable_input(self):
        registry = self.operators()
        plan = registry.projection_plan('future_events', self.binding, schema=plans.VERSION)
        plan['nodes'][0]['op'] = '__import__("os").system'
        with self.assertRaises(InputError): plans.execute(self.store, plan, registry=registry)
        self.assertEqual(self.count(), 0)


if __name__ == '__main__': unittest.main()
