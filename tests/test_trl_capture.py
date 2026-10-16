"""Authored callback controls; actual TRL execution lives in the runtime audit."""
import asyncio
import inspect
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tracker.adapters import normalize
from tracker.capture import Outbox
from tracker.schema import InputError
from tracker.trl_capture import GRPOCapture


class TRLCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Outbox(Path(self.tmp.name)/'out.sqlite',producer='test/rank0')
        self.capture=GRPOCapture(self.out,experiment='audit',reward_definition='length-component/v1',trainer_version='1.15.0',
            context=lambda:{'split':'train','policy_version':'explicit-sampler-id'},on_error='raise')
        self.kw={'prompts':['Question','Question'],'completions':['Answer','Answer'],'completion_ids':[[4,5],[4,5]],
            'trainer_state':SimpleNamespace(global_step=6),'tracking_task_id':['task','task'],'tracking_sample_id':['row','row'],
            'ground_truth':['SECRET','SECRET'],'environments':['PRIVATE','PRIVATE']}

    def payloads(self):
        with self.out.connect() as c:return [json.loads(r[0]) for r in c.execute('SELECT payload FROM queue ORDER BY id')]

    def test_reward_object_is_unchanged_and_duplicate_completions_stay_distinct(self):
        rewards=[0,None];seen=[]
        def reward(**kwargs):seen.append(kwargs);return rewards
        wrapped=self.capture.wrap_reward(reward)
        self.assertIs(wrapped(**self.kw),rewards);self.assertEqual(len(seen),1);self.assertEqual(wrapped.__name__,'reward')
        payloads=self.payloads();self.assertEqual(len({p['rollout_id'] for p in payloads}),2)
        for p in payloads:
            r=normalize(p['document'])[0];m=r['metadata']
            self.assertEqual(m['training_step'],6);self.assertEqual(m['policy_version'],'explicit-sampler-id')
            self.assertEqual(m['training_step_basis'],'trainer_global_step_at_reward_callback')
            self.assertNotIn('generation_step',m);self.assertNotIn('rollout_n',m)
            self.assertEqual(m['training_inclusion'],'reward_scored_optimizer_use_unconfirmed')
            self.assertNotIn('SECRET',str(p));self.assertNotIn('PRIVATE',str(p))
        self.assertEqual([p['document']['outcome']['reward'] for p in payloads],[0,None])

    def test_unwrapped_training_values_and_hook_args_are_not_modified(self):
        def reward(**kw):return [float(len(t)) for t in kw['completions']]
        expected=reward(**self.kw);self.assertEqual(self.capture.wrap_reward(reward)(**self.kw),expected)
        self.assertEqual(self.kw['completion_ids'],[[4,5],[4,5]])

    def test_async_reward_keeps_async_contract_and_propagates_reward_error(self):
        async def reward(**kwargs):return [1,2]
        fn=self.capture.wrap_reward(reward);self.assertTrue(inspect.iscoroutinefunction(fn))
        self.assertEqual(asyncio.run(fn(**self.kw)),[1,2])
        async def broken(**kwargs):raise RuntimeError('reward failed')
        with self.assertRaisesRegex(RuntimeError,'reward failed'):asyncio.run(self.capture.wrap_reward(broken)(**self.kw))
        self.assertEqual(len(self.payloads()),4)
        for p in self.payloads()[-2:]:
            self.assertEqual(p['state'],'failed');self.assertIsNone(p['document']['outcome']['reward'])
            self.assertEqual(p['document']['capture_provenance']['reward_error']['type'],'RuntimeError')
            self.assertNotIn('reward failed',str(normalize(p['document'])[0]['events']))

    def test_capture_failure_during_reward_exception_never_masks_original_error(self):
        self.out.max_pending_bytes=1
        def broken(**kw):raise RuntimeError('original reward error')
        with self.assertRaisesRegex(RuntimeError,'original reward error') as caught:self.capture.wrap_reward(broken)(**self.kw)
        self.assertIn('could not preserve',str(caught.exception.__notes__))
        self.assertEqual(self.payloads(),[])

    def test_new_callbacks_even_at_same_global_step_get_new_sample_identity(self):
        fn=self.capture.wrap_reward(lambda **kw:[1,1]);fn(**self.kw);fn(**self.kw)
        self.assertEqual(len({p['rollout_id'] for p in self.payloads()}),4)
        restarted=GRPOCapture(self.out,experiment='audit',reward_definition='r/v1',trainer_version='1.15.0',context=lambda:{'split':'evaluation'},on_error='raise')
        restarted.wrap_reward(lambda **kw:[1,1])(**self.kw)
        self.assertEqual(len({p['rollout_id'] for p in self.payloads()}),6)
        self.assertNotIn('policy_version',self.payloads()[-1]['document']['metadata'])

    def test_structured_history_is_preserved_missing_call_ids_stay_missing(self):
        kw={**self.kw,'prompts':[[{'role':'user','content':'Read it.'}]]*2,
            'completions':[[{'role':'assistant','content':None,'tool_calls':[{'type':'function','function':{'name':'read','arguments':'{}'}}]},
                {'role':'tool','content':'Returned text','name':'read'}]]*2}
        self.capture.wrap_reward(lambda **kw:[1,1])(**kw)
        from tracker.capabilities import links
        for p in self.payloads():
            r=normalize(p['document'])[0];self.assertEqual(links(r)['records'],[])
            self.assertEqual(sum(e['kind']=='action' for e in r['events']),1)

    def test_capture_failure_policy_is_explicit_and_never_changes_reward_values(self):
        rewards=[1,2];self.capture.on_error='warn';self.out.max_pending_bytes=1
        with self.assertWarnsRegex(RuntimeWarning,'no capture'):
            self.assertIs(self.capture.wrap_reward(lambda **kw:rewards)(**self.kw),rewards)
        self.assertEqual(self.capture.status()['failed_batches'],1);self.assertEqual(self.payloads(),[])
        self.capture.context=lambda:(_ for _ in ()).throw(RuntimeError('context unavailable'))
        with self.assertWarnsRegex(RuntimeWarning,'context unavailable'):
            self.assertIs(self.capture.wrap_reward(lambda **kw:rewards)(**self.kw),rewards)

    def test_reserved_clocks_bad_batch_and_invalid_last_row_fail_before_queueing(self):
        cases=[{**self.kw,'trainer_state':SimpleNamespace(global_step='6')},
            {**self.kw,'tracking_sample_id':['one']},{**self.kw,'completion_ids':[[1],[True]]},
            {**self.kw,'completions':['fine',{'invalid':'shape'}]}]
        for kw in cases:
            with self.assertRaises(InputError):self.capture.wrap_reward(lambda **kw:[1,1])(**kw)
            self.assertEqual(self.payloads(),[])
        self.capture.context=lambda:{'split':'train','generation_step':6}
        with self.assertRaisesRegex(InputError,'reserved'):self.capture.wrap_reward(lambda **kw:[1,1])(**self.kw)

    def test_atomic_enqueue_rolls_back_if_last_row_exceeds_capacity(self):
        row={'rollout_id':'a','document':{'test':1},'state':'complete'}
        self.out.log_many([row]);size=self.out.status()['pending_bytes']
        self.out.max_pending_bytes=size*2+2
        with self.assertRaises(BufferError):self.out.log_many([dict(row,rollout_id='b'),dict(row,rollout_id='c')])
        self.assertEqual([p['rollout_id'] for p in self.payloads()],['a'])
        self.assertEqual(self.out.log_many([row])[0]['duplicate'],True)

    def test_atomic_enqueue_preserves_revisions_and_lost_ack_contract(self):
        row={'rollout_id':'a','document':{'test':1},'state':'in_progress'}
        receipts=self.out.log_many([row,dict(row,state='complete'),dict(row,state='complete')])
        self.assertEqual([r['revision'] for r in receipts],[0,1,1])
        self.assertEqual([r['duplicate'] for r in receipts],[False,False,True])
        with self.assertRaises(ValueError):self.out.log_many([dict(row,rollout_id='b'),dict(row,rollout_id='c',document={'bad':float('nan')})])
        self.assertEqual(len(self.payloads()),2)


if __name__=='__main__':unittest.main()
