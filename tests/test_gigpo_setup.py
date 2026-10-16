import copy
import unittest

from tracker.gigpo_setup import examples, PIN
from tracker.training_setup import inspect, prepare, SUPPORTED_VERSIONS
from tracker.training_recipes import validate
from tracker.adapters import normalize
from tracker.import_batch import preflight


def request():
    return {'framework': 'verl_agent', 'version': PIN, 'resolved': True,
            'config': copy.deepcopy(examples()[0][3])}


class GiGPOSetupTests(unittest.TestCase):
    def test_nested_credit_is_not_plain_prompt_group_contrast(self):
        p = request(); p['framework'] = 'auto'
        r = inspect(p)
        self.assertEqual((r['status'], r['framework']), ('ready', 'verl_agent'))
        self.assertEqual(r['profile']['credit'], 'hierarchical_group_relative')
        ids = {m['id'] for m in r['monitors']}
        self.assertTrue({'state_groups', 'episode_baseline', 'advantage_components', 'turn_continuity'} <= ids)
        self.assertNotIn('group_contrast', ids)
        self.assertEqual(r['profile']['credit_unit'], 'turn')
        self.assertEqual(r['monitoring_plan']['time_axes'][0]['id'], 'episode_turn')
        self.assertTrue(all(m['state'] == 'capture_pending' for m in r['monitors'] if m['id'] in ids - {'reward', 'use'}))
        validate({'schema':'training-recipes/1', 'producer':'p', 'experiment':'e', 'recipes':[r['recipe']]})

    def test_state_weight_controls_guidance_and_identity(self):
        p = request(); before = inspect(p)
        p['config']['algorithm']['gigpo']['step_advantage_w'] = 0
        zero = inspect(p)
        self.assertEqual(zero['status'], 'ready')
        self.assertNotEqual(before['settings_digest'], zero['settings_digest'])
        ids = {m['id'] for m in zero['monitors']}
        self.assertNotIn('state_groups', ids)
        self.assertNotIn('advantage_components', ids)
        self.assertIn('episode_baseline', ids)
        self.assertIn('disabled', zero['profile']['estimator'])

    def test_similarity_and_dynamic_sampling_are_independent(self):
        p = request(); g = p['config']['algorithm']['gigpo']
        g['enable_similarity'] = True
        p['config']['algorithm']['filter_groups']['enable'] = True
        self.assertIn('selection', {m['id'] for m in inspect(p)['monitors']})
        for value in [0, 1, True, '0.9']:
            g['similarity_thresh'] = value
            self.assertIsNone(inspect(p)['recipe'])
        g['similarity_thresh'] = .9
        self.assertEqual(inspect(p)['status'], 'ready')
        p['config']['algorithm']['filter_groups'].pop('max_num_gen_batches')
        self.assertIsNone(inspect(p)['recipe'])

    def test_no_fork_defaults_or_unverified_method_substitution(self):
        for key, value in [('adv_estimator', 'grpo'), ('use_pf_ppo', True)]:
            p = request(); p['config']['algorithm'][key] = value
            self.assertIsNone(inspect(p)['recipe'])
        p = request(); p['version'] = 'unverified-fork'; p['framework'] = 'auto'
        r = inspect(p)
        self.assertEqual(r['framework'], 'verl_agent')
        self.assertIsNone(r['recipe'])
        p = request(); p['config']['algorithm']['gigpo'].pop('mode')
        self.assertIsNone(inspect(p)['recipe'])
        p = request(); p['config']['env'].pop('rollout')
        p['config']['actor_rollout_ref']['rollout'] = {'n':8}
        self.assertIsNone(inspect(p)['recipe'])  # Different native sampling field.

    def test_settings_and_ratio_change_are_safe_and_replayable(self):
        p = request(); cfg = p['config']; cfg['api_key'] = 'secret'
        cfg['actor_rollout_ref']['actor']['policy_loss']['loss_mode'] = 'gspo'
        r = inspect(p)
        self.assertEqual(r['profile']['ratio_unit'], 'sequence')
        exported = prepare('verl_agent', cfg, version=PIN, resolved=True)
        self.assertEqual(r, inspect(exported))
        self.assertNotIn('secret', str(exported))
        self.assertIn('training-setup/3', SUPPORTED_VERSIONS)
        for key in ['mode', 'step_advantage_w']:
            cfg['algorithm']['gigpo'][key] = True
            self.assertIsNone(inspect(p)['recipe'])
            cfg['algorithm']['gigpo'][key] = request()['config']['algorithm']['gigpo'][key]

    def test_generation_grain_is_projection_and_never_replays_prompt_history(self):
        row = {'input':'History: action open fridge. Current turn 2.',
               'output':'<action>inspect fridge</action>', 'score':10, 'step':1}
        run = normalize(row, 'verl-generation')[0]
        before = copy.deepcopy(run)
        result = preflight([run, copy.deepcopy(run)])
        self.assertEqual(run, before)
        self.assertEqual(result['total_records'], 2)
        self.assertEqual(result['source_units'][0]['id'], 'generation_record')
        self.assertEqual(result['source_units'][0]['records'], 2)
        self.assertEqual(result['recorded_actions'], 0)
        self.assertEqual(result['metric_coverage']['recorded_success']['available'], 0)
        self.assertEqual(result['runs'][0]['source_unit']['label'], 'Generated response')
        self.assertEqual([(e['actor'], e['source_pointer']) for e in run['events']], [('context','/input'),('agent','/output')])


if __name__ == '__main__': unittest.main()
