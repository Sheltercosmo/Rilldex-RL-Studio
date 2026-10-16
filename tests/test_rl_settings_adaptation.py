import copy
import json
import unittest
from pathlib import Path

from tracker import training_setup, training_recipes
from test_training_setup import request


class MethodAdaptationTests(unittest.TestCase):
    def test_verl_native_bypass_overrides_nominal_loss(self):
        p = request('verl')
        p['config']['algorithm']['rollout_correction'] = {
            'bypass_mode':True, 'loss_type':'reinforce', 'rollout_is':'token', 'rollout_rs':'seq_max_k3'}
        d = training_setup.inspect(p)
        self.assertEqual(d['status'], 'ready')
        self.assertEqual(d['profile']['weighting'], 'none')
        ids = {m['id'] for m in d['monitors']}
        self.assertIn('selection', ids)
        self.assertIn('policy_mismatch', ids)
        self.assertNotIn('objective_exposure', ids)
        p['config']['algorithm']['rollout_correction']['loss_type'] = 'ppo_clip'
        changed = training_setup.inspect(p)
        self.assertEqual(changed['profile']['weighting'], 'hard_gate')
        self.assertNotEqual(d['settings_digest'], changed['settings_digest'])

    def test_verl_missing_and_invalid_bypass_do_not_get_ready_label(self):
        for correction in [{'bypass_mode':True}, {'bypass_mode':'false'}, {'loss_type':'reinforce'}]:
            p=request('verl');p['config']['algorithm']['rollout_correction']=correction
            self.assertEqual(training_setup.inspect(p)['status'],'needs_review')
        p=request('verl');p['config']['actor_rollout_ref']['actor']['policy_loss']['loss_mode']='bypass_mode'
        self.assertEqual(training_setup.inspect(p)['status'],'needs_review')

    def test_nemo_estimator_and_objective_are_independent(self):
        p=request('nemo_rl');d=training_setup.inspect(p)
        self.assertEqual(d['profile']['credit'],'critic')
        self.assertNotIn('group_contrast',{m['id'] for m in d['monitors']})
        p['config']['ppo']['adv_estimator']['name']='raw_reward'
        self.assertEqual(training_setup.inspect(p)['profile']['credit'],'return')
        p['config']['grpo']={'adv_estimator':{'name':'reinforce_plus_plus','minus_baseline':False}}
        del p['config']['ppo']
        self.assertEqual(training_setup.inspect(p)['profile']['credit'],'return')
        p['config']['grpo']['adv_estimator']['minus_baseline']=True
        self.assertEqual(training_setup.inspect(p)['profile']['credit'],'group_relative')
        p['config']['loss_fn']['disable_ppo_ratio']=True
        self.assertEqual(training_setup.inspect(p)['profile']['weighting'],'none')

    def test_nemo_rejects_native_loss_incompatibilities(self):
        variants=[{'use_cispo':True,'disable_ppo_ratio':True}, {'use_cispo':True,'force_on_policy_ratio':True},
                  {'use_cispo':True,'ratio_clip_c':3}, {'use_cispo':True,'token_level_loss':False},
                  {'sequence_level_importance_ratios':True}, {'force_on_policy_ratio':True,'disable_ppo_ratio':True},
                  {'use_cispo':'false'}]
        for override in variants:
            with self.subTest(override=override):
                p=request('nemo_rl');p['config']['loss_fn'].update(override)
                self.assertEqual(training_setup.inspect(p)['status'],'needs_review')

    def test_async_and_critic_clocks_selected_without_group_proxy(self):
        p=request('nemo_rl');p['config']['ppo'].update({'critic_ppo_epochs':4,'policy_training_start_step':4,
            'async_ppo':{'enabled':True,'in_flight_weight_updates':True}})
        self.assertEqual(training_setup.inspect(p)['status'],'needs_review')
        p['config']['loss_fn']['use_importance_sampling_correction']=True
        d=training_setup.inspect(p)
        self.assertEqual(d['status'],'ready')
        self.assertEqual(d['profile']['scheduling'],'asynchronous')
        ids={m['id'] for m in d['monitors']}
        self.assertTrue({'policy_lag','policy_segments','actor_critic_schedule'}<=ids)
        self.assertNotIn('group_contrast',ids)
        self.assertEqual(d['recipe']['context']['scheduling'],'asynchronous')

    def test_ambiguous_and_non_rl_nemo_configs_do_not_become_grpo(self):
        p=request('nemo_rl');p['config']['grpo']={'adv_estimator':{'name':'grpo'}}
        self.assertEqual(training_setup.inspect(p)['status'],'needs_review')
        p=request('nemo_rl');del p['config']['ppo'];p['config']['grpo']={'adv_estimator':{'name':'opd'}}
        self.assertEqual(training_setup.inspect(p)['status'],'needs_review')
        self.assertEqual(training_setup.inspect(p)['profile']['credit'],'unknown')

    def test_examples_and_old_schema_replay(self):
        for example in training_setup.examples()['examples']:
            with self.subTest(example=example['id']):
                report=training_setup.inspect(example['request'])
                self.assertEqual(report['status'],'ready',report['issues'])
                packet={'schema':'training-recipes/1','producer':'p','experiment':'e','recipes':[report['recipe']]}
                training_recipes.validate(packet)
                if report['framework']!='nemo_rl' and report['schema'] in training_setup.SUPPORTED_VERSIONS:
                    packet['recipes'][0]['setup']['schema']='training-setup/1'
                    training_recipes.validate(packet)

    def test_pinned_public_configuration_results(self):
        path=Path(__file__).parent/'fixtures'/'rl-settings'/'nemo-public-configs.json'
        cases=json.loads(path.read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(case=case['name']):
                report=training_setup.inspect(case['request'])
                self.assertEqual(report['status'],'ready',report['issues'])
                for key,value in case['expected'].items(): self.assertEqual(report['profile'][key],value)
                clean=training_setup.prepare('nemo_rl',case['request']['config'],version=training_setup.PINS['nemo_rl'],resolved=True)
                self.assertEqual(training_setup.inspect(clean),report)


if __name__=='__main__':unittest.main()
