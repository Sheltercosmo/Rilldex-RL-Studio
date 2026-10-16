import copy
from types import SimpleNamespace
import unittest
from tracker import training_token_context as tokens, areal_capture, training_lineage
from tracker.schema import InputError
import test_training_samples as sample_fixtures
from test_training_samples import record


def context():
    return {'schema':tokens.VERSION,'tokenizer_id':'authored-vocab/1','boundary':'authored export',
        'generation':{'input_ids':[1,2],'output_ids':[3,4],'policy_versions':[7,8],'logprobs':[-.1,-.2]},
        'training':{'input_ids':[1,2,3,4],'loss_mask':[0,0,1,1],'policy_versions':[-1,-1,7,8],'logprobs':[0,0,-.1,-.2]}}


def native_like():
    c=context();g=c['generation'];t=c['training']
    interaction=SimpleNamespace(interaction_id='call-1',model_response=SimpleNamespace(
        input_tokens=g['input_ids'],output_tokens=g['output_ids'],output_versions=g['policy_versions'],output_logprobs=g['logprobs']))
    # The bridge must only read supplied tensors, never generate or tensorize.
    def forbidden():raise AssertionError('Capture invoked the exporter')
    interaction.to_tensor_dict=forbidden
    rows={'call-1':{'input_ids':[t['input_ids']],'loss_mask':[t['loss_mask']],'attention_mask':[[1,1,1,1]],
        'versions':[t['policy_versions']],'logprobs':[t['logprobs']],'rewards':[.75],'original_rewards':[1.]}}
    return {'call-1':interaction},rows


class TokenContextTests(unittest.TestCase):
    def test_equal_sequence_retains_mixed_policy_and_mask_facts(self):
        got=tokens.summarize(context())
        self.assertTrue(got['sequence_equal']);self.assertEqual(got['loss_policy_versions'],[7,8])
        self.assertEqual(got['loss_tokens'],2);self.assertIsNone(got['first_difference'])
        self.assertEqual(got['different_positions'],0)

    def test_difference_is_positional_and_includes_length_not_semantic_alignment(self):
        c=context();c['training']['input_ids']=[2,1,3,4]
        got=tokens.summarize(c);self.assertEqual(got['different_positions'],2);self.assertEqual(got['first_difference'],0)
        c=context();c['generation']['input_ids'].append(9)
        got=tokens.summarize(c);self.assertEqual(got['different_positions'],3)

    def test_missing_policy_and_empty_sequence_do_not_invent_version_zero(self):
        c=context();del c['training']['policy_versions'];got=tokens.summarize(c)
        self.assertIsNone(got['loss_policy_versions']);self.assertIsNone(got['loss_tokens_without_policy_version'])
        c=context();c['training']['policy_versions']=[-1,-1,-1,8]
        self.assertEqual(tokens.summarize(c)['loss_tokens_without_policy_version'],1)
        c=context();c['generation']={'input_ids':[],'output_ids':[]};c['training']={'input_ids':[],'loss_mask':[]}
        self.assertTrue(tokens.summarize(c)['sequence_equal'])

    def test_invalid_array_types_lengths_limits_and_nonfinite_logprobs_fail(self):
        changes=[('training','input_ids',[1,True,3,4]),('training','loss_mask',[0,1]),
            ('training','loss_mask',[0,0,1,2]),('training','policy_versions',[-1,-1,-2,8]),
            ('generation','policy_versions',[7]),('generation','logprobs',[-.1,float('nan')]),
            ('generation','output_ids',[-1]),('generation','input_ids',[0]*(tokens.MAX_TOKENS+1))]
        for part,key,value in changes:
            with self.subTest(part=part,key=key),self.assertRaises(InputError):
                c=context();c[part][key]=value;tokens.validate(c)
        for key in ['schema','boundary','tokenizer_id']:
            c=context();c[key]=''
            with self.assertRaises(InputError):tokens.validate(c)


class TokenLedgerTests(unittest.TestCase):
    setUp=sample_fixtures.IndependentSampleTests.setUp
    packet=sample_fixtures.IndependentSampleTests.packet
    add=sample_fixtures.IndependentSampleTests.add

    def test_roundtrip_keeps_raw_once_and_summary_without_inventing_source_or_use(self):
        c=context();self.add(record('sample',token_context=c,episode={'producer':'native','id':'episode'}))
        got=training_lineage.snapshot(self.store)['samples'][0]
        self.assertTrue(got['token_context_summary']['sequence_equal']);self.assertNotIn('token_context',got)
        self.assertEqual(got['records'][0]['data']['token_context'],c)
        self.assertEqual(got['episode'],{'producer':'native','id':'episode'})
        self.assertFalse(got['populations']['optimizer']);self.assertEqual(got['join_status'],'source_not_declared')

    def test_invalid_context_is_atomic_and_episode_requires_typed_reference(self):
        c=context();c['training']['loss_mask']=[0]
        with self.assertRaises(InputError):self.add(record('sample','good'),record('sample','bad',token_context=c))
        self.assertEqual(training_lineage.snapshot(self.store)['samples'],[])
        with self.assertRaises(InputError):self.add(record('sample',episode='episode'))


class AReaLBridgeTests(unittest.TestCase):
    def packet(self,interactions=None,rows=None,**kw):
        if interactions is None:interactions,rows=native_like()
        args={'producer':'worker','experiment':'experiment','episode_id':'native-episode','tokenizer_id':'authored-vocab/1',
            'boundary':'prepared export, before trainer transforms','export_style':'individual','sample_context':{'split':'train'},'upstream_commit':areal_capture.UPSTREAM_COMMIT,'capture_token_context':True}
        return areal_capture.build_packet(interactions,rows,**(args|kw))

    def test_capture_preserves_export_object_and_uses_stable_independent_identity(self):
        interactions,rows=native_like();before=copy.deepcopy(rows)
        result=self.packet(interactions,rows)
        self.assertEqual(rows,before);sample=result['records'][0]
        self.assertEqual(sample['data']['token_context']['training']['input_ids'],[1,2,3,4])
        self.assertEqual(sample['data']['episode']['id'],'native-episode')
        self.assertEqual([r['data']['value'] for r in result['records'][1:]],[.75,1.])
        self.assertEqual(result,self.packet(interactions,rows))
        self.assertNotEqual(sample['sample'],self.packet(interactions,rows,episode_id='other')['records'][0]['sample'])
        self.assertNotEqual(sample['sample'],self.packet(interactions,rows,export_style='concat')['records'][0]['sample'])
        self.assertFalse(any(r['kind'] in {'use','selection'} for r in result['records']))

    def test_default_lightweight_capture_does_not_read_or_copy_token_tensors(self):
        class UnreadableTensor:
            def detach(self):raise AssertionError('Token payload read during lightweight capture')
        interactions,rows=native_like();rows['call-1']['input_ids']=UnreadableTensor()
        interactions['call-1'].model_response=None
        result=self.packet(interactions,rows,capture_token_context=False)
        self.assertNotIn('token_context',result['records'][0]['data'])
        self.assertEqual(len(result['records']),3)

    def test_multiple_interactions_share_one_pinned_source_without_merging_scores(self):
        interactions,rows=native_like();second=copy.deepcopy(interactions['call-1']);second.interaction_id='call-2'
        interactions['call-2']=second;rows['call-2']=copy.deepcopy(rows['call-1']);rows['call-2']['rewards']=[0.]
        p=self.packet(interactions,rows,source={'producer':'env','rollout_id':'episode','revision':2})
        declarations=[r for r in p['records'] if r['kind']=='sample']
        self.assertEqual(len({r['sample']['id'] for r in declarations}),2)
        self.assertEqual(declarations[0]['data']['source'],declarations[1]['data']['source'])
        self.assertEqual([r['data']['value'] for r in p['records'] if r['kind']=='score' and r['data']['component']=='export_reward'],[.75,0.])

    def test_logical_rollout_reference_is_separate_from_row_reward(self):
        interactions,rows=native_like();interactions['call-1'].rollout_reward=2.
        p=self.packet(interactions,rows);r=p['records'][-1]
        self.assertEqual(r['data']['component'],'logical_rollout_reward_reference');self.assertEqual(r['data']['value'],2.)
        self.assertEqual(p['records'][1]['data']['value'],.75)

    def test_grouped_rollouts_must_be_split_before_claiming_one_episode(self):
        interactions,rows=native_like();other=copy.deepcopy(interactions['call-1']);other.interaction_id='other'
        interactions['other']=other;rows['other']=copy.deepcopy(rows['call-1']);other.rollout_index=1
        with self.assertRaisesRegex(InputError,'logical rollout'):self.packet(interactions,rows)
        interactions['call-1'].rollout_index=0
        with self.assertRaisesRegex(InputError,'logical rollout'):self.packet(interactions,rows)
        other.rollout_index=0;other.rollout_reward=1.;interactions['call-1'].rollout_reward=2.
        with self.assertRaisesRegex(InputError,'reward references'):self.packet(interactions,rows)

    def test_padding_is_removed_only_when_attention_is_contiguous_and_loss_is_zero(self):
        interactions,rows=native_like();r=rows['call-1']
        for key in ['input_ids','loss_mask','attention_mask','versions','logprobs']:r[key][0].append(0)
        p=self.packet(interactions,rows);self.assertEqual(p['records'][0]['data']['token_context']['training']['input_ids'],[1,2,3,4])
        r['loss_mask'][0][-1]=1
        with self.assertRaisesRegex(InputError,'Padding carries'):self.packet(interactions,rows)
        r['loss_mask'][0][-1]=0;r['attention_mask'][0]=[1,0,1,1,0]
        with self.assertRaisesRegex(InputError,'right-padded'):self.packet(interactions,rows)

    def test_unknown_pin_guessed_policy_and_invalid_spans_fail(self):
        for changes in [{'upstream_commit':'unvalidated'}, {'sample_context':{'split':'train','policy_version':'guessed'}},
            {'spans_by_interaction':[]},{'spans_by_interaction':{'call-1':[]}}, {'spans_by_interaction':{'missing':[]}}]:
            with self.subTest(changes=changes),self.assertRaises(InputError):self.packet(**changes)

    def test_missing_or_multiple_tensor_rows_are_not_flattened_into_one_sample(self):
        interactions,rows=native_like()
        with self.assertRaises(InputError):self.packet(interactions,{})
        rows['call-1']['input_ids']=[[1,2],[3,4]]
        with self.assertRaisesRegex(InputError,'exactly one tensor row'):self.packet(interactions,rows)
        interactions['call-1'].interaction_id='other'
        with self.assertRaisesRegex(InputError,'identity differs'):self.packet(interactions,rows)


if __name__=='__main__':unittest.main()
