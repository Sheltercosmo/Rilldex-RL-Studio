import unittest
from scripts.rl_longitudinal_simulation import scenario, expected, document, facts, PHASES


class LongitudinalScenarioTests(unittest.TestCase):
    def test_source_success_is_presented_as_a_fraction_without_changing_reward_units(self):
        from tracker.monitoring import unit
        self.assertEqual(unit(dict(kind='metric',metric='recorded_success')),'fraction')
        self.assertEqual(unit(dict(kind='metric',metric='recorded_reward')),'value')

    def test_long_run_is_reproducible_and_keeps_every_sample_during_mix_shift(self):
        batches=scenario()
        self.assertEqual(batches,scenario())
        self.assertNotEqual(batches,scenario(seed=18))
        self.assertEqual(len(batches),64)
        self.assertTrue(all(len(b)==16 for b in batches))
        self.assertEqual({r['phase'] for b in batches for r in b},set(PHASES))
        self.assertEqual(sum(r['environment']=='terminal' for r in batches[56]),12)
        self.assertEqual(sum(r['environment']=='terminal' for r in batches[63]),4)

    def test_mix_shift_changes_aggregate_without_changing_each_environment(self):
        batches=scenario()
        first,last=batches[56],batches[-1]
        self.assertEqual(expected(first,'changed')['value'],.625)
        self.assertEqual(expected(last,'changed')['value'],.375)
        for env,value in [('terminal',.75),('business-workflow',.25)]:
            for batch in [first,last]:
                self.assertEqual(expected([r for r in batch if r['environment']==env],'changed')['value'],value)

    def test_first_retry_and_eventual_success_are_independent_expectations(self):
        rows=[dict(pattern='revise_twice',reward=1),dict(pattern='unobserved',reward=0)]
        self.assertEqual(expected(rows,'changed'),dict(value=.5,numerator=1,denominator=2,unknown=1))
        self.assertEqual(expected([rows[0]],'success')['value'],1)
        self.assertEqual(expected([rows[1]],'changed')['value'],None)

    def test_scenario_labels_do_not_leak_into_model_source_or_measurements(self):
        row=scenario()[40][0]
        doc=document(row)
        self.assertNotIn('phase',doc['metadata'])
        self.assertNotIn('pattern',doc['metadata'])
        self.assertNotIn('expected',doc)

    def test_stragglers_keep_generation_clock_and_pin_completed_revision(self):
        batch=scenario()[24]
        delayed=next(r for r in batch if r['due']>r['step'])
        self.assertEqual(delayed['due'],26)
        record=next(r for r in facts(batch,'sdk') if r['kind']=='sample' and r['sample']['id']==delayed['id'])
        self.assertEqual(record['data']['step'],24)
        self.assertEqual(record['data']['source']['revision'],1)
        self.assertEqual(record['data']['group_size'],8)

    def test_unsupported_sizes_are_rejected_before_running(self):
        for args in [(8,16),(17,16),(64,8),(64,20)]:
            with self.subTest(args=args),self.assertRaises(ValueError):scenario(*args)


if __name__=='__main__':unittest.main()
