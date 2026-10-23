import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from rilldex import Outbox, TrainerTelemetry, Workspace
from tracker import capture_bundle, trainer_telemetry as t
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict
from tracker.telemetry_cli import run


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'workspace.sqlite')
        self.config=dict(experiment='study',producer='learner',framework='trl-grpo',framework_version='1.15.0',objective='dapo/beta=0.01/reduction=v1',session='start-1')

    def logger(self,**kwargs):return TrainerTelemetry(self.store,**{**self.config,**kwargs})

    def test_grpo_native_reward_is_a_default_outcome_without_inventing_success(self):
        self.logger().log({'reward':.7},step=1)
        series=t.snapshot(self.store)['series'][0]
        self.assertEqual((series['native_key'],series['group'],series['unit']),('reward','reward','reward'))
        self.assertIn('Not advantage, task success',series['definition'])
        self.assertNotIn('reward',t.PROFILES['trl-ppo'])

    def test_sb3_profiles_keep_native_meanings_and_relevant_missing_groups(self):
        self.logger(framework='stable-baselines3',framework_version='2.9.0',objective='dqn',clock='environment_timesteps').log(
            {'train/loss':.3,'time/fps':120,'rollout/ep_rew_mean':20,'rollout/exploration_rate':.4},step=256)
        snapshot=t.snapshot(self.store);by={s['native_key']:s for s in snapshot['series']}
        self.assertEqual(snapshot['missing_groups'],[])
        self.assertEqual(by['time/fps']['unit'],'environment transitions / second')
        self.assertEqual(by['rollout/exploration_rate']['label'],'DQN epsilon')
        self.logger(framework='stable-baselines3',framework_version='2.9.0',objective='ppo',session='ppo').log(
            {'train/entropy_loss':-.7,'train/approx_kl':.005,'train/clip_fraction':.1},step=128)
        self.assertNotIn('tokens',t.snapshot(self.store)['missing_groups'])

    def test_native_definitions_do_not_merge_truncation_clipping_or_kl(self):
        self.logger().log({'loss':-.03,'entropy':.8,'kl':.01,'clip_ratio/region_mean':.4,'completions/clipped_ratio':.2,'num_tokens':2048,'train_tokens_per_second':100},step=3)
        result=t.snapshot(self.store);by={s['native_key']:s for s in result['series']}
        self.assertEqual(by['completions/clipped_ratio']['group'],'tokens')
        self.assertEqual(by['clip_ratio/region_mean']['group'],'clipping')
        self.assertEqual(by['num_tokens']['reduction'],'cumulative counter')
        self.assertEqual(result['missing_groups'],[])
        self.logger(framework='trl-ppo').log({'objective/kl':2.,'policy/approxkl_avg':.02},step=3)
        kl=[s for s in t.snapshot(self.store)['series'] if s['group']=='kl']
        self.assertEqual(len(kl),3)
        self.assertEqual(len({s['label'] for s in kl}),3)

    def test_missing_nonfinite_invalid_and_conflicts_remain_gaps(self):
        log=self.logger()
        log.log({'loss':1},step=0)
        log.log({'entropy':.3},step=1)
        log.log({'loss':float('nan')},step=2)
        log.log({'loss':True},step=3)
        log.log({'loss':.2},step=4,record_id='a')
        log.log({'loss':.3},step=4,record_id='b')
        s=next(s for s in t.snapshot(self.store)['series'] if s['native_key']=='loss')
        self.assertEqual([p['status'] for p in s['points']],['recorded','missing','nonfinite','invalid','conflicting'])
        self.assertEqual(s['recorded'],1)
        self.assertTrue(all(p['value'] is None for p in s['points'][1:]))

    def test_replay_identity_atomic_conflict_and_clock_isolation(self):
        log=self.logger();a=log.log({'loss':1},step=0,record_id='stable')
        self.assertEqual(a['inserted'],1)
        self.assertEqual(log.log({'loss':1},step=0,record_id='stable')['inserted'],0)
        with self.assertRaises(ReviewConflict):log.log({'loss':2},step=0,record_id='stable')
        for fields in ({'session':'restart'},{'producer':'rank-1'},{'objective':'gspo/config2'},{'clock':'generation_batch'},{'framework_version':'next'}):
            self.logger(**fields).log({'loss':3},step=0)
        log.log({'loss':4},step=0,split='evaluation')
        self.assertEqual(len(t.snapshot(self.store)['series']),7)

    def test_sql_scope_and_full_native_context(self):
        self.logger().log({'loss':1,'custom/new_scalar':5},step=0)
        self.logger(experiment='other').log({'loss':9},step=0)
        ws=Workspace(self.store.path,experiment='study')
        rows=ws.telemetry().rows
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['record']['metrics']['custom/new_scalar']['group'],'other')
        self.assertEqual(ws.sql('SELECT step,objective FROM trainer_telemetry').rows[0]['step'],0)

    def test_outbox_restart_lost_ack_and_offline_bundle(self):
        box=Outbox(self.root/'outbox.sqlite',producer='learner')
        logger=TrainerTelemetry(box,**self.config)
        logger.log({'loss':.4},step=1)
        with patch('tracker.capture.urlopen',side_effect=URLError('offline')):self.assertEqual(box.drain()['pending'],1)
        capture_bundle.export(box.path,self.root/'capture.zip')
        result=capture_bundle.receive(self.store,self.root/'capture.zip',with_receipts=True)
        self.assertTrue(result['complete'])
        def send(request,**kwargs):
            self.assertTrue(request.full_url.endswith('/api/trainer-telemetry'))
            return io.BytesIO(json.dumps(t.receive(self.store,json.loads(request.data))).encode())
        resumed=Outbox(box.path,producer='learner')
        with patch('tracker.capture.urlopen',side_effect=send):self.assertEqual(resumed.drain()['sent_now'],1)
        self.assertEqual(t.snapshot(self.store)['records'],1)

    def test_long_reversed_streams_keep_steps_and_rates(self):
        for stream in range(4):
            logger=self.logger(framework='verl',framework_version='v0.7',producer=f'learner-{stream}')
            for step in reversed(range(128)):
                logger.log({'actor/pg_loss':1/(step+1),'actor/entropy':1-step/200,'actor/ppo_kl':-.003,
                    'actor/pg_clipfrac':.2,'perf/total_num_tokens':4096,'perf/throughput':200+step},step=step)
        result=t.snapshot(self.store)
        self.assertEqual(result['records'],512);self.assertEqual(len(result['series']),24)
        self.assertFalse(result['truncated'])
        for series in result['series']:self.assertEqual([p['step'] for p in series['points']],list(range(128)))
        self.assertTrue(all(s['unit']=='tokens / second / GPU' for s in result['series'] if s['native_key']=='perf/throughput'))
        self.assertTrue(t.snapshot(self.store,limit=5)['truncated'])

    def test_cli_partial_live_jsonl_and_idempotent_batches(self):
        file=self.root/'logs.jsonl';file.write_text('{"step":1,"loss":0.2}\n{"step":2,',encoding='utf-8')
        args=SimpleNamespace(db=str(self.store.path),telemetry_command='import',path=str(file),definitions=None,clock='learner_update',population='trainer logged batch',environment='unspecified',split='train',**self.config)
        self.assertEqual(run(args)['imported'],1)
        file.write_text('{"step":1,"loss":0.2}\n{"step":2,"loss":0.1}\n',encoding='utf-8')
        self.assertEqual(run(args)['imported'],1)
        self.assertEqual(run(args)['imported'],0)
        file.write_text(json.dumps({'log_history':[{'step':3,'eval_loss':.3,'eval_runtime':4}]}),encoding='utf-8')
        run(args)
        self.assertTrue(any(s['context']['split']=='evaluation' for s in t.snapshot(self.store)['series']))

    def test_custom_definitions_and_bad_coordinate(self):
        logger=self.logger(framework='custom',definitions={'server/output_rate':t.metric('Output rate','throughput','tokens / second','server interval','Output tokens / elapsed serving seconds, no prompt tokens.')})
        logger.log({'server/output_rate':42},step=8)
        self.assertEqual(t.snapshot(self.store)['series'][0]['unit'],'tokens / second')
        with self.assertRaises(InputError):logger.log({'server/output_rate':42},step=True)

    def test_native_scalar_objects_not_vectors(self):
        class NativeScalar:
            shape=()
            def item(self):return .25
        class NativeVector:
            shape=(2,)
            def item(self):raise AssertionError('A vector must not be coerced')
        self.logger(framework='verl').log({'actor/entropy_loss':NativeScalar(),'actor/pg_loss':NativeVector(),'kl_loss':.02},step=1)
        rows={s['native_key']:s for s in t.snapshot(self.store)['series']}
        self.assertEqual(rows['actor/entropy_loss']['points'][0]['value'],.25)
        self.assertEqual(rows['actor/pg_loss']['points'][0]['status'],'invalid')
        self.assertEqual(rows['kl_loss']['group'],'kl')

    def test_old_database_read_only_analysis_has_empty_telemetry(self):
        with self.store.connect() as c:c.execute('DROP TABLE trainer_telemetry')
        self.assertEqual(Workspace(self.store.path).telemetry().rows,[])


if __name__=='__main__':unittest.main()
