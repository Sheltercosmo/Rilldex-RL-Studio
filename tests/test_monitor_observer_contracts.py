"""Observer routing portability and preservation of saved question identities."""
import copy
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import analysis_contracts as contracts, analysis_metrics, monitoring
from tracker import analysis_operations
from tracker.analysis_registry import Registry
from tracker.schema import InputError
from tracker.store import Store


class MonitorObserverContractTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / 'tracker.sqlite')

    def definition(self, measure, observer):
        return {'name': 'Portable question', 'kind': 'analysis', 'observer': observer,
                'analysis': {'measure': measure}}

    def changed_contract(self, name, contract):
        registry = Registry()
        for key in analysis_operations.REGISTRY.versions:
            op = analysis_operations.REGISTRY.get(key)
            registry.register(replace(op, contract=contract) if key == name else op)
        return patch.object(analysis_operations, 'REGISTRY', registry)

    def test_source_and_observed_routes_preserve_existing_input_rules(self):
        for measure, observer in [('criterion_recovery', 'source'),
                                  ('returns', 'new-domain-review'),
                                  ('criterion_recovery_window', 'source'),
                                  ('criterion_recovery_window', 'new-domain-review'),
                                  ('feedback_reference', 'source')]:
            with self.subTest(measure=measure, observer=observer):
                monitoring.validate(self.definition(measure, observer))
        for measure, observer in [('criterion_recovery', 'new-domain-review'),
                                  ('returns', 'source')]:
            with self.subTest(measure=measure), self.assertRaises(InputError):
                monitoring.validate(self.definition(measure, observer))

    def test_contract_drives_validation_without_an_operation_allowlist(self):
        changed = copy.deepcopy(contracts.CONTRACTS['work_state'])
        changed['observer_input'] = copy.deepcopy(contracts.OBSERVER_INPUTS['observed'])
        with self.changed_contract('work_state', changed):
            monitoring.validate(self.definition('criterion_recovery', 'new-domain-review'))
            with self.assertRaises(InputError):
                monitoring.validate(self.definition('criterion_recovery', 'source'))

    def test_routing_metadata_cannot_rewrite_saved_measurement_identity(self):
        raw = self.definition('returns', 'review')
        saved = monitoring.create(self.store, raw)
        contract = contracts.registered()['work_episodes']
        contract['observer_input']['guidance'] = 'New setup wording'
        with self.changed_contract('work_episodes', contract):
            reopened = monitoring.validate(monitoring.validate(raw))
            self.assertEqual(reopened['analysis_definition'], saved['analysis_definition'])
            self.assertEqual(monitoring.create(self.store, reopened)['id'], saved['id'])
            self.assertEqual(monitoring.options(self.store)['analysis_inputs']['operations']['work_episodes']['guidance'], 'New setup wording')
        self.assertNotIn('observer_input', saved['analysis_definition'])

    def test_all_measures_expose_routing_without_mutable_catalog_aliases(self):
        options = monitoring.options(self.store)
        inputs = options['analysis_inputs']['operations']
        for spec in analysis_metrics.catalog().values():
            self.assertIn(spec['operation'], inputs)
        self.assertEqual(inputs['feedback_opportunities']['preferred'], 'observed')
        self.assertIn('source', inputs['feedback_opportunities']['accepted'])
        inputs['work_state']['accepted'].append('corruption')
        self.assertEqual(monitoring.options(self.store)['analysis_inputs']['operations']['work_state']['accepted'], ['source'])

    def test_custom_code_offers_graphs_even_without_metric_records(self):
        from tracker.adapters import normalize
        from tracker import graph_store
        from tracker.schema import digest
        from test_tracker import harbor
        run=normalize(harbor(),'harbor',{})[0];self.store.add([run])
        graph=graph_store.build(run,{'observer':{'id':'graph-only','label':'Graph-only review'},
            'document':{'source_hash':digest(run),'units':[],'relations':[]}})
        with self.store.connect() as c:graph_store.save(c,graph)
        options=monitoring.options(self.store)
        self.assertNotIn('graph-only',{o['id'] for o in options['observers']})
        self.assertIn({'id':'graph-only','label':'Graph-only review'},options['custom_observers'])
        self.assertEqual(options['custom_setup']['database'],str(self.store.path.resolve()))


if __name__ == '__main__':
    unittest.main()
