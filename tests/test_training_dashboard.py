import copy
import tempfile
import unittest
from pathlib import Path

from tracker import training_dashboard, training_health, training_lineage, training_recipes, training_setup
from tracker.store import Store
from test_training_health import record


class DashboardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'dashboard.sqlite')

    def recipe(self, example_id):
        example = next(e for e in training_setup.examples()['examples'] if e['id'] == example_id)
        report = training_setup.inspect(copy.deepcopy(example['request']))
        self.assertEqual(report['status'], 'ready', report['issues'])
        training_recipes.receive(self.store, {'schema':'training-recipes/1', 'producer':'worker',
            'experiment':'exp', 'recipes':[report['recipe']]})
        return {'producer':'worker', 'id':report['recipe']['id'], 'revision':0}

    def cohort(self, generation=None, learner=None, *, masks=True):
        rows = []
        for sample in ('a', 'b'):
            rows.extend([record('sample', sample, **({'recipe':generation} if generation else {})),
                         record('score', sample, value=int(sample == 'a'))])
            if learner:
                rows.append(record('use', sample, recipe=learner,
                    **({'model_tokens':10, 'loss_tokens':8} if masks else {})))
        training_lineage.receive(self.store, {'schema':'training-records/1', 'producer':'worker',
            'experiment':'exp', 'records':rows})
        return training_health.snapshot(self.store)['cohorts'][0]

    def test_native_reader_matrix_picks_learning_view_without_threshold_tuning(self):
        expected = {'trl-cispo':'reward', 'trl-sapo':'reward', 'verl-ppo':'use',
                    'verl-reinforce':'use', 'areal-sequence':'use', 'nemo-async-ppo':'use',
                    'nemo-gdpo':'reward', 'openrlhf-flash':'use', 'slime-score':'use',
                    'verl-agent-gigpo':'use'}
        # Independent temporary databases avoid cross-method context leakage.
        for example_id, mode in expected.items():
            with self.subTest(example_id=example_id), tempfile.TemporaryDirectory() as temp:
                self.store = Store(Path(temp)/'matrix.sqlite')
                ref = self.recipe(example_id)
                c = self.cohort(ref, ref)
                self.assertEqual(c['dashboard']['default']['mode'], mode)
                self.assertEqual(c['monitoring_plan']['status'], 'ready')
                if mode == 'use':
                    self.assertEqual(c['dashboard']['default']['use_id'], c['uses'][0]['id'])

    def test_generation_and_use_settings_are_not_substituted(self):
        group = self.recipe('trl-cispo')
        critic = self.recipe('verl-ppo')
        c = self.cohort(group, critic)
        self.assertEqual(c['dashboard']['default']['mode'], 'use')
        self.assertIn('value model', c['dashboard']['default']['reason'])
        self.assertEqual(c['recipe_context']['reference'], group)
        self.assertEqual(c['uses'][0]['recipe_context']['reference'], critic)

    def test_missing_learner_declaration_does_not_inherit_generation_method(self):
        critic = self.recipe('verl-ppo')
        missing = {'producer':'worker', 'id':'not-delivered', 'revision':0}
        c = self.cohort(critic, missing)
        self.assertEqual(c['dashboard']['default']['mode'], 'reward')
        self.assertEqual(c['uses'][0]['recipe_context']['status'], 'not_delivered')
        self.assertIsNone(c['uses'][0]['monitoring_plan'])

    def test_maskless_critic_use_is_still_inspectable_not_measured_as_zero(self):
        ref = self.recipe('verl-ppo')
        c = self.cohort(ref, ref, masks=False)
        self.assertEqual(c['dashboard']['default']['mode'], 'use')
        self.assertIsNone(c['uses'][0]['positive_mask']['value'])
        self.assertIsNone(c['uses'][0]['zero_advantage']['value'])

    def test_teacher_observations_do_not_displace_rl_rewards(self):
        c = self.cohort()
        c['teachers'] = [{'id':'prepared-only'}]
        result = training_dashboard.project(c)
        self.assertEqual(result['default']['mode'], 'reward')
        self.assertIn('teacher', {v['mode'] for v in result['choices']})

    def test_valid_gradients_select_the_exact_stream_not_first_or_largest_step(self):
        c = self.cohort()
        base = {'stage':'backward_completed', 'producer':'worker', 'receipts':2}
        c['uses'] = [{**base, 'id':'a', 'policy_gradient':{'compatible_definitions':False,
            'eligible_tokens':0, 'observed_uses':2, 'unbound_uses':0}},
            {**base, 'id':'z', 'policy_gradient':{'compatible_definitions':True,
            'eligible_tokens':16, 'observed_uses':2, 'unbound_uses':0}}]
        d = training_dashboard.project(c)
        self.assertEqual(d['default']['use_id'], 'z')
        c['uses'].reverse()
        self.assertEqual(d, training_dashboard.project(c))
        c['uses'][0]['policy_gradient']['unbound_uses'] = 2
        self.assertEqual(training_dashboard.project(c)['default']['mode'], 'reward')

    def test_missing_or_foreign_policy_history_is_not_measurable_age(self):
        c = self.cohort()
        c['uses'] = [{'id':'age', 'stage':'backward_completed', 'producer':'worker',
                     'receipts':1, 'policy_age':{'observed_uses':1, 'clocks':[{'known_tokens':0}]}}]
        self.assertEqual(training_dashboard.project(c)['default']['mode'], 'reward')
        c['uses'][0]['policy_age']['clocks'][0]['known_tokens'] = 3
        self.assertEqual(training_dashboard.project(c)['default']['use_id'], 'age')

    def test_explicit_question_and_recovery_lineage_take_priority(self):
        c = self.cohort()
        c['attempt_chains'] = [{'id':'explicit-chain'}]
        self.assertEqual(training_dashboard.project(c)['default']['mode'], 'attempts')
        self.assertEqual(training_dashboard.project(c, has_monitor=True)['default']['mode'], 'behavior')

    def test_unverified_config_does_not_set_method_priority(self):
        c = self.cohort()
        c['uses'] = [{'id':'unverified', 'stage':'backward_completed', 'producer':'worker',
            'receipts':1, 'monitoring_plan':{'status':'needs_review',
                'groups':[{'monitors':[{'id':'critic_credit'}]}]}}]
        self.assertEqual(training_dashboard.project(c)['default']['mode'], 'reward')

    def test_no_evidence_has_no_available_choices(self):
        result = training_dashboard.project({})
        self.assertEqual(result['choices'], [])
        self.assertIn('No reward or training-use records', result['default']['reason'])


if __name__ == '__main__':
    unittest.main()
