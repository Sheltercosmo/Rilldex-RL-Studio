import unittest
import tempfile
from pathlib import Path
from tracker.store import Store

from tracker import analysis_metrics, monitor_catalog, monitoring


class MonitorCatalogTests(unittest.TestCase):
    def test_all_catalog_entries_resolve_to_registered_measures(self):
        self.assertEqual(monitor_catalog.validate_catalog(), [])
        rows = monitor_catalog.catalog()
        self.assertGreaterEqual(len(rows), 10)
        self.assertLessEqual(len(rows), 19)
        for row in rows:
            with self.subTest(recipe=row['id']):
                if row['kind'] == 'metric':
                    self.assertIn(row['metric'], monitoring.DEFINITIONS)
                else:
                    self.assertIn(row['measure'], analysis_metrics.catalog())
                self.assertTrue(row['question'])
                self.assertTrue(row['use'])
                self.assertTrue(row['evidence_requirement'])
                self.assertIn(row['group'], {'Training', 'Behavior', 'Reward integrity'})

    def test_defaults_are_small_source_only_and_monitor_valid(self):
        definitions = monitor_catalog.default_definitions()
        self.assertLessEqual(len(definitions), 8)
        self.assertGreaterEqual(len(definitions), 6)
        self.assertTrue(all(d['observer'] == 'source' for d in definitions))
        self.assertEqual({d.get('metric') or d['analysis']['measure'] for d in definitions}, {
            'recorded_reward', 'recorded_success', 'agent_text_chars', 'actions',
            'environment_tool_error_fraction', 'exact_dispatch_repeat_rate',
            'feedback_link_rate', 'next_check_success'})
        for definition in definitions:
            with self.subTest(name=definition['name']):
                self.assertEqual(monitoring.validate(definition)['observer'], 'source')

    def test_semantic_recipes_need_explicit_observer_and_validate(self):
        definitions = monitor_catalog.default_definitions('reviewed-observer-v1')
        semantic = [d for d in definitions if d['observer'] != 'source']
        self.assertEqual(len(semantic), 9)
        for definition in semantic:
            with self.subTest(name=definition['name']):
                validated = monitoring.validate(definition)
                self.assertEqual(validated['observer'], 'reviewed-observer-v1')

    def test_semantic_recipes_are_not_defaulted_to_a_fake_observer(self):
        rows = monitor_catalog.catalog()
        semantic = [row for row in rows if row['observer_requirement'] == 'explicit_observer']
        self.assertTrue(semantic)
        self.assertTrue(all(row['definition']['observer'] is None for row in semantic))
        with self.assertRaises(ValueError):
            monitor_catalog.default_definitions('source')

    def test_catalog_searches_question_and_measure_ids(self):
        self.assertEqual([r['id'] for r in monitor_catalog.catalog('explicit feedback')], ['feedback-reference'])
        self.assertEqual([r['id'] for r in monitor_catalog.catalog('procedure_change_fraction')], ['procedure-change'])
        self.assertEqual(monitor_catalog.catalog('explicit_observer'), [])
        self.assertEqual([r['id'] for r in monitor_catalog.catalog('revisit_exact_repeat_fraction')], ['revisit-matching-feedback'])

    def test_add_defaults_preserves_equivalent_renamed_paused_measure(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'test.sqlite')
            old=monitoring.create(store,dict(name='My reward',kind='metric',metric='recorded_reward',observer='source'))
            monitoring.enabled(store,old['id'],False)
            result=monitoring.add_starters(store,{})
            self.assertEqual(len(result['added']),7)
            self.assertIn(old['id'],result['existing'])
            self.assertEqual(monitoring.add_starters(store,{})['added'],[])
            self.assertFalse(next(d for d in monitoring.definitions(store) if d['id']==old['id'])['enabled'])
            self.assertEqual(len(monitoring.options(store)['starters']),19)


if __name__ == '__main__':
    unittest.main()
