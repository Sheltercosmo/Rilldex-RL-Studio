import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tracker.store import Store
from tracker.telemetry_cli import run
from tracker import trainer_telemetry as t, telemetry_queries as q


class SwiftTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'study.sqlite')
        self.config = dict(producer='learner', experiment='swift', framework='ms-swift-grpo',
                           framework_version='3.11-custom/test', objective='grpo/test', session='start')

    def test_reward_components_and_entropy_keep_their_own_denominators(self):
        logger = t.TrainerTelemetry(self.store, **self.config)
        logger.log({'reward': 2.1, 'reward_std': .2, 'frac_reward_zero_std': .25,
                    'rewards/format/mean': .9, 'rewards/format/std': .3,
                    'entropy/mean': .5, 'entropy/max': .8, 'entropy/min': .2,
                    'completions/clipped_ratio': .1, 'clip_ratio/region_mean': .2,
                    'completions/max_length': 4096, 'learning_rate': 1e-5}, step=5)
        series = {s['native_key']: s for s in q.query(self.store)['series']}
        self.assertEqual(series['reward']['group'], 'reward')
        self.assertEqual(series['rewards/format/mean']['unit'], 'component reward')
        self.assertIn('Unweighted', series['rewards/format/mean']['definition'])
        self.assertIn('group or batch', series['reward_std']['reduction'])
        self.assertIn('not a filtering or failure rate', series['frac_reward_zero_std']['definition'])
        self.assertIn('per-completion token mean', series['entropy/max']['reduction'])
        self.assertEqual(series['completions/clipped_ratio']['group'], 'tokens')
        self.assertEqual(series['clip_ratio/region_mean']['group'], 'clipping')
        self.assertEqual(series['learning_rate']['reduction'], 'trainer logger value')

    def test_import_mixed_evaluation_replay_and_unknown_keys(self):
        file = self.root / 'trainer_state.json'
        file.write_text(json.dumps({'log_history': [
            {'step': 1, 'epoch': .1, 'reward': 1., 'entropy/mean': .3},
            {'step': 2, 'reward': 2., 'eval_reward': 3., 'eval_rewards/format/mean': .8,
             'eval_entropy/mean': .4, 'custom/new': 6.}]}), encoding='utf-8')
        args = SimpleNamespace(db=self.store.path, telemetry_command='import', path=file,
                               definitions=None, clock='learner_update', population='logged batch',
                               environment='video', split='train', **self.config)
        self.assertEqual(run(args)['imported'], 3)
        self.assertEqual(run(args)['imported'], 0)
        result = q.query(self.store)
        series = {s['native_key']: s for s in result['series']}
        self.assertEqual(series['eval_reward']['context']['split'], 'evaluation')
        self.assertEqual(series['eval_reward']['group'], 'reward')
        self.assertEqual(series['eval_entropy/mean']['group'], 'entropy')
        self.assertEqual(series['custom/new']['reduction'], 'unmapped')
        self.assertNotIn('epoch', series)
        self.assertEqual(series['reward']['stats']['coordinates'], 2)

    def test_custom_definitions_win_and_other_profiles_do_not_gain_swift_semantics(self):
        logs = {'rewards/scorer/mean': .2, 'entropy/mean': .4}
        custom = t.metric('Human score', 'reward', 'points', 'median', 'Provided by the researcher.')
        packet = t.packet(logs, step=1, definitions={'rewards/scorer/mean': custom}, **self.config)
        self.assertEqual(packet['records'][0]['metrics']['rewards/scorer/mean']['reduction'], 'median')
        unknown = t.packet(logs, step=1, **{**self.config, 'framework': 'custom'})
        self.assertEqual(unknown['records'][0]['metrics']['entropy/mean']['reduction'], 'unmapped')
        self.assertNotEqual(packet['records'][0]['mapping'], unknown['records'][0]['mapping'])


if __name__ == '__main__':
    unittest.main()
