import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker import slime_debug as sd
from tracker.adapters import normalize
from tracker.capture import Outbox
from tracker.schema import InputError


def fixture():
    samples=[dict(index=i,group_index=7,rollout_id=11,prompt='Question',response='Answer',
                  tokens=[1,2,3,4],response_length=2,loss_mask=[1,1],reward=float(i),
                  rollout_log_probs=[-.5,-.25],status='completed') for i in (100,101)]
    train=[dict(sample_index=i,rollout_position=p,data_parallel_rank=1-p,tokens=[1,2,3,4],
                total_lengths=4,response_lengths=2,loss_masks=[1,p],rollout_log_probs=[-.5,-.25],
                advantages=[1.,-1.],values=[0.,0.],returns=[1.,-1.]) for p,i in enumerate((100,101))]
    return {'rollout_id':3,'samples':samples},{'format_version':2,'rollout_id':3,'samples':list(reversed(train)),'dp_shards':[]}


def prepare(r,t):
    return sd.prepare(r,t,producer='slime-worker',experiment='rl-job',session='branch-a',tokenizer_id='test-tokens/1')


class SlimeDebugTests(unittest.TestCase):
    def test_join_native_position_not_file_order(self):
        r,t=fixture();before=copy.deepcopy((r,t));result=prepare(r,t)
        self.assertEqual((r,t),before)
        self.assertEqual(result['report']['join']['join_basis'],{'rollout_position':2})
        self.assertEqual([c['token_context']['loss_tokens'] for c in result['report']['comparisons']],[1,2])
        self.assertEqual([c['data_parallel_rank'] for c in result['report']['comparisons']],[1,0])
        self.assertEqual({rec['kind'] for p in result['packets'] for rec in p['records']},{'sample','score'})
        self.assertEqual(result['report']['training_use_receipts'],0)
        sample=result['packets'][0]['records'][0]['data']
        self.assertEqual(sample['environment'],'slime-debug')
        self.assertEqual(sample['display_name'],'Batch 3 · position 0')
        self.assertEqual(result['report']['comparisons'][0]['retained_rollout_logprobs']['max_absolute_difference'],0)

    def test_missing_and_duplicate_indexes_with_explicit_position(self):
        for indexes in [(None,None),(9,9)]:
            r,t=fixture()
            for row,idx in zip(r['samples'],indexes):row['index']=idx
            for row in t['samples']:row['sample_index']=indexes[row['rollout_position']]
            self.assertEqual(len(prepare(r,t)['report']['comparisons']),2)

    def test_index_fallback_only_unique(self):
        r,t=fixture()
        for row in t['samples']:row.pop('rollout_position')
        self.assertEqual(prepare(r,t)['report']['join']['join_basis'],{'unique_sample_index':2})
        r['samples'][0]['index']=101
        with self.assertRaisesRegex(InputError,'unambiguous'):prepare(r,t)

    def test_identity_errors_not_silent_misjoins(self):
        edits=[lambda t:t.update(rollout_id=4),lambda t:t.update(format_version=1),
               lambda t:t['samples'][0].update(sample_index=999),
               lambda t:t['samples'][0].update(rollout_position=7),
               lambda t:t['samples'].append(copy.deepcopy(t['samples'][0])),
               lambda t:t['samples'][0].update(rollout_position=None,sample_index=None)]
        for edit in edits:
            with self.subTest(edit=edit):
                r,t=fixture();edit(t)
                with self.assertRaises(InputError):prepare(r,t)

    def test_unmatched_is_not_rejection(self):
        r,t=fixture();t['samples']=t['samples'][:1];out=prepare(r,t)
        self.assertEqual(out['report']['join']['unmatched_rollout'],1)
        self.assertFalse(any(x['kind']=='selection' for p in out['packets'] for x in p['records']))
        self.assertEqual(sum('token_context' in x['data'] for p in out['packets'] for x in p['records']),1)

    def test_native_difference_is_preserved(self):
        r,t=fixture();t['samples'][0]['tokens'][2]=99;t['samples'][1]['rollout_log_probs'][1]=-.3
        out=prepare(r,t)['report']['comparisons']
        self.assertEqual(out[1]['token_context']['different_positions'],1)
        self.assertEqual(out[1]['retained_rollout_logprobs']['status'],'unavailable')
        self.assertAlmostEqual(out[0]['retained_rollout_logprobs']['max_absolute_difference'],.05)

    def test_empty_response_does_not_use_negative_zero_slice(self):
        r,t=fixture();r['samples'][0].update(response='',response_length=0,loss_mask=[],rollout_log_probs=[])
        t['samples'][1].update(response_lengths=0,loss_masks=[],rollout_log_probs=[],advantages=[],values=[],returns=[])
        s=prepare(r,t)['packets'][0]['records'][0]['data']['token_context']
        self.assertEqual(s['generation']['output_ids'],[])
        self.assertEqual(s['training']['loss_mask'],[0,0,0,0])

    def test_invalid_native_lengths_and_nonfinite_rejected(self):
        edits=[lambda t:t['samples'][0].update(response_lengths=5),
               lambda t:t['samples'][0].update(loss_masks=[1]),
               lambda t:t['samples'][0].update(advantages=[1.]),
               lambda t:t['samples'][0].update(tokens=[True,2,3,4]),
               lambda t:t['samples'][0].update(returns=[float('nan'),0]),
               lambda t:t['samples'][0].update(total_lengths=3)]
        for edit in edits:
            r,t=fixture();edit(t)
            with self.assertRaises(InputError):prepare(r,t)

    def test_sources_and_episode_identity_remain_distinct(self):
        r,t=fixture();r['samples'][0]['weight_versions']=['policy4','policy5'];out=prepare(r,t)
        samples=[x for p in out['packets'] for x in p['records'] if x['kind']=='sample']
        self.assertEqual(samples[0]['data']['episode'],samples[1]['data']['episode'])
        self.assertNotEqual(samples[0]['sample'],samples[1]['sample'])
        self.assertNotEqual(samples[0]['data']['source'],samples[1]['data']['source'])
        self.assertFalse(any('policy_history' in x['data'] or 'policy_version' in x['data'] or 'group_size' in x['data'] for x in samples))
        other=sd.prepare(r,t,producer='slime-worker',experiment='other',session='branch-a',tokenizer_id='test-tokens/1')
        self.assertNotEqual(out['snapshots'][0]['rollout_id'],other['snapshots'][0]['rollout_id'])

    def test_flattened_response_not_invented_agent_units(self):
        r,t=fixture();r['samples'][0]['response']='I search. <tool_response>answer from environment</tool_response>'
        r['samples'][0]['label']='PRIVATE REFERENCE ANSWER'
        s=prepare(r,t)['snapshots'][0];run=normalize(s['document'],s['format'],s['metadata'])[0]
        self.assertTrue(all(e['actor']!='agent' for e in run['events']))
        self.assertFalse(any('PRIVATE REFERENCE' in e['text'] for e in run['events']))
        self.assertEqual(run['events'][1]['source_pointer'],'/sample/response')

    def test_atomic_outbox_retry_and_backpressure(self):
        r,t=fixture();out=prepare(r,t)
        with tempfile.TemporaryDirectory() as tmp:
            box=Outbox(Path(tmp)/'outbox.sqlite',producer='slime-worker')
            first=sd.enqueue(box,out);second=sd.enqueue(box,out)
            self.assertEqual(len(first),3);self.assertTrue(all(x['duplicate'] for x in second))
            with box.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM queue').fetchone()[0],3)
            blocked=Outbox(Path(tmp)/'small.sqlite',producer='slime-worker',max_pending_bytes=1)
            with self.assertRaises(BufferError):sd.enqueue(blocked,out)
            with blocked.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM queue').fetchone()[0],0)

    def test_unknown_revision_and_unsafe_objects(self):
        r,t=fixture()
        with self.assertRaisesRegex(InputError,'revision'):
            sd.prepare(r,t,producer='p',experiment='e',session='s',tokenizer_id='t',upstream_commit='unknown')
        with self.assertRaises(InputError):sd.plain({'tensor':object()})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'r.json';p.write_text(json.dumps(r),encoding='utf-8')
            self.assertEqual(sd.read(p),r)


if __name__=='__main__':unittest.main()
